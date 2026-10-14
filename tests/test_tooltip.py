"""Regression test for native connector tooltips (dynamic canvas title).

The tooltip logic lives in the GUI (xcos_mini/web/app.js). This test drives the
real app.js in a minimal DOM mock via Node (tests/test_tooltip.js) and asserts
that hovering each input/output connector sets the correct native title for
single-port, multi-port, input-only, output-only and filesystem-loaded blocks,
and that it stays correct after diagram reload and library refresh.
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST = os.path.join(ROOT, "tests", "test_tooltip.js")


class TestConnectorTooltips(unittest.TestCase):
    def test_node_available(self):
        self.assertIsNotNone(shutil.which("node"), "node is required for the GUI tooltip test")

    def test_tooltip_js(self):
        self.assertTrue(os.path.isfile(JS_TEST), "tests/test_tooltip.js is missing")
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "tooltip JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL TOOLTIP TESTS PASSED", proc.stdout)

    def test_app_js_wires_tooltip_to_port_hover(self):
        """Static guard: the tooltip div is driven by the port hit-test on mousemove
        and hidden on mouseleave (the dynamic HTML-tooltip mechanism)."""
        with open(os.path.join(ROOT, "xcos_mini", "web", "app.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("function portTooltip", src)
        self.assertIn("function updateCanvasTooltip", src)
        self.assertIn("portTooltipEl.classList.remove('hidden')", src)
        self.assertIn("portTooltipEl.classList.add('hidden')", src)
        self.assertIn("updateCanvasTooltip(p.x, p.y)", src)
        self.assertIn("canvas.addEventListener('mouseleave'", src)
        # The tooltip must be derived from the existing port hit-test, not hardcoded per block.
        self.assertIn("const port = portAt(x, y);", src)


if __name__ == "__main__":
    unittest.main()
