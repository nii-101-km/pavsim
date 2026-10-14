"""Known objectives exercise pattern moves and Polyak inertia, not source text."""
import copy
import unittest
from xcos_mini.core import BlockError
from xcos_mini.optimization import optimize, algorithm_options

class SearchMethodsTests(unittest.TestCase):
    def search(self, algorithm, options='', bounds=None, start=None, objective=None, budget=100):
        start=start or [.2,.1,7.]
        model={'blocks':[{'id':'opt','params':dict(zip(('p1','p2','p3'),start))}]}
        original=copy.deepcopy(model)
        def evaluate(candidate):
            p=candidate['blocks'][0]['params'];x,y=p['p1'],p['p2']
            score=objective(x,y) if objective else (x-.7)**2+2*(y-.6)**2
            metrics=dict(settled=True,iae=score,ise=score)
            return metrics,[(0,score),(1,score)],score
        result=optimize(model,None,dict(algorithm=algorithm,algorithm_options=options,
            bounds=bounds or [[0,1],[0,1],[7,7]],max_evaluations=budget,t_end=1,h=.1),
            binding={'parameters':[('opt',f'p{i}') for i in range(1,4)],'evaluate':evaluate})
        self.assertEqual(model,original)
        self.assertLessEqual(result['evaluations'],budget)
        self.assertEqual(result['coefficients']['k3'],7)
        return result

    def test_both_methods_converge_reproducibly_and_respect_fixed_axes(self):
        for algorithm in ('hooke_jeeves','heavy_ball'):
            with self.subTest(algorithm=algorithm):
                a=self.search(algorithm);b=self.search(algorithm)
                self.assertEqual(a,b)
                self.assertLess(a['score'],1e-4)
                self.assertTrue(all(0<=r['values'][i]<=1 for r in a['trace'] for i in (0,1)))
                self.assertEqual(a['algorithm_options']['random_starts'],0)

    def test_hooke_jeeves_pattern_move_and_initial_step(self):
        result=self.search('hooke_jeeves','initial_step=.1; max_iterations=1')
        values=[r['values'][:2] for r in result['trace']]
        self.assertTrue(any(abs(x-.4)<1e-9 and abs(y-.3)<1e-9 for x,y in values),values)
        no_pattern=self.search('hooke_jeeves','initial_step=.1; pattern_step=.2; max_iterations=1')
        self.assertNotEqual(values,[r['values'][:2] for r in no_pattern['trace']])

    def test_heavy_ball_uses_previous_displacement(self):
        # f=.5*(x-.7)^2: first step .2 -> .3. Second uses
        # -.2*(-.4)+.5*(.1)=.13, hence x=.43 (zero inertia gives .38).
        quadratic=lambda x,y:.5*(x-.7)**2
        r=self.search('heavy_ball','initial_step=.2; momentum=.5; max_iterations=2',
                      bounds=[[0,1],[.1,.1],[7,7]],objective=quadratic)
        self.assertTrue(any(abs(t['values'][0]-.43)<1e-8 for t in r['trace']))
        z=self.search('heavy_ball','initial_step=.2; momentum=0; max_iterations=2',
                      bounds=[[0,1],[.1,.1],[7,7]],objective=quadratic)
        self.assertTrue(any(abs(t['values'][0]-.38)<1e-8 for t in z['trace']))

    def test_bounds_budget_failed_trials_and_unreachable_minimum(self):
        def bounded(x,y):
            if x>.8:raise BlockError('invalid experiment')
            return (x-2)**2+(y+1)**2
        for algorithm in ('hooke_jeeves','heavy_ball'):
            r=self.search(algorithm,objective=bounded,budget=20)
            self.assertLess(r['score'],r['baseline_score'])
            self.assertGreater(r['failed_evaluations'],0)
            self.assertTrue(all(0<=v<=1 for t in r['trace'] for v in t['values'][:2]))
            fixed=self.search(algorithm,bounds=[[.2,.2],[.1,.1],[7,7]])
            self.assertEqual(fixed['evaluations'],1)

    def test_options_are_validated(self):
        self.assertEqual(algorithm_options('heavy_ball','momentum=0')['momentum'],0)
        for algorithm,options in [('heavy_ball','momentum=1'),('heavy_ball','momentum=-.1'),
                                  ('hooke_jeeves','pattern_step=0'),('hooke_jeeves','pattern_step=11')]:
            with self.subTest(options=options),self.assertRaises(BlockError):algorithm_options(algorithm,options)
