"""Tests for the unified persistent block library.

Covers:
- Unified tree structure (shell + numerical sections, categories preserved)
- Context metadata (outer vs numerical placement rules)
- Nested context inheritance (subsystem inside numerical => numerical)
- Transition preserves tree identity (enter/exit re-render, no refetch)
- Refresh picks up block file changes
- Unavailable engine does not break the shell
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import shell.server as server


def _app_js():
    return (PROJECT_ROOT / "shell" / "web" / "app.js").read_text("utf-8")


def _extract_function(js, name):
    """Extract a top-level function by name using brace matching."""
    start = js.index("function " + name)
    brace_start = js.index("{", start)
    depth = 0
    i = brace_start
    while i < len(js):
        c = js[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return js[start:i + 1]
        i += 1
    raise ValueError("unbalanced braces for " + name)


class UnifiedBase(unittest.TestCase):
    """Start a live server with the numerical engine available."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _get(self, path):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read())

    def _post(self, path, body=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())


class TestUnifiedTreeStructure(UnifiedBase):
    """The unified /api/library returns shell + numerical sections."""

    def test_has_shell_section(self):
        data = self._get("/api/library")
        sections = {n["section"] for n in data["tree"]}
        self.assertIn("shell", sections)
        shell_cats = [n["name"] for n in data["tree"] if n["section"] == "shell"]
        self.assertIn("Shell", shell_cats)
        self.assertIn("Computation", shell_cats)
        self.assertIn("Optimization", shell_cats)

    def test_has_numerical_section(self):
        data = self._get("/api/library")
        sections = {n["section"] for n in data["tree"]}
        self.assertIn("numerical", sections)
        num_cats = [n["name"] for n in data["tree"] if n["section"] == "numerical"]
        self.assertIn("Dynamics", num_cats)
        self.assertIn("Math", num_cats)
        self.assertIn("Sources", num_cats)

    def test_engine_available_flag(self):
        data = self._get("/api/library")
        self.assertTrue(data["engine_available"])

    def test_block_contexts_present(self):
        data = self._get("/api/library")
        self.assertIn("block_contexts", data)
        self.assertIsInstance(data["block_contexts"], dict)
        self.assertGreater(len(data["block_contexts"]), 10)

    def test_every_block_has_context(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        for cat in data["tree"]:
            for b in cat.get("blocks", []):
                self.assertIn(b, bc, "block %s missing from block_contexts" % b)
                self.assertIsInstance(bc[b], list)
                self.assertTrue(len(bc[b]) > 0, "block %s has empty contexts" % b)

    def test_no_duplicate_block_across_categories(self):
        data = self._get("/api/library")
        seen = {}
        for cat in data["tree"]:
            for b in cat.get("blocks", []):
                if b in seen:
                    self.fail("block %s appears in both %s and %s" % (b, seen[b], cat["name"]))
                seen[b] = cat["name"]


class TestContextMetadata(UnifiedBase):
    """Context rules: which blocks are placeable where."""

    def test_shell_blocks_outer_only(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        for name in ("input_value", "param_assembler", "result_display"):
            self.assertEqual(bc[name], ["outer"], "%s must be outer-only" % name)

    def test_numerical_wrapper_outer_only(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        self.assertNotIn("numerical", bc)

    def test_optimizer_outer_and_objective_numerical(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        self.assertEqual(bc["optimizer"], ["outer"])
        self.assertEqual(bc["objective"], ["numerical"])

    def test_subsystem_numerical_only(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        self.assertEqual(bc["subsystem"], ["numerical"])

    def test_terminals_numerical_only(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        self.assertEqual(bc["in1_terminal"], ["numerical"])
        self.assertEqual(bc["out1_terminal"], ["numerical"])

    def test_engine_blocks_numerical_only(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        for name in ("constant", "first_order", "gain", "integrator", "graph_display", "sine"):
            self.assertEqual(bc[name], ["numerical"], "%s must be numerical-only" % name)


class TestNestedContextInheritance(unittest.TestCase):
    """_currentContext() inherits from nearest parent engine block."""

    def _ctx(self, state_js):
        js = _app_js()
        fn_src = _extract_function(js, "_currentContext")
        script = "\nconst state = " + state_js + ";\n" + fn_src + "\nconsole.log(_currentContext());\n"
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_outer_context(self):
        self.assertEqual(self._ctx("{activeView: null, rootBlocks: [], blocks: []}"), "outer")

    def test_inside_numerical(self):
        state = """{activeView: 'b1', rootBlocks: [{id: 'b1', type: 'typed_experiment', internal: {blocks: []}}], blocks: []}"""
        self.assertEqual(self._ctx(state), "numerical")

    def test_subsystem_inside_numerical_inherits(self):
        state = """{activeView: 'b1/b2', rootBlocks: [{id: 'b1', type: 'typed_experiment', internal: {blocks: [{id: 'b2', type: 'subsystem', internal: {blocks: []}}]}}], blocks: []}"""
        self.assertEqual(self._ctx(state), "numerical")

    def test_subsystem_at_top_level_is_outer(self):
        state = """{activeView: 'b2', rootBlocks: [{id: 'b2', type: 'subsystem', internal: {blocks: []}}], blocks: []}"""
        self.assertEqual(self._ctx(state), "outer")

    def test_deep_nesting_inherits_numerical(self):
        state = """{activeView: 'b1/b2/b3', rootBlocks: [{id: 'b1', type: 'typed_experiment', internal: {blocks: [{id: 'b2', type: 'subsystem', internal: {blocks: [{id: 'b3', type: 'subsystem', internal: {blocks: []}}]}}]}}], blocks: []}"""
        self.assertEqual(self._ctx(state), "numerical")


class TestTransitionPreservesTree(unittest.TestCase):
    """enter/exit subsystem re-render the tree without refetching."""

    def test_enter_subsystem_uses_render_not_load(self):
        js = _app_js()
        enter_fn = js[js.index("function enterSubsystem"):js.index("function exitSubsystem")]
        self.assertIn("renderLibraryTree()", enter_fn)
        self.assertNotIn("loadLibrary()", enter_fn)

    def test_exit_subsystem_uses_render_not_load(self):
        js = _app_js()
        exit_fn = js[js.index("function exitSubsystem"):]
        next_fn_idx = exit_fn.find("function ", 10)
        if next_fn_idx > 0:
            exit_fn = exit_fn[:next_fn_idx]
        self.assertIn("renderLibraryTree()", exit_fn)
        self.assertNotIn("loadLibrary()", exit_fn)

    def test_load_library_uses_unified_endpoint(self):
        js = _app_js()
        self.assertIn("api('/api/library')", js)
        self.assertNotIn("_isInsideNumerical() ? '/api/numerical/library' : '/api/library'", js)

    def test_render_node_does_not_mark_unavailable(self):
        js = _app_js()
        render_fn = js[js.index("function renderNode"):js.index("function selectPlacingBlock")]
        self.assertNotIn("_blockAvailable", render_fn)
        self.assertNotIn("unavailable", render_fn)

    def test_select_placing_block_guards(self):
        js = _app_js()
        self.assertIn("status.block_context", js)

    def test_boundary_blocks_cannot_be_deleted(self):
        delete = _extract_function(_app_js(), 'deleteBlock')
        script = r"""
const assert = require('assert');
const state = {blocks:[{id:'P1',type:'experiment_input'}, {id:'J',type:'experiment_result'},
  {id:'In1',type:'in1_terminal'}, {id:'Out1',type:'out1_terminal'}], connections:[]};
let errors = 0;
function setStatus(kind) { if (kind === 'error') errors++; }
""" + delete + r"""
for (const b of [...state.blocks]) deleteBlock(b.id);
assert.strictEqual(errors, 4);
assert.strictEqual(state.blocks.length, 4);
"""
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

    def test_port_hit_area_selects_nearest_connector(self):
        port_at = _extract_function(_app_js(), 'portAt')
        script = r"""
const assert = require('assert');
const block = {id:'pid'};
const state = {blocks:[block]};
function instancePorts() { return {nIn:2, nOut:0}; }
function inputPort(b, i) { return {x:0, y:i*22}; }
function outputPort() { throw Error('no output'); }
""" + port_at + r"""
assert.strictEqual(portAt(14, 0).index, 0);
assert.strictEqual(portAt(0, 13).index, 1);
assert.strictEqual(portAt(0, 9).index, 0);
assert.strictEqual(portAt(17, 0), null);
"""
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

    def test_canvas_pointer_coordinates_follow_display_scaling(self):
        canvas_pos = _extract_function(_app_js(), 'canvasPos')
        script = r"""
const assert = require('assert');
const canvas = {width:1000, height:825,
  getBoundingClientRect:()=>({left:250,top:83,width:944,height:788})};
""" + canvas_pos + r"""
const point = canvasPos({clientX:722,clientY:477});
assert(Math.abs(point.x - 500) < 1e-9);
assert(Math.abs(point.y - 412.5) < 1e-9);
"""
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)


class TestRefreshPicksUpFileChanges(UnifiedBase):
    """POST /api/library/refresh re-reads block files from disk."""

    def test_add_block_and_refresh(self):
        blocks_dir = PROJECT_ROOT / "blocks"
        temp_dir = tempfile.TemporaryDirectory(prefix="pavsim_refresh_test_", dir=blocks_dir)
        block_file = Path(temp_dir.name) / "refresh_test_block.py"
        try:
            block_file.write_text(textwrap.dedent("""
                from xcos_mini.core import Block
                class RefreshTestBlock(Block):
                    name = "refresh_test_block"
                    n_inputs = 0
                    n_outputs = 1
                    def compute(self, t, inputs, params, state):
                        return 42.0
            """))
            # Refresh to pick up the new block
            data = self._post("/api/library/refresh")
            all_blocks = []
            for cat in data["tree"]:
                all_blocks.extend(cat.get("blocks", []))
            self.assertIn("refresh_test_block", all_blocks)
            self.assertEqual(data["block_contexts"]["refresh_test_block"], ["numerical"])
        finally:
            # Clean up
            temp_dir.cleanup()
            # Refresh again to remove the block
            data = self._post("/api/library/refresh")
            all_blocks = []
            for cat in data["tree"]:
                all_blocks.extend(cat.get("blocks", []))
            self.assertNotIn("refresh_test_block", all_blocks)

    def test_refresh_returns_full_tree(self):
        data = self._post("/api/library/refresh")
        self.assertIn("tree", data)
        self.assertIn("block_contexts", data)
        self.assertIn("engine_available", data)
        self.assertTrue(data["engine_available"])


class TestUnavailableEngine(unittest.TestCase):
    """An unavailable engine must not break the shell."""

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            ["python3", "-m", "shell.server", "--no-engines", "--port", "8897"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT)
        )
        time.sleep(2)
        cls.base = "http://127.0.0.1:8897"

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()

    def _get(self, path):
        url = self.base + path
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read())

    def _get_status(self, path):
        url = self.base + path
        try:
            with urllib.request.urlopen(url) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_engine_not_available(self):
        data = self._get("/api/health")
        self.assertFalse(data["engine_available"])

    def test_library_returns_shell_section_only(self):
        data = self._get("/api/library")
        self.assertFalse(data["engine_available"])
        sections = {n["section"] for n in data["tree"]}
        self.assertIn("shell", sections)
        self.assertNotIn("numerical", sections)
        # Shell blocks still present
        all_blocks = []
        for cat in data["tree"]:
            all_blocks.extend(cat.get("blocks", []))
        self.assertIn("input_value", all_blocks)
        self.assertIn("typed_experiment", all_blocks)

    def test_numerical_library_returns_503(self):
        status, data = self._get_status("/api/numerical/library")
        self.assertEqual(status, 503)

    def test_shell_blocks_still_placeable(self):
        data = self._get("/api/library")
        bc = data["block_contexts"]
        self.assertEqual(bc["input_value"], ["outer"])
        self.assertNotIn("numerical", bc)


if __name__ == "__main__":
    unittest.main()
