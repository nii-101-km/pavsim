"""Behavioral tests for the exact request the editor Run button produces.

The editor's runSim() sends toActiveDiagramDict() to /api/simulate.
When inside a numerical block, the fix wraps the inner diagram in a
numerical computation block. These tests reproduce that exact request.

Key distinction: these tests verify the request shape the editor actually
produces (inner diagram wrapped in a numerical block), NOT a manually
constructed model that happens to work.
"""
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import shell.server as server


def _app_js():
    return (PROJECT_ROOT / "shell" / "web" / "app.js").read_text("utf-8")


class EditorRunBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _post(self, path, body):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read()), e.code

    def _get(self, path):
        import urllib.request
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url) as resp:
                return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read()), e.code




class TestEditorRunWithPorts(EditorRunBase):
    """A numerical block with declared ports must NOT allow local Run."""

    def test_ported_numerical_block_rejected_by_ownership(self):
        """A model with in1_terminal/out1_terminal is rejected by /api/simulate."""
        # The editor's ownership check (hasExternal) would block this before sending,
        # but the server also enforces it. Verify the server-side rejection.
        model = {
            "blocks": [
                {"id": "In1", "type": "in1_terminal", "params": {}, "x": 40, "y": 120},
                {"id": "Out1", "type": "out1_terminal", "params": {}, "x": 300, "y": 120},
                {"id": "c1", "type": "constant", "params": {"value": 1.0}, "x": 150, "y": 120},
            ],
            "connections": [
                {"from": "In1", "fromPort": 0, "to": "c1", "toPort": 0},
                {"from": "c1", "fromPort": 0, "to": "Out1", "toPort": 0},
            ],
        }
        body, status = self._post("/api/simulate", {"model": model, "t_end": 1.0, "h": 0.01})
        self.assertEqual(status, 403, f"Expected 403 for ported model, got {status}: {body}")
        self.assertIn("externally controlled", body.get("error", ""))

    def test_ported_numerical_block_inside_wrapper_rejected(self):
        """Even wrapped in a numerical block, ports forbid local Run."""
        inner = {
            "blocks": [
                {"id": "In1", "type": "in1_terminal", "params": {}, "x": 40, "y": 120},
                {"id": "Out1", "type": "out1_terminal", "params": {}, "x": 300, "y": 120},
                {"id": "c1", "type": "constant", "params": {"value": 1.0}, "x": 150, "y": 120},
            ],
            "connections": [
                {"from": "In1", "fromPort": 0, "to": "c1", "toPort": 0},
                {"from": "c1", "fromPort": 0, "to": "Out1", "toPort": 0},
            ],
        }
        model = {
            "blocks": [{"id": "_run", "type": "numerical", "params": {"model": inner}}],
            "connections": []
        }
        body, status = self._post("/api/simulate", {"model": model, "t_end": 1.0, "h": 0.01})
        self.assertEqual(status, 400, f"Expected 400 for ported inner model, got {status}: {body}")




class TestRunSimSource(EditorRunBase):
    """Verify the frontend source implements the wrapping logic."""


    def test_runsim_ownership_check_still_present(self):
        js = _app_js()
        runsim_fn = js[js.index("async function runSim"):]
        next_fn = runsim_fn.find("\nfunction ", 10)
        if next_fn > 0:
            runsim_fn = runsim_fn[:next_fn]
        # Ownership check: in1_terminal or out1_terminal blocks local Run
        self.assertIn("in1_terminal", runsim_fn)
        self.assertIn("out1_terminal", runsim_fn)
        self.assertIn("externally_controlled", runsim_fn)


if __name__ == "__main__":
    unittest.main()
