"""Supplementary paper experiments; never replace the submitted main strategies."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

from model import DT, build_cache, lp_structure, simulate, summarize

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/experiments/paper-study"
SOURCES = ("scripts/evaluate_paper_sensitivity.py", "scripts/model.py",
           "data/processed/data.npz", "outputs/main/summary.json", "outputs/main/dispatch.npz")


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def solve_day(data, usable=9600.0, power=5000.0, eta=0.9):
    """Vary usable inventory symmetrically about the same 6000 kWh boundary."""
    n = 144
    net = (data["q1_load"] - data["q1_pv"]) * DT
    price = data["fixed_price"]
    lower, upper = np.zeros(5 * n), np.full(5 * n, np.inf)
    lower[3*n:4*n], upper[3*n:4*n] = 6000 - usable/2, 6000 + usable/2
    lower[4*n-1] = upper[4*n-1] = 6000
    upper[n:3*n] = power * DT
    objective = np.r_[price, np.zeros(4*n)]
    rhs = np.r_[net, 6000, np.zeros(n-1)]
    result = linprog(objective, A_eq=lp_structure(n, eta), b_eq=rhs,
                     bounds=np.c_[lower, upper], method="highs")
    if not result.success:
        raise RuntimeError(result.message)
    x = result.x.copy()
    # Remove any degenerate simultaneous cycle without changing energy or cost.
    delta = np.minimum(x[n:2*n], x[2*n:3*n] / eta**2)
    x[n:2*n] -= delta
    x[2*n:3*n] -= eta**2 * delta
    x[4*n:] += (1 - eta**2) * delta
    finite = np.isfinite(upper)
    dual = float(rhs @ result.eqlin.marginals + lower @ result.lower.marginals
                 + upper[finite] @ result.upper.marginals[finite])
    arrays = dict(grid=x[:n], charge=x[n:2*n], discharge=x[2*n:3*n],
                  soc=np.r_[6000, x[3*n:4*n]], spill=x[4*n:])
    stats = dict(usable_kwh=usable, power_kw=power, eta=eta,
                 cost=float(price @ arrays["grid"]), grid_kwh=float(arrays["grid"].sum()),
                 dual_bound_yuan=dual, solver_status=int(result.status))
    return stats, arrays


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source_hashes = hashes()
    if (OUT / "sensitivity.json").exists():
        previous = json.loads((OUT / "sensitivity.json").read_text(encoding="utf-8"))
        archive = OUT / "dispatch.npz"
        if (previous["source_sha256"] == source_hashes and archive.exists()
                and previous["dispatch_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()):
            print("Supplementary experiments already match current inputs.")
            return
    data = dict(np.load(ROOT / "data/processed/data.npz"))
    summary = json.loads((ROOT / "outputs/main/summary.json").read_text(encoding="utf-8"))
    primary = np.load(ROOT / "outputs/main/dispatch.npz")
    report = dict(source_sha256=source_hashes, q1={}, q4={},
                  scope="Same-year sensitivity; original main strategies remain unchanged.")
    archive = {}
    configurations = [("usable", value, {"usable": value}) for value in (7680, 8640, 9600, 10560, 11520)]
    configurations += [("power", value, {"power": value}) for value in (4000, 4500, 5000, 5500, 6000)]
    configurations += [("eta", value, {"eta": value}) for value in (.85, .875, .9, .925, .95)]
    configurations += [("no_storage", 0, {"usable": 0, "power": 0})]
    for kind, value, parameters in configurations:
        key = f"q1_{kind}_{value:g}"
        stats, arrays = solve_day(data, **parameters)
        report["q1"][key] = dict(parameter=kind, value=value, **stats)
        archive.update({f"{key}__{name}": a for name, a in arrays.items()})
    for key, forecast in (("q4_2", False), ("q4_3", True)):
        cache = build_cache(data, forecast=forecast, dynamic=True, pv_weight=summary["pv_weights"][key])
        warmup = build_cache(data, forecast=True, dynamic=True) if forecast else cache
        for theta in (-.2, .2):
            print(f"Price-spread sensitivity: {key}, theta={theta:+.1f}", flush=True)
            # Center on the mean of each available remaining forecast horizon.
            mean = np.nanmean(cache.price, axis=2, keepdims=True)
            price = np.maximum(.001, mean + (1 + theta) * (cache.price - mean))
            altered = replace(cache, price=price)
            result = simulate(data, altered, summary["parameters"][key],
                              issues=(36, 72, 108) if forecast else (), dynamic=True,
                              warmup_cache=warmup, progress=True)
            np.testing.assert_allclose(result["soc"][:31], primary[f"{key}_soc"][:31], atol=1e-6, rtol=0)
            scene = f"{key}_spread_{theta:+.1f}"
            report["q4"][scene] = dict(strategy=key, theta=theta, summary=summarize(result),
                                       evaluation="2025-02-01/2025-12-31", common_january_warmup=True)
            archive.update({f"{scene}__{name}": array for name, array in result.items()})
    np.savez_compressed(OUT / "dispatch.npz", **archive)
    report["dispatch_sha256"] = hashlib.sha256((OUT / "dispatch.npz").read_bytes()).hexdigest()
    (OUT / "sensitivity.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("Saved 16 deterministic day studies and 4 annual price-spread studies.")


if __name__ == "__main__":
    main()
