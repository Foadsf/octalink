"""Second public Simulink MWE set: five more adaptations, checked independently.

Windows/PowerShell: python -m unittest discover -s tests -p test_public_mwes_2.py -v

Each reference is computed here without the engine: closed-form linear algebra,
SciPy DOP853 on a separately derived Lagrangian, an exactly discretized
sampled-data loop, or a conservation law over the logged outputs. Native GNU
Octave and strict C99 must reproduce the Python engine; missing tools fail.
"""
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import expm
import test_c_export as c_helpers
from test_internet_mwes import assert_trace
from linear_analysis import analyze_model
from mvp_model import read_document
from octalink_engine_support import resolve_variables
from octalink_gui import BLOCK_SPECS
from octave_backend import discover_octave, export_octave_script
from simulation_service import simulate_document

NAMES = ("motor_speed_lag_lead", "inverted_pendulum", "house_heating",
         "aircraft_pitch_lqr", "motor_position_digital", "inverted_pendulum_loop")
# Tolerances relative to each channel's peak magnitude (at least 1) at the
# documented step sizes: RK4, except the motor position plant (implicit SDIRK4
# at dt = 1e-4). test_08 shows the RK4 error is truncation (16x per halving).
# inverted_pendulum_loop is the CTMS four-Fcn form with an algebraic loop.
TOLERANCES = {"motor_speed_lag_lead": 2e-6, "inverted_pendulum": 1e-6,
              "aircraft_pitch_lqr": 1e-8, "motor_position_digital": 2e-6,
              "inverted_pendulum_loop": 1e-6}
PARITY = 1e-8   # Python vs native Octave/.m/C: identical algorithm, rounding only


def run_octave(executable, script, directory):
    """Standalone .m execution; 80k-step models need more than the 120 s used for the first set."""
    command = [str(executable), "--no-gui", "--quiet", "--no-init-file", "--no-site-file", str(script)]
    completed = subprocess.run(command, cwd=directory, env=dict(os.environ, OCTALINK_NO_PLOT="1"),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if completed.returncode:
        raise AssertionError(f"EXIT {completed.returncode}\nSTDERR: {completed.stderr[-4000:]}")
    return completed


def load(name):
    return read_document(ROOT / "examples" / f"mwe_{name}.json", BLOCK_SPECS)


def variables(doc):
    scalars, arrays = resolve_variables(doc["variables"])
    return {**scalars, **{k: np.array(v, dtype=float) for k, v in arrays.items()}}


def flatten(results, doc):
    """Sinks in ascending document ID order, as test_internet_mwes does."""
    records = [results[i] for i in sorted(results)]
    times = np.asarray(records[0][0], dtype=float)
    labels = [label for record in records for label in record[2]]
    values = np.concatenate([np.asarray(record[1], dtype=float) for record in records], axis=1)
    return np.column_stack([times, values]), labels


def affine_solution(A, forcing, x0, times):
    """x' = A x + f with constant f, from x0 at times[0]: an exact matrix exponential."""
    A, forcing, x0 = (np.asarray(v, dtype=float) for v in (A, forcing, x0))
    n = len(A)
    augmented = np.zeros((n + 1, n + 1))
    augmented[:n, :n], augmented[:n, n] = A, forcing
    start = np.append(x0, 1.0)
    return np.array([(expm(augmented * (t - times[0])) @ start)[:n] for t in times])


def reference(name, doc, times):
    v = variables(doc)
    if name == "motor_speed_lag_lead":
        columns = {}
        for label, (n1, n0, p) in {"lag": (44, 44, .01), "lead": (160000, 5.6e6, 1035)}.items():
            # States [compensator, current, speed]; C(s) = n1 + (n0 - n1 p)/(s + p),
            # e = 1 - w, u = c xc + n1 e, L i' = u - R i - K w, J w' = K i - b w.
            c = n0 - n1 * p
            A = [[-p, 0, -1],
                 [c / v["L"], -v["R"] / v["L"], -(v["K"] + n1) / v["L"]],
                 [0, v["K"] / v["J"], -v["b"] / v["J"]]]
            x = affine_solution(A, [1, n1 / v["L"], 0], [0, 0, 0], times)
            columns[label] = (x[:, 2], c * x[:, 0] + n1 * (1 - x[:, 2]))
        return np.column_stack([columns["lag"][0], columns["lead"][0], columns["lag"][1], columns["lead"][1]])
    if name in ("inverted_pendulum", "inverted_pendulum_loop"):
        M, m, b, l, I, g = (v[k] for k in ("M", "m", "b", "l", "I", "g"))

        def lagrangian(force):
            # Lagrange's equations of the cart-pendulum, solved as a 2x2 mass-matrix system.
            def rhs(_, s):
                x, xd, th, thd = s
                mass = np.array([[M + m, m * l * math.cos(th)], [m * l * math.cos(th), I + m * l * l]])
                generalized = np.array([force - b * xd + m * l * thd ** 2 * math.sin(th), -m * g * l * math.sin(th)])
                xdd, thdd = np.linalg.solve(mass, generalized)
                return [xd, xdd, thd, thdd]
            return rhs
        width = 10 * 0.01 / 100
        early = times[times <= width]
        first = solve_ivp(lagrangian(1000.0), (0, width), [0, 0, math.pi, 0], method="DOP853",
                          rtol=1e-12, atol=1e-13, dense_output=True)
        second = solve_ivp(lagrangian(0.0), (width, times[-1]), first.y[:, -1], method="DOP853",
                           rtol=1e-12, atol=1e-13, dense_output=True)
        states = np.vstack([first.sol(early).T, second.sol(times[times > width]).T])
        return np.column_stack([states[:, 2], states[:, 0]])          # Angle, then Position
    if name == "aircraft_pitch_lqr":
        A, B, K, nbar = v["A"], v["B"].reshape(-1), v["K"].reshape(-1), v["Nbar"]
        closed = A - np.outer(B, K)
        rows = np.empty((len(times), 3))
        before, after = times < 3, times >= 3
        rows[before] = affine_solution(closed, B * nbar * .2, [0, 0, 0], times[before])
        x3 = affine_solution(closed, B * nbar * .2, [0, 0, 0], [0, 3])[-1]
        rows[after] = affine_solution(closed, B * (nbar * .2 + .2), x3, times[after])
        return np.column_stack([rows[:, 2], nbar * .2 - rows @ K])
    if name == "motor_position_digital":
        J, b, K, R, L, Ts = (v[k] for k in ("J", "b", "K", "R", "L", "Ts"))
        A = np.array([[-R / L, -K / L, 0], [K / J, -b / J, 0], [0, 1, 0]])
        B = np.array([1 / L, 0, 0])
        num = 800 * np.poly([.95, .8, .8])
        den = np.poly([-.98, .6, 1])
        steps = int(round(float(doc["stop_time"]) / Ts))
        # Difference equation of the zero-pole controller; the plant is integrated
        # exactly between sample instants under the held input.
        x, e_hist, u_hist, samples = np.zeros(3), [0.0] * 4, [0.0] * 4, []
        for k in range(steps + 1):
            e = 1.0 - x[2]
            e_hist = [e] + e_hist[:3]
            u = float(num @ e_hist - den[1:] @ u_hist[:3])
            u_hist = [u] + u_hist[:3]
            disturbance = 1.0 if k * Ts >= .03 - 1e-12 else 0.0
            samples.append((k * Ts, x[2]))
            x = affine_solution(A, B * (u + disturbance), x, [0, Ts])[-1]
        sample_t = np.array([s[0] for s in samples])
        return sample_t, np.array([s[1] for s in samples])
    raise ValueError(name)


class PublicMWEs2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="public-mwe2-", dir=ROOT)
        cls.previous_tempdir = tempfile.tempdir
        tempfile.tempdir = cls.scratch.name
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.addClassCleanup(setattr, tempfile, "tempdir", cls.previous_tempdir)
        cls.executable = discover_octave()
        if not cls.executable:
            raise RuntimeError("Actual GNU Octave is required; acceptance may not skip it")
        if not c_helpers.CC:
            raise RuntimeError("Installed gcc is required; acceptance may not skip C99")
        cls.documents = {name: load(name) for name in NAMES}
        cls.python, cls.labels = {}, {}
        for name, doc in cls.documents.items():
            cls.python[name], cls.labels[name] = flatten(simulate_document(doc, BLOCK_SPECS, backend="python"), doc)
        cls.measurements = {"tools": {"octave": str(cls.executable), "cc": str(c_helpers.CC)}, "models": {}}

    @classmethod
    def tearDownClass(cls):
        output = ROOT / "artifacts" / "verification" / "public-mwe2-numerics.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(cls.measurements, indent=2) + "\n", encoding="utf-8")

    def record(self, name, **values):
        self.measurements["models"].setdefault(name, {}).update(values)

    def compare(self, name, rows):
        """Max error relative to channel scale; raises AssertionError beyond tolerance."""
        doc = self.documents[name]
        if name == "motor_position_digital":
            t_ref, y_ref = reference(name, doc, None)
            index = np.searchsorted(rows[:, 0], t_ref - 1e-12)
            assert_trace(rows[index, 0], t_ref, 1e-12)
            actual, expected = rows[index, 2:3], y_ref.reshape(-1, 1)
        else:
            actual, expected = rows[:, 1:], reference(name, doc, rows[:, 0])
        if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
            raise AssertionError(f"shape/finite mismatch {actual.shape} {expected.shape}")
        relative = np.abs(actual - expected) / np.maximum(1.0, np.max(np.abs(expected), axis=0))
        worst = float(np.max(relative))
        if worst > TOLERANCES[name]:
            raise AssertionError(f"{name}: relative error {worst:.3e} exceeds {TOLERANCES[name]:.1e}")
        return worst

    def test_01_python_traces_against_independent_references(self):
        for name in TOLERANCES:
            with self.subTest(model=name):
                rows = self.python[name]
                self.assertAlmostEqual(rows[-1, 0], float(self.documents[name]["stop_time"]), places=12)
                error = self.compare(name, rows)
                self.record(name, samples=len(rows), python_reference_max_error=error, tolerance=TOLERANCES[name])
                print(f"MEASUREMENT: {name} Python/reference {len(rows)} rows, max error={error:.3e}")

    def test_02_scope_labels_name_signals_as_drawn(self):
        expected = {"motor_speed_lag_lead": ["DC Motor (lag)", "DC Motor (lead)", "Lag compensator", "Lead compensator"],
                    "inverted_pendulum": ["Pendulum/Angle", "Pendulum/Position"],
                    "inverted_pendulum_loop": ["Pendulum/Angle", "Pendulum/Position"],
                    "house_heating": ["Cost Calculator", "C2F (indoor)", "Outdoor (F)"],
                    "aircraft_pitch_lqr": ["States[3]", "Nbar r - K x"],
                    "motor_position_digital": ["Reference", "Motor_pos", "ZOH (sensor)"]}
        for name, labels in expected.items():
            with self.subTest(model=name):
                self.assertEqual(self.labels[name], labels)

    def test_03_published_behaviour(self):
        lag_lead = self.python["motor_speed_lag_lead"]
        # CTMS: the lag design meets overshoot < 5 %; the lead response has a
        # "slightly larger, but similar" overshoot; both errors approach zero.
        self.assertLess(lag_lead[:, 1].max(), 1.05)
        self.assertGreater(lag_lead[:, 2].max(), lag_lead[:, 1].max())
        self.assertLess(lag_lead[:, 2].max(), 1.10)
        for column in (1, 2):
            self.assertLess(abs(1 - lag_lead[-1, column]), .01)
        # The lead loop is faster and needs more effort.
        first = lambda s: lag_lead[np.argmax(s >= .9), 0]
        self.assertLess(first(lag_lead[:, 2]), first(lag_lead[:, 1]))
        self.assertGreater(np.abs(lag_lead[:, 4]).max(), 100 * np.abs(lag_lead[:, 3]).max())
        pend = self.python["inverted_pendulum"]
        # "The pendulum repeatedly swings through full revolutions ... the cart's position grows."
        self.assertGreater(abs(pend[-1, 1] - math.pi), 4 * math.pi)
        self.assertGreater(abs(pend[-1, 2]), 1)
        pitch = self.python["aircraft_pitch_lqr"]
        before = pitch[pitch[:, 0] < 3]
        self.assertLess(abs(before[-1, 1] - .2), .2 * .02)          # precompensated: no steady-state error
        self.assertLess(before[:, 1].max(), .2 * 1.10)             # overshoot < 10 %
        rise = before[np.argmax(before[:, 1] >= .18), 0] - before[np.argmax(before[:, 1] >= .02), 0]
        self.assertLess(rise, 2)
        self.assertGreater(abs(pitch[-1, 1] - .2), .01)            # disturbance is not rejected
        pos = self.python["motor_position_digital"]
        t, continuous, y = pos[:, 0], pos[:, 2], pos[:, 3]
        # CTMS judges the design on the sampled response (controller's view).
        self.assertLess(y[t < .03].max(), 1.16)                    # overshoot < 16 % (CTMS: about 10 %)
        settled = t[(t < .03) & (np.abs(y - 1) > .02)]
        self.assertLess(settled.max(), .04)                        # 2 % settling before the disturbance
        self.assertLess(abs(y[-1] - 1), .02)                       # integral action rejects the disturbance
        # The controller pole at -0.98 cancels the plant's sampled zero at
        # -0.983: the sampled output is smooth but the shaft rings between
        # samples. Measure that ripple instead of hiding it.
        ripple = float(np.max(np.abs(continuous - y)[t < .03]))
        self.assertGreater(ripple, .1)
        house = self.python["house_heating"]
        cost, indoor = house[:, 1], house[:, 2]
        self.assertAlmostEqual(cost[-1], 30, delta=3)              # "about $30" for two days
        self.assertGreater(indoor.min(), 65 - .1)
        self.assertLess(indoor.max(), 75 + .1)
        self.record("published", lag_lead_rise=[first(lag_lead[:, 1]), first(lag_lead[:, 2])],
                    pitch_rise=rise, pitch_peak=before[:, 1].max(), position_peak_sampled=y[t < .03].max(),
                    position_settling=float(settled.max()), position_intersample_ripple=ripple,
                    house_cost=cost[-1], indoor_band=[indoor.min(), indoor.max()])
        print(f"MEASUREMENT: house two-day cost=${cost[-1]:.2f}; indoor {indoor.min():.2f}..{indoor.max():.2f} F; "
              f"sampled position peak {y[t < .03].max():.4f}, settling {settled.max():.4f} s, "
              f"inter-sample ripple {ripple:.3f} rad")

    def test_04_house_energy_balance_from_logged_outputs(self):
        doc, rows = self.documents["house_heating"], self.python["house_heating"]
        v = variables(doc)
        t, cost, indoor_f, outdoor_f = rows.T
        to_c = lambda f: (f - 32) * 5 / 9
        heat = cost / v["cost"]
        losses = np.trapezoid((to_c(indoor_f) - to_c(outdoor_f)) / v["Req"], t)
        stored = v["M"] * v["c"] * (to_c(indoor_f[-1]) - to_c(indoor_f[0]))
        imbalance = abs(heat[-1] - losses - stored) / heat[-1]
        self.assertLess(imbalance, 1e-3)
        self.record("house_heating", energy_imbalance=imbalance)
        print(f"MEASUREMENT: house heat {heat[-1]/3.6e6:.2f} kWh, energy imbalance {imbalance:.2e}")

    def test_05_native_octave_and_standalone_m_match_python(self):
        for name, doc in self.documents.items():
            with self.subTest(model=name):
                native, _ = flatten(simulate_document(doc, BLOCK_SPECS, backend="octave", executable=self.executable), doc)
                parity = assert_trace(native, self.python[name], PARITY)
                with tempfile.TemporaryDirectory(prefix="mwe2-m-", dir=ROOT) as job:
                    job = Path(job)
                    script = export_octave_script(doc, BLOCK_SPECS, job / "standalone.m")
                    self.assertIn("OCTALINK_COMPLETE", run_octave(self.executable, script, job).stdout)
                    sinks = sorted(b["id"] for b in doc["root"]["blocks"] if b["type"] == "Scope")
                    records = [np.loadtxt(job / f"octalink_sink_{i}.csv", delimiter=",", ndmin=2) for i in sinks]
                    standalone = np.column_stack([records[0][:, 0]] + [r[:, 1:] for r in records])
                    m_parity = assert_trace(standalone, self.python[name], PARITY)
                self.record(name, octave_python_max_error=parity, standalone_m_python_max_error=m_parity)
                print(f"MEASUREMENT: {name} native Octave/Python {parity:.2e}; standalone .m/Python {m_parity:.2e}")

    def test_06_strict_c99_matches_python(self):
        compiler = c_helpers.CExportTests(methodName="runTest")
        compiler.setUp()
        self.addCleanup(compiler.doCleanups)
        for name, doc in self.documents.items():
            with self.subTest(model=name):
                if doc.get("solver", "rk4") != "rk4" or name == "inverted_pendulum_loop":
                    # C export is RK4 without loop solving: refused, never approximated.
                    with self.assertRaisesRegex(ValueError, "RK4 solver only|algebraic loops"):
                        compiler.run_model(doc, float(doc["stop_time"]), float(doc["dt"]))
                    reason = "SDIRK4 solver" if doc.get("solver", "rk4") != "rk4" else "algebraic loop"
                    print(f"NEGATIVE CONTROL: {name} refused by C export ({reason})")
                    continue
                actual = compiler.run_model(doc, float(doc["stop_time"]), float(doc["dt"]))
                parity = assert_trace(actual, self.python[name], PARITY)
                self.record(name, c99_python_max_error=parity)
                print(f"MEASUREMENT: {name} strict C99/Python {parity:.2e}")
        # The motor plant still exports under RK4 at the explicit stability step,
        # checked against the exact sampled-data reference itself.
        explicit = copy.deepcopy(self.documents["motor_position_digital"])
        explicit.update(solver="rk4", dt="1e-6")
        error = self.compare("motor_position_digital", compiler.run_model(explicit, float(explicit["stop_time"]), 1e-6))
        self.record("motor_position_digital", c99_rk4_1us_reference_max_error=error)
        print(f"MEASUREMENT: motor_position_digital strict C99 RK4 dt=1e-6 vs exact sampled reference {error:.2e}")

    def test_07_linear_analysis_matches_ctms_pendulum_and_pitch(self):
        pend = analyze_model(self.documents["inverted_pendulum"], BLOCK_SPECS, channel=0, operating_input=0)
        v = variables(self.documents["inverted_pendulum"])
        M, m, b, l, I, g = (v[k] for k in ("M", "m", "b", "l", "I", "g"))
        p = I * (M + m) + M * m * l * l
        ctms = np.array([[0, 1, 0, 0], [0, -(I + m * l * l) * b / p, m * m * g * l * l / p, 0],
                         [0, 0, 0, 1], [0, -m * l * b / p, m * g * l * (M + m) / p, 0]])
        poles = np.sort_complex(np.linalg.eigvals(ctms))
        assert_trace(np.sort_complex(pend["poles"]), poles, 1e-6)
        # CTMS System Analysis lists 5.5651, -5.6041, -0.1428 for the pendulum angle.
        assert_trace(np.sort(pend["poles"].real), [-5.6041, -.1428, 0, 5.5651], 1e-4)
        self.assertEqual(pend["stability"], "unstable")
        pitch = analyze_model(self.documents["aircraft_pitch_lqr"], BLOCK_SPECS, source_id=next(
            b["id"] for b in self.documents["aircraft_pitch_lqr"]["root"]["blocks"] if b["name"] == "Reference (0.2 rad)"),
            channel=0, operating_input=0)
        vp = variables(self.documents["aircraft_pitch_lqr"])
        closed = vp["A"] - np.outer(vp["B"].reshape(-1), vp["K"].reshape(-1))
        assert_trace(np.sort_complex(pitch["poles"]), np.sort_complex(np.linalg.eigvals(closed)), 1e-6)
        self.assertAlmostEqual(pitch["dc_gain"], 1.0, delta=1e-3)   # Nbar makes theta/r = 1 (4-digit gains)
        self.record("analysis", pendulum_poles=np.sort(pend["poles"].real).tolist(), pitch_dc=pitch["dc_gain"])
        print(f"MEASUREMENT: pendulum poles {np.round(np.sort(pend['poles'].real), 4).tolist()}; pitch DC {pitch['dc_gain']:.6f}")

    def test_08_rk4_refinement_and_negative_controls(self):
        for name in ("motor_speed_lag_lead", "aircraft_pitch_lqr", "inverted_pendulum"):
            fine = copy.deepcopy(self.documents[name])
            fine["dt"] = str(float(fine["dt"]) / 2)
            rows, _ = flatten(simulate_document(fine, BLOCK_SPECS, backend="python"), fine)
            index = np.searchsorted(rows[:, 0], self.python[name][:, 0] - 1e-12)
            fine_error = self.compare(name, rows[index])
            coarse = self.compare(name, self.python[name])
            self.assertLess(fine_error, coarse / 8)     # fourth-order truncation, not a model defect
            self.record(name, rk4_refinement=[coarse, fine_error])
            print(f"MEASUREMENT: {name} RK4 refinement {coarse:.2e} -> {fine_error:.2e}")
        for name, target, key, value in (("motor_speed_lag_lead", "Lead compensator", "numerator", "[160000 5.0e6]"),
                                         ("aircraft_pitch_lqr", "Nbar", "gain", "1"),
                                         ("inverted_pendulum", "Impulse (1 N s)", "amplitude", "1100"),
                                         # Gravity dropped from P: the loop stays regular (its
                                         # Jacobian does not involve g) but the physics is wrong.
                                         ("inverted_pendulum_loop", "P", "expression",
                                          "m*(l*u_vec[1]^2*cos(u_vec[0])+l*u_vec[2]*sin(u_vec[0]))"),
                                         ("motor_position_digital", "Controller", "gain", "700")):
            with self.subTest(control=name):
                corrupt = copy.deepcopy(self.documents[name])

                def amend(scene):
                    for block in scene["blocks"]:
                        if block["name"] == target:
                            block["params"][key] = value
                        if "sub_scene" in block:
                            amend(block["sub_scene"])
                amend(corrupt["root"])
                rows, _ = flatten(simulate_document(corrupt, BLOCK_SPECS, backend="python"), corrupt)
                with self.assertRaises(AssertionError):
                    self.compare(name, rows)
                print(f"NEGATIVE CONTROL: {name} {target}.{key}={value} rejected by the same reference")
        corrupt = copy.deepcopy(self.documents["house_heating"])
        corrupt["variables"]["Mdot"] = "0.5"
        rows, _ = flatten(simulate_document(corrupt, BLOCK_SPECS, backend="python"), corrupt)
        self.assertNotAlmostEqual(rows[-1, 1], self.python["house_heating"][-1, 1], delta=.5)
        print(f"NEGATIVE CONTROL: house Mdot=0.5 changes the cost to ${rows[-1, 1]:.2f}")
        explicit = copy.deepcopy(self.documents["motor_position_digital"])
        explicit["solver"] = "rk4"
        with self.assertRaisesRegex(ValueError, "[Nn]on-finite"), np.errstate(over="ignore", invalid="ignore"):
            simulate_document(explicit, BLOCK_SPECS, backend="python")
        print("NEGATIVE CONTROL: motor position with RK4 at dt=1e-4 diverges (armature pole -1.45e6 rad/s)")

    def test_09_algebraic_loop_form_matches_explicit_form(self):
        # The CTMS four-Fcn diagram (N and P in an algebraic loop) and the
        # explicitly solved diagram are the same equations: equal to Newton tolerance.
        loop, explicit = self.python["inverted_pendulum_loop"], self.python["inverted_pendulum"]
        self.assertEqual(loop.shape, explicit.shape)
        error = float(np.max(np.abs(loop[:, 1:] - explicit[:, 1:]) / np.maximum(1, np.abs(explicit[:, 1:]).max(axis=0))))
        self.assertLess(error, 1e-10)
        self.record("inverted_pendulum_loop", loop_vs_explicit_max_error=error)
        print(f"MEASUREMENT: pendulum algebraic-loop form vs explicit form {error:.2e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
