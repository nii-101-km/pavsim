"""Behavioral coverage of distinct scalar ports and signal-connected tuning."""
import copy
import json
import math
from pathlib import Path
import unittest
from xcos_mini.core import Library, Block, Model, Engine, BlockError
from xcos_mini.server import _build_model, _serialize_results
from xcos_mini.optimization import simulate_with_optimizers, response_metrics
ROOT=Path(__file__).resolve().parents[1]
def b(i,t,p=None):return {'id':i,'type':t,'params':p or {}}
def c(a,z,port=0,source_port=0):return {'from':a,'to':z,'from_port':source_port,'to_port':port}
class OptimizerBlockTests(unittest.TestCase):
    def setUp(self):self.lib=Library(str(ROOT/'blocks'))
    def build(self,m):return _build_model(self.lib,m)
    def fixture(self):return json.loads((ROOT/'examples/demo_block_optimizer.json').read_text())
    def run_tuning(self,m,method='rk4',end=8,h=.04):return simulate_with_optimizers(m,self.build,end,h,method)

    def test_distinct_ports_without_tuning_and_serialization(self):
        m={'blocks':[b('opt','optimizer',{'enabled':False,'p1':2,'p2':3,'p3':7}),b('zero','constant',{'value':0}),b('goal','objective'),b('a','graph_display'),b('z','graph_display'),b('last','graph_display')],
           'connections':[c('zero','goal'),c('goal','opt'),c('opt','a'),c('opt','z',source_port=1),c('opt','last',source_port=2)]}
        r,reports=self.run_tuning(m)
        self.assertEqual(reports,[])
        for id,value in [('a',2),('z',3),('last',7)]:self.assertTrue(all(y==value for t,y in r[id]))
        api=_serialize_results(r)
        self.assertEqual(api['opt']['y'],[2]*len(r['opt']))
        self.assertEqual(api['opt']['outputs'],[[2]*len(r['opt']),[3]*len(r['opt']),[7]*len(r['opt'])])

    def test_one_run_tunes_pi_keeps_unchecked_parameter_and_original_json(self):
        for method in ['rk4','euler']:
            m=self.fixture();original=copy.deepcopy(m)
            result,reports=self.run_tuning(m,method)
            self.assertEqual(m,original)
            report=reports[0];self.assertEqual(report['values']['p3'],7)
            self.assertLess(report['metrics']['iae'],report['baseline']['iae'])
            self.assertEqual(result['opt'][-1][1][2],7)
            self.assertLessEqual(report['evaluations'],60)
            # The actual final simulation uses reported coefficients, not just a label.
            tuned=copy.deepcopy(m);next(z for z in tuned['blocks'] if z['id']=='opt')['params'].update(report['values'])
            expected=Engine(self.build(tuned),8,.04,method).run()
            self.assertEqual(result['graph'],expected['graph'])
            self.assertAlmostEqual(result['goal'][-1][1],report['metrics']['iae'])

    def test_optimizer_is_not_specific_to_regulators(self):
        m={'blocks':[b('opt','optimizer',{'optimize_p1':False,'optimize_p2':True,'optimize_p3':False,'p1':8,'p2':.1,'p3':9,'max_evaluations':80}),b('one','constant',{'value':1}),b('mul','multiplication'),b('goal','objective',{'target':3}),b('graph','graph_display')],
           'connections':[c('one','mul'),c('opt','mul',1,1),c('mul','goal'),c('mul','graph'),c('goal','opt')]}
        results,reports=self.run_tuning(m,end=1,h=.02)
        p=reports[0]['values'];self.assertEqual(p['p1'],8);self.assertEqual(p['p3'],9)
        self.assertAlmostEqual(p['p2'],3,delta=.01)
        self.assertTrue(all(abs(y-3)<.01 for t,y in results['graph']))

    def test_goal_dropdown_choices_produce_correct_full_run_metrics(self):
        for name in ['iae','ise','settling_time','overshoot','oscillation']:
            m=self.fixture();opt=next(b for b in m['blocks'] if b['id']=='opt');opt['params'].update(enabled=False,p1=1,p2=1)
            next(b for b in m['blocks'] if b['id']=='goal')['params']['objective']=name
            results,_=self.run_tuning(m)
            metrics=response_metrics(results['graph'],1)
            if name in ('iae','ise'):self.assertAlmostEqual(results['goal'][-1][1],metrics[name])
            self.assertTrue(math.isfinite(results['goal'][-1][1]))

    def test_subsystem_output_preserves_nonzero_source_port(self):
        inner={'blocks':[b('in','in1_terminal'),b('out','out1_terminal'),b('opt','optimizer',{'enabled':False,'p1':2,'p2':3,'p3':7}),b('goal','objective')],
               'connections':[c('in','goal'),c('goal','opt'),c('opt','out',source_port=2)]}
        sub=b('sub','subsystem');sub['internal']=inner
        m={'blocks':[b('u','constant',{'value':1}),sub,b('graph','graph_display')],'connections':[c('u','sub'),c('sub','graph')]}
        results,_=self.run_tuning(m)
        self.assertTrue(all(y==7 for t,y in results['graph']))

    def test_real_algorithms_respect_bounds_budget_and_fixed_parameters(self):
        for algorithm in ['coordinate','nelder_mead','gradient','hooke_jeeves','heavy_ball']:
            with self.subTest(algorithm=algorithm):
                m=self.fixture();opt=next(b for b in m['blocks'] if b['id']=='opt')
                opt['params'].update(algorithm=algorithm,max_evaluations=80)
                result,reports=self.run_tuning(m)
                report=reports[0]
                self.assertEqual(report['algorithm'],algorithm)
                self.assertLess(report['metrics']['iae'],report['baseline']['iae'])
                self.assertLessEqual(report['evaluations'],80)
                self.assertTrue(all(0<=report['values'][p]<=5 for p in ['p1','p2']))
                self.assertEqual(report['values']['p3'],7)
        m=self.fixture();next(b for b in m['blocks'] if b['id']=='opt')['params']['algorithm']='bogus'
        with self.assertRaisesRegex(BlockError,'алгоритм'):self.run_tuning(m)

    def test_missing_or_wrong_objective_and_invalid_port_rejected(self):
        m=self.fixture();m['connections']=[c for c in m['connections'] if c['to']!='opt']
        with self.assertRaisesRegex(BlockError,'Целевой функции'):self.run_tuning(m)
        m=self.fixture();next(c for c in m['connections'] if c['to']=='opt')['from']='graph'
        with self.assertRaisesRegex(BlockError,'Целевая функция'):self.run_tuning(m)
        m=self.fixture();next(c for c in m['connections'] if c['from']=='opt')['from_port']=3
        with self.assertRaises(BlockError):self.run_tuning(m)

    def test_vector_width_nan_and_scalar_compatibility(self):
        class Multi(Block):
            n_inputs=0;n_outputs=3
            def compute(self,t,x,p,s):return self.params['values']
        for values in [[1,2],[1,2,float('nan')],[1,2,'wrong']]:
            m=Model();source=Multi();source.params['values']=values;m.add_block(source,'source')
            with self.assertRaises(BlockError):Engine(m,1,.1).run()
        # Old splitter scalar remains broadcast to both output ports.
        m={'blocks':[b('u','constant',{'value':4}),b('s','splitter'),b('a','graph_display'),b('z','graph_display')],
           'connections':[c('u','s'),c('s','a'),c('s','z',source_port=1)]}
        r,_=self.run_tuning(m);self.assertEqual(r['a'],r['z']);self.assertTrue(all(y==4 for t,y in r['a']))
