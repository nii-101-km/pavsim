"""Tests for variable port mappings (W023).

Verifies that in1/out1 terminals with a 'mapping' parameter correctly
set internal parameters or extract results, and that the invoke logic
uses the mapping when present.
"""
import json
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestPortMappingBackend(unittest.TestCase):
    """Test the invoke method's mapping support in engines/numerical.py."""

    def _make_adapter(self):
        from engines.numerical import NumericalEngineAdapter
        adapter = NumericalEngineAdapter(blocks_dir=str(PROJECT_ROOT / "blocks"))
        return adapter

    def test_invoke_with_param_mapping(self):
        """in1 with mapping='b2.k' should set gain block's k parameter."""
        adapter = self._make_adapter()
        if not adapter.available:
            self.skipTest("Numerical engine not available")

        # Model: constant(1) -> gain(k=2) -> graph_display
        # in1 maps to gain.k, out1 maps to graph_display
        model = {
            "blocks": [
                {"id": "b1", "type": "constant", "params": {"value": 1.0}, "x": 0, "y": 0},
                {"id": "b2", "type": "gain", "params": {"gain": 2.0}, "x": 100, "y": 0},
                {"id": "b3", "type": "graph_display", "params": {}, "x": 200, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {"name": "gain_val", "mapping": "b2.gain"}, "x": 0, "y": 100},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "result", "mapping": "b3"}, "x": 300, "y": 0},
            ],
            "connections": [
                {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0},
                {"from": "b2", "from_port": 0, "to": "b3", "to_port": 0},
            ],
        }

        # Invoke with gain_val=5.0 -> should set b2.k=5.0, output = 1.0*5.0 = 5.0
        result = adapter.invoke(model, {"gain_val": 5.0}, t_end=1.0, h=0.1, method="rk4")
        self.assertIn("outputs", result)
        self.assertIn("result", result["outputs"])
        # constant(1.0) * gain(k=5.0) = 5.0
        self.assertAlmostEqual(result["outputs"]["result"], 5.0, places=3)

    def test_invoke_with_param_mapping_different_values(self):
        """Different input values should produce different outputs via mapping."""
        adapter = self._make_adapter()
        if not adapter.available:
            self.skipTest("Numerical engine not available")

        model = {
            "blocks": [
                {"id": "b1", "type": "constant", "params": {"value": 1.0}, "x": 0, "y": 0},
                {"id": "b2", "type": "gain", "params": {"gain": 1.0}, "x": 100, "y": 0},
                {"id": "b3", "type": "graph_display", "params": {}, "x": 200, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {"name": "gain_val", "mapping": "b2.gain"}, "x": 0, "y": 100},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y", "mapping": "b3"}, "x": 300, "y": 0},
            ],
            "connections": [
                {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0},
                {"from": "b2", "from_port": 0, "to": "b3", "to_port": 0},
            ],
        }

        r1 = adapter.invoke(model, {"gain_val": 3.0}, t_end=1.0, h=0.1, method="rk4")
        r2 = adapter.invoke(model, {"gain_val": 7.0}, t_end=1.0, h=0.1, method="rk4")

        self.assertAlmostEqual(r1["outputs"]["y"], 3.0, places=3)
        self.assertAlmostEqual(r2["outputs"]["y"], 7.0, places=3)

    def test_invoke_without_mapping_still_works(self):
        """Signal injection (no mapping) should still work as before."""
        adapter = self._make_adapter()
        if not adapter.available:
            self.skipTest("Numerical engine not available")

        # in1 feeds gain.input (signal injection), out1 extracts from gain.output
        model = {
            "blocks": [
                {"id": "b2", "type": "gain", "params": {"gain": 2.0}, "x": 100, "y": 0},
                {"id": "b3", "type": "graph_display", "params": {}, "x": 200, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}, "x": 0, "y": 0},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y"}, "x": 300, "y": 0},
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "b2", "to_port": 0},
                {"from": "b2", "from_port": 0, "to": "b3", "to_port": 0},
                {"from": "b3", "from_port": 0, "to": "out1", "to_port": 0},
            ],
        }

        result = adapter.invoke(model, {"u": 4.0}, t_end=1.0, h=0.1, method="rk4")
        self.assertIn("outputs", result)
        self.assertIn("y", result["outputs"])
        # u=4.0 * k=2.0 = 8.0
        self.assertAlmostEqual(result["outputs"]["y"], 8.0, places=3)

    def test_invoke_missing_input_rejected(self):
        """Missing required input must be rejected even with mapping."""
        adapter = self._make_adapter()
        if not adapter.available:
            self.skipTest("Numerical engine not available")

        model = {
            "blocks": [
                {"id": "b2", "type": "gain", "params": {"gain": 1.0}, "x": 100, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {"name": "gain_val", "mapping": "b2.gain"}, "x": 0, "y": 0},
            ],
            "connections": [],
        }

        with self.assertRaises(ValueError) as ctx:
            adapter.invoke(model, {}, t_end=1.0, h=0.1, method="rk4")
        self.assertIn("gain_val", str(ctx.exception))

    def test_invoke_no_stale_reuse(self):
        """After a successful invoke, a second invoke with missing input must fail."""
        adapter = self._make_adapter()
        if not adapter.available:
            self.skipTest("Numerical engine not available")

        model = {
            "blocks": [
                {"id": "b1", "type": "constant", "params": {"value": 1.0}, "x": 0, "y": 0},
                {"id": "b2", "type": "gain", "params": {"gain": 1.0}, "x": 100, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {"name": "gain_val", "mapping": "b2.gain"}, "x": 0, "y": 100},
            ],
            "connections": [
                {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0},
            ],
        }

        # First invoke succeeds
        r1 = adapter.invoke(model, {"gain_val": 5.0}, t_end=1.0, h=0.1, method="rk4")
        self.assertIn("results", r1)

        # Second invoke with missing input must fail (no stale reuse)
        with self.assertRaises(ValueError):
            adapter.invoke(model, {}, t_end=1.0, h=0.1, method="rk4")


class TestPortMappingServer(unittest.TestCase):
    """Test that the server's block definitions include mapping param."""

    def test_in1_has_mapping_param(self):
        from shell.server import _shell_builtin_blocks
        blocks = {b["name"]: b for b in _shell_builtin_blocks()}
        self.assertIn("mapping", blocks["in1_terminal"]["parameters"])
        self.assertIn("mapping", blocks["in1_terminal"]["parameter_labels"])

    def test_out1_has_mapping_param(self):
        from shell.server import _shell_builtin_blocks
        blocks = {b["name"]: b for b in _shell_builtin_blocks()}
        self.assertIn("mapping", blocks["out1_terminal"]["parameters"])
        self.assertIn("mapping", blocks["out1_terminal"]["parameter_labels"])


if __name__ == "__main__":
    unittest.main()
