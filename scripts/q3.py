from model import summarize
from solve_common import PV_WEIGHTS, run_question


def solve(context, *, dynamic=False):
    name = 'q4_3' if dynamic else 'q3'
    print(f'January joint PV/quantile calibration: {name}',flush=True)
    fit=context.calibrate(dynamic,PV_WEIGHTS)
    context.revision['selection'][name]=fit
    choice=fit['selected']; tau,weight=choice['quantile'],choice['pv_weight']
    context.selected[name],context.weights[name]=tau,weight
    context.calibration[name]=[x for x in fit['candidates'] if x['pv_weight']==weight]
    context.caches[name]=context.cache_for(dynamic,weight)
    context.revision['baselines'][name]={}
    for w,label,kind in [(1.0,'原纯附件3基准','pure_attachment3'),(0.0,'历史光伏基准','historical')]:
        baseline_choice=min((x for x in fit['candidates'] if x['pv_weight']==w),key=lambda x:x['validation_cost'])
        scene_id=name+('_legacy' if w==1 else '_historical')
        context.scene(scene_id,label,w,baseline_choice['quantile'],dynamic=dynamic)
        context.revision['scenes'][scene_id]['validation_cost']=baseline_choice['validation_cost']
        context.revision['baselines'][name][kind]=scene_id
        if w == 0:
            common_id=name+'_historical_fixed'
            context.scene(common_id,'历史光伏基准（共同热启动）',w,baseline_choice['quantile'],
                  dynamic=dynamic,warmup_mode='attachment3_fixed')
            context.revision['scenes'][common_id]['validation_cost']=baseline_choice['validation_cost']
            context.revision['baselines'][name]['historical_common_warmup']=common_id
    context.results[name]=context.scene(name+'_selected','修订主策略',weight,tau,dynamic=dynamic,
                        warmup_mode='attachment3_fixed')
    print(name,'selected',choice,'summary',summarize(context.results[name]),flush=True)


if __name__ == '__main__':
    run_question('q3', solve)
