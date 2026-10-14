"""Subsystem expansion: flatten nested diagrams into a flat executable model.

The expansion function takes a model dict (as sent by the frontend) and
produces an equivalent flat model dict where all subsystem blocks have been
replaced by their internal blocks, with boundary connections rewired.

Design:
- In1 terminal: identified by type "in1_terminal" in the internal blocks.
  Has 1 output (feeds the internal diagram). During expansion, the external
  input source connects to ALL blocks that In1 feeds (fan-out supported).
- Out1 terminal: identified by type "out1_terminal" in the internal blocks.
  Has 1 input (receives from the internal diagram). Exactly one block may
  feed Out1 (multiple sources is a validation error).
- Identity subsystem (In1 -> Out1 only): acts as a wire; the external input
  source is directly connected to the external output destination.
- All other internal blocks are added to the flat model with scoped IDs
  ("{sub_id}/{block_id}") to avoid collisions with parent-level IDs.

The resulting flat model is passed to the existing Engine unchanged.
"""
from __future__ import annotations

IN1_TYPE = "in1_terminal"
OUT1_TYPE = "out1_terminal"


def expand_subsystems(model_dict: dict) -> dict:
    """Expand all subsystem blocks in model_dict into flat blocks.

    Returns a new dict with the same structure (blocks, connections)
    where subsystems have been replaced by their internal contents.
    If no subsystems are present, returns the original dict unchanged.
    """
    blocks = model_dict.get("blocks", [])
    connections = model_dict.get("connections", [])

    # Identify subsystem blocks
    sub_blocks = [b for b in blocks if b.get("type") == "subsystem"]
    if not sub_blocks:
        return model_dict

    sub_ids = {str(b["id"]) for b in sub_blocks}

    # Validate: no subsystem may have multiple input sources
    for sub in sub_blocks:
        sub_id = str(sub["id"])
        input_count = sum(
            1 for c in connections
            if str(c["to"]) == sub_id and int(c.get("to_port", 0)) == 0
        )
        if input_count > 1:
            from xcos_mini.core import BlockError
            raise BlockError(
                f"Subsystem '{sub_id}' has {input_count} input sources. "
                f"A subsystem accepts exactly one input."
            )

    # Phase 1: Analyze each subsystem's boundary structure
    sub_info = {}  # sub_id -> dict with in1_id, out1_id, output_src, input_dsts, identity
    for sub in sub_blocks:
        sub_id = str(sub["id"])
        internal = sub.get("internal", {})
        int_blocks = internal.get("blocks", [])
        int_conns = internal.get("connections", [])

        in1_id = None
        out1_id = None
        for ib in int_blocks:
            if ib.get("type") == IN1_TYPE:
                in1_id = str(ib["id"])
            elif ib.get("type") == OUT1_TYPE:
                out1_id = str(ib["id"])

        if in1_id is None or out1_id is None:
            from xcos_mini.core import BlockError
            raise BlockError(
                f"Subsystem '{sub_id}' is missing In1 or Out1 boundary terminal. "
                f"Every subsystem must contain exactly one In1 and one Out1."
            )

        # Collect ALL destinations In1 feeds (including Out1 for identity detection)
        all_in1_dests = []
        for c in int_conns:
            if str(c["from"]) == in1_id:
                all_in1_dests.append((str(c["to"]), int(c.get("to_port", 0))))

        # Collect ALL sources feeding Out1 (including In1 for identity detection)
        all_out1_sources = []
        for c in int_conns:
            if str(c["to"]) == out1_id:
                all_out1_sources.append(str(c["from"]))

        # Validate: Out1 must have exactly one source (multiple sources is an error)
        from xcos_mini.core import BlockError
        if len(all_out1_sources) == 0:
            raise BlockError(
                f"Subsystem '{sub_id}': Out1 has no incoming connection. "
                f"The internal diagram must provide a path from In1 to Out1."
            )
        if len(all_out1_sources) > 1:
            raise BlockError(
                f"Subsystem '{sub_id}' has {len(all_out1_sources)} sources feeding Out1 "
                f"({', '.join(all_out1_sources)}). Out1 accepts exactly one input."
            )

        # Validate: In1 must have at least one outgoing connection
        if len(all_in1_dests) == 0:
            raise BlockError(
                f"Subsystem '{sub_id}': In1 has no outgoing connection. "
                f"The internal diagram must provide a path from In1 to Out1."
            )

        # Identity: the single source of Out1 is In1 itself (direct wire)
        is_identity = (all_out1_sources[0] == in1_id)

        # output_src: the single block that feeds Out1 (if not identity)
        output_src = None if is_identity else all_out1_sources[0]

        # input_dsts: all blocks In1 feeds, excluding Out1 (identity wire)
        input_dsts = [(d, p) for d, p in all_in1_dests if d != out1_id]

        sub_info[sub_id] = {
            "in1_id": in1_id,
            "out1_id": out1_id,
            "output_src": output_src,
            "output_port": next(int(c.get("from_port", 0)) for c in int_conns if str(c["to"]) == out1_id),
            "input_dsts": input_dsts,
            "identity": is_identity,
            "int_blocks": int_blocks,
            "int_conns": int_conns,
        }

    # Phase 2: Build flat block list
    new_blocks = []

    # Non-subsystem parent blocks
    for b in blocks:
        if str(b["id"]) not in sub_ids:
            new_blocks.append(b)

    # Internal blocks of each subsystem (scoped IDs, excluding terminals)
    for sub in sub_blocks:
        sub_id = str(sub["id"])
        info = sub_info[sub_id]
        for ib in info["int_blocks"]:
            if ib.get("type") in (IN1_TYPE, OUT1_TYPE):
                continue
            new_b = {k: v for k, v in ib.items() if k != "internal"}
            new_b["id"] = f"{sub_id}/{ib['id']}"
            new_blocks.append(new_b)

    # Phase 3: Build flat connection list
    new_conns = []

    # 3a. Internal-to-internal connections (neither endpoint is In1 or Out1)
    for sub in sub_blocks:
        sub_id = str(sub["id"])
        info = sub_info[sub_id]
        in1_id = info["in1_id"]
        out1_id = info["out1_id"]

        for c in info["int_conns"]:
            src = str(c["from"])
            dst = str(c["to"])
            sp = int(c.get("from_port", 0))
            dp = int(c.get("to_port", 0))

            if src == in1_id or dst == out1_id:
                # Boundary connections are resolved via parent connections
                continue
            # Internal-to-internal: scope both endpoints
            new_conns.append({
                "from": f"{sub_id}/{src}", "from_port": sp,
                "to": f"{sub_id}/{dst}", "to_port": dp,
            })

    # 3b. Parent-level connections: resolve subsystem endpoints
    for c in connections:
        from_id = str(c["from"])
        to_id = str(c["to"])
        from_port = int(c.get("from_port", 0))
        to_port = int(c.get("to_port", 0))

        # Resolve the 'from' endpoint if it's a subsystem
        if from_id in sub_ids:
            info = sub_info[from_id]
            if info["identity"]:
                # Identity subsystem as source: find what feeds it, redirect to destination
                src = _find_input_source(connections, from_id)
                if src is not None:
                    new_conns.append({
                        "from": src[0], "from_port": src[1],
                        "to": to_id, "to_port": to_port,
                    })
                continue
            else:
                from_id = f"{from_id}/{info['output_src']}"
                from_port = info["output_port"]

        # Resolve the 'to' endpoint if it's a subsystem
        if to_id in sub_ids:
            info = sub_info[to_id]
            if info["identity"]:
                # Identity subsystem as destination: find what it feeds, redirect source there
                dsts = _find_output_destinations(connections, to_id)
                for dst_id, dst_port in dsts:
                    new_conns.append({
                        "from": from_id, "from_port": from_port,
                        "to": dst_id, "to_port": dst_port,
                    })
                continue
            else:
                # Fan-out: connect to ALL blocks that In1 feeds, preserving internal port
                for dst_id, dst_port in info["input_dsts"]:
                    new_conns.append({
                        "from": from_id, "from_port": from_port,
                        "to": f"{to_id}/{dst_id}", "to_port": dst_port,
                    })
                continue

        new_conns.append({
            "from": from_id, "from_port": from_port,
            "to": to_id, "to_port": to_port,
        })

    # Phase 5: Deduplicate connections
    seen = set()
    final_conns = []
    for c in new_conns:
        key = (c["from"], c["from_port"], c["to"], c["to_port"])
        if key not in seen:
            seen.add(key)
            final_conns.append(c)

    return {"blocks": new_blocks, "connections": final_conns}


def _find_input_source(connections, sub_id):
    """Find the source block and port that feeds into sub_id's input."""
    for c in connections:
        if str(c["to"]) == sub_id and int(c.get("to_port", 0)) == 0:
            return (str(c["from"]), int(c.get("from_port", 0)))
    return None


def _find_output_destinations(connections, sub_id):
    """Find all destinations that sub_id's output feeds."""
    dsts = []
    for c in connections:
        if str(c["from"]) == sub_id and int(c.get("from_port", 0)) == 0:
            dsts.append((str(c["to"]), int(c.get("to_port", 0))))
    return dsts
