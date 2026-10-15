"""Portable C99 export of the validated scalar/hybrid RK4 engine.

Adapted from the shipped examples/hybrid_model.h and hybrid_model.c. Their
state/init/step API is retained, with corrected event and delay semantics.
Generation uses the same graph compiler as the Python engine, lazily imported;
the generated runtime uses only C99 headers and libm (no Qt/Python/Octave).

OctaLink_Init publishes the right-continuous t=0 sample, including discrete
updates. OctaLink_Step(st, duration) advances by a positive duration, splitting
at the export dt grid, source Step events, and every discrete sample event.
After each endpoint it publishes y_out; the caller logs the current t/y_out.
Use OctaLink_NextTime(st, stop) and Step(next-t) to log every engine sample,
including an arbitrary exact stop. Calling Step across several events keeps
the integration correct but exposes only its final sample to the caller.

Scope and To CSV channels are concatenated in flattened document order; the
runtime performs no file I/O. Relay switching occurs at scheduled major samples,
matching Python, without continuous zero-crossing location. SISO continuous
blocks take scalar inputs; nested Mux/Demux and expression u_vec are supported.
There are no external root input ports in this MVP. Unsupported graphs fail
before files are written, including models that select the SDIRK4 solver or
contain an algebraic loop (both run in Python, GNU Octave and the .m export). Status is sticky until Init; inspect it after every
call. Failed calls may have reached an earlier event, so never log as success.
Each call is bounded to 250000 integration substeps; dimensions are bounded at
export to 4096 states, 32768 signals and 32768 logged output channels.
"""

import ast
import math
import os
from pathlib import Path
import re
import tempfile

import numpy as np


def _number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("C export requires finite real coefficients.")
    result = format(value, ".17g")
    return result if "." in result or "e" in result else result + ".0"


def export_c_model(document, specs, dt, base_filepath):
    """Generate a standalone header/source pair, returning their Path objects."""
    dt = float(dt)
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError("C export time step must be finite and positive.")
    from mvp_model import detached_graph
    from octalink_gui import SimulationEngine
    from octalink_engine_support import parse_expression

    scene = detached_graph(document, specs)
    engine = SimulationEngine()
    (blocks, sources, params, slices, models, direct, order, ns) = engine.compile_graph(scene)
    # The C runtime is explicit RK4 with a straight-line evaluation order. The
    # implicit SDIRK4 solver and algebraic-loop Newton run in the Python engine
    # and GNU Octave only; such models are refused before any file is written.
    if document.get("solver", "rk4") != "rk4":
        raise ValueError("C export supports the RK4 solver only; this model selects SDIRK4 (implicit). "
                         "Select RK4 with a step small enough for its fastest dynamics, or simulate in "
                         "Python/GNU Octave or the exported .m script.")
    if engine.algebraic_loops:
        names = "; ".join(loop.name for loop in engine.algebraic_loops)
        raise ValueError(f"C export does not support algebraic loops (loop variables: {names}). "
                         "Break the loop with a Unit Delay or Integrator, or simulate in Python/GNU Octave "
                         "or the exported .m script.")
    supported = {"Step", "Sine Wave", "Constant", "Pulse Generator", "Sum", "Product", "Gain", "Trig",
                 "Octave Function", "Saturation", "Relay", "PID Controller", "Integrator",
                 "Transfer Fcn", "State-Space", "Unit Delay", "Zero-Order Hold", "Switch",
                 "Discrete Transfer Fcn", "Discrete Zero-Pole",
                 "Mux", "Demux", "Scope", "To CSV"}
    for block in blocks:
        if block.block_type not in supported:
            raise ValueError(f"{block.name}: C export does not support {block.block_type}.")
        if not 0 < block.block_id <= 4294967295:
            raise ValueError("C export block IDs must fit uint32_t.")
    if ns > 4096:
        raise ValueError("C export supports at most 4096 continuous states.")
    sinks = [b for b in blocks if b.block_type in ("Scope", "To CSV")]
    if not sinks:
        raise ValueError("C export requires a Scope or To CSV sink to define y_out.")
    scheduled = [b for b in blocks if b.block_type in engine.DISCRETE_BLOCKS]
    discrete_index = {b: i for i, b in enumerate(scheduled)}
    relays = [b for b in blocks if b.block_type == "Relay"]
    relay_index = {b: i for i, b in enumerate(relays)}
    discrete_tf = [b for b in blocks if b.block_type in ("Discrete Transfer Fcn", "Discrete Zero-Pole")]
    dtf_index, dtf_offset, ndx = {}, {}, 0
    for i, b in enumerate(discrete_tf):
        dtf_index[b], dtf_offset[b] = i, ndx
        ndx += models[b][0].shape[0]

    # Infer channel widths using the already validated evaluation order.
    widths, offsets, count = {}, {}, 0
    evaluation_order = [b for b in blocks if not direct[b]] + order
    def channels(connection):
        block, port = connection
        if block.block_type == "Demux":
            return [f"y[{offsets[block] + port}]"]
        return [f"y[{offsets[block] + i}]" for i in range(widths[block])]

    for b in evaluation_order:
        inputs = [channels(c) for c in sources[b]] if direct[b] else []
        kind = b.block_type
        if kind == "Mux":
            width = sum(len(v) for v in inputs)
        elif kind == "Demux":
            width = int(params[b]["outputs"])
            if len(inputs[0]) != width:
                raise ValueError(f"{b.name}: Demux expects {width} channels, received {len(inputs[0])}.")
        elif kind in ("Scope", "To CSV"):
            width = len(inputs[0])
        elif kind in ("Gain", "State-Space"):
            # The compiler already validated these vector widths.
            width = engine.signal_widths[b]
        else:
            width = 1
            if kind != "Octave Function" and any(len(v) != 1 for v in inputs):
                raise ValueError(f"{b.name}: scalar C block received a vector; use Demux.")
        widths[b], offsets[b] = width, count
        count += width
    # Non-feedthrough blocks still require scalar derivative/pending inputs.
    for b in blocks:
        if b.block_type in ("Integrator", "PID Controller", "Transfer Fcn", "State-Space", "Unit Delay",
                            "Discrete Transfer Fcn", "Discrete Zero-Pole"):
            if len(channels(sources[b][0])) != 1:
                raise ValueError(f"{b.name}: scalar C block received a vector; use Demux.")
    nout = sum(widths[b] for b in sinks)
    if count > 32768 or nout > 32768:
        raise ValueError("C export exceeds the 32768 signal/output channel limit.")

    base = Path(base_filepath).resolve()
    if base.suffix.lower() in (".c", ".h"):
        base = base.with_suffix("")
    if not re.fullmatch(r"[A-Za-z0-9_. -]+", base.name):
        raise ValueError("C export filename must use letters, digits, spaces, dot, underscore or hyphen.")
    hp, cp = base.with_suffix(base.suffix + ".h"), base.with_suffix(base.suffix + ".c")
    nc, nd, nr = max(1, ns), max(1, len(scheduled)), max(1, len(relays))
    nt, nx = max(1, len(discrete_tf)), max(1, ndx)
    header = f'''/* Generated OctaLink C99 model; coefficients are embedded. */
#ifndef OCTALINK_GENERATED_MODEL_H
#define OCTALINK_GENERATED_MODEL_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {{
#endif
#define OCTALINK_NUM_STATES {ns}
#define OCTALINK_NUM_OUTPUTS {nout}
#define OCTALINK_MAX_DT {_number(dt)}
#define OCTALINK_MAX_SUBSTEPS 250000U
enum {{ OCTALINK_OK = 0, OCTALINK_BAD_DT = 1,
       OCTALINK_NONFINITE = 2, OCTALINK_LIMIT = 3 }};
typedef struct {{
    double t;
    uint32_t step_idx;
    int status;
    uint32_t error_block; /* document ID, or 0 for runtime/time errors */
    double X[{nc}];
    double y_out[{nout}];
    double delay[{nd}], pending[{nd}], zoh[{nd}];
    uint64_t next_hit[{nd}];
    double relay[{nr}];
    double dtf_x[{nx}], dtf_y[{nt}]; /* discrete transfer states and held outputs */
}} OctaLink_State;
/* Init evaluates t=0. Always inspect status before consuming y_out. */
void OctaLink_Init(OctaLink_State *st);
/* Positive finite duration. Events/grid split automatically; final sample is published. */
void OctaLink_Step(OctaLink_State *st, double dt);
/* Next grid/event time capped at stop. stop==t returns t; invalid bounds return NAN. */
double OctaLink_NextTime(const OctaLink_State *st, double stop);
/* y_out groups, in flattened document order; offsets include all sink channels. */
'''
    output_offset = 0
    for b in sinks:
        header += f"#define OCTALINK_SINK_{b.block_id}_OFFSET {output_offset}\n"
        header += f"#define OCTALINK_SINK_{b.block_id}_CHANNELS {widths[b]}\n"
        output_offset += widths[b]
    header += '''#ifdef __cplusplus
}
#endif
#endif
'''
    lines = [f'#include "{hp.name}"', "#include <math.h>", "#include <float.h>",
             "#include <stddef.h>", "#include <string.h>",
             "/* Sticky errors: no allocation, process exit, or runtime I/O. */",
             "static double OctaLink_Eps(double t) { return 16.0 * DBL_EPSILON * fabs(t); }",
             "static void OctaLink_Error(OctaLink_State *st, int code, uint32_t block) {",
             "    if (st->status == OCTALINK_OK) { st->status = code; st->error_block = block; }", "}"]
    # Expression helpers preserve Python's modulo/exponent semantics.
    helpers = set()
    def expression(node, u, b, output):
        if isinstance(node, ast.Constant):
            value = _number(node.value)
        elif isinstance(node, ast.Name):
            builtin = {"u": u[0], "t": "t", "pi": _number(math.pi), "e": _number(math.e)}
            # Model Workspace variables are embedded as resolved constants.
            value = builtin[node.id] if node.id in builtin else _number(engine.variables[node.id])
        elif isinstance(node, ast.Subscript):
            index = node.slice.value
            if index >= len(u):
                raise ValueError(f"{b.name}: expression requests unavailable u_vec[{index}].")
            value = u[index]
        elif isinstance(node, ast.UnaryOp):
            arg = expression(node.operand, u, b, output)
            value = f"({'-' if isinstance(node.op, ast.USub) else '+'}{arg})"
        elif isinstance(node, ast.BinOp):
            a, z = expression(node.left, u, b, output), expression(node.right, u, b, output)
            operators = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
            if type(node.op) in operators:
                value = f"({a} {operators[type(node.op)]} {z})"
            elif isinstance(node.op, ast.Pow):
                helpers.add("pow")
                value = f"OctaLink_Pow({a}, {z})"
            else:
                helpers.add("mod")
                value = f"OctaLink_Mod({a}, {z})"
        else:
            name = node.func.id
            args = [expression(n, u, b, output) for n in node.args]
            if name in ("min", "max"):
                if len(args) < 2:
                    raise ValueError(f"{b.name}: {name} requires at least two scalar arguments.")
                value = args[0]
                for arg in args[1:]:
                    value = f"{'fmin' if name == 'min' else 'fmax'}({value}, {arg})"
            else:
                if len(args) != 1:
                    raise ValueError(f"{b.name}: {name} requires exactly one argument.")
                value = f"{'fabs' if name == 'abs' else name}({args[0]})"
        symbol = f"e_{b.block_id}_{len(output)}"
        output.append(f"    double {symbol} = {value};")
        output.append(f"    if (!isfinite({symbol})) {{ OctaLink_Error(st, OCTALINK_NONFINITE, {b.block_id}U); return; }}")
        return symbol

    eval_lines = ["static void OctaLink_Eval(OctaLink_State *st, double t, const double *x,",
                  "                          double *dx, int major, const int *hit) {",
                  f"    double y[{count}];", "    (void)t; (void)x; (void)hit; (void)major; (void)dx;"]
    def weighted(coefficients, variables):
        terms = [f"({_number(c)} * {v})" for c, v in zip(coefficients, variables) if c != 0]
        return " + ".join(terms) or "0.0"
    for b in evaluation_order:
        kind, p = b.block_type, params[b]
        u = [channels(c) for c in sources[b]]
        out = [f"y[{offsets[b] + i}]" for i in range(widths[b])]
        if kind == "Step":
            values = [f"(t >= {_number(p['step_time'])} ? {_number(p['final_val'])} : {_number(p['initial_val'])})"]
        elif kind == "Sine Wave":
            values = [f"{_number(p['amplitude'])} * sin({_number(p['frequency'])} * t + {_number(p['phase'])})"]
        elif kind == "Constant":
            values = [_number(p["value"])]
        elif kind == "Pulse Generator":
            helpers.add("pulse")
            values = [f"OctaLink_Pulse(t, {_number(p['amplitude'])}, {_number(p['period'])}, "
                      f"{_number(p['pulse_width'])}, {_number(p['phase_delay'])})"]
        elif kind == "Integrator":
            values = [f"x[{slices[b].start}]"]
        elif kind == "Unit Delay":
            values = [f"st->delay[{discrete_index[b]}]"]
        elif kind in ("Discrete Transfer Fcn", "Discrete Zero-Pole"):
            A, B, C, D = models[b]
            j, base = dtf_index[b], dtf_offset[b]
            held = weighted(C.ravel(), [f"st->dtf_x[{base + i}]" for i in range(A.shape[0])])
            if direct[b]:
                held += f" + {_number(D)} * {u[0][0]}"
            eval_lines.append(f"    if (major && hit[{discrete_index[b]}]) st->dtf_y[{j}] = {held};")
            values = [f"st->dtf_y[{j}]"]
        elif kind in ("Transfer Fcn", "State-Space"):
            A, B, C, D = models[b]
            state_vars = [f"x[{i}]" for i in range(slices[b].start, slices[b].stop)]
            values = [weighted(row, state_vars) for row in C]
            if direct[b]:
                for i, d in enumerate(np.ravel(D)):
                    if d != 0:
                        values[i] += f" + {_number(d)} * {u[0][0]}"
        elif kind == "Gain":
            gain = p["gain"]
            if isinstance(gain, float):
                values = [f"{_number(gain)} * {v}" for v in u[0]]
            elif p["matrix_gain"]:
                values = [weighted(row, u[0]) for row in gain]
            else:
                flat = list(np.ravel(gain))
                inputs = u[0] * len(flat) if len(u[0]) == 1 else u[0]
                values = [f"{_number(k)} * {v}" for k, v in zip(flat, inputs)]
        elif kind == "Saturation":
            values = [f"fmin(fmax({u[0][0]}, {_number(p['lower_limit'])}), {_number(p['upper_limit'])})"]
        elif kind == "Relay":
            i = relay_index[b]
            eval_lines += [f"    if (major) {{ if ({u[0][0]} >= {_number(p['switch_on_point'])}) st->relay[{i}] = {_number(p['on_val'])};",
                           f"        else if ({u[0][0]} <= {_number(p['switch_off_point'])}) st->relay[{i}] = {_number(p['off_val'])}; }}"]
            values = [f"st->relay[{i}]"]
        elif kind == "Zero-Order Hold":
            i = discrete_index[b]
            eval_lines.append(f"    if (major && hit[{i}]) st->zoh[{i}] = {u[0][0]};")
            values = [f"st->zoh[{i}]"]
        elif kind == "Switch":
            values = [f"({u[1][0]} >= {_number(p['threshold'])} ? {u[0][0]} : {u[2][0]})"]
        elif kind == "Trig":
            values = [f"{p['operator']}({u[0][0]})"]
        elif kind == "Octave Function":
            values = [expression(parse_expression(p["expression"], True, frozenset(engine.variables)),
                                 u[0], b, eval_lines)]
        elif kind == "Sum":
            values = ["0.0 " + " ".join(f"{sign} {v[0]}" for sign, v in zip(p["signs"], u))]
        elif kind == "Product":
            values = ["1.0 " + " ".join(f"{op} {v[0]}" for op, v in zip(p["ops"], u))]
        elif kind == "PID Controller":
            i = slices[b].start
            values = [f"{_number(p['Kp'])} * {u[0][0]} + {_number(p['Ki'])} * x[{i}] + {_number(p['Kd'])} * {_number(p['N'])} * ({u[0][0]} - x[{i+1}])"]
        elif kind == "Mux":
            values = [v for group in u for v in group]
        else:  # Demux and sinks simply preserve the exact channel list.
            values = u[0]
        for target, value in zip(out, values):
            eval_lines += [f"    {target} = {value};",
                           f"    if (!isfinite({target})) {{ OctaLink_Error(st, OCTALINK_NONFINITE, {b.block_id}U); return; }}"]
    for b, sl in slices.items():
        u = channels(sources[b][0])[0]
        if b.block_type == "Integrator":
            values = [u]
        elif b.block_type == "PID Controller":
            values = [u, f"{_number(params[b]['N'])} * ({u} - x[{sl.start+1}])"]
        else:
            A, B, C, D = models[b]
            variables = [f"x[{i}]" for i in range(sl.start, sl.stop)]
            values = [weighted(row, variables) + f" + {_number(B[i, 0])} * {u}" for i, row in enumerate(A)]
        for i, value in zip(range(sl.start, sl.stop), values):
            eval_lines += [f"    dx[{i}] = {value};",
                           f"    if (!isfinite(dx[{i}])) {{ OctaLink_Error(st, OCTALINK_NONFINITE, {b.block_id}U); return; }}"]
    eval_lines.append("    if (major) {")
    oi = 0
    for b in sinks:
        for j in range(widths[b]):
            eval_lines.append(f"        st->y_out[{oi}] = y[{offsets[b]+j}];")
            oi += 1
    for b in scheduled:
        if b.block_type == "Unit Delay":
            i = discrete_index[b]
            eval_lines.append(f"        if (hit[{i}]) st->pending[{i}] = {channels(sources[b][0])[0]};")
        elif b in dtf_index and models[b][0].shape[0]:
            # x[k+1] = A x[k] + B u[k], after the held output used x[k].
            A, B, _, _ = models[b]
            base, n = dtf_offset[b], A.shape[0]
            current = [f"st->dtf_x[{base + k}]" for k in range(n)]
            u_k = channels(sources[b][0])[0]
            eval_lines.append(f"        if (hit[{discrete_index[b]}]) {{")
            for k in range(n):
                eval_lines.append(f"            double n_{b.block_id}_{k} = {weighted(A[k], current)} + {_number(B[k, 0])} * {u_k};")
            for k in range(n):
                eval_lines += [f"            st->dtf_x[{base + k}] = n_{b.block_id}_{k};",
                               f"            if (!isfinite(st->dtf_x[{base + k}])) {{ OctaLink_Error(st, OCTALINK_NONFINITE, {b.block_id}U); return; }}"]
            eval_lines.append("        }")
    eval_lines += ["    }", "}"]
    if "pulse" in helpers:
        lines += ["/* Right-continuous pulse; edge arithmetic matches the Python and Octave engines. */",
                  "static double OctaLink_Pulse(double t, double a, double p, double w, double ph) {",
                  "    double k;",
                  "    if (t < ph) return 0.0;",
                  "    k = floor((t - ph) / p);",
                  "    if (ph + k * p > t) k -= 1.0; else if (ph + (k + 1.0) * p <= t) k += 1.0;",
                  "    return t < ph + k * p + p * w / 100.0 ? a : 0.0;", "}"]
    if "pow" in helpers:
        lines += ["static double OctaLink_Pow(double a, double b) { return fabs(b) > 1024.0 ? NAN : pow(a, b); }"]
    if "mod" in helpers:
        lines += ["static double OctaLink_Mod(double a, double b) {",
                  "    double r = fmod(a, b);",
                  "    if (r != 0.0 && ((r < 0.0) != (b < 0.0))) r += b;",
                  "    return r;", "}"]
    lines += eval_lines

    lines += ["static void OctaLink_Major(OctaLink_State *st) {",
              f"    int hit[{nd}] = {{0}};", f"    double dx[{nc}] = {{0}};",
              "    double eps = OctaLink_Eps(st->t);", "    (void)eps;"]
    for b in scheduled:
        i, ts = discrete_index[b], _number(params[b]["sample_time"])
        lines += [f"    if (fabs(st->t - (double)st->next_hit[{i}] * {ts}) <= eps) {{",
                  f"        if (st->next_hit[{i}] == UINT64_MAX) {{ OctaLink_Error(st, OCTALINK_LIMIT, {b.block_id}U); return; }}",
                  f"        hit[{i}] = 1; ++st->next_hit[{i}];"]
        if b.block_type == "Unit Delay":
            lines.append(f"        st->delay[{i}] = st->pending[{i}];")
        lines.append("    }")
    lines += ["    OctaLink_Eval(st, st->t, st->X, dx, 1, hit);", "}",
              "void OctaLink_Init(OctaLink_State *st) {", "    if (!st) return;",
              "    memset(st, 0, sizeof(*st));"]
    initial = engine._initial_state_vector(slices, params, ns)
    for i, value in enumerate(initial):
        if value:
            lines.append(f"    st->X[{i}] = {_number(value)};")
    for b in scheduled:
        if b.block_type == "Unit Delay":
            i = discrete_index[b]
            lines.append(f"    st->delay[{i}] = st->pending[{i}] = {_number(params[b]['initial_condition'])};")
    for b in relays:
        lines.append(f"    st->relay[{relay_index[b]}] = {_number(params[b]['off_val'])};")
    lines += ["    OctaLink_Major(st);", "}"]

    events = sorted({params[b]["step_time"] for b in blocks if b.block_type == "Step" and params[b]["step_time"] > 0})
    # Pulse edges repeat indefinitely, so the runtime computes them.
    pulses = [(_number(params[b]["period"]), _number(params[b]["pulse_width"]), _number(params[b]["phase_delay"]))
              for b in blocks if b.block_type == "Pulse Generator"]
    if pulses:
        lines += ["/* Pulse edges: start = ph + k*p and start + p*w/100, as in the Python engine. */",
                  "static double OctaLink_PulseIndex(double t, double p, double ph) {",
                  "    double k = floor((t - ph) / p);",
                  "    if (ph + k * p > t) k -= 1.0; else if (ph + (k + 1.0) * p <= t) k += 1.0;",
                  "    return k;", "}",
                  "static double OctaLink_PulseNext(double t, double p, double w, double ph) {",
                  "    double k, start, end;",
                  "    if (t < ph) return ph;",
                  "    k = OctaLink_PulseIndex(t, p, ph); start = ph + k * p; end = start + p * w / 100.0;",
                  "    return end > t ? end : ph + (k + 1.0) * p;", "}",
                  "static int OctaLink_PulseIsEdge(double t, double p, double w, double ph) {",
                  "    double start;",
                  "    if (t < ph) return 0;",
                  "    start = ph + OctaLink_PulseIndex(t, p, ph) * p;",
                  "    return t == start || t == start + p * w / 100.0;", "}"]
    lines += ["double OctaLink_NextTime(const OctaLink_State *st, double stop) {",
              "    double next, candidate, eps, grid;",
              "    if (!st || st->status != OCTALINK_OK || !isfinite(stop) || stop < st->t) return NAN;",
              "    if (stop == st->t) return stop;",
              "    eps = OctaLink_Eps(stop);",
              "    grid = floor((st->t + OctaLink_Eps(st->t)) / OCTALINK_MAX_DT) + 1.0;",
              "    if (!isfinite(grid) || grid > 9007199254740991.0) return NAN;",
              "    next = stop; candidate = grid * OCTALINK_MAX_DT;",
              "    if (candidate > st->t + OctaLink_Eps(st->t) && candidate < next) next = candidate;"]
    for b in scheduled:
        i = discrete_index[b]
        lines += [f"    candidate = (double)st->next_hit[{i}] * {_number(params[b]['sample_time'])};",
                  "    if (candidate > st->t + OctaLink_Eps(st->t) && candidate < next) next = candidate;"]
    for value in events:
        lines += [f"    candidate = {_number(value)};",
                  "    if (candidate > st->t + OctaLink_Eps(st->t) && candidate < next) next = candidate;"]
    for period, width, phase in pulses:
        lines += [f"    candidate = OctaLink_PulseNext(st->t + OctaLink_Eps(st->t), {period}, {width}, {phase});",
                  "    if (candidate < next) next = candidate;"]
    # Prefer exact Step event if floating point grid/sample points coincide.
    for value in events:
        lines.append(f"    if ({_number(value)} > st->t && {_number(value)} <= stop && fabs(next - {_number(value)}) <= eps) next = {_number(value)};")
    for period, width, phase in pulses:
        lines += [f"    candidate = OctaLink_PulseNext(next - eps - OctaLink_Eps(next), {period}, {width}, {phase});",
                  "    if (candidate > st->t && candidate <= stop && fabs(next - candidate) <= eps) next = candidate;"]
    lines += ["    if (fabs(stop - next) <= eps) next = stop;", "    return next;", "}",
              "static int OctaLink_IsStepEvent(double t) {", "    (void)t;"]
    for value in events:
        lines.append(f"    if (t == {_number(value)}) return 1;")
    for period, width, phase in pulses:
        lines.append(f"    if (OctaLink_PulseIsEdge(t, {period}, {width}, {phase})) return 1;")
    lines += ["    return 0;", "}",
              "void OctaLink_Step(OctaLink_State *st, double dt) {",
              f"    double k1[{nc}] = {{0}}, k2[{nc}] = {{0}}, k3[{nc}] = {{0}}, k4[{nc}] = {{0}}, tmp[{nc}] = {{0}};",
              "    double target, next, h, end;", "    unsigned int substeps = 0;",
              "    if (!st || st->status != OCTALINK_OK) return;",
              "    target = st->t + dt;",
              "    if (!isfinite(dt) || dt <= 0.0 || !isfinite(target) || target <= st->t) {",
              "        OctaLink_Error(st, OCTALINK_BAD_DT, 0U); return;", "    }",
              "    while (st->t < target) {",
              "        if (++substeps > OCTALINK_MAX_SUBSTEPS || st->step_idx == UINT32_MAX) {",
              "            OctaLink_Error(st, OCTALINK_LIMIT, 0U); return;", "        }",
              "        next = OctaLink_NextTime(st, target);",
              "        if (!isfinite(next) || next <= st->t) { OctaLink_Error(st, OCTALINK_LIMIT, 0U); return; }",
              "        h = next - st->t;",
              "        OctaLink_Eval(st, st->t, st->X, k1, 0, NULL);",
              "        if (st->status) return;"]
    # Fully generated loops avoid zero-sized arrays and unused loop variables.
    if ns:
        lines += [f"        for (int i = 0; i < {ns}; ++i) tmp[i] = st->X[i] + 0.5 * h * k1[i];",
                  "        OctaLink_Eval(st, st->t + 0.5 * h, tmp, k2, 0, NULL);", "        if (st->status) return;",
                  f"        for (int i = 0; i < {ns}; ++i) tmp[i] = st->X[i] + 0.5 * h * k2[i];",
                  "        OctaLink_Eval(st, st->t + 0.5 * h, tmp, k3, 0, NULL);", "        if (st->status) return;",
                  f"        for (int i = 0; i < {ns}; ++i) tmp[i] = st->X[i] + h * k3[i];",
                  "        end = OctaLink_IsStepEvent(next) ? nextafter(next, st->t) : next;",
                  "        OctaLink_Eval(st, end, tmp, k4, 0, NULL);", "        if (st->status) return;",
                  f"        for (int i = 0; i < {ns}; ++i) {{",
                  "            tmp[i] = st->X[i] + (h / 6.0) * (k1[i] + 2.0*k2[i] + 2.0*k3[i] + k4[i]);",
                  "            if (!isfinite(tmp[i])) { OctaLink_Error(st, OCTALINK_NONFINITE, 0U); return; }", "        }",
                  f"        for (int i = 0; i < {ns}; ++i) st->X[i] = tmp[i];"]
    else:
        lines += ["        (void)h; (void)end; (void)tmp; (void)k2; (void)k3; (void)k4;",
                  "        (void)OctaLink_IsStepEvent;"]
    lines += ["        st->t = next; ++st->step_idx;", "        OctaLink_Major(st);",
              "        if (st->status) return;", "    }", "}"]
    source = "\n".join(lines) + "\n"
    # Build both complete contents first; invalid expressions never truncate files.
    temporary = []
    try:
        for path, content in ((hp, header), (cp, source)):
            fd, filename = tempfile.mkstemp(prefix=".octalink-c-", suffix=".tmp", dir=path.parent)
            temporary.append(filename)
            with os.fdopen(fd, "w", encoding="ascii", newline="\n") as stream:
                stream.write(content)
        for filename, path in zip(temporary, (hp, cp)):
            os.replace(filename, path)
    finally:
        for filename in temporary:
            if os.path.exists(filename):
                os.unlink(filename)
    return hp, cp
