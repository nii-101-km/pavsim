"""Numerical simulation engine adapter.

This module is the ONLY place that imports xcos_mini. The shell server
interacts with this adapter through a well-defined interface (NumericalEngineAdapter).

NumericalEngineAdapter provides the dynamic-system interface for the shell.
"""

import copy
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

class NumericalEngineAdapter:
    """Adapter providing numerical simulation capabilities to the shell server.

    This is the ONLY class that imports xcos_mini. The shell server
    interacts with this through a clean interface without knowing
    about xcos_mini internals.
    """

    def __init__(self, blocks_dir=None):
        self._blocks_dir = blocks_dir or str(PROJECT_ROOT / "blocks")
        self._lib = None
        self._available = None  # lazy check

    @property
    def available(self):
        """Check if the numerical engine is available."""
        if self._available is None:
            try:
                self._get_lib()
                self._available = True
            except (ImportError, Exception):
                self._available = False
        return self._available

    def _get_lib(self):
        """Get or create the xcos_mini Library."""
        if self._lib is None:
            from xcos_mini.core import Library
            self._lib = Library(blocks_dir=self._blocks_dir)
        return self._lib

    def get_blocks(self):
        """Return block descriptions for the block library."""
        lib = self._get_lib()
        return lib.describe()

    def get_library_tree(self):
        """Return the library tree (categories with block names)."""
        lib = self._get_lib()
        tree = []
        for category, blocks in lib.categories().items():
            tree.append({"name": category, "type": "category", "blocks": blocks})
        return tree

    def get_load_errors(self):
        """Return any block load errors."""
        try:
            return list(self._get_lib().load_errors)
        except Exception:
            return []

    def reload_blocks(self):
        """Reload the blocks directory."""
        try:
            self._get_lib().reload_blocks_dir(self._blocks_dir)
        except Exception:
            pass

    def get_block_params(self, block_type):
        """Get parameter names and defaults for a block type."""
        try:
            lib = self._get_lib()
            block_def = lib.get(block_type)
            return dict(block_def.parameters)
        except Exception:
            return {}

    def simulate(self, model_dict, t_end=1.0, h=0.01, method="rk4", experiment=None, *, trial_resources=None, cancel_check=None):
        """Run a simulation and return serialized results.

        Args:
            model_dict: model dict with blocks and connections
            t_end: simulation end time
            h: step size
            method: "rk4" or "euler"
            experiment: optional experiment selection

        Returns:
            dict with keys: results, optimization, experiments, n_steps

        Raises:
            ValueError: if parameters are invalid
            RuntimeError: if engine is not available
        """
        if not self.available:
            raise RuntimeError("Numerical engine not available.")

        from xcos_mini.core import Engine, Model, BlockError
        from xcos_mini.subsystem import expand_subsystems
        from xcos_mini.experiments import execute_workspace
        from xcos_mini.optimization import finite

        # Validate params
        if isinstance(t_end, bool) or isinstance(h, bool):
            raise ValueError("t_end and h must be finite numbers, not booleans.")
        t_end = finite(t_end, "t_end")
        h = finite(h, "h")
        if t_end < 0 or h <= 0 or not math.isfinite(t_end / h):
            raise ValueError("t_end must be non-negative and h positive, with finite t_end/h.")

        lib = self._get_lib()

        def build_candidate(candidate):
            flat = expand_subsystems(candidate)
            m = Model()
            for b in flat.get("blocks", []):
                bid = str(b["id"])
                block = lib.instantiate(b["type"])
                if trial_resources is not None:
                    trial_resources.add(block)
                for k, v in b.get("params", {}).items():
                    block.params[k] = v
                m.add_block(block, bid, b.get("x", 0), b.get("y", 0))
            for c in flat.get("connections", []):
                m.add_connection(
                    str(c["from"]), int(c.get("from_port", 0)),
                    str(c["to"]), int(c.get("to_port", 0)),
                )
            return m

        results, tuning, experiments = execute_workspace(
            model_dict, build_candidate, t_end, h, method,
            selected=experiment, cancel_check=cancel_check
        )

        serialized = self._serialize_results(results)
        n_steps = max((len(s) - 1 for s in results.values()), default=0) if not experiments else 1

        return {
            "results": serialized,
            "optimization": tuning,
            "experiments": experiments,
            "n_steps": n_steps,
        }

    def invoke(self, model_dict, inputs, t_end=1.0, h=0.01, method="rk4"):
        """Run a model with input overrides and return outputs.

        Supports two mechanisms for external ports:
        1. Signal injection (default): in1_terminal replaced with constant source,
           out1_terminal extracts from its feeder.
        2. Parameter/result mapping: in1_terminal with mapping="block_id.param"
           sets that parameter; out1_terminal with mapping="block_id" extracts
           the result from that block.

        Args:
            model_dict: model dict with blocks and connections
            inputs: dict of input_name -> value (all required inputs)
            t_end, h, method: simulation parameters

        Returns:
            dict with keys: outputs, results

        Raises:
            ValueError: if inputs are missing or invalid
        """
        if not self.available:
            raise RuntimeError("Numerical engine not available.")

        # Find in1/out1 terminals
        blocks = model_dict.get("blocks", [])
        connections = model_dict.get("connections", [])

        in1_blocks = [b for b in blocks if b.get("type") == "in1_terminal"]
        out1_blocks = [b for b in blocks if b.get("type") == "out1_terminal"]

        if not in1_blocks and not out1_blocks:
            raise ValueError("Model has no external ports. Use simulate() for standalone models.")

        # Validate all required inputs supplied
        missing = []
        for idx, inp in enumerate(in1_blocks):
            name = inp.get("params", {}).get("name", f"input_{idx+1}")
            inp_id = str(inp["id"])
            if name not in inputs and inp_id not in inputs:
                missing.append(name)
        if missing:
            raise ValueError(f"Missing required input(s): {', '.join(missing)}")

        # Prepare model: handle in1 terminals (mapping or signal injection)
        model = copy.deepcopy(model_dict)
        m_blocks = model.get("blocks", [])
        m_connections = model.get("connections", [])

        # Track which in1 blocks use mapping vs signal injection
        mapped_in1_ids = set()
        for idx, inp in enumerate(in1_blocks):
            inp_id = str(inp["id"])
            name = inp.get("params", {}).get("name", f"input_{idx+1}")
            value = inputs.get(name, inputs.get(inp_id, 0.0))
            mapping = inp.get("params", {}).get("mapping", "")

            if mapping:
                # Parameter mapping: set the target block's parameter
                parts = mapping.split(".", 1)
                target_id = parts[0]
                target_param = parts[1] if len(parts) > 1 else None
                if target_param:
                    for b in m_blocks:
                        if str(b["id"]) == target_id:
                            b.setdefault("params", {})[target_param] = value
                            break
                    else:
                        raise ValueError(f"Mapping target block '{target_id}' not found in model.")
                else:
                    raise ValueError(f"Invalid mapping '{mapping}': expected 'block_id.param_name'.")
                mapped_in1_ids.add(inp_id)
            else:
                # Signal injection: replace with constant source
                for b in m_blocks:
                    if str(b["id"]) == inp_id:
                        b["type"] = "constant"
                        b["params"] = {"value": value}
                        break

        # Track output extraction: mapping or signal extraction
        out1_sources = {}
        out1_mapped = {}  # name -> target_block_id
        for out in out1_blocks:
            out_id = str(out["id"])
            name = out.get("params", {}).get("name", f"output_{out1_blocks.index(out)+1}")
            mapping = out.get("params", {}).get("mapping", "")

            if mapping:
                # Result mapping: extract from the mapped block
                out1_mapped[name] = mapping
            else:
                # Signal extraction: extract from feeder
                feeding = [c for c in m_connections if str(c["to"]) == out_id]
                if feeding:
                    out1_sources[name] = {
                        "src_id": str(feeding[0]["from"]),
                        "src_port": int(feeding[0].get("from_port", 0)),
                    }

        # Remove out1 blocks and their incoming connections
        out1_ids = {str(o["id"]) for o in out1_blocks}
        model["blocks"] = [b for b in m_blocks if str(b["id"]) not in out1_ids]
        model["connections"] = [c for c in m_connections if str(c["to"]) not in out1_ids]

        # Also remove mapped in1 blocks (they're not needed as signal sources)
        if mapped_in1_ids:
            model["blocks"] = [b for b in model["blocks"] if str(b["id"]) not in mapped_in1_ids]
            model["connections"] = [c for c in model["connections"] if str(c["from"]) not in mapped_in1_ids]

        # Run simulation
        sim_result = self.simulate(model, t_end, h, method)
        serialized = sim_result["results"]

        # Extract outputs
        outputs = {}
        # Signal-extracted outputs
        for name, src_info in out1_sources.items():
            src_id = src_info["src_id"]
            src_port = src_info["src_port"]
            if src_id in serialized:
                data = serialized[src_id]
                if "outputs" in data and src_port < len(data["outputs"]):
                    series = data["outputs"][src_port]
                    outputs[name] = series[-1] if series else None
                elif "y" in data:
                    outputs[name] = data["y"][-1] if data["y"] else None
                else:
                    outputs[name] = None
            else:
                outputs[name] = None
        # Mapped outputs (extract from target block)
        for name, target_id in out1_mapped.items():
            if target_id in serialized:
                data = serialized[target_id]
                if "y" in data:
                    outputs[name] = data["y"][-1] if data["y"] else None
                elif "outputs" in data and data["outputs"]:
                    outputs[name] = data["outputs"][0][-1] if data["outputs"][0] else None
                else:
                    outputs[name] = None
            else:
                outputs[name] = None

        return {"outputs": outputs, "results": serialized}


    def optimize(self, model_dict, settings=None):
        """Run optimization on a model.

        Args:
            model_dict: model dict with blocks and connections
            settings: optional optimization settings

        Returns:
            dict with optimization results

        Raises:
            ValueError: if parameters are invalid
            RuntimeError: if engine is not available
        """
        if not self.available:
            raise RuntimeError("Numerical engine not available.")

        from xcos_mini.optimization import optimize
        from xcos_mini.subsystem import expand_subsystems
        from xcos_mini.core import Model

        lib = self._get_lib()

        def build_candidate(candidate):
            flat = expand_subsystems(candidate)
            m = Model()
            for b in flat.get("blocks", []):
                block = lib.instantiate(b["type"])
                for k, v in b.get("params", {}).items():
                    block.params[k] = v
                m.add_block(block, str(b["id"]), b.get("x", 0), b.get("y", 0))
            for c in flat.get("connections", []):
                m.add_connection(str(c["from"]), int(c.get("from_port", 0)),
                               str(c["to"]), int(c.get("to_port", 0)))
            return m

        return optimize(model_dict, build_candidate, settings or {})

    def outer_optimize(self, model_dict):
        """Handle outer-level optimizer blocks that invoke a numerical block.

        The optimizer repeatedly invokes the connected numerical block with
        candidate parameter values and minimizes the scalar objective computed
        by the objective block inside the numerical block's inner model.

        Returns:
            tuple: (results_dict, reports_list)
        """
        if not self.available:
            raise RuntimeError("Numerical engine not available for optimization.")

        import copy as _copy
        from xcos_mini.optimization import (
            finite, ALGORITHM_DEFAULTS, algorithm_options, OBJECTIVES,
            optimize as _optimize, response_metrics, objective_score,
        )
        from xcos_mini.optimization_blocks import Optimizer, Objective
        from xcos_mini.core import BlockError

        blocks = model_dict.get("blocks", [])
        connections = model_dict.get("connections", [])
        optimizers = [b for b in blocks if b.get("type") == "optimizer"]
        if not optimizers:
            raise ValueError("No optimizer blocks found in model.")

        reports = []
        prepared = _copy.deepcopy(model_dict)

        for opt_block in optimizers:
            opt_id = str(opt_block["id"])
            defaults = dict(Optimizer.parameters)
            defaults.update(opt_block.get("params", {}))

            if not defaults.get("enabled", True):
                continue

            # Find the numerical block whose output feeds the optimizer's J input
            j_wires = [c for c in connections if str(c["to"]) == opt_id and int(c.get("to_port", 0)) == 0]
            if len(j_wires) != 1:
                raise ValueError(f"Optimizer {opt_id}: must have exactly one J input connection.")
            num_id = str(j_wires[0]["from"])
            num_from_port = int(j_wires[0].get("from_port", 0))
            num_block = next((b for b in blocks if str(b["id"]) == num_id), None)
            if num_block is None or num_block.get("type") != "numerical":
                raise ValueError(f"Optimizer {opt_id}: J input must come from a numerical block.")

            inner_model = num_block.get("params", {}).get("model")
            if inner_model is None or not isinstance(inner_model, dict):
                raise ValueError(f"Numerical block {num_id} has no inner model.")

            # Determine mapping: optimizer output port -> numerical input port
            opt_to_num = [c for c in connections if str(c["from"]) == opt_id and str(c["to"]) == num_id]
            if not opt_to_num:
                raise ValueError(f"Optimizer {opt_id}: no outputs connected to numerical block {num_id}.")
            ports = sorted(int(c.get("from_port", 0)) for c in opt_to_num)
            if ports != list(range(len(ports))) or len(ports) > 3:
                raise ValueError("Optimizer connections must use consecutive distinct outputs starting at p1.")

            # Get inner model's input port names
            inner_blocks = inner_model.get("blocks", [])
            in1_blocks = [b for b in inner_blocks if b.get("type") == "in1_terminal"]
            in1_names = [b.get("params", {}).get("name", f"input_{i+1}") for i, b in enumerate(in1_blocks)]

            # Map optimizer output ports to input names
            mapping = sorted(opt_to_num, key=lambda c: int(c.get("from_port", 0)))
            param_names = []
            for c in mapping:
                num_port = int(c.get("to_port", 0))
                if num_port < len(in1_names):
                    param_names.append(in1_names[num_port])
                else:
                    param_names.append(str(num_port))

            # Get solver settings from the numerical block
            num_params = num_block.get("params", {})
            t_end = finite(num_params.get("t_end", 1.0), "t_end")
            h = finite(num_params.get("h", 0.01), "h")
            method = num_params.get("method", "rk4")

            # Objective parameters: resolve from the objective block connected to
            # the optimizer's J input (via the out1_terminal at num_from_port).
            # If no objective block feeds that output, use defaults.
            inner_connections = inner_model.get("connections", [])
            out1_blocks_inner = [b for b in inner_blocks if b.get("type") == "out1_terminal"]
            connected_objective = None
            if num_from_port < len(out1_blocks_inner):
                out1_id = str(out1_blocks_inner[num_from_port]["id"])
                feeding = [c for c in inner_connections if str(c["to"]) == out1_id]
                if feeding:
                    src_id = str(feeding[0]["from"])
                    src_block = next((b for b in inner_blocks if str(b["id"]) == src_id), None)
                    if src_block and src_block.get("type") == "objective":
                        connected_objective = src_block
            if connected_objective is not None:
                obj_defaults = dict(Objective.parameters)
                obj_defaults.update(connected_objective.get("params", {}))
                objective = obj_defaults.get("objective", "ise")
                target = finite(obj_defaults.get("target", 1.0), "target")
                tolerance = finite(obj_defaults.get("tolerance", 0.02), "tolerance")
            else:
                objective = "ise"
                target = 1.0
                tolerance = 0.02

            # Build intervals from optimizer parameters
            intervals = []
            for i in range(1, 4):
                current = finite(defaults.get(f"p{i}", 0.0), f"p{i}")
                if defaults.get(f"optimize_p{i}", False):
                    intervals.append([finite(defaults.get(f"min_p{i}", 0.0), f"min_p{i}"),
                                     finite(defaults.get(f"max_p{i}", 5.0), f"max_p{i}")])
                else:
                    intervals.append([current, current])

            n_mapped = len(param_names)
            active_intervals = intervals[:n_mapped]

            # Validate algorithm
            algorithm = defaults.get("algorithm", "coordinate")
            if algorithm not in ALGORITHM_DEFAULTS:
                raise ValueError(f"Unknown optimization algorithm: {algorithm}")
            options = algorithm_options(algorithm, defaults.get("algorithm_options", ""))

            max_evaluations = int(finite(defaults.get("max_evaluations", 100), "max_evaluations"))
            if not 20 <= max_evaluations <= 300:
                raise ValueError("max_evaluations must be between 20 and 300.")

            # Build the evaluate closure
            adapter = self
            inner_model_ref = inner_model
            t_end_ref = t_end
            h_ref = h
            method_ref = method
            param_names_ref = param_names
            num_from_port_ref = num_from_port
            n_mapped_ref = n_mapped

            def evaluate_candidate(candidate_model):
                """Invoke the numerical block with candidate values and return (metrics, series, score).

                The score is the scalar output at the port selected by num_from_port
                (the J input connection's from_port). This is the exposed scalar
                that the optimizer minimizes directly.
                """
                opt_in_candidate = next(b for b in candidate_model["blocks"] if str(b["id"]) == opt_id)
                values = [opt_in_candidate.get("params", {}).get(f"p{i}", 0.0) for i in range(1, 4)][:n_mapped_ref]
                inputs = {param_names_ref[i]: values[i] for i in range(n_mapped_ref)}
                result = adapter.invoke(inner_model_ref, inputs, t_end_ref, h_ref, method_ref)

                # Select the output at num_from_port (the port feeding the optimizer J input)
                out1_blocks_ref = [b for b in inner_model_ref.get("blocks", []) if b.get("type") == "out1_terminal"]
                if num_from_port_ref >= len(out1_blocks_ref):
                    raise ValueError(f"num_from_port {num_from_port_ref} out of range for {len(out1_blocks_ref)} outputs.")
                out_name = out1_blocks_ref[num_from_port_ref].get("params", {}).get("name", f"output_{num_from_port_ref+1}")

                outputs = result.get("outputs", {})
                if out_name not in outputs or outputs[out_name] is None:
                    raise ValueError(f"Output '{out_name}' not found in invoke results.")
                score = float(outputs[out_name])

                # Get the series for the record (from the source block feeding this output)
                results_data = result.get("results", {})
                m_connections = inner_model_ref.get("connections", [])
                out1_id = str(out1_blocks_ref[num_from_port_ref]["id"])
                feeding = [c for c in m_connections if str(c["to"]) == out1_id]
                series = []
                if feeding:
                    src_id = str(feeding[0]["from"])
                    if src_id in results_data:
                        data = results_data[src_id]
                        series = list(zip(data.get("t", []), data.get("y", [])))
                if not series:
                    series = [(0.0, score)]

                # Resolve the plant response series for settling computation.
                # Trace from the out1_terminal connected to the optimizer back
                # through the objective block to find the actual response signal.
                # If the response cannot be identified, settled is None (unknown).
                response_series = None
                if feeding:
                    feeder_id = str(feeding[0]["from"])
                    feeder_block = next((b for b in inner_model_ref.get("blocks", []) if str(b["id"]) == feeder_id), None)
                    if feeder_block and feeder_block.get("type") == "objective":
                        # The output is fed by an objective block; trace its input for the response.
                        obj_feeding = [c for c in m_connections if str(c["to"]) == feeder_id]
                        if obj_feeding:
                            resp_src_id = str(obj_feeding[0]["from"])
                            if resp_src_id in results_data:
                                rdata = results_data[resp_src_id]
                                response_series = list(zip(rdata.get("t", []), rdata.get("y", [])))

                # Compute settling metrics from the response series.
                # If response_series is None, settling is unknown (None).
                if response_series is not None and len(response_series) >= 2:
                    try:
                        actual = response_metrics(response_series, target, tolerance)
                        metrics = {
                            'settled': actual['settled'],
                            'iae': score, 'ise': score,
                            'settling_time': actual['settling_time'],
                            'overshoot': actual['overshoot'],
                            'oscillation': actual['oscillation'],
                            'final_error': actual['final_error'],
                            'tail_error': actual['tail_error'],
                        }
                    except (BlockError, ValueError, OverflowError):
                        metrics = {
                            'settled': None, 'iae': score, 'ise': score,
                            'settling_time': None, 'overshoot': 0.0,
                            'oscillation': 0.0, 'final_error': 0.0, 'tail_error': 0.0,
                        }
                else:
                    # Response signal not identifiable: settling is unknown.
                    metrics = {
                        'settled': None, 'iae': score, 'ise': score,
                        'settling_time': None, 'overshoot': 0.0,
                        'oscillation': 0.0, 'final_error': 0.0, 'tail_error': 0.0,
                    }
                return metrics, series, score

            settings = {
                "objective": objective, "target": target, "tolerance": tolerance,
                "bounds": active_intervals, "algorithm": algorithm,
                "algorithm_options": defaults.get("algorithm_options", ""),
                "max_evaluations": max_evaluations,
                "t_end": t_end, "h": h, "method": method,
            }

            binding = {
                "parameters": [(opt_id, f"p{i+1}") for i in range(n_mapped)],
                "evaluate": evaluate_candidate,
            }

            report = _optimize(prepared, lambda m: m, settings, binding=binding)

            # Update the optimizer's parameters in the prepared model
            opt_in_prepared = next(b for b in prepared["blocks"] if str(b["id"]) == opt_id)
            for i in range(n_mapped):
                opt_in_prepared.setdefault("params", {})[f"p{i+1}"] = report["coefficients"][f"k{i+1}"]

            reports.append({
                "block_id": opt_id, "numerical_id": num_id,
                "algorithm": algorithm,
                "values": {f"p{i+1}": report["coefficients"][f"k{i+1}"] for i in range(n_mapped)},
                "score": report["score"],
                "baseline_score": report.get("baseline_score"),
                "evaluations": report["evaluations"],
                "failed_evaluations": report["failed_evaluations"],
                "converged": report["converged"],
            })

        # Run final simulation with optimized (or baseline) values
        final_results = {}
        for opt_block in optimizers:
            opt_id = str(opt_block["id"])
            opt_defaults = dict(Optimizer.parameters)
            opt_defaults.update(opt_block.get("params", {}))
            enabled = opt_defaults.get("enabled", True)
            j_wires = [c for c in connections if str(c["to"]) == opt_id and int(c.get("to_port", 0)) == 0]
            if len(j_wires) != 1:
                continue
            num_id = str(j_wires[0]["from"])
            num_block = next((b for b in blocks if str(b["id"]) == num_id), None)
            if num_block is None or num_block.get("type") != "numerical":
                continue
            inner_model = num_block.get("params", {}).get("model")
            if inner_model is None:
                continue
            inner_blocks = inner_model.get("blocks", [])
            in1_blocks = [b for b in inner_blocks if b.get("type") == "in1_terminal"]
            in1_names = [b.get("params", {}).get("name", f"input_{i+1}") for i, b in enumerate(in1_blocks)]
            opt_to_num = [c for c in connections if str(c["from"]) == opt_id and str(c["to"]) == num_id]
            mapping = sorted(opt_to_num, key=lambda c: int(c.get("from_port", 0)))
            param_names = []
            for c in mapping:
                num_port = int(c.get("to_port", 0))
                if num_port < len(in1_names):
                    param_names.append(in1_names[num_port])
            if enabled:
                opt_in_prepared = next(b for b in prepared["blocks"] if str(b["id"]) == opt_id)
            else:
                # Disabled optimizer: use original values (baseline)
                opt_in_prepared = opt_block
            values = [opt_in_prepared.get("params", {}).get(f"p{i+1}", 0.0) for i in range(len(param_names))]
            inputs = {param_names[i]: values[i] for i in range(len(param_names))}
            num_params = num_block.get("params", {})
            t_end = num_params.get("t_end", 1.0)
            h = num_params.get("h", 0.01)
            method = num_params.get("method", "rk4")
            result = self.invoke(inner_model, inputs, t_end, h, method)
            final_results[num_id] = {"series": {bid: list(zip(data.get("t", []), data.get("y", []))) for bid, data in result.get("results", {}).items()}}

        # Build serialized results
        serialized = {}
        for num_id, result in final_results.items():
            for bid, pairs in result.get("series", {}).items():
                serialized[f"{num_id}/{bid}"] = {"t": [p[0] for p in pairs], "y": [p[1] for p in pairs]}

        n_steps = 0
        for data in serialized.values():
            if "t" in data:
                n_steps = max(n_steps, len(data["t"]) - 1)

        return {"results": serialized, "n_steps": n_steps, "raw_results": final_results}, reports

    @staticmethod
    def _serialize_results(results):
        """Serialize simulation results to JSON-safe format."""
        out = {}
        for bid, series in results.items():
            vector = bool(series and isinstance(series[0][1], tuple))
            out[str(bid)] = {
                "t": [p[0] for p in series],
                "y": [p[1][0] if vector else p[1] for p in series],
            }
            if vector:
                out[str(bid)]["outputs"] = [
                    [v[port] for t, v in series] for port in range(len(series[0][1]))
                ]
        return out
