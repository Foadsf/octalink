"""Backend controls, real Octave conformance, and installed-example provenance.

Run: python -m unittest discover -s tests -p test_octave_backend.py -v
Live tests skip only if discovery finds no Octave. OCTALINK_SKIP_LIVE_OCTAVE=1
explicitly permits offline unit tests in restricted environments.
Mutation: python tests/test_octave_backend.py --mutation-control must fail the
analytical integration test (state advancement is deliberately disabled).

Adapted installed Octave 11.3.0 example: mingw64/share/octave/11.3.0/m/ode/ode45.m,
lines 326-333 (GNU GPLv3+, Octave distribution). Its exact derivative/reference:
%!function ydot = fpol (t, y, varargin)  # The Van der Pol ODE
%!  ydot = [y(2); (1 - y(1)^2) * y(2) - y(1)];
%!endfunction
%!function ref = fref ()       # The computed reference solution
%!  ref = [0.32331666704577, -1.83297456798624];
%!endfunction
The independent ode45 run below uses the shipped nonlinear ODE, tighter
tolerances, and no generated network or backend RK4 implementation.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import octave_backend as backend
from octalink_gui import BLOCK_SPECS, SimulationEngine
from octalink_engine_support import SimulationCancelled
from mvp_model import detached_graph


def model(*kinds, stop=1, dt=.01):
    blocks = []
    for i, entry in enumerate(kinds, 1):
        kind, params = entry if isinstance(entry, tuple) else (entry, {})
        blocks.append(dict(id=i, type=kind, name=f"{kind}_{i}", x=i * 100, y=0, params=params))
    wires = [dict(from_block=i, from_port=0, to_block=i+1, to_port=0)
             for i in range(1, len(blocks))]
    return dict(version="4.0", stop_time=stop, dt=dt, root=dict(blocks=blocks, wires=wires))


def wire(doc, src, dst, inp=0, out=0):
    doc["root"]["wires"].append(dict(from_block=src, from_port=out, to_block=dst, to_port=inp))


OCTAVE = backend.discover_octave()
LIVE = OCTAVE is not None and os.environ.get("OCTALINK_SKIP_LIVE_OCTAVE") != "1"


class BackendOfflineTests(unittest.TestCase):
    def test_explicit_missing_executable_never_falls_back(self):
        self.assertIsNone(backend.discover_octave(ROOT / "absent-octave-executable"))
        with self.assertRaises(FileNotFoundError):
            backend.run_octave_simulation({}, {}, executable=ROOT / "absent-octave-executable")

    def test_explicit_override(self):
        with patch.dict(os.environ, OCTALINK_OCTAVE=sys.executable):
            self.assertEqual(Path(backend.discover_octave()).resolve(), Path(sys.executable).resolve())

    def test_injection_negative_controls(self):
        for expression in ("system('echo BAD')", "u; quit", "u.__class__", "__import__('os')", "u_vec[-1]", "[u, t]"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                backend.translate_expression(expression)
        translated = backend.translate_expression("max(u_vec[0], u_vec[1]) + sin(t) + u^2")
        self.assertIn("u_vec(1)", translated)
        # A literal small integer power is bounded by construction and inlined;
        # any other exponent keeps the bounded ol_power guard.
        self.assertIn("(u_vec(1)^2)", translated)
        self.assertNotIn("ol_power", translated)
        self.assertIn("ol_power", backend.translate_expression("u^t"))
        self.assertIn("ol_power", backend.translate_expression("u^1025"))

    def test_bounds_and_algebraic_loop(self):
        too_many = model("Constant", "Scope", stop=1e9, dt=.01)
        with self.assertRaises(ValueError):
            backend._generate(too_many, BLOCK_SPECS)
        # A direct-feedthrough cycle is generated as a Newton-solved loop
        # (live solving and refusal are tested in tests/test_solvers.py).
        loop = model("Gain", "Gain", "Scope")
        wire(loop, 2, 1)
        source, *_ = backend._generate(loop, BLOCK_SPECS)
        self.assertIn("function z = ol_newton(", source)
        self.assertIn("function [r,z,", source)
        uncuttable = model("Constant", "Mux", "Demux", "Scope")
        uncuttable["root"]["blocks"][1]["params"] = {"inputs": "2"}
        uncuttable["root"]["blocks"][2]["params"] = {"outputs": "2"}
        wire(uncuttable, 3, 2, inp=1, out=1)
        with self.assertRaisesRegex(RuntimeError, "no scalar signal"):
            backend._generate(uncuttable, BLOCK_SPECS)

    def test_schedule_has_exact_stop_and_events(self):
        doc = model(("Step", {"step_time": .13}), ("Zero-Order Hold", {"sample_time": .15}),
                    "Integrator", "Scope", stop=.37, dt=.1)
        source, times, _, _ = backend._generate(doc, BLOCK_SPECS)
        self.assertEqual(times[-1], .37)
        self.assertIn(.13, times)
        self.assertIn(.15, times)
        self.assertIn(.3, times)
        self.assertIn("ol_evaluate", source)
        self.assertNotIn("ode45", source)

    def test_export_is_standalone_and_labels_cannot_inject(self):
        doc = model("Constant", "Scope")
        doc["root"]["blocks"][0]["name"] = "a'; system('bad'); %\nΩ"
        with tempfile.TemporaryDirectory() as tmp:
            exported = backend.export_octave_script(doc, BLOCK_SPECS, Path(tmp) / "run.m")
            source = exported.read_text(encoding="utf-8")
        self.assertIn("plot(r.time,r.values)", source)
        self.assertNotIn("system('bad')", source)
        self.assertNotIn("import ", source)

    def test_cancel_before_launch(self):
        with patch.object(backend.subprocess, "Popen") as launch:
            with self.assertRaises(SimulationCancelled):
                backend.run_octave_simulation({}, {}, cancel_check=lambda: True)
            launch.assert_not_called()

    def test_cancel_and_timeout_child_cleanup_contract(self):
        class Child:
            returncode = None
            killed = False
            def poll(self): return None if not self.killed else -9
            def kill(self): self.killed = True
            def wait(self, timeout): self.returncode = -9; return -9
        doc = model("Constant", "Scope")
        for mode in ("cancel", "timeout", "callback_error"):
            child = Child()
            checks = iter([False, False, True])
            callback = (lambda _: (_ for _ in ()).throw(RuntimeError("callback failed"))) if mode == "callback_error" else None
            # callback failure at initial 0 occurs before process launch; use
            # cancellation/timeout to exercise the launched-child cleanup path.
            with self.subTest(mode=mode), patch.object(backend, "discover_octave", return_value=sys.executable), \
                    patch.object(backend.subprocess, "Popen", return_value=child), \
                    patch.dict(os.environ, OCTALINK_OCTAVE_TIMEOUT="0.0000001"):
                expected = SimulationCancelled if mode == "cancel" else (RuntimeError if callback else TimeoutError)
                with self.assertRaises(expected):
                    backend.run_octave_simulation(doc, BLOCK_SPECS,
                        cancel_check=(lambda: next(checks)) if mode == "cancel" else None,
                        progress_callback=callback)
            if mode != "callback_error":
                self.assertTrue(child.killed)

    def test_invalid_timeout(self):
        for value in ("0", "nan", "-1", "100000"):
            with patch.object(backend, "discover_octave", return_value=sys.executable), \
                    patch.dict(os.environ, OCTALINK_OCTAVE_TIMEOUT=value), self.assertRaises(ValueError):
                backend.run_octave_simulation(model("Constant", "Scope"), BLOCK_SPECS)


@unittest.skipUnless(LIVE, "GNU Octave absent or explicit offline-test mode")
class BackendLiveTests(unittest.TestCase):
    def run_model(self, document):
        return backend.run_octave_simulation(document, BLOCK_SPECS, executable=OCTAVE)

    def assert_matches_python(self, document, atol=2e-11):
        actual = self.run_model(document)
        expected = SimulationEngine().run_simulation(detached_graph(document, BLOCK_SPECS),
                    t_stop=document["stop_time"], dt=document["dt"], write_csv=False,
                    solver=document.get("solver", "rk4"))
        for block, record in expected.items():
            times, values, labels = actual[block.block_id]
            np.testing.assert_array_equal(times, record["time"])
            # Rounding differences scale with each channel's magnitude: a
            # 1.6e5-gain lead compensator (CTMS motor speed) peaks at 160000 V.
            reference = np.asarray(record["values"], dtype=float)
            scale = np.maximum(1.0, np.max(np.abs(reference), axis=0))
            np.testing.assert_array_less(np.abs(np.asarray(values) - reference), atol * scale + 1e-12 * np.abs(reference) + 1e-300)
            self.assertEqual(labels, record["labels"])
        return actual

    def test_analytical_integration_and_step_endpoint(self):
        doc = model(("Step", {"step_time": .13}), "Integrator", "Scope", dt=.1, stop=.37)
        times, values, _ = self.run_model(doc)[3]
        truth = np.maximum(0, np.asarray(times)-.13)
        error = float(np.max(np.abs(np.asarray(values)[:, 0]-truth)))
        print(f"MEASUREMENT: Octave Step/integral maximum absolute error={error:.17g}; samples={len(times)}")
        np.testing.assert_allclose(np.asarray(values)[:, 0], truth, atol=1e-14, rtol=0)

    def test_all_shipped_examples(self):
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(example=path.name):
                results = self.assert_matches_python(json.loads(path.read_text(encoding="utf-8")))
                print(f"MEASUREMENT: Octave/Python {path.name}: {len(results)} matching sinks")

    def test_simultaneous_delays_and_multirate_hold(self):
        for doc in (model(("Constant", {"value": 1}), ("Unit Delay", {"sample_time": .1}),
                          ("Unit Delay", {"sample_time": .1}), "Integrator", "Scope", stop=.37, dt=.07),
                    model(("Octave Function", {"expression": "t"}), "Scope")):
            if doc["root"]["blocks"][0]["type"] == "Octave Function":
                doc = model("Constant", ("Octave Function", {"expression": "t"}),
                            ("Zero-Order Hold", {"sample_time": .15}),
                            ("Unit Delay", {"sample_time": .2}), "Integrator", "Scope", stop=.53, dt=.07)
            self.assert_matches_python(doc)

    def test_all_arithmetic_routing_and_relay(self):
        doc = model(("Sine Wave", {"frequency": 5}), "Relay", "Trig", "Saturation", "Gain",
                    ("Constant", {"value": 3}), "Sum", "Product", "Switch",
                    ("Mux", {"inputs": 2}), ("Demux", {"outputs": 2}), "Scope", stop=.73, dt=.03)
        doc["root"]["wires"] = []
        for src, dst, inp, out in ((1,2,0,0),(2,3,0,0),(3,4,0,0),(4,5,0,0),
                (5,7,0,0),(6,7,1,0),(7,8,0,0),(6,8,1,0),(8,9,0,0),(1,9,1,0),
                (6,9,2,0),(9,10,0,0),(1,10,1,0),(10,11,0,0),(11,12,0,1)):
            wire(doc, src, dst, inp, out)
        self.assert_matches_python(doc)

    def test_transfer_direct_feedthrough_and_pid(self):
        for kind, params in (("Transfer Fcn", {"numerator": "[1 2]", "denominator": "[1 3]"}),
                             ("Transfer Fcn", {"numerator": "[3]", "denominator": "[2]"}),
                             ("PID Controller", {"Kp": 2, "Ki": 1, "Kd": .4, "N": 5})):
            self.assert_matches_python(model(("Step", {"step_time": .17}), (kind, params), "Scope", stop=.5, dt=.02))

    def test_expression_vector_math(self):
        doc = model(("Constant", {"value": 2}), ("Constant", {"value": -3}),
                    ("Mux", {"inputs": 2}),
                    ("Octave Function", {"expression": "max(u_vec[0], abs(u_vec[1])) + min(u,4) + (-3)%2 + log(8,2) + sin(t)^2"}), "Scope")
        doc["root"]["wires"] = []
        for src, dst, inp in ((1,3,0),(2,3,1),(3,4,0),(4,5,0)):
            wire(doc, src, dst, inp)
        self.assert_matches_python(doc)

    def test_runtime_errors_are_not_partial_success(self):
        for expr in ("1/(u-u)", "sqrt(-1)", "u_vec[2]", "u^1025", "log(-2,-2)"):
            with self.subTest(expression=expr), self.assertRaises(RuntimeError):
                self.run_model(model("Constant", ("Octave Function", {"expression": expr}), "Scope"))

    def test_progress_and_real_cancellation(self):
        progress = []
        backend.run_octave_simulation(model("Constant", "Integrator", "Scope"), BLOCK_SPECS,
                                     executable=OCTAVE, progress_callback=progress.append)
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], 1)
        self.assertEqual(progress, sorted(progress))
        children = []
        launch = subprocess.Popen
        def tracked(*args, **kwargs):
            child = launch(*args, **kwargs)
            children.append(child)
            return child
        checks = iter([False, False, True])
        with patch.object(backend.subprocess, "Popen", tracked), self.assertRaises(SimulationCancelled):
            backend.run_octave_simulation(model("Constant", "Integrator", "Scope"),
                BLOCK_SPECS, executable=OCTAVE, cancel_check=lambda: next(checks))
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_real_timeout_terminates_child(self):
        children = []
        launch = subprocess.Popen
        def tracked(*args, **kwargs):
            child = launch(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(backend.subprocess, "Popen", tracked), \
                patch.dict(os.environ, OCTALINK_OCTAVE_TIMEOUT=".0000001"), self.assertRaises(TimeoutError):
            self.run_model(model("Constant", "Integrator", "Scope"))
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_export_executes_without_python_and_matches_backend(self):
        doc = model("Constant", "Integrator", "Scope", stop=.2, dt=.03)
        expected = self.run_model(doc)[3]
        with tempfile.TemporaryDirectory() as tmp:
            target = backend.export_octave_script(doc, BLOCK_SPECS, Path(tmp)/"standalone.m")
            env = dict(os.environ, OCTALINK_NO_PLOT="1")
            result = subprocess.run([OCTAVE, "--no-gui", "--quiet", "--no-init-file", "--no-site-file", str(target)],
                                    cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OCTALINK_COMPLETE", result.stdout)
            values = np.loadtxt(Path(tmp)/"octalink_sink_3.csv", delimiter=",")
        np.testing.assert_allclose(values[:, 0], expected[0], rtol=0, atol=0)
        np.testing.assert_allclose(values[:, 1], np.array(expected[1])[:, 0], rtol=0, atol=1e-14)

    def test_installed_van_der_pol_against_independent_ode45(self):
        doc = model(("Integrator", {"initial_condition": 2}), "Integrator", ("Mux", {"inputs": 2}),
                    ("Octave Function", {"expression": "(1-u_vec[0]^2)*u_vec[1]-u_vec[0]"}), "Scope", stop=2, dt=.005)
        doc["root"]["wires"] = []
        for src, dst, inp in ((2,1,0),(4,2,0),(1,3,0),(2,3,1),(3,4,0),(3,5,0)):
            wire(doc, src, dst, inp)
        actual = np.asarray(self.run_model(doc)[5][1])[-1]
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp)/"installed_case.m"
            script.write_text("% Adapted Octave ode45.m lines 326-333 (GPLv3+)\n"
                "fpol=@(t,y) [y(2);(1-y(1)^2)*y(2)-y(1)];\n"
                "[t,y]=ode45(fpol,[0 2],[2;0],odeset('RelTol',1e-11,'AbsTol',1e-13));\n"
                "dlmwrite('ode45_truth.csv',y(end,:),',','precision','%.17g');\n", encoding="utf-8")
            run = subprocess.run([OCTAVE,"--no-gui","--quiet","--no-init-file","--no-site-file",str(script)],
                                 cwd=tmp,capture_output=True,text=True,timeout=120)
            self.assertEqual(run.returncode,0,run.stderr)
            truth=np.loadtxt(Path(tmp)/"ode45_truth.csv",delimiter=",")
        error=float(np.max(np.abs(actual-truth)))
        print(f"MEASUREMENT: installed Van der Pol RK4 versus independent ode45 maximum endpoint error={error:.17g}")
        np.testing.assert_allclose(actual, truth, atol=5e-8, rtol=0)
        np.testing.assert_allclose(actual,[.32331666704577,-1.83297456798624],atol=5e-8,rtol=0)


if __name__ == "__main__":
    if "--mutation-control" in sys.argv:
        sys.argv.remove("--mutation-control")
        if not LIVE:
            raise SystemExit("Mutation control requires a live Octave executable.")
        original = backend._generate
        def mutated(*args, **kwargs):
            source, *metadata = original(*args, **kwargs)
            return (source.replace("x=x+h*(k1+2*k2+2*k3+k4)/6", "x=x+0*(k1+2*k2+2*k3+k4)/6"), *metadata)
        with patch.object(backend, "_generate", mutated):
            suite=unittest.TestSuite([BackendLiveTests("test_analytical_integration_and_step_endpoint")])
            result=unittest.TextTestRunner(verbosity=2).run(suite)
            raise SystemExit(0 if result.wasSuccessful() else 1)
    unittest.main()
