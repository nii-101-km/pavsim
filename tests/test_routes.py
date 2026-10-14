"""Tests for orthogonal editable connections (xcos_mini/web/app.js).

The routing logic lives in the GUI. This test drives the real app.js in a
minimal DOM mock via Node (tests/test_routes.js) and asserts: default
orthogonal route generation, segment dragging, bend dragging, endpoint
attachment after block moves, route serialization/restoration, legacy
loading without route metadata, connection creation/deletion, and fan-out.
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST = os.path.join(ROOT, "tests", "test_routes.js")
APP_JS = os.path.join(ROOT, "xcos_mini", "web", "app.js")


class TestOrthogonalRoutes(unittest.TestCase):
    def test_node_available(self):
        self.assertIsNotNone(shutil.which("node"), "node is required for the GUI route test")

    def test_routes_js(self):
        self.assertTrue(os.path.isfile(JS_TEST), "tests/test_routes.js is missing")
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "route JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL ROUTE TESTS PASSED", proc.stdout)

    def test_no_bezier_and_orthogonal_machinery(self):
        """Static guards: no Bezier drawing remains; orthogonal route generation,
        segment/bend dragging, block-move adjustment, segment hit-testing and
        route persistence are all wired into app.js."""
        with open(APP_JS, encoding="utf-8") as f:
            src = f.read()
        low = src.lower()
        self.assertNotIn("bezier", low, "Bézier connection code must be gone")
        self.assertNotIn("bezierto", low)
        self.assertNotIn("quadraticcurveto", low)
        for fn in ("function defaultRoute", "function routePoints", "function materializeRoute",
                   "function normalizeRoute", "function dragBend", "function dragSegment",
                   "function adjustRouteForBlockMove", "function hitRoute"):
            self.assertIn(fn, src)
        # Rendering uses the orthogonal polyline; hit-testing uses segment distance.
        self.assertIn("routePoints(c)", src)
        self.assertIn("hitRoute(state.connections[idx], x, y)", src)
        # Route metadata is persisted and restored.
        self.assertIn("o.route = c.route.map", src)
        self.assertIn("Array.isArray(c.route)", src)
        # Block moves adjust only the necessary route portion.
        self.assertIn("adjustRouteForBlockMove(c, d.block.id, ddx, ddy)", src)


if __name__ == "__main__":
    unittest.main()
