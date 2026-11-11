"""Regression tests for the four stage-2 acceptance fixes.

1. Common outer graph: mixed generic+numerical execution
2. Nested ownership: active diagram port guard
3. Per-block settings: solver params resolve to correct nesting level
4. Package-independent editor: static assets from shell/web
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))




class TestW002NestedOwnership(unittest.TestCase):
    """Nested Run and ownership badge refer to active diagram."""

    def test_nested_output_only_blocked(self):
        """A nested model with only out1_terminal is externally controlled."""
        from shell.server import _model_has_external_ports, _get_external_interface
        model = {
            "blocks": [
                {"id": "o", "type": "out1_terminal", "params": {"name": "y"}},
            ],
            "connections": [],
        }
        self.assertTrue(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "externally_controlled")
        self.assertEqual(len(iface["outputs"]), 1)
        self.assertEqual(len(iface["inputs"]), 0)

    def test_nested_portless_allowed(self):
        """A nested model with no external ports is standalone."""
        from shell.server import _model_has_external_ports, _get_external_interface
        model = {
            "blocks": [
                {"id": "a", "type": "input_value", "params": {"value": 1}},
                {"id": "b", "type": "result_display", "params": {}},
            ],
            "connections": [{"from": "a", "from_port": 0, "to": "b", "to_port": 0}],
        }
        self.assertFalse(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "standalone")

    def test_deleting_last_port_restores(self):
        """Removing the last external port makes the model standalone."""
        from shell.server import _model_has_external_ports
        model_with_port = {
            "blocks": [{"id": "o", "type": "out1_terminal", "params": {"name": "y"}}],
            "connections": [],
        }
        self.assertTrue(_model_has_external_ports(model_with_port))
        model_without = {"blocks": [], "connections": []}
        self.assertFalse(_model_has_external_ports(model_without))

    def test_simulate_rejects_nested_output_only(self):
        """API rejects simulate for a model with only output ports."""
        import shell.server as srv
        self.tmpdir = tempfile.mkdtemp(prefix="stage2_w002_")
        orig = srv.MODELS_DIR
        srv.MODELS_DIR = Path(self.tmpdir)
        try:
            from http.server import ThreadingHTTPServer
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
            port = httpd.server_address[1]
            base = f"http://127.0.0.1:{port}"
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            model = {
                "blocks": [{"id": "o", "type": "out1_terminal", "params": {"name": "y"}}],
                "connections": [],
            }
            data = json.dumps({"model": model}).encode()
            req = urllib.request.Request(base + "/api/simulate", data=data,
                                        headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req) as resp:
                    status = resp.status
            except urllib.error.HTTPError as e:
                status = e.code
            self.assertEqual(status, 403, f"Expected 403 for output-only model, got {status}")
            httpd.shutdown()
            httpd.server_close()
        finally:
            srv.MODELS_DIR = orig
            shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestW003PerBlockSettings(unittest.TestCase):
    """Solver settings resolve to the correct nesting level."""

    def test_nested_solver_param_resolution(self):
        """outer.h=.1, inner.h=.2, activeView=outer/inner must use .2."""
        # This tests the frontend logic via the JS sandbox
        js_code = '''
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ROOT = path.resolve(__dirname, '..');
const ctxMock = new Proxy({}, { get: (t, p) => (p in t) ? t[p] : (() => {}), set: (t, p, v) => { t[p] = v; return true; } });
const canvasMock = { id:'canvas', width:800, height:600, title:'', parentElement:{clientWidth:800,clientHeight:600}, getContext:()=>ctxMock, addEventListener(){}, getBoundingClientRect(){return{left:0,top:0,width:800,height:600}} };
function makeElement(id) {
  if (id === 'canvas') return canvasMock;
  return { id, dataset:{}, textContent:'', innerHTML:'', value:'', className:'', style:{},
    classList:{_set:new Set(),add(c){this._set.add(c)},remove(c){this._set.delete(c)},contains(c){return this._set.has(c)},toggle(c,f){if(f===undefined){this._set.has(c)?this._set.delete(c):this._set.add(c)}else if(f)this._set.add(c);else this._set.delete(c)}},
    appendChild(c){return c},_ls:{},addEventListener(t,fn){(this._ls[t]=this._ls[t]||[]).push(fn)},removeEventListener(){},click(){(this._ls["click"]||[]).forEach(fn=>fn({preventDefault(){}}))},
    querySelectorAll(){return[]},getBoundingClientRect(){return{left:0,top:0,width:800,height:600}},clientWidth:800,clientHeight:600};
}
const elements = {};
function getElementById(id) { if(!elements[id]) elements[id]=makeElement(id); return elements[id]; }
const documentMock = { getElementById, createElement:t=>makeElement(t), querySelectorAll:()=>[], activeElement:null, addEventListener(){}, body:makeElement('body'), documentElement:makeElement('html') };
const windowMock = { addEventListener(){}, open:()=>null, innerWidth:800, innerHeight:600 };
const BLOCK_TYPES = [{name:'constant',n_inputs:0,n_outputs:1,parameters:{value:1},state_kind:'none'},{name:'gain',n_inputs:1,n_outputs:1,parameters:{k:1},state_kind:'none'},{name:'graph_display',n_inputs:1,n_outputs:0,parameters:{},state_kind:'none'},{name:'subsystem',n_inputs:1,n_outputs:1,parameters:{},state_kind:'none'},{name:'experiment',n_inputs:0,n_outputs:0,parameters:{},state_kind:'none'}];
const fetchMock = async (p, opts) => {
  if (p === '/api/blocks') return {ok:true,status:200,json:async()=>({blocks:BLOCK_TYPES})};
  if (p === '/api/library') return {ok:true,status:200,json:async()=>({tree:[],load_errors:[]})};
  if (p === '/api/models') return {ok:true,status:200,json:async()=>({models:[]})};
  if (p === '/api/simulate') return {ok:true,status:200,json:async()=>({ok:true,results:{},n_steps:1})};
  if (p === '/api/save') return {ok:true,status:200,json:async()=>({saved:'x'})};
  return {ok:true,status:200,json:async()=>({})};
};
const sandbox = { document:documentMock, window:windowMock, fetch:fetchMock, confirm:()=>true, console, setTimeout, clearTimeout, Math, JSON, Object, Array, String, Number, Promise, Proxy };
vm.createContext(sandbox);
const code = fs.readFileSync(path.join(ROOT, 'xcos_mini', 'web', 'app.js'), 'utf8');
require('./load_i18n')(sandbox);
vm.runInContext(code, sandbox);
const state = vm.runInContext('state', sandbox);

// Set up: outer experiment (h=0.1) containing inner experiment (h=0.2)
state.rootBlocks = [
  {id:'outer', type:'experiment', params:{h:0.1, t_end:1.0, method:'rk4'}, x:0, y:0,
   internal:{blocks:[
     {id:'inner', type:'experiment', params:{h:0.2, t_end:2.0, method:'euler'}, x:0, y:0,
      internal:{blocks:[], connections:[]}}
   ], connections:[]}}
];
state.rootConnections = [];
state.blocks = state.rootBlocks;
state.connections = state.rootConnections;

// Navigate to outer/inner
state.activeView = 'outer/inner';

// Test: _getSolverParam should resolve to inner's h=0.2
const h = vm.runInContext("_getSolverParam('h', 0.01)", sandbox);
if (h !== 0.2) { console.error('FAIL: expected h=0.2, got ' + h); process.exit(1); }
const t_end = vm.runInContext("_getSolverParam('t_end', 1.0)", sandbox);
if (t_end !== 2.0) { console.error('FAIL: expected t_end=2.0, got ' + t_end); process.exit(1); }
const method = vm.runInContext("_getSolverParam('method', 'rk4')", sandbox);
if (method !== 'euler') { console.error('FAIL: expected method=euler, got ' + method); process.exit(1); }

// Test: at outer level, should use outer's h=0.1
state.activeView = 'outer';
const h_outer = vm.runInContext("_getSolverParam('h', 0.01)", sandbox);
if (h_outer !== 0.1) { console.error('FAIL: expected outer h=0.1, got ' + h_outer); process.exit(1); }

console.log('W003 SOLVER PARAM TESTS PASSED');
'''
        result = subprocess.run(
            ["node", "-e", js_code],
            cwd=str(ROOT / "tests"),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, f"W003 JS test failed: {result.stderr}\n{result.stdout}")
        self.assertIn("W003 SOLVER PARAM TESTS PASSED", result.stdout)


class TestW004PackageIndependentEditor(unittest.TestCase):
    """Static assets belong to shell, not xcos_mini/web."""

    def test_web_dir_points_to_shell(self):
        """WEB_DIR in server.py points to shell/web."""
        import shell.server as srv
        web_dir = str(srv.WEB_DIR)
        self.assertIn("shell", web_dir, f"WEB_DIR should be in shell/, got: {web_dir}")
        self.assertNotIn("xcos_mini", web_dir, f"WEB_DIR should NOT be in xcos_mini/, got: {web_dir}")

    def test_shell_web_has_index(self):
        """shell/web/ contains index.html."""
        index = ROOT / "shell" / "web" / "index.html"
        self.assertTrue(index.is_file(), f"shell/web/index.html missing")

    def test_shell_web_has_appjs(self):
        """shell/web/ contains app.js."""
        appjs = ROOT / "shell" / "web" / "app.js"
        self.assertTrue(appjs.is_file(), f"shell/web/app.js missing")

    def test_serve_index_from_shell(self):
        """GET / serves the shell/web/index.html."""
        import shell.server as srv
        self.tmpdir = tempfile.mkdtemp(prefix="stage2_w004_")
        orig = srv.MODELS_DIR
        srv.MODELS_DIR = Path(self.tmpdir)
        try:
            from http.server import ThreadingHTTPServer
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
            port = httpd.server_address[1]
            base = f"http://127.0.0.1:{port}"
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            with urllib.request.urlopen(base + "/") as resp:
                content = resp.read().decode("utf-8")
                self.assertIn("<html", content.lower())
                self.assertEqual(resp.status, 200)
            httpd.shutdown()
            httpd.server_close()
        finally:
            srv.MODELS_DIR = orig
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unknown_block_type_survives_roundtrip(self):
        """Unknown/unavailable engine blocks survive save/load roundtrip."""
        import shell.server as srv
        self.tmpdir = tempfile.mkdtemp(prefix="stage2_w004b_")
        orig = srv.MODELS_DIR
        srv.MODELS_DIR = Path(self.tmpdir)
        try:
            from http.server import ThreadingHTTPServer
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
            port = httpd.server_address[1]
            base = f"http://127.0.0.1:{port}"
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            # Save a model with an unknown block type
            model = {
                "blocks": [
                    {"id": "b1", "type": "mystery_engine_block", "params": {"x": 1}, "x": 0, "y": 0},
                    {"id": "b2", "type": "input_value", "params": {"value": 5}, "x": 200, "y": 0},
                ],
                "connections": [{"from": "b2", "from_port": 0, "to": "b1", "to_port": 0}],
            }
            data = json.dumps({"name": "unknown_block_test", "model": model}).encode()
            req = urllib.request.Request(base + "/api/save", data=data,
                                        headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
            # Load it back
            with urllib.request.urlopen(base + "/api/load?name=unknown_block_test") as resp:
                loaded = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(loaded["model"]["blocks"][0]["type"], "mystery_engine_block")
            self.assertEqual(loaded["model"]["blocks"][0]["params"], {"x": 1})
            httpd.shutdown()
            httpd.server_close()
        finally:
            srv.MODELS_DIR = orig
            shutil.rmtree(self.tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
