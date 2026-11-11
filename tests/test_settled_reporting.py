"""Behavioral test: unsettled response must not be reported as settled.

Verifies that the converged field in outer_optimize reports reflect
actual settling of the response at the setpoint, not a hardcoded True.
"""
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engines.numerical import NumericalEngineAdapter


def _make_inner_model(tau=1.0, delay=0.0, t_end=20.0, h=0.05):
    """Build a minimal inner model: PI -> first_order -> transport_delay -> objective."""
    return {
        "blocks": [
            {"id": "pi", "type": "pi", "params": {"initial_integral": 0}},
            {"id": "ref", "type": "constant", "params": {"value": 1.0}},
            {"id": "err", "type": "subtract", "params": {}},
            {"id": "plant", "type": "first_order", "params": {"tau": tau, "initial_value": 0, "gain": 1.0}},
            {"id": "delay", "type": "transport_delay", "params": {"tau": delay, "initial_value": 0}},
            {"id": "gd", "type": "graph_display", "params": {"label": "y"}},
            {"id": "kp", "type": "in1_terminal", "params": {"name": "Kp"}},
            {"id": "ki", "type": "in1_terminal", "params": {"name": "Ki"}},
            {"id": "obj", "type": "objective", "params": {"objective": "ise", "target": 1.0, "tolerance": 0.02}},
            {"id": "out", "type": "out1_terminal", "params": {"name": "ISE"}},
            {"id": "yout", "type": "out1_terminal", "params": {"name": "response"}},
        ],
        "connections": [
            {"from": "ref", "from_port": 0, "to": "err", "to_port": 0},
            {"from": "err", "from_port": 0, "to": "pi", "to_port": 0},
            {"from": "pi", "from_port": 0, "to": "plant", "to_port": 0},
            {"from": "plant", "from_port": 0, "to": "delay", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "gd", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "err", "to_port": 1},
            {"from": "kp", "from_port": 0, "to": "pi", "to_port": 1},
            {"from": "ki", "from_port": 0, "to": "pi", "to_port": 2},
            {"from": "delay", "from_port": 0, "to": "obj", "to_port": 0},
            {"from": "obj", "from_port": 0, "to": "out", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "yout", "to_port": 0},
        ],
    }


def _make_outer_model(inner, t_end=20.0, h=0.05):
    """Build outer model with optimizer + numerical block."""
    return {
        "blocks": [
            {"id": "opt", "type": "optimizer", "params": {
                "algorithm": "coordinate",
                "p1": 0.2, "p2": 0.1, "p3": 0.0,
                "optimize_p1": True, "optimize_p2": True, "optimize_p3": False,
                "min_p1": 0.01, "max_p1": 5.0,
                "min_p2": 0.01, "max_p2": 5.0,
                "max_evaluations": 60,
            }},
            {"id": "num", "type": "numerical", "params": {
                "model": inner, "t_end": t_end, "h": h, "method": "rk4",
            }},
        ],
        "connections": [
            {"from": "num", "from_port": 0, "to": "opt", "to_port": 0},
            {"from": "opt", "from_port": 0, "to": "num", "to_port": 0},
            {"from": "opt", "from_port": 1, "to": "num", "to_port": 1},
        ],
    }


class TestSettledReporting(unittest.TestCase):
    """Verify converged field reflects actual settling, not hardcoded True."""

    def test_unsettled_response_not_reported_settled(self):
        """A slow plant with short horizon should NOT be reported as settled."""
        adapter = NumericalEngineAdapter()
        # Very slow plant (tau=10) with short horizon (t_end=5): response
        # reaches only ~39% of target, clearly unsettled.
        inner = _make_inner_model(tau=10.0, t_end=5.0, h=0.05)
        model = _make_outer_model(inner, t_end=5.0, h=0.05)
        results, reports = adapter.outer_optimize(model)
        self.assertEqual(len(reports), 1)
        # The response is far from settling: converged must NOT be True
        self.assertFalse(reports[0]["converged"],
                         "Unsettled response must not be reported as settled/converged")

    def test_settled_response_reported_settled(self):
        """A fast plant with long horizon SHOULD be reported as settled."""
        adapter = NumericalEngineAdapter()
        # Fast plant (tau=0.5) with long horizon (t_end=20): response
        # settles well within tolerance.
        inner = _make_inner_model(tau=0.5, t_end=20.0, h=0.05)
        model = _make_outer_model(inner, t_end=20.0, h=0.05)
        results, reports = adapter.outer_optimize(model)
        self.assertEqual(len(reports), 1)
        # The response should settle: converged must be True
        self.assertTrue(reports[0]["converged"],
                        "Settled response should be reported as converged=True")



if __name__ == "__main__":
    unittest.main()


def _make_inner_model_multi_obj(tau=1.0, t_end=20.0, h=0.05):
    """Inner model with TWO objective blocks: one for ISE (feeds optimizer), one for IAE (unused)."""
    return {
        "blocks": [
            {"id": "pi", "type": "pi", "params": {"initial_integral": 0}},
            {"id": "ref", "type": "constant", "params": {"value": 1.0}},
            {"id": "err", "type": "subtract", "params": {}},
            {"id": "plant", "type": "first_order", "params": {"tau": tau, "initial_value": 0, "gain": 1.0}},
            {"id": "delay", "type": "transport_delay", "params": {"tau": 0.0, "initial_value": 0}},
            {"id": "gd", "type": "graph_display", "params": {"label": "y"}},
            {"id": "kp", "type": "in1_terminal", "params": {"name": "Kp"}},
            {"id": "ki", "type": "in1_terminal", "params": {"name": "Ki"}},
            # Two objective blocks: ISE (port 0, feeds optimizer) and IAE (port 1, unused)
            {"id": "obj_ise", "type": "objective", "params": {"objective": "ise", "target": 1.0, "tolerance": 0.02}},
            {"id": "obj_iae", "type": "objective", "params": {"objective": "iae", "target": 1.0, "tolerance": 0.02}},
            {"id": "out_ise", "type": "out1_terminal", "params": {"name": "ISE"}},
            {"id": "out_iae", "type": "out1_terminal", "params": {"name": "IAE"}},
        ],
        "connections": [
            {"from": "ref", "from_port": 0, "to": "err", "to_port": 0},
            {"from": "err", "from_port": 0, "to": "pi", "to_port": 0},
            {"from": "pi", "from_port": 0, "to": "plant", "to_port": 0},
            {"from": "plant", "from_port": 0, "to": "delay", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "gd", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "err", "to_port": 1},
            {"from": "kp", "from_port": 0, "to": "pi", "to_port": 1},
            {"from": "ki", "from_port": 0, "to": "pi", "to_port": 2},
            # Both objectives fed by the same plant response
            {"from": "delay", "from_port": 0, "to": "obj_ise", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "obj_iae", "to_port": 0},
            # ISE output (port 0) feeds optimizer
            {"from": "obj_ise", "from_port": 0, "to": "out_ise", "to_port": 0},
            # IAE output (port 1) unused
            {"from": "obj_iae", "from_port": 0, "to": "out_iae", "to_port": 0},
        ],
    }


def _make_inner_model_no_objective(tau=1.0, t_end=20.0, h=0.05):
    """Inner model where the output is NOT fed by an objective block (direct plant response)."""
    return {
        "blocks": [
            {"id": "pi", "type": "pi", "params": {"initial_integral": 0}},
            {"id": "ref", "type": "constant", "params": {"value": 1.0}},
            {"id": "err", "type": "subtract", "params": {}},
            {"id": "plant", "type": "first_order", "params": {"tau": tau, "initial_value": 0, "gain": 1.0}},
            {"id": "delay", "type": "transport_delay", "params": {"tau": 0.0, "initial_value": 0}},
            {"id": "gd", "type": "graph_display", "params": {"label": "y"}},
            {"id": "kp", "type": "in1_terminal", "params": {"name": "Kp"}},
            {"id": "ki", "type": "in1_terminal", "params": {"name": "Ki"}},
            # No objective block: output is the raw plant response (not a scalar score)
            {"id": "out", "type": "out1_terminal", "params": {"name": "response"}},
        ],
        "connections": [
            {"from": "ref", "from_port": 0, "to": "err", "to_port": 0},
            {"from": "err", "from_port": 0, "to": "pi", "to_port": 0},
            {"from": "pi", "from_port": 0, "to": "plant", "to_port": 0},
            {"from": "plant", "from_port": 0, "to": "delay", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "gd", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "err", "to_port": 1},
            {"from": "kp", "from_port": 0, "to": "pi", "to_port": 1},
            {"from": "ki", "from_port": 0, "to": "pi", "to_port": 2},
            {"from": "delay", "from_port": 0, "to": "out", "to_port": 0},
        ],
    }


class TestMultipleObjectives(unittest.TestCase):
    """Verify correct objective is selected when multiple exist."""

    def test_correct_objective_selected_by_output_port(self):
        """With two objectives, the one feeding the optimizer-connected output is used."""
        adapter = NumericalEngineAdapter()
        inner = _make_inner_model_multi_obj(tau=0.5, t_end=20.0, h=0.05)
        model = _make_outer_model(inner, t_end=20.0, h=0.05)
        results, reports = adapter.outer_optimize(model)
        self.assertEqual(len(reports), 1)
        # The ISE objective (port 0) feeds the optimizer; settling should be computed
        # from the plant response (same source for both objectives in this model).
        # With tau=0.5 and t_end=20, the response settles.
        self.assertTrue(reports[0]["converged"],
                        "Settled response with correct objective should report converged=True")

    def test_iae_objective_also_settles(self):
        """If the optimizer were connected to port 1 (IAE), settling should still work."""
        adapter = NumericalEngineAdapter()
        inner = _make_inner_model_multi_obj(tau=0.5, t_end=20.0, h=0.05)
        # Build outer model connecting to port 1 (IAE output)
        model = {
            "blocks": [
                {"id": "opt", "type": "optimizer", "params": {
                    "algorithm": "coordinate",
                    "p1": 0.2, "p2": 0.1, "p3": 0.0,
                    "optimize_p1": True, "optimize_p2": True, "optimize_p3": False,
                    "min_p1": 0.01, "max_p1": 5.0,
                    "min_p2": 0.01, "max_p2": 5.0,
                    "max_evaluations": 60,
                }},
                {"id": "num", "type": "numerical", "params": {
                    "model": inner, "t_end": 20.0, "h": 0.05, "method": "rk4",
                }},
            ],
            "connections": [
                {"from": "num", "from_port": 1, "to": "opt", "to_port": 0},
                {"from": "opt", "from_port": 0, "to": "num", "to_port": 0},
                {"from": "opt", "from_port": 1, "to": "num", "to_port": 1},
            ],
        }
        results, reports = adapter.outer_optimize(model)
        self.assertEqual(len(reports), 1)
        # IAE objective also fed by plant response; should settle
        self.assertTrue(reports[0]["converged"],
                        "IAE objective with settled response should report converged=True")


class TestUnknownSettling(unittest.TestCase):
    """Verify that when response cannot be identified, settled is None (unknown)."""

    def test_no_objective_gives_unknown_settling(self):
        """If the output is NOT fed by an objective block, settling must be None (unknown)."""
        adapter = NumericalEngineAdapter()
        inner = _make_inner_model_no_objective(tau=0.5, t_end=20.0, h=0.05)
        model = _make_outer_model(inner, t_end=20.0, h=0.05)
        results, reports = adapter.outer_optimize(model)
        self.assertEqual(len(reports), 1)
        # No objective block feeds the output → settling is unknown (None), not False
        self.assertIsNone(reports[0]["converged"],
                          "Unknown settling must be None, not False")


def _make_inner_model_diff_targets(tau=0.5, t_end=20.0, h=0.05):
    """Inner model with two objectives having DIFFERENT targets.

    obj_1 (port 0): target=1.0, tolerance=0.02 → response at 1.0 settles
    obj_2 (port 1): target=2.0, tolerance=0.1 → response at 1.0 does NOT settle
    """
    return {
        "blocks": [
            {"id": "pi", "type": "pi", "params": {"initial_integral": 0}},
            {"id": "ref", "type": "constant", "params": {"value": 1.0}},
            {"id": "err", "type": "subtract", "params": {}},
            {"id": "plant", "type": "first_order", "params": {"tau": tau, "initial_value": 0, "gain": 1.0}},
            {"id": "delay", "type": "transport_delay", "params": {"tau": 0.0, "initial_value": 0}},
            {"id": "gd", "type": "graph_display", "params": {"label": "y"}},
            {"id": "kp", "type": "in1_terminal", "params": {"name": "Kp"}},
            {"id": "ki", "type": "in1_terminal", "params": {"name": "Ki"}},
            # Two objectives with different targets
            {"id": "obj_1", "type": "objective", "params": {"objective": "ise", "target": 1.0, "tolerance": 0.02}},
            {"id": "obj_2", "type": "objective", "params": {"objective": "ise", "target": 2.0, "tolerance": 0.1}},
            {"id": "out_1", "type": "out1_terminal", "params": {"name": "score1"}},
            {"id": "out_2", "type": "out1_terminal", "params": {"name": "score2"}},
        ],
        "connections": [
            {"from": "ref", "from_port": 0, "to": "err", "to_port": 0},
            {"from": "err", "from_port": 0, "to": "pi", "to_port": 0},
            {"from": "pi", "from_port": 0, "to": "plant", "to_port": 0},
            {"from": "plant", "from_port": 0, "to": "delay", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "gd", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "err", "to_port": 1},
            {"from": "kp", "from_port": 0, "to": "pi", "to_port": 1},
            {"from": "ki", "from_port": 0, "to": "pi", "to_port": 2},
            {"from": "delay", "from_port": 0, "to": "obj_1", "to_port": 0},
            {"from": "delay", "from_port": 0, "to": "obj_2", "to_port": 0},
            {"from": "obj_1", "from_port": 0, "to": "out_1", "to_port": 0},
            {"from": "obj_2", "from_port": 0, "to": "out_2", "to_port": 0},
        ],
    }


class TestConnectedObjectiveResolution(unittest.TestCase):
    """Verify objective/target/tolerance are resolved from the connected objective block."""

    def test_port0_uses_obj1_target(self):
        """Optimizer connected to port 0 uses obj_1's target=1.0 → settled."""
        adapter = NumericalEngineAdapter()
        inner = _make_inner_model_diff_targets(tau=0.5, t_end=20.0, h=0.05)
        model = _make_outer_model(inner, t_end=20.0, h=0.05)
        results, reports = adapter.outer_optimize(model)
        self.assertEqual(len(reports), 1)
        # obj_1 has target=1.0; response settles at 1.0 → converged=True
        self.assertTrue(reports[0]["converged"],
                        "Port 0 (target=1.0): response at 1.0 should be settled")

    def test_port1_uses_obj2_target(self):
        """Optimizer connected to port 1 uses obj_2's target=2.0 → NOT settled.

        With the old code (obj_blocks[0]), this would incorrectly use obj_1's
        target=1.0 and report converged=True. The fix must use obj_2's target=2.0,
        making the response at 1.0 NOT settled (|1.0-2.0|=1.0 > band=0.2).
        """
        adapter = NumericalEngineAdapter()
        inner = _make_inner_model_diff_targets(tau=0.5, t_end=20.0, h=0.05)
        # Connect optimizer to port 1 (obj_2, target=2.0)
        model = {
            "blocks": [
                {"id": "opt", "type": "optimizer", "params": {
                    "algorithm": "coordinate",
                    "p1": 0.2, "p2": 0.1, "p3": 0.0,
                    "optimize_p1": True, "optimize_p2": True, "optimize_p3": False,
                    "min_p1": 0.01, "max_p1": 5.0,
                    "min_p2": 0.01, "max_p2": 5.0,
                    "max_evaluations": 60,
                }},
                {"id": "num", "type": "numerical", "params": {
                    "model": inner, "t_end": 20.0, "h": 0.05, "method": "rk4",
                }},
            ],
            "connections": [
                {"from": "num", "from_port": 1, "to": "opt", "to_port": 0},
                {"from": "opt", "from_port": 0, "to": "num", "to_port": 0},
                {"from": "opt", "from_port": 1, "to": "num", "to_port": 1},
            ],
        }
        results, reports = adapter.outer_optimize(model)
        self.assertEqual(len(reports), 1)
        # obj_2 has target=2.0; response settles at 1.0 → NOT within band → converged=False
        self.assertFalse(reports[0]["converged"],
                         "Port 1 (target=2.0): response at 1.0 should NOT be settled")



class TestUIUnknownStatus(unittest.TestCase):
    """Verify UI code distinguishes converged=null from false."""

    def _app_js(self):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / "shell" / "web" / "app.js").read_text()

    def _i18n(self):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / "shell" / "web" / "i18n-catalog.js").read_text()

    def test_app_js_has_three_way_converged_check(self):
        """app.js must use ===true and ===false checks, not a simple truthy test."""
        js = self._app_js()
        self.assertIn("r.converged===true", js)
        self.assertIn("r.converged===false", js)
        self.assertIn("t('status.unknown')", js)
        # The old pattern must be gone
        self.assertNotIn("t(r.converged?'status.converged':'status.not_converged')", js)

    def test_i18n_has_unknown_key_en(self):
        """i18n catalog must have status.unknown in English."""
        cat = self._i18n()
        self.assertIn('"status.unknown"', cat)
        self.assertIn("settling status unknown", cat)

    def test_i18n_has_unknown_key_ru(self):
        """i18n catalog must have status.unknown in Russian."""
        cat = self._i18n()
        self.assertIn("статус установления неизвестен", cat)
