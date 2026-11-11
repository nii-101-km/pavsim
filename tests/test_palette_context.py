"""Regression tests for context-dependent palette switching.

Verifies that:
- The outer palette shows Shell + Computation (numerical wrapper) blocks
- The inner palette (inside a numerical block) shows numerical engine blocks
- enterSubsystem and exitSubsystem trigger palette reload
- The server provides /api/numerical/library for the inner palette
"""
import json
import os
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


class TestPaletteContextSource(unittest.TestCase):
    """Verify the frontend source implements context-aware palette switching."""

    def test_is_inside_numerical_function_exists(self):
        js = _app_js()
        self.assertIn("_isInsideNumerical", js)

    def test_load_library_uses_unified_endpoint(self):
        js = _app_js()
        # loadLibrary always fetches the unified /api/library (single source of truth)
        self.assertIn("api('/api/library')", js)
        # The old conditional endpoint selection must be gone
        self.assertNotIn("_isInsideNumerical() ? '/api/numerical/library' : '/api/library'", js)

    def test_enter_subsystem_renders_library(self):
        js = _app_js()
        # enterSubsystem re-renders the tree (re-marks unavailable blocks) without refetching
        enter_fn = js[js.index("function enterSubsystem"):js.index("function exitSubsystem")]
        self.assertIn("renderLibraryTree()", enter_fn)
        self.assertNotIn("loadLibrary()", enter_fn)

    def test_exit_subsystem_renders_library(self):
        js = _app_js()
        # exitSubsystem re-renders the tree (re-marks unavailable blocks) without refetching
        exit_fn = js[js.index("function exitSubsystem"):]
        # Find the next function boundary
        next_fn_idx = exit_fn.find("function ", 10)
        if next_fn_idx > 0:
            exit_fn = exit_fn[:next_fn_idx]
        self.assertIn("renderLibraryTree()", exit_fn)
        self.assertNotIn("loadLibrary()", exit_fn)


class TestNumericalLibraryEndpoint(unittest.TestCase):
    """Verify the server provides /api/numerical/library."""

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
        import urllib.request
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read())

    def test_numerical_library_returns_tree(self):
        data = self._get("/api/numerical/library")
        self.assertIn("tree", data)
        self.assertIsInstance(data["tree"], list)
        self.assertGreater(len(data["tree"]), 0)

    def test_numerical_library_has_categories(self):
        data = self._get("/api/numerical/library")
        categories = [n["name"] for n in data["tree"]]
        # Should have standard numerical categories
        self.assertIn("Dynamics", categories)
        self.assertIn("Math", categories)

    def test_outer_library_has_shell_and_computation(self):
        data = self._get("/api/library")
        categories = [n["name"] for n in data["tree"]]
        self.assertIn("Shell", categories)
        self.assertIn("Computation", categories)

    def test_outer_library_marks_numerical_blocks_unavailable(self):
        data = self._get("/api/library")
        # The unified library lists numerical blocks but marks them as
        # unavailable in the outer context (contexts=['numerical']).
        all_blocks = []
        for cat in data["tree"]:
            all_blocks.extend(cat.get("blocks", []))
        self.assertIn("first_order", all_blocks)
        self.assertIn("integrator", all_blocks)
        self.assertIn("gain", all_blocks)
        # Context metadata: numerical blocks are only placeable in 'numerical' context
        bc = data["block_contexts"]
        self.assertEqual(bc["first_order"], ["numerical"])
        self.assertEqual(bc["integrator"], ["numerical"])
        self.assertEqual(bc["gain"], ["numerical"])
        # Shell blocks are only placeable in 'outer' context
        self.assertEqual(bc["input_value"], ["outer"])
        self.assertNotIn("numerical", bc)
        # Subsystem is available only inside the dynamic-system engine.
        self.assertEqual(bc["subsystem"], ["numerical"])

    def test_outer_library_has_experiment(self):
        data = self._get("/api/library")
        all_blocks = []
        for cat in data["tree"]:
            all_blocks.extend(cat.get("blocks", []))
        self.assertIn("typed_experiment", all_blocks)


if __name__ == "__main__":
    unittest.main()
