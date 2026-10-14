"""Behavioral regression: root/visible diagram synchronization after Clear and
after individual block/wire deletion.

The companion JS test (tests/test_sync_fix.js) drives the PRODUCTION app.js event
handlers and serialization inside a Node vm sandbox, then emits the exact Run and
Save model JSON for each scenario. This test takes that JSON and:
  * passes each runnable model through production _build_model + Engine and
    asserts the designated sink block(s) record a FULL series of 1.0
    (constant(1) -> ... -> graph_display), and
  * performs a real /api/save + /api/load round-trip through the production
    server (temp models dir, temp port) and re-runs the reloaded model.

Both Run and Save paths are exercised because runSim and saveModel both serialize
via toModelDict; the captured bodies are the very payloads the handlers send.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST = os.path.join(ROOT, "tests", "test_sync_fix.js")
MARKER = "ALL SYNC FIX REGRESSION TESTS PASSED"
RESULT_PREFIX = "SYNC_RESULT_JSON:"
TOL = 1e-9


def _run_js():
    """Run the JS harness and return (parsed_result_dict, raw_stdout)."""
    proc = subprocess.run(
        ["node", JS_TEST], cwd=ROOT,
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr
    assert MARKER in proc.stdout, "marker missing in JS output"
    line = next(l for l in proc.stdout.splitlines() if l.startswith(RESULT_PREFIX))
    return json.loads(line[len(RESULT_PREFIX):]), proc.stdout


class TestSyncFix(unittest.TestCase):
    """Frontend serialization + backend engine + live save/load round-trip."""

    @classmethod
    def setUpClass(cls):
        import sys
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        cls.result, _ = _run_js()
        cls.scenarios = cls.result["scenarios"]
        import xcos_mini.server as srv
        cls.srv = srv
        cls.tmpdir = tempfile.mkdtemp(prefix="xcos_sync_models_")
        cls._orig_models_dir = srv.MODELS_DIR
        srv.MODELS_DIR = cls.tmpdir
        os.makedirs(cls.tmpdir, exist_ok=True)
        cls.lib = srv.Library(blocks_dir=os.path.join(ROOT, "blocks"))
        srv.lib = cls.lib
        srv.Handler.lib = cls.lib
        from http.server import ThreadingHTTPServer
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.srv.MODELS_DIR = cls._orig_models_dir
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    # ---- helpers ---------------------------------------------------------
    def _model_for(self, scenario):
        sc = self.scenarios[scenario]
        return sc.get("run") or sc.get("model") or sc["save"]

    def _assert_runs_to_one(self, model, expect_ids=None):
        """Build via production code, run the Engine, assert sink series = 1.0."""
        import xcos_mini.core as core
        m = self.srv._build_model(self.lib, model)
        eng = core.Engine(m, t_end=1.0, h=0.01, method="rk4")
        results = eng.run()
        # Determine which blocks to check: explicit expect list, else all graph_display.
        if expect_ids is None:
            expect_ids = [str(b["id"]) for b in model["blocks"] if b["type"] == "graph_display"]
        self.assertTrue(expect_ids, "no sink block to check")
        n_steps = int(round(1.0 / 0.01))
        for bid in expect_ids:
            series = results.get(bid)
            self.assertIsNotNone(series, f"no result for sink {bid}")
            self.assertEqual(len(series), n_steps + 1, f"sink {bid} series not full length")
            for t, v in series:
                self.assertAlmostEqual(v, 1.0, delta=TOL, msg=f"sink {bid} @t={t} != 1.0")

    def _post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path):
        with urllib.request.urlopen(self.base + path) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ---- per-scenario engine checks ------------------------------------
    def test_s1_clear_rebuild_runs_to_one(self):
        """Load -> Clear -> rebuild constant(1)->graph_display: Run AND Save payloads run to 1.0."""
        for key in ("run", "save"):
            self._assert_runs_to_one(self.scenarios["s1_clear_rebuild"][key])

    def test_s2_delete_all_rebuild_runs_to_one(self):
        """Load -> delete all -> rebuild: Run AND Save payloads run to 1.0, no deleted refs."""
        for key in ("run", "save"):
            model = self.scenarios["s2_delete_all_rebuild"][key]
            ids = {str(b["id"]) for b in model["blocks"]}
            self.assertNotIn("b1", ids, "deleted block b1 must not appear")
            self.assertNotIn("b2", ids, "deleted block b2 must not appear")
            self._assert_runs_to_one(model)

    def test_s3_delete_one_block_runs_to_one(self):
        """Delete one connected block, unrelated wire preserved; surviving sink = 1.0."""
        model = self.scenarios["s3_delete_one_block"]["model"]
        ids = {str(b["id"]) for b in model["blocks"]}
        self.assertNotIn("b3", ids, "deleted block b3 must not appear")
        self.assertIn("b5", ids, "unrelated sink b5 preserved")
        self._assert_runs_to_one(model, expect_ids=["b5"])

    def test_s4_wire_replace_navigate_runs_to_one(self):
        """Delete old wire, add replacement, navigate out/back: payload runs to 1.0."""
        for key in ("run", "save"):
            self._assert_runs_to_one(self.scenarios["s4_wire_replace_navigate"][key], expect_ids=["b2"])

    def test_s5_two_subsystems_full_root_runs_to_one(self):
        """Edit one of two subsystems; Run/Save from inside still serializes full root; runs to 1.0."""
        for key in ("run", "save"):
            self._assert_runs_to_one(self.scenarios["s5_two_subsystems"][key], expect_ids=["gd", "gd2"])

    def test_s6_clear_inside_sub_runs_to_one(self):
        """Clear inside a subsystem -> new parent diagram: Run AND Save payloads run to 1.0."""
        for key in ("run", "save"):
            self._assert_runs_to_one(self.scenarios["s6_clear_inside_sub"][key])

    # ---- live save/load round-trip --------------------------------------
    def test_save_load_roundtrip_and_rerun(self):
        """Save a rebuilt diagram through the production server, reload, and re-run to 1.0."""
        model = self.scenarios["s1_clear_rebuild"]["save"]
        name = "sync_fix_disposable"
        res = self._post("/api/save", {"name": name, "model": model})
        self.assertEqual(res["saved"], name)
        loaded = self._get("/api/load?name=" + name)
        self.assertEqual(loaded["name"], name)
        self.assertEqual(loaded["model"], model, "reloaded model must equal saved model")
        # Re-run the freshly reloaded model through production Engine.
        self._assert_runs_to_one(loaded["model"])

    def test_flat_file_compatibility(self):
        """A plain flat constant(1)->gain(1)->graph_display model builds and runs to 1.0."""
        model = {
            "blocks": [
                {"id": "f1", "type": "constant", "params": {"value": 1}, "x": 50, "y": 50},
                {"id": "f2", "type": "gain", "params": {"k": 1}, "x": 300, "y": 50},
                {"id": "f3", "type": "graph_display", "params": {}, "x": 550, "y": 50},
            ],
            "connections": [
                {"from": "f1", "from_port": 0, "to": "f2", "to_port": 0},
                {"from": "f2", "from_port": 0, "to": "f3", "to_port": 0},
            ],
        }
        self._assert_runs_to_one(model, expect_ids=["f3"])


if __name__ == "__main__":
    unittest.main()
