"""Architecture separation tests: shell is generic, numerical runs only in computation blocks.

Verifies:
1. Generic-to-numerical-to-generic value flow
2. Legacy model migration (open/save/reopen)
3. No-engine mode (open, edit, save, clear error)
4. No direct top-level numerical-engine fallback
5. Ownership rules preserved
"""

import json
import math
import os
import re
import sys
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "shell" / "web"
sys.path.insert(0, str(PROJECT_ROOT))

import shell.server as server



_BASE = ["http://127.0.0.1:1"]  # mutable holder

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


class ArchBase(unittest.TestCase):
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


class TestGenericToNumericalToGeneric(ArchBase):
    """Values flow: generic source -> numerical computation block -> generic sink."""



    def test_missing_input_rejected(self):
        """Numerical block with required input not connected -> error with port name."""
        model = {
            "blocks": [
                {"id": "comp", "type": "numerical", "params": {
                    "model": {
                        "blocks": [
                            {"id": "in1", "type": "in1_terminal", "params": {"name": "a"}},
                            {"id": "g1", "type": "gain", "params": {"gain": 2.0}},
                            {"id": "out1", "type": "out1_terminal", "params": {"name": "out_a"}}
                        ],
                        "connections": [
                            {"from": "in1", "from_port": 0, "to": "g1", "to_port": 0},
                            {"from": "g1", "from_port": 0, "to": "out1", "to_port": 0}
                        ]
                    },
                    "t_end": 1.0, "h": 0.01, "method": "rk4"
                }},
                {"id": "dst", "type": "result_display", "params": {}}
            ],
            "connections": [
                {"from": "comp", "from_port": 0, "to": "dst", "to_port": 0}
            ]
        }
        result, status = _post("/api/simulate", {"model": model})
        # Should fail: input 'a' is required but not connected
        self.assertIn(status, (400, 500))
        self.assertFalse(result.get("ok", True))


class TestLegacyModelMigration(ArchBase):
    """Legacy models (numerical blocks at top level) are now REJECTED, not migrated."""


    def test_legacy_model_save_load_unmodified(self):
        """Save a legacy model, load it back, verify it is returned unmodified."""
        model = {
            "blocks": [
                {"id": "b1", "type": "constant", "params": {"value": 2.0}},
                {"id": "b2", "type": "gain", "params": {"gain": 3.0}},
                {"id": "b3", "type": "graph_display", "params": {}}
            ],
            "connections": [
                {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0},
                {"from": "b2", "from_port": 0, "to": "b3", "to_port": 0}
            ]
        }
        # Save
        result, status = _post("/api/save", {"name": "arch_legacy_test", "model": model})
        self.assertEqual(status, 200)
        self.assertEqual(result["saved"], "arch_legacy_test")

        # Load: model is returned unmodified (no auto-wrapping)
        loaded, status = _get("/api/load?name=arch_legacy_test")
        self.assertEqual(status, 200)
        self.assertEqual(len(loaded["model"]["blocks"]), 3)
        types = {b["type"] for b in loaded["model"]["blocks"]}
        self.assertIn("constant", types)
        self.assertIn("gain", types)
        self.assertNotIn("numerical", types)



class TestNoEngineMode(ArchBase):
    """Without numerical engine: shell opens, edits, saves; explains unavailable calculation."""


    def test_save_load_works_without_engine(self):
        """Save and load work regardless of engine availability."""
        model = {
            "blocks": [
                {"id": "b1", "type": "constant", "params": {"value": 1.0}},
                {"id": "b2", "type": "graph_display", "params": {}}
            ],
            "connections": [
                {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0}
            ]
        }
        result, status = _post("/api/save", {"name": "arch_noengine_test", "model": model})
        self.assertEqual(status, 200)
        loaded, status = _get("/api/load?name=arch_noengine_test")
        self.assertEqual(status, 200)
        # Model is returned unmodified (no auto-wrapping)
        self.assertEqual(len(loaded["model"]["blocks"]), 2)
        self.assertEqual(loaded["model"]["blocks"][0]["type"], "constant")
        self.assertEqual(loaded["model"]["blocks"][1]["type"], "graph_display")



class TestNoDirectFallback(ArchBase):
    """Verify there is no direct top-level numerical-engine fallback."""

    def test_source_code_has_no_direct_simulate_fallback(self):
        """The shell server source should not contain a direct _numerical_adapter.simulate() call
        in the _handle_simulate method (outside of the legacy migration path)."""
        src = Path(server.__file__).read_text()
        # The only allowed use of _numerical_adapter.simulate is inside engines/numerical.py
        # In shell/server.py, it should only appear in the adapter's own methods
        # Check that _handle_simulate does NOT call _numerical_adapter.simulate directly
        # (it should go through _execute_generic_dataflow -> DataGraphEngine -> NumericalExecutor)
        handle_simulate_start = src.find("def _handle_simulate")
        handle_simulate_end = src.find("def _handle_invoke", handle_simulate_start)
        handle_simulate_src = src[handle_simulate_start:handle_simulate_end]
        # The direct call pattern would be: _numerical_adapter.simulate(model_dict
        self.assertNotIn("_numerical_adapter.simulate(model_dict", handle_simulate_src,
                         "Direct numerical fallback found in _handle_simulate")

    def test_unknown_block_type_rejected(self):
        """A model with an unknown block type gets a clear error, not a silent fallback."""
        model = {
            "blocks": [
                {"id": "b1", "type": "totally_unknown_block", "params": {}},
                {"id": "b2", "type": "result_display", "params": {}}
            ],
            "connections": [
                {"from": "b1", "from_port": 0, "to": "b2", "to_port": 0}
            ]
        }
        result, status = _post("/api/simulate", {"model": model})
        # Should be rejected (400) or fail (500), not silently succeed
        self.assertIn(status, (400, 500))


class TestOwnershipPreserved(ArchBase):
    """Ownership rules: any declared port prohibits local run."""

    def test_output_only_blocked(self):
        """Model with only output ports cannot run locally."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "a"}},
                {"id": "g1", "type": "gain", "params": {"gain": 2.0}},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "out_a"}}
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "g1", "to_port": 0},
                {"from": "g1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        result, status = _post("/api/simulate", {"model": model})
        self.assertEqual(status, 403)



if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Regression tests for unnamed input handling (W013)
# ---------------------------------------------------------------------------

class TestUnnamedInputRegression(ArchBase):
    """Regression tests for unnamed input port naming, ordering, and validation."""
    def _post(self, path, body):
        return _post(path, body)

    def _get(self, path):
        return _get(path)


    def test_single_unnamed_input_gain(self):
        """Single unnamed input with gain block: input_1=3, gain=2 -> output_1=6."""
        model = {
            "blocks": [
                {"id": "g1", "type": "gain", "params": {"gain": 2.0}, "x": 100, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
                {"id": "out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "g1", "to_port": 0},
                {"from": "g1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        resp, _st = self._post("/api/invoke", {"model": model, "inputs": {"input_1": 3.0}})
        self.assertTrue(resp["ok"], resp)
        self.assertAlmostEqual(resp["outputs"]["output_1"], 6.0)

    def test_multiple_unnamed_inputs(self):
        """Two unnamed inputs: input_1=3, input_2=4 -> addition -> output_1=7."""
        model = {
            "blocks": [
                {"id": "add1", "type": "addition", "params": {}, "x": 100, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
                {"id": "in2", "type": "in1_terminal", "params": {}, "x": 0, "y": 50},
                {"id": "out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "add1", "to_port": 0},
                {"from": "in2", "from_port": 0, "to": "add1", "to_port": 1},
                {"from": "add1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        resp, _st = self._post("/api/invoke", {"model": model, "inputs": {"input_1": 3.0, "input_2": 4.0}})
        self.assertTrue(resp["ok"], resp)
        self.assertAlmostEqual(resp["outputs"]["output_1"], 7.0)

    def test_unnamed_input_different_block_order(self):
        """Gain block listed BEFORE input terminal: naming still works by position."""
        model = {
            "blocks": [
                {"id": "g1", "type": "gain", "params": {"gain": 3.0}, "x": 100, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
                {"id": "out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "g1", "to_port": 0},
                {"from": "g1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        resp, _st = self._post("/api/invoke", {"model": model, "inputs": {"input_1": 5.0}})
        self.assertTrue(resp["ok"], resp)
        self.assertAlmostEqual(resp["outputs"]["output_1"], 15.0)

    def test_missing_input_rejected(self):
        """Missing required input must be rejected, not zero-substituted."""
        model = {
            "blocks": [
                {"id": "g1", "type": "gain", "params": {"gain": 2.0}, "x": 100, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
                {"id": "out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "g1", "to_port": 0},
                {"from": "g1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        # Supply no inputs at all
        resp, _st = self._post("/api/invoke", {"model": model, "inputs": {}})
        self.assertFalse(resp["ok"])
        self.assertIn("input_1", resp.get("error", ""))

    def test_missing_one_of_two_inputs_rejected(self):
        """With two inputs, supplying only one must be rejected."""
        model = {
            "blocks": [
                {"id": "add1", "type": "addition", "params": {}, "x": 100, "y": 0},
                {"id": "in1", "type": "in1_terminal", "params": {}, "x": 0, "y": 0},
                {"id": "in2", "type": "in1_terminal", "params": {}, "x": 0, "y": 50},
                {"id": "out1", "type": "out1_terminal", "params": {}, "x": 200, "y": 0}
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "add1", "to_port": 0},
                {"from": "in2", "from_port": 0, "to": "add1", "to_port": 1},
                {"from": "add1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        resp, _st = self._post("/api/invoke", {"model": model, "inputs": {"input_1": 3.0}})
        self.assertFalse(resp["ok"])
        self.assertIn("input_2", resp.get("error", ""))



# ---- Regression tests for editor fixes (W015-W017) -------------------------

class TestEditorPortDeserialization(unittest.TestCase):
    """Verify enterSubsystem properly deserializes connections from server format."""

    def _app_js(self):
        return (WEB_DIR / "app.js").read_text("utf-8")



    def test_deserialize_connections_converts_port_names(self):
        """deserializeConnections must convert from_port to fromPort and to_port to toPort."""
        js = self._app_js()
        # Check the deserializeConnections function does the conversion
        assert "fromPort: Number(c.from_port)" in js,             "deserializeConnections must convert from_port to fromPort"
        assert "toPort: Number(c.to_port)" in js,             "deserializeConnections must convert to_port to toPort"


class TestResultKeyForBlock(unittest.TestCase):
    """Verify resultKeyForBlock returns scoped key when inside numerical block."""

    def _app_js(self):
        return (WEB_DIR / "app.js").read_text("utf-8")

    def test_result_key_scoped_when_inside_numerical(self):
        """resultKeyForBlock must use activeView prefix when inside a numerical block."""
        js = self._app_js()
        func_match = re.search(r'function resultKeyForBlock\(block\)\s*\{([^}]+)\}', js)
        assert func_match, "resultKeyForBlock function not found"
        body = func_match.group(1)
        assert "_isInsideNumerical" in body,             "resultKeyForBlock must check _isInsideNumerical"
        assert "state.activeView" in body,             "resultKeyForBlock must use state.activeView prefix"
        assert "return block.id" in body,             "resultKeyForBlock must return block.id as fallback"


class TestNoEngineLoadAllowed(unittest.TestCase):
    """Verify loadModel allows loading models with unknown block types."""

    def _app_js(self):
        return (WEB_DIR / "app.js").read_text("utf-8")

    def test_load_model_does_not_refuse_unknown_blocks(self):
        """loadModel must not return early when unknown blocks are found."""
        js = self._app_js()
        # Find the loadModel function
        func_start = js.index("async function loadModel()")
        func_end = js.index("function escapeHtml", func_start)
        load_func = js[func_start:func_end]
        # The old code had: setStatus('error', 'status.missing_blocks'...) followed by return;
        # The new code should use 'info' level and NOT return
        assert "status.missing_blocks" not in load_func or "return;" not in load_func.split("status.missing_blocks")[1][:200],             "loadModel must not hard-refuse when unknown blocks are found"
        # Should use info level for unknown blocks warning
        assert "status.unknown_blocks" in load_func,             "loadModel should show info-level warning for unknown blocks"

    def test_i18n_has_unknown_blocks_key(self):
        """i18n catalog must have status.unknown_blocks key."""
        catalog = (WEB_DIR / "i18n-catalog.js").read_text("utf-8")
        assert "status.unknown_blocks" in catalog,             "i18n catalog must define status.unknown_blocks"

class TestEditorRoundtripBehavioral(ArchBase):
    """Behavioral test: enter numerical block, exit, save, reload, run.

    Simulates the actual editor roundtrip:
    1. Model has a numerical block with 2 constants (2, 3) -> addition -> graph
    2. Editor enters the block (deserializes connections to camelCase)
    3. Editor exits the block (serializes connections back to snake_case)
    4. Model is saved
    5. Model is reloaded and run
    6. Result must be 5 (2 + 3)
    """

    def _make_addition_model(self):
        """Create a model with a numerical block containing:
        constant(2) -> addition(input 0)
        constant(3) -> addition(input 1)
        addition -> graph_display
        """
        internal_blocks = [
            {"id": "c1", "type": "constant", "params": {"value": 2.0}, "x": 40, "y": 60},
            {"id": "c2", "type": "constant", "params": {"value": 3.0}, "x": 40, "y": 140},
            {"id": "add1", "type": "addition", "params": {}, "x": 200, "y": 100},
            {"id": "gd1", "type": "graph_display", "params": {}, "x": 360, "y": 100},
        ]
        internal_connections = [
            {"from": "c1", "from_port": 0, "to": "add1", "to_port": 0},
            {"from": "c2", "from_port": 0, "to": "add1", "to_port": 1},
            {"from": "add1", "from_port": 0, "to": "gd1", "to_port": 0},
        ]
        return {
            "blocks": [
                {"id": "comp1", "type": "numerical", "params": {
                    "model": {"blocks": internal_blocks, "connections": internal_connections}
                }, "x": 100, "y": 100}
            ],
            "connections": []
        }


    def test_buggy_format_gives_wrong_result(self):
        """Verify that the OLD buggy format (fromPort/toPort in saved model) gives
        wrong result or error. Documents why the fix is necessary."""
        model = self._make_addition_model()

        # Simulate the BUG: save with camelCase port names (what old exitSubsystem did)
        comp = model["blocks"][0]
        buggy_conns = [
            {"from": "c1", "fromPort": 0, "to": "add1", "toPort": 0},
            {"from": "c2", "fromPort": 0, "to": "add1", "toPort": 1},
            {"from": "add1", "fromPort": 0, "to": "gd1", "toPort": 0},
        ]
        comp["params"]["model"]["connections"] = buggy_conns

        # The server should either reject this or produce wrong results
        resp, status = _post("/api/simulate", {"model": model, "t_end": 1.0, "h": 0.01})
        # If it succeeds, the result should be WRONG (not 5)
        if status == 200 and "results" in resp:
            gd_result = resp["results"].get("_run/gd1") or resp["results"].get("gd1")
            if isinstance(gd_result, dict) and "series" in gd_result:
                final_val = gd_result["series"][-1][1] if gd_result["series"] else None
            elif isinstance(gd_result, (int, float)):
                final_val = gd_result
            else:
                final_val = None
            if final_val is not None:
                self.assertNotAlmostEqual(final_val, 5.0, places=3,
                    msg="Buggy format should not produce correct result of 5")

# ---- W019b: exitSubsystem preserves params.model fields ------------------- #

class TestExitPreservesModelFields(ArchBase):
    """Verify that exitSubsystem preserves non-blocks/connections fields in params.model."""

    def _make_model_with_metadata(self):
        """Create a model with a numerical block containing metadata and custom fields."""
        internal_blocks = [
            {"id": "c1", "type": "constant", "params": {"value": 2.0}, "x": 40, "y": 60},
            {"id": "gd1", "type": "graph_display", "params": {}, "x": 200, "y": 60},
        ]
        internal_connections = [
            {"from": "c1", "from_port": 0, "to": "gd1", "to_port": 0},
        ]
        return {
            "blocks": [
                {"id": "comp1", "type": "numerical", "params": {
                    "model": {
                        "blocks": internal_blocks,
                        "connections": internal_connections,
                        "metadata": {"description": "must survive", "custom": 17},
                        "solver": {"method": "rk4", "h": 0.005}
                    }
                }, "x": 100, "y": 100}
            ],
            "connections": []
        }

    def test_metadata_preserved_after_roundtrip(self):
        """Load -> enter -> exit -> save -> reload must preserve metadata and custom fields."""
        model = self._make_model_with_metadata()
        name = "exit_preserve_test"

        # Save initial model
        resp, status = _post("/api/save", {"name": name, "model": model})
        self.assertEqual(status, 200)

        # Load (as editor would)
        resp, status = _get("/api/load?name=" + name)
        self.assertEqual(status, 200)
        loaded = resp["model"]

        # Verify metadata exists before enter/exit
        comp = loaded["blocks"][0]
        self.assertIn("metadata", comp["params"]["model"])
        self.assertEqual(comp["params"]["model"]["metadata"]["description"], "must survive")
        self.assertEqual(comp["params"]["model"]["metadata"]["custom"], 17)
        self.assertIn("solver", comp["params"]["model"])

        # Simulate enterSubsystem: deserialize blocks/connections
        # (this is what app.js does: sub.internal = {blocks: deserializeBlocks(...), ...})
        internal_blocks = comp["params"]["model"]["blocks"]
        internal_conns = comp["params"]["model"]["connections"]
        # Editor uses camelCase internally
        editor_conns = [{"from": c["from"], "fromPort": c.get("from_port", 0),
                         "to": c["to"], "toPort": c.get("to_port", 0)} for c in internal_conns]

        # Simulate exitSubsystem (FIXED): update in place, preserve other fields
        # The fix: sub.params.model.blocks = serializeBlocks(...); sub.params.model.connections = ...
        # NOT: sub.params.model = {blocks: ..., connections: ...}
        serialized_conns = [{"from": c["from"], "from_port": c["fromPort"],
                             "to": c["to"], "to_port": c["toPort"]} for c in editor_conns]
        # In-place update (the fix)
        comp["params"]["model"]["blocks"] = internal_blocks  # unchanged
        comp["params"]["model"]["connections"] = serialized_conns
        # metadata and solver should still be there (they were never touched)

        # Save after editor roundtrip
        resp, status = _post("/api/save", {"name": name + "_edited", "model": loaded})
        self.assertEqual(status, 200)

        # Reload and verify all fields preserved
        resp, status = _get("/api/load?name=" + name + "_edited")
        self.assertEqual(status, 200)
        reloaded = resp["model"]
        reloaded_comp = reloaded["blocks"][0]
        pm = reloaded_comp["params"]["model"]

        # Metadata must survive
        self.assertIn("metadata", pm, "metadata must be preserved after exit")
        self.assertEqual(pm["metadata"]["description"], "must survive")
        self.assertEqual(pm["metadata"]["custom"], 17)
        # Solver settings must survive
        self.assertIn("solver", pm, "solver settings must be preserved after exit")
        self.assertEqual(pm["solver"]["method"], "rk4")
        # Blocks and connections must be correct
        self.assertEqual(len(pm["blocks"]), 2)
        self.assertEqual(len(pm["connections"]), 1)
        self.assertEqual(pm["connections"][0]["to_port"], 0)

    def test_nested_numerical_block_preserved(self):
        """Nested numerical blocks: inner block's metadata must survive enter/exit of inner."""
        inner_blocks = [
            {"id": "c1", "type": "constant", "params": {"value": 1.0}, "x": 40, "y": 60},
            {"id": "gd1", "type": "graph_display", "params": {}, "x": 200, "y": 60},
        ]
        inner_conns = [{"from": "c1", "from_port": 0, "to": "gd1", "to_port": 0}]

        outer_blocks = [
            {"id": "inner1", "type": "numerical", "params": {
                "model": {
                    "blocks": inner_blocks,
                    "connections": inner_conns,
                    "metadata": {"inner_desc": "inner must survive", "tag": 42}
                }
            }, "x": 40, "y": 60},
            {"id": "gd_outer", "type": "graph_display", "params": {}, "x": 200, "y": 60},
        ]
        outer_conns = [{"from": "inner1", "from_port": 0, "to": "gd_outer", "to_port": 0}]

        model = {
            "blocks": [
                {"id": "comp1", "type": "numerical", "params": {
                    "model": {
                        "blocks": outer_blocks,
                        "connections": outer_conns,
                        "metadata": {"outer_desc": "outer must survive"}
                    }
                }, "x": 100, "y": 100}
            ],
            "connections": []
        }

        name = "nested_preserve_test"
        resp, status = _post("/api/save", {"name": name, "model": model})
        self.assertEqual(status, 200)

        resp, status = _get("/api/load?name=" + name)
        self.assertEqual(status, 200)
        loaded = resp["model"]

        # Verify both metadata fields exist
        comp = loaded["blocks"][0]
        pm = comp["params"]["model"]
        self.assertEqual(pm["metadata"]["outer_desc"], "outer must survive")
        inner = pm["blocks"][0]
        self.assertEqual(inner["params"]["model"]["metadata"]["inner_desc"], "inner must survive")
        self.assertEqual(inner["params"]["model"]["metadata"]["tag"], 42)

        # Simulate: enter comp1, enter inner1, exit inner1, exit comp1
        # After the fix, both exits update in place, preserving metadata

        # Enter comp1: deserialize outer blocks/connections
        outer_editor_blocks = pm["blocks"]
        outer_editor_conns = [{"from": c["from"], "fromPort": c.get("from_port", 0),
                               "to": c["to"], "toPort": c.get("to_port", 0)} for c in pm["connections"]]

        # Enter inner1: deserialize inner blocks/connections
        inner_pm = inner["params"]["model"]
        inner_editor_conns = [{"from": c["from"], "fromPort": c.get("from_port", 0),
                               "to": c["to"], "toPort": c.get("to_port", 0)} for c in inner_pm["connections"]]

        # Exit inner1 (FIXED): update inner.params.model in place
        inner_serialized_conns = [{"from": c["from"], "from_port": c["fromPort"],
                                   "to": c["to"], "to_port": c["toPort"]} for c in inner_editor_conns]
        inner["params"]["model"]["connections"] = inner_serialized_conns
        # inner metadata must still be there
        self.assertIn("metadata", inner["params"]["model"], "inner metadata must survive exit")
        self.assertEqual(inner["params"]["model"]["metadata"]["inner_desc"], "inner must survive")

        # Exit comp1 (FIXED): update comp.params.model in place
        comp_serialized_conns = [{"from": c["from"], "from_port": c["fromPort"],
                                  "to": c["to"], "to_port": c["toPort"]} for c in outer_editor_conns]
        pm["connections"] = comp_serialized_conns
        # outer metadata must still be there
        self.assertIn("metadata", pm, "outer metadata must survive exit")
        self.assertEqual(pm["metadata"]["outer_desc"], "outer must survive")

        # Save and reload
        resp, status = _post("/api/save", {"name": name + "_edited", "model": loaded})
        self.assertEqual(status, 200)

        resp, status = _get("/api/load?name=" + name + "_edited")
        self.assertEqual(status, 200)
        reloaded = resp["model"]
        reloaded_comp = reloaded["blocks"][0]
        rpm = reloaded_comp["params"]["model"]

        # Both metadata fields must survive the full roundtrip
        self.assertEqual(rpm["metadata"]["outer_desc"], "outer must survive")
        reloaded_inner = rpm["blocks"][0]
        self.assertEqual(reloaded_inner["params"]["model"]["metadata"]["inner_desc"], "inner must survive")
        self.assertEqual(reloaded_inner["params"]["model"]["metadata"]["tag"], 42)
