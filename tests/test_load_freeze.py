"""Regression tests: loading a diagram must not leave the editor frozen.

Root cause: fromModelDict() did not reset state.bendEditMode or state.drag.
When a user loaded a diagram while in Add Bend or Reset Route mode, the
mousedown handler's early-return for bendEditMode blocked all block and
empty-space interaction, making the canvas appear unresponsive.

Fix: fromModelDict() now resets bendEditMode, drag, and updates mode buttons.
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "xcos_mini", "web", "app.js")
JS_TEST = os.path.join(ROOT, "tests", "test_load_freeze.js")


class TestLoadFreezeFix(unittest.TestCase):
    """Verify the fix is present in app.js source."""

    def test_node_available(self):
        self.assertIsNotNone(shutil.which("node"), "node is required")

    def test_frommodeldict_resets_bendeditmode(self):
        """fromModelDict must reset state.bendEditMode."""
        with open(APP_JS, encoding="utf-8") as f:
            code = f.read()
        # The fix adds bendEditMode reset in fromModelDict
        self.assertIn("state.bendEditMode = null", code,
                      "fromModelDict must reset state.bendEditMode")

    def test_frommodeldict_resets_drag(self):
        """fromModelDict must reset state.drag."""
        with open(APP_JS, encoding="utf-8") as f:
            code = f.read()
        self.assertIn("state.drag = null", code,
                      "fromModelDict must reset state.drag")

    def test_frommodeldict_updates_mode_buttons(self):
        """fromModelDict must call updateModeButtons to sync UI."""
        with open(APP_JS, encoding="utf-8") as f:
            code = f.read()
        self.assertIn("updateModeButtons()", code,
                      "fromModelDict must call updateModeButtons()")


class TestLoadFreezeBehavior(unittest.TestCase):
    """Behavioral tests via Node.js VM sandbox."""

    def _run_js(self):
        proc = subprocess.run(
            ["node", JS_TEST], cwd=ROOT,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0,
                         "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL LOAD FREEZE REGRESSION TESTS PASSED", proc.stdout)

    def test_bendeditmode_reset_on_load(self):
        """Loading a diagram while in Add Bend mode must reset the mode."""
        self._run_js()

    def test_reset_route_mode_reset_on_load(self):
        """Loading a diagram while in Reset Route mode must reset the mode."""
        self._run_js()

    def test_drag_reset_on_load(self):
        """Loading a diagram must clear any stale drag state."""
        self._run_js()

    def test_canvas_interactive_after_load(self):
        """After loading, mousedown on a block must initiate drag."""
        self._run_js()

    def test_repeated_loads_no_accumulation(self):
        """Loading the same diagram repeatedly must not duplicate state."""
        self._run_js()

    def test_connections_preserved(self):
        """Loaded connections must be reconstructed correctly."""
        self._run_js()

    def test_manual_routes_preserved(self):
        """Loaded manual routes must remain intact."""
        self._run_js()


if __name__ == "__main__":
    unittest.main()
