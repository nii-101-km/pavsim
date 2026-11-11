"""Tests for the fixed outer optimizer (v2).

Verifies:
- evaluate_candidate uses the output at num_from_port as the scalar to minimize
- Different from_port values select different outputs
- Inner ISE is correctly computed and minimized
- Disabled optimizer runs baseline simulation
- No outer objective block required
"""
import json
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

class OuterOptV2Base(unittest.TestCase):
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

def _b(i, t, p=None):
    return {"id": i, "type": t, "params": p or {}}

def _c(a, z, port=0, source_port=0):
    return {"from": a, "to": z, "from_port": source_port, "to_port": port}

def _inner_single():
    """in1(Kp) -> gain -> first_order -> objective(ise) -> out1"""
    return {
        "blocks": [
            _b("in1", "in1_terminal", {"name": "Kp"}),
            _b("kp_gain", "gain", {"gain": 1.0}),
            _b("plant", "first_order", {"tau": 1.0, "gain": 1.0}),
            _b("obj", "objective", {"objective": "ise", "target": 1.0, "tolerance": 0.02}),
            _b("out1", "out1_terminal", {"name": "ise_score"}),
        ],
        "connections": [
            _c("in1", "kp_gain"), _c("kp_gain", "plant"),
            _c("plant", "obj"), _c("obj", "out1"),
        ],
    }

def _inner_two_out():
    """Two outputs: port0=ISE, port1=plant raw output"""
    return {
        "blocks": [
            _b("in1", "in1_terminal", {"name": "Kp"}),
            _b("kp_gain", "gain", {"gain": 1.0}),
            _b("plant", "first_order", {"tau": 1.0, "gain": 1.0}),
            _b("obj", "objective", {"objective": "ise", "target": 1.0, "tolerance": 0.02}),
            _b("out1", "out1_terminal", {"name": "ise_score"}),
            _b("out2", "out1_terminal", {"name": "plant_out"}),
        ],
        "connections": [
            _c("in1", "kp_gain"), _c("kp_gain", "plant"),
            _c("plant", "obj"), _c("obj", "out1"), _c("plant", "out2"),
        ],
    }

def _outer(inner, from_port=0, enabled=True, p1=0.1):
    return {
        "blocks": [
            _b("opt", "optimizer", {
                "enabled": enabled, "p1": p1, "p2": 0.0, "p3": 0.0,
                "optimize_p1": True, "optimize_p2": False, "optimize_p3": False,
                "min_p1": 0.0, "max_p1": 10.0, "max_evaluations": 50,
                "algorithm": "coordinate",
            }),
            _b("num", "numerical", {"model": inner, "t_end": 5.0, "h": 0.05, "method": "rk4"}),
        ],
        "connections": [
            _c("num", "opt", port=0, source_port=from_port),
            _c("opt", "num", source_port=0, port=0),
        ],
    }
