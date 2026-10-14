"""Bounded PI/PID tuning around the existing Engine; no solver changes."""
import copy
import math
import random

from .core import BlockError, Engine

OBJECTIVES = ('settling_time', 'overshoot', 'oscillation', 'iae', 'ise')


def finite(value, label):
    if isinstance(value, bool):
        raise BlockError(f'{label}: требуется число, не true/false')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise BlockError(f'{label}: требуется число')
    if not math.isfinite(value):
        raise BlockError(f'{label}: требуется конечное число')
    return value



ALGORITHM_DEFAULTS = {
    'coordinate':dict(random_starts=0,initial_step=.25,tolerance=.0005,shrink=.5,max_iterations=1000),
    'nelder_mead':dict(random_starts=0,initial_step=.15,tolerance=.0005,reflection=1.,expansion=2.,contraction=.5,shrink=.5,max_iterations=500),
    'gradient':dict(random_starts=0,initial_step=.2,tolerance=.00005,difference_step=.001,shrink=.5,backtracks=12,max_iterations=100),
    'hooke_jeeves':dict(random_starts=0,initial_step=.1,tolerance=.0005,shrink=.5,pattern_step=1.,max_iterations=500),
    'heavy_ball':dict(random_starts=0,initial_step=.1,tolerance=.00005,difference_step=.001,momentum=.5,shrink=.5,backtracks=12,max_iterations=100),
}

def algorithm_options(algorithm, text=''):
    if algorithm not in ALGORITHM_DEFAULTS:raise BlockError('Неизвестный алгоритм оптимизации')
    result=dict(ALGORITHM_DEFAULTS[algorithm]);seen=set()
    if not isinstance(text,str):raise BlockError('Параметры алгоритма должны быть строкой key=value; key=value')
    for item in text.split(';'):
        if not item.strip():continue
        if item.count('=')!=1:raise BlockError('Параметры алгоритма: используйте key=value; key=value')
        key,value=(part.strip() for part in item.split('='))
        if key not in result:raise BlockError('Неизвестный параметр '+key+' для '+algorithm+'. Доступны: '+', '.join(result))
        if key in seen:raise BlockError('Параметр '+key+' указан дважды')
        seen.add(key);number=finite(value.replace(',','.'),key)
        if key=='random_starts':
            if number!=int(number) or not 0<=number<=50:raise BlockError('random_starts: нужно целое число от 0 до 50')
            number=int(number)
        elif key in ('max_iterations','backtracks'):
            if number!=int(number) or not 1<=number<=10000:raise BlockError(key+': нужно целое число от 1 до 10000')
            number=int(number)
        elif key in ('shrink','contraction'):
            if not 0<number<1:raise BlockError(key+': нужно значение строго между 0 и 1')
        elif key=='momentum':
            if not 0<=number<1:raise BlockError('momentum: нужно значение от 0 включительно до 1 исключительно')
        elif key=='pattern_step':
            if not 0<number<=10:raise BlockError('pattern_step: нужно значение больше 0 и не больше 10')
        elif key=='expansion':
            if not number>1:raise BlockError('expansion должен быть больше 1')
        elif key=='reflection':
            if not 0<number<=10:raise BlockError('reflection должен быть больше 0 и не больше 10')
        elif not 0<number<=1:raise BlockError(key+': нужно значение больше 0 и не больше 1 (доля диапазона)')
        result[key]=number
    if result['tolerance']>=result['initial_step']:raise BlockError('tolerance должен быть меньше initial_step')
    return result


def response_metrics(series, target, tolerance=.02):
    """Step response metrics, trapezoidal errors, finite-horizon settling.

    Settling requires the response to stay in the tolerance band for at least
    the last 10% of the horizon. None means settling was not observed.
    Oscillation is excess total variation / (2 * response amplitude).
    """
    if len(series) < 2:
        raise BlockError('Для оценки требуется минимум два отсчёта')
    target = finite(target, 'Уставка')
    tolerance = finite(tolerance, 'Допуск')
    if not 0 < tolerance <= .2:
        raise BlockError('Допуск должен быть больше 0 и не больше 20%')
    points = [(finite(t, 'Время'), finite(y, 'Выход')) for t, y in series]
    t0, y0 = points[0]
    horizon = points[-1][0]-t0
    if horizon <= 0 or any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise BlockError('Время отсчётов должно возрастать')
    scale = abs(target-y0) or max(abs(target), 1.)
    direction = 1 if target >= y0 else -1
    iae = ise = variation = 0.
    for (ta, ya), (tb, yb) in zip(points, points[1:]):
        ea, eb = target-ya, target-yb
        iae += (tb-ta)*(abs(ea)+abs(eb))/2
        ise += (tb-ta)*(ea*ea+eb*eb)/2
        variation += abs(yb-ya)
    band = tolerance*scale
    outside = [i for i, (_, y) in enumerate(points) if abs(y-target) > band]
    first = outside[-1]+1 if outside else 0
    settling = None
    if first < len(points) and points[-1][0]-points[first][0] >= .1*horizon-1e-12:
        settling = points[first][0]-t0
    tail = [abs(y-target)/scale for t, y in points if t >= points[-1][0]-.1*horizon]
    values = {
        'settling_time': settling,
        'overshoot': 100*max(0., max(direction*(y-target)/scale for _, y in points)),
        'oscillation': max(0., variation-abs(points[-1][1]-y0))/(2*scale),
        'iae': iae, 'ise': ise,
        'final_error': abs(points[-1][1]-target),
        'tail_error': max(tail), 'settled': settling is not None,
    }
    if any(not math.isfinite(v) for v in values.values() if isinstance(v, (int, float))):
        raise BlockError('Отклик расходится: критерий не является конечным')
    return values


def objective_score(metrics, objective, horizon, scale):
    if objective not in OBJECTIVES:
        raise BlockError('Неизвестная целевая функция')
    if objective == 'iae':
        return metrics['iae']/(horizon*scale)
    if objective == 'ise':
        return metrics['ise']/(horizon*scale*scale)
    # A stationary output that never reaches the setpoint must not win on
    # zero overshoot/variation. Feasible responses always rank first.
    if not metrics['settled']:
        return 1000+metrics['tail_error']+metrics['iae']/(horizon*scale)
    if objective == 'settling_time':
        return metrics['settling_time']/horizon
    if objective == 'overshoot':
        return metrics['overshoot']/100
    return metrics['oscillation']


def coefficient_sources(model, controller_id):
    """Resolve distinct, dedicated Constant sources on coefficient inputs."""
    blocks = {str(b['id']): b for b in model.get('blocks', [])}
    controller = blocks.get(str(controller_id))
    if controller is None or controller.get('type') not in ('pi', 'pid'):
        raise BlockError('Выберите ПИ или ПИД в корневой схеме')
    wires = model.get('connections', [])
    sources = []
    for port in range(1, 3 if controller['type'] == 'pi' else 4):
        incoming = [c for c in wires if str(c['to']) == str(controller_id) and int(c.get('to_port', 0)) == port]
        if len(incoming) != 1:
            raise BlockError(f'Подключите отдельную Константу к k{port}')
        wire = incoming[0]; source = blocks.get(str(wire['from']))
        if source is None or source.get('type') != 'constant':
            raise BlockError(f'k{port}: для подбора нужен вход от Константы')
        if int(wire.get('from_port', 0)) != 0:
            raise BlockError(f'k{port}: неверный выход Константы')
        uses = [c for c in wires if str(c['from']) == str(source['id'])]
        if len(uses) != 1:
            raise BlockError(f'Константа {source["id"]} должна питать только k{port}, чтобы подбор не менял другие сигналы')
        sources.append(str(source['id']))
    return sources


def optimize(model, build_model, settings, binding=None):
    """Deterministic bounded search in normalized parameter axes.

    build_model creates a fresh production Model for every candidate. Input
    JSON is never mutated, nor are diagrams saved by the optimizer.
    """
    source_ids = coefficient_sources(model, settings.get('controller')) if binding is None else [bid for bid, key in binding['parameters']]
    parameters = [(bid, 'value') for bid in source_ids] if binding is None else binding['parameters']
    output = str(settings.get('output', ''))
    output_block = next((b for b in model.get('blocks', []) if str(b['id']) == output), None)
    if binding is None and (output_block is None or output_block.get('type') == 'subsystem'):
        raise BlockError('Выберите выходной блок в корневой схеме, например График')
    algorithm = settings.get('algorithm', 'coordinate')
    if algorithm not in ALGORITHM_DEFAULTS:
        raise BlockError('Неизвестный алгоритм оптимизации')
    options=algorithm_options(algorithm,settings.get('algorithm_options',''))
    objective = settings.get('objective', 'iae')
    if objective not in OBJECTIVES:
        raise BlockError('Неизвестная целевая функция')
    target = finite(settings.get('target', 1), 'Уставка')
    tolerance = finite(settings.get('tolerance', .02), 'Допуск')
    if not 0 < tolerance <= .2:
        raise BlockError('Допуск должен быть больше 0 и не больше 20%')
    end = finite(settings.get('t_end', 10), 'Время расчёта')
    h = finite(settings.get('h', .01), 'Шаг')
    budget_value = finite(settings.get('max_evaluations', 100), 'Количество расчётов')
    budget = int(budget_value)
    if budget != budget_value or not 20 <= budget <= 300:
        raise BlockError('Количество расчётов должно быть целым от 20 до 300')
    if end <= 0 or h <= 0 or end/h < 1:
        raise BlockError('Время расчёта должно быть положительным и не меньше шага')
    if end/h > 10000 or (math.ceil(end/h)+1)*budget > 600000:
        raise BlockError('Слишком большой объём: уменьшите число расчётов/время или увеличьте шаг (лимит 600000 отсчётов)')
    method = settings.get('method', 'rk4')
    if method not in Engine.METHODS:
        raise BlockError('Неизвестный метод расчёта')
    bounds = settings.get('bounds', [])
    if len(bounds) != len(source_ids):
        raise BlockError('Задайте границы для каждого коэффициента')
    intervals = []
    for i, pair in enumerate(bounds):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise BlockError(f'k{i+1}: нужны две границы')
        lo, hi = (finite(v, f'k{i+1}') for v in pair)
        if not math.isfinite(hi-lo):
            raise BlockError(f'k{i+1}: диапазон слишком велик')
        if lo > hi:
            raise BlockError(f'k{i+1}: нижняя граница больше верхней')
        intervals.append((lo, hi))
    current = [finite(next(b for b in model['blocks'] if str(b['id']) == bid).get('params', {}).get(key, 1), 'Коэффициент') for bid, key in parameters]
    trace = []
    cache = {}; count = 0; failures = 0; last_error = None
    best = None

    def evaluate(values, baseline=False):
        nonlocal count, failures, last_error, best
        key = tuple(values)
        if key in cache:
            return cache[key]
        if count >= budget:
            return None
        count += 1
        candidate = copy.deepcopy(model)
        by_id = {str(b['id']): b for b in candidate['blocks']}
        for (bid, parameter_name), value in zip(parameters, values):
            by_id[bid].setdefault('params', {})[parameter_name] = value
        try:
            if binding is not None and 'evaluate' in binding:
                metrics,series,score=binding['evaluate'](candidate)
            else:
                executable = build_model(candidate)
                results = Engine(executable, end, h, method).run()
                if binding is None:
                    if output not in results:
                        raise BlockError('Выбранный блок не имеет доступного выходного сигнала')
                    series = results[output]
                else:
                    series = executable.blocks[binding['objective_id']].state['history']
                metrics = response_metrics(series, target, tolerance)
                scale = abs(target-series[0][1]) or max(abs(target), 1.)
                score = metrics[objective] if binding is not None and objective in ('iae', 'ise') else objective_score(metrics, objective, series[-1][0]-series[0][0], scale)
            record = dict(values=list(values), metrics=metrics, score=score, series=series)
            # Tie-break equal primary scores by tracking error.
            record['rank'] = (not metrics['settled'] if objective not in ('iae', 'ise') else False,
                              score, metrics['iae'], metrics['ise'])
            if not baseline and (best is None or record['rank'] < best['rank']):
                best = record
        except (BlockError, ValueError, OverflowError, ZeroDivisionError) as exc:
            failures += 1; last_error = str(exc); record = None
        trace.append({'values':list(values),'score':record['score'] if record else None,'baseline':baseline,'error':last_error if record is None else None})
        cache[key] = record
        return record

    baseline = evaluate(current, baseline=True)
    clipped = [min(hi, max(lo, v)) for v, (lo, hi) in zip(current, intervals)]
    first = evaluate(clipped)
    if first is not None:
        best = first
    active = [i for i, (lo, hi) in enumerate(intervals) if hi > lo]
    rng = random.Random(1729)
    starts = [[lo+(hi-lo)*rng.random() for lo, hi in intervals] for _ in range(options['random_starts'])]
    for values in starts:
        evaluate(values)
    if algorithm == 'coordinate':
        step = options['initial_step'];iteration=0
        while count < budget and active and step >= options['tolerance'] and iteration<options['max_iterations']:
            iteration+=1
            if best is None:
                break
            origin = best
            for i in active:
                lo, hi = intervals[i]
                for sign in (-1, 1):
                    values = list(best['values'])
                    values[i] = min(hi, max(lo, values[i]+sign*step*(hi-lo)))
                    evaluate(values)
            if best is origin:
                step *= options['shrink']
    elif algorithm == 'hooke_jeeves' and best is not None and active:
        def exploratory(origin, step):
            found=origin
            for i in active:
                lo,hi=intervals[i]
                for sign in (1,-1):
                    values=list(found['values'])
                    values[i]=min(hi,max(lo,values[i]+sign*step*(hi-lo)))
                    trial=evaluate(values)
                    if trial is not None and trial['rank']<found['rank']:
                        found=trial;break
            return found
        base=best;step=options['initial_step']
        for iteration in range(options['max_iterations']):
            if count>=budget or step<options['tolerance']:break
            found=exploratory(base,step)
            if found['rank']>=base['rank']:
                step*=options['shrink'];continue
            # Follow the successful displacement, then explore around that
            # pattern point. Failed pattern moves return to the last good base.
            while count<budget:
                values=[min(hi,max(lo,b+options['pattern_step']*(b-a)))
                        for a,b,(lo,hi) in zip(base['values'],found['values'],intervals)]
                base=found
                pattern=evaluate(values)
                if pattern is None:break
                found=exploratory(pattern,step)
                if found['rank']>=base['rank']:break
                if found['values']==base['values']:break
    elif algorithm == 'heavy_ball' and best is not None and active:
        # Projected Polyak momentum in normalized coordinates. Restart the
        # velocity and backtrack when inertia proposes a non-improving step.
        origin=best;velocity=[0.]*len(active);step=options['initial_step']
        for iteration in range(options['max_iterations']):
            if count>=budget:break
            gradients=[]
            for i in active:
                lo,hi=intervals[i];width=hi-lo
                left=list(origin['values']);right=list(origin['values'])
                left[i]=max(lo,left[i]-width*options['difference_step'])
                right[i]=min(hi,right[i]+width*options['difference_step'])
                a,b=evaluate(left),evaluate(right)
                denominator=(right[i]-left[i])/width
                if a is None or b is None or not denominator:break
                gradients.append((b['score']-a['score'])/denominator)
            if len(gradients)!=len(active) or not all(math.isfinite(g) for g in gradients):break
            accepted=None
            for attempt in range(options['backtracks']):
                if count>=budget or step<options['tolerance']:break
                motion=[options['momentum']*v-step*g for v,g in zip(velocity,gradients)]
                values=list(origin['values'])
                for i,v in zip(active,motion):
                    lo,hi=intervals[i];values[i]=min(hi,max(lo,values[i]+v*(hi-lo)))
                trial=evaluate(values)
                if trial is not None and trial['rank']<origin['rank']:
                    accepted=trial
                    velocity=[(values[i]-origin['values'][i])/(intervals[i][1]-intervals[i][0]) for i in active]
                    break
                if any(velocity):velocity=[0.]*len(active)
                else:step*=options['shrink']
            if accepted is None:break
            displacement=max(abs(v) for v in velocity)
            origin=accepted
            if displacement<options['tolerance']:break
    elif algorithm == 'nelder_mead' and best is not None and active:
        def unit(values):return [(values[i]-intervals[i][0])/(intervals[i][1]-intervals[i][0]) for i in active]
        def candidate(point):
            point=[min(1.,max(0.,v)) for v in point]
            values=list(best['values'])
            for i,v in zip(active,point):
                lo,hi=intervals[i];values[i]=lo+v*(hi-lo)
            return (point,evaluate(values))
        def rank(item):return item[1]['rank'] if item[1] is not None else (True,float('inf'),float('inf'),float('inf'))
        center=unit(best['values']);simplex=[candidate(center)]
        for axis in range(len(active)):
            point=list(center);point[axis]+= options['initial_step'] if point[axis]<=1-options['initial_step'] else -options['initial_step']
            simplex.append(candidate(point))
        for iteration in range(options['max_iterations']):
            if count>=budget:break
            simplex.sort(key=rank)
            n=len(active)
            if max(abs(v-simplex[0][0][i]) for point,record in simplex for i,v in enumerate(point))<options['tolerance']:break
            centroid=[sum(item[0][i] for item in simplex[:-1])/n for i in range(n)]
            worst=simplex[-1][0]
            reflected=candidate([a+options['reflection']*(a-b) for a,b in zip(centroid,worst)])
            before=count
            if rank(reflected)<rank(simplex[0]):
                expanded=candidate([a+options['expansion']*options['reflection']*(a-b) for a,b in zip(centroid,worst)])
                simplex[-1]=expanded if rank(expanded)<rank(reflected) else reflected
            elif rank(reflected)<rank(simplex[-2]):simplex[-1]=reflected
            else:
                outside=rank(reflected)<rank(simplex[-1])
                target=reflected[0] if outside else worst
                contracted=candidate([a+options['contraction']*(b-a) for a,b in zip(centroid,target)])
                if rank(contracted)<(rank(reflected) if outside else rank(simplex[-1])):simplex[-1]=contracted
                else:
                    anchor=simplex[0][0]
                    simplex=[simplex[0]]+[candidate([a+options['shrink']*(b-a) for a,b in zip(anchor,item[0])]) for item in simplex[1:]]
            if count==before and all(rank(item)==rank(simplex[0]) for item in simplex):break
    elif algorithm == 'gradient' and best is not None and active:
        # Projected descent in normalized axes, with finite differences and
        # backtracking. Nonsmooth criteria may stop without a useful direction.
        def merit(record):return float('inf') if record is None else record['score']+1e-9*record['metrics']['iae']
        for iteration in range(options['max_iterations']):
            if count>=budget:break
            origin=best; gradients=[]
            for i in active:
                lo,hi=intervals[i];width=hi-lo;epsilon=width*options['difference_step']
                left=list(origin['values']);right=list(origin['values'])
                left[i]=max(lo,left[i]-epsilon);right[i]=min(hi,right[i]+epsilon)
                a,b=evaluate(left),evaluate(right)
                denominator=(right[i]-left[i])/width
                gradients.append((merit(b)-merit(a))/denominator if denominator and a is not None and b is not None else 0.)
            magnitude=math.sqrt(sum(v*v for v in gradients))
            if not math.isfinite(magnitude) or magnitude<1e-12:break
            improved=False;step=options['initial_step']
            for attempt in range(options['backtracks']):
                if step<options['tolerance']:break
                values=list(origin['values'])
                for i,g in zip(active,gradients):
                    lo,hi=intervals[i];values[i]=min(hi,max(lo,values[i]-step*g/magnitude*(hi-lo)))
                trial=evaluate(values)
                if trial is not None and trial['rank']<origin['rank']:
                    improved=True;break
                step*=options['shrink']
                if count>=budget:break
            if not improved:
                if best['rank']<origin['rank']:continue
                break
    if best is None:
        raise BlockError('Не найден допустимый расчёт: '+(last_error or 'проверьте схему'))
    return {
        'objective': objective, 'algorithm': algorithm, 'algorithm_options':options, 'source_ids': source_ids, 'trace':trace,
        'coefficients': {f'k{i+1}': v for i, v in enumerate(best['values'])},
        'baseline': baseline['metrics'] if baseline else None,
        'metrics': best['metrics'], 'baseline_score': baseline['score'] if baseline else None,
        'score': best['score'], 'evaluations': count, 'failed_evaluations': failures,
        'converged': best['metrics']['settled'],
        'series': {'t': [t for t, y in best['series']], 'y': [y for t, y in best['series']]},
    }


def simulate_with_optimizers(model, build_model, t_end, h, method):
    """Run orchestration: tune connected generic blocks, then simulate once.

    Candidate Engine runs only read parameter outputs and cannot start tuning.
    This function alone orchestrates the search; connections identify objectives.
    """
    from .subsystem import expand_subsystems
    prepared=copy.deepcopy(model)
    flat=expand_subsystems(prepared)
    optimizers=[b for b in flat.get('blocks',[]) if b.get('type')=='optimizer']
    reports=[]
    def original_block(scoped_id):
        parts=scoped_id.split('/')
        nodes=prepared.get('blocks',[])
        for index,part in enumerate(parts):
            block=next((b for b in nodes if str(b['id'])==part),None)
            if block is None:raise BlockError('Не удалось найти исходный блок '+scoped_id)
            if index<len(parts)-1:nodes=block.get('internal',{}).get('blocks',[])
        return block
    from .optimization_blocks import Optimizer, Objective
    for block in optimizers:
        defaults=dict(Optimizer.parameters);defaults.update(block.get('params',{}))
        if not defaults['enabled']:continue
        bid=str(block['id'])
        wires=[c for c in flat.get('connections',[]) if str(c['to'])==bid and int(c.get('to_port',0))==0]
        if len(wires)!=1:raise BlockError(f'{bid}: соедините выход Целевой функции со входом J')
        objective_id=str(wires[0]['from'])
        objective=next((b for b in flat['blocks'] if str(b['id'])==objective_id),None)
        if objective is None or objective.get('type')!='objective' or int(wires[0].get('from_port',0))!=0:
            raise BlockError(f'{bid}: вход J должен получать выход блока Целевая функция')
        goal=dict(Objective.parameters);goal.update(objective.get('params',{}))
        intervals=[]
        for i in range(1,4):
            current=finite(defaults[f'p{i}'],f'p{i}')
            intervals.append([defaults[f'min_p{i}'],defaults[f'max_p{i}']] if defaults[f'optimize_p{i}'] else [current,current])
        settings=dict(objective=goal['objective'],target=goal['target'],tolerance=goal['tolerance'],
                      bounds=intervals,algorithm=defaults['algorithm'],algorithm_options=defaults['algorithm_options'],max_evaluations=defaults['max_evaluations'],t_end=t_end,h=h,method=method)
        report=optimize(flat,build_model,settings,binding=dict(parameters=[(bid,f'p{i}') for i in range(1,4)],objective_id=objective_id))
        params=original_block(bid).setdefault('params',{})
        values={f'p{i}':report['coefficients'][f'k{i}'] for i in range(1,4)}
        params.update(values)
        reports.append(dict(block_id=bid,objective_id=objective_id,algorithm=defaults['algorithm'],values=values,
                            metrics=report['metrics'],baseline=report['baseline'],evaluations=report['evaluations'],
                            failed_evaluations=report['failed_evaluations'],converged=report['converged']))
        flat=expand_subsystems(prepared)
    executable=build_model(prepared)
    results=Engine(executable,t_end,h,method).run()
    # The final objective output is the whole-run score, consistently including
    # the finite-horizon feasibility rule used by the search.
    for bid,b in executable.blocks.items():
        if b.name=='objective' and b.state and b.state.get('history'):
            series=b.state['history'];metrics=response_metrics(series,b.params['target'],b.params['tolerance'])
            horizon=series[-1][0]-series[0][0]
            scale=abs(float(b.params['target'])-series[0][1]) or max(abs(float(b.params['target'])),1.)
            value=metrics[b.params['objective']] if b.params['objective'] in ('iae','ise') else objective_score(metrics,b.params['objective'],horizon,scale)
            results[bid][-1]=(series[-1][0],value)
    from .workspace_blocks import collect_plots
    collect_plots(executable,results)
    return results,reports
