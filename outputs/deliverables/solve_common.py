from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
from model import build_cache, simulate, summarize

ROOT = Path(__file__).resolve().parents[1]
QUANTILES = (0.5,0.65,0.7,0.8,0.9,0.95)
PV_WEIGHTS = (0.0,0.25,0.5,0.75,1.0)


class SolveContext:

    def __init__(self, data):
        self.data = data
        self.caches, self.selected, self.calibration, self.results, self.weights = {},{},{},{},{}
        self.memo, self.archived = {},{}
        self.revision = dict(schema_version=1,selection={},scenes={},baselines={},
                        information_ablation={},contracts={},
                        validation_days=[14,31],submission_days=[31,365],
                        candidate_family_post_review=True,
                        warmup=dict(quantile=0.8,pv_weight=1.0,ends_before_day=31,
                                    applies_to='scenes with warmup_mode=attachment3_fixed'))

    def cache_for(self,dynamic=False,weight=1.0,sources=(0,1,2,3),load_update=True,anchor_updates=True):
        key=(dynamic,weight,tuple(sources),load_update,anchor_updates)
        if key not in self.memo:
            self.memo[key]=build_cache(self.data,forecast=True,dynamic=dynamic,pv_weight=weight,
                                  forecast_sources=sources,load_update=load_update,
                                  anchor_updates=anchor_updates)
        return self.memo[key]

    def calibrate(self,dynamic,weight_candidates,issues=(36,72,108),settlement='final_net'):
        trials=[]
        for weight in weight_candidates:
            for tau in QUANTILES:
                r=simulate(self.data,self.cache_for(dynamic,weight),tau,issues=issues,days=31,
                           dynamic=dynamic,warmup_quantile=None,settlement=settlement)
                score=summarize(r,start=14)
                trials.append(dict(pv_weight=weight,quantile=tau,
                                   validation_cost=score['total_cost'],
                                   validation_emergency_kwh=score['emergency_kwh']))
        choice=min(trials,key=lambda x:(x['validation_cost'],x['pv_weight'],x['quantile']))
        return dict(selected=choice,candidates=trials)

    def scene(self,scene_id,label,weight,tau,dynamic=False,issues=(36,72,108),
              sources=(0,1,2,3),load_update=True,anchor_updates=True,
              settlement='final_net',warmup_mode='self'):
        print(f'Scene {scene_id}: w={weight}, tau={tau}, {settlement}',flush=True)
        cache=self.cache_for(dynamic,weight,sources,load_update,anchor_updates)
        warm=self.cache_for(dynamic,1.0) if warmup_mode=='attachment3_fixed' else None
        r=simulate(self.data,cache,tau,issues=issues,dynamic=dynamic,settlement=settlement,
                   warmup_cache=warm)
        self.archived[scene_id]=r
        self.revision['scenes'][scene_id]=dict(label=label,pv_weight=weight,quantile=tau,
            issues=list(issues),dynamic=dynamic,settlement=settlement,
            forecast_sources=list(sources),load_update=load_update,anchor_updates=anchor_updates,
            warmup_mode=warmup_mode,soc_observation='own_actual',summary=summarize(r))
        return r


def plain(obj):
    if isinstance(obj,np.ndarray):
        return obj.tolist()
    if isinstance(obj,np.generic):
        return obj.item()
    raise TypeError(type(obj).__name__)


def run_question(name, solve):
    parser = argparse.ArgumentParser(description=f"Solve {name} independently")
    parser.add_argument('--data', type=Path, default=ROOT/'data/processed/data.npz')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/questions'/name)
    args = parser.parse_args()
    with np.load(args.data, allow_pickle=False) as source:
        data = dict(source)
    context = SolveContext(data)
    if name == 'q1':
        results = solve(data)
        summary = {key: {k: v for k, v in result.items() if np.isscalar(v)}
                   for key, result in results.items()}
    else:
        solve(context)
        results = context.results
        summary = dict(parameters=context.selected, pv_weights=context.weights,
                       calibration=context.calibration,
                       primary={key: summarize(value) for key, value in results.items()},
                       revision=context.revision)
    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output/'dispatch.npz', **{
        f'{name}_{key}': value for name, result in results.items()
        for key, value in result.items()})
    (args.output/'summary.json').write_text(
        json.dumps(summary, default=plain, indent=2), encoding='utf-8')
    if context.archived:
        np.savez_compressed(args.output/'revision-dispatch.npz', **{
            f'{name}_{key}': value for name, result in context.archived.items()
            for key, value in result.items()})
    print(f'Completed {name}: {args.output}', flush=True)
