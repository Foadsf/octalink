"""Independent full-trace qualification of three public Simulink adaptations.

Windows/PowerShell: python -m unittest discover -s tests -p test_internet_mwes.py -v
Requires actual GNU Octave and strict C99 gcc; missing tools fail acceptance.
No network, Python fallback, or precomputed simulator output is used.
"""
import copy
import json
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
import test_c_export as c_helpers
from linear_analysis import analyze_model
from mvp_model import detached_graph, read_document, validate_document
from octalink_gui import BLOCK_SPECS, SimulationEngine
from octave_backend import discover_octave, export_octave_script
from simulation_service import simulate_document

NAMES = ("dc_motor", "cruise_pi", "van_der_pol")
# Absolute units include the cruise force channel (initial force 8000 N).
# Fourth-order refinement below independently checks the discretization error.
TOLERANCES = {"dc_motor": 3e-9, "cruise_pi": 2e-7, "van_der_pol": 3e-7}


def load_model(name):
    return read_document(ROOT / "examples" / ("mwe_" + name + ".json"), BLOCK_SPECS)


def assert_trace(actual, expected, tolerance):
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
        raise AssertionError(f"Trace shape/finite mismatch: {actual.shape}, {expected.shape}")
    np.testing.assert_allclose(actual, expected, atol=tolerance, rtol=0)
    return float(np.max(np.abs(actual - expected)))


def linear_solution(A, forcing, times):
    """Independent closed-form affine solution using spectral decomposition.

    This deliberately does not use the engine or linear_analysis exponential.
    Both references have distinct real eigenvalues and zero initial states.
    """
    A, forcing = np.asarray(A, dtype=float), np.asarray(forcing, dtype=float)
    poles, vectors = np.linalg.eig(A)
    equilibrium = -np.linalg.solve(A, forcing)
    transients = (np.exp(np.outer(times, poles)) *
                  np.linalg.solve(vectors, -equilibrium)) @ vectors.T
    return np.real_if_close(equilibrium + transients).astype(float)


def reference_trace(name, times):
    """Independent physics in scope/C output order; nonlinear uses ode45."""
    times = np.asarray(times, dtype=float)
    if name == "dc_motor":
        # State order [angular speed, armature current], CTMS SI parameters.
        return linear_solution([[-10, 1], [-.02, -2]], [0, 2], times)
    if name == "cruise_pi":
        # State order [speed, integral of error], not implementation states.
        state = linear_solution([[-.85, .04], [-1, 0]], [8, 10], times)
        speed, integrated_error = state.T
        effort = 800 * (10 - speed) + 40 * integrated_error
        return np.column_stack([np.full(len(times), 10.), speed, effort])
    if name != "van_der_pol":
        raise ValueError(name)
    executable = discover_octave()
    if not executable:
        raise RuntimeError("GNU Octave required for independent adaptive ode45 reference")
    with tempfile.TemporaryDirectory(prefix="internet-ode45-", dir=ROOT) as directory:
        directory = Path(directory)
        grid = "[" + " ".join(format(t, ".17g") for t in times) + "]'"
        script = directory / "reference.m"
        reference_dir = str(ROOT / "tests" / "references").replace("'", "''")
        script.write_text(f"addpath('{reference_dir}');\n"
                          f"data=van_der_pol_reference({grid});\n"
                          "dlmwrite('reference.csv',data,'precision','%.17g');\n",
                          encoding="utf-8")
        run_octave(executable, script, directory)
        reference = np.loadtxt(directory / "reference.csv", delimiter=",")
    assert_trace(reference[:, 0], times, 1e-12)
    return reference[:, 1:]


def run_octave(executable, script, directory):
    command = [str(executable), "--no-gui", "--quiet", "--no-init-file",
               "--no-site-file", str(script)]
    completed = subprocess.run(command, cwd=directory,
        env=dict(os.environ, OCTALINK_NO_PLOT="1"), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120)
    if completed.returncode:
        raise AssertionError(f"COMMAND: {command!r}\nEXIT: {completed.returncode}\n"
                             f"STDOUT: {completed.stdout}\nSTDERR: {completed.stderr}")
    return completed


def flatten_results(results):
    records = [results[ident] for ident in sorted(results)]
    times = np.asarray(records[0][0], dtype=float)
    for record in records[1:]:
        assert_trace(record[0], times, 1e-12)
    values = np.concatenate([np.asarray(record[1]) for record in records], axis=1)
    return np.column_stack([times, values])


class InternetMWEAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep the native backend's child-job files in the authorized workspace,
        # including under the Windows app sandbox's redirected TEMP environment.
        cls.scratch = tempfile.TemporaryDirectory(prefix="internet-mwe-jobs-", dir=ROOT)
        cls.previous_tempdir = tempfile.tempdir
        tempfile.tempdir = cls.scratch.name
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.addClassCleanup(setattr, tempfile, "tempdir", cls.previous_tempdir)
        cls.executable = discover_octave()
        if not cls.executable:
            raise RuntimeError("Actual GNU Octave is required; acceptance may not skip it")
        if not c_helpers.CC:
            raise RuntimeError("Installed gcc is required; acceptance may not skip C99")
        cls.measurements = {"tools": {"octave": str(cls.executable), "cc": str(c_helpers.CC)},
                            "models": {}, "controls": {}}
        cls.documents = {name: load_model(name) for name in NAMES}
        cls.python = {name: flatten_results(simulate_document(doc, BLOCK_SPECS, backend="python"))
                      for name, doc in cls.documents.items()}
        cls.references = {name: reference_trace(name, rows[:, 0]) for name, rows in cls.python.items()}

    @classmethod
    def tearDownClass(cls):
        output = ROOT / "artifacts" / "verification" / "internet-mwe-numerics.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(cls.measurements, indent=2) + "\n", encoding="utf-8")

    def test_01_python_full_traces_against_independent_physics(self):
        for name in NAMES:
            with self.subTest(model=name):
                rows, doc = self.python[name], self.documents[name]
                self.assertAlmostEqual(rows[-1, 0], float(doc["stop_time"]), places=12)
                self.assertEqual(len(rows), round(float(doc["stop_time"]) / float(doc["dt"])) + 1)
                error = assert_trace(rows[:, 1:], self.references[name], TOLERANCES[name])
                self.measurements["models"][name] = {"samples": len(rows), "channels": rows.shape[1]-1,
                    "python_reference_max_error": error, "reference_tolerance": TOLERANCES[name],
                    "final_channels": rows[-1, 1:].tolist()}
                print(f"MEASUREMENT: {name} Python/reference {len(rows)} rows, max error={error:.17g}")

    def test_02_native_octave_full_traces(self):
        for name, doc in self.documents.items():
            with self.subTest(model=name):
                actual = flatten_results(simulate_document(doc, BLOCK_SPECS,
                    backend="octave", executable=self.executable))
                assert_trace(actual[:, 0], self.python[name][:, 0], 1e-12)
                error = assert_trace(actual[:, 1:], self.references[name], TOLERANCES[name])
                parity = assert_trace(actual, self.python[name], 2e-9)
                self.measurements["models"].setdefault(name, {}).update(
                    octave_reference_max_error=error, octave_python_max_error=parity)
                print(f"MEASUREMENT: {name} native Octave/reference max error={error:.17g}; Python error={parity:.17g}")

    def test_03_standalone_octave_exports_full_traces(self):
        for name, doc in self.documents.items():
            with self.subTest(model=name), tempfile.TemporaryDirectory(prefix="internet-m-", dir=ROOT) as job:
                job = Path(job)
                script = export_octave_script(doc, BLOCK_SPECS, job / "standalone.m")
                completed = run_octave(self.executable, script, job)
                self.assertIn("OCTALINK_COMPLETE", completed.stdout)
                scopes = sorted(b["id"] for b in doc["root"]["blocks"] if b["type"] == "Scope")
                records = [np.loadtxt(job / f"octalink_sink_{ident}.csv", delimiter=",") for ident in scopes]
                for record in records:
                    assert_trace(record[:, 0], self.python[name][:, 0], 1e-12)
                actual = np.concatenate([r[:, 1:] for r in records], axis=1)
                error = assert_trace(actual, self.references[name], TOLERANCES[name])
                self.measurements["models"].setdefault(name, {})["standalone_m_reference_max_error"] = error
                print(f"MEASUREMENT: {name} standalone .m/reference max error={error:.17g}")

    def test_04_strict_c99_exports_full_traces(self):
        # Composition reuses the actual strict compiler harness without exposing
        # its TestCase class to unittest's discovery or duplicating its tests.
        compiler = c_helpers.CExportTests(methodName="runTest")
        compiler.setUp()
        self.addCleanup(compiler.doCleanups)
        for name, doc in self.documents.items():
            with self.subTest(model=name):
                actual = compiler.run_model(doc, float(doc["stop_time"]), float(doc["dt"]))
                assert_trace(actual[:, 0], self.python[name][:, 0], 1e-12)
                error = assert_trace(actual[:, 1:], self.references[name], TOLERANCES[name])
                parity = assert_trace(actual, self.python[name], 2e-9)
                self.measurements["models"].setdefault(name, {}).update(
                    c99_reference_max_error=error, c99_python_max_error=parity)
                print(f"MEASUREMENT: {name} strict C99/reference max error={error:.17g}; Python error={parity:.17g}")

    def test_05_selected_linear_models_matrices_poles_and_dc(self):
        cases = {
            "dc_motor": dict(source_id=1, sink_id=14, channel=0,
                A=[[-2, -.02], [1, -10]], B=[[2], [0]], C=[[0, 1]], dc=.01/.1001),
            "cruise_pi": dict(source_id=1, sink_id=9, channel=1,
                A=[[0, -40], [.001, -.85]], B=[[40], [.8]], C=[[0, 1]], dc=1),
        }
        for name, case in cases.items():
            with self.subTest(model=name):
                options = {k: case[k] for k in ("source_id", "sink_id", "channel")}
                analysis = analyze_model(self.documents[name], BLOCK_SPECS,
                    operating_input=0, operating_state=[0, 0], **options)
                for key in ("A", "B", "C"):
                    assert_trace(analysis[key], case[key], 1e-8)
                self.assertAlmostEqual(float(analysis["D"]), 0, places=10)
                poles = np.sort_complex(np.linalg.eigvals(case["A"]))
                assert_trace(np.sort_complex(analysis["poles"]), poles, 1e-8)
                self.assertAlmostEqual(analysis["dc_gain"], case["dc"], places=8)
                self.measurements["models"].setdefault(name, {})["linear_analysis"] = {
                    "A": analysis["A"].tolist(), "B": analysis["B"].tolist(),
                    "C": analysis["C"].tolist(), "poles": poles.real.tolist(), "dc_gain": analysis["dc_gain"]}
                print(f"MEASUREMENT: {name} selected linearization poles={poles.tolist()}, dc={analysis['dc_gain']:.17g}")

    def test_06_mu_zero_harmonic_and_rk4_step_refinement(self):
        harmonic = copy.deepcopy(self.documents["van_der_pol"])
        next(b for b in harmonic["root"]["blocks"] if b["name"] == "Mu")["params"]["gain"] = "0"
        actual = flatten_results(simulate_document(harmonic, BLOCK_SPECS, backend="python"))
        exact = np.column_stack([2*np.cos(actual[:, 0]), -2*np.sin(actual[:, 0])])
        harmonic_error = assert_trace(actual[:, 1:], exact, 2e-9)
        fine = copy.deepcopy(self.documents["van_der_pol"])
        fine["dt"] = ".005"
        refined = flatten_results(simulate_document(fine, BLOCK_SPECS, backend="python"))
        coarse = self.python["van_der_pol"]
        indices = np.searchsorted(refined[:, 0], coarse[:, 0])
        assert_trace(refined[indices, 0], coarse[:, 0], 1e-12)
        fine_error = assert_trace(refined[indices, 1:], self.references["van_der_pol"], 3e-8)
        coarse_error = float(np.max(np.abs(coarse[:, 1:]-self.references["van_der_pol"])))
        self.assertLess(fine_error, coarse_error / 8)
        self.measurements["controls"]["harmonic_mu0_max_error"] = harmonic_error
        self.measurements["controls"]["vdp_refined_max_error"] = fine_error
        print(f"MEASUREMENT: Mu=0 harmonic error={harmonic_error:.17g}; nonlinear refinement={coarse_error:.17g}->{fine_error:.17g}")
        for name in ("dc_motor", "cruise_pi"):
            fine = copy.deepcopy(self.documents[name])
            fine["dt"] = str(float(fine["dt"]) / 2)
            actual = flatten_results(simulate_document(fine, BLOCK_SPECS, backend="python"))
            coarse = self.python[name]
            indices = np.searchsorted(actual[:, 0], coarse[:, 0])
            assert_trace(actual[indices, 0], coarse[:, 0], 1e-12)
            fine_error = float(np.max(np.abs(actual[indices, 1:]-self.references[name])))
            coarse_error = float(np.max(np.abs(coarse[:, 1:]-self.references[name])))
            self.assertLess(fine_error, coarse_error / 8)
            self.measurements["controls"][name + "_refined_max_error"] = fine_error
            print(f"MEASUREMENT: {name} RK4 refinement={coarse_error:.17g}->{fine_error:.17g}")

    def test_07_corrupted_source_gain_and_feedback_sign_are_rejected(self):
        for name, target, key, value in (("dc_motor", "Torque Kt", "gain", ".02"),
                ("cruise_pi", "Speed error", "signs", "++"),
                ("van_der_pol", "Mu", "gain", "0")):
            with self.subTest(model=name):
                corrupt = copy.deepcopy(self.documents[name])
                next(b for b in corrupt["root"]["blocks"] if b["name"] == target)["params"][key] = value
                actual = flatten_results(simulate_document(corrupt, BLOCK_SPECS, backend="python"))[:, 1:]
                with self.assertRaises(AssertionError):
                    assert_trace(actual, self.references[name], TOLERANCES[name])
                error = float(np.max(np.abs(actual-self.references[name])))
                self.measurements["controls"][name + "_source_mutation_error"] = error
                print(f"NEGATIVE CONTROL: {name} source {target}.{key}={value} rejected; error={error:.17g}")

    def test_08_missing_input_invalid_port_and_wrong_scope_signal(self):
        doc = copy.deepcopy(self.documents["dc_motor"])
        doc["root"]["wires"] = [w for w in doc["root"]["wires"] if w["to_block"] != 5]
        with self.assertRaisesRegex(ValueError, "unconnected|unresolved"):
            SimulationEngine().compile_graph(detached_graph(doc, BLOCK_SPECS))
        doc = copy.deepcopy(self.documents["dc_motor"])
        doc["root"]["wires"][0]["from_port"] = 1
        with self.assertRaisesRegex(ValueError, "missing port"):
            validate_document(doc, BLOCK_SPECS)
        doc = copy.deepcopy(self.documents["dc_motor"])
        for wire in doc["root"]["wires"]:
            if wire["to_block"] == 13:
                wire["to_port"] = 1 - wire["to_port"]
        wrong = flatten_results(simulate_document(doc, BLOCK_SPECS, backend="python"))[:, 1:]
        with self.assertRaises(AssertionError):
            assert_trace(wrong, self.references["dc_motor"], TOLERANCES["dc_motor"])
        self.measurements["controls"]["missing_input_rejected"] = True
        self.measurements["controls"]["invalid_source_port_rejected"] = True
        self.measurements["controls"]["swapped_motor_channels_rejected"] = True
        print("NEGATIVE CONTROL: missing integrator input, nonexistent source port, swapped motor scope signals rejected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
