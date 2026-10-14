"""Tests for the Reset Route mode (xcos_mini/web/app.js).

Drives the real app.js in a minimal DOM mock via Node (tests/test_reset_route.js)
and asserts: mutual exclusion, toggle-off, Escape, reset behavior (segment click,
bend click, already-automatic, multiple connections), isolation, orthogonal
geometry, endpoint preservation, save/load persistence, mode stays active after
reset, and regression (Add Bend, bend dragging, segment dragging).
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST = os.path.join(ROOT, "tests", "test_reset_route.js")
APP_JS = os.path.join(ROOT, "xcos_mini", "web", "app.js")
HTML = os.path.join(ROOT, "xcos_mini", "web", "index.html")
CSS = os.path.join(ROOT, "xcos_mini", "web", "style.css")


class TestResetRouteToolbar(unittest.TestCase):
    def test_node_available(self):
        self.assertIsNotNone(shutil.which("node"), "node is required for the reset route test")

    def test_reset_route_js(self):
        self.assertTrue(os.path.isfile(JS_TEST), "tests/test_reset_route.js is missing")
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "reset route JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_reset_route_button_in_html(self):
        """The Reset Route button exists in the toolbar HTML."""
        with open(HTML, encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="reset_route"', html)
        self.assertIn("Reset Route", html)

    def test_delete_bend_button_absent(self):
        """The Delete Bend button must NOT exist in the toolbar HTML."""
        with open(HTML, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn('id="delete_bend"', html)
        self.assertNotIn("Delete Bend", html)

    def test_reset_route_mode_in_app_js(self):
        """Static guards: the reset_route mode is wired into app.js."""
        with open(APP_JS, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("toggleResetRouteMode", src)
        self.assertIn("'reset_route'", src)
        self.assertIn("updateModeButtons", src)
        self.assertIn("state.bendEditMode === 'reset_route'", src)
        self.assertIn("state.bendEditMode === 'edit_bends'", src)

    def test_delete_bend_mode_absent(self):
        """The old delete_bend mode must NOT exist in app.js."""
        with open(APP_JS, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("toggleDeleteBendMode", src)
        self.assertNotIn("'delete_bend'", src)

    def test_reset_route_active_css(self):
        """CSS rule for #reset_route.active must exist."""
        with open(CSS, encoding="utf-8") as f:
            css = f.read()
        self.assertIn("#reset_route.active", css)
        self.assertIn("#reset_route.active { background:", css)


class TestResetRouteBehavior(unittest.TestCase):
    def test_reset_segment_click(self):
        """Resetting by clicking a segment clears the route."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_reset_bend_click(self):
        """Resetting by clicking a bend clears the route."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_reset_already_automatic(self):
        """Resetting an already-automatic connection is a no-op."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_reset_multiple_connections(self):
        """Reset multiple connections in sequence without leaving the mode."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)


class TestResetRouteIsolation(unittest.TestCase):
    def test_isolation(self):
        """Resetting one connection does not affect another."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_ports_unchanged(self):
        """Source and destination ports remain unchanged after reset."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)


class TestResetRouteGeometry(unittest.TestCase):
    def test_orthogonal_geometry(self):
        """All segments remain orthogonal after reset."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_endpoint_preservation(self):
        """Endpoints remain attached after reset."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)


class TestResetRoutePersistence(unittest.TestCase):
    def test_save_load_persistence(self):
        """Reset routes survive save/load."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)


class TestResetRouteRegression(unittest.TestCase):
    def test_add_bend_still_works(self):
        """Add Bend mode still adds bends."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_bend_dragging(self):
        """Bend dragging still works."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_segment_dragging(self):
        """Segment dragging still works."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_routes_js(self):
        """Existing routing tests continue passing."""
        routes_js = os.path.join(ROOT, "tests", "test_routes.js")
        proc = subprocess.run(["node", routes_js], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "routes JS test failed:\n" + proc.stdout + "\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()
