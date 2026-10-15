"""Independent analytical controls for the local SISO advisor.

Run: python -m unittest discover -s tests -p test_linear_analysis.py -v
Run the deliberate bad-matrix control: python tests/test_linear_analysis.py --mutation-control
The latter must fail and exit nonzero.
"""
import copy
import json
import math
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import linear_analysis
from linear_analysis import analyze_model, crossing_margins
from octalink_gui import BLOCK_SPECS


def serial_document(*entries):
    blocks = [{"id": i + 1, "type": kind, "name": f"{kind}_{i+1}", "x": i * 100, "y": 0,
               "params": params} for i, (kind, params) in enumerate(entries)]
    return {"version": "4.0", "stop_time": "10", "dt": ".01",
            "root": {"blocks": blocks, "wires": [
                {"from_block": i, "from_port": 0, "to_block": i + 1, "to_port": 0}
                for i in range(1, len(blocks))]}}


def transfer(numerator, denominator, **kwargs):
    return analyze_model(serial_document(("Step", {"step_time": "0"}),
                                         ("Transfer Fcn", {"numerator": numerator, "denominator": denominator}),
                                         ("Scope", {})), BLOCK_SPECS, **kwargs)


class LinearAnalysisTests(unittest.TestCase):
    def test_shipped_first_order_feedback(self):
        data = json.loads((ROOT / "examples/first_order_feedback.json").read_text())
        before = copy.deepcopy(data)
        result = analyze_model(data, BLOCK_SPECS)
        np.testing.assert_allclose(result["A"], [[-2]], atol=1e-9)
        np.testing.assert_allclose(result["B"], [[2]], atol=1e-9)
        np.testing.assert_allclose(result["C"], [[1]], atol=1e-9)
        self.assertEqual(result["D"], 0)
        np.testing.assert_allclose(result["freq_resp"], 2 / (2 + 1j * result["omega"]), atol=1e-10)
        self.assertAlmostEqual(result["dc_gain"], 1)
        self.assertAlmostEqual(result["step_metrics"]["rise_time"], math.log(9) / 2, delta=5e-5)
        self.assertAlmostEqual(result["step_metrics"]["settling_time"], -math.log(.02) / 2, delta=.011)
        self.assertEqual(result["sink"]["channel"], 1)
        self.assertIn("Integrator", result["sink"]["label"])
        self.assertEqual(result["stability"], "stable")
        self.assertEqual(before, data)
        self.assertEqual(len(result["zeros"]), 0)
        # A subtracting Sum is insufficient to infer model loop margins.
        self.assertTrue(math.isnan(result["margins"]["phase_margin_deg"]))
        print(f"MEASUREMENT: first-order A={result['A'].tolist()}, B={result['B'].tolist()}, DC={result['dc_gain']:.12g}, rise={result['step_metrics']['rise_time']:.6g}s.")

    def test_reference_channel_is_explicit(self):
        data = json.loads((ROOT / "examples/first_order_feedback.json").read_text())
        result = analyze_model(data, BLOCK_SPECS, source_id=1, sink_id=6, channel=0)
        np.testing.assert_allclose(result["freq_resp"], 1, atol=1e-9)
        self.assertAlmostEqual(result["D"], 1)
        self.assertEqual(len(result["zeros"]), 0)  # Hidden state is not a transfer zero.
        self.assertEqual(result["sink"]["channel"], 0)
        with self.assertRaises(ValueError):
            analyze_model(data, BLOCK_SPECS, channel=2)
        with self.assertRaises(ValueError):
            analyze_model(data, BLOCK_SPECS, source_id=999)

    def test_second_order_filter_and_strictly_proper_zero(self):
        result = transfer("[1 3]", "[1 2 4]")
        w = result["omega"]
        np.testing.assert_allclose(result["freq_resp"], (1j * w + 3) / ((1j * w) ** 2 + 2j * w + 4), atol=2e-10)
        np.testing.assert_allclose(result["zeros"], [-3], atol=1e-8)
        np.testing.assert_allclose(np.sort_complex(result["poles"]), [-1 - math.sqrt(3) * 1j, -1 + math.sqrt(3) * 1j], atol=1e-8)
        np.testing.assert_allclose(result["numerator"], [1, 3], atol=1e-8)

    def test_feedthrough_zero_static_gain_and_csv_sink(self):
        result = transfer("[1 3]", "[1 2]")
        self.assertAlmostEqual(result["D"], 1)
        np.testing.assert_allclose(result["zeros"], [-3], atol=1e-8)
        data = serial_document(("Constant", {"value": "4"}), ("Gain", {"gain": "2"}),
                               ("To CSV", {"filename": "analysis-must-not-write.csv"}))
        result = analyze_model(data, BLOCK_SPECS)
        np.testing.assert_allclose(result["freq_resp"], 2, atol=1e-9)
        self.assertEqual(len(result["poles"]), 0)
        self.assertEqual(result["operating_point"]["input"], 4)
        self.assertFalse((ROOT / "analysis-must-not-write.csv").exists())

    def test_margin_crossovers_have_independent_formula(self):
        w = np.logspace(-3, 3, 10000)
        H = 10 / (1j * w * (1 + 1j * w))
        result = crossing_margins(w, H)
        expected_w = math.sqrt((math.sqrt(401) - 1) / 2)
        expected_pm = math.degrees(math.atan(1 / expected_w))
        self.assertAlmostEqual(result["w_gc"], expected_w, delta=1e-5)
        self.assertAlmostEqual(result["phase_margin_deg"], expected_pm, delta=1e-5)
        self.assertTrue(math.isnan(result["gain_margin_db"]))
        H = 10 / (1 + 1j * w) ** 3
        result = crossing_margins(w, H)
        self.assertAlmostEqual(result["w_pc"], math.sqrt(3), delta=1e-5)
        self.assertAlmostEqual(result["gain_margin_db"], 20 * math.log10(.8), delta=2e-5)
        self.assertIn("hypothetical", result["interpretation"])

    def test_nonlinear_constant_source_bias_and_second_source_selection(self):
        data = json.loads((ROOT / "examples/nonlinear_statespace.json").read_text())
        result = analyze_model(data, BLOCK_SPECS)
        w = result["omega"]
        # d[2*cos(a*b)+1]/da at a=2,b=3 is -6*sin(6).
        expected = -6 * math.sin(6) / (1j * w + 1) ** 2
        np.testing.assert_allclose(result["freq_resp"], expected, rtol=2e-8, atol=1e-9)
        self.assertEqual(result["operating_point"]["input"], 2)
        second = analyze_model(data, BLOCK_SPECS, source_id=14)
        np.testing.assert_allclose(second["freq_resp"], -4 * math.sin(6) / (1j * w + 1) ** 2, rtol=2e-8, atol=1e-9)
        self.assertTrue(any("not an equilibrium" in note for note in result["notes"]))

    def test_pade_delay_formula_and_discrete_refusal(self):
        data = serial_document(("Step", {"step_time": "0"}),
                               ("Unit Delay", {"sample_time": ".2"}), ("Scope", {}))
        result = analyze_model(data, BLOCK_SPECS)
        w = result["omega"]
        np.testing.assert_allclose(result["freq_resp"], (1 - .1j * w) / (1 + .1j * w), atol=1e-9)
        np.testing.assert_allclose(result["poles"], [-10], atol=1e-9)
        np.testing.assert_allclose(result["zeros"], [10], atol=1e-8)
        self.assertEqual(result["approximations"][0]["tau"], .2)
        self.assertTrue(any("not exact discrete" in note for note in result["notes"]))
        with self.assertRaisesRegex(ValueError, "Exact discrete"):
            analyze_model(data, BLOCK_SPECS, use_pade=False)
        zoh = serial_document(("Step", {}), ("Zero-Order Hold", {"sample_time": ".2"}), ("Scope", {}))
        result = analyze_model(zoh, BLOCK_SPECS)
        np.testing.assert_allclose(result["poles"], [-20], atol=1e-8)

    def test_shipped_hybrid_finite_and_labeled(self):
        data = json.loads((ROOT / "examples/hybrid_control_loop.json").read_text())
        result = analyze_model(data, BLOCK_SPECS)
        self.assertTrue(np.all(np.isfinite(result["freq_resp"])))
        self.assertTrue(np.all(np.isfinite(result["mag_db"])))
        self.assertEqual(len(result["approximations"]), 2)
        self.assertEqual(result["sink"]["channel"], 2)
        s = 1j * result["omega"]
        polynomial_response = np.polyval(result["numerator"], s) / np.polyval(result["denominator"], s)
        np.testing.assert_allclose(polynomial_response, result["freq_resp"], atol=5e-9)
        self.assertNotIn("Closed-Loop", result["margins"]["interpretation"])
        print(f"MEASUREMENT: shipped hybrid: {len(result['poles'])} state poles, {len(result['zeros'])} transfer zeros, {len(result['omega'])} finite frequency samples, two labeled Padé approximations.")

    def test_pade_algebraic_loop_is_rejected(self):
        data = serial_document(("Step", {}), ("Sum", {"signs": "+-"}),
                               ("Unit Delay", {"sample_time": ".2"}), ("Scope", {}))
        data["root"]["wires"].append({"from_block": 3, "from_port": 0, "to_block": 2, "to_port": 1})
        with self.assertRaisesRegex(ValueError, "introduces an algebraic loop"):
            analyze_model(data, BLOCK_SPECS)

    def test_invalid_operating_and_frequency_inputs(self):
        with self.assertRaises(ValueError):
            transfer("[1]", "[1 1]", operating_state=[math.nan])
        with self.assertRaises(ValueError):
            transfer("[1]", "[1 1]", omega=[1, 0])
        with self.assertRaisesRegex(ValueError, "singular"):
            transfer("[1]", "[1 0 1]", omega=[.5, 1, 2])

    def test_matrix_exponential_defective_system_and_short_horizon(self):
        result = transfer("[1]", "[1 2 1]", t_stop=8, dt=.02)
        expected = 1 - (1 + result["step_t"]) * np.exp(-result["step_t"])
        np.testing.assert_allclose(result["step_y"], expected, atol=2e-12)
        short = transfer("[1]", "[1 1]", t_stop=.1)
        self.assertTrue(math.isnan(short["step_metrics"]["rise_time"]))
        self.assertTrue(math.isnan(short["step_metrics"]["settling_time"]))

    def test_nondifferentiable_and_unstable_controls(self):
        data = serial_document(("Constant", {"value": "1"}),
                               ("Saturation", {"upper_limit": "1", "lower_limit": "-1"}), ("Scope", {}))
        with self.assertRaisesRegex(ValueError, "nondifferentiable"):
            analyze_model(data, BLOCK_SPECS)
        data["root"]["blocks"][0]["params"]["value"] = "2"
        result = analyze_model(data, BLOCK_SPECS)
        np.testing.assert_allclose(result["freq_resp"], 0, atol=1e-9)
        unstable = transfer("[1]", "[1 -2]")
        self.assertEqual(unstable["stability"], "unstable")
        self.assertTrue(math.isnan(unstable["step_metrics"]["settling_time"]))
        integrator = transfer("[1]", "[1 0]")
        self.assertEqual(integrator["stability"], "marginal")

    def test_bad_matrix_negative_control(self):
        correct = transfer("[2]", "[1 2]")
        bad = transfer("[2]", "[1 3]")
        with self.assertRaises(AssertionError):
            np.testing.assert_allclose(bad["A"], correct["A"], atol=1e-9)
        with self.assertRaises(AssertionError):
            np.testing.assert_allclose(bad["freq_resp"], 2 / (2 + 1j * bad["omega"]), atol=1e-9)
        print("NEGATIVE CONTROL: changed A=-3 is rejected by A=-2 and independent transfer checks.")


if __name__ == "__main__":
    if "--mutation-control" in sys.argv:
        sys.argv.remove("--mutation-control")
        real_analyze = linear_analysis.analyze_scene
        def mutant(*args, **kwargs):
            result = real_analyze(*args, **kwargs)
            result["A"] = result["A"] + np.eye(len(result["A"]))
            return result
        linear_analysis.analyze_scene = mutant
    unittest.main(verbosity=2)
