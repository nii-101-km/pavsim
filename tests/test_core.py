"""Automated test suite for the xcos_mini simulation core.

Covers:
  * numerical correctness (integrator, feedback decay, oscillator, delay,
    delay-feedback, signal generators, arithmetic, custom blocks)
  * integration-method behaviour (RK4 vs Euler)
  * algebraic-loop policy (rejected vs accepted)
  * save/load round-trip (Model.to_dict -> rebuild -> to_dict)
  * extensible library (custom-block loading + diagnostics)
  * error diagnostics (bad params, bad ports, non-scalar output, unknown type)

Run with:  python3 -m unittest discover -s tests -v
   or:     python3 tests/test_core.py
"""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xcos_mini.core import (  # noqa: E402
    Block, Model, Engine, Library, BlockError, AlgebraicLoopError,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS_DIR = os.path.join(ROOT, "blocks")

# Shared library: ALL blocks live in the filesystem-driven block library
# (blocks/) and are discovered recursively — instantiate them by name,
# not by import. There is no separate built-in/custom registry.
LIB = Library(blocks_dir=BLOCKS_DIR)


def blk(name):
    """Instantiate a block by name from the (filesystem-driven) library."""
    return LIB.instantiate(name)


def build_model(lib, d):
    """Rebuild a Model from a dict (mirrors the server's _build_model)."""
    m = Model()
    for b in d.get("blocks", []):
        block = lib.instantiate(b["type"])
        for k, v in b.get("params", {}).items():
            block.params[k] = v
        m.add_block(block, str(b["id"]), b.get("x", 0), b.get("y", 0))
    for c in d.get("connections", []):
        m.add_connection(str(c["from"]), int(c.get("from_port", 0)),
                         str(c["to"]), int(c.get("to_port", 0)))
    return m


class TestNumerical(unittest.TestCase):
    def test_integrator_ramp(self):
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
        m.add_block(blk("integrator"), "i", 100, 0)
        m.add_connection("c", 0, "i", 0)
        res = Engine(m, t_end=1.0, h=0.01).run()
        self.assertAlmostEqual(res["i"][-1][1], 1.0, places=9)
        # monotonic increasing
        ys = [v for _, v in res["i"]]
        self.assertTrue(all(b >= a for a, b in zip(ys, ys[1:])))

    def test_decay_rk4(self):
        m = Model()
        m.add_block(blk("integrator"), "i", 0, 0); m.blocks["i"].params["initial_value"] = 1.0
        m.add_block(blk("gain"), "g", 100, 0); m.blocks["g"].params["gain"] = -1.0
        m.add_connection("i", 0, "g", 0); m.add_connection("g", 0, "i", 0)
        res = Engine(m, t_end=1.0, h=0.001).run()
        self.assertAlmostEqual(res["i"][-1][1], math.exp(-1.0), places=6)

    def test_decay_euler(self):
        m = Model()
        m.add_block(blk("integrator"), "i", 0, 0); m.blocks["i"].params["initial_value"] = 1.0
        m.add_block(blk("gain"), "g", 100, 0); m.blocks["g"].params["gain"] = -1.0
        m.add_connection("i", 0, "g", 0); m.add_connection("g", 0, "i", 0)
        res = Engine(m, t_end=1.0, h=0.001, method="euler").run()
        # Euler: x_n = (1-h)^n ; at t=1, n=1000
        expected = (1 - 0.001) ** 1000
        self.assertAlmostEqual(res["i"][-1][1], expected, places=9)
        self.assertAlmostEqual(res["i"][-1][1], math.exp(-1.0), delta=5e-4)

    def test_delay_step(self):
        m = Model()
        m.add_block(blk("signal_generator"), "s", 0, 0)
        m.blocks["s"].params.update({"type": "step", "t0": 0.0, "amplitude": 1.0})
        m.add_block(blk("delay"), "d", 100, 0)
        m.add_connection("s", 0, "d", 0)
        res = Engine(m, t_end=0.03, h=0.01).run()
        dvals = [v for _, v in res["d"]]
        self.assertEqual(dvals, [0.0, 1.0, 1.0, 1.0])

    def test_delay_feedback_convergence(self):
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
        m.add_block(blk("addition"), "a", 0, 100)
        m.add_block(blk("delay"), "d", 100, 100)
        m.add_block(blk("gain"), "g", 200, 100); m.blocks["g"].params["gain"] = 0.5
        m.add_connection("c", 0, "a", 0)
        m.add_connection("g", 0, "a", 1)
        m.add_connection("a", 0, "d", 0)
        m.add_connection("d", 0, "g", 0)
        res = Engine(m, t_end=0.05, h=0.01).run()
        dvals = [v for _, v in res["d"]]
        self.assertAlmostEqual(dvals[0], 0.0, places=12)
        self.assertAlmostEqual(dvals[-1], 1.9375, places=9)

    def test_oscillator(self):
        m = Model()
        m.add_block(blk("integrator"), "i1", 0, 0); m.blocks["i1"].params["initial_value"] = 1.0
        m.add_block(blk("integrator"), "i2", 0, 100); m.blocks["i2"].params["initial_value"] = 0.0
        m.add_block(blk("gain"), "gn", 100, 100); m.blocks["gn"].params["gain"] = -1.0
        m.add_connection("i2", 0, "i1", 0)   # dx1/dt = x2
        m.add_connection("i1", 0, "gn", 0)   # -x1
        m.add_connection("gn", 0, "i2", 0)   # dx2/dt = -x1
        res = Engine(m, t_end=math.pi / 2, h=0.001).run()
        x1 = res["i1"][-1][1]; x2 = res["i2"][-1][1]
        self.assertAlmostEqual(x1, 0.0, delta=1e-3)
        self.assertAlmostEqual(x2, -1.0, delta=1e-3)

    def test_signal_generators(self):
        def run_gen(params, t_end, h=0.001):
            m = Model()
            m.add_block(blk("signal_generator"), "s", 0, 0)
            m.blocks["s"].params.update(params)
            return Engine(m, t_end=t_end, h=h).run()["s"]

        # sine at t where sin = 1
        s = run_gen({"type": "sine", "amplitude": 2.0, "frequency": 0.5, "phase": 0.0}, 0.5)
        self.assertAlmostEqual(s[-1][1], 2.0, places=6)  # sin(pi/2)=1 * amp 2
        # ramp
        r = run_gen({"type": "ramp", "slope": 3.0, "offset": 1.0}, 2.0)
        self.assertAlmostEqual(r[-1][1], 3.0 * 2.0 + 1.0, places=9)
        # step
        st = run_gen({"type": "step", "t0": 0.5, "amplitude": 4.0}, 1.0)
        self.assertAlmostEqual(st[0][1], 0.0, places=12)
        self.assertAlmostEqual(st[-1][1], 4.0, places=12)
        # square
        sq = run_gen({"type": "square", "amplitude": 1.0, "frequency": 0.5}, 0.5)
        self.assertAlmostEqual(sq[-1][1], 1.0, places=9)

    def test_arithmetic(self):
        m = Model()
        m.add_block(blk("constant"), "a", 0, 0); m.blocks["a"].params["value"] = 3.0
        m.add_block(blk("constant"), "b", 0, 100); m.blocks["b"].params["value"] = 4.0
        m.add_block(blk("addition"), "add", 100, 0)
        m.add_block(blk("multiplication"), "mul", 100, 100)
        m.add_block(blk("gain"), "g", 200, 0); m.blocks["g"].params["gain"] = 2.0
        m.add_connection("a", 0, "add", 0); m.add_connection("b", 0, "add", 1)
        m.add_connection("a", 0, "mul", 0); m.add_connection("b", 0, "mul", 1)
        m.add_connection("add", 0, "g", 0)
        res = Engine(m, t_end=0.1, h=0.05).run()
        self.assertAlmostEqual(res["add"][-1][1], 7.0, places=12)
        self.assertAlmostEqual(res["mul"][-1][1], 12.0, places=12)
        self.assertAlmostEqual(res["g"][-1][1], 14.0, places=12)

    def test_graph_display_records_input(self):
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 5.0
        m.add_block(blk("graph_display"), "gd", 100, 0)
        m.add_connection("c", 0, "gd", 0)
        res = Engine(m, t_end=0.2, h=0.1).run()
        self.assertAlmostEqual(res["gd"][-1][1], 5.0, places=12)

    def test_second_order_step_response(self):
        # constant(1) -> second_order (K=1, omega0=2, zeta=0.2): underdamped
        # step response. Peak must match the analytic value
        # 1 + exp(-zeta*omega0*pi/omega_d) at t = pi/omega_d.
        import math
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
        so = blk("second_order")
        so.params["K"] = 1.0; so.params["omega0"] = 2.0; so.params["zeta"] = 0.2
        m.add_block(so, "so", 100, 0)
        m.add_connection("c", 0, "so", 0)
        res = Engine(m, t_end=10.0, h=0.001, method="rk4").run()
        series = res["so"]
        zeta, omega0 = 0.2, 2.0
        omega_d = omega0 * math.sqrt(1.0 - zeta * zeta)
        t_peak = math.pi / omega_d
        y_peak = 1.0 + math.exp(-zeta * omega0 * t_peak)
        mx = max(v for _, v in series)
        self.assertAlmostEqual(mx, y_peak, places=3)
        # settles toward K=1 (analytic y(10) = 0.9840...)
        self.assertAlmostEqual(series[-1][1], 0.984015, places=3)


class TestCustomBlocks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = Library(blocks_dir=BLOCKS_DIR)

    def test_custom_blocks_loaded(self):
        names = self.lib.names()
        self.assertIn("saturator", names)
        self.assertIn("first_order", names)
        self.assertEqual(self.lib.load_errors, [])

    def test_saturator_clamp(self):
        m = Model()
        m.add_block(blk("signal_generator"), "s", 0, 0)
        m.blocks["s"].params.update({"type": "ramp", "slope": 10.0})
        m.add_block(self.lib.instantiate("saturator"), "sat", 100, 0)
        m.blocks["sat"].params["limit"] = 1.0
        m.add_connection("s", 0, "sat", 0)
        res = Engine(m, t_end=0.3, h=0.05).run()
        ys = [v for _, v in res["sat"]]
        self.assertTrue(all(-1.0 <= y <= 1.0 for y in ys))
        self.assertAlmostEqual(ys[-1], 1.0, places=12)  # ramp hit the limit

    def test_first_order_lowpass(self):
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
        m.add_block(self.lib.instantiate("first_order"), "fo", 100, 0)
        m.blocks["fo"].params.update({"tau": 1.0, "initial_value": 0.0})
        m.add_connection("c", 0, "fo", 0)
        res = Engine(m, t_end=1.0, h=0.001).run()
        self.assertAlmostEqual(res["fo"][-1][1], 1.0 - math.exp(-1.0), places=6)

    def test_custom_block_in_feedback_loop(self):
        # first_order in a feedback loop: dy/dt = (u - y)/tau with u = -y (via gain -1)
        # => dy/dt = (-y - y)/tau = -2y/tau  ->  y(t) = e^(-2t/tau)
        m = Model()
        m.add_block(self.lib.instantiate("first_order"), "fo", 0, 0)
        m.blocks["fo"].params.update({"tau": 1.0, "initial_value": 1.0})
        m.add_block(blk("gain"), "g", 100, 0); m.blocks["g"].params["gain"] = -1.0
        m.add_connection("fo", 0, "g", 0)
        m.add_connection("g", 0, "fo", 0)
        res = Engine(m, t_end=1.0, h=0.001).run()
        self.assertAlmostEqual(res["fo"][-1][1], math.exp(-2.0), places=6)


class TestAlgebraicLoopPolicy(unittest.TestCase):
    def test_rejected_gain_loop(self):
        m = Model()
        m.add_block(blk("gain"), "a", 0, 0); m.add_block(blk("gain"), "b", 100, 0)
        m.add_connection("a", 0, "b", 0); m.add_connection("b", 0, "a", 0)
        with self.assertRaises(AlgebraicLoopError):
            Engine(m, t_end=1.0, h=0.1)

    def test_rejected_self_gain_with_add(self):
        # gain -> addition -> gain cycle (all non-stateful)
        m = Model()
        m.add_block(blk("gain"), "g", 0, 0); m.blocks["g"].params["gain"] = 0.5
        m.add_block(blk("addition"), "a", 100, 0)
        m.add_connection("g", 0, "a", 0)
        m.add_connection("a", 0, "g", 0)
        with self.assertRaises(AlgebraicLoopError):
            Engine(m, t_end=1.0, h=0.1)

    def test_accepted_integrator_loop(self):
        m = Model()
        m.add_block(blk("integrator"), "i", 0, 0); m.blocks["i"].params["initial_value"] = 1.0
        m.add_block(blk("gain"), "g", 100, 0); m.blocks["g"].params["gain"] = -1.0
        m.add_connection("i", 0, "g", 0); m.add_connection("g", 0, "i", 0)
        res = Engine(m, t_end=1.0, h=0.01).run()  # must not raise
        self.assertAlmostEqual(res["i"][-1][1], math.exp(-1.0), places=5)

    def test_accepted_delay_loop(self):
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
        m.add_block(blk("delay"), "d", 100, 0)
        m.add_block(blk("gain"), "g", 200, 0); m.blocks["g"].params["gain"] = 0.5
        m.add_connection("c", 0, "d", 0)
        m.add_connection("d", 0, "g", 0)
        m.add_connection("g", 0, "d", 0)  # note: d has 1 input; this replaces c->d
        # Rebuild cleanly: d input = g output; g input = d output; c feeds g via add
        m2 = Model()
        m2.add_block(blk("constant"), "c", 0, 0); m2.blocks["c"].params["value"] = 1.0
        m2.add_block(blk("addition"), "a", 0, 100)
        m2.add_block(blk("delay"), "d", 100, 100)
        m2.add_block(blk("gain"), "g", 200, 100); m2.blocks["g"].params["gain"] = 0.5
        m2.add_connection("c", 0, "a", 0)
        m2.add_connection("g", 0, "a", 1)
        m2.add_connection("a", 0, "d", 0)
        m2.add_connection("d", 0, "g", 0)
        res = Engine(m2, t_end=0.05, h=0.01).run()  # must not raise
        self.assertAlmostEqual([v for _, v in res["d"]][-1], 1.9375, places=9)


class TestSaveLoad(unittest.TestCase):
    def test_round_trip(self):
        lib = Library(blocks_dir=BLOCKS_DIR)
        m = Model()
        m.add_block(blk("constant"), "c", 10, 20); m.blocks["c"].params["value"] = 2.5
        m.add_block(blk("integrator"), "i", 120, 20)
        m.add_block(blk("graph_display"), "gd", 240, 20)
        m.add_connection("c", 0, "i", 0)
        m.add_connection("i", 0, "gd", 0)
        d1 = m.to_dict()
        m2 = build_model(lib, d1)
        d2 = m2.to_dict()
        self.assertEqual(d1, d2)
        # and it still simulates correctly
        res = Engine(m2, t_end=1.0, h=0.01).run()
        self.assertAlmostEqual(res["i"][-1][1], 2.5, places=9)

    def test_round_trip_custom_block(self):
        lib = Library(blocks_dir=BLOCKS_DIR)
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
        m.add_block(lib.instantiate("first_order"), "fo", 100, 0)
        m.blocks["fo"].params.update({"tau": 0.5, "initial_value": 0.0})
        m.add_connection("c", 0, "fo", 0)
        d1 = m.to_dict()
        m2 = build_model(lib, d1)
        self.assertEqual(d1, m2.to_dict())
        res = Engine(m2, t_end=1.0, h=0.001).run()
        self.assertAlmostEqual(res["fo"][-1][1], 1.0 - math.exp(-2.0), places=6)


class TestErrorDiagnostics(unittest.TestCase):
    def test_unknown_method(self):
        m = Model(); m.add_block(blk("constant"), "c", 0, 0)
        with self.assertRaises(BlockError):
            Engine(m, t_end=1.0, h=0.1, method="bogus")

    def test_bad_step(self):
        m = Model(); m.add_block(blk("constant"), "c", 0, 0)
        with self.assertRaises(BlockError):
            Engine(m, t_end=1.0, h=0.0)

    def test_negative_t_end(self):
        m = Model(); m.add_block(blk("constant"), "c", 0, 0)
        with self.assertRaises(BlockError):
            Engine(m, t_end=-1.0, h=0.1)

    def test_empty_model(self):
        m = Model()
        with self.assertRaises(BlockError):
            Engine(m, t_end=1.0, h=0.1)

    def test_port_out_of_range(self):
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0)
        m.add_block(blk("gain"), "g", 100, 0)
        m.add_connection("c", 5, "g", 0)  # constant has 1 output
        with self.assertRaises(BlockError):
            m.validate()

    def test_multiple_sources_one_input(self):
        m = Model()
        m.add_block(blk("constant"), "a", 0, 0)
        m.add_block(blk("constant"), "b", 0, 100)
        m.add_block(blk("gain"), "g", 100, 0)
        m.add_connection("a", 0, "g", 0)
        m.add_connection("b", 0, "g", 0)  # second source to same input
        with self.assertRaises(BlockError):
            m.validate()

    def test_unknown_block_type(self):
        lib = Library()
        with self.assertRaises(BlockError):
            lib.get("does_not_exist")

    def test_non_scalar_output(self):
        class Bad(Block):
            name = "bad"; n_inputs = 0; n_outputs = 1
            def compute(self, t, inputs, params, state):
                return [1.0, 2.0]  # non-scalar
        m = Model(); m.add_block(Bad(), "b", 0, 0)
        with self.assertRaises(BlockError):
            Engine(m, t_end=0.1, h=0.05).run()

    def test_custom_block_exception_wrapped(self):
        class Boom(Block):
            name = "boom"; n_inputs = 1; n_outputs = 1
            def compute(self, t, inputs, params, state):
                raise ValueError("kaboom")
        m = Model()
        m.add_block(blk("constant"), "c", 0, 0); m.blocks["c"].params["value"] = 1.0
        m.add_block(Boom(), "b", 100, 0)
        m.add_connection("c", 0, "b", 0)
        with self.assertRaises(BlockError) as ctx:
            Engine(m, t_end=0.1, h=0.05).run()
        self.assertIn("kaboom", str(ctx.exception))

    def test_bad_custom_file_reported(self):
        import tempfile, textwrap
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "broken.py"), "w") as f:
                f.write(textwrap.dedent("""
                    from xcos_mini.core import Block
                    class X(Block):
                        name = "x"
                        def compute(self, t, inputs, params, state):
                            raise RuntimeError("nope")
                    undefined_name_reference  # triggers import error
                """))
            lib = Library(blocks_dir=td)
            self.assertEqual(len(lib.load_errors), 1)
            self.assertIn("broken.py", lib.load_errors[0][0])



# --------------------------------------------------------------------------- #
# Unified filesystem-driven block library
# --------------------------------------------------------------------------- #
EXPECTED_BLOCKS = ['absolute',
 'addition',
 'comparison',
 'constant',
 'controlled_switch',
 'counter',
 'dead_zone',
 'delay',
 'derivative',
 'divide',
 'experiment',
 'exponential',
 'filtered_derivative',
 'first_order',
 'gain',
 'graph_display',
 'graph_series2',
 'graph_series3',
 'graph_series4',
 'graph_xy',
 'graph_xyz',
 'integrator',
 'linear_extrapolator',
 'logical_not',
 'logical_operation',
 'manual_gate',
 'manual_switch',
 'model_time',
 'multiplication',
 'normal_noise',
 'objective',
 'optimizer',
 'pd',
 'pi',
 'pid',
 'piecewise',
 'polynomial',
 'quantizer',
 'rate_limiter',
 'real_integrator',
 'relay',
 'running_maximum',
 'running_minimum',
 'sample_hold',
 'saturator',
 'sawtooth',
 'second_order',
 'sign',
 'signal_generator',
 'sine',
 'splitter',
 'square_wave',
 'sr_trigger',
 'step',
 'subsystem',
 'subtract',
 'time_average',
 'transfer_function',
 'transport_delay',
 'uniform_noise',
 'weighted_sum']
EXPECTED_CATEGORIES = {'Discrete': ['linear_extrapolator', 'sample_hold'],
 'Dynamics': ['delay',
              'derivative',
              'filtered_derivative',
              'first_order',
              'integrator',
              'pd',
              'pi',
              'pid',
              'real_integrator',
              'second_order',
              'transfer_function',
              'transport_delay'],
 'Logic': ['comparison', 'logical_not', 'logical_operation', 'sr_trigger'],
 'Math': ['absolute',
          'addition',
          'divide',
          'gain',
          'multiplication',
          'sign',
          'splitter',
          'subtract',
          'weighted_sum'],
 'Nonlinear': ['dead_zone', 'quantizer', 'rate_limiter', 'relay', 'saturator'],
 'Optimization': ['objective', 'optimizer'],
 'Sources': ['constant',
             'exponential',
             'model_time',
             'normal_noise',
             'piecewise',
             'polynomial',
             'sawtooth',
             'signal_generator',
             'sine',
             'square_wave',
             'step',
             'uniform_noise'],
 'Statistics': ['counter',
                'running_maximum',
                'running_minimum',
                'time_average'],
 'Switches': ['controlled_switch', 'manual_gate', 'manual_switch'],
 'System': ['experiment', 'subsystem'],
 'Visualization': ['graph_display',
                   'graph_series2',
                   'graph_series3',
                   'graph_series4',
                   'graph_xy',
                   'graph_xyz']}


class TestUnifiedLibrary(unittest.TestCase):
    """One loader, one block per file, categories from directories."""

    def test_discovers_all_existing_blocks(self):
        lib = Library(blocks_dir=BLOCKS_DIR)
        self.assertEqual(lib.names(), EXPECTED_BLOCKS)
        self.assertEqual(lib.load_errors, [])

    def test_exactly_one_implementation_per_identifier(self):
        lib = Library(blocks_dir=BLOCKS_DIR)
        # No duplicate registrations and no load errors.
        self.assertEqual(len(lib.names()), len(set(lib.names())))
        self.assertEqual(lib.load_errors, [])
        # Each identifier resolves to a single class.
        for name in EXPECTED_BLOCKS:
            self.assertIs(lib.get(name), lib.get(name))

    def test_recursive_category_discovery(self):
        lib = Library(blocks_dir=BLOCKS_DIR)
        self.assertEqual(lib.categories(), EXPECTED_CATEGORIES)

    def test_add_new_category_and_block_without_core_changes(self):
        import tempfile, textwrap
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "MyCategory")
            os.makedirs(cat)
            with open(os.path.join(cat, "myblock.py"), "w") as f:
                f.write(textwrap.dedent("""
                    from xcos_mini.core import Block
                    class MyBlock(Block):
                        name = "myblock"
                        n_inputs = 1
                        n_outputs = 1
                        parameters = {"k": 2.0}
                        def compute(self, t, inputs, params, state):
                            return float(params["k"]) * float(inputs[0])
                """))
            lib = Library(blocks_dir=td)
            self.assertIn("myblock", lib.names())
            self.assertEqual(lib.categories(), {"MyCategory": ["myblock"]})
            self.assertEqual(lib.load_errors, [])
            # And it is usable through the same block contract.
            b = lib.instantiate("myblock")
            self.assertEqual(b.n_outputs, 1)
            self.assertEqual(b.compute(0.0, [2.0], {"k": 3.0}, []), 6.0)

    def test_remove_block_and_refresh(self):
        import tempfile, textwrap
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "Cat")
            os.makedirs(cat)
            def write_block(fname, name):
                with open(os.path.join(cat, fname), "w") as f:
                    f.write(textwrap.dedent(f"""
                        from xcos_mini.core import Block
                        class B(Block):
                            name = "{name}"
                            n_inputs = 0
                            n_outputs = 1
                            def compute(self, t, inputs, params, state):
                                return 1.0
                    """))
            write_block("alpha.py", "alpha")
            write_block("beta.py", "beta")
            lib = Library(blocks_dir=td)
            self.assertEqual(lib.names(), ["alpha", "beta"])
            # Remove one file, then refresh.
            os.remove(os.path.join(cat, "beta.py"))
            lib.reload_blocks_dir(td)
            self.assertEqual(lib.names(), ["alpha"])
            self.assertEqual(lib.load_errors, [])
            # No stale registration of the removed block.
            with self.assertRaises(BlockError):
                lib.get("beta")

    def test_relocate_block_keeps_identifier(self):
        import tempfile, textwrap
        with tempfile.TemporaryDirectory() as td:
            a = os.path.join(td, "CatA"); b = os.path.join(td, "CatB")
            os.makedirs(a); os.makedirs(b)
            src = textwrap.dedent("""
                from xcos_mini.core import Block
                class Mover(Block):
                    name = "mover"
                    n_inputs = 0
                    n_outputs = 1
                    def compute(self, t, inputs, params, state):
                        return 42.0
            """)
            with open(os.path.join(a, "mover.py"), "w") as f:
                f.write(src)
            lib = Library(blocks_dir=td)
            self.assertEqual(lib.categories(), {"CatA": ["mover"]})
            # Relocate the file to another category directory.
            os.rename(os.path.join(a, "mover.py"), os.path.join(b, "mover.py"))
            lib.reload_blocks_dir(td)
            self.assertIn("mover", lib.names())
            self.assertEqual(lib.categories(), {"CatB": ["mover"]})
            self.assertEqual(lib.load_errors, [])
            # Same identifier, same behaviour after the move.
            self.assertEqual(lib.instantiate("mover").compute(0.0, [], {}, []), 42.0)

    def test_duplicate_identifier_diagnostic(self):
        import tempfile, textwrap
        with tempfile.TemporaryDirectory() as td:
            a = os.path.join(td, "CatA"); b = os.path.join(td, "CatB")
            os.makedirs(a); os.makedirs(b)
            def write_block(path, name, value):
                with open(path, "w") as f:
                    f.write(textwrap.dedent(f"""
                        from xcos_mini.core import Block
                        class D(Block):
                            name = "{name}"
                            n_inputs = 0
                            n_outputs = 1
                            def compute(self, t, inputs, params, state):
                                return {value}
                    """))
            write_block(os.path.join(a, "dup.py"), "dup", "1.0")
            write_block(os.path.join(b, "dup2.py"), "dup", "2.0")
            lib = Library(blocks_dir=td)
            # Both files define 'dup': explicit diagnostic, first kept.
            self.assertEqual(len(lib.load_errors), 1)
            rel, msg = lib.load_errors[0]
            self.assertIn("duplicate block identifier 'dup'", msg)
            self.assertEqual(lib.names(), ["dup"])
            # The first definition (CatA/dup.py) wins.
            self.assertEqual(lib.instantiate("dup").compute(0.0, [], {}, []), 1.0)

    def test_broken_block_file_isolation(self):
        import tempfile, textwrap
        with tempfile.TemporaryDirectory() as td:
            cat = os.path.join(td, "Cat")
            os.makedirs(cat)
            with open(os.path.join(cat, "broken.py"), "w") as f:
                f.write("this is not valid python (((")
            with open(os.path.join(cat, "good.py"), "w") as f:
                f.write(textwrap.dedent("""
                    from xcos_mini.core import Block
                    class Good(Block):
                        name = "good"
                        n_inputs = 0
                        n_outputs = 1
                        def compute(self, t, inputs, params, state):
                            return 7.0
                """))
            lib = Library(blocks_dir=td)
            # The valid block still loads; the broken one is reported.
            self.assertEqual(lib.names(), ["good"])
            self.assertEqual(len(lib.load_errors), 1)
            self.assertIn("broken.py", lib.load_errors[0][0])
            self.assertEqual(lib.instantiate("good").compute(0.0, [], {}, []), 7.0)

    def test_saved_diagram_compatibility(self):
        # This fixture was saved against the old layout; it must
        # still load and execute unchanged.
        import json
        model_path = os.path.join(ROOT, "tests", "fixtures", "legacy_constant.json")
        with open(model_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        lib = Library(blocks_dir=BLOCKS_DIR)
        m = build_model(lib, d)
        self.assertEqual(len(m.blocks), 1)
        res = Engine(m, t_end=0.5, h=0.1).run()
        self.assertAlmostEqual(res["c"][-1][1], 2.0, places=12)

    def test_gui_category_hierarchy(self):
        # The server builds the GUI tree from Library.categories(); verify the
        # shape the frontend renders: bold category parents + block children.
        from xcos_mini.server import _build_library_tree
        lib = Library(blocks_dir=BLOCKS_DIR)
        tree = _build_library_tree(lib)
        self.assertEqual([n["name"] for n in tree],
                         sorted(EXPECTED_CATEGORIES))
        for node in tree:
            self.assertEqual(node["type"], "category")
            self.assertIsInstance(node["blocks"], list)
            for name in node["blocks"]:
                self.assertIn(name, EXPECTED_BLOCKS)
        # No filenames, paths, or built-in/custom sections leak into the tree.
        flat = json.dumps(tree)
        self.assertNotIn(".py", flat)
        self.assertNotIn("built-in", flat.lower())
        self.assertNotIn("custom", flat.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
