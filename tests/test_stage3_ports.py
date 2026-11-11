"""Stage 3 regression tests: variable per-instance external ports.

Acceptance scenarios:
1. Two-input/two-output: a->gain(2)->out_a, b->gain(3)->out_b; values 3,5 -> 6,15
2. Reverse edge creation order: named results remain 6 and 15
3. Two instances with different port counts keep independent interfaces
4. Remove one required connection after successful run: next run fails clearly
5. Output-only and zero-port cases respect ownership
6. Save/load preserves embedded models, names, mappings, interfaces
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Stage3Base(unittest.TestCase):
    """Base class with server setup."""

    @classmethod
    def setUpClass(cls):
        import shell.server as srv
        cls.srv = srv
        cls.tmpdir = tempfile.mkdtemp(prefix="stage3_models_")
        cls._orig_models_dir = srv.MODELS_DIR
        srv.MODELS_DIR = Path(cls.tmpdir)
        os.makedirs(cls.tmpdir, exist_ok=True)
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

    def _post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))








class TestOwnership(Stage3Base):
    """Output-only and zero-port cases respect ownership."""

    def test_output_only_blocked(self):
        """A model with only out1_terminal is externally controlled (403)."""
        model = {
            "blocks": [
                {"id": "g", "type": "gain", "params": {"gain": 2.0}},
                {"id": "o", "type": "out1_terminal", "params": {"name": "y"}},
            ],
            "connections": [{"from": "g", "from_port": 0, "to": "o", "to_port": 0}],
        }
        status, body = self._post("/api/simulate", {"model": model})
        self.assertEqual(status, 403, f"Expected 403 for output-only, got {status}")


    def test_input_only_blocked(self):
        """A model with only in1_terminal is externally controlled (403)."""
        model = {
            "blocks": [
                {"id": "i", "type": "in1_terminal", "params": {"name": "u"}},
                {"id": "g", "type": "gain", "params": {"gain": 2.0}},
            ],
            "connections": [{"from": "i", "from_port": 0, "to": "g", "to_port": 0}],
        }
        status, body = self._post("/api/simulate", {"model": model})
        self.assertEqual(status, 403, f"Expected 403 for input-only, got {status}")


class TestSaveLoad(Stage3Base):
    """Save/load preserves embedded models, names, mappings, interfaces."""

    def test_save_load_roundtrip_preserves_ports(self):
        """Save a two-port model, load it, verify ports are preserved."""
        model = {
            "blocks": [
                {"id": "src", "type": "input_value", "params": {"value": 3.0}, "x": 0, "y": 0},
                {"id": "comp", "type": "numerical", "params": {
                    "model": {
                        "blocks": [
                            {"id": "i", "type": "in1_terminal", "params": {"name": "my_input"}},
                            {"id": "g", "type": "gain", "params": {"gain": 7.0}},
                            {"id": "o", "type": "out1_terminal", "params": {"name": "my_output"}},
                        ],
                        "connections": [
                            {"from": "i", "from_port": 0, "to": "g", "to_port": 0},
                            {"from": "g", "from_port": 0, "to": "o", "to_port": 0},
                        ],
                    },
                    "t_end": 0.5, "h": 0.05, "method": "euler",
                }, "x": 200, "y": 0},
                {"id": "disp", "type": "result_display", "params": {}, "x": 400, "y": 0},
            ],
            "connections": [
                {"from": "src", "from_port": 0, "to": "comp", "to_port": 0},
                {"from": "comp", "from_port": 0, "to": "disp", "to_port": 0},
            ],
        }
        # Save
        status, body = self._post("/api/save", {"name": "stage3_test", "model": model})
        self.assertEqual(status, 200, f"Save failed: {status}: {body}")

        # Load
        status, body = self._get("/api/load?name=stage3_test")
        self.assertEqual(status, 200, f"Load failed: {status}: {body}")
        loaded = body.get("model", {})

        # Verify the numerical block's embedded model is preserved
        comp_block = next(b for b in loaded["blocks"] if b["id"] == "comp")
        embedded = comp_block["params"]["model"]
        in1s = [b for b in embedded["blocks"] if b["type"] == "in1_terminal"]
        out1s = [b for b in embedded["blocks"] if b["type"] == "out1_terminal"]
        self.assertEqual(len(in1s), 1)
        self.assertEqual(in1s[0]["params"]["name"], "my_input")
        self.assertEqual(len(out1s), 1)
        self.assertEqual(out1s[0]["params"]["name"], "my_output")

        # Verify solver settings preserved
        self.assertEqual(comp_block["params"]["t_end"], 0.5)
        self.assertEqual(comp_block["params"]["h"], 0.05)
        self.assertEqual(comp_block["params"]["method"], "euler")





if __name__ == "__main__":
    unittest.main()
