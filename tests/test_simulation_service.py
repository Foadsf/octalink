"""Checks of persisted backend selection and failure transparency."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from octalink_gui import BLOCK_SPECS
from mvp_model import read_document, validate_document
from simulation_service import simulate_document

ROOT = Path(__file__).resolve().parents[1]


class SimulationServiceTests(unittest.TestCase):
    def setUp(self):
        self.data = read_document(ROOT/"examples"/"first_order_feedback.json", BLOCK_SPECS)

    def test_original_version_three_examples_load_and_simulate(self):
        for name in ("hybrid_control_loop.json", "nonlinear_statespace.json"):
            with self.subTest(name=name):
                data = read_document(ROOT/"examples"/name, BLOCK_SPECS)
                self.assertEqual(data["version"], "3.0")
                data["stop_time"] = ".1"
                self.assertTrue(simulate_document(data, BLOCK_SPECS, backend="python"))

    def test_explicit_backend_overrides_saved_choice(self):
        self.data["backend"] = "octave"
        with patch("octave_backend.run_octave_simulation", side_effect=AssertionError("wrong engine")):
            result = simulate_document(self.data, BLOCK_SPECS, backend="python")
        values = next(iter(result.values()))
        self.assertAlmostEqual(values[1][-1][1], 1-__import__("math").exp(-4), places=7)

    def test_octave_failure_never_silently_falls_back(self):
        self.data["backend"] = "octave"
        with patch("octave_backend.run_octave_simulation", side_effect=RuntimeError("actual Octave failure")):
            with self.assertRaisesRegex(RuntimeError, "actual Octave failure"):
                simulate_document(self.data, BLOCK_SPECS)

    def test_invalid_backend_is_rejected(self):
        self.data["backend"] = "unsupported"
        with self.assertRaisesRegex(ValueError, "backend"):
            validate_document(self.data, BLOCK_SPECS)
