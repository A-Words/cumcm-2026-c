"""Independently reconstruct Q1 as a MILP and verify the delivered LP solution.

Run after prepare_data.py and solve.py:
    python scripts/verify_q1_milp.py

This verifier does not import model.py or reuse its constraint matrices. Each of
the 144 delivery slots has a binary variable prohibiting simultaneous charging
and discharging. Its objective contains electricity cost only, without numeric
tie-breaking penalties.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


ROOT = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(data_path: Path, dispatch_path: Path, time_limit: float) -> dict:
    with np.load(data_path) as data:
        price = data["fixed_price"].astype(float)
        net = (data["q1_load"] - data["q1_pv"]) / 6
    with np.load(dispatch_path) as dispatch:
        reference_grid = dispatch["q1_grid"].copy()
    n = len(net)
    if n != 144 or price.shape != (n,) or reference_grid.shape != (n,):
        raise ValueError("Q1 requires 144 aligned price, net-load, and grid slots")

    # Independent ordering: grid, charge, discharge, end-of-slot SOC, unused, mode.
    size = 6 * n
    power_limit = 5000 / 6
    efficiency = 0.9
    initial = 6000.0
    objective = np.zeros(size)
    objective[:n] = price
    equations = lil_matrix((2 * n, size))
    rhs = np.r_[net, initial, np.zeros(n - 1)]
    mode_constraints = lil_matrix((2 * n, size))
    mode_upper = np.r_[np.zeros(n), np.full(n, power_limit)]

    for t in range(n):
        # grid + discharge - charge - unused = net load.
        equations[t, t] = 1
        equations[t, n + t] = -1
        equations[t, 2 * n + t] = 1
        equations[t, 4 * n + t] = -1
        # S_after - S_before - eta * charge + discharge / eta = 0.
        equations[n + t, n + t] = -efficiency
        equations[n + t, 2 * n + t] = 1 / efficiency
        equations[n + t, 3 * n + t] = 1
        if t:
            equations[n + t, 3 * n + t - 1] = -1
        # charge <= limit * mode; discharge <= limit * (1 - mode).
        mode_constraints[t, n + t] = 1
        mode_constraints[t, 5 * n + t] = -power_limit
        mode_constraints[n + t, 2 * n + t] = 1
        mode_constraints[n + t, 5 * n + t] = power_limit

    equations = equations.tocsr()
    mode_constraints = mode_constraints.tocsr()
    lower = np.zeros(size)
    upper = np.full(size, np.inf)
    lower[3 * n:4 * n] = 1200
    upper[3 * n:4 * n] = 10800
    upper[n:3 * n] = power_limit
    lower[4 * n - 1] = upper[4 * n - 1] = initial
    upper[5 * n:] = 1
    integrality = np.r_[np.zeros(5 * n, dtype=int), np.ones(n, dtype=int)]

    started = time.perf_counter()
    result = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=[
            LinearConstraint(equations, rhs, rhs),
            LinearConstraint(mode_constraints, np.full(2 * n, -np.inf), mode_upper),
        ],
        options={"time_limit": time_limit, "mip_rel_gap": 1e-9},
    )
    elapsed = time.perf_counter() - started
    evidence = {
        "verification": "Independent Q1 MILP with explicit charge/discharge exclusivity",
        "source_hashes_sha256": {
            "data": file_hash(data_path),
            "dispatch": file_hash(dispatch_path),
            "verifier": file_hash(Path(__file__)),
        },
        "inputs": {"data": str(data_path), "dispatch": str(dispatch_path)},
        "versions": {"numpy": np.__version__, "scipy": scipy.__version__},
        "num_intervals": n,
        "num_variables": size,
        "num_binaries": n,
        "num_equalities": 2 * n,
        "num_mode_inequalities": 2 * n,
        "efficiency_charge": efficiency,
        "efficiency_discharge": efficiency,
        "soc_initial_kwh": initial,
        "soc_terminal_constraint_kwh": initial,
        "status": int(result.status),
        "message": str(result.message),
        "solver_success": bool(result.success),
        "solve_seconds": elapsed,
        "solver_relative_gap_tolerance": 1e-9,
        "feasibility_tolerance": 1e-6,
        "reference_cost_tolerance_yuan": 1e-5,
    }
    if result.x is None:
        evidence.update(passed=False, objective=None, gap=None,
                        max_constraint_violation=None)
        return evidence

    x = result.x
    equality_error = float(np.max(np.abs(equations @ x - rhs)))
    inequality_error = float(max(0, np.max(mode_constraints @ x - mode_upper)))
    bound_error = float(max(0, np.max(lower - x), np.max(x - upper)))
    binary_error = float(np.max(np.abs(x[5 * n:] - np.round(x[5 * n:]))))
    maximum_error = max(equality_error, inequality_error, bound_error, binary_error)
    reference_cost = float(reference_grid @ price)
    solved_cost = float(price @ x[:n])
    gap = solved_cost - reference_cost
    evidence.update(
        objective=solved_cost,
        objective_unit="CNY",
        reference_lp_cost_yuan=reference_cost,
        gap=gap,
        gap_definition="independent MILP electricity cost minus delivered Q1 LP electricity cost, CNY",
        absolute_gap_yuan=abs(gap),
        solver_mip_gap=float(result.mip_gap),
        solver_dual_bound=float(result.mip_dual_bound),
        solver_node_count=int(result.mip_node_count),
        max_constraint_violation=maximum_error,
        max_equality_residual_kwh=equality_error,
        max_inequality_violation_kwh=inequality_error,
        max_bound_violation=bound_error,
        max_binary_integrality_violation=binary_error,
        max_simultaneous_charge_discharge_kwh=float(np.max(np.minimum(x[n:2*n], x[2*n:3*n]))),
        soc_terminal_kwh=float(x[4 * n - 1]),
        grid_total_kwh=float(x[:n].sum()),
        passed=bool(result.success and maximum_error <= 1e-6 and abs(gap) <= 1e-5),
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/data.npz")
    parser.add_argument("--dispatch", type=Path, default=ROOT / "outputs/main/dispatch.npz")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/main/q1-milp-verification.json")
    parser.add_argument("--time-limit", type=float, default=60)
    args = parser.parse_args()
    evidence = verify(args.data.resolve(), args.dispatch.resolve(), args.time_limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: evidence.get(key) for key in (
        "passed", "status", "objective", "gap", "max_constraint_violation", "num_binaries"
    )}, indent=2))
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
