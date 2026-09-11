"""Generate question-specific tables, figures and numbers from archived evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from build_paper_tables import table, number, param, DATES
from model import build_cache, risk_forecast

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "paper/generated"
FIG = ROOT / "outputs/figures"


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main():
    study_validation = read("outputs/experiments/paper-study/validation.json")
    assert study_validation["status"] == "passed"
    for name, expected in study_validation["source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    s, r, r2 = [read(f) for f in ("outputs/main/summary.json", "outputs/experiments/revision/experiments.json", "outputs/experiments/round2/experiments.json")]
    study = read("outputs/experiments/paper-study/sensitivity.json")
    a, d = np.load(ROOT / "outputs/main/dispatch.npz"), np.load(ROOT / "data/processed/data.npz")
    p = s["primary"]
    files, numbers, figures = {}, {}, []

    def value(key, x, digits=2):
        numbers[key] = number(x, digits)

    def save_table(name, caption, headers, rows, spec=None):
        files[name + ".tex"] = table(caption, "tab:" + name, headers, rows, spec=spec)

    q1_rows = []
    base = s["q1"]["cost"]
    for kind, name, settings in (("usable", "可用容量/kWh", (7680, 9600, 11520)),
                                  ("power", "功率上限/kW", (4000, 5000, 6000)),
                                  ("eta", "单向效率", (.85, .9, .95))):
        for setting in settings:
            row = study["q1"][f"q1_{kind}_{setting:g}"]
            q1_rows.append([name, param(setting), number(row["cost"]), number((row["cost"]/base-1)*100)])
    save_table("q1-sensitivity", "问题一的单参数扰动与最低电费", ["扰动参数", "取值", "费用/元", "费用变化/\\%"], q1_rows)
    no_storage = study["q1"]["q1_no_storage_0"]["cost"]
    value("q1-no-storage-cost", no_storage)
    value("q1-storage-saving", no_storage-base)
    value("q1-storage-saving-percent", (no_storage-base)/no_storage*100)
    for key, arr in (("load", d["q1_load"]/6), ("pv", d["q1_pv"]/6), ("charge", a["q1_charge"]),
                     ("discharge", a["q1_discharge"]), ("unused", a["q1_spill"])):
        value("q1-" + key, arr.sum())
    value("q1-cycle-loss", a["q1_charge"].sum()-a["q1_discharge"].sum())
    value("q1-trapezoid-cost", s["q1_trapezoid_cost"])
    value("q1-roundtrip-cost", s["q1_roundtrip90_cost"])
    metrics = [("原计划费/元", "plan_cost"), ("调整费/元", "adjustment_cost"), ("紧急费/元", "emergency_cost"),
               ("总费用/元", "total_cost"), ("常规购电/kWh", "adjusted_kwh"), ("紧急购电/kWh", "emergency_kwh"),
               ("未利用电量/kWh", "spill_kwh"), ("发生紧急购电的天数", "emergency_days"),
               ("期初储电量/kWh", "start_soc"), ("期末储电量/kWh", "end_soc")]
    save_table("q2-summary", "问题二的累计结果（2025年2—12月）", ["指标", "数值"],
               [[label, number(p["q2"][key])] for label, key in metrics
                if key in ("plan_cost", "emergency_cost", "total_cost", "adjusted_kwh", "emergency_kwh")])
    save_table("q3-comparison", "固定电价下两种策略的结果（2—12月）", ["指标", "零时固定计划", "日内调整计划"],
               [[label, *[number(p[k][key], 0 if key == "emergency_days" else 2) for k in ("q2", "q3")]] for label, key in metrics])
    save_table("q4-comparison", "波动电价下两种策略的结果（2—12月）", ["指标", "问题4-2", "问题4-3"],
               [[label, *[number(p[k][key], 0 if key == "emergency_days" else 2) for k in ("q4_2", "q4_3")]] for label, key in metrics])
    for key in ("q2", "q3"):
        rows = []
        for alpha in sorted({.5, .7, .9, s["parameters"][key]}):
            stat = p[key] if alpha == s["parameters"][key] else s["sensitivity"][f"{key}_tau{alpha:g}"]
            rows.append([param(alpha), number(stat["total_cost"]), number(stat["emergency_kwh"]), number(stat["end_soc"])])
        save_table(key + "-risk-sensitivity", f"{'问题二' if key=='q2' else '问题三'}的分位参数扰动（2—12月）",
                   [r"$\alpha$", "总费用/元", "紧急购电/kWh", "年末储电量/kWh"], rows)
    rows = []
    for reserve in (3000, 6000, 9000):
        stat = p["q3"] if reserve == 6000 else s["sensitivity"][f"q3_terminal{reserve}"]
        rows.append([str(reserve), number(stat["total_cost"]), number(stat["start_soc"]), number(stat["end_soc"])])
    save_table("q3-reserve", "日末预测储备目标的变化（2—12月）", ["目标/kWh", "总费用/元", "期初储电量/kWh", "期末储电量/kWh"], rows)
    for key in ("q2", "q3"):
        rows = []
        for date in DATES:
            day = list(d["dates"]).index(date)
            rows.append([date[5:], number(a[key+"_adjusted"][day].sum()), number(a[key+"_emergency"][day].sum()), number(a[key+"_costs"][day, 3])])
        save_table(key + "-days-summary", f"{'问题二' if key=='q2' else '问题三'}的指定日期结果（2025年）",
                   ["日期", "常规购电/kWh", "紧急购电/kWh", "全天总费用/元"], rows)
    rows = []
    for date in DATES:
        day = list(d["dates"]).index(date)
        rows.append([date[5:], *[number(a[k+"_costs"][day, 3]) for k in ("q4_2", "q4_3")],
                     number(a["q4_2_costs"][day, 3]-a["q4_3_costs"][day, 3])])
    save_table("q4-days-summary", "波动电价下指定日期费用（2025年，元）", ["日期", "问题4-2", "问题4-3", "日内方案节省"], rows)
    for key, label in (("q3", "问题三"), ("q4_3", "问题4-3")):
        rows = []
        for kind, scene_id in (("纯历史", r["baselines"][key]["historical_common_warmup"]),
                               ("纯附件三", r["baselines"][key]["pure_attachment3"]), ("融合", key+"_selected")):
            scene = r["scenes"][scene_id]
            rows.append([kind, param(scene["pv_weight"]), param(scene["quantile"]), number(scene["summary"]["total_cost"])])
        save_table(key.replace("_", "-") + "-forecast", f"{label}的光伏预测基准（共同热启动，2—12月）",
                   ["预测来源", r"$\lambda$", r"$\alpha$", "总费用/元"], rows)
    rows = []
    for alpha in (.5, .65, .7, .8, .9, .95):
        vals = [next(c["validation_cost"] for c in s["calibration"][k] if c["quantile"] == alpha) for k in ("q4_2", "q4_3")]
        rows.append([param(alpha), *[number(v) for v in vals]])
    save_table("q4-calibration", "波动电价的1月分位评分（1月15—31日）", [r"$\alpha$", "问题4-2费用/元", "问题4-3费用/元"], rows)
    rows = []
    for key in ("q4_2", "q4_3"):
        for theta in (-.2, 0, .2):
            stat = p[key] if theta == 0 else study["q4"][f"{key}_spread_{theta:+.1f}"]["summary"]
            rows.append([key.replace("q", "问题").replace("_", "-"), f"{theta:+.1f}" if theta else "0",
                         number(stat["total_cost"]), number(stat["total_cost"]-p[key]["total_cost"]), number(stat["end_soc"])])
    save_table("q4-price-sensitivity", "预测价差幅度扰动（共同热启动，2—12月）",
               ["方案", r"$\theta$", "总费用/元", "较主方案增费/元", "期末储电量/kWh"], rows)
    for key in ("q4_2", "q4_3"):
        ref = s["sensitivity"][key+"_known_price"]["total_cost"]
        value(key.replace("_", "-")+"-oracle", ref)
        value(key.replace("_", "-")+"-oracle-saving", p[key]["total_cost"]-ref)
    value("q3-per-trade-cost", r["scenes"][r["contracts"]["q3"]["reoptimized"]]["summary"]["total_cost"])

    plt.rcParams.update({"font.family": "SimSun", "font.size": 11, "axes.unicode_minus": False,
                         "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": .2, "legend.frameon": False})
    colors = ["#176B87", "#B3541E", "#446B3C", "#704C90"]

    def finish(fig, name):
        fig.savefig(FIG / (name+".pdf"), bbox_inches="tight")
        fig.savefig(FIG / (name+".png"), dpi=170, bbox_inches="tight")
        figures.extend(["outputs/figures/" + name + suffix for suffix in (".pdf", ".png")])
        plt.close(fig)

    hours = np.arange(144)/6
    fig, ax = plt.subplots(2, 1, figsize=(7.4, 4.3), sharex=True, layout="constrained")
    for name, label, color, ls in (("q1_grid", "外网购电", colors[0], "-"), ("q1_charge", "充电输入", colors[1], "--"), ("q1_discharge", "放电输出", colors[2], "-.")):
        ax[0].step(hours, a[name]*6, where="post", label=label, color=color, ls=ls, lw=1.2)
    ax[0].set_ylabel("功率/kW"); ax[0].legend(ncol=3, loc="lower left", bbox_to_anchor=(0, 1.02))
    ax[1].plot(np.arange(145)/6, a["q1_soc"], color=colors[0], label="储电量")
    ax[1].axhline(1200, color="gray", ls=":"); ax[1].axhline(10800, color="gray", ls=":")
    right = ax[1].twinx(); right.grid(False); right.plot(hours, d["fixed_price"], color=colors[1], ls="--", label="电价")
    right.set_ylabel("电价/(元/kWh)"); ax[1].set_ylabel("储电量/kWh"); ax[1].set_xlabel("时刻/h")
    ax[1].legend(loc="lower left", bbox_to_anchor=(0, 1.02))
    right.legend(loc="lower right", bbox_to_anchor=(1, 1.02))
    ax[1].set_xticks(np.arange(0, 25, 4)); ax[1].set_xlim(0, 24)
    finish(fig, "paper-q1-dispatch")

    day = list(d["dates"]).index("2025-09-23")
    cache = build_cache(d, forecast=False)
    fig, ax = plt.subplots(2, 1, figsize=(7.4, 3.6), sharex=True, layout="constrained")
    for arr, label, color, ls in (((d["load"][day]-d["pv"][day])/6, "实际净负荷", "#333333", "-"),
                                 (risk_forecast(cache, day, 0, .8), "风险净负荷", colors[2], "--"),
                                 (a["q2_plan"][day], "零时购电计划", colors[0], "-.")):
        ax[0].plot(hours, arr*6, label=label, color=color, ls=ls, lw=1.2)
    ax[0].set_ylabel("功率/kW"); ax[0].legend(ncol=3, loc="lower left", bbox_to_anchor=(0, 1.02))
    ax[1].plot(np.arange(145)/6, a["q2_soc"][day], color=colors[0], label="储电量")
    ax[1].axhline(1200, color="gray", ls=":")
    right = ax[1].twinx(); right.grid(False); right.bar(hours, a["q2_emergency"][day], width=1/6, color=colors[1], alpha=.65, label="紧急购电")
    ax[1].set_ylabel("储电量/kWh"); right.set_ylabel("每段紧急电量/kWh"); ax[1].set_xlabel("时刻/h")
    ax[1].legend(loc="lower left", bbox_to_anchor=(0, 1.02))
    right.legend(loc="lower right", bbox_to_anchor=(1, 1.02))
    ax[1].set_xticks(np.arange(0,25,4)); ax[1].set_xlim(0,24)
    finish(fig, "paper-q2-day")

    fig, ax = plt.subplots(2, 1, figsize=(7.4, 4.2), sharex=True, layout="constrained")
    ax[0].plot(hours, d["load"][day]-d["pv"][day], color="#333333", label="实际净负荷", lw=1.2)
    ax[0].step(hours, a["q3_plan"][day]*6, where="post", color=colors[0], ls="--", label="零时原计划")
    ax[0].step(hours, a["q3_adjusted"][day]*6, where="post", color=colors[1], label="最终常规购电")
    ax[0].set_ylabel("功率/kW"); ax[0].legend(ncol=3, loc="lower left", bbox_to_anchor=(0, 1.02))
    for key, color in (("q2", colors[0]), ("q3", colors[1])):
        ax[1].plot(np.arange(145)/6, a[key+"_soc"][day], color=color, label="固定计划" if key=="q2" else "日内调整")
    for axis in ax:
        for h in (6,12,18): axis.axvline(h, color="gray", lw=.8, ls=":")
    ax[1].set_ylabel("储电量/kWh"); ax[1].set_xlabel("时刻/h")
    ax[1].legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.02))
    ax[1].set_xticks(np.arange(0,25,4)); ax[1].set_xlim(0,24)
    finish(fig, "paper-q3-day")

    fig, ax = plt.subplots(2, 1, figsize=(7.4, 4.2), sharex=True, layout="constrained")
    months = np.arange(2,13)
    for key, color, ls in (("q4_2", colors[0], "-"), ("q4_3", colors[1], "--")):
        masks = [np.array([str(date)[5:7] == f"{m:02d}" for date in d["dates"]]) for m in months]
        ax[0].plot(months, [a[key+"_costs"][mask,3].sum()/10000 for mask in masks], marker="o", ms=4, color=color, ls=ls, label=key.replace("q", "问题").replace("_", "-"))
        ax[1].plot(months, [a[key+"_emergency"][mask].sum()/1000 for mask in masks], marker="o", ms=4, color=color, ls=ls)
    ax[0].set_ylabel("月费用/万元")
    ax[0].legend(ncol=2, loc="lower left", bbox_to_anchor=(0, 1.02))
    ax[1].set_ylabel("紧急购电/MWh"); ax[1].set_xlabel("月份")
    ax[1].set_xticks(months)
    finish(fig, "paper-q4-months")

    files["evidence-numbers.tex"] = "\n".join(rf"\expandafter\def\csname PaperData{key}\endcsname{{{val}}}" for key, val in numbers.items()) + "\n"
    for name, content in files.items():
        (DEST / name).write_text(content, encoding="utf-8", newline="\n")
    sources = ["scripts/build_paper_evidence.py", "scripts/build_paper_tables.py", "scripts/model.py",
               "outputs/main/summary.json", "outputs/experiments/revision/experiments.json", "outputs/experiments/round2/experiments.json",
               "outputs/main/dispatch.npz", "data/processed/data.npz", "outputs/experiments/paper-study/sensitivity.json", "outputs/experiments/paper-study/validation.json"]
    manifest = dict(status="passed", source_sha256={f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in sources},
                    generated_sha256={"paper/generated/"+f: hashlib.sha256((DEST/f).read_bytes()).hexdigest() for f in files},
                    figure_sha256={f: hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in figures}, numbers=numbers,
                    provenance="Tables regroup existing verified archives; new parameter experiments are independently checked in outputs/experiments/paper-study/validation.json.")
    (DEST / "evidence-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(f"Generated {len(files)-1} tables and {len(figures)//2} figures.")


if __name__ == "__main__":
    main()
