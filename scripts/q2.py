from model import simulate
from solve_common import run_question


def solve(context, *, dynamic=False):
    name = 'q4_2' if dynamic else 'q2'
    data = context.data
    print(f'January calibration: {name}',flush=True)
    fit=context.calibrate(dynamic,(0.0,),issues=())
    tau=fit['selected']['quantile']
    context.selected[name],context.calibration[name],context.weights[name]=tau,fit['candidates'],0.0
    context.caches[name]=context.cache_for(dynamic,0.0)
    context.results[name]=simulate(data,context.caches[name],tau,dynamic=dynamic,progress=True)


if __name__ == '__main__':
    run_question('q2', solve)
