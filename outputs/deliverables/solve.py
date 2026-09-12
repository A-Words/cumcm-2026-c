"""Run the four questions, January-only calibration, ablations and sensitivity."""
from __future__ import annotations
import json
from pathlib import Path
import time
import hashlib
import itertools
import numpy as np
import scipy
from model import (DT, build_cache, simulate, summarize, settle_revisions)

from q1 import solve as solve_q1
from q2 import solve as solve_q2
from q3 import solve as solve_q3
from q4 import solve as solve_q4
from solve_common import SolveContext, PV_WEIGHTS, plain

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs'


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
    (OUT/'main').mkdir(parents=True, exist_ok=True)
    (OUT/'experiments/revision').mkdir(parents=True, exist_ok=True)
    data = dict(np.load(ROOT/'data/processed/data.npz'))
    variants = solve_q1(data)
    q1, trap, roundtrip = (variants[key] for key in ('q1', 'q1_trapezoid', 'q1_roundtrip90'))
    context = SolveContext(data)
    solve_q2(context)
    solve_q3(context)
    solve_q4(context)
    caches, selected = context.caches, context.selected
    calibration, results, weights = context.calibration, context.results, context.weights
    archived, revision = context.archived, context.revision
    cache_for, calibrate, scene = context.cache_for, context.calibrate, context.scene

    summary = dict(parameters=selected,calibration=calibration,
                   pv_weights=weights,revision_experiments='../experiments/revision/experiments.json',
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
    # Controlled information experiments: current observations and update permissions
    # remain available, only receipt of each new hourly forecast is switched.
    for group,weight,tau,warmup in [('legacy',1.0,revision['scenes']['q3_legacy']['quantile'],'self'),
                                  ('selected',weights['q3'],selected['q3'],'attachment3_fixed')]:
        subset_ids=[]
        for bits in itertools.product((0,1),repeat=3):
            sources=[0]
            for issue,enabled in enumerate(bits,1):
                sources.append(issue if enabled else sources[-1])
            if all(bits):
                scene_id='q3_'+group
            else:
                bitstr=''.join(map(str,bits)); scene_id=f'q3_{group}_info_{bitstr}'
                scene(scene_id,'新小时预报 '+bitstr,weight,tau,sources=tuple(sources),warmup_mode=warmup)
            subset_ids.append(scene_id)
        revision['information_ablation'][group]=dict(hourly_subsets=subset_ids)

    legacy_tau=revision['scenes']['q3_legacy']['quantile']
    scene('q3_legacy_no_updates','仅00点计划，无日内重规划',1.0,legacy_tau,issues=())
    scene('q3_ladder_replan','开放重规划与实际SOC，沿用日前负荷与PV',1.0,legacy_tau,
          sources=(0,0,0,0),load_update=False,anchor_updates=False)
    scene('q3_ladder_load','再增加已观测负荷修正',1.0,legacy_tau,
          sources=(0,0,0,0),anchor_updates=False)
    revision['information_ablation']['legacy']['ladder']=[
        'q3_legacy_no_updates','q3_ladder_replan','q3_ladder_load','q3_legacy_info_000','q3_legacy']

    for name,dynamic,without in [('q3',False,'q2'),('q4_3',True,'q4_2')]:
        contract={}
        price=data['dynamic_price'] if dynamic else data['fixed_price']
        for kind,scene_id in [('legacy',name+'_legacy'),('selected',name+'_selected')]:
            frozen=archived[scene_id]
            billed=settle_revisions(frozen['plan'],frozen['revisions'],price,settlement='per_revision')
            extra=float(billed['adjustment_cost'][31:].sum()-frozen['costs'][31:,1].sum())
            frozen_total=summarize(frozen)['total_cost']+extra
            contract['frozen_'+kind]=dict(scene_id=scene_id,extra_cost=extra,total_cost=frozen_total,
                withdrawn_kwh=float(billed['revision_down'][31:].sum()),
                saving_vs_without_adjustment=summarize(results[without])['total_cost']-frozen_total,
                reoptimized=False)
        print(f'Per-revision contract: January calibration {name}',flush=True)
        fit=calibrate(dynamic,PV_WEIGHTS,settlement='per_revision')
        choice=fit['selected']; scene_id=name+'_per_revision'
        scene(scene_id,'逐笔合约重新优化',choice['pv_weight'],choice['quantile'],dynamic=dynamic,
              settlement='per_revision',warmup_mode='attachment3_fixed')
        contract.update(selection=fit,reoptimized=scene_id)
        revision['contracts'][name]=contract

    # Same forecast/controller, varying only issued updates. Parameters remain frozen.
    for name,issues in [('q3_midnight_only',()),('q3_update06',(36,)),
                        ('q3_update12',(72,)),('q3_update18',(108,)),
                        ('q3_update06_12',(36,72)),('q3_update06_18',(36,108)),
                        ('q3_update12_18',(72,108))]:
        print(f'Ablation {name}',flush=True)
        r = simulate(data,caches['q3'],selected['q3'],issues=issues,warmup_cache=cache_for(False,1.0))
        summary['sensitivity'][name] = summarize(r)
    for key in ('q2','q3'):
        for tau in (0.5,0.7,0.9):
            print(f'Risk sensitivity {key} tau={tau}',flush=True)
            issues = () if key=='q2' else (36,72,108)
            r = simulate(data,caches[key],tau,issues=issues,
                         warmup_cache=cache_for(False,1.0) if key=='q3' else None)
            summary['sensitivity'][f'{key}_tau{tau}'] = summarize(r)
    for key in ('q3','q4_3'):
        print(f'Refund sensitivity {key}',flush=True)
        r = simulate(data,caches[key],selected[key],issues=(36,72,108),refund=True,dynamic='4' in key,
                     warmup_cache=cache_for('4' in key,1.0))
        summary['sensitivity'][f'{key}_refund'] = summarize(r)
    for terminal in (3000.0,9000.0):
        print(f'Terminal reserve sensitivity {terminal}',flush=True)
        r = simulate(data,caches['q3'],selected['q3'],issues=(36,72,108),terminal=terminal,
                     warmup_cache=cache_for(False,1.0))
        summary['sensitivity'][f'q3_terminal{int(terminal)}'] = summarize(r)
    for key,forecasts,issues in [('q4_2',False,()),('q4_3',True,(36,72,108))]:
        print(f'Perfect-price reference {key}',flush=True)
        cache = build_cache(data,forecast=forecasts,dynamic=True,oracle_price=True,pv_weight=weights[key])
        warm=build_cache(data,forecast=True,dynamic=True,oracle_price=True) if forecasts else None
        r = simulate(data,cache,selected[key],issues=issues,dynamic=True,warmup_cache=warm)
        summary['sensitivity'][f'{key}_known_price'] = summarize(r)
    # Positive-price no-storage perfect-net reference: different information, no claim of bound.
    actual_net = np.maximum((data['load'][31:]-data['pv'][31:])*DT,0)
    summary['ideal_no_storage_reference'] = dict(
        fixed_cost=float(np.sum(actual_net*data['fixed_price'])),
        dynamic_cost=float(np.sum(actual_net*data['dynamic_price'][31:])),
        grid_kwh=float(actual_net.sum()))
    summary['elapsed_seconds'] = time.perf_counter()-started
    revision['source_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
        for p in ('scripts/model.py','scripts/solve.py','scripts/solve_common.py',
                  'scripts/q1.py','scripts/q2.py','scripts/q3.py','scripts/q4.py','data/processed/data.npz','docs/reviews/revision-plan.md')}
    # Publish one coherent generation after every scenario is complete.
    payload = workbook_payload(data,q1,results)
    (OUT/'main/results.json').write_text(json.dumps(payload,default=plain,separators=(',',':')),encoding='utf-8')
    arrays = {f'q1_{k}':v for k,v in q1.items() if isinstance(v,np.ndarray)}
    for name,result in results.items():
        arrays.update({f'{name}_{k}':v for k,v in result.items()})
    np.savez_compressed(OUT/'main/dispatch.npz',**arrays)
    np.savez_compressed(OUT/'experiments/revision/dispatch.npz',**{
        f'{name}_{k}':v for name,result in archived.items() for k,v in result.items()})
    (OUT/'experiments/revision/experiments.json').write_text(json.dumps(revision,default=plain,indent=2),encoding='utf-8')
    (OUT/'main/summary.json').write_text(json.dumps(summary,default=plain,indent=2),encoding='utf-8')
    print(f'Completed in {summary["elapsed_seconds"]:.1f}s',flush=True)


if __name__ == '__main__':
    main()
