"""GNU Octave subprocess backend and standalone .m export.

Python validates and compiles the detached graph. Octave evaluates the network,
all derivatives, discrete transitions, every RK4 or SDIRK4 state update and the
Newton iterations of algebraic loops. No Oct2Py,
shell, shared Octave session, or Python runtime is needed by exported scripts.
"""
import ast
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import numpy as np


def discover_octave(executable=None):
    """Find a local Octave executable; an explicit override never falls back."""
    override = executable if executable is not None else os.environ.get("OCTALINK_OCTAVE")
    if override:
        candidate = shutil.which(str(override)) or str(override)
        return str(Path(candidate).resolve()) if Path(candidate).is_file() else None
    for name in ("octave-cli", "octave"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    roots = []
    if os.name == "nt":
        for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            value = os.environ.get(variable)
            if value:
                roots.append(Path(value))
        # AppContainer processes can have a redirected LOCALAPPDATA.
        roots.append(Path.home() / "AppData" / "Local")
        for root in roots:
            for pattern in ("Programs/GNU Octave/Octave-*/mingw64/bin/octave-cli.exe",
                            "GNU Octave/Octave-*/mingw64/bin/octave-cli.exe",
                            "GNU Octave/Octave-*/bin/octave-cli.exe"):
                candidates = sorted(root.glob(pattern), reverse=True)
                if candidates:
                    return str(candidates[0])
    else:
        for candidate in ("/opt/homebrew/bin/octave-cli", "/usr/local/bin/octave-cli",
                          "/usr/bin/octave-cli", "/Applications/Octave.app/Contents/Resources/usr/bin/octave-cli"):
            if Path(candidate).is_file():
                return candidate
    return None


def _number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Octave generation requires finite real numbers.")
    return format(value, ".17g")


def _matrix_literal(value):
    a = np.asarray(value, dtype=float)
    if not a.size:
        return "zeros(0,1)" if a.ndim == 1 else f"zeros({a.shape[0]},{a.shape[1]})"
    if a.ndim == 1:
        a = a.reshape(1, -1)
    return "[" + ";".join(",".join(_number(v) for v in row) for row in a) + "]"


def _string(value):
    # User labels/path strings are data, never Octave syntax. UTF-8 byte vectors
    # handle apostrophes, line breaks, and non-ASCII without source injection.
    return "char([" + ",".join(str(v) for v in str(value).encode("utf-8")) + "])"


def translate_expression(expression, signal="u_vec", variables=None):
    """Translate only the same bounded arithmetic AST accepted by the engine.

    Model Workspace variables are embedded as their resolved numeric values.
    """
    from octalink_engine_support import parse_expression
    variables = variables or {}
    tree = parse_expression(expression, allow_signal=True, variable_names=frozenset(variables))

    def emit(node):
        if isinstance(node, ast.Constant):
            code = _number(node.value)
        elif isinstance(node, ast.Name):
            builtin = {"u": f"{signal}(1)", "t": "t", "pi": "pi", "e": "exp(1)"}
            code = builtin[node.id] if node.id in builtin else _number(variables[node.id])
        elif isinstance(node, ast.Subscript):
            code = f"{signal}({node.slice.value + 1})"
        elif isinstance(node, ast.UnaryOp):
            code = f"({'-' if isinstance(node.op, ast.USub) else '+'}{emit(node.operand)})"
        elif isinstance(node, ast.BinOp):
            left, right = emit(node.left), emit(node.right)
            if isinstance(node.op, ast.Pow):
                literal = node.right.value if isinstance(node.right, ast.Constant) else None
                # A small positive integer power of a finite real stays real;
                # overflow is caught by the evaluator's vectorised check.
                code = (f"({left}^{right})" if type(literal) is int and 1 <= literal <= 8
                        else f"ol_power({left},{right})")
            elif isinstance(node.op, ast.Mod):
                code = f"ol_mod({left},{right})"
            elif isinstance(node.op, ast.Div):
                code = f"ol_chk({left}/{right})"
            else:
                operator = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(node.op)]
                code = f"({left}{operator}{right})"
        else:
            name, args = node.func.id, [emit(a) for a in node.args]
            if name in ("min", "max"):
                if len(args) < 2:
                    raise ValueError(f"{name} requires at least two scalar arguments.")
                code = f"{name}([{','.join(args)}])"
            elif name == "log" and len(args) == 2:
                code = f"ol_chk(ol_chk(log({args[0]}))/ol_chk(log({args[1]})))"
            else:
                if len(args) != 1:
                    raise ValueError(f"{name} requires one argument.")
                code = f"{name}({args[0]})"
                if name in ("log", "sqrt", "asin", "acos", "exp"):
                    code = f"ol_chk({code})"
        # Operands are scalars by construction. Functions that can leave the
        # real domain, division and power are checked where they occur (as the
        # Python engine does); the evaluator's vectorised check covers the rest.
        return code
    return emit(tree)


def _compile(document, specs):
    # Deferred import avoids GUI/backend import cycles. The compiler itself
    # touches detached records only; no QWidget or Octave process is created.
    from mvp_model import detached_graph
    from octalink_gui import SimulationEngine
    engine = SimulationEngine()
    compiled = engine.compile_graph(detached_graph(document, specs))
    blocks, sources, parsed, slices, ss, direct, order, nstates = compiled
    stop, dt = float(document.get("stop_time", 10)), float(document.get("dt", .01))
    max_intervals = 250000
    if not math.isfinite(stop / dt) or stop / dt > max_intervals:
        raise ValueError("Simulation exceeds 250000 time intervals; increase dt.")
    sinks = [b for b in blocks if b.block_type in ("Scope", "To CSV")]
    periods = {b: parsed[b]["sample_time"] for b in blocks
               if b.block_type in engine.DISCRETE_BLOCKS}
    times = [i * dt for i in range(int(math.floor(stop / dt)) + 1)] + [stop]
    for ts in set(periods.values()):
        ratio = stop / ts
        if not math.isfinite(ratio) or ratio > max_intervals:
            raise ValueError("Sample time requires more than 250000 intervals.")
        if len(times) + int(math.floor(ratio)) + 1 > 4 * max_intervals:
            raise ValueError("Combined sample schedule is too large.")
        times.extend(i * ts for i in range(int(math.floor(ratio)) + 1))
    events = engine.source_events(blocks, parsed, stop)
    times.extend(events)
    epsilon = 16 * np.finfo(float).eps * stop
    schedule = []
    for t in sorted(times):
        if t > stop:
            continue
        if not schedule or t - schedule[-1] > epsilon:
            schedule.append(t)
        elif t == stop or t in events:
            schedule[-1] = t
    if len(schedule) > max_intervals + 1:
        raise ValueError("Combined sample schedule exceeds 250000 intervals.")
    if len(schedule) * max(1, len(sinks)) > 2000000:
        raise ValueError("Scope result allocation is too large.")
    labels = {b.block_id: engine._resolve_scope_labels(b, sources) for b in sinks}
    return engine, compiled, schedule, periods, events, epsilon, sinks, labels


_HELPERS = r'''
function y = ol_power(a,b)
  if abs(b) > 1024, error('OctaLink: exponent magnitude exceeds 1024'); endif
  y = ol_chk(a^b);
endfunction
function y = ol_chk(y)
  if ~isreal(y) || ~isfinite(y)
    error('OctaLink: expression left the finite real domain');
  endif
endfunction
function ol_fail(t, names, values)
  % Called only after the vectorised check failed: name the first bad block.
  for k = 1:numel(values)
    if ~isreal(values{k}) || any(~isfinite(values{k}(:)))
      error('OctaLink: %s: non-finite or complex signal at t=%g; reduce dt or check model', names{k}, t);
    endif
  endfor
  error('OctaLink: non-finite or complex state derivative at t=%g; reduce dt or check model', t);
endfunction
function y = ol_mod(a,b)
  if b == 0, error('OctaLink: division by zero'); endif
  y = mod(a,b);
endfunction
function ol_finite(x)
  if ~isreal(x) || any(~isfinite(x(:)))
    error('OctaLink: non-finite or complex signal/state; reduce dt or check model');
  endif
endfunction
function y = ol_pulse(t,a,p,w,ph)
  % Same edge arithmetic as the Python engine and C export.
  if t < ph, y = 0; return; endif
  k = floor((t-ph)/p);
  if ph + k*p > t, k = k-1; elseif ph + (k+1)*p <= t, k = k+1; endif
  if t < ph + k*p + p*w/100, y = a; else y = 0; endif
endfunction
'''


def _sdirk4_helper():
    from octalink_engine_support import (SDIRK4_A, SDIRK4_C, SDIRK4_GAMMA, SQRT_EPS,
                                         STAGE_NEWTON_ITERATIONS, STAGE_NEWTON_TOLERANCE)
    rows = ", ".join("[" + ",".join(_number(a) for a in row) + "]" for row in SDIRK4_A)
    return f'''
function y = ol_sdirk4(t,x,z,hits,f0,h,t_end)
  % SDIRK4 (Hairer-Wanner, L-stable, stiffly accurate): the Python engine's
  % sdirk4_step, operation for operation. One numerical Jacobian per step.
  A = {{{rows}}};
  c = [{",".join(_number(v) for v in SDIRK4_C)}];
  n = numel(x); Jm = zeros(n);
  for j = 1:n
    xp = x; d = {_number(SQRT_EPS)}*max(1,abs(x(j))); xp(j) = xp(j) + d;
    Jm(:,j) = (ol_evaluate(t,xp,z,false,hits) - f0)/d;
  endfor
  gh = {_number(SDIRK4_GAMMA)}*h; M = eye(n) - gh*Jm;
  if any(~isfinite(M(:))) || rcond(M) < eps
    error('OctaLink: implicit SDIRK4 iteration matrix is singular at t=%g; reduce dt or check the model', t);
  endif
  K = zeros(n,numel(c)); prev = f0;
  for s = 1:numel(c)
    base = x;
    for j = 1:s-1, base = base + (h*A{{s}}(j))*K(:,j); endfor
    if s == numel(c), ts = t_end; else ts = t + c(s)*h; endif
    y = base + gh*prev; ok = false;
    for it = 1:{STAGE_NEWTON_ITERATIONS}
      inc = M\\(-(y - base - gh*ol_evaluate(ts,y,z,false,hits)));
      y = y + inc;
      if any(~isfinite(y)), break; endif
      if max(abs(inc)) <= {_number(STAGE_NEWTON_TOLERANCE)}*(1 + max(abs(y))), ok = true; break; endif
    endfor
    if any(~isfinite(y))
      error('OctaLink: non-finite implicit SDIRK4 stage at t=%g; reduce dt or check the model', t);
    elseif ~ok
      error('OctaLink: implicit SDIRK4 Newton iteration did not converge at t=%g; reduce dt', t);
    endif
    prev = (y - base)/gh; K(:,s) = prev;
  endfor
endfunction
'''


def _loop_helpers():
    from octalink_engine_support import (LOOP_MIN_STEP, LOOP_NEWTON_ITERATIONS, LOOP_STALL_TOLERANCE,
                                         LOOP_TOLERANCE, SQRT_EPS)
    return f'''
function z = ol_newton(f, z, name, t)
  % Newton on the loop-cut signals, as solve_algebraic_loop in the Python engine.
  r = f(z);
  if any(~isfinite(r)), error('OctaLink: algebraic loop at %s: non-finite residual at t=%g', name, t); endif
  for iteration = 1:{LOOP_NEWTON_ITERATIONS}
    scale = 1 + max(abs(z)); nr = max(abs(r));
    if nr <= {_number(LOOP_TOLERANCE)}*scale, return; endif
    n = numel(z); Jm = zeros(n);
    for j = 1:n
      zp = z; d = {_number(SQRT_EPS)}*max(1,abs(z(j))); zp(j) = zp(j) + d;
      Jm(:,j) = (f(zp) - r)/d;
    endfor
    if any(~isfinite(Jm(:))) || rcond(Jm) < eps
      error('OctaLink: algebraic loop at %s: the loop Jacobian is singular at t=%g; the loop has no unique solution', name, t);
    endif
    step = Jm\\(-r); fraction = 1;
    while true
      trial = z + fraction*step; tr = f(trial);
      if all(isfinite(tr)), tn = max(abs(tr)); else tn = Inf; endif
      if tn < nr || fraction <= {_number(LOOP_MIN_STEP)}, break; endif
      fraction = fraction/2;
    endwhile
    if ~(tn < nr)
      if nr <= {_number(LOOP_STALL_TOLERANCE)}*scale, return; endif
      error('OctaLink: algebraic loop at %s: Newton iteration stalled at t=%g (residual %g)', name, t, nr);
    endif
    z = trial; r = tr;
  endfor
  error('OctaLink: algebraic loop at %s: Newton iteration did not converge at t=%g', name, t);
endfunction
'''


def _generate(document, specs, standalone=False):
    from octalink_engine_support import SOLVERS
    solver = document.get("solver", "rk4")
    if solver not in SOLVERS:
        raise ValueError(f"Solver must be one of: {', '.join(SOLVERS)}.")
    engine, compiled, schedule, periods, events, epsilon, sinks, labels = _compile(document, specs)
    blocks, sources, parsed, slices, ss, direct, order, nstates = compiled
    index = {b: i + 1 for i, b in enumerate(blocks)}
    discrete_tf = ("Discrete Transfer Fcn", "Discrete Zero-Pole")
    # Discrete transfer states live in z after the per-block held values.
    dstate, offset = {}, len(blocks)
    for b in blocks:
        if b.block_type in discrete_tf:
            n = ss[b][0].shape[0]
            dstate[b] = (offset + 1, offset + n)
            offset += n

    def source(conn):
        # Signals are plain locals: scalars, or column vectors for Mux/vector
        # blocks. Widths were fixed by the compiler, so no runtime wrappers.
        b, port = conn
        value = f"v_{index[b]}"
        return value + f"({port + 1})" if b.block_type == "Demux" else value

    def state(b):
        sl = slices[b]
        return f"x({sl.start + 1}:{sl.stop})" if sl.stop - sl.start > 1 else f"x({sl.start + 1})"

    evaluated = [b for b in blocks if not direct[b]] + order
    loops = engine.algebraic_loops
    loop_of = {b: k for k, loop in enumerate(loops, 1) for b in loop.members}
    # Signals ol_run needs at major steps: sinks, and inputs captured by
    # Unit Delay / discrete transfer blocks at their sample hits.
    export_slot = {}
    for code in [f"v_{index[s]}" for s in sinks] + [source(sources[b][0]) for b in blocks
                                                   if b.block_type == "Unit Delay" or b in dstate]:
        export_slot.setdefault(code, len(export_slot) + 1)
    # Octave rebuilds a matrix literal on every evaluation; constant matrices
    # are created once in persistent variables (measured: the dominant cost).
    constants = []

    def _hoisted(value):
        a = np.asarray(value, dtype=float)
        if a.size == 1:
            return _number(a.ravel()[0])
        constants.append(_matrix_literal(a))
        return f"K{len(constants)}"

    def _inline(value):
        a = np.asarray(value, dtype=float)
        return _number(a.ravel()[0]) if a.size == 1 else _matrix_literal(a)

    lines = ["1; % OctaLink standalone script: GNU Octave 7+; all integration executes here.",
             "% Generated from the validated detached model; no Python required.", _HELPERS]
    if loops:
        lines.append(_loop_helpers())
    if solver == "sdirk4":
        lines.append(_sdirk4_helper())
    evaluate_lines = ["function [dx,z,out] = ol_evaluate(t,x,z,update,hits)",
                      "%CONSTANTS%",
                      f"dx = zeros({nstates},1);"]

    def emit(b, lines, target, _matrix):
        """Append block b's output computation, assigning it to ``target``."""
        i, kind, p = index[b], b.block_type, parsed[b]
        num = lambda key: _number(p[key])
        raw = [source(c) for c in sources[b]]
        u = raw[0] if raw else "0"
        if kind == "Step":
            lines.append(f"if t >= {num('step_time')}, {target}={num('final_val')}; else {target}={num('initial_val')}; endif")
            expression = None
        elif kind == "Sine Wave":
            expression = f"{num('amplitude')}*sin({num('frequency')}*t+{num('phase')})"
        elif kind == "Constant":
            expression = num("value")
        elif kind == "Pulse Generator":
            expression = (f"ol_pulse(t,{num('amplitude')},{num('period')},{num('pulse_width')},"
                          f"{num('phase_delay')})")
        elif kind in discrete_tf:
            A, B, C, D = ss[b]
            first, last = dstate.get(b, (0, -1))
            held = f"{_matrix(C)}*z({first}:{last})" if A.shape[0] else "0"
            if direct[b]:
                held += f"+{_number(D)}*{u}"
            lines.append(f"if update && hits({i}), z({i})={held}; endif")
            expression = f"z({i})"
        elif kind == "Integrator":
            expression = state(b)
        elif kind in ("Unit Delay", "Zero-Order Hold", "Relay"):
            expression = f"z({i})"
            if kind == "Zero-Order Hold":
                lines.append(f"if update && hits({i}), z({i})={u}; endif")
            elif kind == "Relay":
                lines.append(f"if update, if {u}>={num('switch_on_point')}, z({i})={num('on_val')}; elseif {u}<={num('switch_off_point')}, z({i})={num('off_val')}; endif; endif")
        elif kind == "Gain":
            gain = p["gain"]
            if isinstance(gain, float):
                expression = f"{num('gain')}*{u}"
            elif p["matrix_gain"]:
                expression = f"{_matrix(gain)}*{u}"
            else:
                expression = f"reshape({_matrix(gain)},[],1).*{u}"
        elif kind == "Sum":
            expression = "0" + "".join(f"{sign}{value}" for sign, value in zip(p["signs"], raw))
        elif kind == "Product":
            expression = "1"
            for op, value in zip(p["ops"], raw):
                if op == "/":
                    lines.append(f"if {value}==0, error('OctaLink: division by zero'); endif")
                expression = f"({expression}{op}{value})"
        elif kind == "Trig":
            expression = f"{p['operator']}({u})"
        elif kind == "Octave Function":
            lines.append(f"u_vec = {raw[0]};")
            expression = translate_expression(p["expression"], variables=engine.variables)
        elif kind == "Saturation":
            expression = f"min(max({u},{num('lower_limit')}),{num('upper_limit')})"
        elif kind == "Switch":
            lines.append(f"if {raw[1]} >= {num('threshold')}, {target}={u}; else {target}={raw[2]}; endif")
            expression = None
        elif kind == "PID Controller":
            sl = slices[b]
            expression = f"{num('Kp')}*{u}+{num('Ki')}*x({sl.start + 1})+{num('Kd')}*{num('N')}*({u}-x({sl.start + 2}))"
        elif kind in ("Transfer Fcn", "State-Space"):
            A, B, C, D = ss[b]
            expression = f"{_matrix(C)}*{state(b)}" if A.shape[0] else "0"
            if direct[b]:
                expression += f"+{_matrix(D) if isinstance(D, np.ndarray) else _number(D)}*{u}"
        elif kind == "Mux":
            expression = "[" + ";".join(raw) + "]"
        elif kind in ("Demux", "Scope", "To CSV"):
            expression = raw[0]
        else:
            raise ValueError(f"Unsupported Octave block: {kind}")
        if expression is not None:
            lines.append(f"{target} = {expression};")

    # Each algebraic loop becomes a residual function of its cut guesses g:
    # cut outputs read g, the cut blocks' own outputs go to w_*, and the
    # residual is w - g. ol_newton solves it; a final call sets the members.
    # Octave passes z by value, so every trial starts from the same held values.
    header, loop_functions, loop_calls = lines, [], {}
    for k, loop in enumerate(loops, 1):
        members = set(loop.members)
        external = list(dict.fromkeys(f"v_{index[c[0]]}" for b in loop.members for c in sources[b]
                                      if c[0] not in members))
        outputs = ",".join(f"v_{index[b]}" for b in loop.members)
        loop_functions.append(f"function [r,z,{outputs}] = ol_loop_{k}({','.join(['t,x,z,update,hits,g'] + external)})")
        loop_functions += [f"v_{index[c]} = g({j});" for j, c in enumerate(loop.cuts, 1)]
        for b in loop.members:
            emit(b, loop_functions, f"w_{index[b]}" if b in loop.cut_set else f"v_{index[b]}", _inline)
        loop_functions += ["r = [" + ";".join(f"w_{index[c]}" for c in loop.cuts) + "] - g;", "endfunction"]
        rest = "".join("," + name for name in external)
        loop_calls[k] = [f"if isempty(ol_g{k}), ol_g{k} = zeros({len(loop.cuts)},1); endif",
                         f"ol_g{k} = ol_newton(@(g) ol_loop_{k}(t,x,z,update,hits,g{rest}), "
                         f"ol_g{k}, {_string(loop.name)}, t);",
                         f"[~,z,{outputs}] = ol_loop_{k}(t,x,z,update,hits,ol_g{k}{rest});"]
    for b in evaluated:
        k = loop_of.get(b)
        if k is None:
            emit(b, evaluate_lines, f"v_{index[b]}", _hoisted)
        elif k in loop_calls:
            evaluate_lines += loop_calls.pop(k)
    lines = header + loop_functions + evaluate_lines
    for b, sl in slices.items():
        kind, p = b.block_type, parsed[b]
        u = source(sources[b][0])
        if kind == "Integrator":
            derivative = u
        elif kind == "PID Controller":
            derivative = f"[{u};{_number(p['N'])}*({u}-x({sl.start + 2}))]"
        else:
            A, B, C, D = ss[b]
            if not A.shape[0]:
                continue
            derivative = f"{_hoisted(A)}*{state(b)}+{_hoisted(B)}*{u}"
        target = f"dx({sl.start + 1})" if sl.stop - sl.start == 1 else f"dx({sl.start + 1}:{sl.stop})"
        lines.append(f"{target} = {derivative};")
    # One vectorised finiteness/realness check per evaluation; the slow
    # per-block search runs only when it has already failed.
    # Every vector signal is a column (Mux stacks with ';', C*x, K*u), so the
    # signals concatenate vertically without per-signal reshapes.
    signal_list = ";".join(f"v_{index[b]}" for b in evaluated)
    names = ",".join(_string(b.name) for b in evaluated)
    values = ",".join(f"v_{index[b]}" for b in evaluated)
    lines += [f"check = [{signal_list}; dx];",
              f"if ~isreal(check) || any(~isfinite(check)), ol_fail(t, {{{names}}}, {{{values}}}); endif",
              "if nargout > 2",
              f"out = {{{','.join(f'reshape({code},1,[])' for code in export_slot)}}};",
              "endif", "endfunction", "function results = ol_run()",
              f"times = {_matrix_literal(schedule)}';",
              f"x = {_matrix_literal(engine._initial_state_vector(slices, parsed, nstates))}';",
              f"z = zeros({offset},1); pending=z; has_pending=false(size(z));",
              "next_sample = zeros(size(z)); results=struct('id',{},'time',{},'values',{},'labels',{});"]
    for b in blocks:
        if b.block_type in ("Unit Delay", "Relay"):
            key = "initial_condition" if b.block_type == "Unit Delay" else "off_val"
            lines.append(f"z({index[b]})={_number(parsed[b][key])};")
    for s, b in enumerate(sinks, 1):
        lines.append(f"Y{s}=zeros(numel(times),{len(labels[b.block_id])});")
    lines += ["stride=max(1,floor(numel(times)/100));",
              "for step=1:numel(times)", "t=times(step); hits=false(size(z));"]
    for b, ts in periods.items():
        i = index[b]
        lines.append(f"if abs(t-next_sample({i})*{_number(ts)}) <= {_number(epsilon)}, hits({i})=true; next_sample({i})+=1; endif")
    delay_indices = [index[b] for b in blocks if b.block_type == "Unit Delay"]
    if delay_indices:
        lines += [f"delay_indices={_matrix_literal(delay_indices)};",
                  "commit=delay_indices(hits(delay_indices) & has_pending(delay_indices)); z(commit)=pending(commit);"]
    lines.append("[k1,z,out]=ol_evaluate(t,x,z,true,hits);")
    for s, b in enumerate(sinks, 1):
        lines.append(f"Y{s}(step,:)=out{{{export_slot[f'v_{index[b]}']}}};")
    for b in blocks:
        if b.block_type == "Unit Delay":
            i = index[b]
            lines.append(f"if hits({i}), pending({i})=out{{{export_slot[source(sources[b][0])]}}}; has_pending({i})=true; endif")
        elif b in dstate:
            # x[k+1] = A x[k] + B u[k]; the held output z(i) is unchanged.
            A, B, _, _ = ss[b]
            first, last = dstate[b]
            lines.append(f"if hits({index[b]}), z({first}:{last})={_matrix_literal(A)}*z({first}:{last})"
                         f"+{_matrix_literal(B)}*out{{{export_slot[source(sources[b][0])]}}}; ol_finite(z); endif")
    # Serialize IEEE nextafter endpoints so every time-dependent block sees
    # exactly the same left endpoint as Python, without an Octave package.
    lines += [f"if {nstates}>0 && step<numel(times)", "tn=times(step+1); h=tn-t; t_end=tn;"]
    for event in sorted(events):
        lines.append(f"if tn == {_number(event)}, t_end={_number(math.nextafter(event,0))}; endif")
    if solver == "sdirk4":
        lines.append("x=ol_sdirk4(t,x,z,hits,k1,h,t_end); ol_finite(x); endif")
    else:
        lines += ["k2=ol_evaluate(t+h/2,x+h*k1/2,z,false,hits);",
                  "k3=ol_evaluate(t+h/2,x+h*k2/2,z,false,hits);",
                  "k4=ol_evaluate(t_end,x+h*k3,z,false,hits);",
                  "x=x+h*(k1+2*k2+2*k3+k4)/6; ol_finite(x); endif"]
    lines += [
              "if mod(step-1,stride)==0 || step==numel(times), fprintf('OCTALINK_PROGRESS %.17g\\n',step/numel(times)); fflush(stdout); endif",
              "endfor"]
    for s, b in enumerate(sinks, 1):
        label_values = ",".join(_string(l) for l in labels[b.block_id])
        lines += [f"results({s}).id={b.block_id}; results({s}).time=times;",
                  f"results({s}).values=Y{s}; results({s}).labels={{{label_values}}};"]
    lines += ["endfunction", "octalink_results=ol_run();",
              "outdir=fileparts(mfilename('fullpath'));",
              "for sink=1:numel(octalink_results)",
              "r=octalink_results(sink); target=fullfile(outdir,sprintf('octalink_sink_%d.csv',r.id));",
              "dlmwrite(target,[r.time,r.values],',','precision','%.17g');", "endfor"]
    if standalone:
        lines += ["% Interactive plotting is optional; headless runs can set OCTALINK_NO_PLOT=1.",
                  "if ~strcmp(getenv('OCTALINK_NO_PLOT'),'1')",
                  "for sink=1:numel(octalink_results)",
                  "r=octalink_results(sink); figure(); plot(r.time,r.values); grid on; xlabel('Time (s)'); ylabel('Signal'); legend(r.labels);",
                  "endfor", "endif"]
    lines.append("fprintf('OCTALINK_COMPLETE\\n'); fflush(stdout);")
    names = " ".join(f"K{i}" for i in range(1, len(constants) + 1))
    hoisted = ([f"persistent {names}", "if isempty(K1)"] +
               [f"K{i} = {literal};" for i, literal in enumerate(constants, 1)] + ["endif"]) if constants else []
    if loops:
        # Loop warm starts: the previous solution, as in the Python engine.
        hoisted.insert(0, "persistent " + " ".join(f"ol_g{k}" for k in range(1, len(loops) + 1)))
    position = lines.index("%CONSTANTS%")
    lines[position:position + 1] = hoisted
    return "\n".join(lines) + "\n", schedule, sinks, labels


def export_octave_script(document, specs, filepath):
    """Write a standalone GNU Octave .m script with plots and per-sink CSVs."""
    source, _, _, _ = _generate(document, specs, standalone=True)
    path = Path(filepath).resolve()
    path.write_text(source, encoding="utf-8", newline="\n")
    return path


def run_octave_simulation(document, specs, executable=None, cancel_check=None, progress_callback=None):
    """Run an isolated cancellable Octave job, publishing complete results only.

    OCTALINK_OCTAVE_TIMEOUT sets the wall-clock budget (default 600 seconds; Stop cancels sooner).
    Progress callbacks are monotone and execute in the calling thread. CSV
    sink destinations are published by the caller, after successful completion.
    """
    from octalink_engine_support import SimulationCancelled

    def check_cancelled():
        if cancel_check is not None and cancel_check():
            raise SimulationCancelled("Octave simulation cancelled.")

    check_cancelled()
    path = discover_octave(executable)
    if path is None:
        raise FileNotFoundError("GNU Octave was not found. Install Octave or set OCTALINK_OCTAVE to its executable.")
    timeout = float(os.environ.get("OCTALINK_OCTAVE_TIMEOUT", "600"))
    if not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise ValueError("OCTALINK_OCTAVE_TIMEOUT must be finite and in (0,86400].")
    source, schedule, sinks, labels = _generate(document, specs)
    check_cancelled()
    if progress_callback is not None:
        progress_callback(0.0)
    with tempfile.TemporaryDirectory(prefix="octalink-octave-") as directory:
        job = Path(directory)
        (job / "octalink_job.m").write_text(source, encoding="utf-8")
        stdout_path, stderr_path = job / "stdout.txt", job / "stderr.txt"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        start = time.monotonic()
        process = None
        try:
            with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                process = subprocess.Popen([path, "--no-gui", "--quiet", "--no-init-file", "--no-site-file", "octalink_job.m"],
                                           cwd=job, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                           shell=False, creationflags=flags)
                last_progress, offset, remainder = 0.0, 0, ""
                while process.poll() is None:
                    check_cancelled()
                    if time.monotonic() - start > timeout:
                        raise TimeoutError(f"GNU Octave exceeded its {timeout:g} second timeout.")
                    if stdout_path.stat().st_size > 1_000_000 or stderr_path.stat().st_size > 1_000_000:
                        raise RuntimeError("GNU Octave exceeded its diagnostic output limit.")
                    if progress_callback is not None:
                        with stdout_path.open("r", encoding="utf-8", errors="replace") as progress:
                            progress.seek(offset)
                            chunk = progress.read()
                            offset = progress.tell()
                        complete = (remainder + chunk).split("\n")
                        remainder = complete.pop()
                        for line in complete:
                            if line.startswith("OCTALINK_PROGRESS "):
                                value = float(line.split()[1])
                                if math.isfinite(value) and last_progress < value < 1:
                                    last_progress = value
                                    progress_callback(value)
                    time.sleep(.03)
                check_cancelled()
            if stdout_path.stat().st_size > 1_000_000 or stderr_path.stat().st_size > 1_000_000:
                raise RuntimeError("GNU Octave exceeded its diagnostic output limit.")
            output = stdout_path.read_text(encoding="utf-8", errors="replace")
            error = stderr_path.read_text(encoding="utf-8", errors="replace")
            if process.returncode != 0 or "OCTALINK_COMPLETE\n" not in output:
                raise RuntimeError(f"GNU Octave simulation failed (exit {process.returncode}):\n{error[-12000:]}\n{output[-2000:]}")
            results = {}
            for b in sinks:
                check_cancelled()
                csv = job / f"octalink_sink_{b.block_id}.csv"
                width = 1 + len(labels[b.block_id])
                if not csv.is_file() or csv.stat().st_size > len(schedule) * width * 32:
                    raise RuntimeError("GNU Octave returned a missing or oversized result file.")
                data = np.loadtxt(csv, delimiter=",", ndmin=2)
                if data.shape != (len(schedule), width) or not np.all(np.isfinite(data)):
                    raise RuntimeError("GNU Octave returned invalid or non-finite results.")
                if not np.array_equal(data[:, 0], np.asarray(schedule)):
                    raise RuntimeError("GNU Octave returned an unexpected sample schedule.")
                results[b.block_id] = (data[:, 0].tolist(), data[:, 1:].tolist(), labels[b.block_id])
            check_cancelled()
            if progress_callback is not None:
                progress_callback(1.0)
            return results
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
