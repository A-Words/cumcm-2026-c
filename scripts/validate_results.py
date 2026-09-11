"""Independently validate dispatch physics, settlement and forecast causality.

Physical and settlement checks deliberately do not call model optimization or
execution functions. Only the temporal-invariance tests import the predictors.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
HOURS = 1.0 / 6.0
CHARGE_EFFICIENCY = 0.9
DISCHARGE_EFFICIENCY = 0.9
MIN_SOC, MAX_SOC, INITIAL_SOC = 1200.0, 10800.0, 6000.0
MAX_SLOT_ENERGY = 5000.0 * HOURS
ENERGY_TOLERANCE = 2e-5
COST_TOLERANCE = 1e-3


class Checks:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def add(self, name: str, passed: bool, **details) -> None:
        self.results.append({"name": name, "passed": bool(passed), **details})

    def close(self, name: str, left, right, tolerance=ENERGY_TOLERANCE) -> None:
        a, b = np.asarray(left), np.asarray(right)
        try:
            delta = np.abs(a - b)
            finite = bool(np.all(np.isfinite(delta)))
            maximum = (float(np.max(delta)) if delta.size else 0.0) if finite else None
            passed = finite and maximum <= tolerance
        except ValueError:
            maximum, passed = None, False
        self.add(name, passed, maximum_absolute_error=maximum, tolerance=tolerance)

    @property
    def passed(self) -> bool:
        return all(item["passed"] for item in self.results)


def finite_shape(checks: Checks, name: str, array, shape: tuple) -> bool:
    actual_shape = tuple(array.shape)
    passed = actual_shape == shape and np.all(np.isfinite(array))
    checks.add(name + ".shape_and_finite", passed,
               expected_shape=list(shape), actual_shape=list(actual_shape))
    return bool(passed)


def check_physics(checks: Checks, name: str, grid, charge, discharge, emergency,
                  spill, soc, net) -> None:
    checks.close(name + ".ac_energy_balance", grid + emergency + discharge,
                 net + charge + spill)
    checks.close(name + ".soc_dynamics", np.diff(soc, axis=-1),
                 CHARGE_EFFICIENCY * charge - discharge / DISCHARGE_EFFICIENCY)
    checks.add(name + ".soc_bounds", np.min(soc) >= MIN_SOC - ENERGY_TOLERANCE
               and np.max(soc) <= MAX_SOC + ENERGY_TOLERANCE,
               minimum=float(np.min(soc)), maximum=float(np.max(soc)))
    for label, values in (("grid", grid), ("charge", charge), ("discharge", discharge),
                          ("emergency", emergency), ("spill", spill)):
        checks.add(name + ".nonnegative_" + label,
                   np.min(values) >= -ENERGY_TOLERANCE, minimum=float(np.min(values)))
    checks.add(name + ".charge_power_limit", np.max(charge) <= MAX_SLOT_ENERGY + ENERGY_TOLERANCE,
               maximum_kw=float(np.max(charge) / HOURS))
    checks.add(name + ".discharge_power_limit", np.max(discharge) <= MAX_SLOT_ENERGY + ENERGY_TOLERANCE,
               maximum_kw=float(np.max(discharge) / HOURS))
    simultaneous = np.minimum(charge, discharge)
    checks.add(name + ".charge_discharge_exclusion", np.max(simultaneous) <= ENERGY_TOLERANCE,
               maximum_simultaneous_kwh=float(np.max(simultaneous)))
    # Emergency purchases should cover a deficit; purchasing while spilling
    # energy would indicate a broken execution or accounting path.
    checks.add(name + ".emergency_spill_exclusion",
               np.max(np.minimum(emergency, spill)) <= ENERGY_TOLERANCE,
               maximum_simultaneous_kwh=float(np.max(np.minimum(emergency, spill))))


def check_q1(checks: Checks, dispatch: dict, data: dict) -> dict:
    fields = ("grid", "charge", "discharge", "soc", "spill")
    result = {key: dispatch["q1_" + key] for key in fields}
    valid = [finite_shape(checks, "q1." + key, value, (145,) if key == "soc" else (144,))
             for key, value in result.items()]
    if not all(valid):
        return {}
    net = (data["q1_load"] - data["q1_pv"]) * HOURS
    check_physics(checks, "q1", result["grid"], result["charge"], result["discharge"],
                  np.zeros(144), result["spill"], result["soc"], net)
    checks.close("q1.initial_soc", result["soc"][0], INITIAL_SOC)
    checks.close("q1.daily_cycle", result["soc"][0], result["soc"][-1])
    return {"purchase_kwh": float(result["grid"].sum()),
            "purchase_cost_yuan": float(result["grid"] @ data["fixed_price"]),
            "initial_soc_kwh": float(result["soc"][0]),
            "terminal_soc_kwh": float(result["soc"][-1])}


def check_revisions(checks: Checks, name: str, result: dict,
                    allow_revisions: bool) -> dict:
    revisions = result["revisions"]
    expected = (365, 4, 144)
    checks.add(name + ".revisions_shape", revisions.shape == expected,
               expected_shape=list(expected), actual_shape=list(revisions.shape))
    if revisions.shape != expected:
        return {}
    checks.close(name + ".midnight_revision_is_plan", revisions[:, 0], result["plan"])
    reconstructed = result["plan"].copy()
    active_count = {}
    for issue in range(1, 4):
        start = issue * 36
        current = revisions[:, issue]
        prefix_hidden = np.all(np.isnan(current[:, :start]))
        checks.add(name + f".issue_{issue * 6:02d}_does_not_rewrite_past", prefix_hidden)
        suffix = current[:, start:]
        all_missing = np.all(np.isnan(suffix), axis=1)
        all_finite = np.all(np.isfinite(suffix), axis=1)
        checks.add(name + f".issue_{issue * 6:02d}_complete_or_unused",
                   np.all(all_missing | all_finite))
        active_count[str(issue * 6)] = int(np.count_nonzero(all_finite))
        reconstructed[all_finite, start:] = suffix[all_finite]
        if not allow_revisions:
            checks.add(name + f".issue_{issue * 6:02d}_unused", np.all(all_missing))
    checks.close(name + ".adjusted_matches_chronological_revisions", reconstructed,
                 result["adjusted"])
    return active_count


def check_year(checks: Checks, name: str, dispatch: dict, data: dict) -> dict:
    keys = ("plan", "adjusted", "charge", "discharge", "emergency", "spill", "soc", "costs", "revisions")
    result = {key: dispatch[name + "_" + key] for key in keys}
    shape_by_key = {"soc": (365, 145), "costs": (365, 4)}
    valid = [finite_shape(checks, name + "." + key, values,
                          shape_by_key.get(key, (365, 144)))
             for key, values in result.items() if key != "revisions"]
    if not all(valid):
        return {}
    net = (data["load"] - data["pv"]) * HOURS
    check_physics(checks, name, result["adjusted"], result["charge"], result["discharge"],
                  result["emergency"], result["spill"], result["soc"], net)
    checks.add(name + ".nonnegative_plan", np.min(result["plan"]) >= -ENERGY_TOLERANCE,
               minimum=float(np.min(result["plan"])))
    checks.close(name + ".initial_soc", result["soc"][0, 0], INITIAL_SOC)
    checks.close(name + ".cross_day_soc", result["soc"][1:, 0], result["soc"][:-1, -1])
    dynamic = name.startswith("q4_")
    price = data["dynamic_price"] if dynamic else np.broadcast_to(data["fixed_price"], (365, 144))
    # Main convention: original nomination remains payable; down-adjustment
    # incurs an additional 50% cancellation penalty, up-adjustment costs 150%.
    increase = np.maximum(result["adjusted"] - result["plan"], 0)
    decrease = np.maximum(result["plan"] - result["adjusted"], 0)
    base_cost = np.sum(price * result["plan"], axis=1)
    adjustment_cost = np.sum(price * (1.5 * increase + 0.5 * decrease), axis=1)
    emergency_cost = np.sum(5.0 * price * result["emergency"], axis=1)
    recomputed = np.column_stack((base_cost, adjustment_cost, emergency_cost,
                                 base_cost + adjustment_cost + emergency_cost))
    for index, label in enumerate(("plan", "adjustment", "emergency", "total")):
        checks.close(name + ".settlement_" + label, result["costs"][:, index],
                     recomputed[:, index], COST_TOLERANCE)
    active = check_revisions(checks, name, result, name in ("q3", "q4_3"))
    if name in ("q2", "q4_2"):
        checks.close(name + ".no_adjustment", result["plan"], result["adjusted"])
    return {"submission_days": 334, "submission_start": "2025-02-01",
            "february_initial_soc_kwh": float(result["soc"][31, 0]),
            "annual_terminal_soc_kwh": float(result["soc"][-1, -1]),
            "submitted_emergency_kwh": float(result["emergency"][31:].sum()),
            "submitted_costs_yuan": recomputed[31:].sum(axis=0).tolist(),
            "active_revision_days_by_hour": active}


def check_original_sources(checks: Checks) -> None:
    audit = json.loads((ROOT / "data/processed/audit.json").read_text(encoding="utf-8"))
    for name, expected in audit["source_sha256"].items():
        actual = hashlib.sha256((ROOT / "data/raw" / name).read_bytes()).hexdigest()
        checks.add("source_sha256." + name, actual == expected, sha256=actual)


def check_causality(checks: Checks, data: dict) -> None:
    from model import ForecastCache, point_forecast, risk_forecast

    point_cases, largest_error = 0, 0.0
    for day in (0, 1, 7, 31, 100, 364):
        for issue in range(4):
            start = issue * 36
            changed = {key: value.copy() for key, value in data.items()}
            for key in ("load", "pv", "dynamic_price"):
                # All current/future delivery values are hidden at issue time.
                changed[key][day, start:] += 123456.0
                changed[key][day + 1:] += 345678.0
            changed["forecast"][day, issue + 1:] += 765432.0
            changed["forecast"][day + 1:] += 876543.0
            # A current batch is visible in full, but targets beyond midnight
            # are unused by this single-day predictor and must not affect it.
            changed["forecast"][day, issue, 144 - start:] += 987654.0
            for use_forecast in (False, True):
                for dynamic in (False, True):
                    baseline = point_forecast(data, day, issue, use_forecast, dynamic)
                    mutated = point_forecast(changed, day, issue, use_forecast, dynamic)
                    differences = [float(np.max(np.abs(a - b))) for a, b in zip(baseline, mutated)]
                    largest_error = max(largest_error, *differences)
                    point_cases += 1
    checks.add("causality.point_forecast_hidden_future_invariance", largest_error == 0.0,
               cases=point_cases, maximum_absolute_error=largest_error,
               mutated_fields=["current_future_load", "current_future_pv", "current_future_price",
                               "unreleased_forecasts", "unused_cross_midnight_forecast_targets"])

    # Positive control: a forecast which has actually been released must have
    # an effect, so a constant/no-op implementation cannot pass all tests.
    day, issue = 100, 2
    changed = dict(data)
    changed["forecast"] = data["forecast"].copy()
    changed["forecast"][day, issue, :72] += 120.0
    baseline = point_forecast(data, day, issue, True, True)
    visible_change = point_forecast(changed, day, issue, True, True)
    checks.close("causality.published_forecast_positive_control", visible_change[0] - baseline[0],
                 np.full(72, -20.0), tolerance=1e-10)

    # No full build_cache comparison: forecast-error containers deliberately
    # contain realized outcomes for retrospective scoring, but current risk
    # predictions are permitted to consume only already-completed days.
    rng = np.random.default_rng(20260910)
    shape = (365, 4, 144)
    random_net = rng.normal(100.0, 30.0, shape)
    errors = rng.normal(0.0, 10.0, shape)
    unused = np.zeros(shape)
    cache = ForecastCache(random_net, unused, errors, unused, unused)
    risk_cases, risk_maximum = 0, 0.0
    for day in (0, 7, 8, 31, 100, 364):
        changed_errors = errors.copy()
        changed_errors[day:] += 1e9
        changed_cache = ForecastCache(random_net, unused, changed_errors, unused, unused)
        for issue in range(4):
            for quantile in (0.5, 0.8):
                before = risk_forecast(cache, day, issue, quantile)
                after = risk_forecast(changed_cache, day, issue, quantile)
                risk_maximum = max(risk_maximum, float(np.max(np.abs(before - after))))
                risk_cases += 1
    checks.add("causality.risk_forecast_current_and_future_error_invariance", risk_maximum == 0.0,
               cases=risk_cases, maximum_absolute_error=risk_maximum)
    changed_errors = errors.copy()
    changed_errors[72:100] += 50.0
    changed_cache = ForecastCache(random_net, unused, changed_errors, unused, unused)
    checks.close("causality.completed_past_error_positive_control",
                 risk_forecast(changed_cache, 100, 0, 0.8) - risk_forecast(cache, 100, 0, 0.8),
                 np.full(144, 50.0), tolerance=1e-10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/data.npz")
    parser.add_argument("--dispatch", type=Path, default=ROOT / "outputs/main/dispatch.npz")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/main/validation.json")
    parser.add_argument("--causality-only", action="store_true",
                        help="Run predictor temporal checks and source hashes; print without writing output.")
    args = parser.parse_args()
    with np.load(args.data, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    checks = Checks()
    check_original_sources(checks)
    check_causality(checks, data)
    summary = {}
    if not args.causality_only:
        with np.load(args.dispatch, allow_pickle=False) as archive:
            dispatch = {key: archive[key] for key in archive.files}
        try:
            summary["q1"] = check_q1(checks, dispatch, data)
            for name in ("q2", "q3", "q4_2", "q4_3"):
                summary[name] = check_year(checks, name, dispatch, data)
        except KeyError as error:
            checks.add("dispatch.required_keys", False, missing_key=str(error))
    report = {"status": "passed" if checks.passed else "failed",
              "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "causality_only" if args.causality_only else "full_dispatch",
              "artifact_sha256": {
                  str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path):
                  hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in ([args.data.resolve(), Path(__file__).resolve(), ROOT / "scripts/model.py"]
                               + ([] if args.causality_only else [args.dispatch.resolve()]))
              },
              "settlement_convention": "original_plan_plus_50pct_down_penalty_150pct_up_500pct_emergency",
              "check_count": len(checks.results),
              "failed_checks": [item["name"] for item in checks.results if not item["passed"]],
              "summary": summary, "checks": checks.results}
    if not args.causality_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "scope", "check_count", "failed_checks")},
                     ensure_ascii=False, indent=2))
    if not checks.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
