from q2 import solve as solve_day_ahead
from q3 import solve as solve_intraday
from solve_common import run_question


def solve(context):
    solve_day_ahead(context, dynamic=True)
    solve_intraday(context, dynamic=True)


if __name__ == '__main__':
    run_question('q4', solve)
