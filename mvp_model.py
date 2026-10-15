"""Validated model documents and detached simulation graphs (no Qt objects)."""
import copy
import json
import math
import os
import tempfile
from pathlib import Path

from octalink_engine_support import SOLVERS, port_counts, resolve_variables

# 4.1 adds the Model Workspace ("variables") and parameter-sized Sum/Product,
# and the optional fixed-step "solver" ("rk4" when absent, or "sdirk4").
DOCUMENT_VERSION = "4.1"
SUPPORTED_VERSIONS = ("3.0", "3.1", "4.0", "4.1")


def validate_document(data, specs):
    if not isinstance(data, dict):
        raise ValueError("A model must be a JSON object.")
    if data.get("version", "3.1") not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported model version.")
    resolve_variables(data.get("variables", {}))
    for key in ("provenance", "description"):
        if not isinstance(data.get(key, ""), str) or len(data.get(key, "")) > 20000:
            raise ValueError(f"Model {key} must be text of at most 20000 characters.")
    if data.get("backend", "python") not in ("python", "octave"):
        raise ValueError("Simulation backend must be python or octave.")
    if data.get("solver", "rk4") not in SOLVERS:
        raise ValueError(f"Solver must be one of: {', '.join(SOLVERS)}.")
    for key, default in (("stop_time", 10), ("dt", .01)):
        try:
            value = float(data.get(key, default))
        except (ValueError, TypeError):
            raise ValueError(f"{key} must be a finite positive number.") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a finite positive number.")
    seen = set()

    def scene_check(scene, depth=0):
        if depth > 24 or not isinstance(scene, dict):
            raise ValueError("Invalid or excessively nested subsystem.")
        if scene.get("connection_style", "orthogonal") not in ("orthogonal", "curved"):
            raise ValueError("Diagram connection style must be orthogonal or curved.")
        blocks, wires = scene.get("blocks"), scene.get("wires")
        if not isinstance(blocks, list) or not isinstance(wires, list):
            raise ValueError("Each diagram needs blocks and wires arrays.")
        local = {}
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError("Invalid block record.")
            ident, kind = block.get("id"), block.get("type")
            if type(ident) is not int or ident < 1 or ident in seen:
                raise ValueError("Block IDs must be unique positive integers.")
            if kind not in specs:
                raise ValueError(f"Unknown block type: {kind}")
            seen.add(ident)
            if len(seen) > 5000:
                raise ValueError("MVP models support at most 5000 blocks.")
            for coordinate in ("x", "y"):
                value = block.get(coordinate)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e7:
                    raise ValueError("Invalid block position.")
            if not isinstance(block.get("name", ""), str) or not isinstance(block.get("params", {}), dict):
                raise ValueError("Invalid block name or parameters.")
            params = dict(specs[kind]["params"])
            params.update(block.get("params", {}))
            if any(not isinstance(k, str) or not isinstance(v, (str, int, float)) for k, v in params.items()):
                raise ValueError("Parameters must be text or numbers.")
            try:
                ni, no = port_counts(kind, params, specs[kind])
                if kind == "Subsystem":
                    child = block.get("sub_scene", {"blocks": [], "wires": []})
                    scene_check(child, depth + 1)
                    ni = sum(b["type"] == "Inport" for b in child["blocks"])
                    no = sum(b["type"] == "Outport" for b in child["blocks"])
                    for boundary in ("Inport", "Outport"):
                        numbers = sorted(int(b.get("params", {}).get("port_number", 1)) for b in child["blocks"] if b["type"] == boundary)
                        if numbers != list(range(1, len(numbers) + 1)):
                            raise ValueError("Subsystem port numbers must be consecutive from 1.")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid ports for {block.get('name', kind)}: {exc}") from None
            if ni > 64 or no > 64:
                raise ValueError("MVP blocks support at most 64 ports.")
            local[ident] = (ni, no)
        inputs = set()
        for wire in wires:
            if not isinstance(wire, dict):
                raise ValueError("Invalid wire record.")
            src, dst = wire.get("from_block"), wire.get("to_block")
            outp, inp = wire.get("from_port"), wire.get("to_port")
            if src not in local or dst not in local:
                raise ValueError("Wire references a missing block.")
            if type(outp) is not int or type(inp) is not int or not (0 <= outp < local[src][1] and 0 <= inp < local[dst][0]):
                raise ValueError("Wire references a missing port.")
            if (dst, inp) in inputs:
                raise ValueError("An input port cannot have multiple drivers.")
            inputs.add((dst, inp))

    scene_check(data.get("root", data))
    return copy.deepcopy(data)


def read_document(path, specs):
    if Path(path).stat().st_size > 10_000_000:
        raise ValueError("Model exceeds the 10 MB MVP document limit.")
    with open(path, encoding="utf-8") as stream:
        return validate_document(json.load(stream), specs)


def save_document(path, data, specs):
    data = validate_document(data, specs)
    path = Path(path).resolve()
    fd, temporary = tempfile.mkstemp(prefix=".octalink-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


class GraphObject:
    """Identity-hashable records matching the compiler's block/port contract."""
    def __init__(self, **attributes):
        self.__dict__.update(attributes)

    def scene(self):
        return self._scene


def document_from_scene(scene, t_stop=10, dt=.01):
    """Serialize either Qt scene objects or the detached graph contract."""
    def record(current):
        blocks = []
        for block in current.blocks:
            position = block.pos() if hasattr(block, "pos") else None
            entry = {"id": block.block_id, "type": block.block_type, "name": block.name,
                     "params": copy.deepcopy(block.params), "flipped": getattr(block, "flipped", False),
                     "x": position.x() if position else 0, "y": position.y() if position else 0}
            if block.block_type == "Subsystem":
                entry["sub_scene"] = record(block.sub_scene)
            blocks.append(entry)
        wires = [{"from_block": w.start_port.parent_block.block_id, "from_port": w.start_port.index,
                  "to_block": w.end_port.parent_block.block_id, "to_port": w.end_port.index}
                 for w in current.wires if w.end_port is not None]
        return {"blocks": blocks, "wires": wires,
                "connection_style": getattr(current, "connection_style", "orthogonal")}
    document = {"version": DOCUMENT_VERSION, "stop_time": str(t_stop), "dt": str(dt), "root": record(scene)}
    if getattr(scene, "variables", None):
        document["variables"] = copy.deepcopy(scene.variables)
    return document


def detached_graph(data, specs):
    validate_document(data, specs)

    def build(record, owner=None):
        scene = GraphObject(blocks=[], wires=[], owner_subsystem=owner,
                            variables=None if owner else copy.deepcopy(data.get("variables", {})))
        lookup = {}
        for entry in record["blocks"]:
            kind = entry["type"]
            params = dict(specs[kind]["params"])
            params.update(entry.get("params", {}))
            block = GraphObject(block_id=entry["id"], name=entry.get("name", kind), block_type=kind,
                                spec=specs[kind], params=params, _scene=scene, sub_scene=None,
                                scope_t=[], scope_y=[], scope_labels=[])
            ni, no = port_counts(kind, params, specs[kind])
            if kind == "Subsystem":
                block.sub_scene = build(entry.get("sub_scene", {"blocks": [], "wires": []}), block)
                ni = sum(b.block_type == "Inport" for b in block.sub_scene.blocks)
                no = sum(b.block_type == "Outport" for b in block.sub_scene.blocks)
            block.in_ports = [GraphObject(parent_block=block, index=i, wires=[]) for i in range(ni)]
            block.out_ports = [GraphObject(parent_block=block, index=i, wires=[]) for i in range(no)]
            scene.blocks.append(block)
            lookup[block.block_id] = block
        for entry in record["wires"]:
            start = lookup[entry["from_block"]].out_ports[entry["from_port"]]
            end = lookup[entry["to_block"]].in_ports[entry["to_port"]]
            wire = GraphObject(start_port=start, end_port=end)
            start.wires.append(wire)
            end.wires.append(wire)
            scene.wires.append(wire)
        return scene

    return build(data.get("root", data))
