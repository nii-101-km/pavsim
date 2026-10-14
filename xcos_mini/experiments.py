"""Explicit experiment lifecycle: initialize, run local time, complete with J."""
import copy
from .core import Engine,BlockError
from .optimization import optimize,finite,simulate_with_optimizers
from .optimization_blocks import Optimizer
from .workspace_blocks import Experiment,collect_plots

def execute_workspace(model,build_model,t_end=1.,h=.01,method='rk4',selected=None):
    experiments=[b for b in model.get('blocks',[]) if b['type']=='experiment']
    if not experiments:
        result,reports=simulate_with_optimizers(model,build_model,t_end,h,method)
        return result,reports,[]
    world=copy.deepcopy(model);reports=[];completed=[];latest={};trial_runs={}
    probe=copy.deepcopy(world)
    for b in probe['blocks']:
        if b['type']=='experiment':b.setdefault('params',{})['_result']=0.
    initial=build_model(probe)
    for bid,block in initial.blocks.items():
        if block.state_kind=='integrated':raise BlockError(bid+': динамический контур разместите внутри Эксперимента')
    def snapshot(candidate,scores=None):
        local=copy.deepcopy(candidate)
        for b in local['blocks']:
            if b['type']=='experiment':b.setdefault('params',{})['_result']=(scores or {}).get(str(b['id']),0.)
        exe=build_model(local)
        return Engine(exe,0,1).run()
    def port_value(results,bid,port):
        value=results[str(bid)][-1][1]
        return value[port] if isinstance(value,tuple) else value
    def run_experiment(candidate,eid,stack=()):
        if eid in stack:raise BlockError('Цикл зависимостей экспериментов: '+str(stack+(eid,)))
        exp=next(b for b in candidate['blocks'] if str(b['id'])==eid)
        config=dict(Experiment.parameters);config.update(exp.get('params',{}))
        end=finite(config['t_end'],'Время эксперимента');step=finite(config['h'],'Шаг эксперимента')
        if end<=0 or step<=0 or end/step<1 or end/step>10000:raise BlockError(eid+': нужен положительный прогон, до 10000 шагов')
        if config['method'] not in Engine.METHODS:raise BlockError(eid+': неизвестный метод')
        by_id={str(b['id']):b for b in candidate['blocks']};wires=candidate.get('connections',[])
        dependencies=set()
        def upstream(bid,visited):
            if bid in visited:return
            visited.add(bid)
            b=by_id[bid]
            if b['type']=='optimizer':return # Parameters are a committed batch, not J feedback.
            if b['type']=='experiment':dependencies.add(bid);return
            for c in wires:
                if str(c['to'])==bid:upstream(str(c['from']),visited)
        for c in wires:
            if str(c['to'])==eid:upstream(str(c['from']),set())
        scores={}
        for dep in sorted(dependencies):scores[dep]=run_experiment(candidate,dep,stack+(eid,))[0]
        values=snapshot(candidate,scores);parameters=[0.,0.,0.]
        for c in wires:
            if str(c['to'])==eid:parameters[int(c.get('to_port',0))]=port_value(values,c['from'],int(c.get('from_port',0)))
        inside=copy.deepcopy(exp.get('internal',{}));blocks=inside.get('blocks',[])
        terminals=[b for b in blocks if b['type']=='experiment_result']
        if len(terminals)!=1:raise BlockError(eid+': внутри нужен ровно один выход J')
        result_id=str(terminals[0]['id']);incoming=[c for c in inside.get('connections',[]) if str(c['to'])==result_id]
        if len(incoming)!=1:raise BlockError(eid+': подключите итоговую оценку к выходу J')
        seen=set()
        for b in blocks:
            if b['type']=='experiment_input':
                index=int(b.get('params',{}).get('port',0))
                if index not in range(3) or index in seen:raise BlockError(eid+': неверные или повторные входные терминалы')
                seen.add(index);b['type']='constant';b['params']={'value':parameters[index]}
            elif b['type']=='experiment_result':b['type']='graph_display';b['params']={}
            elif b['type'] in ('experiment','optimizer'):raise BlockError('Вложенный запуск эксперимента/оптимизатора внутри эксперимента не поддерживается')
        if seen!=set(range(3)):raise BlockError(eid+': нужны терминалы p1, p2 и p3')
        # Every call constructs a new production Model/Engine: all integrated
        # states, delay histories, accumulated objectives and seeds restart.
        results,_=simulate_with_optimizers(inside,build_model,end,step,config['method'])
        source=incoming[0];j=finite(port_value(results,source['from'],int(source.get('from_port',0))),'Итоговая J')
        results[result_id][-1]=(results[result_id][-1][0],j)
        info=dict(block_id=eid,parameters=parameters,result=j,status='completed',t_end=end,h=step,method=config['method'])
        return j,results,info
    optimizers=[b for b in world['blocks'] if b['type']=='optimizer']
    for opt in optimizers:
        if selected is not None:continue
        params=dict(Optimizer.parameters);params.update(opt.get('params',{}))
        if not params['enabled']:continue
        oid=str(opt['id']);wires=[c for c in world.get('connections',[]) if str(c['to'])==oid and int(c.get('to_port',0))==0]
        if len(wires)!=1:raise BlockError(oid+': подключите завершённую J эксперимента')
        eid=str(wires[0]['from']);exp=next((b for b in world['blocks'] if str(b['id'])==eid and b['type']=='experiment'),None)
        if exp is None:raise BlockError(oid+': на рабочем поле экспериментов вход J должен идти от Эксперимента')
        config=dict(Experiment.parameters);config.update(exp.get('params',{}))
        intervals=[[params[f'min_p{i}'],params[f'max_p{i}']] if params[f'optimize_p{i}'] else [params[f'p{i}']]*2 for i in range(1,4)]
        def evaluate(candidate):
            j,result,info=run_experiment(candidate,eid)
            # Optimizer consumes only the experiment's final scalar J. No
            # knowledge of a controller or of the experiment's objective type.
            metrics=dict(iae=abs(j),ise=j*j,settled=True,settling_time=None,overshoot=0.,oscillation=0.,final_error=0.,tail_error=0.)
            return metrics,[(0,j),(float(config['t_end']),j)],j
        settings=dict(bounds=intervals,algorithm=params['algorithm'],algorithm_options=params['algorithm_options'],max_evaluations=params['max_evaluations'],t_end=config['t_end'],h=config['h'],method=config['method'])
        report=optimize(world,build_model,settings,binding=dict(parameters=[(oid,f'p{i}') for i in range(1,4)],evaluate=evaluate))
        values={f'p{i}':report['coefficients'][f'k{i}'] for i in range(1,4)}
        opt.setdefault('params',{}).update(values)
        reports.append(dict(block_id=oid,experiment_id=eid,values=values,algorithm=params['algorithm'],evaluations=report['evaluations'],converged=None,score=report['score'],trace=report['trace']))
        trial_runs[oid]=(eid,report['trace'])
    if selected is not None and not any(str(e['id'])==str(selected) for e in experiments):raise BlockError('Эксперимент не найден')
    for exp in experiments:
        if selected is not None and str(exp['id'])!=str(selected):continue
        eid=str(exp['id']);j,results,info=run_experiment(world,eid);latest[eid]=j;completed.append(info)
        for bid,series in results.items():latest[eid+'/'+bid]=series
    results=snapshot(world,{k:v for k,v in latest.items() if '/' not in k})
    for key,value in latest.items():
        if '/' in key:results[key]=value
    # Outer plot axis is evaluation number, not the local experiment clock.
    for b in world['blocks']:
        if not b['type'].startswith('graph_'):continue
        incoming=sorted([c for c in world.get('connections',[]) if str(c['to'])==str(b['id'])],key=lambda c:int(c.get('to_port',0)))
        plot_optimizer=next((oid for oid,(eid,trace) in trial_runs.items() if any(str(c['from']) in (oid,eid) for c in incoming)),None)
        if plot_optimizer:
            eid,trace=trial_runs[plot_optimizer];points=[]
            count=1 if b['type']=='graph_display' else 2 if b['type'] in ('graph_series2','graph_xy') else 4 if b['type']=='graph_series4' else 3
            for trial_step,trial in enumerate(trace,1):
                if trial['score'] is None:continue
                values=[0.]*count
                for c in incoming:
                    source=str(c['from']);port=int(c.get('from_port',0))
                    values[int(c.get('to_port',0))]=trial['values'][port] if source==plot_optimizer else trial['score'] if source==eid else port_value(results,source,port)
                points.append((trial_step,values[0] if count==1 else tuple(values)))
            results[str(b['id'])]=points
        else:
            count=1 if b['type']=='graph_display' else 2 if b['type'] in ('graph_series2','graph_xy') else 4 if b['type']=='graph_series4' else 3
            values=[0.]*count
            for c in incoming:values[int(c.get('to_port',0))]=port_value(results,c['from'],int(c.get('from_port',0)))
            results[str(b['id'])]=[(1,values[0] if count==1 else tuple(values))]
    if selected is not None:results={key:value for key,value in results.items() if key==str(selected) or key.startswith(str(selected)+'/')}
    return results,reports,completed
