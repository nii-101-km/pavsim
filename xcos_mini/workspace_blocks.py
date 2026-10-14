"""Experiment boundaries and recording-only plot blocks."""
import math
from .core import Block, BlockError

class Experiment(Block):
    name='experiment';display_name='Эксперимент'
    n_inputs=3;n_outputs=1;input_labels=['p1','p2','p3'];output_labels=['J']
    state_kind='memory';direct_feedthrough=False
    parameters={'t_end':10.,'h':.02,'method':'rk4'}
    parameter_labels={'t_end':'Время одного прогона','h':'Шаг','method':'Метод'}
    parameter_choices={'method':[{'value':'rk4','label':'RK4'},{'value':'euler','label':'Euler'}]}
    description='Independent fresh-state experiment; returns J only after completion.'
    def initial_state(self,p):return None
    def compute(self,t,x,p,s):
        if '_result' not in p:raise BlockError('Эксперимент запускается планировщиком рабочего поля')
        return float(p['_result'])
    def update_memory(self,t,x,p,s):return None

def axis_range(text, label):
    if not isinstance(text,str):raise BlockError(label+': требуется строка минимум:максимум')
    if not text.strip():return None
    try:
        if text.count(':')!=1:raise ValueError()
        lo,hi=(float(v.strip().replace(',','.')) for v in text.split(':'))
        if not all(math.isfinite(v) for v in (lo,hi,hi-lo)) or hi<=lo:raise ValueError()
    except ValueError:
        raise BlockError(label+': задайте минимум:максимум, например 0:5; максимум должен быть больше минимума')
    return [lo,hi]

class Plot(Block):
    n_outputs=0;state_kind='memory';direct_feedthrough=True
    def prepare(self,h):
        if self.plot_kind in ('xy','xy_score'):
            axis_range(self.params['x_range'],'Диапазон X')
            axis_range(self.params['y_range'],'Диапазон Y')
    def initial_state(self,p):return []
    def compute(self,t,x,p,s):return float(x[0])
    def update_memory(self,t,x,p,s):
        s.append((t,tuple(float(v) for v in x)));return s

def make_plot(name,label,n,labels,kind):
    params={'label':label}
    if kind in ('xy','xy_score'):params.update(x_range='',y_range='')
    return type(name,(Plot,),dict(name=name,display_name=label,n_inputs=n,input_labels=labels,output_labels=[],plot_kind=kind,
        parameters=params,parameter_choices={},parameter_labels={'label':'Название','x_range':'Диапазон X (минимум:максимум)','y_range':'Диапазон Y (минимум:максимум)'},
        required_inputs=(0,1) if kind in ('xy','xy_score') else tuple(range(n)), description='Recorded scalar inputs plotted as '+kind))

def collect_plots(executable,results):
    for bid,block in executable.blocks.items():
        if isinstance(block,Plot):results[bid]=list(block.state)
