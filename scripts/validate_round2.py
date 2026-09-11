"""Independent accounting, rolling-selection and temporal checks for round two.

All cash costs, physics and month summaries are reconstructed from archive
arrays. The simulator is called only as the subject of representative replay
and temporal-invariance checks, not as the source of expected accounting.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from validate_results import Checks, check_physics, COST_TOLERANCE, ENERGY_TOLERANCE
from validate_revision import reconstruct_transactions

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("plan", "adjusted", "charge", "discharge", "emergency", "spill",
          "soc", "costs", "revisions", "revision_up", "revision_down")
WEIGHTS = (0., .25, .5, .75, 1.)
QUANTILES = (.5, .65, .7, .8, .9, .95)


def compare_arrays(checks, name, actual, expected):
    checks.add(name + ".shape", actual.shape == expected.shape)
    if actual.shape != expected.shape:
        return
    mask = np.isfinite(expected)
    checks.add(name + ".missing_values", np.array_equal(np.isnan(actual), np.isnan(expected))
               and np.array_equal(np.isfinite(actual), mask))
    checks.close(name + ".values", actual[mask], expected[mask])


def observed_summary(path, start=0, end=None):
    selection = slice(start, end)
    cost = path["costs"][selection].sum(axis=0)
    result = {key + "_kwh": float(path[key][selection].sum()) for key in
              ("plan", "adjusted", "emergency", "spill", "charge", "discharge")}
    result.update(plan_cost=float(cost[0]), adjustment_cost=float(cost[1]),
                  emergency_cost=float(cost[2]), total_cost=float(cost[3]),
                  start_soc=float(path["soc"][start, 0]),
                  end_soc=float(path["soc"][selection][-1, -1]),
                  emergency_days=int(np.any(path["emergency"][selection] > 1e-7, axis=1).sum()))
    return result


def compare_summary(checks, name, stored, expected):
    checks.add(name + ".keys", set(stored) == set(expected))
    for key in expected:
        if key in stored:
            checks.close(name + "." + key, stored[key], expected[key], COST_TOLERANCE)


def check_scene(checks, name, metadata, path, data):
    start, stop = metadata["day_start"], metadata["day_stop"]
    count = stop - start
    for field in FIELDS:
        shape = ((count, 145) if field == "soc" else (count, 4) if field == "costs"
                 else (count, 4, 144) if field in ("revisions", "revision_up", "revision_down")
                 else (count, 144))
        checks.add(name + ".shape_" + field, path[field].shape == shape)
    price = (data["dynamic_price"][start:stop] if metadata["dynamic"] else
             np.broadcast_to(data["fixed_price"], (count, 144)))
    actual = (data["load"][start:stop] - data["pv"][start:stop]) / 6.
    check_physics(checks, name, path["adjusted"], path["charge"], path["discharge"],
                  path["emergency"], path["spill"], path["soc"], actual)
    checks.close(name + ".continuous_days", path["soc"][1:, 0], path["soc"][:-1, -1])
    checks.add(name + ".charging_uses_only_existing_surplus",
               bool(np.all(path["charge"] <= np.maximum(path["adjusted"] - actual, 0) + ENERGY_TOLERANCE)))
    transactions = reconstruct_transactions(path, price)
    checks.add(name + ".complete_revision_versions", transactions["valid_versions"])
    checks.add(name + ".does_not_change_completed_deliveries", transactions["hidden_past"])
    checks.close(name + ".midnight_revision", path["revisions"][:, 0], path["plan"])
    checks.close(name + ".reconstructed_adjusted", transactions["adjusted"], path["adjusted"])
    for field in ("revision_up", "revision_down"):
        checks.close(name + "." + field, transactions[field], path[field])
    for issue in (36, 72, 108):
        expected = count if issue in metadata["issues"] else 0
        checks.add(name + f".permitted_issue_{issue}",
                   transactions["active_days"][str(issue // 6)] == expected)
    change = path["adjusted"] - path["plan"]
    plan_cost = (price * path["plan"]).sum(axis=1)
    adjustment_cost = (price * (1.5 * np.maximum(change, 0) + .5 * np.maximum(-change, 0))).sum(axis=1)
    emergency_cost = (5 * price * path["emergency"]).sum(axis=1)
    costs = np.column_stack((plan_cost, adjustment_cost, emergency_cost,
                             plan_cost + adjustment_cost + emergency_cost))
    checks.close(name + ".independent_all_daily_costs", costs, path["costs"], COST_TOLERANCE)
    checks.add(name + ".final_net_contract", metadata["settlement"] == "final_net")
    first = metadata["evaluation_start_day"]
    checks.add(name + ".evaluation_dates", metadata["evaluation_start"] == str(data["dates"][first])
               and metadata["evaluation_end"] == str(data["dates"][stop - 1]))
    compare_summary(checks, name + ".summary", metadata["summary"],
                    observed_summary(path, first - start))


def check_feedback(checks, report, paths, primary):
    for strategy, comparison in report["feedback"].items():
        greedy_id, mpc_id = comparison["greedy"], comparison["mpc"]
        greedy, mpc = paths[greedy_id], paths[mpc_id]
        gmeta, mmeta = report["scenes"][greedy_id], report["scenes"][mpc_id]
        evaluation_start = gmeta["evaluation_start_day"] - gmeta["day_start"]
        label = "feedback." + strategy
        baseline = {field: primary[strategy + "_" + field] for field in FIELDS}
        checks.add(label + ".greedy_history_exact_all_eleven_fields",
                   all(np.array_equal(greedy[field][:365], baseline[field], equal_nan=True) for field in FIELDS))
        checks.add(label + ".january_exact_all_eleven_fields",
                   all(np.array_equal(mpc[field][:31], greedy[field][:31], equal_nan=True) for field in FIELDS))
        for field in FIELDS:
            compare_arrays(checks, label + ".preserved_greedy_" + field,
                           greedy[field][:365], baseline[field])
            compare_arrays(checks, label + ".shared_january_" + field,
                           mpc[field][:31], greedy[field][:31])
        if report["evaluation_type"].startswith("retrospective"):
            checks.close(label + ".common_evaluation_initial_soc", greedy["soc"][evaluation_start, 0],
                         mpc["soc"][evaluation_start, 0])
        gsum, msum = observed_summary(greedy, evaluation_start), observed_summary(mpc, evaluation_start)
        saving = gsum["total_cost"] - msum["total_cost"]
        checks.close(label + ".cash_saving", comparison["cash_saving_yuan"], saving, COST_TOLERANCE)
        checks.close(label + ".saving_percent", comparison["saving_percent"],
                     100 * saving / gsum["total_cost"], 1e-8)
        checks.close(label + ".start_soc_difference", comparison["start_soc_difference"],
                     msum["start_soc"] - gsum["start_soc"])
        checks.close(label + ".end_soc_difference", comparison["end_soc_difference"],
                     msum["end_soc"] - gsum["end_soc"])
        checks.add(label + ".same_nomination_information_and_parameters",
                   all(gmeta[k] == mmeta[k] for k in ("dynamic", "issues", "pv_weight", "quantile", "settlement")))


def replay_window(data, cache, strategy, choice, start, stop, initial):
    from feedback import simulate_feedback
    return simulate_feedback(data, cache, choice["quantile"], issues=(36, 72, 108),
                             days=stop, start_day=start, initial=initial,
                             dynamic=strategy == "q4_3", feedback="greedy", warmup_quantile=None)


def check_rolling(checks, report, paths, data, primary):
    from model import build_cache

    dates = data["dates"].astype("datetime64[D]")
    months = dates.astype("datetime64[M]")
    expected_months = [str(month) for month in np.arange(np.datetime64("2025-04", "M"),
                                                        np.datetime64("2026-01", "M"))]
    cache = {}
    replay_cases = 0
    for strategy, study in report["rolling"].items():
        labels = study["scenes"]
        reference_soc = primary[strategy + "_soc"]
        checks.add(strategy + ".rolling_month_coverage", [fold["month"] for fold in study["folds"]] == expected_months)
        initial = reference_soc[90, 0]
        for policy in ("fixed", "adaptive", "historical"):
            checks.close(strategy + "." + policy + ".common_april_soc", paths[labels[policy]]["soc"][0, 0], initial)
        for fold in study["folds"]:
            label = strategy + ".rolling." + fold["month"]
            month = np.datetime64(fold["month"], "M")
            score_days, test_days = np.flatnonzero(months == month - 1), np.flatnonzero(months == month)
            score_start, score_stop = int(score_days[0]), int(score_days[-1] + 1)
            start, stop = int(test_days[0]), int(test_days[-1] + 1)
            checks.add(label + ".only_previous_complete_month_is_scored",
                       (fold["score_day_start"], fold["score_day_stop"], fold["test_day_start"], fold["test_day_stop"])
                       == (score_start, score_stop, start, stop) and score_stop == start)
            checks.add(label + ".selection_timestamp_and_information_cutoff",
                       fold["decision_time"] == str(dates[start]) + "T00:00:00"
                       and fold["latest_actual_date"] == str(dates[start - 1]))
            checks.close(label + ".common_candidate_initial_inventory", fold["score_start_soc"], reference_soc[score_start, 0])
            candidates = fold["candidates"]
            keys = [(row["pv_weight"], row["quantile"]) for row in candidates]
            checks.add(label + ".complete_unique_candidate_grid", len(keys) == 30
                       and set(keys) == {(w, q) for w in WEIGHTS for q in QUANTILES})
            checks.add(label + ".finite_candidate_scores_and_terminal_inventory",
                       all(np.isfinite(row["validation_cost"]) and 1200-1e-5 <= row["end_soc"] <= 10800+1e-5
                           for row in candidates))
            checks.close(label + ".all_candidates_start_identically", [row["start_soc"] for row in candidates],
                         fold["score_start_soc"])
            ranking = lambda row: (row["validation_cost"], row["pv_weight"], row["quantile"])
            checks.add(label + ".adaptive_choice_is_argmin", fold["selected"] == min(candidates, key=ranking))
            checks.add(label + ".history_choice_is_argmin_of_six", fold["historical_selected"] ==
                       min((row for row in candidates if row["pv_weight"] == 0), key=ranking))
            for policy in ("fixed", "adaptive", "historical"):
                path = paths[labels[policy]]
                path_start = report["scenes"][labels[policy]]["day_start"]
                monthly = observed_summary(path, start-path_start, stop-path_start)
                compare_summary(checks, label + ".monthly_" + policy, fold["monthly"][policy], monthly)
            # Three predetermined months check both the full candidate ranking and
            # actual monthly execution under the selected, frozen parameters.
            if fold["month"] not in ("2025-04", "2025-07", "2025-12"):
                continue
            for weight in WEIGHTS:
                key = (strategy, weight)
                if key not in cache:
                    cache[key] = build_cache(data, forecast=True, dynamic=strategy == "q4_3", pv_weight=weight)
                for candidate in (row for row in candidates if row["pv_weight"] == weight):
                    replay = replay_window(data, cache[key], strategy, candidate, score_start, score_stop, fold["score_start_soc"])
                    actual = observed_summary(replay)
                    suffix = f".candidate_w{weight}_q{candidate['quantile']}"
                    checks.close(label + suffix + ".cost", candidate["validation_cost"], actual["total_cost"], COST_TOLERANCE)
                    checks.close(label + suffix + ".terminal_soc", candidate["end_soc"], actual["end_soc"])
                    replay_cases += 1
            for policy, selection in (("adaptive", "selected"), ("historical", "historical_selected")):
                choice = fold[selection]
                path = paths[labels[policy]]
                path_start = report["scenes"][labels[policy]]["day_start"]
                offset = start-path_start
                replay = replay_window(data, cache[(strategy, choice["pv_weight"])], strategy, choice,
                                       start, stop, path["soc"][offset, 0])
                for field in FIELDS:
                    compare_arrays(checks, label + ".frozen_month_" + policy + "." + field,
                                   replay[field], path[field][offset:stop-path_start])
        totals = {policy: observed_summary(paths[labels[policy]])["total_cost"] for policy in labels}
        checks.close(strategy + ".aggregate_adaptive_vs_fixed", study["cash_saving_adaptive_vs_fixed"],
                     totals["fixed"]-totals["adaptive"], COST_TOLERANCE)
        checks.close(strategy + ".aggregate_adaptive_vs_historical", study["cash_saving_adaptive_vs_historical"],
                     totals["historical"]-totals["adaptive"], COST_TOLERANCE)
        for baseline in ("fixed", "historical"):
            wins = sum(fold["monthly"]["adaptive"]["total_cost"] < fold["monthly"][baseline]["total_cost"]
                       for fold in study["folds"])
            checks.add(strategy + ".monthly_win_count_vs_" + baseline,
                       study["adaptive_wins_vs_" + baseline] == wins)
    return cache, replay_cases


def check_month_boundary_causality(checks, data, cache, report):
    from model import build_cache, risk_forecast

    replay_cases = 0
    for strategy in ("q3", "q4_3"):
        fold = next(row for row in report["rolling"][strategy]["folds"] if row["month"] == "2025-07")
        cutoff, start = fold["test_day_start"], fold["score_day_start"]
        changed = {key: value.copy() for key, value in data.items()}
        for field, increment in (("load", 100000.), ("pv", 30000.), ("dynamic_price", 10.),
                                 ("forecast", 200000.), ("forecast_hourly", 200000.),
                                 ("forecast_anchor", 200000.)):
            changed[field][cutoff:] += increment
        for weight in WEIGHTS:
            baseline = cache[(strategy, weight)]
            altered = build_cache(changed, forecast=True, dynamic=strategy == "q4_3", pv_weight=weight)
            label = f"{strategy}.future_month_mutation.w{weight}"
            for field in ("net", "price", "errors"):
                compare_arrays(checks, label + ".past_" + field,
                               getattr(altered, field)[:cutoff], getattr(baseline, field)[:cutoff])
            for day in (start, cutoff-1):
                for issue in range(4):
                    checks.close(label + f".risk_day{day}_issue{issue}",
                                 risk_forecast(baseline, day, issue, .65), risk_forecast(altered, day, issue, .65))
            # Exercise full replay, including actual costs and inventory, for one
            # fixed representative quantile from each of the five weight families.
            choice = next(row for row in fold["candidates"] if row["pv_weight"] == weight and row["quantile"] == .65)
            replay = replay_window(changed, altered, strategy, choice, start, cutoff, fold["score_start_soc"])
            checks.close(label + ".previous_month_score", replay["costs"][:, 3].sum(),
                         choice["validation_cost"], COST_TOLERANCE)
            checks.close(label + ".previous_month_terminal_soc", replay["soc"][-1, -1], choice["end_soc"])
            replay_cases += 1
    return replay_cases


def check_feedback_causality(checks, data, paths):
    from feedback import simulate_feedback
    from model import build_cache

    for strategy, day, observed_slot in (("q3", 100, 35), ("q4_3", 200, 72)):
        dynamic = strategy == "q4_3"
        archived = paths["feedback_" + strategy + "_mpc"]
        initial = archived["soc"][day, 0]
        cache = build_cache(data, forecast=True, dynamic=dynamic, pv_weight=.5)
        baseline = simulate_feedback(data, cache, .65, issues=(36, 72, 108), days=day+1,
                                     start_day=day, initial=initial, dynamic=dynamic,
                                     feedback="mpc", warmup_quantile=None)
        label = f"feedback_causality.{strategy}.day{day}.slot{observed_slot}"
        for field in FIELDS:
            compare_arrays(checks, label + ".archived_day_" + field,
                           baseline[field], archived[field][day:day+1])
        changed = {key: value.copy() for key, value in data.items()}
        for field, increment in (("load", 10000.), ("pv", 3000.), ("dynamic_price", 5.)):
            changed[field][day, observed_slot+1:] += increment
            changed[field][day+1:] += 2 * increment
        latest_issue = observed_slot // 36
        for field in ("forecast", "forecast_hourly", "forecast_anchor"):
            changed[field][day, latest_issue+1:] += 30000.
            changed[field][day+1:] += 40000.
        changed_cache = build_cache(changed, forecast=True, dynamic=dynamic, pv_weight=.5)
        after = simulate_feedback(changed, changed_cache, .65, issues=(36, 72, 108),
                                  days=day+1, start_day=day, initial=initial, dynamic=dynamic,
                                  feedback="mpc", warmup_quantile=None)
        for field in ("plan", "adjusted", "charge", "discharge", "emergency", "spill", "soc"):
            stop = observed_slot + (2 if field == "soc" else 1)
            checks.close(label + ".hidden_future_does_not_change_" + field,
                         baseline[field][:, :stop], after[field][:, :stop])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "outputs/experiments/round2")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--future-data", type=Path,
                        help="Relocated external NPZ; its SHA-256 must match the archived source")
    args = parser.parse_args()
    directory = args.directory.resolve()
    report = json.loads((directory / "experiments.json").read_text(encoding="utf-8"))
    data = dict(np.load(ROOT / "data/processed/data.npz"))
    if report["evaluation_type"] == "frozen_parameters_future_dates":
        from external_inputs import load_future_data
        future_source = args.future_data or report["external_data"]["source_path"]
        data, metadata = load_future_data(data, future_source)
    elif args.future_data is not None:
        parser.error("--future-data is only supported for frozen external evaluations")
    with np.load(directory / "dispatch.npz") as archive:
        paths = {name: {field: archive[name + "__" + field].copy() for field in FIELDS}
                 for name in report["scenes"]}
    primary = dict(np.load(ROOT / "outputs/main/dispatch.npz"))
    checks = Checks()
    checks.add("does_not_claim_verified_external_independence", report["external_independence_verified"] is False)
    for filename, expected in report["source_sha256"].items():
        actual = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        checks.add("source_hash." + filename, actual == expected)
    for name, scene in report["scenes"].items():
        check_scene(checks, name, scene, paths[name], data)
    check_feedback(checks, report, paths, primary)
    replay_count = causality_count = 0
    if "rolling" in report:
        checks.add("same_year_development_exposure_disclosed", report["development_data_previously_seen"] is True)
        cache, replay_count = check_rolling(checks, report, paths, data, primary)
        causality_count = check_month_boundary_causality(checks, data, cache, report)
        check_feedback_causality(checks, data, paths)
    else:
        checks.add("external_data_hash", metadata["source_sha256"] == report["external_data"]["source_sha256"])
        checks.add("external_data_metadata", {k: v for k, v in metadata.items() if k != "source_path"} ==
                   {k: v for k, v in report["external_data"].items() if k != "source_path"})
        for name, scene in report["scenes"].items():
            checks.add(name + ".external_evaluation_only_future_days",
                       scene["evaluation_start_day"] == metadata["history_days"]
                       and scene["day_start"] == 0 and scene["day_stop"] == len(data["dates"]))
            boundary = metadata["history_days"]
            checks.close(name + ".inherits_own_last_historical_soc", paths[name]["soc"][boundary, 0],
                         paths[name]["soc"][boundary-1, -1])
    filenames = (ROOT / "scripts/validate_round2.py", directory / "experiments.json",
                 directory / "dispatch.npz", ROOT / "data/processed/data.npz")
    result = dict(status="passed" if checks.passed else "failed",
                  checked_at=datetime.now(timezone.utc).isoformat(), check_count=len(checks.results),
                  representative_candidate_replays=replay_count,
                  future_month_mutation_replays=causality_count,
                  source_sha256={str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path):
                                 hashlib.sha256(path.read_bytes()).hexdigest() for path in filenames},
                  checks=checks.results)
    output = args.output or directory / "validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in result.items() if key not in ("source_sha256", "checks")}, indent=2))
    if not checks.passed:
        for check in checks.results:
            if not check["passed"]:
                print(json.dumps(check, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
