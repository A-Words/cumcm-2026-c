"""问题一：确定性单日购电与储能优化，以及积分/效率口径对照。"""
import numpy as np
from model import DT, ETA, INITIAL, optimize
from solve_common import run_question


def q1_solution(data, trapezoid=False, eta=ETA):
    suffix = '_trapezoid' if trapezoid else ''
    net = (data['q1_load'+suffix]-data['q1_pv'+suffix])*DT
    sol = optimize(net, data['fixed_price'], INITIAL, terminal_equal=True,eta=eta)
    exact = optimize(net, data['fixed_price'], INITIAL, tie_break=False, terminal_equal=True,eta=eta)
    sol['cost'] = float(sol['grid']@data['fixed_price'])
    sol['unperturbed_lower_bound'] = float(exact['grid']@data['fixed_price'])
    sol['optimality_gap_yuan'] = sol['cost']-sol['unperturbed_lower_bound']
    sol['net'] = net
    return sol


def solve(data):
    return dict(q1=q1_solution(data),
                q1_trapezoid=q1_solution(data, trapezoid=True),
                q1_roundtrip90=q1_solution(data, eta=float(np.sqrt(.9))))


if __name__ == '__main__':
    run_question('q1', solve)
