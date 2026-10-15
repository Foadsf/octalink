"""Local SISO Jacobian analysis, using the same graph evaluator as simulation.

Continuous state poles describe the complete realization. Transfer zeros are
computed after removing unreachable/unobservable modes. Crossing margins treat
the selected transfer as a hypothetical unity-negative-feedback loop; they are
never inferred to be the diagram's actual loop margins.
"""
import math
from collections import deque

import numpy as np

from mvp_model import GraphObject, detached_graph

SOURCE_TYPES = ("Step", "Sine Wave", "Constant", "Pulse Generator")


def analyze_model(document, specs, **options):
    """Analyze a validated detached document; selected IDs use document block IDs."""
    # Lazy import avoids a cycle when the GUI uses this helper.
    from octalink_gui import SimulationEngine
    options.setdefault("t_stop", float(document.get("stop_time", 10)))
    options.setdefault("dt", float(document.get("dt", .01)))
    return analyze_scene(detached_graph(document, specs), SimulationEngine(), **options)


def _select(blocks, selector, description):
    if not blocks:
        raise ValueError(f"Linear analysis requires a {description}.")
    if selector is None:
        return blocks[0]
    matches = [b for b in blocks if b is selector or getattr(b, "block_id", None) == selector or b.name == selector]
    if len(matches) != 1:
        raise ValueError(f"Select one valid {description} by block ID or unique name.")
    return matches[0]


def _sort_direct(blocks, source_map, direct):
    pending = [b for b in blocks if direct[b]]
    degrees = {b: 0 for b in pending}
    adjacency = {b: [] for b in pending}
    for b in pending:
        for src, _ in source_map[b]:
            if direct[src]:
                degrees[b] += 1
                adjacency[src].append(b)
    queue = deque(b for b in pending if not degrees[b])
    result = []
    while queue:
        block = queue.popleft()
        result.append(block)
        for next_block in adjacency[block]:
            degrees[next_block] -= 1
            if not degrees[next_block]:
                queue.append(next_block)
    if len(result) != len(pending):
        raise ValueError("Padé approximation introduces an algebraic loop; this hybrid model cannot be analyzed by this approximation.")
    return result


def _minimal_siso(A, B, C):
    """Orthogonal reachable then observable reductions for transfer zeros."""
    if not len(A):
        return A, B, C
    def basis(matrix):
        U, singular, _ = np.linalg.svd(matrix, full_matrices=False)
        threshold = (singular[0] if len(singular) else 0) * max(matrix.shape) * np.finfo(float).eps * 100
        return U[:, singular > threshold]
    terms, term = [], B
    for _ in range(len(A)):
        terms.append(term)
        term = A @ term
    Q = basis(np.hstack(terms))
    A, B, C = Q.T @ A @ Q, Q.T @ B, C @ Q
    if not len(A):
        return A, B, C
    terms, term = [], C
    for _ in range(len(A)):
        terms.append(term)
        term = term @ A
    Q = basis(np.vstack(terms).T)
    return Q.T @ A @ Q, Q.T @ B, C @ Q


def _transfer_polynomials(A, B, C, D):
    A, B, C = _minimal_siso(A, B, C)
    denominator = np.real_if_close(np.poly(A)).astype(float) if len(A) else np.array([1.])
    # det(sI-A) * (C(sI-A)^(-1)B+D), using Markov coefficients.
    numerator = D * denominator.copy()
    markov, term = [], B
    for index in range(len(A)):
        markov.append(float((C @ term)[0, 0]))
        numerator[index + 1] += sum(denominator[k] * markov[index - k] for k in range(index + 1))
        term = A @ term
    tolerance = max(np.max(np.abs(numerator)), np.finfo(float).tiny) * 1e-10
    nonzero = np.flatnonzero(np.abs(numerator) > tolerance)
    numerator = numerator[nonzero[0]:] if len(nonzero) else np.array([0.])
    return numerator, denominator


def crossing_margins(omega, response):
    """Interpolated crossings on the supplied finite frequency interval.

    No crossing is NaN (unknown/absent on this interval), never an assertion of
    infinite margin. All odd negative-real phase branches are considered.
    """
    w, H = np.asarray(omega), np.asarray(response)
    magnitude = 20 * np.log10(np.maximum(np.abs(H), np.finfo(float).tiny))
    phase = np.degrees(np.unwrap(np.angle(H)))
    logw = np.log(w)
    def crossings(values, target, companion):
        result = []
        for i in range(len(w) - 1):
            a, b = values[i] - target, values[i + 1] - target
            if a == 0 and b == 0:
                continue  # A continuum is not an isolated crossover.
            if a == 0 or a * b < 0 or (i == len(w) - 2 and b == 0):
                fraction = -a / (b - a)
                result.append((float(np.exp(logw[i] + fraction * (logw[i + 1] - logw[i]))),
                               float(companion[i] + fraction * (companion[i + 1] - companion[i]))))
        return result
    gc = []
    for w_gc, ph in crossings(magnitude, 0, phase):
        margin = (360 + ph) % 360 - 180
        gc.append((w_gc, 180. if margin == -180 else margin))
    pc = []
    low, high = float(min(phase)), float(max(phase))
    for k in range(math.floor((low + 180) / 360), math.ceil((high + 180) / 360) + 1):
        target = -180 + 360 * k
        pc.extend((frequency, -gain) for frequency, gain in crossings(phase, target, magnitude))
    chosen_gc = min(gc, key=lambda v: abs(v[1])) if gc else (math.nan, math.nan)
    chosen_pc = min(pc, key=lambda v: abs(v[1])) if pc else (math.nan, math.nan)
    return {"gain_margin_db": chosen_pc[1], "phase_margin_deg": chosen_gc[1],
            "w_gc": chosen_gc[0], "w_pc": chosen_pc[0],
            "gain_crossings": gc, "phase_crossings": pc,
            "interpretation": "Selected transfer interpreted as a hypothetical unity-negative-feedback loop; actual diagram loop margins are not inferred.",
            "interval": (float(w[0]), float(w[-1])),
            "missing_crossing": "No isolated crossing in the analyzed frequency interval (NaN)."}


def _matrix_exponential(matrix):
    """Scaling/squaring Taylor exponential for the bounded step-response model."""
    norm = float(np.linalg.norm(matrix, 1))
    scales = max(0, math.ceil(math.log2(norm))) if norm > 0 else 0
    if scales > 64:
        raise ValueError("Linear dynamics exceed the supported numerical scale.")
    scaled = matrix / 2. ** scales
    result = np.eye(len(matrix))
    term = result.copy()
    for order in range(1, 65):
        term = term @ scaled / order
        result += term
        if np.linalg.norm(term, 1) <= np.finfo(float).eps * max(1, np.linalg.norm(result, 1)):
            break
    for _ in range(scales):
        result = result @ result
    return result


def _step_metrics(A, B, C, D, poles, stop, dt):
    empty = {k: math.nan for k in ("rise_time", "settling_time", "overshoot_pct", "ss_error")}
    if len(poles) and np.any(poles.real >= -1e-10):
        return empty, np.array([]), np.array([]), math.nan
    dc = D - float((C @ np.linalg.solve(A, B))[0, 0]) if len(A) else D
    times = np.linspace(0, stop, max(2, int(math.ceil(stop / dt)) + 1))
    if len(A):
        augmented = np.zeros((len(A) + 1, len(A) + 1))
        augmented[:-1, :-1], augmented[:-1, -1:] = A, B
        transition = _matrix_exponential(augmented * (times[1] - times[0]))
        state = np.zeros(len(A) + 1)
        state[-1] = 1
        output = np.zeros(len(times))
        for i in range(len(times)):
            output[i] = float((C @ state[:-1])[0]) + D
            state = transition @ state
    else:
        output = np.full(len(times), D)
    if not np.all(np.isfinite(output)):
        raise ValueError("Non-finite linear step response.")
    metrics = dict(empty, ss_error=abs(1 - dc))
    if abs(dc) > 1e-10:
        normalized = output / dc
        def first_crossing(level):
            found = np.flatnonzero(normalized >= level)
            if not len(found):
                return math.nan
            i = found[0]
            return float(times[i]) if i == 0 else float(times[i - 1] + (level - normalized[i - 1]) / (normalized[i] - normalized[i - 1]) * (times[i] - times[i - 1]))
        metrics["rise_time"] = first_crossing(.9) - first_crossing(.1)
        metrics["overshoot_pct"] = max(0., float(np.max(normalized) - 1) * 100)
        outside = np.flatnonzero(np.abs(normalized - 1) > .02)
        metrics["settling_time"] = (0. if not len(outside) else float(times[outside[-1] + 1])) if not len(outside) or outside[-1] < len(times) - 1 else math.nan
    return metrics, times, output, dc


def analyze_scene(scene, engine, source_id=None, sink_id=None, channel=-1,
                  use_pade=True, operating_state=None, operating_input=None,
                  operating_time=0., t_stop=10., dt=.01, omega=None):
    """Linearize around explicit state/input/time (defaults: initial state/input).

    Source: first Step/Sine/Constant by default; sink: first Scope, then CSV.
    Channel is zero based; -1 chooses the last logged channel (plant output in
    the shipped feedback example). Other sources retain their operating values.
    Unit Delay uses Pade(Ts); ZOH uses Pade(Ts/2), both order one and approximate.
    No CSV files or scope data are written, and the caller's model is unchanged.
    """
    if not math.isfinite(t_stop) or t_stop <= 0 or not math.isfinite(dt) or dt <= 0 or t_stop / dt > 50000:
        raise ValueError("Linear step response requires positive finite stop/dt and at most 50000 intervals.")
    if not math.isfinite(operating_time):
        raise ValueError("Operating time must be finite.")
    original = engine.compile_graph(scene)
    old_blocks, old_map, old_parsed, old_slices, old_models, old_direct, _, n = original
    if n > 128:
        raise ValueError("Linear analysis supports at most 128 states.")
    clones = {b: GraphObject(block_id=getattr(b, "block_id", None), name=b.name, block_type=b.block_type) for b in old_blocks}
    blocks = list(clones.values())
    source_map = {clones[b]: [(clones[src], port) for src, port in connections] for b, connections in old_map.items()}
    parsed = {clones[b]: dict(p) for b, p in old_parsed.items()}
    slices = {clones[b]: sl for b, sl in old_slices.items()}
    models = {clones[b]: model for b, model in old_models.items()}
    direct = {clones[b]: value for b, value in old_direct.items()}
    sources = [b for b in blocks if b.block_type in SOURCE_TYPES]
    sinks = [b for b in blocks if b.block_type == "Scope"] + [b for b in blocks if b.block_type == "To CSV"]
    src = _select(sources, source_id, "source")
    sink = _select(sinks, sink_id, "Scope or CSV sink")
    initial = engine._initial_state_vector(slices, parsed, n)
    approximations = []
    for b in blocks:
        if b.block_type == "Relay":
            raise ValueError(f"{b.name}: hysteretic Relay linearization requires a specified branch and is unsupported.")
        if b.block_type in ("Discrete Transfer Fcn", "Discrete Zero-Pole"):
            raise ValueError(f"{b.name}: s-plane analysis of discrete transfer blocks is unsupported; "
                             "analyze the continuous plant or a continuous controller equivalent.")
        if b.block_type in ("Unit Delay", "Zero-Order Hold"):
            if not use_pade:
                raise ValueError("Exact discrete/hybrid frequency analysis is unsupported; enable the labeled Padé approximation.")
            tau = parsed[b]["sample_time"] * (1 if b.block_type == "Unit Delay" else .5)
            approximations.append({"block": b.name, "kind": b.block_type, "tau": tau, "order": 1})
            b.block_type = "State-Space"
            slices[b] = slice(n, n + 1)
            n += 1
            initial = np.append(initial, 0.)
            models[b] = (np.array([[-2 / tau]]), np.array([[1.]]), np.array([[4 / tau]]), -1.)
            direct[b] = True
    if n > 128:
        raise ValueError("Linear analysis supports at most 128 states including Padé approximations.")
    # Algebraic loops of the diagram itself are solved as in simulation; a loop
    # created only by the Padé substitution is rejected (see _sort_direct).
    had_loops = bool(engine.algebraic_loops)
    order, loops = engine.order_direct(blocks, source_map, direct)
    if loops and not had_loops:
        _sort_direct(blocks, source_map, direct)
    evaluator = engine._build_evaluator(blocks, source_map, parsed, slices, models, direct,
                                        order, n, {}, {}, {}, dt, algebraic_loops=loops)
    x0 = initial if operating_state is None else np.asarray(operating_state, dtype=float)
    if x0.shape != (n,) or not np.all(np.isfinite(x0)):
        raise ValueError(f"Operating state must contain {n} finite values, including Padé states.")
    baseline, residual = evaluator(operating_time, x0)
    u0 = float(baseline[src]) if operating_input is None else float(operating_input)
    if not math.isfinite(u0):
        raise ValueError("Operating input must be finite.")
    baseline, residual = evaluator(operating_time, x0, source_override={src: u0})
    for b in blocks:
        if b.block_type in ("Saturation", "Switch"):
            inp = engine._as_scalar(engine._extract_port_signal(baseline, source_map[b][1 if b.block_type == "Switch" else 0]))
            limits = [parsed[b]["threshold"]] if b.block_type == "Switch" else [parsed[b]["lower_limit"], parsed[b]["upper_limit"]]
            if any(abs(inp - bound) < 1e-7 * max(1, abs(inp)) for bound in limits):
                raise ValueError(f"{b.name}: operating point is on a nondifferentiable switching/saturation boundary.")
    channels = engine._as_vector(baseline[sink])
    if type(channel) is not int or not -len(channels) <= channel < len(channels):
        raise ValueError(f"Output channel must select one of {len(channels)} logged channels.")
    channel %= len(channels)
    def evaluate(x, u):
        outputs, derivative = evaluator(operating_time, x, source_override={src: u})
        return derivative, engine._as_vector(outputs[sink])[channel]
    A, B, C = np.zeros((n, n)), np.zeros((n, 1)), np.zeros((1, n))
    epsilon = 1e-5
    for j in range(n):
        delta = np.zeros(n)
        delta[j] = epsilon * max(1, abs(x0[j]))
        plus, yp = evaluate(x0 + delta, u0)
        minus, ym = evaluate(x0 - delta, u0)
        A[:, j], C[0, j] = (plus - minus) / (2 * delta[j]), (yp - ym) / (2 * delta[j])
    du = epsilon * max(1, abs(u0))
    plus, yp = evaluate(x0, u0 + du)
    minus, ym = evaluate(x0, u0 - du)
    B[:, 0], D = (plus - minus) / (2 * du), (yp - ym) / (2 * du)
    poles = np.linalg.eigvals(A) if n else np.array([], complex)
    numerator, denominator = _transfer_polynomials(A, B, C, D)
    zeros = np.roots(numerator).astype(complex) if len(numerator) > 1 else np.array([], complex)
    scales = np.abs(poles[np.abs(poles) > 1e-10])
    w = np.asarray(omega, dtype=float) if omega is not None else np.logspace(math.log10(min(scales) / 1000 if len(scales) else .001), math.log10(max(scales) * 1000 if len(scales) else 1000), 1000)
    if w.ndim != 1 or len(w) < 2 or not np.all(np.isfinite(w)) or np.any(w <= 0) or np.any(np.diff(w) <= 0):
        raise ValueError("Frequency array must contain increasing finite positive rad/s values.")
    transfer_A, transfer_B, transfer_C = _minimal_siso(A, B, C)
    transfer_n = len(transfer_A)
    transfer_poles = np.linalg.eigvals(transfer_A) if transfer_n else np.array([])
    for pole in transfer_poles:
        if np.any(np.abs(1j * w - pole) <= 1e-10 * max(1, abs(pole))):
            raise ValueError("Frequency response is singular at a requested frequency; change the frequency interval.")
    try:
        H = np.array([complex((transfer_C @ np.linalg.solve(1j * frequency * np.eye(transfer_n) - transfer_A, transfer_B))[0, 0] + D) if transfer_n else complex(D) for frequency in w])
    except np.linalg.LinAlgError as exc:
        raise ValueError("Frequency response is singular at a requested frequency; change the frequency interval.") from exc
    if not np.all(np.isfinite(H)):
        raise ValueError("Frequency response is singular or non-finite in the requested interval.")
    metrics, step_t, step_y, dc = _step_metrics(A, B, C, D, poles, t_stop, dt)
    original_sink = next(b for b, clone in clones.items() if clone is sink)
    labels = engine._resolve_scope_labels(original_sink, old_map)
    stability = "unstable" if np.any(poles.real > 1e-10) else "marginal" if np.any(poles.real >= -1e-10) else "stable"
    notes = ["Local Jacobian at the reported operating state/input/time.",
             "Step metrics describe the selected linear transfer's unit perturbation, measured against its exact DC gain; NaN means unavailable or the horizon is too short."]
    if approximations:
        notes.append("First-order Padé approximation of delays and ZOH; s-plane results are not exact discrete/hybrid stability results.")
    if len(residual) and np.linalg.norm(residual, np.inf) > 1e-8:
        notes.append("The chosen operating point is not an equilibrium; this is an instantaneous local Jacobian.")
    return {"A": A, "B": B, "C": C, "D": D, "poles": poles, "zeros": zeros,
            "numerator": numerator, "denominator": denominator,
            "omega": w, "freq_resp": H,
            "mag_db": 20 * np.log10(np.maximum(abs(H), 1e-15)),
            "phase_deg": np.degrees(np.unwrap(np.angle(H))),
            "margins": crossing_margins(w, H), "step_metrics": metrics,
            "step_t": step_t, "step_y": step_y, "dc_gain": dc,
            "stability": stability, "domain": "continuous", "approximations": approximations,
            "source": {"id": src.block_id, "name": src.name},
            "sink": {"id": sink.block_id, "name": sink.name, "channel": channel, "label": labels[channel]},
            "operating_point": {"state": x0.copy(), "input": u0, "time": operating_time, "derivative": residual},
            "notes": notes}
