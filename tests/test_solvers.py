"""Implicit SDIRK4 solver and algebraic-loop Newton, against independent references.

Windows/PowerShell: python -m unittest discover -s tests -p test_solvers.py -v

No reference uses the engine: closed-form matrix exponentials and exponentials,
a scalar root found by bisection (SciPy brentq), and SciPy Radau at tight
tolerances on a separately written Van der Pol right-hand side. Native GNU
Octave must reproduce the Python engine (the same algorithm; rounding only), and
a missing Octave fails rather than skips. Negative controls: explicit RK4 at the
same step fails on both stiff models; a singular loop and a loop with no scalar
signal are refused by Python and Octave; C export refuses both features without
writing files; an invalid solver name is rejected by document validation.
"""
import copy
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq
from c_export import export_c_model
from mvp_model import detached_graph, read_document, save_document, validate_document
from octalink_engine_support import AlgebraicLoopError
from octalink_gui import BLOCK_SPECS, SimulationEngine
from octave_backend import discover_octave
from simulation_service import simulate_document
from test_c_export import Document

PARITY = 1e-8   # Python vs native Octave: identical algorithm, rounding only


def rows(doc, backend="python", executable=None):
    """time column followed by every sink channel, sinks in ascending ID order."""
    results = simulate_document(doc, BLOCK_SPECS, backend=backend, executable=executable)
    records = [results[i] for i in sorted(results)]
    return np.column_stack([np.asarray(records[0][0])] + [np.asarray(r[1], dtype=float) for r in records])


def relative_error(actual, expected):
    actual, expected = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
        raise AssertionError(f"shape/finite mismatch {actual.shape} {expected.shape}")
    scale = np.maximum(1.0, np.max(np.abs(expected), axis=0))
    return float(np.max(np.abs(actual - expected) / scale))


def stiff_linear(dt=.01, solver="sdirk4"):
    # y = C x with x1' = -1e6 x1 + 1e6 u (pole -1e6) and x2' = -x2 + u; unit step.
    doc = Document()
    step = doc.add("Step", step_time=0, initial_val=0, final_val=1)
    plant = doc.add("State-Space", "Stiff plant", A="[-1e6 0; 0 -1]", B="[1e6; 1]", C="[1 1]", D="0", x0="[0 0]")
    scope = doc.add("Scope")
    doc.connect(step, plant)
    doc.connect(plant, scope)
    doc.data.update(stop_time="2", dt=str(dt), solver=solver)
    return doc.data


def stiff_linear_exact(t):
    return (1 - np.exp(-1e6 * t)) + (1 - np.exp(-t))


MU = 1000.0


def van_der_pol(dt=1e-3, solver="sdirk4"):
    # x1' = x2, x2' = mu((1 - x1^2) x2 - x1): stiff relaxation oscillator (mu = 1000).
    # On the slow manifold x1 falls from 2 and reaches the fold x1 = 1 (a fast
    # jump no fixed step resolves) at t = 1.5 - ln 2 = 0.807; stop before it,
    # where the fast eigenvalue mu(1 - x1^2) runs from -3000 to about -1000.
    doc = Document()
    x1 = doc.add("Integrator", "x1", initial_condition=2)
    x2 = doc.add("Integrator", "x2", initial_condition=0)
    mux = doc.add("Mux", "x1, x2", inputs=2)
    rhs = doc.add("Octave Function", "x2'", expression=f"{MU:g}*((1-u_vec[0]^2)*u_vec[1]-u_vec[0])")
    scope = doc.add("Scope")
    doc.connect(x2, x1)
    doc.connect(x1, mux, 0)
    doc.connect(x2, mux, 1)
    doc.connect(mux, rhs)
    doc.connect(rhs, x2)
    doc.connect(x1, scope)
    doc.data.update(stop_time="0.7", dt=str(dt), solver=solver)
    return doc.data


def van_der_pol_reference(times):
    rhs = lambda _, s: [s[1], MU * ((1 - s[0] ** 2) * s[1] - s[0])]
    jac = lambda _, s: [[0, 1], [MU * (-2 * s[0] * s[1] - 1), MU * (1 - s[0] ** 2)]]
    solution = solve_ivp(rhs, (0, times[-1]), [2, 0], method="Radau", jac=jac, rtol=1e-12, atol=1e-12,
                         dense_output=True)
    return solution.sol(times)[0]


K_LOOP = 3.0


def loop_with_dynamics():
    # y = 1 - x - K y (Sum fed by its own Gain: an algebraic loop), x' = y.
    # Closed form: y = (1 - x)/(1 + K), so x = 1 - exp(-t/(1+K)).
    doc = Document()
    step = doc.add("Step", step_time=0, initial_val=0, final_val=1)
    total = doc.add("Sum", "1 - x - K y", signs="+--")
    gain = doc.add("Gain", "K", gain=K_LOOP)
    integrator = doc.add("Integrator", "x")
    mux = doc.add("Mux", "y, x", inputs=2)
    scope = doc.add("Scope")
    doc.connect(step, total, 0)
    doc.connect(integrator, total, 1)
    doc.connect(gain, total, 2)
    doc.connect(total, gain)
    doc.connect(total, integrator)
    doc.connect(total, mux, 0)
    doc.connect(integrator, mux, 1)
    doc.connect(mux, scope)
    doc.data.update(stop_time="2", dt="0.01")
    return doc.data


def self_loop_cosine():
    # y = cos(y): one Trig block driving its own input (a self-loop).
    doc = Document()
    trig = doc.add("Trig", "cos", operator="cos")
    scope = doc.add("Scope")
    doc.connect(trig, trig)
    doc.connect(trig, scope)
    doc.data.update(stop_time="1", dt="0.5")
    return doc.data


def singular_loop():
    # y = 1 + y has no solution: the loop Jacobian dF/dy - 1 is exactly zero.
    doc = Document()
    constant = doc.add("Constant", value=1)
    total = doc.add("Sum", "1 + y", signs="++")
    gain = doc.add("Gain", "unity", gain=1)
    scope = doc.add("Scope")
    doc.connect(constant, total, 0)
    doc.connect(gain, total, 1)
    doc.connect(total, gain)
    doc.connect(total, scope)
    return doc.data


def vector_only_loop():
    doc = Document()
    constant = doc.add("Constant", value=1)
    mux = doc.add("Mux", inputs=2)
    demux = doc.add("Demux", outputs=2)
    scope = doc.add("Scope")
    doc.connect(constant, mux, 0)
    doc.connect(demux, mux, 1, source_port=1)
    doc.connect(mux, demux)
    doc.connect(demux, scope)
    return doc.data


class SolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.octave = discover_octave()
        if not cls.octave:
            raise RuntimeError("Actual GNU Octave is required; solver parity may not skip it")

    def assert_octave_parity(self, doc, python_rows):
        native = rows(doc, "octave", self.octave)
        self.assertEqual(native.shape, python_rows.shape)
        np.testing.assert_array_equal(native[:, 0], python_rows[:, 0])
        parity = relative_error(native[:, 1:], python_rows[:, 1:])
        self.assertLess(parity, PARITY)
        return parity

    def test_sdirk4_stiff_linear_plant_against_matrix_exponential(self):
        doc = stiff_linear()
        result = rows(doc)
        t = result[:, 0]
        # The pole at -1e6 settles within 1e-5 s; L-stability damps it in one step.
        settled = t >= .05
        error = relative_error(result[settled, 1], stiff_linear_exact(t[settled]))
        self.assertLess(error, 1e-9)
        fine = rows(stiff_linear(dt=.005))
        index = np.searchsorted(fine[:, 0], t[settled] - 1e-12)
        fine_error = relative_error(fine[index, 1], stiff_linear_exact(t[settled]))
        self.assertLess(fine_error, error / 8)            # fourth order on the slow mode
        with self.assertRaisesRegex(ValueError, "[Nn]on-finite"), np.errstate(over="ignore", invalid="ignore"):
            rows(stiff_linear(solver="rk4"))               # h*lambda = -1e4: RK4 diverges
        parity = self.assert_octave_parity(doc, result)
        print(f"MEASUREMENT: stiff linear SDIRK4 dt=0.01 error {error:.2e}, dt=0.005 {fine_error:.2e}; "
              f"Octave/Python {parity:.2e}; RK4 at dt=0.01 diverges (negative control)")

    def test_sdirk4_stiff_van_der_pol_against_radau(self):
        doc = van_der_pol()
        result = rows(doc)
        error = relative_error(result[:, 1], van_der_pol_reference(result[:, 0]))
        self.assertLess(error, 5e-6)
        # Measured 1.8e-6 -> 1.8e-7 -> 1.1e-8 for dt = 1e-3, 5e-4, 2.5e-4: order ~4,
        # with the mild order reduction SDIRK methods show on stiff nonlinear problems.
        fine = rows(van_der_pol(dt=5e-4))
        index = np.searchsorted(fine[:, 0], result[:, 0] - 1e-12)
        fine_error = relative_error(fine[index, 1], van_der_pol_reference(result[:, 0]))
        self.assertLess(fine_error, error / 6)
        try:
            with np.errstate(over="ignore", invalid="ignore"):
                rk4 = rows(van_der_pol(solver="rk4"))
            rk4_error = relative_error(rk4[:, 1], van_der_pol_reference(rk4[:, 0]))
        except ValueError:
            rk4_error = math.inf
        self.assertGreater(rk4_error, 1e-2)               # negative control: explicit RK4 fails at this step
        parity = self.assert_octave_parity(doc, result)
        print(f"MEASUREMENT: Van der Pol mu=1000 SDIRK4 dt=1e-3 vs Radau {error:.2e}, dt=5e-4 {fine_error:.2e}; "
              f"RK4 {rk4_error:.2e}; "
              f"Octave/Python {parity:.2e}")

    def test_algebraic_loop_with_dynamics_against_closed_form(self):
        doc = loop_with_dynamics()
        engine = SimulationEngine()
        engine.compile_graph(detached_graph(doc, BLOCK_SPECS))
        self.assertEqual(len(engine.algebraic_loops), 1)
        self.assertEqual(len(engine.algebraic_loops[0].cuts), 1)
        result = rows(doc)
        t = result[:, 0]
        decay = np.exp(-t / (1 + K_LOOP))
        error = relative_error(result[:, 1:], np.column_stack([decay / (1 + K_LOOP), 1 - decay]))
        self.assertLess(error, 1e-9)
        corrupt = copy.deepcopy(doc)
        corrupt["root"]["blocks"][2]["params"]["gain"] = "2.9"
        with self.assertRaises(AssertionError):           # the same reference rejects a wrong loop gain
            wrong = rows(corrupt)
            self.assertLess(relative_error(wrong[:, 1:], np.column_stack([decay / (1 + K_LOOP), 1 - decay])), 1e-6)
        parity = self.assert_octave_parity(doc, result)
        print(f"MEASUREMENT: loop y = 1 - x - 3y vs closed form {error:.2e}; Octave/Python {parity:.2e}")

    def test_nonlinear_self_loop_against_root(self):
        doc = self_loop_cosine()
        result = rows(doc)
        dottie = brentq(lambda y: math.cos(y) - y, 0, 1, xtol=1e-15)
        self.assertLess(np.max(np.abs(result[:, 1] - dottie)), 1e-12)
        parity = self.assert_octave_parity(doc, result)
        print(f"MEASUREMENT: y = cos(y) self-loop {result[0, 1]:.15f} (root {dottie:.15f}); Octave/Python {parity:.2e}")

    def test_singular_and_vector_only_loops_are_refused(self):
        with self.assertRaisesRegex(AlgebraicLoopError, "singular"):
            rows(singular_loop())
        with self.assertRaisesRegex(RuntimeError, "singular"):
            rows(singular_loop(), "octave", self.octave)
        with self.assertRaisesRegex(AlgebraicLoopError, "no scalar signal"):
            SimulationEngine().compile_graph(detached_graph(vector_only_loop(), BLOCK_SPECS))
        print("NEGATIVE CONTROL: singular loop (Python and Octave) and Mux/Demux-only loop refused")

    def test_c_export_refuses_sdirk4_and_algebraic_loops(self):
        with tempfile.TemporaryDirectory(prefix="solver-c-", dir=ROOT) as directory:
            for doc, message in ((stiff_linear(), "RK4 solver only"), (loop_with_dynamics(), "algebraic loops")):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    export_c_model(doc, BLOCK_SPECS, float(doc["dt"]), Path(directory) / "model")
            self.assertEqual(list(Path(directory).iterdir()), [])
            header, source = export_c_model(stiff_linear(solver="rk4"), BLOCK_SPECS, 1e-7, Path(directory) / "model")
            self.assertTrue(header.is_file() and source.is_file())     # the same plant exports under RK4
        print("NEGATIVE CONTROL: C export refuses SDIRK4 and algebraic loops before writing files")

    def test_solver_is_validated_and_saved(self):
        doc = stiff_linear()
        bad = dict(doc, solver="ode45")
        with self.assertRaisesRegex(ValueError, "Solver must be one of"):
            validate_document(bad, BLOCK_SPECS)
        with self.assertRaisesRegex(ValueError, "Solver must be one of"):
            SimulationEngine().run_simulation(detached_graph(doc, BLOCK_SPECS), 1, .1, solver="ode45")
        with tempfile.TemporaryDirectory(prefix="solver-doc-", dir=ROOT) as directory:
            path = save_document(Path(directory) / "stiff.json", doc, BLOCK_SPECS)
            self.assertEqual(read_document(path, BLOCK_SPECS)["solver"], "sdirk4")
        self.assertEqual(validate_document(loop_with_dynamics(), BLOCK_SPECS).get("solver", "rk4"), "rk4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
