"""Independent checks for the review-driven forecast and contract revision.

Expected hourly targets and transaction charges are reconstructed without model
helpers.  Calls into the model are used only as the subject of invariance tests
and to replay January candidate decisions from the archived selection protocol.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from validate_results import Checks, check_physics, COST_TOLERANCE, ENERGY_TOLERANCE

ROOT = Path(__file__).resolve().parents[1]
RESULT_FIELDS = ("plan", "adjusted", "charge", "discharge", "emergency", "spill",
                 "soc", "costs", "revisions")


def expected_published_pv(data: dict, day: int, issue: int, source: int) -> np.ndarray:
    """Hand-interpolate the same delivery targets from one available release."""
    if not 0 <= source <= issue <= 3:
        raise ValueError("Forecast sources must already be published")
    elapsed_hours = 6 * (issue - source)
    remaining_hours = 24 - 6 * issue
    targets = data["forecast_hourly"][day, source,
                                        elapsed_hours:elapsed_hours + remaining_hours]
    start = issue * 36
    anchor = (data["pv"][day, start - 1] if start else
              data["pv"][day - 1, -1] if day else 0.0)
    previous = float(anchor)
    values = []
    for target in targets:
        # Do not use np.interp or the production interpolation implementation.
        for substep in range(1, 7):
            values.append(previous + (float(target) - previous) * substep / 6.0)
        previous = float(target)
    return np.array(values)


def reconstruct_transactions(result: dict, price: np.ndarray) -> dict:
    """Replay order versions, including purchases subsequently cancelled."""
    current = result["plan"].copy()
    up, down = np.zeros_like(current), np.zeros_like(current)
    revision_up = np.zeros_like(result["revisions"])
    revision_down = np.zeros_like(result["revisions"])
    shape_ok = result["revisions"].shape == (len(current), 4, 144)
    if not shape_ok:
        raise ValueError("Revision snapshot shape is invalid")
    monotone, valid_versions, hidden_past = True, True, True
    active_days = {}
    for issue in range(1, 4):
        start = issue * 36
        version = result["revisions"][:, issue]
        hidden_past &= bool(np.all(np.isnan(version[:, :start])))
        tail = version[:, start:]
        active = np.all(np.isfinite(tail), axis=1)
        absent = np.all(np.isnan(tail), axis=1)
        valid_versions &= bool(np.all(active | absent))
        active_days[str(issue * 6)] = int(np.sum(active))
        change = tail[active] - current[active, start:]
        monotone &= bool(np.all(change >= -ENERGY_TOLERANCE))
        up[active, start:] += np.maximum(change, 0)
        down[active, start:] += np.maximum(-change, 0)
        revision_up[active, issue, start:] = np.maximum(change, 0)
        revision_down[active, issue, start:] = np.maximum(-change, 0)
        current[active, start:] = tail[active]
    return {"adjusted": current, "up": up, "down": down,
            "revision_up": revision_up, "revision_down": revision_down,
            "fee": np.sum(price * (1.5 * up + 0.5 * down), axis=1),
            "monotone": monotone, "valid_versions": valid_versions,
            "hidden_past": hidden_past, "active_days": active_days}


def check_scene(checks: Checks, name: str, result: dict, data: dict,
                dynamic: bool, settlement: str) -> dict:
    count = len(result["plan"])
    expected_shapes = {"soc": (count, 145), "costs": (count, 4),
                       "revisions": (count, 4, 144)}
    for field in RESULT_FIELDS:
        expected = expected_shapes.get(field, (count, 144))
        checks.add(name + ".shape_" + field, result[field].shape == expected)
    price = (data["dynamic_price"][:count] if dynamic else
             np.broadcast_to(data["fixed_price"], (count, 144)))
    flow = reconstruct_transactions(result, price)
    checks.close(name + ".midnight_snapshot", result["revisions"][:, 0], result["plan"])
    checks.add(name + ".complete_revision_versions", flow["valid_versions"])
    checks.add(name + ".does_not_rewrite_delivered_slots", flow["hidden_past"])
    checks.close(name + ".replayed_final_delivery", flow["adjusted"], result["adjusted"])
    for field in ("revision_up", "revision_down"):
        if field in result:
            checks.close(name + ".archived_" + field, flow[field], result[field])
    if settlement == "per_revision":
        adjustment = flow["fee"]
        checks.add(name + ".committed_orders_never_reduced", flow["monotone"])
        checks.close(name + ".zero_cancelled_commitments", flow["down"], 0.0)
    elif settlement == "final_net":
        difference = result["adjusted"] - result["plan"]
        adjustment = np.sum(price * (1.5 * np.maximum(difference, 0)
                                     + 0.5 * np.maximum(-difference, 0)), axis=1)
    else:
        raise ValueError(f"Unknown settlement {settlement}")
    base = np.sum(price * result["plan"], axis=1)
    emergency = np.sum(5.0 * price * result["emergency"], axis=1)
    costs = np.column_stack((base, adjustment, emergency, base + adjustment + emergency))
    checks.close(name + ".all_daily_cost_components", costs, result["costs"], COST_TOLERANCE)
    check_physics(checks, name, result["adjusted"], result["charge"], result["discharge"],
                  result["emergency"], result["spill"], result["soc"],
                  (data["load"][:count] - data["pv"][:count]) / 6.0)
    checks.close(name + ".initial_soc", result["soc"][0, 0], 6000.0)
    checks.close(name + ".continuous_days", result["soc"][1:, 0], result["soc"][:-1, -1])
    return {"total_cost": float(costs[31:, 3].sum()),
            "path_repriced_total_cost": float((base + flow["fee"] + emergency)[31:].sum()),
            "cancelled_purchase_kwh": float(flow["down"][31:].sum()),
            "path_up_kwh": float(flow["up"][31:].sum()),
            "active_days": flow["active_days"]}


def check_contract_fixture(checks: Checks) -> None:
    from model import settle_revisions

    plan = np.full(144, 100.0)
    versions = np.full((4, 144), np.nan)
    versions[0] = plan
    current = plan.copy()
    for issue, amount in ((1, 150.0), (2, 130.0), (3, 160.0)):
        current[120] = amount
        versions[issue, issue * 36:] = current[issue * 36:]
    price = np.ones(144)
    price[120] = 2.0
    # One delivery changes 100 -> 150 -> 130 -> 160. At price 2:
    # final-net = 60*1.5*2 = 180; transaction path = (80*1.5+20*.5)*2 = 260.
    final_net = settle_revisions(plan, versions, price, settlement="final_net")
    path = settle_revisions(plan, versions, price, settlement="per_revision")
    checks.close("contract_fixture.final_net_fee", final_net["adjustment_cost"], 180.0)
    checks.close("contract_fixture.path_fee_includes_cancelled_purchase", path["adjustment_cost"], 260.0)
    checks.close("contract_fixture.path_up", path["up"][120], 80.0)
    checks.close("contract_fixture.path_down", path["down"][120], 20.0)
    checks.close("contract_fixture.final_delivery", path["final"][120], 160.0)


def check_information_controls(checks: Checks, data: dict) -> None:
    from model import ForecastCache, point_forecast, published_pv, risk_forecast

    routes = ((0, 1, 2, 3), (0, 0, 0, 0), (0, 1, 1, 2), (0, 0, 2, 2))
    largest_target_error = 0.0
    largest_anchor_error = 0.0
    for day in (0, 1, 31, 100, 364):
        for route in routes:
            for issue in range(4):
                prediction = published_pv(data, day, issue, route)
                expected = expected_published_pv(data, day, issue, route[issue])
                largest_target_error = max(largest_target_error,
                                          float(np.max(np.abs(prediction - expected))))
                # Recover the common origin from the first 10-minute point and
                # the first hourly target; it must equal the latest observation.
                inferred_anchor = (6.0 * prediction[0] - prediction[5]) / 5.0
                slot = issue * 36
                anchor = (data["pv"][day, slot - 1] if slot else
                          data["pv"][day - 1, -1] if day else 0.0)
                largest_anchor_error = max(largest_anchor_error, float(abs(inferred_anchor - anchor)))
    checks.add("information.absolute_hourly_targets_and_interpolation", largest_target_error < 1e-9,
               cases=80, maximum_absolute_error=largest_target_error)
    checks.add("information.all_routes_keep_identical_current_anchor", largest_anchor_error < 1e-9,
               cases=80, maximum_absolute_error=largest_anchor_error)

    largest_hidden_error = 0.0
    cases = 0
    for day in (0, 31, 100, 364):
        for issue in range(4):
            slot = issue * 36
            for route in routes:
                source = route[issue]
                changed = {key: value.copy() for key, value in data.items()}
                for key in ("load", "pv", "dynamic_price"):
                    changed[key][day, slot:] += 100000.0
                    changed[key][day + 1:] += 200000.0
                # Deliberately change all releases excluded by this information
                # route, including already-published batches omitted as control.
                for key in ("forecast", "forecast_hourly"):
                    changed[key][day, source + 1:] += 300000.0
                    changed[key][day + 1:] += 400000.0
                changed["forecast_anchor"][day, issue + 1:] += 500000.0
                changed["forecast_anchor"][day + 1:] += 500000.0
                # Targets beyond this day's end cannot enter a one-day plan.
                changed["forecast_hourly"][day, source, 24 - 6 * source:] += 600000.0
                changed["forecast"][day, source, 144 - 36 * source:] += 600000.0
                for weight in (0.0, 0.5, 1.0):
                    for dynamic in (False, True):
                        before = point_forecast(data, day, issue, True, dynamic,
                                                pv_weight=weight, forecast_sources=route)
                        after = point_forecast(changed, day, issue, True, dynamic,
                                               pv_weight=weight, forecast_sources=route)
                        largest_hidden_error = max(largest_hidden_error,
                            *(float(np.max(np.abs(a - b))) for a, b in zip(before, after)))
                        cases += 1
    checks.add("information.excluded_forecasts_and_future_actuals_invariance",
               largest_hidden_error == 0.0, cases=cases,
               maximum_absolute_error=largest_hidden_error)

    # Positive controls exclude a predictor that simply ignores every input.
    day, issue = 100, 2
    changed = {key: value.copy() for key, value in data.items()}
    changed["forecast_hourly"][day, 0, 12] += 60.0
    before = published_pv(data, day, issue, (0, 0, 0, 0))
    after = published_pv(changed, day, issue, (0, 0, 0, 0))
    checks.close("information.visible_old_hourly_target_positive_control",
                 after[:6] - before[:6], np.arange(1, 7) * 10.0, 1e-9)
    changed = {key: value.copy() for key, value in data.items()}
    changed["forecast_anchor"][day, issue] += 60.0
    after = published_pv(changed, day, issue, (0, 0, 0, 0))
    checks.close("information.current_observation_anchor_positive_control",
                 after[:6] - before[:6], np.arange(5, -1, -1) * 10.0, 1e-9)
    unchanged_origin = published_pv(data, day, issue, (0, 0, 0, 0), anchor_updates=False)
    checks.close("information.anchor_disabled_retains_original_midnight_curve",
                 unchanged_origin, data["forecast"][day, 0, issue * 36:], 1e-9)
    checks.close("information.anchor_disabled_ignores_current_observation",
                 published_pv(changed, day, issue, (0, 0, 0, 0), anchor_updates=False),
                 unchanged_origin, 1e-9)
    changed = {key: value.copy() for key, value in data.items()}
    changed["load"][day, 54:72] *= 10.0
    without_update = point_forecast(data, day, issue, True, load_update=False)
    without_update_changed = point_forecast(changed, day, issue, True, load_update=False)
    with_update = point_forecast(data, day, issue, True, load_update=True)
    with_update_changed = point_forecast(changed, day, issue, True, load_update=True)
    checks.close("information.load_update_disabled_ignores_recent_load",
                 without_update_changed[2], without_update[2], 1e-9)
    checks.add("information.load_update_enabled_responds_to_recent_load",
               bool(np.any(np.abs(with_update_changed[2] - with_update[2]) > 1.0)))

    # Verify the empirical quantile using an explicit order statistic, with the
    # declared 28 prior days and repeated-edge seven-slot neighborhood.
    shape = (365, 4, 144)
    slot_numbers = np.arange(144)[None, None, :]
    day_numbers = np.arange(365)[:, None, None]
    issue_numbers = np.arange(4)[None, :, None]
    errors = np.broadcast_to(day_numbers * 3.7 + issue_numbers * 11.3 + slot_numbers * 0.19,
                             shape).copy()
    net = np.full(shape, 100.0)
    empty = np.zeros(shape)
    cache = ForecastCache(net, empty, errors, empty, empty)
    maximum = 0.0
    for day in (8, 31, 100):
        for issue in range(4):
            first = issue * 36
            for alpha in (0.5, 0.65, 0.8):
                prediction = risk_forecast(cache, day, issue, alpha)
                expected = []
                for slot in range(first, 144):
                    samples = sorted(errors[past, issue, min(143, max(first, slot + offset))]
                                     for past in range(max(7, day - 28), day)
                                     for offset in range(-3, 4))
                    rank = alpha * (len(samples) - 1)
                    low, high = int(np.floor(rank)), int(np.ceil(rank))
                    correction = samples[low] + (samples[high] - samples[low]) * (rank - low)
                    expected.append(100.0 + correction)
                maximum = max(maximum, float(np.max(np.abs(prediction - expected))))
    checks.add("information.risk_quantile_independent_past_window_and_slot_pool", maximum < 1e-9,
               cases=36, maximum_absolute_error=maximum)
    errors_changed = errors.copy()
    errors_changed[31:] += 1e10
    changed_cache = ForecastCache(net, empty, errors_changed, empty, empty)
    checks.close("information.risk_current_and_future_residuals_excluded",
                 risk_forecast(cache, 31, 2, 0.65),
                 risk_forecast(changed_cache, 31, 2, 0.65), 1e-9)


def check_january_selection(checks: Checks, data: dict, experiments: dict) -> None:
    from model import build_cache, simulate

    future_changed = {key: value.copy() for key, value in data.items()}
    for key in ("load", "pv", "dynamic_price", "forecast", "forecast_hourly", "forecast_anchor"):
        future_changed[key][31:] += 12345.0
    cache_store = {}

    def get_cache(weight: float, dynamic: bool, changed: bool):
        key = (weight, dynamic, changed)
        if key not in cache_store:
            cache_store[key] = build_cache(future_changed if changed else data,
                                           forecast=True, dynamic=dynamic, pv_weight=weight)
        return cache_store[key]

    selections = [(name, selection, "final_net")
                  for name, selection in experiments["selection"].items()]
    selections += [(name + ".per_revision", spec["selection"], "per_revision")
                   for name, spec in experiments.get("contracts", {}).items()]
    for name, selection, settlement in selections:
        candidates, selected = selection["candidates"], selection["selected"]
        dynamic = name.startswith("q4_")
        minimum = min(float(row["validation_cost"]) for row in candidates)
        checks.close("selection." + name + ".minimum_january_score",
                     selected["validation_cost"], minimum, COST_TOLERANCE)
        matches = [row for row in candidates if row["pv_weight"] == selected["pv_weight"]
                   and row["quantile"] == selected["quantile"]]
        checks.add("selection." + name + ".winner_is_archived_candidate", len(matches) == 1)
        checks.add("selection." + name + ".finite_january_scores",
                   all(np.isfinite(row["validation_cost"]) for row in candidates))
        checks.add("selection." + name + ".both_historical_and_published_endpoints_present",
                   {0.0, 1.0}.issubset({row["pv_weight"] for row in candidates}))
        # Winner plus each endpoint's best January setting covers the new blend
        # and both simple alternatives without rerunning all 30 candidates.
        representatives = [selected]
        representatives += [min((row for row in candidates if row["pv_weight"] == weight),
                                key=lambda row: row["validation_cost"])
                            for weight in (0.0, 1.0)]
        used = set()
        for candidate in representatives:
            weight, alpha = candidate["pv_weight"], candidate["quantile"]
            if (weight, alpha) in used:
                continue
            used.add((weight, alpha))
            label = f"selection.{name}.w{weight:g}.q{alpha:g}"
            original_cache = get_cache(weight, dynamic, False)
            changed_cache = get_cache(weight, dynamic, True)
            maximum = 0.0
            for field in ("net", "price", "load", "pv", "errors"):
                original = getattr(original_cache, field)[:31]
                changed = getattr(changed_cache, field)[:31]
                maximum = max(maximum, float(np.nanmax(np.abs(original - changed))))
            checks.add(label + ".all_january_forecasts_ignore_february_onwards",
                       maximum == 0.0, maximum_absolute_error=maximum)
            replay = simulate(data, original_cache, alpha, issues=(36, 72, 108),
                              days=31, dynamic=dynamic, warmup_quantile=None, settlement=settlement)
            changed_replay = simulate(future_changed, changed_cache, alpha, issues=(36, 72, 108),
                                      days=31, dynamic=dynamic, warmup_quantile=None,
                                      settlement=settlement)
            score = float(replay["costs"][14:31, 3].sum())
            checks.close(label + ".archived_score_reproduced_from_january_only",
                         score, candidate["validation_cost"], COST_TOLERANCE)
            checks.close(label + ".score_unchanged_when_all_test_months_are_replaced",
                         changed_replay["costs"][14:31, 3], replay["costs"][14:31, 3], COST_TOLERANCE)
            checks.close(label + ".plans_unchanged_when_all_test_months_are_replaced",
                         changed_replay["plan"], replay["plan"])
        print(f"January selection checked: {name} ({len(used)} representative candidates)", flush=True)


def load_scene(archive: dict, name: str) -> dict:
    fields = RESULT_FIELDS + ("revision_up", "revision_down")
    return {field: archive[name + "_" + field] for field in fields
            if name + "_" + field in archive}


def check_fixed_warmups(checks: Checks, data: dict, experiments: dict, dispatch: dict) -> None:
    from model import build_cache, simulate

    references = {}
    for name, spec in experiments["scenes"].items():
        if spec["warmup_mode"] != "attachment3_fixed":
            continue
        identity = (spec["dynamic"], tuple(spec["issues"]), spec["settlement"])
        if identity not in references:
            cache = build_cache(data, forecast=True, dynamic=spec["dynamic"], pv_weight=1.0)
            references[identity] = simulate(data, cache, 0.8, issues=tuple(spec["issues"]),
                                            dynamic=spec["dynamic"], days=31,
                                            settlement=spec["settlement"])
        reference, result = references[identity], load_scene(dispatch, name)
        for field in ("plan", "adjusted", "costs", "soc"):
            checks.close(name + ".january_uses_fixed_attachment3_warmup_" + field,
                         result[field][:31], reference[field],
                         COST_TOLERANCE if field == "costs" else ENERGY_TOLERANCE)


def check_selected_artifacts(checks: Checks, experiments: dict, dispatch: dict, primary: dict) -> None:
    checks.add("selection.validation_window_is_january15_through31",
               experiments["validation_days"] == [14, 31])
    checks.add("selection.warmup_protocol_is_fixed_before_february",
               all(experiments["warmup"].get(key) == value for key, value in
                   {"quantile": 0.8, "pv_weight": 1.0, "ends_before_day": 31}.items()))
    for name, selection in experiments["selection"].items():
        scene_id = selection.get("primary_scene_id", name + "_selected")
        scene, selected = experiments["scenes"][scene_id], selection["selected"]
        for field in ("pv_weight", "quantile"):
            checks.close("selection." + name + ".primary_uses_selected_" + field,
                         scene[field], selected[field], 1e-12)
        result = load_scene(dispatch, scene_id)
        for field in ("plan", "adjusted", "costs", "soc", "emergency"):
            checks.close("selection." + name + ".primary_artifact_matches_" + field,
                         primary[name + "_" + field], result[field],
                         COST_TOLERANCE if field == "costs" else ENERGY_TOLERANCE)
        baseline_id = experiments["baselines"][name]["historical_common_warmup"]
        baseline = experiments["scenes"][baseline_id]
        historic_candidate = min((row for row in selection["candidates"] if row["pv_weight"] == 0.0),
                                 key=lambda row: row["validation_cost"])
        checks.close("baseline." + name + ".historical_only", baseline["pv_weight"], 0.0)
        checks.close("baseline." + name + ".historical_parameter_selected_in_january",
                     baseline["quantile"], historic_candidate["quantile"], 1e-12)
        shared_fields = ("issues", "dynamic", "settlement", "forecast_sources", "load_update",
                         "anchor_updates", "warmup_mode", "soc_observation")
        checks.add("baseline." + name + ".same_planning_and_information_opportunities",
                   all(baseline[field] == scene[field] for field in shared_fields))
        baseline_result = load_scene(dispatch, baseline_id)
        checks.close("baseline." + name + ".same_february_starting_inventory",
                     baseline_result["soc"][31, 0], result["soc"][31, 0])
    for name, contract in experiments.get("contracts", {}).items():
        scene = experiments["scenes"][contract["reoptimized"]]
        selected = contract["selection"]["selected"]
        for field in ("pv_weight", "quantile"):
            checks.close("selection." + name + ".contract_uses_selected_" + field,
                         scene[field], selected[field], 1e-12)


def check_experiment_comparability(checks: Checks, experiments: dict) -> None:
    common_fields = ("pv_weight", "quantile", "issues", "dynamic", "settlement", "load_update",
                     "anchor_updates", "warmup_mode", "soc_observation")
    for group, experiments_in_group in experiments["information_ablation"].items():
        names = experiments_in_group["hourly_subsets"]
        reference = experiments["scenes"][names[-1]]
        checks.add("information." + group + ".all_eight_release_subsets_present", len(names) == 8)
        routes = set()
        for name in names:
            scene = experiments["scenes"][name]
            routes.add(tuple(scene["forecast_sources"]))
            checks.add(name + ".only_hourly_information_is_changed",
                       all(scene[field] == reference[field] for field in common_fields))
            checks.add(name + ".all_replanning_and_observation_updates_retained",
                       scene["issues"] == [36, 72, 108] and scene["load_update"]
                       and scene["anchor_updates"] and scene["soc_observation"] == "own_actual")
        checks.add("information." + group + ".eight_distinct_causal_release_routes",
                   len(routes) == 8 and all(len(route) == 4 and
                       all(0 <= source <= issue for issue, source in enumerate(route)) for route in routes))


def check_frozen_contract_summaries(checks: Checks, experiments: dict, summary: dict) -> None:
    for name, contract in experiments["contracts"].items():
        for variant in ("frozen_legacy", "frozen_selected"):
            archived = contract[variant]
            source = summary[archived["scene_id"]]
            label = "contract." + name + "." + variant
            checks.close(label + ".path_repriced_total", archived["total_cost"],
                         source["path_repriced_total_cost"], COST_TOLERANCE)
            checks.close(label + ".extra_fee", archived["extra_cost"],
                         source["path_repriced_total_cost"] - source["total_cost"], COST_TOLERANCE)
            checks.close(label + ".cancelled_purchase_kwh", archived["withdrawn_kwh"],
                         source["cancelled_purchase_kwh"])
            checks.add(label + ".identified_as_frozen_dispatch", archived["reoptimized"] is False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/data.npz")
    parser.add_argument("--experiments", type=Path, default=ROOT / "outputs/experiments/revision/experiments.json")
    parser.add_argument("--dispatch", type=Path, default=ROOT / "outputs/experiments/revision/dispatch.npz")
    parser.add_argument("--primary-dispatch", type=Path, default=ROOT / "outputs/main/dispatch.npz")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/experiments/revision/validation.json")
    args = parser.parse_args()
    with np.load(args.data, allow_pickle=False) as source:
        data = {key: source[key] for key in source.files}
    experiments = json.loads(args.experiments.read_text(encoding="utf-8"))
    with np.load(args.dispatch, allow_pickle=False) as source:
        dispatch = {key: source[key] for key in source.files}
    with np.load(args.primary_dispatch, allow_pickle=False) as source:
        primary = {key: source[key] for key in source.files}
    checks = Checks()
    check_contract_fixture(checks)
    check_information_controls(checks, data)
    check_january_selection(checks, data, experiments)
    check_fixed_warmups(checks, data, experiments, dispatch)
    check_selected_artifacts(checks, experiments, dispatch, primary)
    check_experiment_comparability(checks, experiments)
    summary = {}
    for name, spec in experiments["scenes"].items():
        result = load_scene(dispatch, name)
        summary[name] = check_scene(checks, name, result, data, spec["dynamic"], spec["settlement"])
        checks.close(name + ".summary_total_cost", summary[name]["total_cost"],
                     spec["summary"]["total_cost"], COST_TOLERANCE)
        for issue in (36, 72, 108):
            checks.add(name + f".archived_update_schedule_{issue // 6:02d}",
                       summary[name]["active_days"][str(issue // 6)] ==
                       (365 if issue in spec["issues"] else 0))
    check_frozen_contract_summaries(checks, experiments, summary)
    paths = (args.data, args.experiments, args.dispatch, args.primary_dispatch,
             Path(__file__), ROOT / "scripts/model.py")
    report = {"status": "passed" if checks.passed else "failed",
              "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "forecast_controls_january_selection_and_transaction_contracts",
              "limits": "Physics and billing checks do not establish optimality or out-of-year generalization. "
                        "January replay samples the selected setting and both predictor endpoints; "
                        "minimum-score comparison covers every archived candidate.",
              "artifact_sha256": {str(path.resolve().relative_to(ROOT)):
                                  hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
              "check_count": len(checks.results),
              "failed_checks": [row["name"] for row in checks.results if not row["passed"]],
              "summary": summary, "checks": checks.results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "check_count", "failed_checks")},
                     ensure_ascii=False, indent=2))
    if not checks.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
