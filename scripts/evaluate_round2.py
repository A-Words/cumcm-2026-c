"""Additional feedback and chronological evaluation; never replace main outputs.

All protocols are fixed in docs/round2-plan.md. The future-data mode extends the
historical trajectory with frozen settings; calendar separation alone does not
establish that the developer has never seen the evaluation data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from external_inputs import build_causal_cache, load_future_data
from feedback import simulate_feedback
from model import build_cache, summarize

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = (0.0, .25, .5, .75, 1.0)
QUANTILES = (.5, .65, .7, .8, .9, .95)
CONFIGS = {
    'q2': dict(dynamic=False, pv_weight=0.0, quantile=.8, issues=()),
    'q3': dict(dynamic=False, pv_weight=.5, quantile=.65, issues=(36,72,108)),
    'q4_2': dict(dynamic=True, pv_weight=0.0, quantile=.8, issues=()),
    'q4_3': dict(dynamic=True, pv_weight=.5, quantile=.65, issues=(36,72,108)),
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')


def primary_path(name):
    with np.load(ROOT/'outputs/dispatch.npz') as archive:
        prefix = name+'_'
        return {key[len(prefix):]: archive[key].copy() for key in archive.files if key.startswith(prefix)}


def source_hashes():
    names = ('scripts/model.py', 'scripts/feedback.py', 'scripts/external_inputs.py',
             'scripts/evaluate_round2.py', 'data/processed/data.npz',
             'outputs/dispatch.npz', 'outputs/summary.json', 'docs/round2-plan.md')
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


class Experiments:
    def __init__(self, data, history_days=365):
        self.data = data
        self.history_days = history_days
        self.cache = {}
        self.scenes = {}
        self.arrays = {}

    def predictor(self, dynamic, weight):
        key = (dynamic, weight)
        if key not in self.cache:
            self.cache[key] = (build_cache(self.data, forecast=True, dynamic=dynamic, pv_weight=weight)
                               if len(self.data['dates']) == 365
                               else build_causal_cache(self.data, pv_weight=weight, dynamic=dynamic))
        return self.cache[key]

    def run(self, strategy, weight, quantile, start, end, initial, feedback='greedy', full_warmup=False):
        config = CONFIGS[strategy]
        warm = self.predictor(config['dynamic'], 1.0) if full_warmup and config['issues'] else None
        return simulate_feedback(self.data, self.predictor(config['dynamic'], weight), quantile,
            issues=config['issues'], days=end, initial=initial, start_day=start,
            dynamic=config['dynamic'], feedback=feedback, warmup_cache=warm,
            warmup_quantile=.8 if full_warmup else None)

    def archive(self, name, strategy, path, start, evaluation_start, **metadata):
        end = start+len(path['plan'])
        dates = self.data['dates']
        self.scenes[name] = dict(strategy=strategy, dynamic=CONFIGS[strategy]['dynamic'],
            issues=list(CONFIGS[strategy]['issues']), settlement='final_net',
            day_start=start, day_stop=end, evaluation_start_day=evaluation_start,
            evaluation_start=str(dates[evaluation_start]), evaluation_end=str(dates[end-1]),
            summary=summarize(path, start=evaluation_start-start), **metadata)
        self.arrays.update({name+'__'+key: value for key,value in path.items()})

    def feedback(self, external=False):
        comparisons = {}
        evaluation_start = self.history_days if external else 31
        end = len(self.data['dates'])
        for strategy, config in CONFIGS.items():
            print('Feedback benchmark:', strategy, flush=True)
            base = (self.run(strategy, config['pv_weight'], config['quantile'], 0, end, 6000.,
                             full_warmup=True) if external else primary_path(strategy))
            price_aware = self.run(strategy, config['pv_weight'], config['quantile'], 0, end,
                                  6000., feedback='mpc', full_warmup=True)
            for control, path in [('greedy',base), ('mpc',price_aware)]:
                self.archive('feedback_'+strategy+'_'+control, strategy, path, 0, evaluation_start,
                    feedback=control, pv_weight=config['pv_weight'], quantile=config['quantile'],
                    feedback_start_day=31, warmup='original_greedy_january')
            b, p = summarize(base, evaluation_start), summarize(price_aware, evaluation_start)
            comparisons[strategy] = dict(greedy='feedback_'+strategy+'_greedy',
                mpc='feedback_'+strategy+'_mpc', cash_saving_yuan=b['total_cost']-p['total_cost'],
                saving_percent=100*(b['total_cost']-p['total_cost'])/b['total_cost'],
                start_soc_difference=p['start_soc']-b['start_soc'],
                end_soc_difference=p['end_soc']-b['end_soc'])
            print(strategy, comparisons[strategy], flush=True)
        return comparisons

    def rolling(self):
        dates = self.data['dates'].astype('datetime64[D]')
        months = dates.astype('datetime64[M]')
        evaluate_months = np.arange(np.datetime64('2025-04','M'), np.datetime64('2026-01','M'))
        study = {}
        for strategy in ('q3','q4_3'):
            reference = primary_path(strategy)
            first = int(np.flatnonzero(months==evaluate_months[0])[0])
            current_soc = {key: float(reference['soc'][first,0]) for key in ('adaptive','historical')}
            pieces = {key: [] for key in current_soc}
            folds = []
            for month in evaluate_months:
                test_indices = np.flatnonzero(months==month)
                score_indices = np.flatnonzero(months==month-1)
                start, end = int(test_indices[0]), int(test_indices[-1])+1
                score_start, score_end = int(score_indices[0]), int(score_indices[-1])+1
                score_soc = float(reference['soc'][score_start,0])
                print('Rolling validation:',strategy,str(month),'past month',str(month-1),flush=True)
                trials = []
                for weight in WEIGHTS:
                    for quantile in QUANTILES:
                        candidate = self.run(strategy, weight, quantile, score_start, score_end, score_soc)
                        result = summarize(candidate, start=0)
                        trials.append(dict(pv_weight=weight, quantile=quantile,
                            validation_cost=result['total_cost'], emergency_kwh=result['emergency_kwh'],
                            start_soc=result['start_soc'], end_soc=result['end_soc']))
                rank = lambda row: (row['validation_cost'], row['pv_weight'], row['quantile'])
                selected = min(trials, key=rank)
                historical = min((row for row in trials if row['pv_weight']==0), key=rank)
                fold = dict(month=str(month), decision_time=str(dates[start])+'T00:00:00',
                    latest_actual_date=str(dates[score_end-1]),
                    score_day_start=score_start, score_day_stop=score_end,
                    test_day_start=start, test_day_stop=end, score_start_soc=score_soc,
                    candidates=trials, selected=selected, historical_selected=historical,
                    monthly={'fixed': summarize(reference,start=start,end=end)})
                for name, choice in [('adaptive',selected), ('historical',historical)]:
                    path = self.run(strategy, choice['pv_weight'], choice['quantile'],
                                    start, end, current_soc[name])
                    pieces[name].append(path)
                    current_soc[name] = float(path['soc'][-1,-1])
                    fold['monthly'][name] = summarize(path,start=0)
                folds.append(fold)
            fixed = {key:value[first:] for key,value in reference.items()}
            self.archive('rolling_'+strategy+'_fixed',strategy,fixed,first,first,
                         feedback='greedy', parameter_policy='january_fixed')
            for name in pieces:
                path = {key:np.concatenate([part[key] for part in pieces[name]],axis=0)
                        for key in pieces[name][0]}
                self.archive('rolling_'+strategy+'_'+name,strategy,path,first,first,
                             feedback='greedy',parameter_policy='previous_month_'+name)
            scene_ids = {key:'rolling_'+strategy+'_'+key for key in ('fixed','adaptive','historical')}
            totals = {key:self.scenes[value]['summary']['total_cost'] for key,value in scene_ids.items()}
            study[strategy] = dict(folds=folds,scenes=scene_ids,
                cash_saving_adaptive_vs_fixed=totals['fixed']-totals['adaptive'],
                cash_saving_adaptive_vs_historical=totals['historical']-totals['adaptive'],
                adaptive_wins_vs_fixed=sum(f['monthly']['adaptive']['total_cost']<f['monthly']['fixed']['total_cost'] for f in folds),
                adaptive_wins_vs_historical=sum(f['monthly']['adaptive']['total_cost']<f['monthly']['historical']['total_cost'] for f in folds))
            print(strategy,'rolling totals',totals,flush=True)
        return study


def save_part(study, name, content, directory, seconds):
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory/(name+'.json'),dict(content=content,scenes=study.scenes,
               elapsed_seconds=seconds,source_sha256=source_hashes()))
    np.savez_compressed(directory/(name+'.npz'),**study.arrays)


def combine(parts, output):
    report = dict(schema_version=1,protocol='docs/round2-plan.md',
        development_data_previously_seen=True,external_independence_verified=False,
        evaluation_type='retrospective_2025_feedback_and_monthly_rolling',
        scenes={},source_sha256=source_hashes(),part_seconds={})
    arrays = {}
    for name in ('feedback','rolling'):
        part = json.loads((parts/(name+'.json')).read_text(encoding='utf-8'))
        if part['source_sha256'] != report['source_sha256']:
            raise ValueError('Source changed since '+name+' was calculated; replay that part')
        report[name] = part['content']
        report['scenes'].update(part['scenes'])
        report['part_seconds'][name] = part['elapsed_seconds']
        with np.load(parts/(name+'.npz')) as source:
            arrays.update({key:source[key] for key in source.files})
    output.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(output/'dispatch.npz',**arrays)
    write_json(output/'experiments.json',report)
    print('Published',len(report['scenes']),'scenes and',len(arrays),'arrays to',output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('all','feedback','rolling','combine','external'),default='all')
    parser.add_argument('--future-data',type=Path)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/round2')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    identifier = hashlib.sha256(str(output).encode()).hexdigest()[:10]
    parts = ROOT/'tmp'/('round2-parts-'+identifier)
    if args.mode=='combine':
        combine(parts,output)
        return
    data = dict(np.load(ROOT/'data/processed/data.npz'))
    if args.mode=='external':
        if args.future_data is None:
            parser.error('--mode external requires --future-data')
        if output == (ROOT/'outputs/round2').resolve():
            parser.error('external mode requires a separate --output-dir to preserve retrospective results')
        history_days = len(data['dates'])
        data, metadata = load_future_data(data,args.future_data)
        study = Experiments(data,history_days)
        started=time.perf_counter()
        feedback=study.feedback(external=True)
        output.mkdir(parents=True,exist_ok=True)
        np.savez_compressed(output/'dispatch.npz',**study.arrays)
        write_json(output/'experiments.json',dict(schema_version=1,
            evaluation_type='frozen_parameters_future_dates',external_independence_verified=False,
            external_data=metadata,feedback=feedback,scenes=study.scenes,
            source_sha256=source_hashes(),elapsed_seconds=time.perf_counter()-started))
        return
    if args.future_data is not None:
        parser.error('--future-data is only accepted with --mode external')
    for name in ('feedback','rolling'):
        if args.mode not in ('all',name):
            continue
        study=Experiments(data)
        started=time.perf_counter()
        content=getattr(study,name)()
        save_part(study,name,content,parts,time.perf_counter()-started)
    if args.mode=='all':
        combine(parts,output)


if __name__=='__main__':
    main()
