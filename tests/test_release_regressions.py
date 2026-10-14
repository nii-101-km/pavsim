"""Real HTTP boundary checks and independently specified endpoint behavior."""
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from xcos_mini import server
from xcos_mini.core import Library, Engine, BlockError
from xcos_mini.experiments import execute_workspace
from xcos_mini.optimization import optimize

ROOT = Path(__file__).resolve().parents[1]

def block(bid, kind, **params):
    return {'id':bid, 'type':kind, 'params':params}

def wire(source, target, port=0):
    return {'from':source, 'to':target, 'from_port':0, 'to_port':port}

class TimeGridTests(unittest.TestCase):
    def setUp(self):
        self.lib = Library(str(ROOT/'blocks'))
    def run_model(self, blocks, wires, end=1, h=.6, method='rk4'):
        model=server._build_model(self.lib, {'blocks':blocks, 'connections':wires})
        return Engine(model,end,h,method).run()
    def test_shortened_last_step_and_exact_multiples(self):
        for h,expected in [(.6,[0,.6,1]),(.25,[0,.25,.5,.75,1]),(.1,[i*.1 for i in range(10)]+[1]),(2,[0,1])]:
            for method in ['rk4','euler']:
                with self.subTest(h=h,method=method):
                    result=self.run_model([block('c','constant',value=1),block('i','integrator')],[wire('c','i')],h=h,method=method)['i']
                    self.assertEqual([t for t,y in result],expected)
                    for t,y in result:self.assertAlmostEqual(y,t,places=12)
                    self.assertTrue(all(t<=1 for t,y in result))
    def test_zero_and_tiny_horizons(self):
        for end,h in [(0,.6),(1e-320,1e308)]:
            result=self.run_model([block('t','model_time')],[],end=end,h=h)['t']
            self.assertEqual([t for t,y in result],[0] if not end else [0,end])
    def test_rk4_stages_use_the_last_actual_interval(self):
        # x'=-x: RK4's independent stability polynomial at dt=.6 and .4.
        p=lambda dt:1-dt+dt**2/2-dt**3/6+dt**4/24
        result=self.run_model([block('i','integrator',initial_value=1),block('g','gain',gain=-1)],
                              [wire('i','g'),wire('g','i')])['i']
        self.assertAlmostEqual(result[-1][1],p(.6)*p(.4),places=12)
    def test_memory_delay_and_discrete_periods_keep_their_definitions(self):
        blocks=[block('t','model_time'),block('d','delay'),block('hold','sample_hold',period=.6),
                block('linear','linear_extrapolator',period=.6),block('deriv','derivative'),
                block('lag','transport_delay',tau=.3)]
        result=self.run_model(blocks,[wire('t',bid) for bid in ['d','hold','linear','deriv','lag']])
        self.assertEqual([y for t,y in result['d']],[0,0,.6])
        self.assertEqual([y for t,y in result['hold']],[0,.6,.6])
        self.assertEqual([y for t,y in result['linear']],[0,.6,1])
        self.assertEqual([y for t,y in result['deriv']],[0,1,1])
        for t,y in result['lag']:self.assertAlmostEqual(y,max(0,t-.3),places=12)
        for tau in [0,.3,.6,.8]:
            lag=self.run_model([block('t','model_time'),block('lag','transport_delay',tau=tau)],
                               [wire('t','lag')])['lag']
            for t,y in lag:self.assertAlmostEqual(y,max(0,t-tau),places=12)
    def test_hold_sampling_period_is_not_redefined_by_final_step(self):
        result=self.run_model([block('t','model_time'),block('hold','sample_hold',period=1.2)],
                              [wire('t','hold')])['hold']
        self.assertEqual([y for t,y in result],[0,0,0])
    def test_invalid_time_arguments_raise_block_error(self):
        for end,h in [(None,.1),('bad',.1),(math.nan,.1),(math.inf,.1),(1,math.nan),(1,math.inf),
                      (1,0),(-1,.1),(True,.1),(1,False),(1,1e-320)]:
            with self.subTest(end=end,h=h),self.assertRaises(BlockError):
                self.run_model([block('c','constant')],[],end=end,h=h)
    def test_experiment_and_hooke_jeeves_end_at_the_local_horizon(self):
        model=json.loads((ROOT/'examples/demo_experiment_workspace.json').read_text())
        opt=next(b for b in model['blocks'] if b['type']=='optimizer')
        opt['params'].update(enabled=False,algorithm='hooke_jeeves',max_evaluations=20)
        exp=next(b for b in model['blocks'] if b['type']=='experiment')
        exp['params'].update(t_end=1,h=.6)
        result,_,done=execute_workspace(model,lambda d:server._build_model(self.lib,d),selected='exp')
        self.assertEqual([t for t,y in result['exp/graph']],[0,.6,1])
        self.assertEqual(done[0]['t_end'],1)
        opt['params']['enabled']=True
        result,reports,done=execute_workspace(model,lambda d:server._build_model(self.lib,d))
        self.assertEqual(result['exp/graph'][-1][0],1)
        self.assertLessEqual(reports[0]['evaluations'],20)
    def test_controller_optimization_series_ends_at_requested_time(self):
        model=json.loads((ROOT/'examples/demo_pi_optimization.json').read_text())
        result=optimize(model,lambda d:server._build_model(self.lib,d),dict(controller='pi',output='graph',
            bounds=[[0,5],[0,5]],algorithm='hooke_jeeves',max_evaluations=20,t_end=1,h=.6))
        self.assertEqual(result['series']['t'],[0,.6,1])
    def test_optimizer_volume_limit_accounts_for_last_partial_sample(self):
        # 2999 full intervals + final partial interval + initial sample =
        # 3001 samples per trial, exceeding 600000 at a budget of 200.
        model=json.loads((ROOT/'examples/demo_pi_optimization.json').read_text())
        with self.assertRaisesRegex(BlockError,'Слишком большой объём'):
            optimize(model,lambda d:server._build_model(self.lib,d),dict(controller='pi',output='graph',
                bounds=[[0,0],[0,0]],max_evaluations=200,t_end=1,h=1/2999.1))

class HTTPReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.web=self.root/'web';self.web.mkdir()
        (self.web/'index.html').write_text('SAFE_INDEX');(self.web/'ok.txt').write_text('SAFE_FILE')
        self.outside=self.root/'web-private';self.outside.mkdir();(self.outside/'secret.txt').write_text('SENTINEL')
        self.patch=patch.object(server,'WEB_DIR',str(self.web));self.patch.start();self.addCleanup(self.patch.stop)
        class Handler(server.Handler):pass
        Handler.lib=Library(str(ROOT/'blocks'))
        self.httpd=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=self.httpd.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.httpd.server_close);self.addCleanup(thread.join);self.addCleanup(self.httpd.shutdown)
        self.url='http://127.0.0.1:'+str(self.httpd.server_address[1])
    def request(self,path,body=None):
        request=urllib.request.Request(self.url+path,data=None if body is None else json.dumps(body).encode(),
                                       headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,response.read()
        except urllib.error.HTTPError as error:return error.code,error.read()
    def test_static_directory_boundaries_and_symlinks(self):
        (self.web/'inside-link.txt').symlink_to(self.web/'ok.txt')
        (self.web/'outside-link.txt').symlink_to(self.outside/'secret.txt')
        (self.web/'outside-dir').symlink_to(self.outside,target_is_directory=True)
        for path in ['/','/index.html','/ok.txt','/inside-link.txt']:
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],200)
        for path in ['/../web-private/secret.txt','/%2e%2e/web-private/secret.txt',
                     '/outside-link.txt','/outside-dir/secret.txt','/../../etc/passwd']:
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],403)
        (self.web/'index.html').unlink();(self.web/'index.html').symlink_to(self.outside/'secret.txt')
        for path in ['/','/index.html']:self.assertEqual(self.request(path)[0],403)
    def test_bad_time_values_return_client_errors(self):
        for endpoint in ['/api/simulate','/api/optimize']:
            for field in ['t_end','h']:
                for value in [None,True,False,'bad','NaN','Infinity',math.nan,math.inf,-math.inf,{},[],10**400]:
                    if endpoint=='/api/simulate':
                        body={'model':{'blocks':[],'connections':[]},'t_end':1,'h':.1};body[field]=value
                    else:
                        body={'model':json.loads((ROOT/'examples/demo_pi_optimization.json').read_text()),
                              'settings':dict(controller='pi',output='graph',bounds=[[0,5],[0,5]],t_end=1,h=.1)}
                        body['settings'][field]=value
                    with self.subTest(endpoint=endpoint,field=field,value=value):
                        status,data=self.request(endpoint,body)
                        self.assertEqual(status,400,data);self.assertIn('error',json.loads(data))
        for end,h in [(-1,.1),(1,0),(1,-.1),(1,1e-320)]:
            self.assertEqual(self.request('/api/simulate',{'model':{},'t_end':end,'h':h})[0],400)
    def test_step_count_matches_actual_shortened_grid(self):
        body={'model':{'blocks':[block('t','model_time')],'connections':[]},'t_end':1,'h':.6}
        status,data=self.request('/api/simulate',body);result=json.loads(data)
        self.assertEqual(status,200,data);self.assertEqual(result['n_steps'],2)
        self.assertEqual(result['results']['t']['t'],[0,.6,1])
