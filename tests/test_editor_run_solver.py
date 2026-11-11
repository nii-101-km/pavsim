"""Behavioral tests for editor Run path with non-default solver settings.

Verifies that when runSim() wraps the inner diagram in a _run numerical block,
the solver settings (t_end, h, method) are passed through to the engine and
produce visibly different results. Also verifies graph_display result IDs
are accessible by inner block ID and plot data is collected.
"""
import json
import math
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


class SolverBase(unittest.TestCase):
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
        import urllib.request, urllib.error
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read()), e.code

    def _get(self, path):
        import urllib.request, urllib.error
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url) as resp:
                return json.loads(resp.read()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read()), e.code

    def _inner_model(self):
        """constant(1.0) -> first_order(tau=0.5) -> graph_display."""
        return {
            "blocks": [
                {"id": "c1", "type": "constant", "params": {"value": 1.0}, "x": 40, "y": 120},
                {"id": "fo1", "type": "first_order", "params": {"tau": 0.5, "gain": 1.0, "initial_value": 0.0}, "x": 200, "y": 120},
                {"id": "gd1", "type": "graph_display", "params": {"label": "out"}, "x": 360, "y": 120},
            ],
            "connections": [
                {"from": "c1", "fromPort": 0, "to": "fo1", "toPort": 0},
                {"from": "fo1", "fromPort": 0, "to": "gd1", "toPort": 0},
            ],
        }

    def _wrapped(self, t_end=1.0, h=0.01, method="rk4"):
        """The exact request shape the editor produces when inside a numerical block."""
        return {
            "model": {
                "blocks": [{"id": "_run", "type": "numerical",
                           "params": {"model": self._inner_model(), "t_end": t_end, "h": h, "method": method}}],
                "connections": []
            },
            "t_end": t_end, "h": h, "method": method
        }








if __name__ == "__main__":
    unittest.main()
