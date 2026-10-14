"""Calculation blocks inspired by the SimOpt library, using the global solver.

No optimizer or UI code from SimOpt is used. Memory is committed by Engine once
per output step; compute never mutates it during RK4 trial evaluations.
"""
import bisect
import json
import math
import random

from .core import Block


def number(p, key):
    value = float(p[key])
    if not math.isfinite(value):
        raise ValueError(f'{key} must be finite')
    return value


def positive(p, key):
    value = number(p, key)
    if value <= 0:
        raise ValueError(f'{key} must be positive')
    return value


def coefficients(text):
    values = json.loads(text) if str(text).strip().startswith('[') else str(text).split(',')
    values = [float(v) for v in values]
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError('Use a nonempty comma-separated list of finite numbers')
    return values


def polynomial(values, t):
    result = 0.0
    for v in values:
        result = result * t + v
    return result


def square(t, x, p):
    period = positive(p, 'period')
    width = number(p, 'width')
    if not 0 <= width <= period:
        raise ValueError('width must be between 0 and period')
    return number(p, 'low') if t < number(p, 'delay') else (
        number(p, 'high') if (t-number(p, 'delay')) % period < width else number(p, 'low'))


def saw(t, x, p):
    period = positive(p, 'period')
    low, high = number(p, 'low'), number(p, 'high')
    phase = (t-number(p, 'delay')) / period
    f = 0 if phase < 0 else phase - math.floor(phase)
    return high + (low-high)*f if number(p, 'reverse') else low + (high-low)*f


def piecewise(t, x, p):
    times, values = coefficients(p['times']), coefficients(p['values'])
    if len(times) != len(values) or any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError('times and values must have equal lengths; times must increase')
    index = bisect.bisect_right(times, t)-1
    if index < 0:
        return values[0]
    if index == len(times)-1 or p['mode'] == 'hold':
        return values[index]
    if p['mode'] != 'linear':
        raise ValueError('mode must be hold or linear')
    f = (t-times[index])/(times[index+1]-times[index])
    return values[index]+f*(values[index+1]-values[index])


def dead_zone(t, x, p):
    low, high = number(p, 'lower'), number(p, 'upper')
    if low > high:
        raise ValueError('lower must not exceed upper')
    return x[0]-high if x[0] > high else (x[0]-low if x[0] < low else 0.0)


def divide(t, x, p):
    if x[1] == 0:
        raise ValueError('division by zero')
    return x[0]/x[1]


def compare(t, x, p):
    operations = {'>': lambda: x[0] > x[1], '<': lambda: x[0] < x[1],
                  '>=': lambda: x[0] >= x[1], '<=': lambda: x[0] <= x[1],
                  '==': lambda: x[0] == x[1], '!=': lambda: x[0] != x[1]}
    if p['operation'] not in operations:
        raise ValueError('operation must be >, <, >=, <=, == or !=')
    return float(operations[p['operation']]())


def logic(t, x, p):
    a, b = bool(x[0]), bool(x[1])
    if p['operation'] == 'and': return float(a and b)
    if p['operation'] == 'or': return float(a or b)
    if p['operation'] == 'xor': return float(a != b)
    raise ValueError('operation must be and, or or xor')


# category, visible name, inputs, parameters, pure calculation
SIMPLE = {
    'model_time': ('Sources', 'Модельное время', 0, {}, lambda t,x,p: t),
    'step': ('Sources', 'Ступенька', 0, {'before':0., 'after':1., 'time':0.},
             lambda t,x,p: number(p, 'before' if t < number(p,'time') else 'after')),
    'sine': ('Sources', 'Синусоида', 0, {'amplitude':1., 'omega':1., 'phase':0., 'offset':0.},
             lambda t,x,p: number(p,'amplitude')*math.sin(number(p,'omega')*t+number(p,'phase'))+number(p,'offset')),
    'square_wave': ('Sources', 'Прямоугольный сигнал', 0,
                    {'low':0., 'high':1., 'period':2., 'width':1., 'delay':0.}, square),
    'sawtooth': ('Sources', 'Пилообразный сигнал', 0,
                 {'low':0., 'high':1., 'period':2., 'delay':0., 'reverse':0.}, saw),
    'exponential': ('Sources', 'Экспонента', 0, {'amplitude':1., 'rate':1., 'shift':0.},
                    lambda t,x,p: number(p,'amplitude')*math.exp(number(p,'rate')*t+number(p,'shift'))),
    'polynomial': ('Sources', 'Полином', 0, {'coefficients':'1,0'},
                   lambda t,x,p: polynomial(coefficients(p['coefficients']),t)),
    'piecewise': ('Sources', 'Кусочный сигнал', 0,
                  {'times':'0,1,2', 'values':'0,1,0', 'mode':'linear'}, piecewise),
    'subtract': ('Math', 'Вычитатель', 2, {}, lambda t,x,p: x[0]-x[1]),
    'divide': ('Math', 'Делитель', 2, {}, divide),
    'absolute': ('Math', 'Модуль', 1, {}, lambda t,x,p: abs(x[0])),
    'sign': ('Math', 'Знак', 1, {}, lambda t,x,p: float((x[0]>0)-(x[0]<0))),
    'weighted_sum': ('Math', 'Сумматор с весами', 2, {'w1':1., 'w2':1.},
                     lambda t,x,p: number(p,'w1')*x[0]+number(p,'w2')*x[1]),
    'dead_zone': ('Nonlinear', 'Зона нечувствительности', 1, {'lower':-.5,'upper':.5}, dead_zone),
    'quantizer': ('Nonlinear', 'Квантователь', 1, {'level':.5},
                  lambda t,x,p: math.copysign(math.floor(abs(x[0])/positive(p,'level')+.5)*positive(p,'level'),x[0])),
    'comparison': ('Logic', 'Сравнение', 2, {'operation':'>'}, compare),
    'logical_not': ('Logic', 'Отрицание', 1, {}, lambda t,x,p: float(not x[0])),
    'logical_operation': ('Logic', 'Логическая операция', 2, {'operation':'and'}, logic),
    'manual_gate': ('Switches', 'Ключ', 1, {'closed':1.}, lambda t,x,p: x[0] if number(p,'closed') else 0.),
    'manual_switch': ('Switches', 'Переключатель', 2, {'selected':1.},
                      lambda t,x,p: x[0] if number(p,'selected') == 1 else x[1]),
    'controlled_switch': ('Switches', 'Управляемый ключ', 3, {'threshold':.5},
                          lambda t,x,p: x[1] if x[2] >= number(p,'threshold') else x[0]),
    'splitter': ('Math', 'Разветвитель', 1, {}, lambda t,x,p: x[0]),
}


def make_simple(name):
    category, label, inputs, params, calculate = SIMPLE[name]
    port_labels = {
        'subtract': (['a','b'],['a−b']),
        'divide': (['числ.','знам.'],['a/b']),
        'weighted_sum': (['a','b'],['Σ']),
        'comparison': (['a','b'],['0/1']),
        'logical_not': (['A'],['¬A']),
        'logical_operation': (['A','B'],['0/1']),
        'manual_gate': (['u'],['y']),
        'manual_switch': (['u1','u2'],['y']),
        'controlled_switch': (['u1','u2','ctrl'],['y']),
        'splitter': (['u'],['u','u']),
        'model_time': ([],['t']),
    }
    ins, outs = port_labels.get(name, (['u'] if inputs else [], ['y']))
    def compute(self, t, inputs, params, state):
        return float(calculate(t, inputs, params))
    return type(''.join(p.title() for p in name.split('_')), (Block,), {
        'name':name, 'display_name':label, 'n_inputs':inputs,
        'n_outputs':2 if name == 'splitter' else 1,
        'input_labels':ins, 'output_labels':outs,
        'parameters':params, 'description':label, 'compute':compute,
    })


class PID(Block):
    name = 'pid'
    display_name = 'ПИД регулятор'
    n_inputs = 4
    input_labels = ['e','k1','k2','k3']
    output_labels = ['u']
    required_inputs = (0,1,2,3)
    state_kind = 'integrated'
    direct_feedthrough = True
    parameters = {'filter_tau':.05, 'initial_integral':0., 'initial_filter':0.}
    description = 'u=k1*e+k2*integral(e)+k3*filtered_derivative(e). Coefficients are signal inputs.'

    def prepare(self, h):
        positive(self.params, 'filter_tau')

    def state_size(self, p): return 2

    def initial_state(self, p):
        return [number(p,'initial_integral'),number(p,'initial_filter')]

    def compute(self, t, x, p, s):
        return x[1]*x[0]+x[2]*s[0]+x[3]*(x[0]-s[1])/positive(p,'filter_tau')

    def derivative(self, t, x, p, s):
        return [x[0],(x[0]-s[1])/positive(p,'filter_tau')]


class PI(PID):
    name = 'pi'
    display_name = 'ПИ регулятор'
    n_inputs = 3
    input_labels = ['e','k1','k2']
    required_inputs = (0,1,2)
    parameters = {'initial_integral':0.}
    description = 'u=k1*e+k2*integral(e). Coefficients are signal inputs.'
    def prepare(self,h): pass
    def state_size(self,p): return 1
    def initial_state(self,p): return [number(p,'initial_integral')]
    def compute(self,t,x,p,s): return x[1]*x[0]+x[2]*s[0]
    def derivative(self,t,x,p,s): return [x[0]]


class PD(PID):
    name = 'pd'
    display_name = 'ПД регулятор'
    n_inputs = 3
    input_labels = ['e','k1','k3']
    required_inputs = (0,1,2)
    parameters = {'filter_tau':.05,'initial_filter':0.}
    description = 'u=k1*e+k3*filtered_derivative(e). Coefficients are signal inputs.'
    def state_size(self,p): return 1
    def initial_state(self,p): return [number(p,'initial_filter')]
    def compute(self,t,x,p,s): return x[1]*x[0]+x[2]*(x[0]-s[0])/positive(p,'filter_tau')
    def derivative(self,t,x,p,s): return [(x[0]-s[0])/positive(p,'filter_tau')]


class FilteredDerivative(Block):
    name = 'filtered_derivative'
    display_name = 'Реальный дифференциатор'
    state_kind = 'integrated'
    direct_feedthrough = True
    parameters = {'gain':1.,'tau':1.,'initial_filter':0.}
    description = 'Transfer function gain*s/(tau*s+1).'
    def prepare(self,h): positive(self.params,'tau')
    def state_size(self,p): return 1
    def initial_state(self,p): return [number(p,'initial_filter')]
    def compute(self,t,x,p,s): return number(p,'gain')*(x[0]-s[0])/positive(p,'tau')
    def derivative(self,t,x,p,s): return [(x[0]-s[0])/positive(p,'tau')]


class RealIntegrator(Block):
    name = 'real_integrator'
    display_name = 'Реальный интегратор'
    state_kind = 'integrated'
    parameters = {'gain':1.,'tau':1.,'initial_value':0.,'initial_rate':0.}
    description = 'Transfer function gain/(s*(tau*s+1)).'
    def prepare(self,h): positive(self.params,'tau')
    def state_size(self,p): return 2
    def initial_state(self,p): return [number(p,'initial_value'),number(p,'initial_rate')]
    def compute(self,t,x,p,s): return s[0]
    def derivative(self,t,x,p,s): return [s[1],(number(p,'gain')*x[0]-s[1])/positive(p,'tau')]


class TransferFunction(Block):
    name = 'transfer_function'
    display_name = 'Передаточная функция'
    state_kind = 'integrated'
    parameters = {'numerator':'1','denominator':'1,1','initial_state':'0'}
    description = 'Proper rational transfer function; coefficients in descending powers of s.'

    def prepare(self,h):
        a,b = coefficients(self.params['denominator']),coefficients(self.params['numerator'])
        while len(b)>1 and b[0] == 0: b.pop(0)
        if a[0] == 0 or len(b)>len(a):
            raise ValueError('denominator must be nonzero and numerator degree must not exceed it')
        self.a = [v/a[0] for v in reversed(a[1:])]
        normalized = [v/a[0] for v in b]
        normalized = [0.]*(len(a)-len(normalized))+normalized
        self.d = normalized[0]
        self.c = [v-self.d*self.a[i] for i,v in enumerate(reversed(normalized[1:]))]
        self.direct_feedthrough = self.d != 0

    def state_size(self,p): return len(coefficients(p['denominator']))-1
    def initial_state(self,p):
        n=self.state_size(p); values=coefficients(p['initial_state'])
        if values == [0.]: return [0.]*n
        if len(values)!=n: raise ValueError(f'initial_state must contain {n} values')
        return values
    def compute(self,t,x,p,s):
        return self.d*x[0]+sum(c*v for c,v in zip(self.c,s))
    def derivative(self,t,x,p,s):
        return s[1:]+[x[0]-sum(a*v for a,v in zip(self.a,s))] if s else []


class TransportDelay(Block):
    name = 'transport_delay'
    display_name = 'Чистое запаздывание'
    state_kind = 'memory'
    parameters = {'tau':1.,'initial_value':0.}
    description = 'y(t)=u(t-tau); linear interpolation between samples, initial_value before t=0.'
    def prepare(self,h):
        tau=number(self.params,'tau')
        if tau<0: raise ValueError('tau must be non-negative')
        self.direct_feedthrough = tau < h
    def initial_state(self,p): return []
    def compute(self,t,x,p,s):
        tau=number(p,'tau');target=t-tau
        if tau == 0: return x[0]
        if target < -1e-12 or not s: return number(p,'initial_value')
        target=max(0.,target)
        i=bisect.bisect_right(s,(target,math.inf))
        if i == 0: return s[0][1]
        left=s[i-1]
        right=s[i] if i<len(s) else (t,x[0])
        if abs(target-left[0])<1e-12 or right[0]<=left[0]: return left[1]
        if target>right[0]+1e-12: raise ValueError('delay history does not bracket requested time')
        f=(target-left[0])/(right[0]-left[0])
        return left[1]+f*(right[1]-left[1])
    def update_memory(self,t,x,p,s):
        cutoff=t-number(p,'tau')-self.step_size
        i=max(0,bisect.bisect_right(s,(cutoff,math.inf))-1)
        return s[i:]+[(t,float(x[0]))]


class Derivative(Block):
    name = 'derivative'
    display_name = 'Дифференциатор'
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {'gain':1.}
    description = 'Backward difference at output steps; derivative is zero at the initial sample.'
    def initial_state(self,p): return None
    def compute(self,t,x,p,s):
        if s is None: return 0.
        old_t, old_x, old_d = s
        dt=t-old_t
        return old_d if dt<=1e-12 else number(p,'gain')*(x[0]-old_x)/dt
    def update_memory(self,t,x,p,s): return (t,x[0],self.compute(t,x,p,s))


class Relay(Block):
    name = 'relay'
    display_name = 'Реле с гистерезисом'
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {'lower':-.5,'upper':.5,'low':0.,'high':1.,'initial_value':0.}
    description = 'Switches high at upper and low at lower; holds output between thresholds.'
    def prepare(self,h):
        if number(self.params,'lower') >= number(self.params,'upper'):
            raise ValueError('lower must be less than upper')
    def initial_state(self,p): return number(p,'initial_value')
    def compute(self,t,x,p,s):
        if x[0]>=number(p,'upper'): return number(p,'high')
        if x[0]<=number(p,'lower'): return number(p,'low')
        return s
    def update_memory(self,t,x,p,s): return self.compute(t,x,p,s)


class RateLimiter(Block):
    name = 'rate_limiter'
    display_name = 'Ограничитель производной'
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {'fall_rate':-1.,'rise_rate':1.,'initial_value':0.}
    description = 'Limits sampled output slope; initial output is initial_value.'
    def prepare(self,h):
        if number(self.params,'fall_rate')>0 or number(self.params,'rise_rate')<0:
            raise ValueError('fall_rate must be <=0 and rise_rate >=0')
    def initial_state(self,p): return (0.,number(p,'initial_value'))
    def compute(self,t,x,p,s):
        dt=max(0.,t-s[0]);low=s[1]+number(p,'fall_rate')*dt;high=s[1]+number(p,'rise_rate')*dt
        return max(low,min(high,x[0]))
    def update_memory(self,t,x,p,s): return (t,self.compute(t,x,p,s))


class RunningMinimum(Block):
    name = 'running_minimum'
    display_name = 'Минимальное значение'
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {}
    description = 'Minimum of all samples since simulation start.'
    def initial_state(self,p): return None
    def compute(self,t,x,p,s): return x[0] if s is None else min(s,x[0])
    def update_memory(self,t,x,p,s): return self.compute(t,x,p,s)


class RunningMaximum(RunningMinimum):
    name = 'running_maximum'
    display_name = 'Максимальное значение'
    description = 'Maximum of all samples since simulation start.'
    def compute(self,t,x,p,s): return x[0] if s is None else max(s,x[0])


class TimeAverage(Block):
    name = 'time_average'
    display_name = 'Среднее по времени'
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {}
    description = 'Trapezoidal time average of samples; first sample returns the input.'
    def initial_state(self,p): return None
    def _area(self,t,x,s): return s[2]+(t-s[0])*(x[0]+s[1])*.5
    def compute(self,t,x,p,s): return x[0] if s is None or t == 0 else self._area(t,x,s)/t
    def update_memory(self,t,x,p,s):
        return (t,x[0],0. if s is None else self._area(t,x,s))


class Counter(Block):
    name = 'counter'
    display_name = 'Счётчик'
    n_inputs = 2
    input_labels = ['+1','−1']
    output_labels = ['n']
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {'threshold':.5,'initial_count':0.}
    description = 'Counts rising crossings on up minus rising crossings on down; t=0 initializes inputs.'
    def initial_state(self,p): return (None,None,number(p,'initial_count'))
    def compute(self,t,x,p,s):
        if s[0] is None: return s[2]
        level=number(p,'threshold')
        return s[2]+float(s[0]<level<=x[0])-float(s[1]<level<=x[1])
    def update_memory(self,t,x,p,s): return (x[0],x[1],self.compute(t,x,p,s))


class Trigger(Block):
    name = 'sr_trigger'
    display_name = 'Триггер'
    n_inputs = 2
    input_labels = ['S','R']
    output_labels = ['Q']
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {'initial_value':0.}
    description = 'Set/reset latch; reset takes priority when both inputs are active.'
    def initial_state(self,p): return float(bool(number(p,'initial_value')))
    def compute(self,t,x,p,s): return 0. if x[1] else (1. if x[0] else s)
    def update_memory(self,t,x,p,s): return self.compute(t,x,p,s)


class SampleHold(Block):
    name = 'sample_hold'
    display_name = 'Экстраполятор 0-го порядка'
    state_kind = 'memory'
    direct_feedthrough = True
    parameters = {'period':1.}
    description = 'Samples at multiples of period and holds between samples; period must be a multiple of h.'
    def prepare(self,h):
        n=positive(self.params,'period')/h
        if n<1 or not math.isclose(n,round(n),abs_tol=1e-8,rel_tol=0):
            raise ValueError('period must be an integer multiple of simulation step h')
    def initial_state(self,p): return None
    def _sample(self,t,p):
        n=t/positive(p,'period')
        return math.isclose(n,round(n),abs_tol=1e-8,rel_tol=0)
    def compute(self,t,x,p,s): return x[0] if s is None or self._sample(t,p) else s[1]
    def update_memory(self,t,x,p,s): return (t,x[0],0.) if s is None or self._sample(t,p) else s


class LinearExtrapolator(SampleHold):
    name = 'linear_extrapolator'
    display_name = 'Экстраполятор 1-го порядка'
    description = 'Samples at multiples of period and extrapolates using the last two samples.'
    def compute(self,t,x,p,s):
        return x[0] if s is None or self._sample(t,p) else s[1]+s[2]*(t-s[0])
    def update_memory(self,t,x,p,s):
        if s is None: return (t,x[0],0.)
        if self._sample(t,p) and t>s[0]: return (t,x[0],(x[0]-s[1])/(t-s[0]))
        return s


class UniformNoise(Block):
    name = 'uniform_noise'
    display_name = 'Равномерный шум'
    n_inputs = 0
    parameters = {'lower':0.,'upper':1.,'seed':1.}
    description = 'Seeded, reproducible noise held for each simulation step.'
    def compute(self,t,x,p,s):
        low,high=number(p,'lower'),number(p,'upper')
        if low>high: raise ValueError('lower must not exceed upper')
        sample=int(math.floor(t/self.step_size+1e-9))
        return random.Random(int(number(p,'seed'))+sample).uniform(low,high)


class NormalNoise(UniformNoise):
    name = 'normal_noise'
    display_name = 'Нормальный шум'
    parameters = {'mean':0.,'sigma':1.,'seed':1.}
    description = 'Seeded, reproducible Gaussian noise held for each simulation step.'
    def compute(self,t,x,p,s):
        sigma=number(p,'sigma')
        if sigma<0: raise ValueError('sigma must be non-negative')
        sample=int(math.floor(t/self.step_size+1e-9))
        return random.Random(int(number(p,'seed'))+sample).gauss(number(p,'mean'),sigma)
