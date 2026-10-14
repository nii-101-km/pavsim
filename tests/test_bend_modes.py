"""Tests for Add Bend / Reset Route toolbar modes.

Covers: toolbar labels, active-state styling, interaction separation,
geometry preservation, and regression.
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "xcos_mini", "web", "index.html")
CSS = os.path.join(ROOT, "xcos_mini", "web", "style.css")
APP_JS = os.path.join(ROOT, "xcos_mini", "web", "app.js")
JS_TEST = os.path.join(ROOT, "tests", "test_reset_route.js")


class TestToolbarLabels(unittest.TestCase):
    def test_add_bend_label_exists(self):
        with open(HTML, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Add Bend", html, "'Add Bend' label must be in the toolbar")

    def test_reset_route_label_exists(self):
        with open(HTML, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Reset Route", html, "'Reset Route' label must be in the toolbar")

    def test_delete_bend_label_absent(self):
        with open(HTML, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("Delete Bend", html, "'Delete Bend' label must NOT be displayed")

    def test_edit_bends_label_removed(self):
        with open(HTML, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("Edit Bends", html, "'Edit Bends' label must NOT be displayed")


class TestActiveStateStyling(unittest.TestCase):
    def test_edit_bends_active_css(self):
        with open(CSS, encoding="utf-8") as f:
            css = f.read()
        self.assertIn("#edit_bends.active", css, "CSS rule for #edit_bends.active must exist")

    def test_reset_route_active_css(self):
        with open(CSS, encoding="utf-8") as f:
            css = f.read()
        self.assertIn("#reset_route.active", css, "CSS rule for #reset_route.active must exist")

    def test_both_active_rules_have_visual_styling(self):
        with open(CSS, encoding="utf-8") as f:
            css = f.read()
        # Both rules must set a background (visual highlight)
        self.assertIn("#edit_bends.active { background:", css)
        self.assertIn("#reset_route.active { background:", css)


class TestModeSeparation(unittest.TestCase):
    def test_node_available(self):
        self.assertIsNotNone(shutil.which("node"), "node is required")

    def test_add_bend_does_not_reset(self):
        """In Add Bend (edit_bends) mode, clicking a segment must NOT reset the route."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_reset_route_does_not_add(self):
        """In Reset Route mode, clicking a segment must NOT add a bend."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_add_bend_can_add(self):
        """In Add Bend mode, clicking a segment DOES add a bend."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_reset_route_can_reset(self):
        """In Reset Route mode, clicking a connection DOES reset its route."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)


class TestModeSwitching(unittest.TestCase):
    def test_mutual_exclusion(self):
        """Activating one mode must deactivate the other."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_escape_disables_both(self):
        """Escape must disable both modes."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_toggle_off(self):
        """Clicking the active button must disable it."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)


class TestGeometryAndPersistence(unittest.TestCase):
    def test_orthogonal_geometry(self):
        """All resulting segments remain orthogonal after reset."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_endpoint_preservation(self):
        """Connection endpoints remain attached after reset."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_save_load_persistence(self):
        """Reset routes survive save/load."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)


class TestRegression(unittest.TestCase):
    def test_bend_dragging(self):
        """Existing bend dragging continues to work."""
        proc = subprocess.run(["node", JS_TEST], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL RESET ROUTE TESTS PASSED", proc.stdout)

    def test_segment_dragging(self):
        """Existing segment dragging continues to work."""
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
