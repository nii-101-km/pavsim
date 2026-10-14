import copy,json,math,threading,unittest,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from xcos_mini.core import Library,BlockError
from xcos_mini.server import _build_model
from xcos_mini.experiments import execute_workspace
ROOT=Path(__file__).resolve().parents[1]
class ExperimentTests(unittest.TestCase):
 def setUp(self):self.lib=Library(str(ROOT/'blocks'))
 def fixture(self):return json.loads((ROOT/'examples/demo_experiment_workspace.json').read_text())
 def run_world(self,m,**kw):return execute_workspace(m,lambda d:_build_model(self.lib,d),**kw)
 def test_fresh_trials_local_settings_and_scalar_completion(self):
  m=self.fixture();old=copy.deepcopy(m)
  a,reports,done=self.run_world(m,t_end=1,h=.5,method='euler')
  self.assertEqual(m,old);self.assertEqual(done[0]['t_end'],10);self.assertEqual(done[0]['method'],'rk4')
  self.assertEqual(len(a['exp/graph']),501);self.assertEqual(done[0]['status'],'completed')
  self.assertAlmostEqual(a['exp'][-1][1],reports[0]['score'])
  self.assertLess(reports[0]['score'],.25)
  self.assertEqual(len(a['route']),len([r for r in reports[0]['trace'] if r['score'] is not None]))
  for (i,v),trial in zip(a['route'],reports[0]['trace']):
   self.assertEqual(v[:2],tuple(trial['values'][:2]));self.assertEqual(v[2],trial['score'])
 def test_independent_clocks_and_selected_run(self):
  m=self.fixture();m['blocks'][0]['params']['enabled']=False
  second=copy.deepcopy(next(b for b in m['blocks'] if b['id']=='exp'));second['id']='second';second['params'].update(t_end=2,h=.1,method='euler')
  m['blocks'].append(second)
  for i in range(3):m['connections'].append({'from':'opt','from_port':i,'to':'second','to_port':i})
  a,reports,done=self.run_world(m)
  self.assertEqual(len(a['exp/graph']),501);self.assertEqual(len(a['second/graph']),21)
  self.assertEqual([d['method'] for d in done],['rk4','euler'])
  a,reports,done=self.run_world(m,selected='second')
  self.assertEqual(reports,[]);self.assertEqual(len(done),1);self.assertNotIn('exp',a)
  self.assertEqual(len(a['second/graph']),21)
 def test_repeat_runs_restart_all_states_and_objective(self):
  m=self.fixture();m['blocks'][0]['params'].update(enabled=False,p1=1,p2=1)
  a,_,_=self.run_world(m,selected='exp');b,_,_=self.run_world(m,selected='exp')
  self.assertEqual(a,b)
  for t,y in a['exp/graph']:self.assertAlmostEqual(y,1-math.exp(-t),delta=1e-8)
  self.assertAlmostEqual(a['exp'][-1][1],1-math.exp(-10),delta=.0001)
 def test_delay_history_and_noise_restart_between_experiments(self):
  m=self.fixture();m['blocks'][0]['params'].update(enabled=False,p1=1,p2=1)
  inner=next(b for b in m['blocks'] if b['id']=='exp')['internal']
  inner['blocks'] += [{'id':'delay','type':'transport_delay','params':{'tau':.1}}, {'id':'noise','type':'normal_noise','params':{'seed':9,'sigma':.2}}]
  for c in inner['connections']:
   if c['from']=='plant':c['from']='delay'
  inner['connections'].append({'from':'plant','from_port':0,'to':'delay','to_port':0})
  a,_,_=self.run_world(m,selected='exp');b,_,_=self.run_world(m,selected='exp')
  self.assertEqual(a,b)
  self.assertTrue(all(y==0 for t,y in a['exp/delay'] if t<.1))
  self.assertEqual(a['exp/noise'],b['exp/noise'])
 def test_all_algorithms_minimize_completed_scalar(self):
  for algorithm in ['coordinate','nelder_mead','gradient','hooke_jeeves','heavy_ball']:
   m=self.fixture();m['blocks'][0]['params'].update(algorithm=algorithm,max_evaluations=25)
   result,reports,_=self.run_world(m)
   self.assertLess(reports[0]['score'],1.)
   self.assertLessEqual(reports[0]['evaluations'],25)
 def test_invalid_boundaries_and_local_settings_are_explicit(self):
  for change in ['missing_result','missing_input','bad_h','bad_method']:
   m=self.fixture();exp=next(b for b in m['blocks'] if b['id']=='exp')
   if change=='missing_result':exp['internal']['blocks']=[b for b in exp['internal']['blocks'] if b['type']!='experiment_result']
   if change=='missing_input':exp['internal']['blocks']=[b for b in exp['internal']['blocks'] if b['id']!='P3']
   if change=='bad_h':exp['params']['h']=0
   if change=='bad_method':exp['params']['method']='bad'
   with self.subTest(change=change),self.assertRaises(BlockError):self.run_world(m,selected='exp')
 def test_recording_plots_capture_each_input(self):
  for kind,n in [('graph_series2',2),('graph_series3',3),('graph_series4',4),('graph_xy',2),('graph_xyz',3)]:
   m={'blocks':[{'id':'plot','type':kind,'params':{}}]+[{'id':str(i),'type':'constant','params':{'value':i+2}} for i in range(n)],'connections':[{'from':str(i),'from_port':0,'to':'plot','to_port':i} for i in range(n)]}
   result,_,_=self.run_world(m,t_end=1,h=.1)
   self.assertTrue(all(v==tuple(range(2,n+2)) for t,v in result['plot']))
 def test_live_api_supplies_plot_packets_for_both_clocks(self):
  from xcos_mini import server
  class Handler(server.Handler):pass
  Handler.lib=self.lib;httpd=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start();url=f'http://127.0.0.1:{httpd.server_address[1]}'
  try:
   m=self.fixture();m['blocks'][0]['params']['max_evaluations']=20
   body=json.dumps({'model':m,'t_end':1,'h':.5}).encode()
   response=json.load(urllib.request.urlopen(urllib.request.Request(url+'/api/simulate',data=body,headers={'Content-Type':'application/json'})))
   route=json.load(urllib.request.urlopen(url+'/api/plot?run='+response['run_id']+'&block=route'))
   inner=json.load(urllib.request.urlopen(url+'/api/plot?run='+response['run_id']+'&block=exp/graph'))
   self.assertEqual(route['config']['axis'],'trial');self.assertEqual(len(route['data']['outputs']),3)
   self.assertEqual(inner['config']['axis'],'t');self.assertEqual(len(inner['data']['t']),501)
  finally:httpd.shutdown();httpd.server_close();thread.join()
