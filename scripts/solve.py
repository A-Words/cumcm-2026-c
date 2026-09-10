"""Run the four questions, January-only calibration, ablations and sensitivity."""
from __future__ import annotations
import json
from pathlib import Path
import time
import numpy as np
import scipy
from model import (DT, INITIAL, build_cache, q1_solution, simulate, summarize)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs'


def plain(obj):
    if isinstance(obj,np.ndarray):
        return obj.tolist()
    if isinstance(obj,np.generic):
        return obj.item()
    raise TypeError(type(obj).__name__)


def workbook_payload(data, q1, results):
    payload = dict(schemaVersion=1,slotConvention='right-end-0000-to-2400',
                   q1=dict(plan=q1['grid'],charge=q1['charge'],discharge=q1['discharge'],
                           socStart=q1['soc'][0],socEnd=q1['soc'][-1]))
    for name,result in results.items():
        days = []
        for d in range(31,365):
            row = dict(date=str(data['dates'][d]),plan=result['plan'][d],
                       planCost=result['costs'][d,0],charge=result['charge'][d],
                       discharge=result['discharge'][d],socStart=result['soc'][d,0],
                       socEnd=result['soc'][d,-1],emergency=result['emergency'][d],
                       emergencyCost=result['costs'][d,2],totalCost=result['costs'][d,3])
            if name in ('q3','q4_3'):
                row.update(adjusted=result['adjusted'][d],
                           adjustedCost=result['costs'][d,0]+result['costs'][d,1])
            days.append(row)
        payload[name] = dict(days=days)
    return payload


def main():
    started = time.perf_counter()
    OUT.mkdir(exist_ok=True)
    data = dict(np.load(ROOT/'data/processed/data.npz'))
    q1 = q1_solution(data)
    trap = q1_solution(data,trapezoid=True)
    roundtrip = q1_solution(data,eta=float(np.sqrt(.9)))
    specs = dict(q2=(False,False,()),q3=(True,False,(36,72,108)),
                 q4_2=(False,True,()),q4_3=(True,True,(36,72,108)))
    caches, selected, calibration, results = {},{},{},{}
    for name,(forecasts,dynamic,issues) in specs.items():
        print(f'Cache and January calibration: {name}',flush=True)
        cache = build_cache(data,forecast=forecasts,dynamic=dynamic)
        caches[name] = cache
        trials = []
        for tau in (0.5,0.65,0.7,0.8,0.9,0.95):
            r = simulate(data,cache,tau,issues=issues,days=31,dynamic=dynamic,warmup_quantile=None)
            score = summarize(r,start=14)
            trials.append(dict(quantile=tau,validation_cost=score['total_cost'],
                               validation_emergency_kwh=score['emergency_kwh']))
        calibration[name] = trials
        tau = min(trials,key=lambda x:x['validation_cost'])['quantile']
        selected[name] = tau
        print(f'{name} selected tau={tau}; running year',flush=True)
        result = simulate(data,cache,tau,issues=issues,dynamic=dynamic,progress=True)
        results[name] = result
        print(name,summarize(result),flush=True)

    # Write primary deliverables first so independent validation/export can run.
    payload = workbook_payload(data,q1,results)
    (OUT/'results.json').write_text(json.dumps(payload,default=plain,separators=(',',':')),encoding='utf-8')
    arrays = {f'q1_{k}':v for k,v in q1.items() if isinstance(v,np.ndarray)}
    for name,result in results.items():
        arrays.update({f'{name}_{k}':v for k,v in result.items()})
    np.savez_compressed(OUT/'dispatch.npz',**arrays)
    summary = dict(parameters=selected,calibration=calibration,
                   q1={k:v for k,v in q1.items() if np.isscalar(v)},
                   q1_grid_kwh=float(q1['grid'].sum()),
                   q1_trapezoid_cost=trap['cost'],q1_trapezoid_grid_kwh=float(trap['grid'].sum()),
                   q1_roundtrip90_cost=roundtrip['cost'],
                   primary={k:summarize(v) for k,v in results.items()},
                   sensitivity={},forecast_accuracy={},versions=dict(numpy=np.__version__,scipy=scipy.__version__))
    for name,cache in caches.items():
        err = cache.errors[31:,0]
        summary['forecast_accuracy'][name] = dict(
            net_mae_kw=float(np.mean(np.abs(err))/DT),
            load_mae_kw=float(np.mean(np.abs(cache.load[31:,0]-data['load'][31:]))),
            pv_mae_kw=float(np.mean(np.abs(cache.pv[31:,0]-data['pv'][31:]))),
            price_mae=float(np.mean(np.abs(cache.price[31:,0]-(data['dynamic_price'][31:] if '4' in name else data['fixed_price'])))))
    (OUT/'summary.json').write_text(json.dumps(summary,default=plain,indent=2),encoding='utf-8')
    print('PRIMARY_READY: outputs/results.json and dispatch.npz',flush=True)

    # Same forecast/controller, varying only issued updates. Parameters remain frozen.
    for name,issues in [('q3_midnight_only',()),('q3_update06',(36,)),
                        ('q3_update12',(72,)),('q3_update18',(108,)),
                        ('q3_update06_12',(36,72)),('q3_update06_18',(36,108)),
                        ('q3_update12_18',(72,108))]:
        print(f'Ablation {name}',flush=True)
        r = simulate(data,caches['q3'],selected['q3'],issues=issues)
        summary['sensitivity'][name] = summarize(r)
    for key in ('q2','q3'):
        for tau in (0.5,0.7,0.9):
            print(f'Risk sensitivity {key} tau={tau}',flush=True)
            issues = () if key=='q2' else (36,72,108)
            r = simulate(data,caches[key],tau,issues=issues)
            summary['sensitivity'][f'{key}_tau{tau}'] = summarize(r)
    for key in ('q3','q4_3'):
        print(f'Refund sensitivity {key}',flush=True)
        r = simulate(data,caches[key],selected[key],issues=(36,72,108),refund=True,dynamic='4' in key)
        summary['sensitivity'][f'{key}_refund'] = summarize(r)
    for terminal in (3000.0,9000.0):
        print(f'Terminal reserve sensitivity {terminal}',flush=True)
        r = simulate(data,caches['q3'],selected['q3'],issues=(36,72,108),terminal=terminal)
        summary['sensitivity'][f'q3_terminal{int(terminal)}'] = summarize(r)
    for key,forecasts,issues in [('q4_2',False,()),('q4_3',True,(36,72,108))]:
        print(f'Perfect-price reference {key}',flush=True)
        cache = build_cache(data,forecast=forecasts,dynamic=True,oracle_price=True)
        r = simulate(data,cache,selected[key],issues=issues,dynamic=True)
        summary['sensitivity'][f'{key}_known_price'] = summarize(r)
    # Positive-price no-storage perfect-net reference: different information, no claim of bound.
    actual_net = np.maximum((data['load'][31:]-data['pv'][31:])*DT,0)
    summary['ideal_no_storage_reference'] = dict(
        fixed_cost=float(np.sum(actual_net*data['fixed_price'])),
        dynamic_cost=float(np.sum(actual_net*data['dynamic_price'][31:])),
        grid_kwh=float(actual_net.sum()))
    summary['elapsed_seconds'] = time.perf_counter()-started
    (OUT/'summary.json').write_text(json.dumps(summary,default=plain,indent=2),encoding='utf-8')
    print(f'Completed in {summary["elapsed_seconds"]:.1f}s',flush=True)


if __name__ == '__main__':
    main()
