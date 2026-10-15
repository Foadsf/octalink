"""Compile/run exported C99 and compare measured samples against engine truth.

Windows: python -m unittest discover -s tests -p test_c_export.py -v
Windows: python tests/test_c_export.py --mutation-control (must exit nonzero)
Uses an installed gcc, never installs tools. OCTALINK_CC may select a compiler.
"""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from c_export import export_c_model
from mvp_model import detached_graph
from octalink_gui import BLOCK_SPECS, SimulationEngine

CC = os.environ.get("OCTALINK_CC") or shutil.which("gcc")
if not CC and Path("C:/msys64/ucrt64/bin/gcc.exe").is_file():
    CC = "C:/msys64/ucrt64/bin/gcc.exe"
MUTATE = False


class Document:
    def __init__(self):
        self.data = {"version": "4.0", "stop_time": 1, "dt": .01,
                     "root": {"blocks": [], "wires": []}}

    def add(self, kind, name=None, **params):
        ident = len(self.data["root"]["blocks"]) + 1
        self.data["root"]["blocks"].append({"id": ident, "type": kind,
            "name": name or f"{kind} {ident}", "x": 0, "y": 0,
            "params": {k: str(v) for k, v in params.items()}})
        return ident

    def connect(self, source, target, target_port=0, source_port=0):
        self.data["root"]["wires"].append({"from_block": source,
            "from_port": source_port, "to_block": target, "to_port": target_port})


def chain(*entries):
    doc = Document()
    ids = [doc.add(kind, **params) for kind, params in entries]
    for a, b in zip(ids, ids[1:]):
        doc.connect(a, b)
    return doc.data


@unittest.skipUnless(CC, "Installed C99 gcc compiler is required")
class CExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="c-export-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def compile(self, doc, dt, main, mutate=False):
        header, source = export_c_model(doc, BLOCK_SPECS, dt, self.directory / "model")
        if mutate:
            text = source.read_text()
            self.assertIn("st->X[i] = tmp[i];", text, "Mutation must target actual generated integration")
            source.write_text(text.replace("st->X[i] = tmp[i];", "st->X[i] = st->X[i];"))
        runner = self.directory / "runner.c"
        runner.write_text('#include "model.h"\n#include <math.h>\n#include <stdio.h>\n' + main)
        executable = self.directory / ("run.exe" if os.name == "nt" else "run")
        env = dict(os.environ)
        # gcc subprocesses and the built executable need the installed runtime DLLs.
        env["PATH"] = str(Path(CC).resolve().parent) + os.pathsep + env.get("PATH", "")
        result = subprocess.run([CC, "-std=c99", "-pedantic", "-Wall", "-Wextra", "-Werror",
                                 "-O2", str(source), str(runner), "-lm", "-o", str(executable)],
                                capture_output=True, text=True, env=env, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return executable, env

    def run_model(self, doc, stop, dt, mutate=False, bulk=False):
        body = f'''int main(void) {{
    OctaLink_State st;
    OctaLink_Init(&st);
    for (;;) {{
        if (st.status) {{ fprintf(stderr, "STATUS=%d BLOCK=%u TIME=%.17g\\n", st.status, st.error_block, st.t); return st.status; }}
        printf("%.17g", st.t);
        for (int i=0; i<OCTALINK_NUM_OUTPUTS; ++i) printf(",%.17g", st.y_out[i]);
        puts("");
        if (st.t >= {stop:.17g}) break;
        double next = {'('+format(stop,'.17g')+')' if bulk else 'OctaLink_NextTime(&st, '+format(stop,'.17g')+')'};
        OctaLink_Step(&st, next-st.t);
    }}
    return 0;
}}
'''
        exe, env = self.compile(doc, dt, body, mutate=mutate)
        result = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = np.array([[float(v) for v in row.split(",")] for row in result.stdout.splitlines()])
        self.assertTrue(np.all(np.isfinite(rows)), result.stdout)
        return rows

    def compare_python(self, doc, stop, dt, tolerance=1e-10, bulk=False):
        scene = detached_graph(doc, BLOCK_SPECS)
        result = SimulationEngine().run_simulation(scene, stop, dt, write_csv=False)
        self.assertTrue(result)
        time = list(result.values())[0]["time"]
        values = np.concatenate([np.array(sink["values"]) for sink in result.values()], axis=1)
        truth = np.column_stack([time, values])
        actual = self.run_model(doc, stop, dt, mutate=MUTATE, bulk=bulk)
        if bulk:
            truth = truth[[0, -1]]
        self.assertEqual(actual.shape, truth.shape)
        np.testing.assert_allclose(actual[:, 0], truth[:, 0], atol=2e-14, rtol=0)
        np.testing.assert_allclose(actual[:, 1:], truth[:, 1:], atol=tolerance, rtol=tolerance)
        error = np.max(np.abs(actual[:, 1:] - truth[:, 1:]))
        print(f"MEASUREMENT: C/Python {len(actual)} rows, {actual.shape[1]-1} channels, max error={error:.3g}, final time={actual[-1,0]:.17g}.")
        return actual

    def test_analytical_integrator_and_exact_step(self):
        doc = chain(("Step", {"step_time": .13}), ("Integrator", {}), ("Scope", {}))
        rows = self.compare_python(doc, .37, .1)
        np.testing.assert_allclose(rows[:, 1], np.maximum(0, rows[:, 0]-.13), atol=1e-14, rtol=0)
        self.assertTrue(np.any(rows[:, 0] == .13))
        self.assertAlmostEqual(rows[-1, 1], .24, places=14)
        # Legacy API: one long Step call still splits internal events/grid.
        self.compare_python(doc, .37, .1, bulk=True)

    def test_analytical_transfer_and_state_space(self):
        doc = chain(("Constant", {"value": 2}),
                    ("Transfer Fcn", {"numerator": "[1]", "denominator": "[1 2]"}), ("Scope", {}))
        rows = self.compare_python(doc, 1, .02)
        np.testing.assert_allclose(rows[:, 1], 1-np.exp(-2*rows[:, 0]), atol=9e-9, rtol=0)
        doc = chain(("Constant", {"value": 3}), ("State-Space", {"A": "[-2]", "B": "[1]",
                    "C": "[2]", "D": ".5", "x0": "[4]"}), ("Scope", {}))
        rows = self.compare_python(doc, 1, .01)
        np.testing.assert_allclose(rows[:, 1], 4.5+5*np.exp(-2*rows[:, 0]), atol=3e-9, rtol=0)
        doc = chain(("Constant", {"value": 3}),
                    ("Transfer Fcn", {"numerator": "[2 3]", "denominator": "[1 4]"}), ("Scope", {}))
        rows = self.compare_python(doc, 1, .01)
        np.testing.assert_allclose(rows[:, 1], 2.25+3.75*np.exp(-4*rows[:, 0]), atol=4e-8, rtol=0)

    def test_shipped_models_every_time_and_channel(self):
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(model=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                engine = SimulationEngine()
                engine.compile_graph(detached_graph(document, BLOCK_SPECS))
                if document.get("solver", "rk4") != "rk4" or engine.algebraic_loops:
                    # C export is RK4 with a straight-line network: SDIRK4 models
                    # and algebraic loops are refused before any file is written.
                    with self.assertRaisesRegex(ValueError, "RK4 solver only|algebraic loops"):
                        export_c_model(document, BLOCK_SPECS, float(document["dt"]), self.directory / "refused")
                    self.assertFalse(list(self.directory.glob("refused*")))
                    print(f"NEGATIVE CONTROL: {path.name} refused by C export.")
                    continue
                # Each model's own fixed step. The horizon is capped to keep this sweep fast.
                dt = float(document.get("dt", .01))
                stop = min(float(document.get("stop_time", 10)), 10.0, 5000 * dt)
                rows = self.compare_python(document, stop, dt)
                print(f"MEASUREMENT: {path.name} compiled C99 final channels={rows[-1,1:].tolist()}.")

    def test_delay_continuous_hold_and_simultaneous_commit(self):
        doc = chain(("Constant", {"value": 1}), ("Unit Delay", {"sample_time": .1}),
                    ("Integrator", {}), ("Scope", {}))
        rows = self.compare_python(doc, .5, .05)
        np.testing.assert_allclose(rows[:, 1], np.maximum(0, rows[:, 0]-.1), atol=1e-14, rtol=0)
        doc = chain(("Constant", {"value": 1}), ("Unit Delay", {"sample_time": .1}),
                    ("Unit Delay", {"sample_time": .1}), ("Scope", {}))
        rows = self.compare_python(doc, .3, .03)
        np.testing.assert_allclose(rows[:, 1], (rows[:, 0] >= .2-1e-14).astype(float), atol=0, rtol=0)

    def test_noncommensurate_sample_events_and_zoh_integration(self):
        doc = chain(("Constant", {"value": 0}), ("Octave Function", {"expression": "t"}),
                    ("Zero-Order Hold", {"sample_time": .15}), ("Integrator", {}), ("Scope", {}))
        rows = self.compare_python(doc, .53, .11)
        n = np.floor((rows[:, 0]+1e-14)/.15)
        truth = .15**2*n*(n-1)/2+n*.15*(rows[:, 0]-n*.15)
        np.testing.assert_allclose(rows[:, 1], truth, atol=1e-14, rtol=0)
        doc = chain(("Constant", {"value": 0}), ("Octave Function", {"expression": "t"}),
                    ("Zero-Order Hold", {"sample_time": .15}), ("Unit Delay", {"sample_time": .2}), ("Scope", {}))
        self.compare_python(doc, .6, .11)

    def test_nested_mux_demux_vector_expr_and_arbitrary_names(self):
        doc = Document()
        a, b, c = [doc.add("Constant", name='*/ invalid ; label "\\\n😺', value=value) for value in (1, 2, 3)]
        inner, outer = doc.add("Mux", inputs=2), doc.add("Mux", inputs=2)
        demux = doc.add("Demux", outputs=3)
        function = doc.add("Octave Function", expression="u_vec[2]^2 + u + t")
        scope, scalar_scope = doc.add("Scope"), doc.add("To CSV", filename="unused.csv")
        doc.connect(a, inner); doc.connect(b, inner, 1)
        doc.connect(inner, outer); doc.connect(c, outer, 1)
        doc.connect(outer, demux); doc.connect(outer, function)
        doc.connect(demux, scope, source_port=1); doc.connect(function, scalar_scope)
        rows = self.compare_python(doc.data, .3, .1)
        np.testing.assert_allclose(rows[:, 1], 2)
        np.testing.assert_allclose(rows[:, 2], 10+rows[:, 0])
        self.assertFalse((self.directory / "unused.csv").exists())

    def test_expression_precedence_math_modulo_and_static_transfer(self):
        for expression in ("(u+1)^2^3", "-u^2 + pi + e", "-5 % u", "5 % (-u)",
                           "min(u, 2, 4) + max(u, 1) + abs(-u)", "sqrt(u)+log(u)+exp(t)+floor(u)+ceil(t)"):
            with self.subTest(expression=expression):
                doc = chain(("Constant", {"value": 3}), ("Octave Function", {"expression": expression}), ("Scope", {}))
                self.compare_python(doc, .2, .1)
        doc = chain(("Constant", {"value": 3}), ("Transfer Fcn", {"numerator": "[2]", "denominator": "[4]"}), ("Scope", {}))
        rows = self.compare_python(doc, 0, .1)
        self.assertEqual(rows.tolist(), [[0, 1.5]])

    def test_relay_switch_saturation_and_pid(self):
        doc = Document()
        sine = doc.add("Sine Wave", amplitude=2, frequency=5)
        relay = doc.add("Relay", switch_on_point=.5, switch_off_point=-.5, on_val=1, off_val=-1)
        pid = doc.add("PID Controller", Kp=2, Ki=.4, Kd=.01, N=10)
        sat = doc.add("Saturation", lower_limit=-.75, upper_limit=.75)
        zero = doc.add("Constant", value=0)
        switch = doc.add("Switch", threshold=0)
        scope = doc.add("Scope")
        doc.connect(sine, relay); doc.connect(sine, pid); doc.connect(pid, sat)
        doc.connect(sat, switch); doc.connect(relay, switch, 1); doc.connect(zero, switch, 2)
        doc.connect(switch, scope)
        self.compare_python(doc.data, 2, .017)

    def test_unsafe_expressions_and_vector_mismatches_rejected(self):
        for expression in ('u; system("x")', "__import__('os')", "u.__class__", "u_vec[1]", "sin(u, t)", "min(u)"):
            doc = chain(("Constant", {}), ("Octave Function", {"expression": expression}), ("Scope", {}))
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                export_c_model(doc, BLOCK_SPECS, .01, self.directory / "rejected")
        self.assertFalse((self.directory / "rejected.c").exists())
        doc = chain(("Constant", {}), ("Demux", {"outputs": 2}), ("Scope", {}))
        with self.assertRaisesRegex(ValueError, "Demux expects"):
            export_c_model(doc, BLOCK_SPECS, .1, self.directory / "rejected")
        print("NEGATIVE CONTROL: unsafe syntax, bad function arity, missing vector channel and Demux width rejected before writing C.")

    def test_runtime_domain_division_and_bad_time_status(self):
        for expression in ("sqrt(-u)", "1/(u-1)", "min(sqrt(-u),0)", "u^(2000+t)"):
            doc = chain(("Constant", {"value": 1}), ("Octave Function", {"expression": expression}), ("Scope", {}))
            main = '''int main(void) { OctaLink_State st; OctaLink_Init(&st);
            printf("%d,%u\\n", st.status, st.error_block);
            return st.status==OCTALINK_NONFINITE && st.error_block==2U ? 0 : 99; }'''
            exe, env = self.compile(doc, .1, main)
            result = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(result.stdout.strip(), "2,2")
        doc = chain(("Constant", {"value": 1}), ("Scope", {}))
        main = '''int main(void) {
            OctaLink_State st; double bad[]={0,-1,NAN,INFINITY};
            for(int i=0;i<4;++i) { OctaLink_Init(&st); OctaLink_Step(&st,bad[i]);
                if(st.status!=OCTALINK_BAD_DT || st.t!=0) return 99;
                OctaLink_Step(&st,.1); if(st.t!=0) return 98; }
            OctaLink_Init(&st); st.step_idx=UINT32_MAX; OctaLink_Step(&st,.1);
            if(st.status!=OCTALINK_LIMIT) return 97;
            OctaLink_Init(&st); OctaLink_Step(&st,30000);
            if(st.status!=OCTALINK_LIMIT) return 96;
            puts("RUNTIME CONTROL: domain errors, bad dt, sticky status and substep/counter bounds observed"); return 0;
        }'''
        exe, env = self.compile(doc, .1, main)
        result = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        print(result.stdout.strip())

    def test_compiled_disabled_integration_control_really_fails(self):
        doc = chain(("Constant", {"value": 1}), ("Integrator", {}), ("Scope", {}))
        good = self.run_model(doc, .3, .1)
        bad = self.run_model(doc, .3, .1, mutate=True)
        np.testing.assert_allclose(good[:, 1], good[:, 0], atol=1e-14, rtol=0)
        with self.assertRaises(AssertionError):
            np.testing.assert_allclose(bad[:, 1], bad[:, 0], atol=1e-14, rtol=0)
        self.assertAlmostEqual(bad[-1, 1], 0)
        print("NEGATIVE CONTROL: compiled disabled-integration mutant failed the same analytical sample comparator; healthy C passed.")


if __name__ == "__main__":
    if "--mutation-control" in sys.argv:
        MUTATE = True
        suite = unittest.TestSuite(CExportTests(name) for name in (
            "test_analytical_integrator_and_exact_step", "test_delay_continuous_hold_and_simultaneous_commit",
            "test_noncommensurate_sample_events_and_zoh_integration"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(f"C MUTATION CONTROL: disabled integration; {len(result.failures)} failures, {len(result.errors)} errors.")
        sys.exit(0 if result.wasSuccessful() else 1)
    unittest.main()
