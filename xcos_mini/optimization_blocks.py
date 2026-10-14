"""Signal-connected optimizer and objective blocks, with scalar ports."""
from .core import Block, BlockError
from .optimization import finite, OBJECTIVES, objective_score, algorithm_options, ALGORITHM_DEFAULTS

class Optimizer(Block):
    name='optimizer'
    display_name='Оптимизатор'
    n_inputs=1
    n_outputs=3
    input_labels=['J']
    output_labels=['p1','p2','p3']
    state_kind='memory'
    direct_feedthrough=False
    required_inputs=(0,)
    parameters={'algorithm':'coordinate','algorithm_options':'','enabled':True, 'p1':.2,'p2':.1,'p3':0.,
                'optimize_p1':True,'optimize_p2':True,'optimize_p3':False,
                'min_p1':0.,'max_p1':5.,'min_p2':0.,'max_p2':5.,'min_p3':0.,'max_p3':2.,
                'max_evaluations':100}
    parameter_choices={'algorithm':[{'value':key,'label':label} for key,label in [('coordinate','Покоординатный поиск'),('nelder_mead','Нелдер–Мид'),('gradient','Градиентный (численные производные)'),('hooke_jeeves','Хук–Дживс'),('heavy_ball','Тяжёлый шарик (Поляк)')]]}
    parameter_labels={'algorithm':'Алгоритм','algorithm_options':'Параметры алгоритма (через ;)','enabled':'Подбирать при Run','max_evaluations':'Максимум расчётов', **{key:label for i in range(1,4) for key,label in [(f'p{i}',f'p{i}: текущее значение'),(f'optimize_p{i}',f'Подбирать p{i}'),(f'min_p{i}',f'p{i}: минимум'),(f'max_p{i}',f'p{i}: максимум')]}}
    description='Three independent parameter outputs; Run performs bounded search using the connected objective J.'
    def prepare(self,h):
        if self.params['algorithm'] not in ALGORITHM_DEFAULTS:raise BlockError('Неизвестный алгоритм оптимизации')
        algorithm_options(self.params['algorithm'],self.params['algorithm_options'])
        for key in ('enabled','optimize_p1','optimize_p2','optimize_p3'):
            if not isinstance(self.params[key],bool):raise BlockError(key+': требуется галочка true/false')
    def initial_state(self,p):return None
    def compute(self,t,x,p,s):return [finite(p[f'p{i}'],f'p{i}') for i in range(1,4)]
    def update_memory(self,t,x,p,s):return None

class Objective(Block):
    name='objective'
    display_name='Целевая функция'
    n_inputs=1
    n_outputs=1
    input_labels=['y']
    output_labels=['J']
    required_inputs=(0,)
    state_kind='memory'
    direct_feedthrough=True
    parameters={'objective':'iae','target':1.,'tolerance':.02}
    parameter_labels={'objective':'Целевая функция','target':'Уставка','tolerance':'Допуск (0.02 = 2%)'}
    parameter_choices={'objective':[{'value':key,'label':label} for key,label in [('iae','IAE — интеграл |ошибки|'),('ise','ISE — интеграл ошибки²'),('settling_time','Время регулирования'),('overshoot','Перерегулирование'),('oscillation','Колебательность')]]}
    description='Evaluate response against a constant target; objective J feeds the optimizer.'
    def prepare(self,h):
        finite(self.params['target'],'Уставка')
        tolerance=finite(self.params['tolerance'],'Допуск')
        if not 0<tolerance<=.2:raise BlockError('Допуск должен быть больше 0 и не больше 20%')
        if self.params['objective'] not in OBJECTIVES:raise BlockError('Неизвестная целевая функция')
    def initial_state(self,p):return None
    def _sample(self,t,y,p,s):
        target=finite(p['target'],'Уставка');y=finite(y,'Выход')
        if s is None:
            scale=abs(target-y) or max(abs(target),1.)
            s=dict(start=t,y0=y,scale=scale,direction=1 if target>=y else -1,
                   t=t,y=y,iae=0.,ise=0.,variation=0.,overshoot=0.,inside=None,tail_error=0.)
        else:s=dict(s)
        dt=t-s['t']
        if dt< -1e-12:raise BlockError('Время целевой функции должно возрастать')
        dt=max(0.,dt);error=target-y;previous=target-s['y']
        s['iae']+=dt*(abs(previous)+abs(error))/2
        s['ise']+=dt*(previous*previous+error*error)/2
        s['variation']+=abs(y-s['y'])
        s['overshoot']=max(s['overshoot'],s['direction']*(y-target)/s['scale']*100)
        if abs(error)<=float(p['tolerance'])*s['scale']:
            if s['inside'] is None:s['inside']=t
        else:s['inside']=None
        s['t']=t;s['y']=y
        horizon=t-s['start']
        settled=(horizon>0 and s['inside'] is not None and t-s['inside']>=.1*horizon-1e-12)
        # Tracking penalty for incomplete transients; exact tail statistics for
        # reporting are calculated once from committed samples at run completion.
        s['metrics']=dict(settling_time=s['inside']-s['start'] if settled else None,
            overshoot=max(0.,s['overshoot']),oscillation=max(0.,s['variation']-abs(y-s['y0']))/(2*s['scale']),
            iae=s['iae'],ise=s['ise'],final_error=abs(error),tail_error=abs(error)/s['scale'],settled=settled)
        return s
    def compute(self,t,x,p,s):
        sample=self._sample(t,x[0],p,s)
        horizon=t-sample['start']
        if horizon<=0:return 0.
        if p['objective'] in ('iae','ise'):return sample['metrics'][p['objective']]
        return objective_score(sample['metrics'],p['objective'],horizon,sample['scale'])
    def update_memory(self,t,x,p,s):
        sample=self._sample(t,x[0],p,s)
        history=[] if s is None else s['history']
        history.append((t,float(x[0])))
        sample['history']=history
        return sample
