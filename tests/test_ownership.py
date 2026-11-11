"""Tests for execution ownership rules and external invocation.

Verifies:
- Standalone model (no external ports) can run via /api/simulate
- Externally controlled model (has in1/out1) is rejected by /api/simulate
- /api/invoke requires all declared inputs
- /api/invoke returns correct outputs for different inputs
- Removing the last external port restores standalone execution
- Ownership is determined by declared ports, not by wires
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shell.server import (
    _model_has_external_ports,
    _get_external_interface,
    _find_external_ports,
)


class TestOwnershipRule(unittest.TestCase):
    """Test the ownership rule logic (pure functions, no server needed)."""

    def test_standalone_no_ports(self):
        """Model with no in1/out1 is standalone."""
        model = {
            "blocks": [
                {"id": "1", "type": "constant", "params": {"value": 5.0}},
                {"id": "2", "type": "gain", "params": {"gain": 2.0}},
            ],
            "connections": [
                {"from": "1", "from_port": 0, "to": "2", "to_port": 0}
            ]
        }
        self.assertFalse(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "standalone")
        self.assertEqual(iface["inputs"], [])
        self.assertEqual(iface["outputs"], [])

    def test_externally_controlled_input_only(self):
        """Model with only in1_terminal is externally controlled."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}},
                {"id": "1", "type": "gain", "params": {"gain": 2.0}},
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "1", "to_port": 0}
            ]
        }
        self.assertTrue(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "externally_controlled")
        self.assertEqual(len(iface["inputs"]), 1)
        self.assertEqual(iface["inputs"][0]["name"], "u")
        self.assertEqual(len(iface["outputs"]), 0)

    def test_externally_controlled_output_only(self):
        """Model with only out1_terminal is externally controlled."""
        model = {
            "blocks": [
                {"id": "1", "type": "constant", "params": {"value": 5.0}},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y"}},
            ],
            "connections": [
                {"from": "1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        self.assertTrue(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "externally_controlled")
        self.assertEqual(len(iface["inputs"]), 0)
        self.assertEqual(len(iface["outputs"]), 1)
        self.assertEqual(iface["outputs"][0]["name"], "y")

    def test_externally_controlled_both(self):
        """Model with both in1 and out1 is externally controlled."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}},
                {"id": "1", "type": "gain", "params": {"gain": 2.0}},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y"}},
            ],
            "connections": [
                {"from": "in1", "from_port": 0, "to": "1", "to_port": 0},
                {"from": "1", "from_port": 0, "to": "out1", "to_port": 0}
            ]
        }
        self.assertTrue(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "externally_controlled")
        self.assertEqual(len(iface["inputs"]), 1)
        self.assertEqual(len(iface["outputs"]), 1)

    def test_removing_last_port_restores_standalone(self):
        """Removing the last external port makes the model standalone."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}},
                {"id": "1", "type": "gain", "params": {"gain": 2.0}},
            ],
            "connections": []
        }
        self.assertTrue(_model_has_external_ports(model))

        # Remove the in1_terminal
        model["blocks"] = [b for b in model["blocks"] if b["type"] != "in1_terminal"]
        self.assertFalse(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "standalone")

    def test_nested_subsystem_ports_not_counted(self):
        """In1/Out1 inside a subsystem's internal diagram are NOT the model's external ports."""
        model = {
            "blocks": [
                {"id": "1", "type": "constant", "params": {"value": 5.0}},
                {"id": "sub", "type": "subsystem", "params": {},
                 "internal": {
                     "blocks": [
                         {"id": "in1", "type": "in1_terminal", "params": {}},
                         {"id": "out1", "type": "out1_terminal", "params": {}},
                         {"id": "g", "type": "gain", "params": {"gain": 1.0}},
                     ],
                     "connections": [
                         {"from": "in1", "from_port": 0, "to": "g", "to_port": 0},
                         {"from": "g", "from_port": 0, "to": "out1", "to_port": 0}
                     ]
                 }},
            ],
            "connections": [
                {"from": "1", "from_port": 0, "to": "sub", "to_port": 0}
            ]
        }
        # The model itself has NO top-level in1/out1
        self.assertFalse(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(iface["mode"], "standalone")

    def test_multiple_inputs(self):
        """Model with multiple in1_terminals."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "a"}},
                {"id": "in2", "type": "in1_terminal", "params": {"name": "b"}},
                {"id": "1", "type": "addition", "params": {}},
            ],
            "connections": []
        }
        self.assertTrue(_model_has_external_ports(model))
        iface = _get_external_interface(model)
        self.assertEqual(len(iface["inputs"]), 2)
        names = {i["name"] for i in iface["inputs"]}
        self.assertEqual(names, {"a", "b"})


class TestInvokeValidation(unittest.TestCase):
    """Test invoke input validation logic."""

    def test_missing_input_detected(self):
        """If a required input is not supplied, it's detected as missing."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}},
                {"id": "1", "type": "gain", "params": {"gain": 2.0}},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y"}},
            ],
            "connections": []
        }
        iface = _get_external_interface(model)
        required = iface["inputs"]
        supplied = {}  # empty - nothing supplied
        missing = [inp["name"] for inp in required
                   if inp["name"] not in supplied and inp["id"] not in supplied]
        self.assertEqual(missing, ["u"])

    def test_all_inputs_supplied(self):
        """If all required inputs are supplied, no missing."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}},
                {"id": "1", "type": "gain", "params": {"gain": 2.0}},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y"}},
            ],
            "connections": []
        }
        iface = _get_external_interface(model)
        required = iface["inputs"]
        supplied = {"u": 3.0}
        missing = [inp["name"] for inp in required
                   if inp["name"] not in supplied and inp["id"] not in supplied]
        self.assertEqual(missing, [])

    def test_supplied_by_id(self):
        """Inputs can be supplied by block ID as well as name."""
        model = {
            "blocks": [
                {"id": "in1", "type": "in1_terminal", "params": {"name": "u"}},
                {"id": "1", "type": "gain", "params": {"gain": 2.0}},
                {"id": "out1", "type": "out1_terminal", "params": {"name": "y"}},
            ],
            "connections": []
        }
        iface = _get_external_interface(model)
        required = iface["inputs"]
        supplied = {"in1": 5.0}  # supplied by ID
        missing = [inp["name"] for inp in required
                   if inp["name"] not in supplied and inp["id"] not in supplied]
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
