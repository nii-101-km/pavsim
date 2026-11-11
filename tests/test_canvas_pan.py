"""Regression test for canvas panning (drag empty canvas to pan the view).

Verifies that the pan mechanism in app.js:
- initializes panX/panY to 0
- worldPos() correctly subtracts pan offset
- draw() uses ctx.translate for the pan offset
- mousedown on empty space starts pan drag
- mousemove during pan updates panX/panY
- window-level mouseup stops pan (even outside canvas)
- _panMoved guard prevents click action after pan
- pan is reset on model load
- block logical positions are NOT modified by panning
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST = os.path.join(ROOT, "tests", "test_canvas_pan.js")


class TestCanvasPan(unittest.TestCase):
    def test_node_available(self):
        self.assertIsNotNone(shutil.which("node"), "node is required for the canvas pan test")

    def test_canvas_pan_js(self):
        self.assertTrue(os.path.isfile(JS_TEST), "tests/test_canvas_pan.js is missing")
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "canvas pan JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL CANVAS PAN TESTS PASSED", proc.stdout)

    def test_pan_in_source(self):
        """Static guard: key pan-related code exists in app.js."""
        with open(os.path.join(ROOT, "xcos_mini", "web", "app.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("panX: 0, panY: 0", src)
        self.assertIn("function worldPos", src)
        self.assertIn("ctx.translate(state.panX, state.panY)", src)
        self.assertIn("state.panDrag", src)
        self.assertIn("window.addEventListener('mouseup'", src)
        self.assertIn("_panMoved", src)
