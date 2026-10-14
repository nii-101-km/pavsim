"""Numerical equivalence tests for Subsystem expansion.
Run with:  python3 -m unittest discover -s tests -v"""
import os, sys, math, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xcos_mini.core import Model, Engine, Library, BlockError, AlgebraicLoopError
from xcos_mini.subsystem import expand_subsystems
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS_DIR = os.path.join(ROOT, "blocks")
LIB = Library(blocks_dir=BLOCKS_DIR)
TOL = 1e-10

def build_flat(d):
    m = Model()
    for b in d.get("blocks", []):
        block = LIB.instantiate(b["type"])
        for k, v in b.get("params", {}).items(): block.params[k] = v
        m.add_block(block, str(b["id"]), b.get("x", 0), b.get("y", 0))
    for c in d.get("connections", []):
        m.add_connection(str(c["from"]), int(c.get("from_port", 0)), str(c["to"]), int(c.get("to_port", 0)))
    return m

def build_sub(d):
    flat = expand_subsystems(d)
    m = Model()
    for b in flat.get("blocks", []):
        block = LIB.instantiate(b["type"])
        for k, v in b.get("params", {}).items(): block.params[k] = v
        m.add_block(block, str(b["id"]), b.get("x", 0), b.get("y", 0))
    for c in flat.get("connections", []):
        m.add_connection(str(c["from"]), int(c.get("from_port", 0)), str(c["to"]), int(c.get("to_port", 0)))
    return m

def run(m, t=1.0, h=0.01, method="rk4"): return Engine(m, t_end=t, h=h, method=method).run()

def aser(tc, sa, sb, tol=TOL):
    tc.assertEqual(len(sa), len(sb), "length mismatch")
    mx = max(abs(a[1]-b[1]) for a,b in zip(sa,sb))
    tc.assertLessEqual(mx, tol, f"max diff {mx} > {tol}")

def ig(k):
    """Internal diagram: In1 -> gain(k) -> Out1"""
    return {"blocks": [
        {"id": "In1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
        {"id": "b1", "type": "gain", "params": {"gain": k}, "x": 100, "y": 0},
        {"id": "Out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
    ], "connections": [
        {"from": "In1", "from_port": 0, "to": "b1", "to_port": 0},
        {"from": "b1", "from_port": 0, "to": "Out1", "to_port": 0}
    ]}

def ifo(tau, gain=1.0):
    """Internal diagram: In1 -> [gain(gain)] -> first_order(tau) -> Out1"""
    if gain == 1.0:
        return {"blocks": [
            {"id": "In1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
            {"id": "b1", "type": "first_order", "params": {"tau": tau}, "x": 100, "y": 0},
            {"id": "Out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
        ], "connections": [
            {"from": "In1", "from_port": 0, "to": "b1", "to_port": 0},
            {"from": "b1", "from_port": 0, "to": "Out1", "to_port": 0}
        ]}
    else:
        return {"blocks": [
            {"id": "In1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
            {"id": "g1", "type": "gain", "params": {"gain": gain}, "x": 50, "y": 0},
            {"id": "b1", "type": "first_order", "params": {"tau": tau}, "x": 150, "y": 0},
            {"id": "Out1", "type": "out1_terminal", "params": {}, "x": 250, "y": 0}
        ], "connections": [
            {"from": "In1", "from_port": 0, "to": "g1", "to_port": 0},
            {"from": "g1", "from_port": 0, "to": "b1", "to_port": 0},
            {"from": "b1", "from_port": 0, "to": "Out1", "to_port": 0}
        ]}

def iid():
    """Identity internal diagram: In1 -> Out1"""
    return {"blocks": [
        {"id": "In1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
        {"id": "Out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
    ], "connections": [
        {"from": "In1", "from_port": 0, "to": "Out1", "to_port": 0}
    ]}

class TestIdentity(unittest.TestCase):
    def test_identity_rk4(self):
        fd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 5.0}},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 5.0}},
                         {"id": "s1", "type": "subsystem", "params": {}, "internal": iid()},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                               {"from": "s1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 1.0, 0.01, "rk4")
        rs = run(build_sub(sd), 1.0, 0.01, "rk4")
        aser(self, rf["gd"], rs["gd"])
        self.assertAlmostEqual(rs["gd"][-1][1], 5.0, places=9)

    def test_identity_euler(self):
        fd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 3.0}},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 3.0}},
                         {"id": "s1", "type": "subsystem", "params": {}, "internal": iid()},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                               {"from": "s1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 0.5, 0.01, "euler")
        rs = run(build_sub(sd), 0.5, 0.01, "euler")
        aser(self, rf["gd"], rs["gd"])

class TestGain(unittest.TestCase):
    def test_gain_rk4(self):
        fd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 4.0}},
                         {"id": "g1", "type": "gain", "params": {"gain": 2.5}},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "g1", "to_port": 0},
                               {"from": "g1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 4.0}},
                         {"id": "s1", "type": "subsystem", "params": {}, "internal": ig(2.5)},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                               {"from": "s1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 1.0, 0.01, "rk4")
        rs = run(build_sub(sd), 1.0, 0.01, "rk4")
        aser(self, rf["gd"], rs["gd"])
        self.assertAlmostEqual(rs["gd"][-1][1], 10.0, places=9)

    def test_gain_euler(self):
        fd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 2.0}},
                         {"id": "g1", "type": "gain", "params": {"gain": -1.5}},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "g1", "to_port": 0},
                               {"from": "g1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 2.0}},
                         {"id": "s1", "type": "subsystem", "params": {}, "internal": ig(-1.5)},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                               {"from": "s1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 0.5, 0.01, "euler")
        rs = run(build_sub(sd), 0.5, 0.01, "euler")
        aser(self, rf["gd"], rs["gd"])
        self.assertAlmostEqual(rs["gd"][-1][1], -3.0, places=9)

class TestFirstOrder(unittest.TestCase):
    def test_rk4(self):
        # In1 -> gain(2.0) -> first_order(tau=0.5) -> Out1
        # Flat: c1(1.0) -> g1(gain=2.0) -> fo1(tau=0.5) -> gd
        # y(t) = 2.0 * (1 - exp(-t/0.5))
        fd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 1.0}},
                         {"id": "g1", "type": "gain", "params": {"gain": 2.0}},
                         {"id": "fo1", "type": "first_order", "params": {"tau": 0.5}},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "g1", "to_port": 0},
                               {"from": "g1", "from_port": 0, "to": "fo1", "to_port": 0},
                               {"from": "fo1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 1.0}},
                         {"id": "s1", "type": "subsystem", "params": {}, "internal": ifo(0.5, 2.0)},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                               {"from": "s1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 2.0, 0.01, "rk4")
        rs = run(build_sub(sd), 2.0, 0.01, "rk4")
        aser(self, rf["gd"], rs["gd"])
        expected = 2.0 * (1 - math.exp(-2.0 / 0.5))
        self.assertAlmostEqual(rs["gd"][-1][1], expected, places=5)

    def test_euler(self):
        # In1 -> first_order(tau=1.0) -> Out1
        # Flat: c1(1.0) -> fo1(tau=1.0) -> gd
        fd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 1.0}},
                         {"id": "fo1", "type": "first_order", "params": {"tau": 1.0}},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "fo1", "to_port": 0},
                               {"from": "fo1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [{"id": "c1", "type": "constant", "params": {"value": 1.0}},
                         {"id": "s1", "type": "subsystem", "params": {}, "internal": ifo(1.0)},
                         {"id": "gd", "type": "graph_display", "params": {}}],
              "connections": [{"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                               {"from": "s1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 1.0, 0.01, "euler")
        rs = run(build_sub(sd), 1.0, 0.01, "euler")
        aser(self, rf["gd"], rs["gd"])

class TestTwoIndependent(unittest.TestCase):
    def test_same_local_ids(self):
        sd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "s1", "type": "subsystem", "params": {}, "internal": ig(2.0)},
            {"id": "s2", "type": "subsystem", "params": {}, "internal": ig(5.0)},
            {"id": "gd1", "type": "graph_display", "params": {}},
            {"id": "gd2", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                {"from": "c1", "from_port": 0, "to": "s2", "to_port": 0},
                {"from": "s1", "from_port": 0, "to": "gd1", "to_port": 0},
                {"from": "s2", "from_port": 0, "to": "gd2", "to_port": 0}]}
        rs = run(build_sub(sd), 1.0, 0.01, "rk4")
        self.assertAlmostEqual(rs["gd1"][-1][1], 2.0, places=9)
        self.assertAlmostEqual(rs["gd2"][-1][1], 5.0, places=9)
        self.assertIn("s1/b1", rs)
        self.assertIn("s2/b1", rs)
        self.assertAlmostEqual(rs["s1/b1"][-1][1], 2.0, places=9)
        self.assertAlmostEqual(rs["s2/b1"][-1][1], 5.0, places=9)

class TestSeries(unittest.TestCase):
    def test_series_rk4(self):
        # c1(2.0) -> s1(gain 3.0) -> s2(gain 4.0) -> gd => 2*3*4 = 24
        fd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 2.0}},
            {"id": "g1", "type": "gain", "params": {"gain": 3.0}},
            {"id": "g2", "type": "gain", "params": {"gain": 4.0}},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "g1", "to_port": 0},
                {"from": "g1", "from_port": 0, "to": "g2", "to_port": 0},
                {"from": "g2", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 2.0}},
            {"id": "s1", "type": "subsystem", "params": {}, "internal": ig(3.0)},
            {"id": "s2", "type": "subsystem", "params": {}, "internal": ig(4.0)},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                {"from": "s1", "from_port": 0, "to": "s2", "to_port": 0},
                {"from": "s2", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 1.0, 0.01, "rk4")
        rs = run(build_sub(sd), 1.0, 0.01, "rk4")
        aser(self, rf["gd"], rs["gd"])
        self.assertAlmostEqual(rs["gd"][-1][1], 24.0, places=9)

    def test_series_stateful_rk4(self):
        # c1(1.0) -> s1(first_order tau=1.0) -> s2(gain 2.0) -> gd
        # y(t) = 2.0 * (1 - exp(-t))
        fd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "fo1", "type": "first_order", "params": {"tau": 1.0}},
            {"id": "g1", "type": "gain", "params": {"gain": 2.0}},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "fo1", "to_port": 0},
                {"from": "fo1", "from_port": 0, "to": "g1", "to_port": 0},
                {"from": "g1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "s1", "type": "subsystem", "params": {}, "internal": ifo(1.0)},
            {"id": "s2", "type": "subsystem", "params": {}, "internal": ig(2.0)},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                {"from": "s1", "from_port": 0, "to": "s2", "to_port": 0},
                {"from": "s2", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 2.0, 0.01, "rk4")
        rs = run(build_sub(sd), 2.0, 0.01, "rk4")
        aser(self, rf["gd"], rs["gd"])
        expected = 2.0 * (1 - math.exp(-2.0))
        self.assertAlmostEqual(rs["gd"][-1][1], expected, places=5)

class TestFanOut(unittest.TestCase):
    def test_fanout_rk4(self):
        sd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 3.0}},
            {"id": "s1", "type": "subsystem", "params": {}, "internal": ig(2.0)},
            {"id": "s2", "type": "subsystem", "params": {}, "internal": ig(5.0)},
            {"id": "gd1", "type": "graph_display", "params": {}},
            {"id": "gd2", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                {"from": "c1", "from_port": 0, "to": "s2", "to_port": 0},
                {"from": "s1", "from_port": 0, "to": "gd1", "to_port": 0},
                {"from": "s2", "from_port": 0, "to": "gd2", "to_port": 0}]}
        rs = run(build_sub(sd), 1.0, 0.01, "rk4")
        self.assertAlmostEqual(rs["gd1"][-1][1], 6.0, places=9)
        self.assertAlmostEqual(rs["gd2"][-1][1], 15.0, places=9)

class TestFeedback(unittest.TestCase):
    def test_feedback_rk4(self):
        # c1(1.0) -> add1(0); int1 -> sf(gain -1.0) -> add1(1); add1 -> int1
        # dy/dt = 1 + (-1)*y = 1 - y => y(t) = 1 - exp(-t)
        fd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "int1", "type": "integrator", "params": {}},
            {"id": "gn", "type": "gain", "params": {"gain": -1.0}},
            {"id": "add1", "type": "addition", "params": {}},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "add1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "gn", "to_port": 0},
                {"from": "gn", "from_port": 0, "to": "add1", "to_port": 1},
                {"from": "add1", "from_port": 0, "to": "int1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "int1", "type": "integrator", "params": {}},
            {"id": "sf", "type": "subsystem", "params": {}, "internal": ig(-1.0)},
            {"id": "add1", "type": "addition", "params": {}},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "add1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "sf", "to_port": 0},
                {"from": "sf", "from_port": 0, "to": "add1", "to_port": 1},
                {"from": "add1", "from_port": 0, "to": "int1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 2.0, 0.01, "rk4")
        rs = run(build_sub(sd), 2.0, 0.01, "rk4")
        aser(self, rf["gd"], rs["gd"])
        expected = 1.0 - math.exp(-2.0)
        self.assertAlmostEqual(rs["gd"][-1][1], expected, places=5)

    def test_feedback_euler(self):
        fd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "int1", "type": "integrator", "params": {}},
            {"id": "gn", "type": "gain", "params": {"gain": -1.0}},
            {"id": "add1", "type": "addition", "params": {}},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "add1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "gn", "to_port": 0},
                {"from": "gn", "from_port": 0, "to": "add1", "to_port": 1},
                {"from": "add1", "from_port": 0, "to": "int1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "gd", "to_port": 0}]}
        sd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "int1", "type": "integrator", "params": {}},
            {"id": "sf", "type": "subsystem", "params": {}, "internal": ig(-1.0)},
            {"id": "add1", "type": "addition", "params": {}},
            {"id": "gd", "type": "graph_display", "params": {}}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "add1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "sf", "to_port": 0},
                {"from": "sf", "from_port": 0, "to": "add1", "to_port": 1},
                {"from": "add1", "from_port": 0, "to": "int1", "to_port": 0},
                {"from": "int1", "from_port": 0, "to": "gd", "to_port": 0}]}
        rf = run(build_flat(fd), 2.0, 0.01, "euler")
        rs = run(build_sub(sd), 2.0, 0.01, "euler")
        aser(self, rf["gd"], rs["gd"])

class TestValidation(unittest.TestCase):
    def test_algebraic_loop_rejected(self):
        # g1 -> s1(gain 3.0) -> g2(gain -1.0) -> g1: all non-stateful => algebraic loop
        sd = {"blocks": [
            {"id": "g1", "type": "gain", "params": {"gain": 2.0}},
            {"id": "s1", "type": "subsystem", "params": {}, "internal": ig(3.0)},
            {"id": "g2", "type": "gain", "params": {"gain": -1.0}}],
            "connections": [
                {"from": "g1", "from_port": 0, "to": "s1", "to_port": 0},
                {"from": "s1", "from_port": 0, "to": "g2", "to_port": 0},
                {"from": "g2", "from_port": 0, "to": "g1", "to_port": 0}]}
        m = build_sub(sd)
        with self.assertRaises((AlgebraicLoopError, BlockError)):
            m.validate()

    def test_multiple_sources_rejected(self):
        sd = {"blocks": [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}},
            {"id": "c2", "type": "constant", "params": {"value": 2.0}},
            {"id": "s1", "type": "subsystem", "params": {}, "internal": iid()}],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "s1", "to_port": 0},
                {"from": "c2", "from_port": 0, "to": "s1", "to_port": 0}]}
        with self.assertRaises(BlockError):
            build_sub(sd)


class TestBoundaryValidation(unittest.TestCase):
    """Validation tests for subsystem boundary edge cases."""

    def test_fanout_internal(self):
        """In1 fans out to two gains, summed -> Out1. Output = sum of both."""
        d = {
            "blocks": [
                {"id": "c", "type": "constant", "x": 0, "y": 0, "params": {"value": 1}},
                {"id": "s", "type": "subsystem", "x": 100, "y": 0, "params": {}, "internal": {
                    "blocks": [
                        {"id": "In1", "type": "in1_terminal", "x": 0, "y": 0, "params": {}},
                        {"id": "Out1", "type": "out1_terminal", "x": 200, "y": 0, "params": {}},
                        {"id": "a", "type": "gain", "x": 50, "y": -50, "params": {"gain": 2}},
                        {"id": "b", "type": "gain", "x": 50, "y": 50, "params": {"gain": 3}},
                        {"id": "sum", "type": "addition", "x": 150, "y": 0, "params": {}}
                    ],
                    "connections": [
                        {"from": "In1", "from_port": 0, "to": "a", "to_port": 0},
                        {"from": "In1", "from_port": 0, "to": "b", "to_port": 0},
                        {"from": "a", "from_port": 0, "to": "sum", "to_port": 0},
                        {"from": "b", "from_port": 0, "to": "sum", "to_port": 1},
                        {"from": "sum", "from_port": 0, "to": "Out1", "to_port": 0}
                    ]
                }},
                {"id": "g", "type": "graph_display", "x": 200, "y": 0, "params": {}}
            ],
            "connections": [
                {"from": "c", "from_port": 0, "to": "s", "to_port": 0},
                {"from": "s", "from_port": 0, "to": "g", "to_port": 0}
            ]
        }
        m = build_sub(d)
        r = run(m)
        # 1*2 + 1*3 = 5
        self.assertAlmostEqual(r["g"][-1][1], 5.0, places=9)

    def test_broken_subsystem_no_path(self):
        """Subsystem with In1/Out1 but no connections must raise BlockError."""
        d = {
            "blocks": [
                {"id": "c", "type": "constant", "x": 0, "y": 0, "params": {"value": 1}},
                {"id": "s", "type": "subsystem", "x": 100, "y": 0, "params": {}, "internal": {
                    "blocks": [
                        {"id": "In1", "type": "in1_terminal", "x": 0, "y": 0, "params": {}},
                        {"id": "Out1", "type": "out1_terminal", "x": 200, "y": 0, "params": {}}
                    ],
                    "connections": []
                }},
                {"id": "g", "type": "graph_display", "x": 200, "y": 0, "params": {}}
            ],
            "connections": [
                {"from": "c", "from_port": 0, "to": "s", "to_port": 0},
                {"from": "s", "from_port": 0, "to": "g", "to_port": 0}
            ]
        }
        from xcos_mini.core import BlockError
        with self.assertRaises(BlockError) as ctx:
            build_sub(d)
        self.assertIn("In1", str(ctx.exception))

    def test_multiple_sources_to_out1(self):
        """Two blocks feeding Out1 must raise BlockError."""
        d = {
            "blocks": [
                {"id": "c", "type": "constant", "x": 0, "y": 0, "params": {"value": 1}},
                {"id": "s", "type": "subsystem", "x": 100, "y": 0, "params": {}, "internal": {
                    "blocks": [
                        {"id": "In1", "type": "in1_terminal", "x": 0, "y": 0, "params": {}},
                        {"id": "Out1", "type": "out1_terminal", "x": 200, "y": 0, "params": {}},
                        {"id": "a", "type": "gain", "x": 50, "y": -50, "params": {"gain": 2}},
                        {"id": "b", "type": "gain", "x": 50, "y": 50, "params": {"gain": 3}}
                    ],
                    "connections": [
                        {"from": "In1", "from_port": 0, "to": "a", "to_port": 0},
                        {"from": "In1", "from_port": 0, "to": "b", "to_port": 0},
                        {"from": "a", "from_port": 0, "to": "Out1", "to_port": 0},
                        {"from": "b", "from_port": 0, "to": "Out1", "to_port": 0}
                    ]
                }},
                {"id": "g", "type": "graph_display", "x": 200, "y": 0, "params": {}}
            ],
            "connections": [
                {"from": "c", "from_port": 0, "to": "s", "to_port": 0},
                {"from": "s", "from_port": 0, "to": "g", "to_port": 0}
            ]
        }
        from xcos_mini.core import BlockError
        with self.assertRaises(BlockError) as ctx:
            build_sub(d)
        self.assertIn("Out1", str(ctx.exception))

    def test_in1_direct_wire_plus_gain_to_out1_rejected(self):
        """In1->gain->Out1 AND In1->Out1 (direct wire) must raise BlockError.

        The direct In1->Out1 wire counts as a second source on Out1,
        which is a multiple-sources violation.
        """
        d = {
            "blocks": [
                {"id": "c", "type": "constant", "x": 0, "y": 0, "params": {"value": 1}},
                {"id": "s", "type": "subsystem", "x": 100, "y": 0, "params": {}, "internal": {
                    "blocks": [
                        {"id": "In1", "type": "in1_terminal", "x": 0, "y": 0, "params": {}},
                        {"id": "Out1", "type": "out1_terminal", "x": 200, "y": 0, "params": {}},
                        {"id": "g", "type": "gain", "x": 100, "y": 0, "params": {"gain": 2}}
                    ],
                    "connections": [
                        {"from": "In1", "from_port": 0, "to": "g", "to_port": 0},
                        {"from": "g", "from_port": 0, "to": "Out1", "to_port": 0},
                        {"from": "In1", "from_port": 0, "to": "Out1", "to_port": 0}
                    ]
                }},
                {"id": "gd", "type": "graph_display", "x": 200, "y": 0, "params": {}}
            ],
            "connections": [
                {"from": "c", "from_port": 0, "to": "s", "to_port": 0},
                {"from": "s", "from_port": 0, "to": "gd", "to_port": 0}
            ]
        }
        from xcos_mini.core import BlockError
        with self.assertRaises(BlockError) as ctx:
            build_sub(d)
        msg = str(ctx.exception)
        self.assertIn("Out1", msg)
        self.assertIn("sources", msg)
