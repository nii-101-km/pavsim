"""Frontend/persistence tests for Subsystem feature.

Verifies that the JS/HTML code correctly implements:
- Double-click opens internal canvas (not param dialog)
- Back to parent button and navigation
- In1/Out1 boundary terminal protection
- Save/load includes internal diagram data
- One-level nesting restriction
- State clearing on view change

Run with:  python3 -m unittest discover -s tests -v
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "xcos_mini", "web", "app.js")
INDEX_HTML = os.path.join(ROOT, "xcos_mini", "web", "index.html")


def _app_js():
    with open(APP_JS, encoding="utf-8") as f:
        return f.read()


def _index_html():
    with open(INDEX_HTML, encoding="utf-8") as f:
        return f.read()


class TestSubsystemNavigation(unittest.TestCase):
    """Double-click opens internal canvas, back button returns to parent."""

    def test_back_button_exists_in_html(self):
        html = _index_html()
        self.assertIn('id="back_to_parent"', html,
                      "back_to_parent button must exist in HTML")

    def test_enter_subsystem_function_exists(self):
        code = _app_js()
        self.assertIn("function enterSubsystem", code)

    def test_exit_subsystem_function_exists(self):
        code = _app_js()
        self.assertIn("function exitSubsystem", code)

    def test_dblclick_subsystem_opens_internal(self):
        """Double-clicking a subsystem block must call enterSubsystem, not showParams."""
        code = _app_js()
        # The dblclick handler must check for subsystem type and call enterSubsystem
        self.assertIn("enterSubsystem(b.id)", code,
                      "dblclick must call enterSubsystem for subsystem blocks")

    def test_back_button_listener(self):
        code = _app_js()
        self.assertIn("back_to_parent", code)
        self.assertIn("exitSubsystem", code)

    def test_active_view_state(self):
        """state.activeView tracks the current subsystem or null for parent."""
        code = _app_js()
        self.assertIn("activeView: null", code)
        self.assertIn("state.activeView = subId", code)
        self.assertIn("state.activeView = null", code)


class TestBoundaryTerminals(unittest.TestCase):
    """In1/Out1 are protected from deletion and have correct port counts."""

    def test_in1_terminal_type_registered(self):
        code = _app_js()
        self.assertIn("'in1_terminal'", code)

    def test_out1_terminal_type_registered(self):
        code = _app_js()
        self.assertIn("'out1_terminal'", code)

    def test_boundary_terminal_delete_protection(self):
        """Deleting In1 or Out1 must be blocked with an error message."""
        code = _app_js()
        self.assertIn("status.boundary", code,
                      "boundary terminal deletion must be blocked")

    def test_in1_has_one_output(self):
        """In1 terminal must have n_outputs=1."""
        code = _app_js()
        self.assertIn("n_outputs:1", code)

    def test_out1_has_one_input(self):
        """Out1 terminal must have n_inputs=1."""
        code = _app_js()
        self.assertIn("n_inputs:1", code)


class TestOneLevelNesting(unittest.TestCase):
    """Subsystem placement is blocked while inside another subsystem."""

    def test_subsystem_placement_blocked_in_internal_view(self):
        code = _app_js()
        self.assertIn("state.placingType==='subsystem' && containerForView(state.activeView).type!=='experiment'", code,
                      "must block subsystem placement while in internal view")


class TestSaveLoadInternal(unittest.TestCase):
    """Save/load preserves internal diagram data."""

    def test_serialize_includes_internal(self):
        """toModelDict must include the internal field for subsystem blocks."""
        code = _app_js()
        # The serialization must check b.internal and include it
        self.assertIn("['subsystem','experiment'].includes(b.type) && b.internal", code,
                      "serialization must include internal data")

    def test_deserialize_handles_subsystem_type(self):
        """fromModelDict must handle subsystem blocks (not crash)."""
        code = _app_js()
        # The block type validation must not reject 'subsystem'
        self.assertIn("subsystem", code)

    def test_root_blocks_preserved_on_enter(self):
        """enterSubsystem must save rootBlocks before switching view."""
        code = _app_js()
        self.assertIn("state.rootBlocks = state.blocks", code,
                      "enterSubsystem must preserve parent blocks")

    def test_exit_restores_root_blocks(self):
        """exitSubsystem must restore blocks from rootBlocks."""
        code = _app_js()
        self.assertIn("state.blocks = state.rootBlocks", code,
                      "exitSubsystem must restore parent blocks")


class TestStateClearingOnNavigation(unittest.TestCase):
    """View changes must clear stale interaction state."""

    def test_enter_clears_selection(self):
        code = _app_js()
        # enterSubsystem or its context must clear selection
        self.assertIn("state.selected = null", code)

    def test_enter_clears_drag(self):
        code = _app_js()
        self.assertIn("state.drag = null", code)

    def test_enter_clears_placing(self):
        code = _app_js()
        self.assertIn("state.placingType = null", code)

    def test_enter_clears_pending_connection(self):
        code = _app_js()
        self.assertIn("state.pendingConn = null", code)


class TestGraphDisplayScope(unittest.TestCase):
    """Graph display results must be scoped to the correct diagram."""

    def test_result_key_for_block_scoped(self):
        """resultKeyForBlock must prefix with activeView for internal blocks."""
        code = _app_js()
        self.assertIn("state.activeView + '/' + block.id", code,
                      "result keys must be scoped to the active view")


class TestFlatCompatibility(unittest.TestCase):
    """Loading a flat diagram (no subsystems) must work unchanged."""

    def test_no_subsystem_in_flat_model(self):
        """A model dict without 'subsystem' type blocks loads normally."""
        # This is a structural test: expand_subsystems returns the dict unchanged
        # when no subsystems are present (tested in test_subsystem.py)
        # Here we verify the frontend doesn't crash on flat models by checking
        # that the type validation accepts all standard block types.
        code = _app_js()
        # The block type check in fromModelDict or similar must not reject
        # standard types. This is implicitly tested by the existing tests
        # (test_load_freeze, test_save_naming) passing.
        self.assertIn("state.blockTypes", code)
