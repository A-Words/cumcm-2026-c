"""Independently recompute constraints and bills of supplementary paper experiments."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "outputs/experiments/paper-study"
    report = json.loads((folder / "sensitivity.json").read_text(encoding="utf-8"))
    arrays = np.load(folder / "dispatch.npz")
    data = np.load(ROOT / "data/processed/data.npz")
    primary = np.load(ROOT / "outputs/main/dispatch.npz")
    checks = []

    def check(name, residual, tolerance=1e-6):
        error = float(np.max(np.abs(residual)))
        checks.append(dict(name=name, error=error, tolerance=tolerance, passed=error <= tolerance))

    for name, expected in report["source_sha256"].items():
        check("hash." + name, int(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected), 0)
    check("archive_hash", int(hashlib.sha256((folder / "dispatch.npz").read_bytes()).hexdigest() != report["dispatch_sha256"]), 0)
    for scene, params in report["q1"].items():
        a = {name: arrays[f"{scene}__{name}"] for name in ("grid", "charge", "discharge", "soc", "spill")}
        c, b, s = a["charge"], a["discharge"], a["soc"]
        eta = params["eta"]
        net = (data["q1_load"] - data["q1_pv"]) / 6
        check(scene + ".balance", a["grid"] + b - net - c - a["spill"])
        check(scene + ".state", np.diff(s) - eta*c + b/eta)
        check(scene + ".inventory", np.maximum(np.abs(s - 6000) - params["usable_kwh"]/2, 0))
        check(scene + ".power", np.maximum(np.r_[c, b] - params["power_kw"]/6, 0))
        check(scene + ".nonnegative", np.minimum(np.r_[a["grid"], c, b, a["spill"]], 0))
        check(scene + ".exclusive", np.minimum(c, b))
        check(scene + ".boundary", s[[0, -1]] - 6000)
        bill = a["grid"] @ data["fixed_price"]
        check(scene + ".bill", bill - params["cost"])
        check(scene + ".dual_gap", bill - params["dual_bound_yuan"])
        if params["usable_kwh"] == 9600 and params["power_kw"] == 5000 and eta == .9:
            check(scene + ".main_cost", bill - primary["q1_grid"] @ data["fixed_price"])
    for scene, params in report["q4"].items():
        names = ("plan", "adjusted", "charge", "discharge", "emergency", "spill", "soc", "costs")
        a = {name: arrays[f"{scene}__{name}"] for name in names}
        c, b, s = a["charge"], a["discharge"], a["soc"]
        net = (data["load"] - data["pv"]) / 6
        check(scene + ".balance", a["adjusted"] + a["emergency"] + b - net - c - a["spill"])
        check(scene + ".state", np.diff(s, axis=1) - .9*c + b/.9)
        check(scene + ".bounds", np.maximum(np.abs(s - 6000) - 4800, 0))
        check(scene + ".power", np.maximum(np.stack([c, b]) - 5000/6, 0))
        check(scene + ".nonnegative", np.minimum(np.stack([a[n] for n in names[:6]]), 0))
        check(scene + ".exclusive", np.minimum(c, b))
        check(scene + ".no_plan_reduction", np.minimum(a["adjusted"] - a["plan"], 0))
        check(scene + ".continuity", s[1:, 0] - s[:-1, -1])
        check(scene + ".common_start", s[31, 0] - primary[params["strategy"] + "_soc"][31, 0])
        p = data["dynamic_price"]
        original = (p*a["plan"]).sum(axis=1)
        adjustment = (p*(1.5*np.maximum(a["adjusted"]-a["plan"], 0)
                         + .5*np.maximum(a["plan"]-a["adjusted"], 0))).sum(axis=1)
        emergency = (5*p*a["emergency"]).sum(axis=1)
        costs = np.c_[original, adjustment, emergency, original+adjustment+emergency]
        check(scene + ".daily_bills", costs-a["costs"])
        check(scene + ".total_bill", costs[31:, 3].sum()-params["summary"]["total_cost"])
        check(scene + ".emergency_total", a["emergency"][31:].sum()-params["summary"]["emergency_kwh"])
    result = dict(status="passed" if all(c["passed"] for c in checks) else "failed", check_count=len(checks),
                  checks=checks, source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in ("scripts/validate_paper_sensitivity.py", "outputs/experiments/paper-study/sensitivity.json", "outputs/experiments/paper-study/dispatch.npz")},
                  limits="Direct feasibility and billing checks; Q1 primal/recorded dual agreement. Q4 retains the existing causal predictor and is same-year sensitivity, not optimality or external validation.")
    (folder / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(result["status"], len(checks), "checks")
    if result["status"] != "passed":
        raise SystemExit([c for c in checks if not c["passed"]])


if __name__ == "__main__":
    main()
