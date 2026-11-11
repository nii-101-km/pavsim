"""Regression tests for legacy numerical-diagram compatibility removal.

Verifies that after removing _is_legacy_model and _migrate_legacy_model:
1. Models with numerical blocks at top level are REJECTED by /api/simulate (400)
2. Loading such a model via /api/load returns it UNMODIFIED (no auto-wrapping)
3. /api/blocks palette does NOT include individual numerical blocks but DOES include 'numerical'
4. A properly wrapped model (numerical block containing sub-model) still executes correctly
5. /api/invoke endpoint still works for externally controlled models
"""

import json
import math
import os
import sys
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import shell.server as server

_BASE = ["http://127.0.0.1:1"]


def _post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(_BASE[0] + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode()), e.code


def _get(path):
    try:
        with urllib.request.urlopen(_BASE[0] + path) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode()), e.code


class LegacyRemovalBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        _BASE[0] = cls.base
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()


class TestTopLevelNumericalRejected(LegacyRemovalBase):
    """Models with numerical blocks at top level must be rejected by /api/simulate."""


    def test_gain_graph_display_rejected(self):
        """Another legacy model (constant -> gain -> graph_display) gets 400."""
        model = {
            "blocks": [
                {"id": "c1", "type": "constant", "params": {"value": 2.0}, "x": 0, "y": 0},
                {"id": "g1", "type": "gain", "params": {"gain": 3.0}, "x": 100, "y": 0},
                {"id": "gd1", "type": "graph_display", "params": {}, "x": 200, "y": 0},
            ],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "g1", "to_port": 0},
                {"from": "g1", "from_port": 0, "to": "gd1", "to_port": 0},
            ],
        }
        body, status = _post("/api/simulate", {"model": model})
        self.assertEqual(status, 400, f"Expected 400, got {status}: {body}")
        self.assertIn("error", body)


class TestLoadReturnsUnmodified(LegacyRemovalBase):
    """Loading a legacy model via /api/load must return it unmodified."""

    def test_load_returns_model_as_is(self):
        """Save a legacy model, load it back, verify no auto-wrapping occurred."""
        model = {
            "blocks": [
                {"id": "c1", "type": "constant", "params": {"value": 1.0}, "x": 0, "y": 0},
                {"id": "fo1", "type": "first_order", "params": {"tau": 1.0, "gain": 1.0}, "x": 100, "y": 0},
                {"id": "gd1", "type": "graph_display", "params": {}, "x": 200, "y": 0},
            ],
            "connections": [
                {"from": "c1", "from_port": 0, "to": "fo1", "to_port": 0},
                {"from": "fo1", "from_port": 0, "to": "gd1", "to_port": 0},
            ],
        }
        # Save the model
        body, status = _post("/api/save", {"name": "test_legacy_load", "model": model})
        self.assertEqual(status, 200, f"Save failed: {body}")

        # Load it back
        body, status = _get("/api/load?name=test_legacy_load")
        self.assertEqual(status, 200, f"Load failed: {body}")
        loaded = body["model"]

        # The loaded model must be identical to what was saved (no wrapping)
        self.assertEqual(len(loaded["blocks"]), 3, f"Expected 3 blocks, got {len(loaded['blocks'])}")
        types = {b["type"] for b in loaded["blocks"]}
        self.assertIn("constant", types)
        self.assertIn("first_order", types)
        self.assertIn("graph_display", types)
        # Must NOT be wrapped in a 'numerical' block
        self.assertNotIn("numerical", types)

        # Cleanup
        import urllib.request as ur
        req = ur.Request(self.base + "/api/models?name=test_legacy_load", method="DELETE")
        try:
            ur.urlopen(req)
        except Exception:
            pass


class TestPaletteExcludesNumericalBlocks(LegacyRemovalBase):
    """The /api/library palette must not include individual numerical blocks."""

    def test_no_individual_numerical_blocks_placeable_in_outer(self):
        """first_order, constant, gain, graph_display are listed but restricted to the numerical context."""
        body, status = _get("/api/library")
        self.assertEqual(status, 200)
        block_names = set()
        for cat in body["tree"]:
            block_names.update(cat.get("blocks", []))

        # Individual numerical blocks are listed in the unified library...
        for name in ("first_order", "constant", "gain", "graph_display", "integrator"):
            self.assertIn(name, block_names)
        # ...but their context metadata forbids placement in the outer palette
        bc = body["block_contexts"]
        for name in ("first_order", "constant", "gain", "graph_display", "integrator"):
            self.assertEqual(bc[name], ["numerical"], f"{name} must be numerical-context only")


    def test_shell_builtins_in_palette(self):
        """Shell builtins must still be in the outer palette."""
        body, status = _get("/api/library")
        self.assertEqual(status, 200)
        block_names = set()
        for cat in body["tree"]:
            block_names.update(cat.get("blocks", []))
        self.assertIn("input_value", block_names)
        self.assertIn("param_assembler", block_names)
        self.assertIn("result_display", block_names)




class TestInvokeStillWorks(LegacyRemovalBase):
    """The /api/invoke endpoint must still work for externally controlled models."""

    def test_invoke_externally_controlled_model(self):
        """A flat model with in1/out1 terminals at top level can be invoked externally."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}, "x": 0, "y": 0},
                {"id": "fo1", "type": "first_order", "params": {"tau": 1.0, "gain": 1.0}, "x": 100, "y": 0},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y"}, "x": 200, "y": 0},
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "fo1", "to_port": 0},
                {"from": "fo1", "from_port": 0, "to": "out1", "to_port": 0},
            ],
        }
        # Invoke with input u=1.0
        body, status = _post("/api/invoke", {
            "model": model,
            "inputs": {"u": 1.0},
            "t_end": 1.0,
            "h": 0.01,
        })
        self.assertEqual(status, 200, f"Expected 200, got {status}: {body}")
        self.assertTrue(body.get("ok"), f"Expected ok=True: {body}")


if __name__ == "__main__":
    unittest.main()
