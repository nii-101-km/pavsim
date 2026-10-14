"""Behavioral tuning tests through production model construction and Engine."""
import copy
import json
import math
from pathlib import Path
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

from xcos_mini.core import Library, BlockError
from xcos_mini.server import _build_model
from xcos_mini.optimization import optimize, response_metrics, coefficient_sources, objective_score, algorithm_options

ROOT=Path(__file__).resolve().parents[1]

def model():
    return json.loads((ROOT/'examples/demo_pi_optimization.json').read_text())

def settings(**changes):
    result=dict(controller='pi',output='graph',target=1,objective='iae',bounds=[[0,5],[0,5]],t_end=8,h=.04,max_evaluations=40)
    result.update(changes);return result

class OptimizationTests(unittest.TestCase):
    def setUp(self):self.lib=Library(str(ROOT/'blocks'))
    def tune(self,m=None,**changes):
        return optimize(m or model(),lambda d:_build_model(self.lib,d),settings(**changes))

    def test_metrics_known_series_and_negative_step(self):
        m=response_metrics([(0,0),(1,.9),(2,1),(3,1),(4,1)],1)
        self.assertEqual(m['settling_time'],2)
        self.assertEqual(m['overshoot'],0)
        self.assertEqual(m['oscillation'],0)
        self.assertAlmostEqual(m['iae'],.6)
        self.assertAlmostEqual(m['ise'],.51)
        n=response_metrics([(0,0),(1,-1.2),(2,-1),(3,-1),(4,-1)],-1)
        self.assertAlmostEqual(n['overshoot'],20)
        self.assertAlmostEqual(n['oscillation'],.2)
        self.assertEqual(n['settling_time'],2)

    def test_terminal_crossing_does_not_count_as_settled(self):
        m=response_metrics([(0,0),(1,0),(2,0),(3,0),(4,1)],1)
        self.assertIsNone(m['settling_time'])
        dead=response_metrics([(0,0),(1,0),(2,0)],1)
        good=response_metrics([(0,0),(1,1),(2,1)],1)
        for objective in ['settling_time','overshoot','oscillation']:
            self.assertGreater(objective_score(dead,objective,2,1),objective_score(good,objective,2,1))

    def test_all_five_objectives_improve_and_never_mutate_source(self):
        for objective in ['iae','ise','settling_time','overshoot','oscillation']:
            with self.subTest(objective=objective):
                m=model();old=copy.deepcopy(m);r=self.tune(m,objective=objective)
                self.assertEqual(m,old)
                self.assertLess(r['score'],r['baseline_score'])
                self.assertTrue(r['converged'])
                self.assertLessEqual(r['evaluations'],40)
                self.assertTrue(all(0<=v<=5 for v in r['coefficients'].values()))
                # Independent analytic closed-loop solution for this first-order
                # plant with arbitrary returned PI coefficients.
                kp,ki=r['coefficients']['k1'],r['coefficients']['k2']
                discriminant=(1+kp)**2-4*ki
                if discriminant>1e-10:
                    r1=(-(1+kp)+math.sqrt(discriminant))/2
                    r2=(-(1+kp)-math.sqrt(discriminant))/2
                    a=(kp+r2)/(r1-r2)
                    expected=lambda t:1+a*math.exp(r1*t)+(-1-a)*math.exp(r2*t)
                elif discriminant < -1e-10:
                    alpha=-(1+kp)/2;beta=math.sqrt(-discriminant)/2
                    expected=lambda t:1+math.exp(alpha*t)*(-math.cos(beta*t)+(kp+alpha)/beta*math.sin(beta*t))
                else:
                    pole=-(1+kp)/2
                    expected=lambda t:1+(-1+(kp+pole)*t)*math.exp(pole*t)
                for t,y in zip(r['series']['t'],r['series']['y']):
                    self.assertAlmostEqual(y,expected(t),delta=7e-6)

    def test_fixed_coefficient_and_baseline_outside_bounds(self):
        m=model();next(b for b in m['blocks'] if b['id']=='kp')['params']['value']=100
        r=self.tune(m,bounds=[[1,1],[.1,2]])
        self.assertEqual(r['coefficients']['k1'],1)
        self.assertTrue(.1<=r['coefficients']['k2']<=2)
        r=self.tune(bounds=[[1,1],[1,1]])
        self.assertEqual(r['coefficients'],{'k1':1,'k2':1})

    def test_pid_three_coefficient_ports_and_euler(self):
        m=model();controller=next(b for b in m['blocks'] if b['id']=='pi')
        controller['type']='pid';controller['params']={'filter_tau':.2}
        m['blocks'].append({'id':'kd','type':'constant','params':{'value':.01}})
        m['connections'].append({'from':'kd','to':'pi','from_port':0,'to_port':3})
        for method in ['rk4','euler']:
            r=self.tune(m,bounds=[[0,3],[0,3],[0,.3]],method=method)
            self.assertEqual(r['source_ids'],['kp','ki','kd'])
            self.assertIn('k3',r['coefficients'])
            self.assertLess(r['metrics']['iae'],r['baseline']['iae'])

    def test_wrong_sources_shared_constants_and_missing_inputs_rejected(self):
        m=model();next(b for b in m['blocks'] if b['id']=='kp')['type']='sine'
        with self.assertRaisesRegex(BlockError,'Константы'):self.tune(m)
        m=model();m['connections'].append({'from':'kp','to':'error','to_port':0})
        with self.assertRaisesRegex(BlockError,'только'):self.tune(m)
        m=model();m['connections']=[c for c in m['connections'] if c['from']!='ki']
        with self.assertRaisesRegex(BlockError,'k2'):self.tune(m)
        m=model();m['connections']=[c for c in m['connections'] if c['from']!='error']
        with self.assertRaisesRegex(BlockError,'Не найден допустимый'):self.tune(m)

    def test_invalid_settings_and_nonfinite_metrics_rejected(self):
        for overrides in [dict(objective='bogus'),dict(target=float('nan')),dict(tolerance=0),
                          dict(h=0),dict(t_end=-1),dict(bounds=[[5,0],[0,1]]),dict(bounds=[[0,1]]),
                          dict(max_evaluations=500),dict(max_evaluations=20.5),dict(method='bad'),
                          dict(t_end=10000,h=.001),dict(output='missing')]:
            with self.subTest(overrides=overrides),self.assertRaises(BlockError):self.tune(**overrides)
        with self.assertRaises(BlockError):response_metrics([(0,0),(1,float('inf'))],1)

    def test_reproducible_search_and_budget(self):
        a=self.tune(max_evaluations=20);b=self.tune(max_evaluations=20)
        self.assertEqual(a,b);self.assertLessEqual(a['evaluations'],20)

    def test_unreachable_setpoint_reported_not_false_success(self):
        r=self.tune(bounds=[[0,0],[0,0]],objective='overshoot')
        self.assertFalse(r['converged'])
        self.assertIsNone(r['metrics']['settling_time'])
        self.assertEqual(r['metrics']['overshoot'],0)
        self.assertGreater(r['score'],1000)

    def test_algorithm_parameter_parser_and_validation(self):
        self.assertEqual(algorithm_options('coordinate','')['initial_step'],.25)
        self.assertEqual(algorithm_options('nelder_mead','')['initial_step'],.15)
        self.assertEqual(algorithm_options('gradient','')['initial_step'],.2)
        self.assertEqual(algorithm_options('coordinate',' initial_step=0,1; shrink=0.4; max_iterations=5;')['initial_step'],.1)
        for algorithm,text in [('coordinate','typo=1'),('coordinate','initial_step=0'),('coordinate','initial_step=nan'),
                               ('coordinate','initial_step=.1; initial_step=.2'),('coordinate','shrink=1'),
                               ('coordinate','max_iterations=1.2'),('coordinate','initial_step=.01; tolerance=.1'),
                               ('gradient','backtracks=0'),('nelder_mead','expansion=1'),('coordinate','initial_step:0.1')]:
            with self.subTest(text=text),self.assertRaises(BlockError):algorithm_options(algorithm,text)

    def test_advanced_parameters_change_real_search_trajectory(self):
        for algorithm in ['coordinate','nelder_mead','gradient']:
            with self.subTest(algorithm=algorithm):
                default=self.tune(algorithm=algorithm)
                configured=self.tune(algorithm=algorithm,algorithm_options='initial_step=0.05; max_iterations=2')
                self.assertEqual(configured['algorithm_options']['initial_step'],.05)
                self.assertNotEqual(default['trace'],configured['trace'])
                self.assertLessEqual(configured['evaluations'],40)
                self.assertTrue(all(0<=v<=5 for v in configured['coefficients'].values()))

    def test_no_hidden_reconnaissance_before_small_simplex(self):
        result=self.tune(algorithm='nelder_mead',algorithm_options='initial_step=0.01; max_iterations=1')
        self.assertEqual(result['algorithm_options']['random_starts'],0)
        # Initial values and the two simplex vertices; no midpoint/random starts.
        self.assertEqual(result['trace'][0]['values'],[.2,.1])
        self.assertEqual(len(result['trace'][1]['values']),2)
        self.assertAlmostEqual(result['trace'][1]['values'][0],.25)
        self.assertAlmostEqual(result['trace'][1]['values'][1],.1)
        self.assertAlmostEqual(result['trace'][2]['values'][0],.2)
        self.assertAlmostEqual(result['trace'][2]['values'][1],.15)
        explored=self.tune(algorithm='nelder_mead',algorithm_options='initial_step=0.01; max_iterations=1; random_starts=3')
        self.assertNotEqual(result['trace'][1]['values'],explored['trace'][1]['values'])
        for text in ['random_starts=-1','random_starts=1.5','random_starts=51']:
            with self.assertRaises(BlockError):algorithm_options('nelder_mead',text)

    def test_live_api_tunes_real_diagram_and_rejects_invalid_settings(self):
        from xcos_mini import server
        # Use a private Handler subclass; do not alter the live application's library.
        class TestHandler(server.Handler):pass
        TestHandler.lib=self.lib
        httpd=ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
        thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{httpd.server_address[1]}/api/optimize'
        try:
            payload=json.dumps({'model':model(),'settings':settings(max_evaluations=20)}).encode()
            result=json.load(urllib.request.urlopen(urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'})))
            self.assertTrue(result['ok']);self.assertLess(result['score'],result['baseline_score'])
            payload=json.dumps({'model':model(),'settings':settings(target='bad')}).encode()
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(url,data=payload))
            self.assertEqual(error.exception.code,400)
            self.assertIn('Уставка',json.load(error.exception)['error'])
        finally:
            httpd.shutdown();httpd.server_close();thread.join()
