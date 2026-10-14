"""Behavioral checks through production model construction and the global Engine."""
import math
import os
import unittest
from xcos_mini.core import Library, Engine, BlockError, AlgebraicLoopError
from xcos_mini.server import _build_model

ROOT=os.path.dirname(os.path.dirname(__file__))

def b(id,kind,params=None):return {'id':id,'type':kind,'params':params or {}}
def c(src,dst,port=0,source_port=0):return {'from':src,'from_port':source_port,'to':dst,'to_port':port}

class SimOptBlocksTests(unittest.TestCase):
    def setUp(self):self.lib=Library(os.path.join(ROOT,'blocks'))
    def run_model(self,blocks,connections,end=1.,h=.01,method='rk4'):
        self.model=_build_model(self.lib,{'blocks':blocks,'connections':connections})
        return Engine(self.model,t_end=end,h=h,method=method).run()
    def chain(self,kind,params=None,source='constant',source_params=None,end=1.,h=.01,method='rk4'):
        result=self.run_model([b('src',source,source_params or {'value':1}),b('block',kind,params),b('graph','graph_display')],
                              [c('src','block'),c('block','graph')],end,h,method)
        return result['graph']
    def assert_series(self,series,expected,tolerance=1e-8):
        self.assertTrue(series)
        for t,y in series:self.assertAlmostEqual(y,expected(t),delta=tolerance,msg=f't={t}')

    def test_all_blocks_load_and_compute_default_models(self):
        self.assertFalse(self.lib.load_errors)
        new={'model_time','step','sine','square_wave','sawtooth','exponential','polynomial','piecewise',
             'subtract','divide','absolute','sign','weighted_sum','dead_zone','quantizer','comparison',
             'logical_not','logical_operation','manual_gate','manual_switch','controlled_switch','splitter',
             'pid','pi','pd','filtered_derivative','real_integrator','transfer_function','transport_delay',
             'derivative','relay','rate_limiter','running_minimum','running_maximum','time_average','counter',
             'sr_trigger','sample_hold','linear_extrapolator','uniform_noise','normal_noise'}
        for name in new:
            with self.subTest(name=name):
                cls=self.lib.get(name);blocks=[b('target',name)];wires=[]
                for i in range(cls.n_inputs):
                    id='u'+str(i);blocks.append(b(id,'constant',{'value':1}));wires.append(c(id,'target',i))
                result=self.run_model(blocks,wires,end=.1,h=.01)['target']
                self.assertEqual(len(result),11)
                self.assertTrue(all(math.isfinite(v) for t,v in result))

    def test_pure_arithmetic_and_logic(self):
        cases=[('subtract',{},5,2,3),('divide',{},5,2,2.5),('weighted_sum',{'w1':2,'w2':-3},5,2,4),
               ('comparison',{'operation':'<'},5,2,0),('logical_operation',{'operation':'xor'},1,1,0),
               ('manual_switch',{'selected':2},5,2,2)]
        for kind,params,a,z,want in cases:
            r=self.run_model([b('a','constant',{'value':a}),b('z','constant',{'value':z}),b('op',kind,params)],
                             [c('a','op'),c('z','op',1)])
            self.assert_series(r['op'],lambda t:want)
        for kind,u,want in [('absolute',-3,3),('sign',-3,-1),('logical_not',0,1),
                            ('dead_zone',2,1.5),('quantizer',-.8,-1)]:
            self.assert_series(self.chain(kind,source_params={'value':u}),lambda t:want)

    def test_sources_against_formula(self):
        for kind,params,expected in [
            ('model_time',{},lambda t:t),('step',{'time':.3,'before':-1,'after':2},lambda t:-1 if t<.3 else 2),
            ('sine',{'amplitude':2,'omega':3,'phase':.4,'offset':1},lambda t:2*math.sin(3*t+.4)+1),
            ('polynomial',{'coefficients':'2,3,4'},lambda t:2*t*t+3*t+4),
            ('exponential',{'amplitude':2,'rate':-.5,'shift':0},lambda t:2*math.exp(-.5*t)),
            ('sawtooth',{'low':-1,'high':1,'period':1},lambda t:-1+2*(t%1)),
            ('piecewise',{'times':'0,.5,1','values':'0,2,0'},lambda t:4*t if t<=.5 else 4*(1-t)),
            ('square_wave',{'low':-1,'high':2,'period':1,'width':.25},lambda t:2 if t%1<.25 else -1)]:
            with self.subTest(kind=kind):
                r=self.run_model([b('src',kind,params)],[])
                self.assert_series(r['src'],expected)

    def test_pid_four_inputs_closed_form_rk4_and_euler(self):
        h=.002; tau=.05; ratio=h/tau
        for method in ['rk4','euler']:
            factor=1-ratio if method=='euler' else 1-ratio+ratio**2/2-ratio**3/6+ratio**4/24
            blocks=[b('e','constant',{'value':1}),b('kp','constant',{'value':2}),
                    b('ki','constant',{'value':3}),b('kd','constant',{'value':.4}),b('pid','pid',{'filter_tau':tau})]
            result=self.run_model(blocks,[c('e','pid',0),c('kp','pid',1),c('ki','pid',2),c('kd','pid',3)],h=h,method=method)['pid']
            self.assertEqual(len(result),501)
            self.assert_series(result,lambda t:2+3*t+.4/tau*factor**round(t/h),1e-10)

    def test_pid_matches_independent_flat_parallel_paths_with_changing_gains(self):
        sources=[b('e','sine',{'omega':2}),b('kp','step',{'time':.4,'before':1,'after':2}),
                 b('ki','constant',{'value':.3}),b('kd','constant',{'value':.2})]
        grouped=sources+[b('pid','pid',{'filter_tau':.2})]
        grouped_wires=[c('e','pid',0),c('kp','pid',1),c('ki','pid',2),c('kd','pid',3)]
        flat=sources+[b('integral','integrator'),b('diff','filtered_derivative',{'tau':.2}),
                      b('p','multiplication'),b('i','multiplication'),b('d','multiplication'),
                      b('pi','addition'),b('sum','addition')]
        wires=[c('e','integral'),c('e','diff'),c('e','p'),c('kp','p',1),c('integral','i'),c('ki','i',1),
               c('diff','d'),c('kd','d',1),c('p','pi'),c('i','pi',1),c('pi','sum'),c('d','sum',1)]
        for method in ['euler','rk4']:
            actual=self.run_model(grouped,grouped_wires,h=.005,method=method)['pid']
            expected=self.run_model(flat,wires,h=.005,method=method)['sum']
            self.assertEqual(len(actual),len(expected))
            for (ta,a),(tb,z) in zip(actual,expected):
                self.assertEqual(ta,tb);self.assertAlmostEqual(a,z,delta=1e-10)

    def test_pi_feedback_closed_form(self):
        blocks=[b('r','constant',{'value':1}),b('error','subtract'),b('k1','constant',{'value':1}),
                b('k2','constant',{'value':1}),b('pi','pi'),b('plant','first_order')]
        wires=[c('r','error'),c('plant','error',1),c('error','pi'),c('k1','pi',1),c('k2','pi',2),c('pi','plant')]
        result=self.run_model(blocks,wires,h=.005)['plant']
        self.assert_series(result,lambda t:1-math.exp(-t),1e-9)

    def test_pd_and_filtered_derivative_closed_form(self):
        self.assert_series(self.chain('filtered_derivative',{'gain':2,'tau':.5}),lambda t:4*math.exp(-2*t),2e-8)
        r=self.run_model([b('e','constant',{'value':1}),b('p','constant',{'value':2}),
                          b('d','constant',{'value':.5}),b('pd','pd',{'filter_tau':.5})],
                         [c('e','pd'),c('p','pd',1),c('d','pd',2)])['pd']
        self.assert_series(r,lambda t:2+math.exp(-2*t),1e-8)

    def test_delay_zero_short_fractional_and_integer_steps(self):
        for tau in [0,.005,.01,.025,.1,.2]:
            for method in ['rk4','euler']:
                with self.subTest(tau=tau,method=method):
                    series=self.chain('transport_delay',{'tau':tau},source='model_time',method=method)
                    self.assertEqual(len(series),101)
                    self.assert_series(series,lambda t:max(t-tau,0),1e-12)
        self.assert_series(self.chain('transport_delay',{'tau':0}),lambda t:1)
        self.assert_series(self.chain('transport_delay',{'tau':.005}),lambda t:0 if t==0 else 1)
        self.chain('transport_delay',{'tau':.1},source='model_time',end=3,h=.01)
        self.assertLessEqual(len(self.model.blocks['block'].state),15)

    def test_delay_pre_history_and_original_one_step_delay(self):
        self.assert_series(self.chain('transport_delay',{'tau':.05,'initial_value':-2}),lambda t:-2 if t<.05 else 1)
        self.assert_series(self.chain('delay'),lambda t:0 if t==0 else 1)

    def test_transfer_functions_with_and_without_feedthrough(self):
        cases=[({'numerator':'2','denominator':'1,1'},lambda t:2*(1-math.exp(-t))),
               ({'numerator':'1,0','denominator':'1,1'},lambda t:math.exp(-t)),
               ({'numerator':'1','denominator':'1,3,2'},lambda t:.5-math.exp(-t)+.5*math.exp(-2*t)),
               ({'numerator':'6','denominator':'2'},lambda t:3)]
        for params,expected in cases:
            self.assert_series(self.chain('transfer_function',params),expected,2e-8)
        self.assert_series(self.chain('real_integrator',{'gain':2,'tau':.5}),lambda t:2*(t-.5*(1-math.exp(-2*t))),2e-8)
        self.assert_series(self.chain('first_order',{'gain':2,'tau':.5}),lambda t:2*(1-math.exp(-2*t)),2e-8)
        self.assert_series(self.chain('integrator',{'gain':3}),lambda t:3*t,1e-10)

    def test_memory_blocks_against_sampled_definitions(self):
        self.assert_series(self.chain('derivative',{'gain':2},source='model_time'),lambda t:0 if t==0 else 2)
        self.assert_series(self.chain('rate_limiter',source_params={'value':5}),lambda t:t)
        self.assert_series(self.chain('time_average',source='model_time'),lambda t:t/2)
        self.assert_series(self.chain('time_average'),lambda t:1)
        self.assert_series(self.chain('running_minimum',source='polynomial',source_params={'coefficients':'-1,2'}),lambda t:2-t)
        self.assert_series(self.chain('running_maximum',source='polynomial',source_params={'coefficients':'-1,-1'}),lambda t:-1)
        for kind,expected in [('sample_hold',lambda t:round(math.floor((t+1e-9)/.1)*.1,8)),
                              ('linear_extrapolator',lambda t:0 if t<.1 else t)]:
            self.assert_series(self.chain(kind,{'period':.1},source='model_time'),expected,1e-10)

    def test_relay_counter_trigger_and_switch(self):
        r=self.chain('relay',{'low':0,'high':2},source='piecewise',
                     source_params={'times':'0,1,2,3','values':'0,2,0,-2'},end=3)
        self.assert_series(r,lambda t:2 if .25<=t<2.25 else 0)
        sources=[b('up','step',{'time':.2}),b('down','step',{'time':.5})]
        result=self.run_model(sources+[b('count','counter')],[c('up','count'),c('down','count',1)])['count']
        self.assert_series(result,lambda t:1 if .2<=t<.5 else 0)
        result=self.run_model(sources+[b('latch','sr_trigger')],[c('up','latch'),c('down','latch',1)])['latch']
        self.assert_series(result,lambda t:1 if .2<=t<.5 else 0)
        result=self.run_model([b('a','constant',{'value':2}),b('z','constant',{'value':3}),b('ctl','step',{'time':.5}),
                              b('sw','controlled_switch')],[c('a','sw'),c('z','sw',1),c('ctl','sw',2)])['sw']
        self.assert_series(result,lambda t:2 if t<.5 else 3)

    def test_noise_repeatability_and_step_hold(self):
        for kind in ['uniform_noise','normal_noise']:
            a=self.run_model([b('noise',kind,{'seed':3})],[])['noise']
            z=self.run_model([b('noise',kind,{'seed':3})],[])['noise']
            other=self.run_model([b('noise',kind,{'seed':4})],[])['noise']
            self.assertEqual(a,z);self.assertNotEqual(a,other)
            if kind=='uniform_noise':self.assertTrue(all(0<=v<=1 for t,v in a))
            block=self.model.blocks['noise'];self.assertEqual(block.compute(.011,[],block.params,block.state),
                                                            block.compute(.019,[],block.params,block.state))
        r=self.run_model([b('n','normal_noise',{'mean':2,'sigma':0})],[])['n']
        self.assert_series(r,lambda t:2)

    def test_clear_validation_errors_and_direct_feedthrough_loops(self):
        for kind,params in [('transport_delay',{'tau':-1}),('pid',{'filter_tau':0}),
                            ('transfer_function',{'numerator':'1,2','denominator':'1'}),
                            ('transfer_function',{'denominator':'0,1'}),('sample_hold',{'period':.015}),
                            ('relay',{'lower':1,'upper':0}),('piecewise',{'times':'1,0','values':'0,1'})]:
            with self.subTest(kind=kind):
                cls=self.lib.get(kind);blocks=[b('target',kind,params)];connections=[]
                for i in range(cls.n_inputs):
                    id='src'+str(i);blocks.append(b(id,'constant'));connections.append(c(id,'target',i))
                with self.assertRaises((BlockError,ValueError)):self.run_model(blocks,connections)
        with self.assertRaisesRegex(BlockError,'requires input port'):
            self.run_model([b('pid','pid')],[])
        for kind,params in [('transport_delay',{'tau':0}),('filtered_derivative',{}),('transfer_function',{'numerator':'1,0'})]:
            with self.assertRaises(AlgebraicLoopError):self.run_model([b('loop',kind,params)],[c('loop','loop')])

    def test_pid_inside_subsystem_and_splitter_outputs(self):
        inner={'blocks':[b('In1','in1_terminal'),b('Out1','out1_terminal'),b('k1','constant',{'value':2}),
                         b('k2','constant',{'value':3}),b('k3','constant',{'value':0}),b('pid','pid')],
               'connections':[c('In1','pid'),c('k1','pid',1),c('k2','pid',2),c('k3','pid',3),c('pid','Out1')]}
        sub=b('sub','subsystem');sub['internal']=inner
        r=self.run_model([b('input','constant',{'value':1}),sub,b('sink','graph_display')],
                         [c('input','sub'),c('sub','sink')])['sink']
        self.assert_series(r,lambda t:2+3*t)
        result=self.run_model([b('u','constant',{'value':2}),b('sp','splitter'),b('a','graph_display'),b('z','graph_display')],
                             [c('u','sp'),c('sp','a'),c('sp','z',source_port=1)])
        self.assertEqual(result['a'],result['z']);self.assert_series(result['z'],lambda t:2)
