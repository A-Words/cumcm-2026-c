"""问题四：动态电价下分别求解日前计划与日内调整策略。"""
from q2 import solve as solve_day_ahead
from q3 import solve as solve_intraday
from solve_common import run_question


def solve(context):
    solve_day_ahead(context, dynamic=True)
    solve_intraday(context, dynamic=True)


if __name__ == '__main__':
    run_question('q4', solve)
