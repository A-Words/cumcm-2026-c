"""Build paper tables from verified archives, without rerunning or changing models.

Run from any directory: ``python scripts/build_paper_tables.py``.
The generated TeX needs booktabs, array, tabularx and longtable.
Numbers are rounded only for presentation; audit data retain full precision.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "paper/generated"
KEYS = ("q2", "q3", "q4_2", "q4_3")
NAMES = {"q2": "问题2", "q3": "问题3", "q4_2": "问题4-2", "q4_3": "问题4-3"}
DATES = ("2025-03-20", "2025-06-21", "2025-09-23", "2025-12-21")
SLOTS = (60, 72, 84, 96, 108, 120)
SOURCES = (
    "outputs/summary.json", "outputs/results.json", "outputs/dispatch.npz",
    "outputs/revision-experiments.json", "outputs/revision-dispatch.npz",
    "outputs/validation.json", "outputs/revision-validation.json",
    "outputs/round2/experiments.json", "outputs/round2/dispatch.npz",
    "outputs/round2/validation.json", "outputs/q1-milp-verification.json",
    "outputs/workbook-verification.json", "data/processed/data.npz",
)


def read_json(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value, digits=2):
    value = float(value)
    if abs(value) < 0.5 * 10 ** -digits:
        value = 0.0
    return f"{value:,.{digits}f}"


def param(value):
    return f"{value:g}"


def clock(index):
    return f"{index // 6:02d}:{index % 6 * 10:02d}"


def events(values):
    active = np.asarray(values) > 1e-7
    result = []
    i = 0
    while i < 144:
        if not active[i]:
            i += 1
            continue
        start = i
        while i < 144 and active[i]:
            i += 1
        result.append((f"{clock(start)}--{clock(i)}", float(np.sum(values[start:i]))))
    return result


def table(caption, label, headers, rows, long=False, spec=None):
    """Use template-sized text and three rules; explanations belong in prose."""
    spec = spec or "l" + "r" * (len(headers) - 1)
    body = [row if isinstance(row, str) else " & ".join(map(str, row)) + r" \\" for row in rows]
    head = " & ".join(rf"\multicolumn{{1}}{{c}}{{{title}}}" for title in headers) + r" \\"
    if long:
        lines = [r"\begingroup", r"\normalsize", r"\renewcommand{\arraystretch}{1.38}",
                 rf"\begin{{longtable}}{{{spec}}}",
                 rf"\caption{{{caption}}}\label{{{label}}}\\", r"\toprule", head,
                 r"\midrule", r"\endfirsthead", rf"\multicolumn{{{len(headers)}}}{{c}}{{续表 \ref{{{label}}}}}\\",
                 r"\toprule", head, r"\midrule", r"\endhead", r"\bottomrule", r"\endfoot"]
        lines.extend(body)
        lines += [r"\end{longtable}"]
        lines.append(r"\endgroup")
    else:
        lines = [r"\begin{table}[!htbp]", r"\centering", rf"\caption{{{caption}}}\label{{{label}}}",
                 r"\normalsize", rf"\begin{{tabular}}{{{spec}}}",
                 r"\toprule", head, r"\midrule", *body, r"\bottomrule", r"\end{tabular}"]
        lines.append(r"\end{table}")
    # End the surrounding prose explicitly: an \input containing a float may
    # otherwise leave the next source sentence in the previous paragraph.
    return "\\par\n" + "\n".join(lines) + "\n\\par\n"


def keep_rows_together(rows):
    """Keep a complete dated table block on one page, allowing a break after it."""
    return [" & ".join(map(str, row)) + (r" \\*" if i < len(rows) - 1 else r" \\")
            for i, row in enumerate(rows)]


def purchase_rows(plan, total_cost, final=None):
    """One interval per row; original and final quantities have separate columns."""
    rows = [[f"{clock(i)}--{clock(i + 1)}", number(plan[i]),
             *([number(final[i])] if final is not None else [])] for i in SLOTS]
    rows.append(["全天购电量", number(sum(plan)),
                 *([number(sum(final))] if final is not None else [])])
    cost = (rf"\multicolumn{{2}}{{r}}{{{number(total_cost)}}}"
            if final is not None else number(total_cost))
    rows.append(["全天常规购电费（元）", cost])
    return rows


def storage_rows(charge, discharge, start_soc, end_soc):
    """Problem table 2: two interval/charge/discharge triples and SOC ends."""
    charge = np.asarray(charge).reshape(6, 24).sum(1)
    discharge = np.asarray(discharge).reshape(6, 24).sum(1)
    rows = []
    for a, b in ((0, 1), (2, 3), (4, 5)):
        row = []
        for i in (a, b):
            row.extend((f"{4*i:02d}:00--{4*i+4:02d}:00", number(charge[i]), number(discharge[i])))
        rows.append(row)
    rows.append([r"\multicolumn{2}{c}{00:00储电量}", number(start_soc),
                 r"\multicolumn{2}{c}{24:00储电量}", number(end_soc)])
    return rows


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    summary = read_json("outputs/summary.json")
    results = read_json("outputs/results.json")
    revision = read_json("outputs/revision-experiments.json")
    round2 = read_json("outputs/round2/experiments.json")
    validation = read_json("outputs/validation.json")
    revision_validation = read_json("outputs/revision-validation.json")
    round2_validation = read_json("outputs/round2/validation.json")
    workbook = read_json("outputs/workbook-verification.json")
    dispatch = np.load(ROOT / "outputs/dispatch.npz")
    data = np.load(ROOT / "data/processed/data.npz")
    files = {}
    checks = []
    audit = {"specified_dates": {}, "numbers": {}}

    def check(name, actual, expected, tolerance=1e-6):
        error = float(np.max(np.abs(np.asarray(actual) - np.asarray(expected))))
        if error > tolerance:
            raise ValueError(f"{name}: {error=} exceeds {tolerance=}")
        checks.append({"name": name, "max_abs_error": error, "tolerance": tolerance})

    for report in (validation, revision_validation, round2_validation):
        assert report["status"] == "passed", "Input results must pass their independent validation."
        for name, expected_hash in report.get("artifact_sha256", report.get("source_sha256", {})).items():
            path = ROOT / name.replace("\\", "/")
            assert sha256(path) == expected_hash, f"Validated input changed: {path}"
    assert workbook["passed"] and sha256(ROOT / workbook["source"]["path"]) == workbook["source"]["sha256"]

    primary = summary["primary"]
    for key in KEYS:
        s = primary[key]
        for array_key, stat_key in (("plan", "plan_kwh"), ("adjusted", "adjusted_kwh"),
                                    ("emergency", "emergency_kwh"), ("charge", "charge_kwh"),
                                    ("discharge", "discharge_kwh"), ("spill", "spill_kwh")):
            check(f"{key}.{stat_key}", dispatch[f"{key}_{array_key}"][31:].sum(), s[stat_key])
        for col, stat_key in enumerate(("plan_cost", "adjustment_cost", "emergency_cost", "total_cost")):
            check(f"{key}.{stat_key}", dispatch[f"{key}_costs"][31:, col].sum(), s[stat_key])
        check(f"{key}.start_soc", dispatch[f"{key}_soc"][31, 0], s["start_soc"])
        check(f"{key}.end_soc", dispatch[f"{key}_soc"][-1, -1], s["end_soc"])

    # Re-aggregate both experimental archives too, so tables do not only trust
    # precomputed JSON summaries. These are presentation checks, not new proofs.
    for report, archive_path, separator in (
        (revision, "outputs/revision-dispatch.npz", "_"),
        (round2, "outputs/round2/dispatch.npz", "__"),
    ):
        archive = np.load(ROOT / archive_path)
        for key, scene in report["scenes"].items():
            start = scene.get("evaluation_start_day", 31) - scene.get("day_start", 0)
            s = scene["summary"]
            for field in ("plan", "adjusted", "emergency", "charge", "discharge", "spill"):
                check(f"experiment.{key}.{field}_kwh", archive[f"{key}{separator}{field}"][start:].sum(), s[f"{field}_kwh"])
            for col, field in enumerate(("plan_cost", "adjustment_cost", "emergency_cost", "total_cost")):
                check(f"experiment.{key}.{field}", archive[f"{key}{separator}costs"][start:, col].sum(), s[field])
            check(f"experiment.{key}.start_soc", archive[f"{key}{separator}soc"][start, 0], s["start_soc"])
            check(f"experiment.{key}.end_soc", archive[f"{key}{separator}soc"][-1, -1], s["end_soc"])

    macro_values = {
        "q1-cost": number(summary["q1"]["cost"]),
        "q1-grid": number(summary["q1_grid_kwh"]),
        "base-checks": str(validation["check_count"]),
        "revision-checks": str(revision_validation["check_count"]),
        "roundtwo-checks": str(round2_validation["check_count"]),
        "q3-weight": param(summary["pv_weights"]["q3"]),
        "q3-quantile": param(summary["parameters"]["q3"]),
        "q4-3-weight": param(summary["pv_weights"]["q4_3"]),
        "q4-3-quantile": param(summary["parameters"]["q4_3"]),
        "q2-quantile": param(summary["parameters"]["q2"]),
        "q4-2-quantile": param(summary["parameters"]["q4_2"]),
    }
    for key in KEYS:
        key_tex = key.replace("_", "-")
        for stat, value in primary[key].items():
            macro_values[f"{key_tex}-{stat.replace('_', '-')}"] = number(value)
        macro_values[f"{key_tex}-cost"] = number(primary[key]["total_cost"])
        macro_values[f"{key_tex}-mpc-extra"] = number(-round2["feedback"][key]["cash_saving_yuan"])
    for key, base in (("q3", "q2"), ("q4_3", "q4_2")):
        key_tex = key.replace("_", "-")
        saving = primary[base]["total_cost"] - primary[key]["total_cost"]
        macro_values[f"{key_tex}-saving"] = number(saving)
        macro_values[f"{key_tex}-saving-percent"] = number(saving / primary[base]["total_cost"] * 100)
        macro_values[f"{key_tex}-rolling-extra"] = number(-round2["rolling"][key]["cash_saving_adaptive_vs_fixed"])
        legacy_hist = revision["scenes"][revision["baselines"][key]["historical_common_warmup"]]["summary"]
        macro_values[f"{key_tex}-vs-history-saving"] = number(legacy_hist["total_cost"] - primary[key]["total_cost"])
    for group in ("legacy", "selected"):
        subset = revision["information_ablation"][group]["hourly_subsets"]
        macro_values[f"hourly-{group}-saving"] = number(revision["scenes"][subset[0]]["summary"]["total_cost"] - revision["scenes"][subset[-1]]["summary"]["total_cost"])
    files["numbers.tex"] = "\n".join([
        r"% Use \PaperValue{key}; values are display strings without units.",
        r"\providecommand{\PaperValue}[1]{\ifcsname PaperData#1\endcsname\csname PaperData#1\endcsname\else\PackageError{paper-data}{Unknown number key: #1}{Check paper/generated/numbers.tex.}\fi}",
        *[rf"\expandafter\def\csname PaperData{key}\endcsname{{{value}}}" for key, value in macro_values.items()], ""])
    audit["numbers"] = macro_values

    files["core-costs.tex"] = table("四种主方案的正式期费用（2025年2—12月，元）", "tab:core-costs",
        ["方案", "原计划费用", "调整费用", "紧急费用", "总费用"],
        [[NAMES[k], *[number(primary[k][c]) for c in ("plan_cost", "adjustment_cost", "emergency_cost", "total_cost")]] for k in KEYS])
    files["core-energy.tex"] = table("四种主方案的正式期电量与库存（kWh）", "tab:core-energy",
        ["方案", r"\shortstack{最终常规\\购电量}", "紧急购电", "未利用电量", r"\shortstack{期初\\储电量}", r"\shortstack{期末\\储电量}"],
        [[NAMES[k], *[number(primary[k][c]) for c in ("adjusted_kwh", "emergency_kwh", "spill_kwh", "start_soc", "end_soc")]] for k in KEYS])
    files["core-storage.tex"] = table("四种主方案的原计划购电与储能吞吐量（2—12月，kWh）", "tab:core-storage",
        ["方案", "原计划购电量", "充电输入", "放电输出"],
        [[NAMES[k], *[number(primary[k][c]) for c in ("plan_kwh", "charge_kwh", "discharge_kwh")]] for k in KEYS])

    q1 = results["q1"]
    for field, archive in (("plan", "grid"), ("charge", "charge"), ("discharge", "discharge")):
        check(f"q1.json_{field}", q1[field], dispatch[f"q1_{archive}"])
    check("q1.total_grid", sum(q1["plan"]), summary["q1_grid_kwh"])
    text = table("问题1指定时段与全天购电（电量单位：kWh）", "tab:q1-purchase", ["时间段", "购电量"],
        purchase_rows(q1["plan"], summary["q1"]["cost"]))
    files["q1-tables.tex"] = text + "\n" + table("问题1六个时段的储能充放电量及首末储电量（kWh）", "tab:q1-storage", ["时间段", "充电量", "放电量"] * 2,
        storage_rows(q1["charge"], q1["discharge"], q1["socStart"], q1["socEnd"]), spec="lrrlrr")

    rows = []
    for weight in (0, .25, .5, .75, 1):
        row = [param(weight)]
        for key in ("q3", "q4_3"):
            candidate = min((c for c in revision["selection"][key]["candidates"] if c["pv_weight"] == weight), key=lambda c: c["validation_cost"])
            row += [param(candidate["quantile"]), number(candidate["validation_cost"])]
        rows.append(row)
    files["jan-selection.tex"] = table("各光伏融合权重下的1月最优分位候选", "tab:jan-selection",
        [r"$\lambda$", r"问题3的$\alpha$", "验证费（元）", r"问题4-3的$\alpha$", "验证费（元）"], rows)
    rows = []
    for c in summary["calibration"]["q2"]:
        q4c = next(x for x in summary["calibration"]["q4_2"] if x["quantile"] == c["quantile"])
        rows.append([param(c["quantile"]), number(c["validation_cost"]), number(q4c["validation_cost"])])
    files["jan-history-selection.tex"] = table("不可调整方案的1月分位候选", "tab:jan-history-selection",
        [r"$\alpha$", "问题2验证费（元）", "问题4-2验证费（元）"], rows)
    rows = []
    for key in ("q3", "q4_3"):
        for label, scene_id in (("纯附件3", revision["baselines"][key]["pure_attachment3"]),
                                ("纯历史", revision["baselines"][key]["historical_common_warmup"]),
                                ("融合主方案", f"{key}_selected")):
            scene = revision["scenes"][scene_id]
            s = scene["summary"]
            rows.append([NAMES[key], label, param(scene["pv_weight"]), param(scene["quantile"]), number(s["total_cost"]), number(s["emergency_kwh"])])
    files["forecast-baselines.tex"] = table("共同热启动下的预测策略比较（2—12月）", "tab:forecast-baselines",
        ["方案", "光伏预测", r"$\lambda$", r"$\alpha$", "费用（元）", r"\shortstack{紧急电\\（kWh）}"], rows)

    rows = []
    subset_groups = {}
    for group in ("legacy", "selected"):
        subset_groups[group] = {}
        for scene_id in revision["information_ablation"][group]["hourly_subsets"]:
            scene = revision["scenes"][scene_id]
            subset = tuple(i * 6 for i in range(1, 4) if scene["forecast_sources"][i] == i)
            subset_groups[group][subset] = scene["summary"]
    for subset, legacy in subset_groups["legacy"].items():
        selected = subset_groups["selected"][subset]
        label = "、".join(f"{hour:02d}" for hour in subset) or "无"
        rows.append([label, number(legacy["total_cost"]), number(selected["total_cost"]), number(selected["emergency_kwh"])])
    files["hourly-subsets.tex"] = table("问题3新小时光伏预报的完整子集对照", "tab:hourly-subsets",
        ["新增预报时刻", r"\shortstack{纯附件3费用\\（元）}", r"\shortstack{融合策略费用\\（元）}", r"\shortstack{融合紧急电\\（kWh）}"], rows)
    rows = []
    for hour in (6, 12, 18):
        subset = tuple(i for i in (6, 12, 18) if i != hour)
        rows.append([f"{hour:02d}点", *[number(subset_groups[g][subset]["total_cost"] - subset_groups[g][(6, 12, 18)]["total_cost"], 4) for g in ("legacy", "selected")]])
    files["hourly-marginals.tex"] = table("单独撤去一次新小时预报的条件费用差（元）", "tab:hourly-marginals",
        ["撤去的预报", "纯附件3", "融合主策略"], rows)

    rows = []
    for key in ("q3", "q4_3"):
        contract = revision["contracts"][key]
        base = primary["q2" if key == "q3" else "q4_2"]["total_cost"]
        for label, cost in (("主合约", primary[key]["total_cost"]),
                            ("冻结主调度，逐笔重计", contract["frozen_selected"]["total_cost"]),
                            ("逐笔合约重新优化", revision["scenes"][contract["reoptimized"]]["summary"]["total_cost"])):
            rows.append([NAMES[key], label, number(cost), number(base - cost)])
    files["contracts.tex"] = table("合约解释与相应策略费用（2—12月，元）", "tab:contracts",
        ["方案", "结算与策略", "总费用", r"\shortstack{较无调整\\方案节省}"], rows)
    rows = []
    for key in ("q3", "q4_3"):
        contract = revision["contracts"][key]
        selected = contract["selection"]["selected"]
        s = revision["scenes"][contract["reoptimized"]]["summary"]
        rows.append([NAMES[key], param(selected["pv_weight"]), param(selected["quantile"]), number(s["emergency_kwh"]), number(s["start_soc"]), number(s["end_soc"])])
    files["contract-parameters.tex"] = table("逐笔合约重优化的参数与库存（电量单位：kWh）", "tab:contract-parameters",
        ["方案", r"$\lambda$", r"$\alpha$", "紧急购电", r"\shortstack{2月初\\储电量}", r"\shortstack{年末\\储电量}"], rows)

    rows = []
    for key in KEYS:
        for feedback, label in (("greedy", "贪心"), ("mpc", "确定性滚动")):
            s = round2["scenes"][round2["feedback"][key][feedback]]["summary"]
            rows.append([NAMES[key], label, number(s["plan_cost"] + s["adjustment_cost"]), number(s["emergency_cost"]), number(s["total_cost"])])
    files["mpc-comparison.tex"] = table("确定性价格感知反馈与原反馈的费用比较（2—12月，元）", "tab:mpc-comparison",
        ["方案", "反馈规则", "常规购电费", "紧急购电费", "总费用"], rows)
    rows = []
    for key in KEYS:
        g = round2["scenes"][round2["feedback"][key]["greedy"]]["summary"]
        m = round2["scenes"][round2["feedback"][key]["mpc"]]["summary"]
        rows.append([NAMES[key], number(m["total_cost"] - g["total_cost"]), number(m["emergency_kwh"]), number(m["spill_kwh"]), number(m["start_soc"]), number(m["end_soc"])])
    files["mpc-inventory.tex"] = table("滚动反馈的费用增量与物理统计", "tab:mpc-inventory",
        ["方案", r"\shortstack{增费\\（元）}", r"\shortstack{紧急电\\（kWh）}", r"\shortstack{未利用电\\（kWh）}", r"\shortstack{期初SOC\\（kWh）}", r"\shortstack{期末SOC\\（kWh）}"], rows)

    rows = []
    for key in ("q3", "q4_3"):
        for rule, label in (("fixed", "固定1月参数"), ("adaptive", "上月选择融合"), ("historical", "上月选择纯历史")):
            s = round2["scenes"][round2["rolling"][key]["scenes"][rule]]["summary"]
            rows.append([NAMES[key], label, number(s["total_cost"]), number(s["emergency_kwh"]), number(s["start_soc"]), number(s["end_soc"])])
    files["rolling-summary.tex"] = table("按月选参与固定参数比较（2025年4—12月）", "tab:rolling-summary",
        ["方案", "参数规则", r"\shortstack{总费用\\（元）}", r"\shortstack{紧急电\\（kWh）}", r"\shortstack{期初SOC\\（kWh）}", r"\shortstack{期末SOC\\（kWh）}"], rows)
    rows = []
    for key in ("q3", "q4_3"):
        for fold in round2["rolling"][key]["folds"]:
            s, h, monthly = fold["selected"], fold["historical_selected"], fold["monthly"]
            rows.append([NAMES[key], fold["month"], param(s["pv_weight"]), param(s["quantile"]), param(h["quantile"]),
                         number(monthly["fixed"]["total_cost"] - monthly["adaptive"]["total_cost"]),
                         number(monthly["historical"]["total_cost"] - monthly["adaptive"]["total_cost"])])
    files["rolling-months.tex"] = table("月初参数选择及当月费用差（2025年4—12月）", "tab:rolling-months",
        ["方案", "评价月份", r"$\lambda$", r"$\alpha$", r"历史$\alpha$", r"\shortstack{固定$-$融合\\（元）}", r"\shortstack{历史$-$融合\\（元）}"], rows, long=True)

    for key in KEYS:
        chosen = [next(day for day in results[key]["days"] if day["date"] == date) for date in DATES]
        appendix = []
        name = NAMES[key]
        tag = key.replace("_", "-")
        purchase, storage, costs, all_events = [], [], [], []
        audit["specified_dates"][key] = []
        for day in chosen:
            date = day["date"]
            index = list(data["dates"]).index(date)
            final = day.get("adjusted", day["plan"])
            for field in ("plan", "charge", "discharge", "emergency"):
                check(f"{key}.{date}.{field}", day[field], dispatch[f"{key}_{field}"][index])
            check(f"{key}.{date}.adjusted", final, dispatch[f"{key}_adjusted"][index])
            check(f"{key}.{date}.bill", day["totalCost"], dispatch[f"{key}_costs"][index, 3])
            if purchase:
                purchase.append(r"\addlinespace")
                storage.append(r"\addlinespace")
            purchase_columns = 3 if key in ("q3", "q4_3") else 2
            purchase.append(rf"\multicolumn{{{purchase_columns}}}{{l}}{{\textbf{{{date}}}}} \\*")
            purchase.extend(keep_rows_together(purchase_rows(
                day["plan"], day.get("adjustedCost", day["planCost"]),
                final if key in ("q3", "q4_3") else None)))
            c = np.asarray(day["charge"]).reshape(6, 24).sum(1)
            d = np.asarray(day["discharge"]).reshape(6, 24).sum(1)
            storage.append(rf"\multicolumn{{6}}{{l}}{{\textbf{{{date}}}}} \\*")
            storage.extend(keep_rows_together(storage_rows(
                day["charge"], day["discharge"], day["socStart"], day["socEnd"])))
            adjustment = day.get("adjustedCost", day["planCost"]) - day["planCost"]
            costs.append([date[5:], number(day["planCost"]), number(adjustment), number(day["emergencyCost"]), number(day["totalCost"])])
            ev = events(day["emergency"])
            all_events.append(ev or [("无", 0.0)])
            check(f"{key}.{date}.event_sum", sum(value for _, value in ev), sum(day["emergency"]))
            audit["specified_dates"][key].append({"date": date, "slot_indices": SLOTS, "plan_at_slots": [day["plan"][i] for i in SLOTS],
                "final_at_slots": [final[i] for i in SLOTS], "charge_4h": c.tolist(), "discharge_4h": d.tolist(),
                "soc_start": day["socStart"], "soc_end": day["socEnd"], "emergency_events": ev,
                "daily_total_cost": day["totalCost"]})
        appendix.append(table(f"{name}指定日期的六个购电时段（2025年，kWh）", f"tab:{tag}-days-purchase",
            ["时间段", "原计划购电量", "最终常规购电量"] if key in ("q3", "q4_3") else ["时间段", "购电量"],
            purchase, long=True))
        appendix.append(table(f"{name}指定日期的六段充放电量（kWh）", f"tab:{tag}-days-storage",
            ["时间段", "充电量", "放电量"] * 2, storage,
            long=True, spec="lrrlrr"))
        appendix.append(table(f"{name}指定日期的全天账单（元）", f"tab:{tag}-days-costs",
            ["日期", "原计划费", "调整费", "紧急费", "总费用"], costs, long=True))
        emergency = []
        for date, ev in zip(DATES, all_events):
            if emergency:
                emergency.append(r"\addlinespace")
            rows = [[date if i == 0 else "", period, number(value)] for i, (period, value) in enumerate(ev)]
            rows.append(["", "全天合计", number(sum(value for _, value in ev))])
            emergency.extend(keep_rows_together(rows))
        appendix.append(table(f"{name}指定日期的紧急购电事件（kWh）", f"tab:{tag}-days-emergency",
            ["日期", "时间段", "购电量"], emergency, long=True, spec="llr"))
        files[f"selected-days-{tag}.tex"] = "\n".join(appendix)

    for name, content in files.items():
        (DEST / name).write_text("% Generated by scripts/build_paper_tables.py; do not edit by hand.\n" + content, encoding="utf-8", newline="\n")
    (DEST / "table-data.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": 1, "status": "passed", "generator": "scripts/build_paper_tables.py",
        "generator_sha256": sha256(Path(__file__)), "source_sha256": {name: sha256(ROOT / name) for name in SOURCES},
        "generated_sha256": {name: sha256(DEST / name) for name in (*files, "table-data.json")},
        "specified_date_count": sum(map(len, audit["specified_dates"].values())),
        "check_count": len(checks), "checks": checks,
        "display_policy": "Money and energy use two decimals; conditional hourly differences use four. No model is rerun. Main window Feb-Dec; monthly rolling window Apr-Dec.",
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Generated {len(files)} TeX modules; {len(checks)} archive comparisons passed; 16 specified dates complete.")


if __name__ == "__main__":
    main()
