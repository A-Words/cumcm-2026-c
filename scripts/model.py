"""Causal forecasts, risk-quantile linear planning and feasible battery feedback.

All power input is kW; optimization and execution variables are AC-side kWh.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix, csr_matrix, hstack

DT = 1 / 6
ETA = 0.9
LOW, HIGH, INITIAL = 1200.0, 10800.0, 6000.0
LIMIT = 5000 * DT


@lru_cache(maxsize=8)
def lp_structure(n, eta=ETA):
    # x = [grid, charge, discharge, state_after_slot, unused_energy]
    a = lil_matrix((2 * n, 5 * n))
    for t in range(n):
        a[t, t], a[t, n+t], a[t, 2*n+t], a[t, 4*n+t] = 1, -1, 1, -1
        a[n+t, n+t], a[n+t, 2*n+t], a[n+t, 3*n+t] = -eta, 1/eta, 1
        if t:
            a[n+t, 3*n+t-1] = -1
    return a.tocsr()


def optimize(net, price, soc, base=None, refund=False, terminal=INITIAL, tie_break=True,
             terminal_equal=False, eta=ETA):
    """Deterministic LP. base is the ORIGINAL midnight nomination for delivery slots."""
    net, price = np.asarray(net, float), np.asarray(price, float)
    n = len(net)
    a = lp_structure(n,eta)
    b = np.r_[net, soc, np.zeros(n-1)]
    cost = np.zeros(5*n)
    cost[:n] = price if base is None else 1.5 * price
    if tie_break:
        cost[n:3*n] = 1e-6
        cost[4*n:] = 1e-7
    lower = np.zeros(5*n)
    upper = np.full(5*n, np.inf)
    lower[3*n:4*n], upper[3*n:4*n] = LOW, HIGH
    upper[n:3*n] = LIMIT
    lower[4*n-1] = terminal
    if terminal_equal:
        upper[4*n-1] = terminal
    if base is not None and not refund:
        lower[:n] = base
    aub, bub = None, None
    if base is not None and refund:
        # q=base+up-down; cost=1.5*p*up-0.5*p*down.
        m = lil_matrix((n, 7*n))
        for t in range(n):
            m[t,t], m[t,5*n+t], m[t,6*n+t] = 1, -1, 1
        from scipy.sparse import vstack
        a = vstack([hstack([a, csr_matrix((2*n,2*n))]), m.tocsr()]).tocsr()
        b = np.r_[b, base]
        cost[:n] = 0
        cost = np.r_[cost, 1.5*price, -0.5*price]
        lower = np.r_[lower, np.zeros(2*n)]
        upper = np.r_[upper, np.full(n,np.inf), base]
    result = linprog(cost, A_eq=a, b_eq=b, bounds=np.c_[lower,upper], method='highs')
    if not result.success:
        raise RuntimeError(f'LP failed: {result.message}; n={n}, soc={soc}')
    x = result.x
    return dict(grid=x[:n], charge=x[n:2*n], discharge=x[2*n:3*n],
                soc=np.r_[soc,x[3*n:4*n]], spill=x[4*n:5*n],
                objective=float(result.fun), primal_residual=float(np.max(np.abs(a@x-b))))


def q1_solution(data, trapezoid=False, eta=ETA):
    suffix = '_trapezoid' if trapezoid else ''
    net = (data['q1_load'+suffix]-data['q1_pv'+suffix])*DT
    sol = optimize(net, data['fixed_price'], INITIAL, terminal_equal=True,eta=eta)
    exact = optimize(net, data['fixed_price'], INITIAL, tie_break=False, terminal_equal=True,eta=eta)
    sol['cost'] = float(sol['grid']@data['fixed_price'])
    sol['unperturbed_lower_bound'] = float(exact['grid']@data['fixed_price'])
    sol['optimality_gap_yuan'] = sol['cost']-sol['unperturbed_lower_bound']
    sol['net'] = net
    return sol


def weighted_profile(history, day, weekly=True):
    """Recent same-weekday profiles. No actual from day or later is read."""
    if day == 0:
        # Explicit cold-start prior; only January initialization is affected.
        return np.full(144, 4500.0) if weekly else np.zeros(144)
    if weekly and day >= 7:
        idx = np.arange(day-7, max(-1,day-29), -7)
        weights = 0.55 ** np.arange(len(idx))
    else:
        idx = np.arange(day-1, max(-1,day-8), -1)
        weights = 0.8 ** np.arange(len(idx))
    return np.average(history[idx], axis=0, weights=weights)


def historical_pv(history, day):
    if day == 0:
        return np.zeros(144)
    idx = np.arange(day-1, max(-1,day-8), -1)
    return np.average(history[idx], axis=0, weights=0.75**np.arange(len(idx)))


def point_forecast(data, day, issue, use_forecast, dynamic=False, oracle_price=False):
    start = issue*36
    load = weighted_profile(data['load'], day)
    if start:
        # Issue-time load update uses only completed 10-minute slots.
        recent = slice(max(0,start-18),start)
        ratio = np.mean(data['load'][day,recent])/max(np.mean(load[recent]),1)
        load = load*np.clip(ratio,0.75,1.25)
    pv = (data['forecast'][day,issue,:144-start] if use_forecast
          else historical_pv(data['pv'],day)[start:])
    if not dynamic:
        price = data['fixed_price'][start:]
    elif oracle_price:
        price = data['dynamic_price'][day,start:]
    elif day == 0:
        price = data['fixed_price'][start:]
    else:
        price = weighted_profile(data['dynamic_price'],day)
        if start:
            recent = slice(max(0,start-18),start)
            ratio = np.mean(data['dynamic_price'][day,recent])/max(np.mean(price[recent]),0.01)
            price = price*np.clip(ratio,0.5,1.5)
        price = np.maximum(price[start:],0.001)
    return (load[start:]-pv)*DT, np.asarray(price), load[start:], pv


@dataclass
class ForecastCache:
    net: np.ndarray
    price: np.ndarray
    errors: np.ndarray
    load: np.ndarray
    pv: np.ndarray


def build_cache(data, forecast=False, dynamic=False, oracle_price=False):
    shape = (365,4,144)
    net, price, errors, load, pv = [np.full(shape,np.nan) for _ in range(5)]
    actual = (data['load']-data['pv'])*DT
    for day in range(365):
        for issue in range(4):
            t = issue*36
            z,p,l,v = point_forecast(data,day,issue,forecast,dynamic,oracle_price)
            net[day,issue,t:],price[day,issue,t:] = z,p
            load[day,issue,t:],pv[day,issue,t:] = l,v
            errors[day,issue,t:] = actual[day,t:]-z
    return ForecastCache(net,price,errors,load,pv)


def risk_forecast(cache, day, issue, quantile):
    start = issue*36
    net = cache.net[day,issue,start:].copy()
    # Stored future errors are excluded explicitly. First 7 days are warmup only.
    lo = max(7,day-28)
    if day > lo:
        past_errors = cache.errors[lo:day,issue,start:]
        # Pool 7 neighboring delivery slots to stabilize small-sample quantiles.
        pad = np.pad(past_errors,((0,0),(3,3)),mode='edge')
        samples = np.concatenate([pad[:,j:j+len(net)] for j in range(7)],axis=0)
        net += np.quantile(samples,quantile,axis=0)
    return net


def execute_slot(grid, net, soc):
    surplus = grid-net
    if surplus >= 0:
        charge = min(surplus,LIMIT,max(0,(HIGH-soc)/ETA))
        return charge,0.0,soc+ETA*charge,0.0,surplus-charge
    discharge = min(-surplus,LIMIT,max(0,(soc-LOW)*ETA))
    return 0.0,discharge,soc-discharge/ETA,-surplus-discharge,0.0


def simulate(data, cache, quantile, issues=(), refund=False, days=365, initial=INITIAL,
             dynamic=False, progress=False, warmup_quantile=0.8, terminal=INITIAL):
    shape = (days,144)
    plan, adjusted, charge, discharge, emergency, spill = [np.zeros(shape) for _ in range(6)]
    state = np.zeros((days,145))
    revisions = np.full((days,4,144),np.nan)
    daily_costs = np.zeros((days,4))  # original plan, adjustment, emergency, total
    soc = initial
    for day in range(days):
        active_quantile = warmup_quantile if day < 31 and warmup_quantile is not None else quantile
        base_net = risk_forecast(cache,day,0,active_quantile)
        sol = optimize(base_net,cache.price[day,0],soc,terminal=terminal)
        plan[day] = sol['grid']
        adjusted[day] = plan[day]
        revisions[day,0] = plan[day]
        state[day,0] = soc
        for t in range(144):
            if t in issues:
                issue = t//36
                net = risk_forecast(cache,day,issue,active_quantile)
                sol = optimize(net,cache.price[day,issue,t:],soc,base=plan[day,t:],refund=refund,terminal=terminal)
                adjusted[day,t:] = sol['grid']
                revisions[day,issue,t:] = sol['grid']
            net_actual = (data['load'][day,t]-data['pv'][day,t])*DT
            c,d,soc,e,w = execute_slot(adjusted[day,t],net_actual,soc)
            charge[day,t],discharge[day,t],emergency[day,t],spill[day,t] = c,d,e,w
            state[day,t+1] = soc
        price = data['dynamic_price'][day] if dynamic else data['fixed_price']
        down,up = np.maximum(plan[day]-adjusted[day],0),np.maximum(adjusted[day]-plan[day],0)
        basecost = price@plan[day]
        adjcost = price@((-.5 if refund else .5)*down+1.5*up)
        emcost = 5*price@emergency[day]
        daily_costs[day] = [basecost,adjcost,emcost,basecost+adjcost+emcost]
        if progress and (day+1)%60 == 0:
            print(f'  day {day+1}: cumulative cost {daily_costs[:day+1,3].sum():,.0f}',flush=True)
    return dict(plan=plan,adjusted=adjusted,charge=charge,discharge=discharge,
                emergency=emergency,spill=spill,soc=state,revisions=revisions,costs=daily_costs)


def summarize(result, start=31, end=None):
    sl = slice(start,end)
    costs = result['costs'][sl].sum(0)
    return dict(plan_kwh=float(result['plan'][sl].sum()),
                adjusted_kwh=float(result['adjusted'][sl].sum()),
                emergency_kwh=float(result['emergency'][sl].sum()),
                spill_kwh=float(result['spill'][sl].sum()),
                charge_kwh=float(result['charge'][sl].sum()),
                discharge_kwh=float(result['discharge'][sl].sum()),
                plan_cost=float(costs[0]),adjustment_cost=float(costs[1]),
                emergency_cost=float(costs[2]),total_cost=float(costs[3]),
                start_soc=float(result['soc'][start,0]),end_soc=float(result['soc'][sl][-1,-1]),
                emergency_days=int(np.sum(np.any(result['emergency'][sl]>1e-7,axis=1))))
