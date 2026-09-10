"""Generate the Chinese Markdown solution and standalone scientific figures."""
from pathlib import Path
import json
import sys
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
    ax.set_title('问题 3：启用不同预报时刻的策略消融',loc='left',fontweight='bold')
    fig.savefig(target/'forecast-ablation.png');fig.savefig(target/'forecast-ablation.svg');plt.close(fig)
    # Matplotlib emits trailing spaces inside SVG paths; normalize only whitespace.
    for svg in target.glob('*.svg'):
        svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',
                       encoding='utf-8',newline='\n')


def main():
    data=dict(np.load(ROOT/'data/processed/data.npz'))
    d=dict(np.load(OUT/'dispatch.npz'))
    s=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    v=json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
    figures(data,d,s)
    p=s['primary']
    saving=p['q2']['total_cost']-p['q3']['total_cost']
    saving4=p['q4_2']['total_cost']-p['q4_3']['total_cost']
    text=rf'''# 微网与外部电网电力调控策略：模型、计算与可复现结果

## 摘要

本文完成题目四问，以 10 分钟为步长，统一描述电力平衡、储能损耗与购电结算。问题 1 在给定预测和日循环边界下用线性规划求得全局最优，全天购电 **{f(s['q1_grid_kwh'])} kWh**，购电费 **{f(s['q1']['cost'])} 元**。独立加入充放电互斥的混合整数规划得到相同目标值。

问题 2—4 采用“历史预测—风险分位规划—实时安全反馈”的可行策略。所有计划只使用决策时刻已到达的信息；1 月用于训练、参数验证及从 6000 kWh 开始的热启动，正式结果覆盖 2025 年 2 月 1 日至 12 月 31 日，共 334 天、48,096 个区间。固定电价下，问题 3 总费用比问题 2 减少 **{f(saving)} 元（{saving/p['q2']['total_cost']:.2%}）**；波动电价下减少 **{f(saving4)} 元（{saving4/p['q4_2']['total_cost']:.2%}）**。紧急电计入费用并消除缺供，储电量逐日连续。

后续问题包含预测误差和控制近似，本文不声称其结果为严格随机全局最优。正式策略的参数由 1 月确定，测试期敏感性中出现更便宜的参数也不回流修改主结果。

**关键词：** 微网；储能调度；线性规划；因果回测；风险分位；实时电价。

## 1. 题目理解与数据审查

题面为 [C 题 PDF](../problem/C题.pdf)，原始输入为 [附件目录](../data/raw/)。完整审计见 [数据审计](data-audit.md)，计算前的判断与修正过程见 [决策记录](decisions.md)，独立方法审查见 [模型审查](model-review.md)。

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

及第 2 节约束。实现有 $5\times144=720$ 个连续变量和 $2\times144=288$ 个线性等式，用 SciPy/HiGHS 求解 [3,4]。数值选解项为 $10^{{-6}}\sum(c_t+d_t)+10^{{-7}}\sum w_t$，只用于选解，不计入报告电费。与纯电费目标差为 **{s['q1']['optimality_gap_yuan']:.3g} 元**。独立 MILP 增加 144 个二元变量，也获得相同费用，见 [MILP 验证结果](../outputs/q1-milp-verification.json)。

**表 1：指定时段与全天购电。**

{table1(d['q1_grid'],s['q1']['cost'])}

**表 2：指定区间充放电与日初、日末储电量。**

{table2(d['q1_charge'],d['q1_discharge'],d['q1_soc'])}

![问题1最优调度](../outputs/figures/q1-dispatch.png)

电池在低价/光伏富余段积累能量，在高价段替代外网购电。每充入 1 kWh 只能最终输出 0.81 kWh，纯套利至少要求放电时段的替代电价大于充电时段电价除以 0.81。容量及功率约束决定不能把全部负荷都移至最低价段。完整 144 段见 [result1.xlsx](../outputs/result1.xlsx)。

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

这是可执行的安全反馈启发式，未优化跨价格时段分配紧急电的电池库存，不应称作严格最优 MPC。滚动优化、仅执行当前动作的标准能源 MPC 方法可参见 [1,2]；本文采用更轻量的确定性风险计划和显式反馈。

## 5. 问题 3：预报更新、调整结算及信息价值

00 点以附件 3 最新光伏预报替换历史光伏预测。06、12、18 点读取新发布预报，并用已经完成的最近 18 个十分钟段修正负载预测水平：历史预测乘以“已观测均值/此前预测均值”，比例截断在 0.75–1.25。预报整点插值不使用未来光伏实测。每个发布时间有各自过去 28 天的预测残差池，参数仍按 1 月选定，问题 3 为 $\alpha={s['parameters']['q3']}$。

### 5.1 主结算口径

令 $u_t=(q_t-g_t)_+$，$v_t=(g_t-q_t)_+$。题面未写下调是否退款，主解释采用原计划仍付款、另收违约费用：

$$C_3=\sum_t[p_tg_t+1.5p_tu_t+0.5p_tv_t+5p_te_t].$$

每次更新只优化未交付的剩余区间，保留原始 00 点 $g_t$ 作为唯一基准。按**最终交付量**相对原计划结算一次，不把三次修订的整张表分别累计计费；这也假设尚未交付的先前增购可以再次修订而不另收路径费用。

允许放弃过购电时，下调至 $q_t<g_t$ 受支配：改成 $q_t=g_t$ 并将增加量全部不接收，物理状态不变，还节省 $0.5p_t(g_t-q_t)$。因此主规划直接限制 $q_t\ge g_t$。更新 LP 的有效变量成本为 $1.5\sum_t\widehat p_tq_t$，原计划常数项不影响最优决策。实际执行仍用第 4.3 节规则。

### 5.2 是否需要其他时刻预报

仅对比问题 2 和问题 3 无法隔离日内预报的贡献，因为两者 00 点的信息本来就不同。下面保持同一预测器、参数、规划器、反馈规则及 1 月 1 日初始状态，仅改变启用的预报更新时刻。不同 SOC 轨迹会影响次日原计划，所以这是**完整策略消融**，不是冻结逐日 $g_t$ 的静态比较。

| 启用时刻 | 2—12 月总费用 / 元 | 紧急购电 / kWh |
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
全部时刻比仅 00 点预报节省 {f(ablation_gain)} 元（{ablation_gain/s['sensitivity']['q3_midnight_only']['total_cost']:.2%}），在全部八种更新组合中费用最低。18 点调度更新同时利用当前 SOC 和已观测负荷偏差，即使当晚光伏很小，也可通过提前增购替代 5 倍紧急购电。**本数据及本策略下，值得引入 06、12、18 点更新。** 这不是“每次新预报必然更准确”的一般结论。

![日内预报消融](../outputs/figures/forecast-ablation.png)

## 6. 问题 4：波动价格的因果决策

沿用问题 2、3，仅将优化器中的价格替换为历史预测价格。00 点价格预测同样取最近四个相隔 7 天的电价曲线，衰减 0.55；不足 7 天用最近 7 天衰减 0.8，1 月 1 日使用题目已提供的固定价曲线。问题 4-3 日内更新使用已完成最近 18 段的实价/预测价均值之比，截断在 0.5–1.5，修正剩余价曲线。

购电计划、追加和紧急电的最终费用一律按附件 4 对应区间真实价格结算。问题 4-2 选定分位 {s['parameters']['q4_2']}，问题 4-3 为 {s['parameters']['q4_3']}。价格未来真值只在专门标明的先知参考中进入优化，主 Excel 不含先知结果。

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
分位提高一般会减少紧急电，但过购与未利用电增多。问题 3 的测试期 α=0.50 比 1 月选出的 0.65 更便宜，说明短验证窗口存在季节泛化不足；本文保留预先锁定的主参数，不能用测试期最低费用倒选后宣称无泄漏。储备敏感性改变的是计划控制规则，实际仍无日末重置；这些参考轨迹也从 1 月 1 日连续运行。

### 8.3 日前点预测误差

| 预测策略 | 负载 MAE / kW | 光伏 MAE / kW | 净负荷 MAE / kW | 价格 MAE /（元/kWh） |
| --- | ---: | ---: | ---: | ---: |
'''
    for key,name in NAMES.items():
        x=s['forecast_accuracy'][key]
        text+=f"| {name} | {f(x['load_mae_kw'])} | {f(x['pv_mae_kw'])} | {f(x['net_mae_kw'])} | {f(x['price_mae'],5)} |\n"
    text+='''
这些是正式区间的 00 点原始点预测误差，不是加风险分位后的误差。附件 3 的日前光伏预报 MAE 在本数据中高于历史预测，但日内更新与实时库存共同改善了费用；不能仅靠预测 MAE 宣称某策略更省钱。光伏夜间有大量零值，因此不报告失真的普通 MAPE。

### 8.4 局限与可继续研究的方向

1. 后续方案是逐点分位规划与贪心反馈，没有完整建模联合时序不确定性，也没有全局最优或概率约束证明。
2. 计划只优化当天剩余区间，附件 3 超出当天的预报已正确读取，但没有利用它们构造跨日价值函数。日末参考储备是近似处理。
3. 反馈没有按未来高低价格分配电池库存。可进一步用多情景 MPC，只执行当前动作并共享当前控制以遵守非预知性；需额外的场景建模和独立滚动验证，本文未声称已经实现。
4. 单年数据和 1 月短窗口不足以证明多年稳健；未计老化、网络输电约束、逆变器非线性与响应延迟。题面没给这些参数，不能人为编造后输出更“真实”的数字。

## 9. 可复现与独立核验

完整计算流程见 [项目说明](../README.md)。所有金额由未四舍五入的 10 分钟数据计算，论文只显示两位小数；Excel 保留底层精度。两位小数的逐行显示数重新相加与总计可能有末位差异。

- 数据核验：完整日期、列时刻、预报发布次序、非负/有限值、整点插值还原与梯形积分守恒、原始附件哈希不变。
- 独立物理与费用核验：179 项通过，覆盖四种策略全年每一段的供电平衡、90% 损耗、1200–10800 kWh 边界、5000 kW 功率、互斥、跨日连续、原始计划不变、修订时间范围及各项费用。
- 因果篡改试验：96 个点预测用例修改决策后真值或尚未发布预报，当前预测不变；48 个风险预测用例修改当日及未来残差，当前风险预测不变。另有两个修改已到达信息的正向对照，确认检验确实能感知可用输入。
- 问题 1 最优性：纯 LP 与独立互斥 MILP 一致，MIP gap 为 0。后续四种策略只验证可行性和结算，不借用问题 1 证明它们全局最优。
- Excel 核验：五个输出均重新读取，与模型 JSON 全量对照；计划、调整、六个四小时充放电聚合、日初日末 SOC、连续紧急区间及全天总量/费用一致。模板预览已检查，标签错位修复见 [模板说明](template-spec.md)。

验收证据为 [物理/因果验证 JSON](../outputs/validation.json)、[问题1 MILP 验证 JSON](../outputs/q1-milp-verification.json)、[模板/Excel 验证 JSON](../outputs/workbook-verification.json)。[全年逐段归档](../outputs/dispatch.npz) 保存包括 1 月热启动在内的计划、最终交付、充放电、SOC、紧急电、未利用量、三次修订快照及费用，可追溯论文中的每个数字。

## 参考文献

1. Wytock M, Moehle N, Boyd S. Dynamic Energy Management with Scenario-Based Robust MPC. *2017 American Control Conference*, 2042–2047. [作者原文](https://web.stanford.edu/~boyd/papers/pdf/dyn_ener_man_acc.pdf)。用于解释标准滚动能源优化与场景非预知控制，不代表本文已实现其模型。
2. Perez-Pineiro D, Skogestad S, Boyd S. Home Energy Management with Dynamic Tariffs and Tiered Peak Power Charges. Manuscript, June 2023. [作者论文页](https://stanford.edu/~boyd/papers/hem.html)。用于动态电价预测控制与全知策略参考的边界；未移用该文的峰值费用或实验节省率。
3. Huangfu Q, Hall J A J. Parallelizing the dual revised simplex method. *Mathematical Programming Computation*, 2018, 10(1):119–142. [DOI](https://link.springer.com/article/10.1007/s12532-017-0130-5)，[HiGHS 官方](https://highs.dev/)。作为 LP 解算算法来源。
4. SciPy community. linprog(method='highs'). [官方文档](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html)。用于实现线性约束、边界和成功状态检查。实际运行版本见 summary.json。

文献链接及支持范围经过官方或作者原站核验。题目参数与附件事实直接来源于用户提供材料，文献不能代替题意中的退款、效率或价格可见性假设。
'''
    # Raw f-strings above escape LaTeX consistently; Markdown needs single slashes.
    (ROOT/'docs/solution.md').write_text(text.replace('\\\\','\\'),encoding='utf-8',newline='\n')
    print('Generated docs/solution.md and 3 figures (PNG/SVG).')


if __name__=='__main__':
    main()
