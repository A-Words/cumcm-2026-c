"""Generate the Chinese Markdown solution and standalone scientific figures."""
from pathlib import Path
import argparse
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from model import DT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs'
NAMES = {'q2':'问题 2','q3':'问题 3','q4_2':'问题 4-2','q4_3':'问题 4-3'}
SELECTED_DATES = ['2025-03-20','2025-06-21','2025-09-23','2025-12-21']


def f(x, digits=2):
    return f'{x:,.{digits}f}'


def time_label(t):
    return f'{t//6:02d}:{t%6*10:02d}'


def events(values):
    out=[]
    i=0
    while i<144:
        if values[i]<=1e-7:
            i+=1
            continue
        start=i
        while i<144 and values[i]>1e-7:
            i+=1
        out.append((f'{time_label(start)}–{time_label(i)}',float(np.sum(values[start:i]))))
    return out


def table1(grid,cost):
    lines=['| 时间段 | 购电量 / kWh | 时间段 | 购电量 / kWh | 时间段 | 购电量 / kWh |',
           '| --- | ---: | --- | ---: | --- | ---: |']
    for indices in [(60,72,84),(96,108,120)]:
        cells=[]
        for i in indices:
            cells += [f'{time_label(i)}–{time_label(i+1)}',f(grid[i])]
        lines.append('| '+' | '.join(cells)+' |')
    lines.append(f'| 全天购电量 | {f(np.sum(grid))} | 全天购电费 / 元 | {f(cost)} | | |')
    return '\n'.join(lines)


def table2(charge,discharge,soc):
    c,d=charge.reshape(6,24).sum(1),discharge.reshape(6,24).sum(1)
    lines=['| 时间段 | 充电量 / kWh | 放电量 / kWh | 时间段 | 充电量 / kWh | 放电量 / kWh |',
           '| --- | ---: | ---: | --- | ---: | ---: |']
    for a,b in [(0,1),(2,3),(4,5)]:
        lines.append(f'| {a*4}:00–{(a+1)*4}:00 | {f(c[a])} | {f(d[a])} | {b*4}:00–{(b+1)*4}:00 | {f(c[b])} | {f(d[b])} |')
    lines.append(f'| 0:00 储电量 | {f(soc[0])} | | 24:00 储电量 | {f(soc[-1])} | |')
    return '\n'.join(lines)


def table3(data,result):
    all_events = []
    for date in SELECTED_DATES:
        day=list(data['dates']).index(date)
        ev=events(result[day])
        all_events.append(ev or [('无紧急购电',0)])
    lines=['| '+' | '.join(x for date in SELECTED_DATES for x in (date,'电量 / kWh'))+' |',
           '| '+' | '.join(['---','---:']*4)+' |']
    for row in range(max(map(len,all_events))):
        cells=[]
        for ev in all_events:
            cells += [ev[row][0],f(ev[row][1])] if row<len(ev) else ['','']
        lines.append('| '+' | '.join(cells)+' |')
    return '\n'.join(lines)


def forecast_comparison(summary):
    revision = summary['revision_experiments']
    lines = ['| 问题与预测器 | 附件 3 权重 λ | 风险分位 α | 1 月验证费用 / 元 | 正式期费用 / 元 | 紧急电 / kWh | 2 月初 SOC / kWh | 年末 SOC / kWh |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key in ('q3','q4_3'):
        candidates = revision['selection'][key]['candidates']
        for label,baseline in [('原纯附件 3 基准','pure_attachment3'),
                               ('历史光伏，原热启动','historical'),
                               ('历史光伏，共同热启动','historical_common_warmup')]:
            scene = revision['scenes'][revision['baselines'][key][baseline]]
            chosen = min((x for x in candidates if x['pv_weight']==scene['pv_weight']),
                         key=lambda x:x['validation_cost'])
            row = scene['summary']
            lines.append(f"| {NAMES[key]}：{label} | {scene['pv_weight']:g} | {scene['quantile']:g} | {f(chosen['validation_cost'])} | {f(row['total_cost'])} | {f(row['emergency_kwh'])} | {f(row['start_soc'],4)} | {f(row['end_soc'],4)} |")
        selected = revision['selection'][key]['selected']
        row = summary['primary'][key]
        lines.append(f"| {NAMES[key]}：修订后主方案 | {selected['pv_weight']:g} | {selected['quantile']:g} | {f(selected['validation_cost'])} | **{f(row['total_cost'])}** | {f(row['emergency_kwh'])} | {f(row['start_soc'],4)} | {f(row['end_soc'],4)} |")
    lines += ['', '各个权重下最优的 1 月候选如下，完整 30 组结果保存在 [修订实验归档](../outputs/experiments/revision/experiments.json)。', '',
              '| 附件 3 权重 λ | 问题 3：选中 α | 1 月费用 / 元 | 问题 4-3：选中 α | 1 月费用 / 元 |',
              '| ---: | ---: | ---: | ---: | ---: |']
    for weight in (0,.25,.5,.75,1):
        cells = [f'{weight:g}']
        for key in ('q3','q4_3'):
            best = min((x for x in revision['selection'][key]['candidates'] if x['pv_weight']==weight),
                       key=lambda x:x['validation_cost'])
            cells += [f"{best['quantile']:g}",f(best['validation_cost'])]
        lines.append('| '+' | '.join(cells)+' |')
    lines += ['', '候选验证时，各候选以自身固定权重和分位重放 1 月；实际热启动与候选回放分开。修订后主方案在 1 月固定使用纯附件 3 权重 1、分位 0.8，至 2 月 1 日才启用所选权重和分位。为完整复现评审，历史光伏“原热启动”在 1 月仍用自身预测器、固定分位 0.8；新增“共同热启动”则在 1 月与主方案一样使用纯附件 3、分位 0.8 及三次调整，至 2 月才切换历史预测器。正式预测器经济比较重点采用共同热启动行，使评价期初库存一致；原热启动行用于复现旧反例，不能将其与主结果差额全部解释为固定初始库存下的信息贡献。', '',
              '紧急购电按五倍电价计入全部策略总费。题目没有额外限制其总量，因此成本更低的历史基准不能仅因紧急电较多而被否定。新增信息是否带来经济价值，须看第 5.4 节统一热启动、控制器与其他信息的严格对照。']
    comparisons = []
    for key in ('q3','q4_3'):
        historical = revision['scenes'][revision['baselines'][key]['historical_common_warmup']]['summary']
        delta = historical['total_cost']-summary['primary'][key]['total_cost']
        comparisons.append(f"{NAMES[key]} 为 {f(delta)} 元")
    lines += ['', '共同热启动下，历史基准总费用减去修订主方案总费用，'+ '，'.join(comparisons)+'。这比较的是各自在相同 1 月规则下选参的预测与控制组合，不能直接解释成固定参数下附件 3 信息的唯一贡献。']
    return '\n'.join(lines)


def information_comparison(summary):
    revision = summary['revision_experiments']
    scenes = revision['scenes']
    information = revision['information_ablation']
    lines = ['先区分五个概念：允许重规划/提前调整购电、规划器读取真实当前 SOC、按已观测负载修正水平、当前光伏观测锚点、后续新发布的小时光伏值。下面第一步联合恢复重规划机会与当时的实际 SOC，之后逐一控制负载修正、光伏锚点和新小时预报；这不能独立识别重规划机会与 SOC 观测各自的费用贡献。所有情景在每次启用的重规划中都读取自身真实 SOC，实际逐段执行也始终使用真实当前净负荷和库存。不同策略的库存轨迹不必相同，不通过人为冻结库存制造对照。', '',
             '**先检验原纯附件 3 策略。** 下面按照归档次序逐项恢复信息。统一使用原策略分位、1 月固定分位 0.8 和反馈；各情景从 1 月 1 日的 6000 kWh 起，按本情景的信息与动作连续热启动，因此评价期初库存可能随情景变化。每个替代预测器均重新构造仅使用过去日期的残差池。', '',
             '| 累计恢复的操作/信息 | 总费用 / 元 | 相对上一行减少费用 / 元 | 紧急电 / kWh |',
             '| --- | ---: | ---: | ---: |']
    previous = None
    for scene_id in information['legacy']['ladder']:
        scene = scenes[scene_id]
        row = scene['summary']
        label = {'q3_legacy_no_updates':'仅 00 点计划，无日内重规划',
                 'q3_ladder_replan':'恢复重规划与实际 SOC，仍用日前负载与小时光伏值',
                 'q3_ladder_load':'再增加已观测负载水平修正',
                 'q3_legacy_info_000':'再增加当前光伏观测锚点，仍仅用 00 点小时预报',
                 'q3_legacy':'再增加 06、12、18 点新小时光伏预报'}.get(scene_id,scene.get('label',scene_id))
        delta = '—' if previous is None else f(previous-row['total_cost'])
        lines.append(f"| {label} | {f(row['total_cost'])} | {delta} | {f(row['emergency_kwh'])} |")
        previous = row['total_cost']
    lines += ['', '上述累计费用差依赖加入次序，会包含后续库存与原计划变化，不是唯一贡献分配，也不可与另一种干预顺序混用。以下另用完整子集对照，只改变允许读取的新小时预报；06、12、18 点重规划、真实 SOC、负载修正和当前光伏锚点均保留。旧预报按同一未来目标整点对齐，不能连观测锚点一起冻结。', '']
    for group,label in [('legacy','原纯附件 3 策略'),('selected','修订后主策略')]:
        warmup_description = ('1 月按各自允许的信息热启动、固定分位 0.8，与原评审对照一致。'
                              if group=='legacy' else
                              '所有子集 1 月统一使用纯附件 3、全部三次更新和分位 0.8，2 月才启用所选权重/分位及本组预报开关。')
        lines += [f'**{label}：新小时预报子集。** 除 00 点预报外，只读取下表指定的新小时预报；未读取时沿用最近一次允许读取的整点预报。{warmup_description}', '',
                  '| 允许读取的新小时预报 | 正式期费用 / 元 | 紧急电 / kWh | 2 月初 SOC / kWh | 年末 SOC / kWh |',
                  '| --- | ---: | ---: | ---: | ---: |']
        by_subset = {}
        for scene_id in information[group]['hourly_subsets']:
            scene = scenes[scene_id]
            subset = tuple(i*6 for i in range(1,4) if scene['forecast_sources'][i]==i)
            by_subset[subset] = scene
            row = scene['summary']
            source_label = '、'.join(f'{hour:02d}' for hour in subset) or '无，仅 00 点小时预报'
            lines.append(f"| {source_label} | {f(row['total_cost'])} | {f(row['emergency_kwh'])} | {f(row['start_soc'],4)} | {f(row['end_soc'],4)} |")
        full = by_subset[(6,12,18)]['summary']['total_cost']
        stale = by_subset[()]['summary']['total_cost']
        lines += ['', f"在所有其他操作和观测均存在的条件下，全部新小时预报相对只用 00 点小时预报的费用改善为 **{f(stale-full)} 元**。保持另外两次新预报可用，分别撤去单次新预报得到：", '',
                  '| 单独撤去的新小时预报 | 撤去后费用 − 全部新预报费用 / 元 |',
                  '| --- | ---: |']
        for hour in (6,12,18):
            subset = tuple(h for h in (6,12,18) if h!=hour)
            delta = by_subset[subset]['summary']['total_cost']-full
            lines.append(f'| {hour:02d} 点 | {f(delta,4)} |')
        weight = by_subset[(6,12,18)]['pv_weight']
        if weight == 0:
            lines += ['', '该组权重 λ=0，控制器没有使用附件 3 分量，改变其小时预报自然不会改变计划；这只说明所选策略不依赖该信息，不能证明附件 3 对所有可能控制器都无用。']
        lines += ['']
    lines += ['表中费用差为正表示撤去该次新预报后更贵，为负表示在本控制器和年度中撤去反而更便宜。单次撤去的条件不同，三项差额不可相加作为全体信息价值。原纯附件 3 对照中 18 点约 0.13 元的差异不足以支持“应引入 18 点新光伏预报”的原断言；修订后策略的条件差额以上表为准。是否保留 18 点重规划则是第 5.3 节的另一问题。这些是确定性回测差异，没有提供统计显著性或未来年度保证。']
    return '\n'.join(lines)


def contract_comparison(summary):
    revision = summary['revision_experiments']
    lines = [r'设 $q_t^{(0)}=g_t$，$q_t^{(r)}$ 为第 $r$ 次更新后仍未交付时段的购电量。替代逐笔合约每次相对前一已成交版本收费：', '',
             r'$$C_{\rm txn}=\sum_t p_tg_t+\sum_{r,t\text{ 未交付}}p_t[1.5(q_t^{(r)}-q_t^{(r-1)})_++0.5(q_t^{(r-1)}-q_t^{(r)})_+]+5\sum_t p_te_t.$$', '',
             r'该式下调不退款且另付罚金。既然可以不接收已付多余电，下调被保持上一版本并放弃余电支配。因此重新规划限制 $q_t^{(r)}\ge q_t^{(r-1)}$，而主合约仅限制 $q_t^{(r)}\ge g_t$；两者的可撤回范围不同。冻结主调度只换账单是压力测试，重新优化则把前一已成交版本带入 LP 并重新选取 1 月参数。', '',
             '| 问题与策略/结算 | 总费用 / 元 | 相对相应无调整策略减少 / 元 |',
             '| --- | ---: | ---: |']
    for key in ('q3','q4_3'):
        contract = revision['contracts'][key]
        no_update = summary['primary']['q2' if key=='q3' else 'q4_2']['total_cost']
        legacy = revision['scenes'][revision['baselines'][key]['pure_attachment3']]['summary']
        reoptimized = revision['scenes'][contract['reoptimized']]['summary']
        for label,cost in [('原纯附件 3，主合约',legacy['total_cost']),
                           ('原纯附件 3，冻结调度逐笔重计',contract['frozen_legacy']['total_cost']),
                           ('修订后主方案，主合约',summary['primary'][key]['total_cost']),
                           ('修订后主方案，冻结调度逐笔重计',contract['frozen_selected']['total_cost']),
                           ('逐笔合约下重新优化',reoptimized['total_cost'])]:
            lines.append(f'| {NAMES[key]}：{label} | {f(cost)} | {f(no_update-cost)} |')
    lines += ['', '| 逐笔合约重新优化 | 附件 3 权重 λ | 风险分位 α | 1 月验证费用 / 元 | 正式期紧急电 / kWh | 2 月初 SOC / kWh | 年末 SOC / kWh |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key in ('q3','q4_3'):
        contract = revision['contracts'][key]
        selected = contract['selection']['selected']
        row = revision['scenes'][contract['reoptimized']]['summary']
        lines.append(f"| {NAMES[key]} | {selected['pv_weight']:g} | {selected['quantile']:g} | {f(selected['validation_cost'])} | {f(row['emergency_kwh'])} | {f(row['start_soc'],4)} | {f(row['end_soc'],4)} |")
    lines += ['', '逐笔情景仍在同一 30 组权重/分位候选中以 1 月费用选择，真实热启动固定纯附件 3 权重 1、分位 0.8，但从 1 月起就使用逐笔合约。主合约选中权重 0.5，逐笔合约选中 0.25；因此两条重新优化后的费用差同时包含合约、所选预测器与调度路径的变化，不能解释成只改收费公式的纯合约边际。只有冻结调度重计费保持路径不变。不同合约也可造成评价期初库存不同，表中同时披露首末 SOC；结果是该合约下有限策略族的重新优化，不能称为随机全局最优。主表与五份 Excel 保持主合约，逐笔、冻结重计和退款结果只列为替代解释。主合约优势不能直接推广到另一种交易制度。']
    return '\n'.join(lines)


def round2_comparison(report):
    """Render the independent second-round benchmarks without changing main results."""
    scenes=report['scenes']
    lines=['**价格感知反馈：2025 年 2—12 月，334 天。** 参数、预报发布时间和 1 月热启动与对应主策略相同；仅从 2 月开始改为每十分钟重算的确定性反馈。反馈 LP 固定当前常规承诺，最小化预测的剩余当日紧急费，只执行首动作，不用紧急电充电。未来量使用最新允许的预测，首段使用已实现净负荷和当前实价；午夜终端价值取 0。因此结果是这一具体反馈基准的费用差，不是随机全局最优或所有 MPC 方法的结论。', '',
           '| 问题与反馈 | 计划费用 / 元 | 调整费用 / 元 | 紧急费用 / 元 | 总费用 / 元 |',
           '| --- | ---: | ---: | ---: | ---: |']
    for strategy,comparison in report['feedback'].items():
        for control,label in [('greedy','原贪心'),('mpc','确定性滚动')]:
            row=scenes[comparison[control]]['summary']
            lines.append(f"| {NAMES[strategy]}：{label} | {f(row['plan_cost'])} | {f(row['adjustment_cost'])} | {f(row['emergency_cost'])} | {f(row['total_cost'])} |")
    lines += ['', '| 问题与反馈 | 紧急电 / kWh | 未利用电 / kWh | 2 月初 SOC / kWh | 年末 SOC / kWh |',
              '| --- | ---: | ---: | ---: | ---: |']
    for strategy,comparison in report['feedback'].items():
        for control,label in [('greedy','原贪心'),('mpc','确定性滚动')]:
            row=scenes[comparison[control]]['summary']
            lines.append(f"| {NAMES[strategy]}：{label} | {f(row['emergency_kwh'])} | {f(row['spill_kwh'])} | {f(row['start_soc'],4)} | {f(row['end_soc'],4)} |")
    lines += ['', '| 问题 | 贪心总费用 − 滚动反馈总费用 / 元 | 相对贪心费用节省 |',
              '| --- | ---: | ---: |']
    for strategy,comparison in report['feedback'].items():
        lines.append(f"| {NAMES[strategy]} | {f(comparison['cash_saving_yuan'])} | {comparison['saving_percent']:+.3f}% |")
    feedback_worse=sum(row['cash_saving_yuan']<0 for row in report['feedback'].values())
    matching_ends=all(abs(row['end_soc_difference'])<1e-6 for row in report['feedback'].values())
    lines += ['', f'最后两列均以正值表示滚动反馈节省、负值表示更贵。本次 {len(report["feedback"])} 种策略中有 {feedback_worse} 种使用滚动反馈后总费用增加。两种反馈具有相同评价期初库存，'+
              ('本次各对应年末库存也相同，费用差不能归于不同的边界库存。' if matching_ends else '年末库存见表，未将库存折价成虚构的现金收入。')+
              '期间库存和后续常规计划仍可以不同；后续计划读取各自真实 SOC，因此总费差含计划及调整路径的变化，这里没有冻结整年购电路径来单独识别当段动作价值。', '',
              '本次四组账单均显示常规购电费用（计划加调整）减少、紧急费增加，后者超过前者。这说明在当前预测、参数和终端规则下，按预测分配电池并没有产生实际费用改善。反馈基准沿用原先针对贪心策略选定的权重和分位，没有另外为 MPC 搜索参数。其不利结果既不证明贪心全局最优，也不排除专门校准、跨日价值或多情景 MPC 的可能改进。', '',
              '**按月选参：2025 年 4—12 月，275 天。** 每次只按上一完整月现金费用选择，次月参数冻结。30 组融合候选和其中 6 组纯历史候选分别选参；所有评分候选共享参考主策略的评分月初库存，并披露各自月末库存。正式三条路径共用 4 月初库存，此后各自连续，不能按月重置库存。下面总费覆盖 4—12 月，不能直接与上面 2—12 月总费相减。', '',
              '| 问题与参数规则 | 总费用 / 元 | 紧急电 / kWh | 4 月初 SOC / kWh | 年末 SOC / kWh |',
              '| --- | ---: | ---: | ---: | ---: |']
    for strategy,study in report['rolling'].items():
        for key,label in [('fixed','固定 1 月参数'),('adaptive','按上月选择融合候选'),('historical','按上月选择纯历史候选')]:
            row=scenes[study['scenes'][key]]['summary']
            lines.append(f"| {NAMES[strategy]}：{label} | {f(row['total_cost'])} | {f(row['emergency_kwh'])} | {f(row['start_soc'],4)} | {f(row['end_soc'],4)} |")
    lines += ['', '| 问题 | 评价月份 | 上月所选 λ | 上月所选 α | 历史候选所选 α | 固定费用 − 融合自适应费用 / 元 | 历史自适应费用 − 融合自适应费用 / 元 |',
              '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for strategy,study in report['rolling'].items():
        for fold in study['folds']:
            chosen=fold['selected']
            month=fold['monthly']
            lines.append(f"| {NAMES[strategy]} | {fold['month']} | {chosen['pv_weight']:g} | {chosen['quantile']:g} | {fold['historical_selected']['quantile']:g} | {f(month['fixed']['total_cost']-month['adaptive']['total_cost'])} | {f(month['historical']['total_cost']-month['adaptive']['total_cost'])} |")
    lines += ['']
    for strategy,study in report['rolling'].items():
        worst=max(study['folds'],key=lambda fold:fold['monthly']['adaptive']['total_cost']-fold['monthly']['fixed']['total_cost'])
        deterioration=worst['monthly']['adaptive']['total_cost']-worst['monthly']['fixed']['total_cost']
        fixed_difference=study['cash_saving_adaptive_vs_fixed']
        direction='节省' if fixed_difference>=0 else '增加'
        lines.append(f"{NAMES[strategy]} 的融合自适应相对固定参数累计{direction} {f(abs(fixed_difference))} 元，9 个月中 {study['adaptive_wins_vs_fixed']} 个月费用更低；相对纯历史自适应累计节省 {f(study['cash_saving_adaptive_vs_historical'])} 元，{study['adaptive_wins_vs_historical']} 个月更低。相对固定参数最不利月份为 {worst['month']}，自适应费用减去固定费用为 {f(deterioration)} 元。")
        lines.append('')
    lines += ['本次两种电价下的融合自适应都比固定主参数更贵，不能据此主张每月重选参数更稳健。它们相对纯历史自适应的费用更低，仅支持这一年度和这些预设路径之间的比较。三条路径在各自问题内的评价期首末库存均相同，评分候选的末库存则不必相同，选参评分也没有将其折价。候选族与本轮检验设计均已接触 2025 年数据，九个月差额又不是独立同分布样本，因此本实验是回顾式跨月再分析，既不证明独立外部泛化，也不由月份胜率推出统计显著性。原主方案和 Excel 沿用已交付策略，不根据这些新结果事后改选。', '',
              '完整参数候选、发布时间、费用分解和路径见 [第二轮实验 JSON](../outputs/experiments/round2/experiments.json) 与 [逐段归档](../outputs/experiments/round2/dispatch.npz)。新增控制器定义及对第二轮意见的逐项回应见 [第二轮回应](reviews/round2-response.md)；未来年度接口与冻结规则见 [外部验证协议](modeling/external-validation-protocol.md)。目前没有未见过的外部年度结果；输入日期在后、接口能够运行和外部泛化已验证是三件不同的事。']
    return '\n'.join(lines)


def figures(data,dispatch,summary):
    target=OUT/'figures'
    target.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':['Microsoft YaHei','DejaVu Sans'],
                         'axes.unicode_minus':False,'figure.dpi':140,'savefig.dpi':180,
                         'axes.spines.top':False,'axes.spines.right':False,
                         'axes.grid':True,'grid.alpha':.18,'font.size':10})
    hours=(np.arange(144)+.5)/6
    fig,ax=plt.subplots(3,1,figsize=(11,8.2),sharex=True,layout='constrained')
    ax[0].plot(hours,data['q1_load'],label='负载',color='#243b53')
    ax[0].plot(hours,data['q1_pv'],label='光伏',color='#de9b29')
    ax[0].step(hours,dispatch['q1_grid']/DT,where='mid',label='计划购电',color='#287d8e',lw=1.2)
    ax[0].set_ylabel('功率 / kW'); ax[0].legend(ncol=3,loc='upper left')
    ax[0].set_title('问题 1：确定性最优调度',loc='left',fontweight='bold')
    ax[1].bar(hours,dispatch['q1_charge']/DT,width=1/6,label='充电',color='#2d9a8b')
    ax[1].bar(hours,-dispatch['q1_discharge']/DT,width=1/6,label='放电（负向）',color='#ba5842')
    ax[1].set_ylabel('储能功率 / kW'); ax[1].legend(ncol=2,loc='upper left')
    ax[2].plot(np.arange(145)/6,dispatch['q1_soc'],color='#76519b',label='储电量')
    ax[2].axhline(1200,color='gray',ls='--',lw=.8); ax[2].axhline(10800,color='gray',ls='--',lw=.8)
    ax[2].set_ylabel('储电量 / kWh'); ax[2].set_xlabel('时刻 / h')
    right=ax[2].twinx();right.plot(hours,data['fixed_price'],color='#de9b29',alpha=.8,label='电价')
    right.set_ylabel('电价 /（元/kWh）',color='#aa7419'); right.grid(False)
    ax[2].set_xlim(0,24);ax[2].set_xticks(np.arange(0,25,2))
    fig.savefig(target/'q1-dispatch.png');fig.savefig(target/'q1-dispatch.svg');plt.close(fig)

    fig,ax=plt.subplots(2,1,figsize=(11,7.3),sharex=True,layout='constrained')
    months=np.array([int(x[5:7]) for x in data['dates']])
    for key,color in [('q2','#648baa'),('q3','#217b76'),('q4_2','#c98955'),('q4_3','#904944')]:
        monthly=[dispatch[key+'_costs'][months==m,3].sum()/1e4 for m in range(2,13)]
        ax[0].plot(range(2,13),monthly,'o-',label=NAMES[key],color=color)
        em=[dispatch[key+'_emergency'][months==m].sum()/1e3 for m in range(2,13)]
        ax[1].plot(range(2,13),em,'o-',label=NAMES[key],color=color)
    ax[0].set_title('正式评价期：每月费用与紧急购电',loc='left',fontweight='bold')
    ax[0].set_ylabel('总费用 / 万元');ax[0].legend(ncol=4)
    ax[1].set_ylabel('紧急购电 / MWh');ax[1].set_xlabel('2025 年月份');ax[1].set_xticks(range(2,13))
    fig.savefig(target/'monthly-comparison.png');fig.savefig(target/'monthly-comparison.svg');plt.close(fig)

    cases=[('仅 00 点','q3_midnight_only'),('00+06','q3_update06'),('00+12','q3_update12'),
           ('00+18','q3_update18'),('00+06+12','q3_update06_12'),
           ('00+06+18','q3_update06_18'),('00+12+18','q3_update12_18'),('全部四次',None)]
    vals=[summary['sensitivity'][k]['total_cost']/1e4 if k else summary['primary']['q3']['total_cost']/1e4 for _,k in cases]
    fig,ax=plt.subplots(figsize=(10.4,5.6),layout='constrained')
    bars=ax.barh([x[0] for x in cases],vals,color=['#87a4b6']*7+['#227c77'])
    ax.bar_label(bars,labels=[f'{v:,.2f}' for v in vals],padding=5)
    ax.set_xlim(0,max(vals)*1.13);ax.invert_yaxis();ax.set_xlabel('2—12 月总费用 / 万元')
    ax.set_title('问题 3：不同日内重规划时刻的策略比较（非预报贡献）',loc='left',fontweight='bold')
    fig.savefig(target/'forecast-ablation.png');fig.savefig(target/'forecast-ablation.svg');plt.close(fig)
    # Matplotlib emits trailing spaces inside SVG paths; normalize only whitespace.
    for svg in target.glob('*.svg'):
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',
                       encoding='utf-8',newline='\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markdown-only',action='store_true',
                        help='Refresh Markdown without rewriting the existing figure artifacts.')
    args=parser.parse_args()
    data=dict(np.load(ROOT/'data/processed/data.npz'))
    d=dict(np.load(OUT/'main/dispatch.npz'))
    s=json.loads((OUT/'main/summary.json').read_text(encoding='utf-8'))
    s['revision_experiments']=json.loads((OUT/'experiments/revision/experiments.json').read_text(encoding='utf-8'))
    v=json.loads((OUT/'main/validation.json').read_text(encoding='utf-8'))
    rv=json.loads((OUT/'experiments/revision/validation.json').read_text(encoding='utf-8'))
    round2_path=OUT/'experiments/round2/experiments.json'
    round2_text=(round2_comparison(json.loads(round2_path.read_text(encoding='utf-8')))
                 if round2_path.exists() else '')
    round2_evidence=''
    round2_validation_path=OUT/'experiments/round2/validation.json'
    if round2_text and round2_validation_path.exists():
        round2_validation=json.loads(round2_validation_path.read_text(encoding='utf-8'))
        if round2_validation['status']!='passed':
            raise ValueError('Second-round validation failed; do not publish a passed report.')
        round2_evidence=(f"第二轮补充核验：[独立验证](../outputs/experiments/round2/validation.json) 共 {round2_validation['check_count']} 项通过，"
            f"包括全部 14 个场景的物理约束及路径账单、{round2_validation['representative_candidate_replays']} 个代表性候选月重放、"
            f"12 个正式月的完整 11 字段重放、{round2_validation['future_month_mutation_replays']} 个修改未来月份后的评分重放及 2 个跨预报发布边界的 MPC 因果探针。"
            "另有 9 个反馈回归测试与 10 个外部输入测试通过。它们检验当前实现、因果和账单一致性，不证明预测策略最优或外部泛化。")
        round2_text+='\n\n'+round2_evidence
    round2_section=('### 8.5 第二轮补充：价格感知反馈与跨月检验\n\n'+round2_text+'\n\n'
                    if round2_text else '')
    round2_evidence_line='- '+round2_evidence+'\n' if round2_evidence else ''
    if not args.markdown_only:
        figures(data,d,s)
    p=s['primary']
    saving=p['q2']['total_cost']-p['q3']['total_cost']
    saving4=p['q4_2']['total_cost']-p['q4_3']['total_cost']
    text=rf'''# 微网与外部电网电力调控策略：模型、计算与可复现结果

## 摘要

本文完成题目四问，以 10 分钟为步长，统一描述电力平衡、储能损耗与购电结算。问题 1 在给定预测和日循环边界下用线性规划求得全局最优，全天购电 **{f(s['q1_grid_kwh'])} kWh**，购电费 **{f(s['q1']['cost'])} 元**。独立加入充放电互斥的混合整数规划得到相同目标值。

问题 2—4 采用“历史预测—风险分位规划—实时安全反馈”的可行策略。所有计划只使用决策时刻已到达的信息；1 月用于训练、参数验证及从 6000 kWh 开始的热启动，正式结果覆盖 2025 年 2 月 1 日至 12 月 31 日，共 334 天、48,096 个区间。固定电价下，问题 3 总费用比问题 2 减少 **{f(saving)} 元（{saving/p['q2']['total_cost']:.2%}）**；波动电价下减少 **{f(saving4)} 元（{saving4/p['q4_2']['total_cost']:.2%}）**。紧急电计入费用并消除缺供，储电量逐日连续。

后续问题包含预测误差和控制近似，本文不声称其结果为严格随机全局最优。修订版增加历史光伏与附件 3 的融合候选，参数仍只按 1 月费用选择；但候选模型族是在评审已有全年结果后扩展，因此本次属于同一数据集上的再分析，不能称为新的独立测试或前瞻验证。费用优势还以未交付增购可撤回、按最终净调整结算的主合约为前提；逐笔收费合约另行优化并报告。

第二轮补充的确定性价格感知反馈和按上月重选参数均未降低对应本年评价期总费，原主方案保持；这些不利结果也不证明贪心全局最优。外部年度数据接口及核验协议已提供，真实独立泛化实证尚未完成。

**关键词：** 微网；储能调度；线性规划；因果回测；风险分位；实时电价。

## 1. 题目理解与数据审查

题面为 [C 题 PDF](../problem/C题.pdf)，原始输入为 [附件目录](../data/raw/)。完整审计见 [数据审计](modeling/data-audit.md)，计算前的判断与修正过程见 [决策记录](modeling/decisions.md)，初次方法审查见 [模型审查](reviews/model-review.md)，后续反向评审及修订回应见 [评审回应](reviews/review-response.md) 与 [第二轮回应](reviews/round2-response.md)。

附件 1 有 144 条电价、负载、光伏预测；附件 2 有全年 365×144 条实际负载和光伏；附件 3 有 365×4×24 个小时预报；附件 4 有 365×144 条实际电价。所需数值无缺失、负数和非有限值，日期连续。原始文件 SHA-256 已保存并在验收时重核。

有四项容易改变答案的细节：

1. 输入的第一个时点为 00:10，最后一个为次日 00:00。主计算将右端记录代表此前 10 分钟的平均功率，功率除以 6 转为电量。题面未明确平均/瞬时语义，因此另做梯形积分敏感性。
2. 附件 5 模板却把第一个区间写成 00:10–00:20，整体偏移 10 分钟。交付文件保留模板结构，并将 144 个标签修正为 **00:00–00:10 至 23:50–24:00**。数据不循环移位。题面 10:00–10:10 对应数组索引 60。
3. 附件 1 负载几乎精确等于附件 2 全年同刻均值，光伏也近似全年均值。问题 2—4 只引用附件 1 电价，绝不把该负载/光伏曲线作为历史预测先验。
4. 附件 3 的“预报 k 小时”表示**发布后 k 小时**，并非当日第 k 小时。发布时刻已有观测作为 0 小时锚点，之后在线性插值曲线上取 10 分钟右端值。06 点新预报只能改变 06:00–06:10 及之后的区间。

## 2. 假设、符号与统一物理模型

### 2.1 必要假设

- 额定容量 12000 kWh，可运行储电量区间为 1200–10800 kWh。充、放电各自效率取 0.9，往返效率为 0.81。充放电功率上限在交流母线侧均为 5000 kW。
- 不售电；题目没有给外网购电上限。允许放弃无法利用的光伏或不接收已付费计划电量，其购电费照付。把这两类统一称为“未利用电量”，不能把它全部叫作弃光。
- 段内功率近似恒定，控制器可响应当前实际负荷/光伏并紧急补电。没有额外的响应延迟、储能老化费、自放电和备用成本，这些均不在题给参数中。
- 除问题 1 的日循环外，不增加实际日末电量等式。后续计划使用 **日末预测储电量至少 6000 kWh** 的恢复库存设计，但执行真实末值可以偏离，并原样传给次日。
- 波动电价的未来值不默认为提前公布。以历史预测价作决策，按对应交付时段真实价格结算。“交易时刻”解释为该 10 分钟交付区间的结算价格；若采用下单瞬间统一报价，将成为另一种合约制度。

### 2.2 符号表

| 符号 | 含义 | 单位 |
| --- | --- | --- |
| $t=0,\ldots,143$，$\Delta=1/6$ | 日内区间与区间长度 | h |
| $L_t,V_t$ | 实际负载电量、光伏电量，等于功率乘 $\Delta$ | kWh |
| $g_t,q_t$ | 00 点原计划、该交付区间最终调整后常规购电 | kWh |
| $e_t,w_t$ | 紧急购电、未利用电量 | kWh |
| $c_t,d_t$ | 母线侧充电输入、放电输出 | kWh |
| $S_t$ | 区间起点储电量 | kWh |
| $p_t,\widehat p_t$ | 实际结算价、决策时预测价 | 元/kWh |

每一段满足

$$
q_t+e_t+V_t+d_t=L_t+c_t+w_t,
\qquad S_{{t+1}}=S_t+0.9c_t-d_t/0.9,
$$

$$
1200\le S_t\le10800,\qquad
0\le c_t,d_t\le 5000/6,
\qquad q_t,e_t,w_t\ge0.
$$

实际调度还满足 $c_td_t=0$。对规划 LP 的任一同时充放电解，令 $\delta=\min(c_t,d_t/0.81)$，将充电减去 $\delta$，放电减去 $0.81\delta$，未利用电量增加 $0.19\delta$。SOC、购电费和电力平衡保持不变，至少一种充放电变为零。因此允许未利用余电时，存在同费用且互斥的 LP 解。实现用微小吞吐惩罚选解，并另解不加惩罚的纯电费 LP 核实问题 1 最优费用未改变。

## 3. 问题 1：确定性日循环最优策略

令 $e_t=0,q_t=g_t$，把附件 1 光伏预测作为确定输入，增加 $S_0=S_{{144}}=6000$，求解

$$\min\sum_{{t=0}}^{{143}}p_tg_t$$

及第 2 节约束。实现有 $5\times144=720$ 个连续变量和 $2\times144=288$ 个线性等式，用 SciPy/HiGHS 求解 [3,4]。数值选解项为 $10^{{-6}}\sum(c_t+d_t)+10^{{-7}}\sum w_t$，只用于选解，不计入报告电费。与纯电费目标差为 **{s['q1']['optimality_gap_yuan']:.3g} 元**。独立 MILP 增加 144 个二元变量，也获得相同费用，见 [MILP 验证结果](../outputs/main/q1-milp-verification.json)。

**表 1：指定时段与全天购电。**

{table1(d['q1_grid'],s['q1']['cost'])}

**表 2：指定区间充放电与日初、日末储电量。**

{table2(d['q1_charge'],d['q1_discharge'],d['q1_soc'])}

![问题1最优调度](../outputs/figures/q1-dispatch.png)

电池在低价/光伏富余段积累能量，在高价段替代外网购电。每充入 1 kWh 只能最终输出 0.81 kWh，纯套利至少要求放电时段的替代电价大于充电时段电价除以 0.81。容量及功率约束决定不能把全部负荷都移至最低价段。完整 144 段见 [result1.xlsx](../outputs/deliverables/result1.xlsx)。

## 4. 问题 2：历史预测、风险计划与实时执行

### 4.1 只使用已有历史的预测

负载存在周周期，但不预设现实中的周末标签。对当日第 $t$ 段，使用最近最多四个相隔 7 天的同刻历史值，权重依次为 $1,0.55,0.55^2,0.55^3$ 后归一化。不足 7 天时退回最近最多 7 天、衰减 0.8 的历史均值。光伏使用最近最多 7 天同刻值，权重为 $1,0.75,\ldots,0.75^6$。1 月 1 日无历史的负载先验为常数 4500 kW、光伏为 0；它只影响热启动，不利用附件 1 全年典型曲线。

这里 $\widehat N_{{d,t}}=(\widehat P^L_{{d,t}}-\widehat P^V_{{d,t}})\Delta$。历史残差必须对应当时实际可生成的预测，定义 $r_{{j,t}}=N_{{j,t}}-\widehat N_{{j,t}}$。取最多过去 28 天（排除最初 7 天）及每个同刻前后各 3 段的残差池，构造

$$\widetilde N_{{d,t}}=\widehat N_{{d,t}}+Q_\alpha\{{r_{{j,t+k}}:j<d,\ |k|\le3\}}.$$

边界邻时段使用重复端点，样本不足时只用点预测。该分位用于适度多买电以降低 5 倍紧急成本，并不代表整日缺供概率保证。在无储能的单区间简化模型 $\min_g pg+5p\mathbb E(N-g)_+$ 中，求导给出经济分位 0.8。储能跨段耦合后仍须验证参数。

### 4.2 参数选取与计划

候选 $\alpha\in\{{0.50,0.65,0.70,0.80,0.90,0.95\}}$，各候选按时间顺序重放 1 月，以 1 月 15—31 日实际总费用选取。**正式实际热启动阶段始终执行预先固定的 0.8，而非把月底选中的参数倒灌给 1 月。** 选中参数从 2 月 1 日生效；残差样本、历史曲线继续按固定窗口因果更新。问题 2 最终 $\alpha={s['parameters']['q2']}$。

每日 00 点把净负荷替换为 $\widetilde N$，解第 3 节同类 LP，初始储电量取上一日真实末值，计划终端下界取 6000。当日 $g_t$ 一旦确定便不再改变。充放电计划用于决定购电量，最终设备动作由下述反馈生成。

### 4.3 实时安全反馈

记当前已实现净负荷与常规购电的差为 $a_t=L_t-V_t-q_t$。若 $a_t\ge0$：

$$d_t=\min\{{a_t,5000/6,0.9(S_t-1200)\}},\quad e_t=a_t-d_t,\quad c_t=w_t=0.$$

若 $a_t<0$：

$$c_t=\min\{{-a_t,5000/6,(10800-S_t)/0.9\}},\quad w_t=-a_t-c_t,\quad d_t=e_t=0.$$

然后更新 $S_{{t+1}}$。故充放电功率与储电边界天然满足，紧急购电补齐全部剩余缺口，互斥也成立。成本为

$$C_2=\sum_t p_tg_t+5\sum_t p_te_t.$$

这是可执行的安全反馈启发式，未优化跨价格时段分配紧急电的电池库存，不应称作严格最优 MPC。例如两段各缺 100 kWh、常规购电为零、初始库存仅够向母线放出 100 kWh，前段电价 0.3713、后段 1.3952 元/kWh 时，贪心先放电会在后段支付 697.60 元紧急费；若前段紧急买电并保留库存，费用为 185.65 元，末 SOC 相同。这证明反馈一般没有经济最优性，但并不证明该节省可在全年未知未来时因果实现。修订保留此控制器，使预测和合约对照使用相同执行规则。滚动优化、仅执行当前动作的标准能源 MPC 方法可参见 [1,2]。

## 5. 问题 3：预报更新、调整结算及信息价值

主策略以历史光伏与附件 3 的最新可用预测作凸组合：

$$\widehat V^{{(\lambda)}}=(1-\lambda)\widehat V^{{\rm hist}}+\lambda\widehat V^{{\rm att3}},\qquad
\lambda\in\{{0,0.25,0.5,0.75,1\}}.$$

$\lambda=0$ 为仅用历史光伏的可实施基准，$\lambda=1$ 为原纯附件 3 策略。每个权重与第 4.2 节六个分位组合，分别以 1 月 15—31 日的费用选取；每个预测器和发布时间独立构造历史残差池，不套用其他预测器的残差。模型族扩展是在审查发现全年反例之后，故本次只能称为同年再分析。

06、12、18 点使用当时已到达信息重规划，并用已经完成的最近 18 个十分钟段修正负载预测水平：历史预测乘以“已观测均值/此前预测均值”，比例截断在 0.75–1.25。附件 3 分量使用最新发布的未来整点值，插值起点使用当前已完成区间的光伏观测；这两项信息在对照中单独控制。所有插值和修正均不使用未来实测。最终参数与各基准见第 5.2 节。

### 5.1 主结算口径

令 $u_t=(q_t-g_t)_+$，$v_t=(g_t-q_t)_+$。题面未写下调是否退款，主解释采用原计划仍付款、另收违约费用：

$$C_3=\sum_t[p_tg_t+1.5p_tu_t+0.5p_tv_t+5p_te_t].$$

每次更新只优化未交付的剩余区间，保留原始 00 点 $g_t$ 作为唯一基准。按**最终交付量**相对原计划结算一次，不把三次修订的整张表分别累计计费；这也假设尚未交付的先前增购可以再次修订而不另收路径费用。这里增购属于交付前可撤回的计划申报；若增购下单后即成交且不可退，需采用第 8.1 节逐笔合约，不能直接沿用主结果的收益。

允许放弃过购电时，下调至 $q_t<g_t$ 受支配：改成 $q_t=g_t$ 并将增加量全部不接收，物理状态不变，还节省 $0.5p_t(g_t-q_t)$。因此主规划直接限制 $q_t\ge g_t$。更新 LP 的有效变量成本为 $1.5\sum_t\widehat p_tq_t$，原计划常数项不影响最优决策。实际执行仍用第 4.3 节规则。

### 5.2 预测器基准与参数选择

{forecast_comparison(s)}

### 5.3 重规划时刻的完整策略比较

仅对比问题 2 和问题 3 无法隔离日内预报的贡献，因为两者 00 点的信息本来就不同。下面固定修订后主预测器、参数、规划器、反馈规则及 1 月 1 日初始状态，仅改变允许日内重规划的时刻。关闭一个时刻会同时失去调整机会、读取当前状态和修正预测的机会，故这是**完整策略比较**，不是新小时预报的价值分解。不同 SOC 轨迹也会影响次日原计划。

| 允许重规划的时刻 | 2—12 月总费用 / 元 | 紧急购电 / kWh |
| --- | ---: | ---: |
'''
    for label,key in [('00','q3_midnight_only'),('00、06','q3_update06'),('00、12','q3_update12'),
                      ('00、18','q3_update18'),('00、06、12','q3_update06_12'),
                      ('00、06、18','q3_update06_18'),('00、12、18','q3_update12_18')]:
        row=s['sensitivity'][key]
        text+=f"| {label} | {f(row['total_cost'])} | {f(row['emergency_kwh'])} |\n"
    text+=f"| 00、06、12、18 | {f(p['q3']['total_cost'])} | {f(p['q3']['emergency_kwh'])} |\n"
    ablation_gain=s['sensitivity']['q3_midnight_only']['total_cost']-p['q3']['total_cost']
    text+=rf'''
允许全部重规划比仅 00 点规划的费用差为 {f(ablation_gain)} 元（{ablation_gain/s['sensitivity']['q3_midnight_only']['total_cost']:.2%}）。该差额包含提前增购、状态更新和预测修正等共同影响，不能全部归于新增小时光伏预报。即使 18 点新光伏预报没有可辨认的费用贡献，18 点仍可能通过当前库存与负荷信息调整晚间购电；两种说法须区分。

![日内重规划时刻比较](../outputs/figures/forecast-ablation.png)

### 5.4 信息贡献的严格控制

{information_comparison(s)}

## 6. 问题 4：波动价格的因果决策

沿用问题 2、3，仅将优化器中的价格替换为历史预测价格。00 点价格预测同样取最近四个相隔 7 天的电价曲线，衰减 0.55；不足 7 天用最近 7 天衰减 0.8，1 月 1 日使用题目已提供的固定价曲线。问题 4-3 日内更新使用已完成最近 18 段的实价/预测价均值之比，截断在 0.5–1.5，修正剩余价曲线。

购电计划、追加和紧急电的最终费用一律按附件 4 对应区间真实价格结算。问题 4-2 选定分位 {s['parameters']['q4_2']}；问题 4-3 选定分位 {s['parameters']['q4_3']}、附件 3 权重 {s['pv_weights']['q4_3']}，选择规则及基准见第 5.2 节。价格未来真值只在专门标明的先知参考中进入优化，主 Excel 不含先知结果。

## 7. 全期结果与指定日期的题面表格

### 7.1 334 天汇总

| 策略 | 计划购电 / kWh | 最终常规购电 / kWh | 紧急购电 / kWh | 未利用电量 / kWh |
| --- | ---: | ---: | ---: | ---: |
'''
    for key,name in NAMES.items():
        x=p[key];text+=f"| {name} | {f(x['plan_kwh'])} | {f(x['adjusted_kwh'])} | {f(x['emergency_kwh'])} | {f(x['spill_kwh'])} |\n"
    text+='\n| 策略 | 计划费用 / 元 | 调整增量费用 / 元 | 紧急费用 / 元 | 总费用 / 元 |\n| --- | ---: | ---: | ---: | ---: |\n'
    for key,name in NAMES.items():
        x=p[key];text+=f"| {name} | {f(x['plan_cost'])} | {f(x['adjustment_cost'])} | {f(x['emergency_cost'])} | **{f(x['total_cost'])}** |\n"
    text+='\n| 策略 | 2 月 1 日 00 点 SOC / kWh | 12 月 31 日 24 点 SOC / kWh | 发生紧急购电的天数 |\n| --- | ---: | ---: | ---: |\n'
    for key,name in NAMES.items():
        x=p[key];text+=f"| {name} | {f(x['start_soc'])} | {f(x['end_soc'])} | {x['emergency_days']} |\n"
    text+='\n各方案 1 月均从 6000 kWh 启动，但热启动中可用信息和动作不同，评价期首末库存因此不同，以上如实披露。购电比较还包含储能损耗、未利用电量和边界库存变化。\n\n![月度费用与紧急电](../outputs/figures/monthly-comparison.png)\n'
    for key,name in NAMES.items():
        text+=f'\n### 7.{list(NAMES).index(key)+2} {name}指定日期\n\n'
        if key in ('q3','q4_3'):
            text+='下列表 1 使用最终调整后常规购电量。全天费列是原计划加调整的常规结算费，紧急费用另列；初始计划与费用也同时披露。原始 00 点计划的 144 段保存在工作簿的“计划购电量”表。\n'
        else:
            text+='下列表 1 使用 00 点计划购电量与计划费用；紧急费用单列。表 2 均为实际执行充放电量。\n'
        for date in SELECTED_DATES:
            day=list(data['dates']).index(date)
            cost=d[key+'_costs'][day]
            text+=f'\n#### {date}\n\n'
            text+=f"原始计划全天 {f(d[key+'_plan'][day].sum())} kWh，计划费 {f(cost[0])} 元，调整费 {f(cost[1])} 元，紧急费 {f(cost[2])} 元，**合计 {f(cost[3])} 元**。\n\n"
            text+=table1(d[key+'_adjusted'][day],cost[0]+cost[1])+'\n\n'
            text+=table2(d[key+'_charge'][day],d[key+'_discharge'][day],d[key+'_soc'][day])+'\n'
        text+='\n**表 3：四个指定日的紧急购电区间。** 相邻正电量段合并，事件跨日时按日分开。\n\n'
        text+=table3(data,d[key+'_emergency'])+'\n'

    text+=rf'''
## 8. 敏感性、预测误差与结果边界

### 8.1 题意解释的敏感性

**未交付增购能否撤回：逐笔交易合约。**

{contract_comparison(s)}

**其他解释。**

- **功率离散化：** 问题 1 改用分段线性梯形积分后，费用为 {f(s['q1_trapezoid_cost'])} 元，相对主口径变化 {(s['q1_trapezoid_cost']/s['q1']['cost']-1):+.2%}；购电量为 {f(s['q1_trapezoid_grid_kwh'])} kWh。主提交仍按右端代表平均功率。该敏感性没有冒充四问全部重算。
- **效率语义：** 若把“90%”解释成往返效率，单向效率改为 $\sqrt{{0.9}}$，问题 1 费用为 {f(s['q1_roundtrip90_cost'])} 元；主口径仍为两个单向效率各 0.9。后续主结果未混用此替代解释。
- **取消退款：** 若下调先退原价，再收 50% 违约费，则调整增量变为 $1.5p_tu_t-0.5p_tv_t$。已重新优化允许下调的策略，问题 3 总费为 {f(s['sensitivity']['q3_refund']['total_cost'])} 元，问题 4-3 为 {f(s['sensitivity']['q4_3_refund']['total_cost'])} 元。它们属于替代合约结果，未覆盖主 Excel；参数沿用主情景，不声称退款情景下又做了全参数最优化。
- **未来价格可见性：** 仅把未来价格替换成先知值、其他信息仍因果时，问题 4-2 为 {f(s['sensitivity']['q4_2_known_price']['total_cost'])} 元，问题 4-3 为 {f(s['sensitivity']['q4_3_known_price']['total_cost'])} 元。该结果不可作为实际提前已知电价的证据，也不是全知负荷/光伏的理论下界。

### 8.2 风险与日末储备敏感性

| 情景 | 正式评价期总费用 / 元 | 紧急购电 / kWh | 未利用电量 / kWh |
| --- | ---: | ---: | ---: |
'''
    for key,label in [('q2_tau0.5','问题2 α=0.50'),('q2_tau0.7','问题2 α=0.70'),('q2_tau0.9','问题2 α=0.90'),
                      ('q3_tau0.5','问题3 α=0.50'),('q3_tau0.7','问题3 α=0.70'),('q3_tau0.9','问题3 α=0.90'),
                      ('q3_terminal3000','问题3 计划末储备≥3000'),('q3_terminal9000','问题3 计划末储备≥9000')]:
        x=s['sensitivity'][key];text+=f"| {label} | {f(x['total_cost'])} | {f(x['emergency_kwh'])} | {f(x['spill_kwh'])} |\n"
    text+='''
分位提高一般会减少紧急电，但过购与未利用电增多。表中逐一改变分位或末库存要求，其他配置沿用修订后主策略；这些全年敏感性不参与参数选择。1 月短窗口与正式期季节不同，选中参数并不保证正式期费用最低。储备敏感性改变的是计划控制规则，实际仍无日末重置；这些参考轨迹也从 1 月 1 日连续运行。

### 8.3 日前点预测误差

| 预测策略 | 负载 MAE / kW | 光伏 MAE / kW | 净负荷 MAE / kW | 价格 MAE /（元/kWh） |
| --- | ---: | ---: | ---: | ---: |
'''
    for key,name in NAMES.items():
        x=s['forecast_accuracy'][key]
        text+=f"| {name} | {f(x['load_mae_kw'])} | {f(x['pv_mae_kw'])} | {f(x['net_mae_kw'])} | {f(x['price_mae'],5)} |\n"
    text+=rf'''
这些是正式区间的 00 点原始点预测误差，不是加风险分位后的误差。问题 3、4-3 使用各自选中的融合权重。费用还由储能库存、调整合约、分位与实时控制共同决定，不能仅靠预测 MAE 宣称某策略更省钱；新增小时预报的经济贡献应看第 5 节保持其他输入一致的对照。光伏夜间有大量零值，因此不报告失真的普通 MAPE。

### 8.4 局限与可继续研究的方向

1. 后续方案是逐点分位规划与贪心反馈，没有完整建模联合时序不确定性，也没有全局最优或概率约束证明。
2. 计划只优化当天剩余区间，附件 3 超出当天的预报已正确读取，但没有利用它们构造跨日价值函数。日末参考储备是近似处理。
3. 主反馈没有按未来高低价格分配电池库存。第二轮已另行实现并比较确定性价格感知反馈，但它的午夜零终端价值仍是近似，也没有完整联合不确定性模型；多情景 MPC 的情景建模、共享当前控制和稳健性分析尚未实现。
4. 单年数据和 1 月短窗口不足以证明多年稳健。融合模型族是在评审后扩展的；即使权重只以 1 月费用选择，也不能抹去模型开发已经看到全年表现的事实。第二轮按月选参仍是同年再分析；真正未见过的外部年度数据尚缺，接入协议不等于实证已经完成。
5. 未计老化、网络输电约束、逆变器非线性与响应延迟。题面没给这些参数，不能人为编造后输出更“真实”的数字。主、逐笔及退款合约只是明确列出的解释情景，不能替题面确认真实交易制度。

{round2_section}## 9. 可复现与独立核验

完整计算流程见 [项目说明](../README.md)。所有金额由未四舍五入的 10 分钟数据计算，论文只显示两位小数；Excel 保留底层精度。两位小数的逐行显示数重新相加与总计可能有末位差异。

- 数据核验：完整日期、列时刻、预报发布次序、非负/有限值、整点插值还原与梯形积分守恒、原始附件哈希不变。
- 独立物理与费用核验：{v['check_count']} 项通过，覆盖四种策略全年每一段的供电平衡、90% 损耗、1200–10800 kWh 边界、5000 kW 功率、互斥、跨日连续、原始计划不变、修订时间范围及各项费用。物理可行和费用自洽不能证明库存分配最优、预报具有经济价值或合约解释唯一正确。
- 修订实验核验：[专项验证](../outputs/experiments/revision/validation.json) 共 {rv['check_count']} 项通过，检查新增基准、严格小时预报对照和逐笔合约归档；[合约检查脚本](../scripts/test_contracts.py) 检查冻结路径收费与重新优化的区别。完整参数候选和情景配置保存在 [修订实验 JSON](../outputs/experiments/revision/experiments.json)。
{round2_evidence_line}- 因果篡改试验：96 个点预测用例修改决策后真值或尚未发布预报，当前预测不变；48 个风险预测用例修改当日及未来残差，当前风险预测不变。另有两个修改已到达信息的正向对照，确认检验确实能感知可用输入。
- 问题 1 最优性：纯 LP 与独立互斥 MILP 一致，MIP gap 为 0。后续四种策略只验证可行性和结算，不借用问题 1 证明它们全局最优。
- Excel 核验：五个输出均重新读取，与模型 JSON 全量对照；计划、调整、六个四小时充放电聚合、日初日末 SOC、连续紧急区间及全天总量/费用一致。模板预览已检查，标签错位修复见 [模板说明](modeling/template-spec.md)。

验收证据为 [物理/因果验证 JSON](../outputs/main/validation.json)、[修订专项验证 JSON](../outputs/experiments/revision/validation.json)、[问题1 MILP 验证 JSON](../outputs/main/q1-milp-verification.json)、[模板/Excel 验证 JSON](../outputs/verification/workbook-verification.json)。[全年逐段归档](../outputs/main/dispatch.npz) 保存包括 1 月热启动在内的计划、最终交付、充放电、SOC、紧急电、未利用量、三次修订快照及费用；新增对照的配置和汇总在 [修订实验 JSON](../outputs/experiments/revision/experiments.json)，逐段路径在 [修订调度归档](../outputs/experiments/revision/dispatch.npz)，由同一计算脚本复现。

## 参考文献

1. Wytock M, Moehle N, Boyd S. Dynamic Energy Management with Scenario-Based Robust MPC. *2017 American Control Conference*, 2042–2047. [作者原文](https://web.stanford.edu/~boyd/papers/pdf/dyn_ener_man_acc.pdf)。用于解释标准滚动能源优化与场景非预知控制，不代表本文已实现其模型。
2. Perez-Pineiro D, Skogestad S, Boyd S. Home Energy Management with Dynamic Tariffs and Tiered Peak Power Charges. Manuscript, June 2023. [作者论文页](https://stanford.edu/~boyd/papers/hem.html)。用于动态电价预测控制与全知策略参考的边界；未移用该文的峰值费用或实验节省率。
3. Huangfu Q, Hall J A J. Parallelizing the dual revised simplex method. *Mathematical Programming Computation*, 2018, 10(1):119–142. [DOI](https://link.springer.com/article/10.1007/s12532-017-0130-5)，[HiGHS 官方](https://highs.dev/)。作为 LP 解算算法来源。
4. SciPy community. linprog(method='highs'). [官方文档](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html)。用于实现线性约束、边界和成功状态检查。实际运行版本见 summary.json。

文献链接及支持范围经过官方或作者原站核验。题目参数与附件事实直接来源于用户提供材料，文献不能代替题意中的退款、效率或价格可见性假设。
'''
    # Raw f-strings above escape LaTeX consistently; Markdown needs single slashes.
    (ROOT/'docs/solution.md').write_text(text.replace('\\\\','\\'),encoding='utf-8',newline='\n')
    if round2_text:
        response_path=ROOT/'docs/reviews/round2-response.md'
        response=response_path.read_text(encoding='utf-8')
        opening='<!-- BEGIN ROUND2 RESULTS -->'
        closing='<!-- END ROUND2 RESULTS -->'
        before,rest=response.split(opening,1)
        _,after=rest.split(closing,1)
        response_text=round2_text.replace('新增控制器定义及对第二轮意见的逐项回应见 [第二轮回应](reviews/round2-response.md)；',
                                          '控制器定义及建模边界见本文件第 1 节；')
        response_text = response_text.replace('](../outputs/', '](../../outputs/').replace('](modeling/', '](../modeling/')
        response_path.write_text(before+opening+'\n\n'+response_text+'\n\n'+closing+after,
                                 encoding='utf-8',newline='\n')
    readme = (ROOT/'README.md').read_text(encoding='utf-8').splitlines()
    rows = {
        '| 1:': f"| 1：确定性日循环 | [result1.xlsx](outputs/deliverables/result1.xlsx) | {f(s['q1']['cost'])} 元/天 |",
        '| 2:': f"| 2：固定电价，无日内调整 | [result2.xlsx](outputs/deliverables/result2.xlsx) | {f(p['q2']['total_cost'])} 元 |",
        '| 3:': f"| 3：固定电价，有日内调整 | [result3.xlsx](outputs/deliverables/result3.xlsx) | {f(p['q3']['total_cost'])} 元 |",
        '| 4-2:': f"| 4-2：波动电价，无日内调整 | [result4-2.xlsx](outputs/deliverables/result4-2.xlsx) | {f(p['q4_2']['total_cost'])} 元 |",
        '| 4-3:': f"| 4-3：波动电价，有日内调整 | [result4-3.xlsx](outputs/deliverables/result4-3.xlsx) | {f(p['q4_3']['total_cost'])} 元 |",
    }
    for i,line in enumerate(readme):
        for prefix,row in rows.items():
            if line.replace('：',':').startswith(prefix):
                readme[i] = row
                break
    (ROOT/'README.md').write_text('\n'.join(readme)+'\n',encoding='utf-8',newline='\n')
    print('Generated docs/solution.md and refreshed README result table.'+
          ('' if args.markdown_only else ' Refreshed 3 figures (PNG/SVG).'))


if __name__=='__main__':
    main()
