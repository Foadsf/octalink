"""Bounded arithmetic expressions for the local simulation engine.

This interpreter deliberately supports mathematics rather than Python or an
Octave workspace. No attribute access, imports, statements or arbitrary calls
are evaluated. Vector indices are zero based, e.g. ``u_vec[0]``.
"""

import ast
from functools import lru_cache
import keyword
import math
import operator
import re


class SimulationCancelled(RuntimeError):
    """A requested simulation cancellation; partial results are not published."""


class AlgebraicLoopError(RuntimeError):
    """An algebraic loop that cannot be cut or whose Newton iteration failed."""


# Fixed-step solvers a model may select ("solver" in the document).
SOLVERS = ("rk4", "sdirk4")
SOLVER_LABELS = {"rk4": "RK4 (explicit)", "sdirk4": "SDIRK4 (implicit, stiff)"}
SQRT_EPS = 1.4901161193847656e-08   # sqrt(2**-52), the forward-difference step scale

# Hairer & Wanner, Solving ODEs II, Table IV.6.5: SDIRK of order 4, L-stable
# and stiffly accurate (b = last row of A), so x[n+1] is the last stage. One
# numerical Jacobian and one iteration matrix I - h/4 J serve all five stages.
# The Octave backend emits exactly these coefficients and the same iteration.
SDIRK4_GAMMA = 0.25
SDIRK4_A = ((), (1 / 2,), (17 / 50, -1 / 25), (371 / 1360, -137 / 2720, 15 / 544),
            (25 / 24, -49 / 48, 125 / 16, -85 / 12))
SDIRK4_C = (1 / 4, 3 / 4, 11 / 20, 1 / 2, 1.0)
STAGE_NEWTON_ITERATIONS = 10
STAGE_NEWTON_TOLERANCE = 1e-10      # max |increment| <= tol * (1 + max |stage|)
# Algebraic loops: Newton on the loop-cut signals with a forward-difference
# Jacobian and a halving line search, warm-started from the previous solution.
LOOP_NEWTON_ITERATIONS = 50
LOOP_TOLERANCE = 1e-12              # max |F(z) - z| <= tol * (1 + max |z|)
LOOP_STALL_TOLERANCE = 1e-8         # accepted only when no step can reduce it further
LOOP_MIN_STEP = 2.0 ** -10


def strongly_connected_components(nodes, successors):
    """Tarjan's algorithm without recursion; components in reverse topological order."""
    index, low, on_stack, stack, result = {}, {}, set(), [], []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(successors[root]))]
        while work:
            node, pending = work[-1]
            descended = False
            for successor in pending:
                if successor not in index:
                    index[successor] = low[successor] = counter
                    counter += 1
                    stack.append(successor)
                    on_stack.add(successor)
                    work.append((successor, iter(successors[successor])))
                    descended = True
                    break
                if successor in on_stack:
                    low[node] = min(low[node], index[successor])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member is node:
                        break
                result.append(component)
    return result


def cyclic_components(nodes, successors):
    """Components that contain a cycle (two or more nodes, or a self-edge)."""
    return [c for c in strongly_connected_components(nodes, successors)
            if len(c) > 1 or c[0] in successors[c[0]]]


def _max_abs(values):
    return max((abs(float(v)) for v in values), default=0.0)


def solve_algebraic_loop(residual, guess, name, t):
    """Newton on z with residual(z) = F(z) - z; returns the converged z.

    ``residual`` returns a float sequence and may raise for invalid signals.
    The Octave backend's ol_newton performs the same iteration.
    """
    import numpy as np
    z = np.array(guess, dtype=float)
    r = np.asarray(residual(z), dtype=float)
    if not np.all(np.isfinite(r)):
        raise AlgebraicLoopError(f"Algebraic loop at {name}: non-finite residual at t={t:g}.")
    for _ in range(LOOP_NEWTON_ITERATIONS):
        scale = 1.0 + _max_abs(z)
        norm = _max_abs(r)
        if norm <= LOOP_TOLERANCE * scale:
            return z
        jacobian = np.empty((len(z), len(z)))
        for j in range(len(z)):
            perturbed = z.copy()
            delta = SQRT_EPS * max(1.0, abs(z[j]))
            perturbed[j] += delta
            jacobian[:, j] = (np.asarray(residual(perturbed), dtype=float) - r) / delta
        if not np.all(np.isfinite(jacobian)) or reciprocal_condition(jacobian) < np.finfo(float).eps:
            raise AlgebraicLoopError(f"Algebraic loop at {name}: the loop Jacobian is singular at t={t:g}; "
                                     "the loop has no unique solution. Insert a delay or integrator.")
        step = np.linalg.solve(jacobian, -r)
        fraction = 1.0
        while True:
            trial = z + fraction * step
            trial_r = np.asarray(residual(trial), dtype=float)
            trial_norm = _max_abs(trial_r) if np.all(np.isfinite(trial_r)) else math.inf
            if trial_norm < norm or fraction <= LOOP_MIN_STEP:
                break
            fraction /= 2
        if not trial_norm < norm:
            if norm <= LOOP_STALL_TOLERANCE * scale:
                return z
            raise AlgebraicLoopError(f"Algebraic loop at {name}: Newton iteration stalled at t={t:g} "
                                     f"(residual {norm:.3g}).")
        z, r = trial, trial_r
    raise AlgebraicLoopError(f"Algebraic loop at {name}: Newton iteration did not converge at t={t:g}.")


def reciprocal_condition(matrix):
    """1-norm reciprocal condition number (0 for a singular matrix)."""
    import numpy as np
    try:
        with np.errstate(all="ignore"):
            value = 1.0 / np.linalg.cond(matrix, 1)
    except np.linalg.LinAlgError:
        return 0.0
    return float(value) if math.isfinite(value) else 0.0


def sdirk4_step(derivative, t, x, f0, h, t_end):
    """One SDIRK4 step of x' = derivative(t, x) from (t, x) with f0 = derivative(t, x).

    The last stage is evaluated at ``t_end`` (the left limit before a source
    discontinuity, as RK4's last stage is). Raises ValueError on failure.
    """
    import numpy as np
    n = len(x)
    jacobian = np.empty((n, n))
    for j in range(n):
        perturbed = x.copy()
        delta = SQRT_EPS * max(1.0, abs(x[j]))
        perturbed[j] += delta
        jacobian[:, j] = (derivative(t, perturbed) - f0) / delta
    gh = SDIRK4_GAMMA * h
    iteration = np.eye(n) - gh * jacobian
    if not np.all(np.isfinite(iteration)) or reciprocal_condition(iteration) < np.finfo(float).eps:
        raise ValueError(f"Implicit SDIRK4 iteration matrix is singular at t={t:g}; reduce dt or check the model.")
    stages, previous = [], f0
    for s, (row, c) in enumerate(zip(SDIRK4_A, SDIRK4_C)):
        base = x.copy()
        for a, k in zip(row, stages):
            base += (h * a) * k
        stage_t = t_end if s == len(SDIRK4_C) - 1 else t + c * h
        y = base + gh * previous
        for _ in range(STAGE_NEWTON_ITERATIONS):
            increment = np.linalg.solve(iteration, -(y - base - gh * derivative(stage_t, y)))
            y = y + increment
            if not np.all(np.isfinite(y)):
                break
            if _max_abs(increment) <= STAGE_NEWTON_TOLERANCE * (1.0 + _max_abs(y)):
                break
        else:
            raise ValueError(f"Implicit SDIRK4 Newton iteration did not converge at t={t:g}; reduce dt.")
        if not np.all(np.isfinite(y)):
            raise ValueError(f"Non-finite implicit SDIRK4 stage at t={t:g}; reduce dt or check the model.")
        previous = (y - base) / gh
        stages.append(previous)
    return y


FUNCTIONS = {name: getattr(math, name) for name in
             ("sin", "cos", "tan", "asin", "acos", "atan", "tanh",
              "exp", "log", "sqrt", "floor", "ceil")}
FUNCTIONS.update(abs=abs, min=min, max=max)
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub,
          ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.Pow: operator.pow, ast.Mod: operator.mod}
RESERVED_NAMES = {"pi", "e", "u", "t", "u_vec"} | set(FUNCTIONS)
MAX_VARIABLES = 256


def normalize_operators(text, allowed):
    """Simulink-style Sum signs / Product ops: "|+-", "+-+" or a port count.

    ``|`` is a layout spacer and is ignored; a positive integer n means n
    copies of the first allowed operator (``"3"`` -> ``"+++"``).
    """
    value = str(text).strip()
    if value.isdigit():
        count = int(value)
        if not 1 <= count <= 64:
            raise ValueError("Input count must be from 1 to 64.")
        return allowed[0] * count
    value = value.replace("|", "").replace(" ", "")
    if not value or len(value) > 64 or any(c not in allowed for c in value):
        raise ValueError(f"Use only {' or '.join(allowed)} for each input (| is a spacer).")
    return value


def port_counts(kind, params, spec):
    """Input/output port counts implied by a block's parameters."""
    inputs, outputs = spec["inputs"], spec["outputs"]
    if kind == "Mux":
        inputs = max(2, int(params["inputs"]))
    elif kind == "Demux":
        outputs = max(2, int(params["outputs"]))
    elif kind == "Sum":
        inputs = len(normalize_operators(params["signs"], "+-"))
    elif kind == "Product":
        inputs = len(normalize_operators(params["ops"], "*/"))
    return inputs, outputs


def resolve_variables(raw):
    """Evaluate an ordered Model Workspace of scalar or array expressions.

    Each value may use variables defined before it. Arrays use bracket syntax
    whose elements are scalar expressions. Returns ``(scalars, arrays)`` with
    arrays as lists of rows.
    """
    if raw is None:
        return {}, {}
    if not isinstance(raw, dict):
        raise ValueError("Model variables must be a name/value object.")
    if len(raw) > MAX_VARIABLES:
        raise ValueError(f"A model supports at most {MAX_VARIABLES} variables.")
    scalars, arrays = {}, {}
    for name, value in raw.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", name)
                or name in RESERVED_NAMES or keyword.iskeyword(name)):
            raise ValueError(f"Invalid variable name {name!r}: use a letter followed by letters, digits or _, "
                             "not a reserved name (u, t, pi, e or a function).")
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError(f"Variable {name} must be a number or expression text.")
        text = str(value).strip()
        try:
            if text.startswith("["):
                arrays[name] = parse_array(text, scalars)
                if len({len(row) for row in arrays[name]}) > 1:
                    raise ValueError("Matrix rows must all have the same length.")
            else:
                scalars[name] = evaluate_expression(text, variables=scalars)
        except ValueError as exc:
            raise ValueError(f"Variable {name}: {exc}") from None
    return scalars, arrays


def parse_array(text, variables=None):
    """Rows of a bracketed real array; ``;`` separates rows."""
    s = str(text).strip()
    if not (s.startswith("[") and s.endswith("]")):
        raise ValueError("Array expression has an unmatched bracket.")
    s = s[1:-1].strip()
    if not s:
        return []
    rows = []
    for row in s.split(";"):
        if not row.strip():
            raise ValueError("Array expression contains an empty row.")
        # Split only at the outer level, preserving commas and whitespace
        # inside function calls; binary operators keep their operands.
        tokens, start, depth = [], 0, 0
        for index, character in enumerate(row):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif character == "," and depth == 0:
                tokens.append(row[start:index])
                start = index + 1
        if tokens:
            tokens.append(row[start:])
        else:
            tokens = _split_whitespace_elements(row)
        rows.append([evaluate_expression(token, variables=variables) for token in tokens])
    # Vector parameters accept "[1, 2; 3]"; matrix users check rectangularity.
    return rows


def _split_whitespace_elements(row):
    """MATLAB array spacing: ``[1 -2]`` has two elements, ``[1 - 2]`` one."""
    text = row.strip()
    tokens, current, depth, i = [], "", 0, 0
    while i < len(text):
        character = text[i]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        if character.isspace() and depth == 0:
            j = i
            while j < len(text) and text[j].isspace():
                j += 1
            previous = current.rstrip()[-1:] if current.strip() else ""
            following = text[j] if j < len(text) else ""
            after = text[j + 1] if j + 1 < len(text) else ""
            joined = (not previous or previous in "*/^+-(,"
                      or following in "*/^)"
                      or (following in "+-" and (after.isspace() or not after)))
            if joined:
                current += " "
            else:
                tokens.append(current)
                current = ""
            i = j
            continue
        current += character
        i += 1
    if current.strip():
        tokens.append(current)
    return tokens


@lru_cache(maxsize=512)
def parse_expression(expression, allow_signal=False, variable_names=frozenset()):
    expression = str(expression).strip().replace("^", "**")
    if not expression or len(expression) > 2048:
        raise ValueError("Expression must contain 1 to 2048 characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError(f"Invalid mathematical expression: {expression!r}") from exc
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise ValueError("Expression is too complex (maximum 256 syntax nodes).")
    names = {"pi", "e"} | ({"u", "t", "u_vec"} if allow_signal else set()) | set(variable_names)

    def validate(node):
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float):
                raise ValueError("Only real numeric constants are allowed.")
        elif isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError(f"Unknown variable {node.id}; define it in Modeling > Model Workspace.")
            if node.id == "u_vec":
                raise ValueError("Use an indexed vector element, e.g. u_vec[0].")
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            validate(node.left)
            validate(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            validate(node.operand)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ValueError("Only named mathematical functions are allowed.")
            if node.keywords or not 1 <= len(node.args) <= 8:
                raise ValueError("Mathematical functions require 1 to 8 positional arguments.")
            for argument in node.args:
                validate(argument)
        elif isinstance(node, ast.Subscript) and allow_signal:
            if not (isinstance(node.value, ast.Name) and node.value.id == "u_vec"
                    and isinstance(node.slice, ast.Constant)
                    and type(node.slice.value) is int and 0 <= node.slice.value <= 255):
                raise ValueError("Vector indices must be literal integers from 0 to 255.")
        else:
            raise ValueError(f"Unsupported expression syntax: {type(node).__name__}")

    validate(tree.body)
    return tree.body


def evaluate_expression(expression, signals=None, variables=None):
    """Evaluate bounded real arithmetic; ``variables`` are scalar names."""
    variables = variables or {}
    tree = parse_expression(str(expression), signals is not None, frozenset(variables))
    values = {"pi": math.pi, "e": math.e}
    values.update(variables)
    if signals:
        values.update(signals)

    def evaluate(node):
        if isinstance(node, ast.Constant):
            result = float(node.value)
        elif isinstance(node, ast.Name):
            result = values[node.id]
        elif isinstance(node, ast.Subscript):
            result = values["u_vec"][node.slice.value]
        elif isinstance(node, ast.UnaryOp):
            result = evaluate(node.operand)
            if isinstance(node.op, ast.USub):
                result = -result
        elif isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1024:
                raise ValueError("Exponent magnitude exceeds 1024.")
            result = BINARY[type(node.op)](left, right)
        else:
            result = FUNCTIONS[node.func.id](*(evaluate(arg) for arg in node.args))
        result = float(result)
        if not math.isfinite(result):
            raise ValueError("Expression produced a non-finite value.")
        return result

    try:
        return evaluate(tree)
    except (ArithmeticError, IndexError, TypeError) as exc:
        raise ValueError(f"Cannot evaluate mathematical expression {expression!r}: {exc}") from exc
