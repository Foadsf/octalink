"""Analytical and adversarial checks for the usable local engine MVP.

Run with ``python -m unittest discover -s tests -p test_engine_mvp.py -v``.
``python tests/test_engine_mvp.py --mutation-control`` deliberately disables
state integration: analytical tests must report failures and exit nonzero.
Fixtures use plain model objects, demonstrating worker-thread compatibility.
The original shipped JSON examples are loaded, including their hierarchy.
"""

import csv
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from octalink_gui import BLOCK_SPECS, SimulationEngine
from octalink_engine_support import SimulationCancelled, port_counts


class Block:
    def __init__(self, kind, name, scene, **params):
        self.block_type, self.name, self._scene = kind, name, scene
        self.spec = BLOCK_SPECS[kind]
        self.params = dict(self.spec["params"], **{key: str(value) for key, value in params.items()})
        # The document contract: Mux/Demux/Sum/Product ports follow parameters.
        n_in, n_out = port_counts(kind, self.params, self.spec)
        self.in_ports = [SimpleNamespace(parent_block=self, index=i, wires=[]) for i in range(n_in)]
        self.out_ports = [SimpleNamespace(parent_block=self, index=i, wires=[]) for i in range(n_out)]
        if kind == "Subsystem":
            self.sub_scene = Scene(self)
        self.scope_t, self.scope_y, self.scope_labels = [], [], []

    def scene(self):
        return self._scene


class Port(SimpleNamespace):
    # Real graphics ports are hashable. Match that contract in the fixture.
    __hash__ = object.__hash__


class Scene:
    def __init__(self, owner=None):
        self.owner_subsystem, self.blocks = owner, []

    def add(self, kind, name=None, **params):
        block = Block(kind, name or f"{kind}_{len(self.blocks)}", self, **params)
        block.in_ports = [Port(**vars(p)) for p in block.in_ports]
        block.out_ports = [Port(**vars(p)) for p in block.out_ports]
        self.blocks.append(block)
        return block

    def connect(self, source, target, target_port=0, source_port=0):
        wire = SimpleNamespace(start_port=source.out_ports[source_port], end_port=target.in_ports[target_port])
        source.out_ports[source_port].wires.append(wire)
        target.in_ports[target_port].wires.append(wire)

    @classmethod
    def from_json(cls, data, owner=None):
        scene = cls(owner)
        blocks = {}
        for entry in data["blocks"]:
            block = scene.add(entry["type"], entry["name"], **entry.get("params", {}))
            blocks[entry["id"]] = block
            if "sub_scene" in entry:
                block.sub_scene = cls.from_json(entry["sub_scene"], block)
                n_in = len([b for b in block.sub_scene.blocks if b.block_type == "Inport"])
                n_out = len([b for b in block.sub_scene.blocks if b.block_type == "Outport"])
                block.in_ports = [Port(parent_block=block, index=i, wires=[]) for i in range(n_in)]
                block.out_ports = [Port(parent_block=block, index=i, wires=[]) for i in range(n_out)]
        for entry in data["wires"]:
            scene.connect(blocks[entry["from_block"]], blocks[entry["to_block"]],
                          entry["to_port"], entry["from_port"])
        return scene


def chain(*blocks):
    scene = Scene()
    added = [scene.add(kind, **params) for kind, params in blocks]
    for source, target in zip(added, added[1:]):
        scene.connect(source, target)
    return scene, added


class EngineMVPTests(unittest.TestCase):
    def setUp(self):
        self.engine = SimulationEngine()

    def assertSignal(self, scope, expected, atol=1e-11):
        actual = np.array(scope.scope_y)[:, 0]
        truth = np.array([expected(t) for t in scope.scope_t])
        np.testing.assert_allclose(actual, truth, atol=atol, rtol=0)
        return float(np.max(np.abs(actual - truth)))

    def test_constructor_does_not_launch_octave(self):
        with patch("octalink_gui.OCTAVE_AVAILABLE", True), patch("octalink_gui.Oct2Py", create=True) as octave:
            engine = SimulationEngine()
            octave.assert_not_called()
            self.assertIsNone(engine.octave)

    def test_safe_arithmetic_and_arrays(self):
        self.assertAlmostEqual(self.engine.eval_scalar("sin(pi/2)+2^3"), 9)
        self.assertAlmostEqual(self.engine.eval_user_expr("u_vec[1]^2 + u + t", [2, 3], 4), 15)
        self.assertEqual(self.engine.eval_vector("[1, sin(pi/2); 2*pi]"), [1, 1, 2 * math.pi])
        np.testing.assert_array_equal(self.engine.eval_matrix("[1 2; 3 4]"), [[1, 2], [3, 4]])
        self.assertEqual(self.engine.eval_scalar("1e-12"), 1e-12)
        self.assertEqual(self.engine.eval_vector("1 + 2"), [3])
        self.assertEqual(self.engine.eval_vector("[max(1, 2), 3]"), [2, 3])

    def test_expression_security_negative_controls(self):
        attacks = ["().__class__.__bases__", "__import__('os').getcwd()",
                   "[x for x in [1]]", "(lambda: 1)()", "u.__class__",
                   "open('attack-proof.txt', 'w')", "u_vec[-1]", "u_vec[u]",
                   "True", "'1'", "10^1000000", "1e309", "1/0"]
        for expression in attacks:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                self.engine.eval_user_expr(expression, 1, 0)
        with self.assertRaises(ValueError):
            self.engine.eval_user_expr("u_vec[1]", [1], 0)
        print("NEGATIVE CONTROL: 13 unsafe/non-finite expressions and missing vector channel rejected.")

    def test_closed_loop_first_order_analytical_response(self):
        scene = Scene()
        source = scene.add("Step", step_time=0)
        error = scene.add("Sum", signs="+-")
        gain = scene.add("Gain", gain=1)
        integral = scene.add("Integrator")
        scope = scene.add("Scope")
        scene.connect(source, error)
        scene.connect(integral, error, 1)
        scene.connect(error, gain)
        scene.connect(gain, integral)
        scene.connect(integral, scope)
        self.engine.run_simulation(scene, 2, .1)
        error_max = self.assertSignal(scope, lambda t: 1 - math.exp(-t), atol=4e-7)
        print(f"MEASUREMENT: closed-loop RK4 max absolute error = {error_max:.3g}.")
        with self.assertRaises(AssertionError):
            self.assertSignal(scope, lambda t: t)

    def test_transfer_function_analytical_response(self):
        scene, blocks = chain(("Constant", {"value": 2}),
                              ("Transfer Fcn", {"numerator": "[1]", "denominator": "[1 2]"}),
                              ("Scope", {}))
        self.engine.run_simulation(scene, 1, .02)
        self.assertSignal(blocks[-1], lambda t: 1 - math.exp(-2 * t), atol=9e-9)

    def test_static_transfer_and_zero_stop(self):
        scene, blocks = chain(("Constant", {"value": 3}),
                              ("Transfer Fcn", {"numerator": "[2]", "denominator": "[4]"}),
                              ("Scope", {}))
        self.engine.run_simulation(scene, 0, .1)
        self.assertEqual(blocks[-1].scope_t, [0])
        self.assertEqual(blocks[-1].scope_y, [[1.5]])

    def test_state_space_initial_state_and_direct_term(self):
        scene, blocks = chain(("Constant", {"value": 3}),
                              ("State-Space", {"A": "[-2]", "B": "[1]", "C": "[2]", "D": ".5", "x0": "[4]"}),
                              ("Scope", {}))
        self.engine.run_simulation(scene, 1, .01)
        self.assertSignal(blocks[-1], lambda t: 4.5 + 5 * math.exp(-2 * t), atol=3e-9)

    def test_exact_stop_and_step_discontinuity(self):
        scene, blocks = chain(("Step", {"step_time": .13}), ("Integrator", {}), ("Scope", {}))
        self.engine.run_simulation(scene, .37, .1)
        self.assertEqual(blocks[-1].scope_t[-1], .37)
        self.assertIn(.13, blocks[-1].scope_t)
        self.assertSignal(blocks[-1], lambda t: max(0, t - .13))
        with self.assertRaises(AssertionError):
            self.assertSignal(blocks[-1], lambda t: t)
        # dt can exceed the duration, while t=0 and t_stop both remain present.
        self.engine.run_simulation(scene, .37, 10)
        self.assertEqual(blocks[-1].scope_t, [0, .13, .37])
        self.assertSignal(blocks[-1], lambda t: max(0, t - .13))

    def test_unit_delay_continuous_integration_holds_old_state(self):
        scene, blocks = chain(("Constant", {"value": 1}),
                              ("Unit Delay", {"sample_time": .1}), ("Integrator", {}), ("Scope", {}))
        self.engine.run_simulation(scene, .5, .05)
        error_max = self.assertSignal(blocks[-1], lambda t: max(0, t - .1))
        print(f"MEASUREMENT: delayed constant integration max absolute error = {error_max:.3g}.")

    def test_noncommensurate_multirate_sample_times(self):
        scene, blocks = chain(("Constant", {"value": 0}), ("Octave Function", {"expression": "t"}),
                              ("Zero-Order Hold", {"sample_time": .15}),
                              ("Unit Delay", {"sample_time": .2}), ("Scope", {}))
        self.engine.run_simulation(scene, .6, .11)
        scope = blocks[-1]
        self.assertTrue(any(abs(t - .15) < 1e-14 for t in scope.scope_t))
        self.assertTrue(any(abs(t - .4) < 1e-14 for t in scope.scope_t))
        def expected(t):
            if t < .4 - 1e-14:
                return 0.0
            if t < .6 - 1e-14:
                return .15
            return .3
        self.assertSignal(scope, expected)

    def test_simultaneous_delay_updates(self):
        scene, blocks = chain(("Constant", {"value": 1}), ("Unit Delay", {"sample_time": .1}),
                              ("Unit Delay", {"sample_time": .1}), ("Scope", {}))
        self.engine.run_simulation(scene, .3, .03)
        self.assertSignal(blocks[-1], lambda t: 0 if t < .2 - 1e-14 else 1)

    def test_zoh_integral_uses_exact_sample_times(self):
        scene, blocks = chain(("Constant", {"value": 0}), ("Octave Function", {"expression": "t"}),
                              ("Zero-Order Hold", {"sample_time": .15}), ("Integrator", {}), ("Scope", {}))
        self.engine.run_simulation(scene, .53, .11)
        def expected(t):
            n = int(math.floor((t + 1e-14) / .15))
            return .15 ** 2 * n * (n - 1) / 2 + n * .15 * (t - n * .15)
        self.assertSignal(blocks[-1], expected)

    def test_delay_feedback_breaks_loop_and_direct_loop_rejected(self):
        scene = Scene()
        delay = scene.add("Unit Delay", initial_condition=1, sample_time=.1)
        gain = scene.add("Gain", gain=2)
        scope = scene.add("Scope")
        scene.connect(delay, gain)
        scene.connect(gain, delay)
        scene.connect(delay, scope)
        self.engine.run_simulation(scene, .3, .05)
        self.assertSignal(scope, lambda t: 2 ** int(math.floor((t + 1e-14) / .1)))
        # Direct-feedthrough cycles are algebraic loops, solved by Newton
        # (tests/test_solvers.py); a loop with no solution is still refused.
        loop = Scene()
        constant, total, unity = loop.add("Constant", value=1), loop.add("Sum", signs="++"), loop.add("Gain", gain=1)
        loop.connect(constant, total)
        loop.connect(unity, total, 1)
        loop.connect(total, unity)
        with self.assertRaisesRegex(RuntimeError, "Algebraic loop .* singular"):
            self.engine.run_simulation(loop)
        tiny_direct = Scene()
        dynamic = tiny_direct.add("State-Space", A="[-1]", B="[1]", C="[1]", D="0.5", x0="[1]")
        gain = tiny_direct.add("Gain", gain=-1)
        scope = tiny_direct.add("Scope")
        tiny_direct.connect(dynamic, gain)
        tiny_direct.connect(gain, dynamic)
        tiny_direct.connect(dynamic, scope)
        # y = x + 0.5 u, u = -y: y = x/1.5 and x' = -x - y = -(5/3) x.
        self.engine.run_simulation(tiny_direct, 1, .01)
        self.assertSignal(scope, lambda t: math.exp(-5 * t / 3) / 1.5, atol=1e-9)
        print("NEGATIVE CONTROL: unsolvable loop y = 1 + y rejected; delay feedback and a solvable loop accepted.")

    def test_missing_input_and_multiple_drivers_rejected(self):
        scene = Scene()
        scope = scene.add("Scope", "Missing")
        with self.assertRaisesRegex(ValueError, "Missing: input 1"):
            self.engine.run_simulation(scene)
        a, b = scene.add("Constant"), scene.add("Constant")
        scene.connect(a, scope)
        scene.connect(b, scope)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.engine.run_simulation(scene)

    def test_bad_time_bounds_and_parameters_rejected(self):
        scene, blocks = chain(("Constant", {}), ("Scope", {}))
        for stop, dt in [(-1, .1), (math.nan, .1), (math.inf, .1),
                         (1, 0), (1, -1), (1, math.inf), (1, math.nan), (1, 1e-10)]:
            with self.subTest(stop=stop, dt=dt), self.assertRaises(ValueError):
                self.engine.run_simulation(scene, stop, dt)
        for value in ["nan", "inf", "1e309", "0/0"]:
            blocks[0].params["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.engine.run_simulation(scene)
        for ts in ["0", "-1", "1e-12"]:
            model, _ = chain(("Constant", {}), ("Zero-Order Hold", {"sample_time": ts}), ("Scope", {}))
            with self.subTest(sample_time=ts), self.assertRaises(ValueError):
                self.engine.run_simulation(model)

    def test_runtime_nonfinite_and_function_domain_errors_rejected(self):
        for kind, params in [("Gain", {"gain": "1e308"}),
                             ("Octave Function", {"expression": "sqrt(-u)"})]:
            scene, _ = chain(("Constant", {"value": 2}), (kind, params), ("Scope", {}))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.engine.run_simulation(scene, 0, .1)
        for value in ["[1;]", "[1,]", "[1", "[1 2; 3]"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.engine.eval_matrix(value)

    def test_inconsistent_state_space_rejected(self):
        cases = [{"A": "[1 2]"}, {"B": "[1 2]"}, {"C": "[1; 2]"}, {"x0": "[1]"}]
        for params in cases:
            scene, _ = chain(("Constant", {}), ("State-Space", params), ("Scope", {}))
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.engine.run_simulation(scene)

    def test_division_by_zero_and_dimension_mismatch_rejected(self):
        scene = Scene()
        one, zero = scene.add("Constant", value=1), scene.add("Constant", value=0)
        product = scene.add("Product", ops="*/")
        scene.connect(one, product)
        scene.connect(zero, product, 1)
        with self.assertRaisesRegex(ValueError, "division by zero"):
            self.engine.run_simulation(scene, 0, .1)
        scene, _ = chain(("Constant", {}), ("Demux", {}), ("Scope", {}))
        with self.assertRaisesRegex(ValueError, "expects 2 channels"):
            self.engine.run_simulation(scene, 0, .1)
        # A vector must not silently lose all channels but its first. Gain is
        # element-wise (Simulink K.*u); a scalar-only block must reject it.
        scene = Scene()
        mux = scene.add("Mux", inputs=2)
        for i in range(2):
            scene.connect(scene.add("Constant"), mux, i)
        integrator = scene.add("Integrator")
        scene.connect(mux, integrator)
        with self.assertRaisesRegex(ValueError, "2-element vector"):
            self.engine.run_simulation(scene, 0, .1)

    def test_progress_cancellation_and_no_partial_publication(self):
        scene, blocks = chain(("Constant", {}), ("Integrator", {}), ("Scope", {}))
        progress = []
        self.engine.run_simulation(scene, .2, .01, progress_callback=progress.append)
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], 1)
        self.assertEqual(progress, sorted(progress))
        old_t, old_y = list(blocks[-1].scope_t), list(blocks[-1].scope_y)
        cancel = {"stop": False}
        def on_progress(fraction):
            if fraction > .2:
                cancel["stop"] = True
        with self.assertRaises(SimulationCancelled):
            self.engine.run_simulation(scene, 10, .01, cancel_check=lambda: cancel["stop"], progress_callback=on_progress)
        self.assertEqual(blocks[-1].scope_t, old_t)
        self.assertEqual(blocks[-1].scope_y, old_y)
        with self.assertRaises(SimulationCancelled):
            self.engine.run_simulation(scene, cancel_check=lambda: True)
        print("NEGATIVE CONTROL: cancellation raised SimulationCancelled and preserved prior results.")

    def test_csv_sink_and_write_opt_out(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "output.csv"
            scene, _ = chain(("Constant", {"value": 2}), ("To CSV", {"filename": str(path)}))
            self.engine.run_simulation(scene, .2, .1, write_csv=False)
            self.assertFalse(path.exists())
            self.engine.run_simulation(scene, .2, .1)
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0][0], "time")
            np.testing.assert_allclose(np.array(rows[1:], dtype=float), [[0, 2], [.1, 2], [.2, 2]])

    def test_nested_mux_preserves_channels_and_labels(self):
        scene = Scene()
        a, b, c = [scene.add("Constant", name=name, value=value) for name, value in
                   (("A", 1), ("B", 2), ("C", 3))]
        inner, outer = scene.add("Mux", inputs=2), scene.add("Mux", inputs=2)
        scope = scene.add("Scope")
        scene.connect(a, inner)
        scene.connect(b, inner, 1)
        scene.connect(inner, outer)
        scene.connect(c, outer, 1)
        scene.connect(outer, scope)
        self.engine.run_simulation(scene, 0, .1)
        self.assertEqual(scope.scope_y, [[1, 2, 3]])
        self.assertEqual(scope.scope_labels, ["A", "B", "C"])

    def test_shipped_examples_hierarchy_and_finite_outputs(self):
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(example=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                scene = Scene.from_json(data["root"])
                scene.variables = data.get("variables")      # Model Workspace
                # Each model's own step and solver (the stiff plant uses SDIRK4), 200 steps.
                dt = float(data.get("dt", .01))
                stop = min(float(data.get("stop_time", 10)), 200 * dt)
                result = self.engine.run_simulation(scene, stop, dt, write_csv=False,
                                                    solver=data.get("solver", "rk4"))
                self.assertTrue(result)
                for sink, output in result.items():
                    self.assertEqual(output["time"][-1], stop)
                    self.assertGreater(len(output["time"]), 100)
                    self.assertTrue(np.all(np.isfinite(output["values"])))
                    print(f"MEASUREMENT: {path.name}/{sink.name}: {len(output['time'])} finite samples.")


if __name__ == "__main__":
    if "--mutation-control" in sys.argv:
        original = SimulationEngine._build_evaluator
        def broken_evaluator(self, *args, **kwargs):
            evaluate = original(self, *args, **kwargs)
            def no_state_integration(*values, **options):
                signals, derivative = evaluate(*values, **options)
                return signals, np.zeros_like(derivative)
            return no_state_integration
        SimulationEngine._build_evaluator = broken_evaluator
        suite = unittest.TestSuite(EngineMVPTests(name) for name in
                                  ("test_closed_loop_first_order_analytical_response",
                                   "test_unit_delay_continuous_integration_holds_old_state",
                                   "test_zoh_integral_uses_exact_sample_times"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        print(f"MUTATION CONTROL: disabled state integration; {len(result.failures)} analytical failures, {len(result.errors)} errors.")
        sys.exit(0 if result.wasSuccessful() else 1)
    unittest.main()
