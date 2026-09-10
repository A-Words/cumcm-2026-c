"""Price-aware, fixed-purchase battery feedback benchmark.

The production nominations and its forecast model are unchanged. A feedback LP
can allocate existing battery energy to predicted expensive deficits, but cannot
buy regular power or charge from emergency purchases. Only the first action is
executed. Its horizon stops at midnight with no terminal value; this is a causal
benchmark, not a proof of annual or stochastic optimality.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

from model import (DT, ETA, HIGH, INITIAL, LIMIT, LOW, execute_slot, optimize,
                   risk_forecast, settle_revisions)


@lru_cache(maxsize=144)
def feedback_structure(n):
    """Battery transitions for x = [charge, discharge, state_after_slot]."""
    matrix = lil_matrix((n, 3*n))
    for t in range(n):
        matrix[t, t] = -ETA
        matrix[t, n+t] = 1/ETA
        matrix[t, 2*n+t] = 1
        if t:
            matrix[t, 2*n+t-1] = -1
    return matrix.tocsr()


def solve_feedback(net, price, grid, soc):
    """Minimize 5 * price * emergency for a fixed delivery commitment.

    Inputs are AC kWh and yuan/kWh for the remaining slots. For each slot,
    charge <= max(grid-net, 0), discharge <= max(net-grid, 0); emergency is
    exactly the residual deficit. Thus emergency supply cannot charge a battery,
    and charge/discharge cannot occur simultaneously. Terminal SOC is only
    constrained by the physical lower bound, without an assigned salvage value.
    """
    net, price, grid = (np.asarray(value, dtype=float) for value in (net, price, grid))
    if (net.ndim != 1 or price.shape != net.shape or grid.shape != net.shape
            or not len(net) or not np.all(np.isfinite(np.r_[net, price, grid, soc]))):
        raise ValueError('net, price and grid must be finite, equal-length nonempty vectors')
    if np.any(price < 0) or np.any(grid < -1e-7):
        raise ValueError('feedback requires nonnegative prices and commitments')
    if not LOW-1e-7 <= soc <= HIGH+1e-7:
        raise ValueError('initial SOC is outside physical limits')
    soc = float(np.clip(soc, LOW, HIGH))
    n = len(net)
    surplus = np.maximum(grid-net, 0)
    deficit = np.maximum(net-grid, 0)
    lower = np.r_[np.zeros(2*n), np.full(n, LOW)]
    upper = np.r_[np.minimum(surplus, LIMIT), np.minimum(deficit, LIMIT),
                  np.full(n, HIGH)]
    objective = np.r_[np.zeros(n), -5*price, np.zeros(n)]
    matrix = feedback_structure(n)
    rhs = np.r_[soc, np.zeros(n-1)]
    answer = linprog(objective, A_eq=matrix, b_eq=rhs,
                     bounds=np.c_[lower, upper], method='highs')
    if not answer.success:
        raise RuntimeError(f'Feedback LP failed: {answer.message}; n={n}, soc={soc}')
    charge = answer.x[:n]
    discharge = answer.x[n:2*n]
    emergency = np.maximum(deficit-discharge, 0)
    return dict(grid=grid.copy(), charge=charge, discharge=discharge,
                emergency=emergency, spill=np.maximum(surplus-charge, 0),
                soc=np.r_[soc, answer.x[2*n:]],
                objective=float(5*price@emergency),
                primal_residual=float(np.max(np.abs(matrix@answer.x-rhs))))


def execute_feedback(grid, net, price, soc):
    """Execute one economically optimal action for the supplied forecast horizon.

    Free surplus should always be stored up to physical limits: holding more
    energy cannot increase future emergency expense. With no available discharge
    the action is forced. If today's first price is at least every later price,
    using available energy now is also optimal (future prices are nonnegative).
    These dominance shortcuts avoid unnecessary LPs and retain free surplus even
    where the zero-terminal-value LP has multiple optimal solutions.
    """
    if (grid[0] >= net[0] or soc <= LOW+1e-9
            or price[0] >= np.max(price)):
        return execute_slot(grid[0], net[0], soc)
    solution = solve_feedback(net, price, grid, soc)
    return (solution['charge'][0], solution['discharge'][0], solution['soc'][1],
            solution['emergency'][0], solution['spill'][0])


def simulate_feedback(data, cache, quantile, issues=(), days=365, initial=INITIAL,
                      dynamic=False, settlement='final_net', warmup_cache=None,
                      start_day=0, feedback='mpc', feedback_start_day=31,
                      warmup_quantile=.8, terminal=INITIAL, progress=False):
    """Replay production nominations with a different causal execution policy.

    ``days`` is the absolute exclusive end day; returned arrays have
    ``days-start_day`` rows. ``initial`` is the actual SOC at ``start_day``.
    Day numbers passed to forecasts remain absolute. By default January uses the
    original greedy policy, so a full replay shares the production February SOC.
    No extra release is consumed: between permitted nomination issues, the
    latest permitted net/price forecast is retained and only its current slot is
    replaced by realized net load and the observed current tariff. The residual
    regular commitments are fixed inside each feedback LP. Later nomination
    revisions still use their own actual SOC and the production contract rules.
    """
    if feedback not in ('mpc', 'greedy'):
        raise ValueError("feedback must be 'mpc' or 'greedy'")
    if settlement not in ('final_net', 'per_revision'):
        raise ValueError(f'Unknown settlement: {settlement}')
    if not 0 <= start_day < days <= len(data['load']):
        raise ValueError('require 0 <= start_day < days <= number of data days')
    if any(t not in (36, 72, 108) for t in issues) or len(set(issues)) != len(issues):
        raise ValueError('issues must be a subset of (36, 72, 108)')
    shape = (days-start_day, 144)
    plan, adjusted, charge, discharge, emergency, spill = [np.zeros(shape) for _ in range(6)]
    state = np.zeros((days-start_day, 145))
    revisions = np.full((days-start_day, 4, 144), np.nan)
    revision_up, revision_down = np.zeros_like(revisions), np.zeros_like(revisions)
    daily_costs = np.zeros((days-start_day, 4))
    soc = initial
    for row, day in enumerate(range(start_day, days)):
        active_cache = warmup_cache if day < 31 and warmup_cache is not None else cache
        active_quantile = warmup_quantile if day < 31 and warmup_quantile is not None else quantile
        latest_issue = 0
        forecast_net = risk_forecast(active_cache, day, 0, active_quantile)
        forecast_price = active_cache.price[day, 0]
        solution = optimize(forecast_net, forecast_price, soc, terminal=terminal)
        plan[row] = solution['grid']
        adjusted[row] = plan[row]
        revisions[row, 0] = plan[row]
        state[row, 0] = soc
        for t in range(144):
            if t in issues:
                latest_issue = t//36
                forecast_net = risk_forecast(active_cache, day, latest_issue, active_quantile)
                forecast_price = active_cache.price[day, latest_issue, t:]
                base = adjusted[row, t:] if settlement == 'per_revision' else plan[row, t:]
                solution = optimize(forecast_net, forecast_price, soc, base=base,
                                    terminal=terminal, settlement=settlement)
                adjusted[row, t:] = solution['grid']
                revisions[row, latest_issue, t:] = solution['grid']
            net_actual = (data['load'][day, t]-data['pv'][day, t])*DT
            if feedback == 'greedy' or day < feedback_start_day:
                c, d, soc, e, w = execute_slot(adjusted[row, t], net_actual, soc)
            else:
                offset = t-latest_issue*36
                current_net = forecast_net[offset:].copy()
                current_price = forecast_price[offset:].copy()
                current_net[0] = net_actual
                current_price[0] = (data['dynamic_price'][day, t] if dynamic
                                    else data['fixed_price'][t])
                c, d, soc, e, w = execute_feedback(adjusted[row, t:], current_net,
                                                  current_price, soc)
            charge[row, t], discharge[row, t], emergency[row, t], spill[row, t] = c, d, e, w
            state[row, t+1] = soc
        price = data['dynamic_price'][day] if dynamic else data['fixed_price']
        billed = settle_revisions(plan[row], revisions[row], price, settlement=settlement)
        revision_up[row], revision_down[row] = billed['revision_up'], billed['revision_down']
        basecost = price@plan[row]
        adjcost = billed['adjustment_cost']
        emcost = 5*price@emergency[row]
        daily_costs[row] = [basecost, adjcost, emcost, basecost+adjcost+emcost]
        if progress and (day+1) % 60 == 0:
            print(f'  feedback day {day+1}: cost {daily_costs[:row+1, 3].sum():,.0f}', flush=True)
    return dict(plan=plan, adjusted=adjusted, charge=charge, discharge=discharge,
                emergency=emergency, spill=spill, soc=state, revisions=revisions,
                revision_up=revision_up, revision_down=revision_down, costs=daily_costs)
