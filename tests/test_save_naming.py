"""Regression tests: saved-diagram naming, selection, and refresh behavior.

Exercises the real production functions in app.js via Node.js VM sandbox.
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_TEST = os.path.join(ROOT, "tests", "test_save_naming.js")


class TestSaveNaming(unittest.TestCase):
    """Frontend naming/selection regression tests via Node.js."""

    def _run_js(self):
        proc = subprocess.run(
            ["node", JS_TEST], cwd=ROOT,
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0,
                         "JS test failed:\n" + proc.stdout + "\n" + proc.stderr)
        self.assertIn("ALL SAVE NAMING REGRESSION TESTS PASSED", proc.stdout)

    def test_node_available(self):
        self.assertIsNotNone(shutil.which("node"), "node is required")

    def test_load_sets_model_name(self):
        """Load diagram B while model_name contains A: save name becomes B."""
        self._run_js()

    def test_failed_load_preserves_state(self):
        """A failed load leaves the existing diagram and save name unchanged."""
        self._run_js()

    def test_save_selects_saved_name(self):
        """Save under C with other alphabetically earlier names: dropdown selects C."""
        self._run_js()

    def test_refresh_preserves_selection(self):
        """Refresh preserves B when B still exists."""
        self._run_js()

    def test_refresh_missing_fallback(self):
        """Missing and empty lists have sane fallbacks."""
        self._run_js()

    def test_failed_refresh_preserves_dropdown(self):
        """A failed refresh preserves the previous dropdown contents/selection."""
        self._run_js()

    def test_load_clears_stale_modes(self):
        """Loading still clears stale Add Bend/Reset Route and drag state."""
        self._run_js()


if __name__ == "__main__":
    unittest.main()
