"""Focused economic, information-boundary and replay tests for feedback.py.

Run: python scripts/test_feedback.py
"""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import numpy as np

from feedback import execute_feedback, simulate_feedback, solve_feedback
from model import DT, ETA, HIGH, INITIAL, LIMIT, LOW, ForecastCache, execute_slot, simulate


def fixture(days=33):
    slots = np.arange(144)
    load = np.broadcast_to(3000+1500*np.sin(slots/10)**2, (days, 144)).copy()
    pv = np.broadcast_to(np.maximum(0, 4500*np.sin((slots-35)/90*np.pi)),
                         (days, 144)).copy()
    fixed_price = .3+.5*(slots >= 70)+.4*(slots >= 100)
    data = dict(load=load, pv=pv, fixed_price=fixed_price,
                dynamic_price=np.broadcast_to(fixed_price, (days, 144)).copy())
    actual = (load-pv)*DT
    shape = (days, 4, 144)
    net, price = np.full(shape, np.nan), np.full(shape, np.nan)
    for issue in range(4):
        start = issue*36
        net[:, issue, start:] = actual[:, start:]+[80., 150., -80., 60.][issue]
        price[:, issue, start:] = fixed_price[start:]
    cache = ForecastCache(net, price, np.zeros(shape), np.zeros(shape), np.zeros(shape))
    return data, cache


class FeedbackOptimizationTests(unittest.TestCase):
    def test_two_price_counterexample_reserves_energy_for_expensive_slot(self):
        net, price, grid = np.array([90., 90.]), np.array([1., 10.]), np.zeros(2)
        solution = solve_feedback(net, price, grid, LOW+100.)
        np.testing.assert_allclose(solution['discharge'], [0., 90.], atol=1e-7)
        self.assertAlmostEqual(solution['objective'], 450.)
        soc, greedy_cost = LOW+100., 0.
        for t in range(2):
            _, _, soc, emergency, _ = execute_slot(grid[t], net[t], soc)
            greedy_cost += 5*price[t]*emergency
        self.assertAlmostEqual(greedy_cost, 4500.)

    def test_emergency_cannot_charge_battery_for_later_arbitrage(self):
        solution = solve_feedback([20., -10., 40.], [.1, .1, 10.], [0., 0., 0.], LOW)
        np.testing.assert_allclose(solution['charge'], [0., 10., 0.], atol=1e-7)
        np.testing.assert_allclose(solution['discharge'], [0., 0., 8.1], atol=1e-7)
        np.testing.assert_allclose(solution['emergency'], [20., 0., 31.9], atol=1e-7)

    def test_shortcuts_preserve_the_deterministic_lp_objective(self):
        rng = np.random.default_rng(719)
        for mode in ('surplus', 'empty', 'largest_price'):
            for _ in range(8):
                grid = rng.uniform(0, 1000, 12)
                net = rng.uniform(100, 1400, 12)
                price = rng.uniform(.1, 1.4, 12)
                soc = rng.uniform(LOW, HIGH)
                if mode == 'surplus':
                    grid[0] = net[0]+1000.
                elif mode == 'empty':
                    soc = LOW
                else:
                    price[0] = 2.
                full = solve_feedback(net, price, grid, soc)
                _, _, next_soc, emergency, _ = execute_feedback(grid, net, price, soc)
                tail = solve_feedback(net[1:], price[1:], grid[1:], next_soc)
                self.assertAlmostEqual(full['objective'], 5*price[0]*emergency+tail['objective'],
                                       places=6)

    def test_energy_bounds_and_no_simultaneous_actions(self):
        rng = np.random.default_rng(2026)
        net, grid = rng.uniform(-900, 1600, (2, 144))
        grid = np.maximum(grid, 0)
        price = rng.uniform(.1, 1.5, 144)
        solution = solve_feedback(net, price, grid, INITIAL)
        c, d, e, w, state = (solution[key] for key in
                              ('charge', 'discharge', 'emergency', 'spill', 'soc'))
        np.testing.assert_allclose(grid+d+e, net+c+w, atol=1e-7)
        np.testing.assert_allclose(np.diff(state), ETA*c-d/ETA, atol=1e-7)
        self.assertLessEqual(max(c.max(), d.max()), LIMIT+1e-7)
        self.assertGreaterEqual(state.min(), LOW-1e-7)
        self.assertLessEqual(state.max(), HIGH+1e-7)
        self.assertLessEqual(np.max(c*d), 1e-7)
        np.testing.assert_allclose(solution['grid'], grid)
        self.assertAlmostEqual(solution['objective'], 5*price@e)


class FeedbackReplayTests(unittest.TestCase):
    def test_greedy_replay_is_identical_to_production_for_both_contracts(self):
        data, cache = fixture(days=3)
        for settlement in ('final_net', 'per_revision'):
            for dynamic in (False, True):
                old = simulate(data, cache, .65, days=3, issues=(36, 72, 108),
                               dynamic=dynamic, settlement=settlement)
                new = simulate_feedback(data, cache, .65, days=3, issues=(36, 72, 108),
                                        dynamic=dynamic, settlement=settlement, feedback='greedy')
                self.assertEqual(set(old), set(new))
                for field in old:
                    np.testing.assert_array_equal(new[field], old[field], err_msg=field)

    def test_default_january_warmup_and_absolute_day_slice(self):
        data, cache = fixture()
        warmup = copy.deepcopy(cache)
        warmup.net *= .9
        full = simulate_feedback(data, cache, .65, days=33, issues=(36, 72, 108),
                                 warmup_cache=warmup)
        old_january = simulate(data, cache, .65, days=31, issues=(36, 72, 108),
                               warmup_cache=warmup)
        for field in full:
            np.testing.assert_array_equal(full[field][:31], old_january[field], err_msg=field)
        sliced = simulate_feedback(data, cache, .65, days=33, start_day=31,
                                   initial=full['soc'][31, 0], issues=(36, 72, 108),
                                   warmup_cache=warmup)
        for field in full:
            np.testing.assert_array_equal(sliced[field], full[field][31:], err_msg=field)

    def test_future_actuals_and_unavailable_releases_do_not_change_prefix(self):
        data, cache = fixture()
        settings = dict(days=32, start_day=31, initial=LOW+500.,
                        feedback_start_day=31, dynamic=True, issues=(72,))
        original = simulate_feedback(data, cache, .65, **settings)
        changed, cache_changed = copy.deepcopy(data), copy.deepcopy(cache)
        stop = 42
        changed['load'][31, stop:] *= 5
        changed['pv'][31, stop:] *= 3
        changed['dynamic_price'][31, stop:] *= 7
        # Current/future residuals and the disabled 06 release are unavailable.
        cache_changed.errors[31:] = 1e8
        cache_changed.net[31, 1] = 1e8
        cache_changed.price[31, 1] = 1e8
        cache_changed.net[31, 2:] = 1e8
        cache_changed.price[31, 2:] = 1e8
        replay = simulate_feedback(changed, cache_changed, .65, **settings)
        for field in ('plan', 'adjusted', 'charge', 'discharge', 'emergency', 'spill'):
            np.testing.assert_array_equal(replay[field][0, :stop], original[field][0, :stop],
                                          err_msg=field)
        np.testing.assert_array_equal(replay['soc'][0, :stop+1], original['soc'][0, :stop+1])

    def test_current_realization_overrides_forecast_without_reading_future_realization(self):
        data, cache = fixture(days=1)
        data['load'][0, 0], data['pv'][0, 0] = 4321., 123.
        data['dynamic_price'][0, 0] = .876
        captured = []

        def observe(grid, net, price, soc):
            captured.append((grid.copy(), net.copy(), price.copy()))
            return execute_slot(grid[0], net[0], soc)

        with patch('feedback.execute_feedback', side_effect=observe):
            simulate_feedback(data, cache, .65, days=1, dynamic=True,
                              feedback_start_day=0, issues=(72,))
        self.assertAlmostEqual(captured[0][1][0], (4321.-123.)*DT)
        self.assertEqual(captured[0][2][0], .876)
        np.testing.assert_array_equal(captured[0][1][1:], cache.net[0, 0, 1:])
        np.testing.assert_array_equal(captured[0][2][1:], cache.price[0, 0, 1:])
        # Disabled 06 issuance changes neither net nor tariff source.
        np.testing.assert_array_equal(captured[36][1][1:], cache.net[0, 0, 37:])
        np.testing.assert_array_equal(captured[72][1][1:], cache.net[0, 2, 73:])

    def test_physics_cross_day_and_commitment_history(self):
        data, cache = fixture()
        result = simulate_feedback(data, cache, .65, start_day=31, days=33,
                                   issues=(36, 72, 108), settlement='per_revision')
        actual = (data['load'][31:33]-data['pv'][31:33])*DT
        np.testing.assert_allclose(result['adjusted']+result['emergency']+result['discharge'],
                                   actual+result['charge']+result['spill'], atol=1e-7)
        np.testing.assert_allclose(np.diff(result['soc'], axis=1),
                                   ETA*result['charge']-result['discharge']/ETA, atol=1e-7)
        self.assertAlmostEqual(result['soc'][1, 0], result['soc'][0, -1])
        self.assertGreaterEqual(result['soc'].min(), LOW-1e-7)
        self.assertLessEqual(result['soc'].max(), HIGH+1e-7)
        self.assertLessEqual(max(result['charge'].max(), result['discharge'].max()), LIMIT+1e-7)
        self.assertLessEqual(result['revision_down'].max(), 1e-7)
        for row in range(2):
            previous = result['plan'][row].copy()
            for issue in range(1, 4):
                start = issue*36
                proposed = result['revisions'][row, issue]
                self.assertTrue(np.all(np.isnan(proposed[:start])))
                self.assertGreaterEqual(np.min(proposed[start:]-previous[start:]), -1e-7)
                previous[start:] = proposed[start:]
            np.testing.assert_allclose(result['adjusted'][row], previous, atol=1e-7)
        # Removing the last revision cannot affect any earlier executed slot.
        earlier = simulate_feedback(data, cache, .65, start_day=31, days=32,
                                    issues=(36, 72), settlement='per_revision')
        for field in ('plan', 'adjusted', 'charge', 'discharge', 'emergency', 'spill'):
            np.testing.assert_array_equal(result[field][0, :108], earlier[field][0, :108])


if __name__ == '__main__':
    unittest.main(verbosity=2)
