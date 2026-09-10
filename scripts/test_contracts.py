"""Focused regression checks for final-net and per-revision purchase contracts.

Run: python scripts/test_contracts.py
"""
from __future__ import annotations

import unittest

import numpy as np

from model import (DT, ETA, HIGH, INITIAL, LIMIT, LOW, ForecastCache, optimize,
                   settle_revisions, simulate)


class FrozenContractPathTests(unittest.TestCase):
    def test_withdrawn_purchase_is_still_billed_per_revision(self):
        plan = np.array([10.0, 20.0, 30.0])
        revisions = np.array([[10., 20., 30.], [15., np.nan, 36.],
                              [12., 18., np.nan], [np.nan, 19., 30.]])
        price = np.array([1., 2., 3.])
        paid = settle_revisions(plan, revisions, price, settlement='per_revision')
        # Independent hand calculation: purchase fees 7.5+3+27, reduction fees
        # 1.5+2+9; a purchase withdrawn later cannot erase the earlier payment.
        self.assertAlmostEqual(paid['adjustment_cost'], 50.)
        np.testing.assert_allclose(paid['up'], [5., 1., 6.])
        np.testing.assert_allclose(paid['down'], [3., 2., 6.])
        np.testing.assert_allclose(paid['final'], [12., 19., 30.])
        net = settle_revisions(plan, revisions, price)
        self.assertAlmostEqual(net['adjustment_cost'], 4.)
        refund = settle_revisions(plan, revisions, price, refund=True)
        self.assertAlmostEqual(refund['adjustment_cost'], 2.)

    def test_vectorized_days_and_missing_revisions(self):
        plan = np.array([[10.], [20.]])
        revisions = np.array([[[10.], [14.], [np.nan], [10.]],
                              [[20.], [np.nan], [np.nan], [np.nan]]])
        paid = settle_revisions(plan, revisions, np.array([[2.], [3.]]),
                                settlement='per_revision')
        np.testing.assert_allclose(paid['adjustment_cost'], [16., 0.])
        np.testing.assert_allclose(paid['final'], plan)
        np.testing.assert_array_equal(paid['revision_up'][:, 0], 0.)
        np.testing.assert_array_equal(paid['revision_down'][:, 0], 0.)

    def test_mixed_contracts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'only supported with final_net'):
            settle_revisions(np.array([1.]), np.array([[1.]]), np.array([1.]),
                             settlement='per_revision', refund=True)
        with self.assertRaisesRegex(ValueError, 'only supported with final_net'):
            optimize(np.array([1.]), np.array([1.]), INITIAL,
                     settlement='per_revision', refund=True)
        with self.assertRaisesRegex(ValueError, 'only supported with final_net'):
            simulate({}, None, .8, settlement='per_revision', refund=True)


def changing_forecast_case(days=2):
    """At 06 a higher forecast is purchased; at 12 that forecast is withdrawn."""
    load = np.full((days, 144), 1200.)
    data = dict(load=load, pv=np.zeros_like(load), fixed_price=np.ones(144))
    shape = (days, 4, 144)
    net, price = np.full(shape, np.nan), np.full(shape, np.nan)
    for issue, demand in enumerate((200., 400., 50., 80.)):
        net[:, issue, issue*36:] = demand
        price[:, issue, issue*36:] = 1.
    actual = (data['load']-data['pv'])*DT
    cache = ForecastCache(net, price, actual[:, None, :]-net,
                          np.zeros(shape), np.zeros(shape))
    return data, cache


class ReoptimizedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.cache = changing_forecast_case()
        cls.result = simulate(cls.data, cls.cache, .8, days=2,
                              issues=(36, 72, 108), settlement='per_revision')

    def test_committed_purchases_cannot_be_freely_withdrawn(self):
        result = self.result
        self.assertGreater(result['revision_up'].sum(), 100.)
        self.assertLess(np.max(result['revision_down']), 1e-7)
        # The same forecast path genuinely triggers withdrawal under the old
        # final-net interpretation, so monotonicity is an exercised constraint.
        net = simulate(self.data, self.cache, .8, days=2, issues=(36, 72, 108))
        self.assertGreater(net['revision_down'].sum(), 100.)
        for day in range(2):
            previous = result['plan'][day].copy()
            for issue in range(1, 4):
                t = issue*36
                revised = result['revisions'][day, issue]
                self.assertTrue(np.all(np.isnan(revised[:t])))
                self.assertGreaterEqual(np.min(revised[t:]-previous[t:]), -1e-7)
                previous[t:] = revised[t:]
            np.testing.assert_allclose(result['adjusted'][day], previous, atol=1e-7)

    def test_future_revision_does_not_change_completed_prefix(self):
        for issues, stop in (((), 36), ((36,), 72), ((36, 72), 108)):
            earlier = simulate(self.data, self.cache, .8, days=1,
                               issues=issues, settlement='per_revision')
            for field in ('plan', 'adjusted', 'charge', 'discharge', 'emergency', 'spill'):
                np.testing.assert_allclose(self.result[field][0, :stop],
                                           earlier[field][0, :stop], atol=1e-7)
            np.testing.assert_allclose(self.result['soc'][0, :stop+1],
                                       earlier['soc'][0, :stop+1], atol=1e-7)

    def test_energy_soc_and_independently_recomputed_payment(self):
        r = self.result
        actual_net = (self.data['load']-self.data['pv'])*DT
        np.testing.assert_allclose(r['adjusted']+r['emergency']+r['discharge'],
                                   actual_net+r['charge']+r['spill'], atol=1e-7)
        np.testing.assert_allclose(np.diff(r['soc'], axis=1),
                                   ETA*r['charge']-r['discharge']/ETA, atol=1e-7)
        self.assertAlmostEqual(r['soc'][0, 0], INITIAL)
        self.assertAlmostEqual(r['soc'][1, 0], r['soc'][0, -1])
        self.assertGreaterEqual(r['soc'].min(), LOW-1e-7)
        self.assertLessEqual(r['soc'].max(), HIGH+1e-7)
        self.assertLessEqual(max(r['charge'].max(), r['discharge'].max()), LIMIT+1e-7)
        # Reconstruct the ledger directly from snapshots, without using the
        # settlement helper or trusting its stored delta arrays.
        for day in range(2):
            previous = r['plan'][day].copy()
            fees = 0.
            for issue in range(1, 4):
                t = issue*36
                next_grid = r['revisions'][day, issue, t:]
                change = next_grid-previous[t:]
                fees += np.sum(1.5*np.maximum(change, 0)+.5*np.maximum(-change, 0))
                previous[t:] = next_grid
            self.assertAlmostEqual(r['costs'][day, 1], fees, places=7)
            self.assertAlmostEqual(r['costs'][day, 3],
                                   r['plan'][day].sum()+fees+5*r['emergency'][day].sum(),
                                   places=7)


class WarmupCacheTests(unittest.TestCase):
    def test_january_replays_fixed_warmup_then_february_uses_candidate(self):
        data, warmup = changing_forecast_case(days=32)
        _, candidate = changing_forecast_case(days=32)
        candidate.net *= 1.7
        # Isolate cache selection from risk-quantile adaptation in this fixture.
        candidate.errors.fill(0.)
        warmup.errors.fill(0.)
        saved_errors = candidate.errors.copy()
        fixed = simulate(data, warmup, .8, days=32, issues=(36, 72, 108))
        switched = simulate(data, candidate, .8, days=32, issues=(36, 72, 108),
                            warmup_cache=warmup)
        for field in ('plan', 'adjusted', 'charge', 'discharge', 'emergency',
                      'spill', 'soc', 'costs', 'revisions'):
            np.testing.assert_allclose(switched[field][:31], fixed[field][:31],
                                       atol=1e-7, equal_nan=True)
        self.assertGreater(np.max(np.abs(switched['plan'][31]-fixed['plan'][31])), 1.)
        np.testing.assert_array_equal(candidate.errors, saved_errors)


if __name__ == '__main__':
    unittest.main(verbosity=2)
