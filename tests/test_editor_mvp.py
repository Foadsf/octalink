"""MVP document and native Qt workflow acceptance tests."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt, QPoint, QPointF, QTimer, QCoreApplication, QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton
from octalink_gui import OctaLinkMainWindow, BLOCK_SPECS, BlockItem
from mvp_model import read_document, save_document, validate_document, detached_graph

APP = QApplication.instance() or QApplication([])


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.window = OctaLinkMainWindow()
        self.window.show()
        APP.processEvents()
        self.window.finish_layout()

    def tearDown(self):
        w = self.window
        if w.worker:
            w.stop_simulation()
            w.worker.wait(5000)
            APP.processEvents()
        w.saved_document = w.serialize_model()
        w.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def test_default_is_checked_analytic_example_and_light_editor(self):
        w = self.window
        self.assertEqual(len(w.root_scene.blocks), 6)
        self.assertTrue(w.check_model())
        self.assertEqual([w.ribbon.tabText(i) for i in range(w.ribbon.count())],
                         ["Simulation", "Modeling", "Format", "Analysis", "Export"])
        self.assertEqual(w.library_dock.windowTitle(), "Library Browser")

    def test_library_search_double_click_insertion_undo_redo(self):
        w = self.window
        QTest.keyClicks(w.library_search, "Gain")
        APP.processEvents()
        category = w.lib_tree.topLevelItem(1)
        gain = next(category.child(i) for i in range(category.childCount()) if category.child(i).text(0) == "Gain")
        self.assertFalse(gain.isHidden())
        self.assertTrue(category.child(0).isHidden())
        position = w.lib_tree.visualItemRect(gain).center()
        count = len(w.root_scene.blocks)
        QTest.mouseClick(w.lib_tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
        QTest.mouseDClick(w.lib_tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
        APP.processEvents()
        self.assertEqual(len(w.root_scene.blocks), count+1)
        w.on_undo_clicked()
        self.assertEqual(len(w.root_scene.blocks), count)
        w.on_redo_clicked()
        self.assertEqual(len(w.root_scene.blocks), count+1)

    def test_property_apply_changes_parameter_and_undo_restores_it(self):
        w = self.window
        gain = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
        gain.setSelected(True)
        APP.processEvents()
        w.property_edits["gain"].setText("3")
        button = next(b for b in w.property_host.findChildren(QPushButton) if b.text() == "Apply")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(gain.params["gain"], "3")
        w.on_undo_clicked()
        gain = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
        self.assertEqual(gain.params["gain"], "2")

    def test_invalid_dynamic_port_edit_preserves_document(self):
        w = self.window
        mux = next(b for b in w.root_scene.blocks if b.block_type == "Mux")
        mux.setSelected(True)
        APP.processEvents()
        before = w.serialize_model()
        w.property_edits["inputs"].setText("garbage")
        w.apply_properties()
        self.assertEqual(w.serialize_model(), before)
        self.assertIn("Error:", w.diagnostics.toPlainText())

    def test_parameter_validation_is_transactional_in_an_unwired_draft(self):
        w = self.window
        w.new_model()
        cases = (
            ("Gain", "gain", "not_a_number"),
            ("Unit Delay", "sample_time", "0"),
            ("Saturation", "lower_limit", "20"),
            ("Transfer Fcn", "numerator", "[1, 0, 0, 0]"),
            ("State-Space", "B", "[1, 2, 3]"),
            ("Octave Function", "expression", "__import__('os')"),
        )
        for kind, key, value in cases:
            with self.subTest(kind=kind):
                block = w.insert_block(kind, QPointF(200, 200))
                before = w.serialize_model()
                undo_count = len(w.undo_stack)
                bad = dict(block.params, **{key: value})
                self.assertFalse(w.apply_block_parameters(block, block.name, bad))
                self.assertEqual(w.serialize_model(), before)
                self.assertEqual(len(w.undo_stack), undo_count)
                self.assertIn("Error:", w.diagnostics.toPlainText())
        gain = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
        self.assertTrue(w.apply_block_parameters(gain, "Valid draft gain", {"gain": "2*pi"}))
        self.assertEqual(gain.params["gain"], "2*pi")
        self.assertFalse(w.check_model(), "An unwired draft must still fail Run validation")

    def test_save_round_trip_and_invalid_open_preserves_live_model(self):
        w = self.window
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/".tmp") as directory:
            path = Path(directory)/"model.json"
            self.assertTrue(w.save_model(path=path))
            original = w.serialize_model()
            w.insert_block("Constant", QPointF(150, 500))
            w.load_model_from_file(path)
            self.assertEqual(w.serialize_model(), original)
            self.assertFalse(w.undo_stack)
            bad = copy.deepcopy(original)
            bad["root"]["wires"][0]["from_block"] = 999999
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing block"):
                w.load_model_from_file(path)
            self.assertEqual(w.serialize_model(), original)

    def test_failed_atomic_replace_preserves_existing_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/".tmp") as directory:
            path = Path(directory)/"model.json"
            original = self.window.serialize_model()
            save_document(path, original, BLOCK_SPECS)
            old_bytes = path.read_bytes()
            changed = copy.deepcopy(original)
            changed["stop_time"] = "20"
            with patch("mvp_model.os.replace", side_effect=OSError("disk unavailable")):
                with self.assertRaisesRegex(OSError, "disk unavailable"):
                    save_document(path, changed, BLOCK_SPECS)
            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(list(Path(directory).glob(".octalink-*.tmp")), [])
            self.assertEqual(read_document(path, BLOCK_SPECS), original)

    def test_copy_paste_subsystem_and_internal_connections(self):
        w = self.window
        selected = [b for b in w.root_scene.blocks if b.block_type in ("Gain", "Integrator")]
        for block in selected:
            block.setSelected(True)
        w.on_create_subsystem_clicked()
        subsystem = next(b for b in w.root_scene.blocks if b.block_type == "Subsystem")
        w.current_scene.clearSelection()
        subsystem.setSelected(True)
        w.copy_selection()
        w.paste_selection()
        self.assertEqual(sum(b.block_type == "Subsystem" for b in w.root_scene.blocks), 2)
        validate_document(w.serialize_model(), BLOCK_SPECS)
        children = [b.sub_scene for b in w.root_scene.blocks if b.block_type == "Subsystem"]
        self.assertEqual(len(children[0].blocks), len(children[1].blocks))
        self.assertEqual(len(children[0].wires), len(children[1].wires))
        w.on_undo_clicked()
        self.assertEqual(sum(b.block_type == "Subsystem" for b in w.root_scene.blocks), 1)

    def test_block_drag_is_undoable(self):
        w = self.window
        gain = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
        old_pos = gain.pos()
        start = w.view.mapFromScene(gain.pos()+QPointF(gain.width/2, gain.height/2))
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.view.viewport(), start+QPoint(50, 50), delay=20)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start+QPoint(50, 50))
        APP.processEvents()
        self.assertNotEqual(gain.pos(), old_pos)
        w.on_undo_clicked()
        restored = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
        self.assertEqual(restored.pos(), old_pos)

    def test_wires_are_orthogonal_and_stay_attached_after_move(self):
        w = self.window
        gain = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
        gain.setPos(gain.pos()+QPointF(15, 70))
        for wire in w.root_scene.wires:
            path = wire.path()
            elements = [path.elementAt(i) for i in range(path.elementCount())]
            self.assertEqual((elements[0].x, elements[0].y),
                             (wire.start_port.scene_pos().x(), wire.start_port.scene_pos().y()))
            self.assertEqual((elements[-1].x, elements[-1].y),
                             (wire.end_port.scene_pos().x(), wire.end_port.scene_pos().y()))
            for a, b in zip(elements, elements[1:]):
                self.assertTrue(a.x == b.x or a.y == b.y)

    def test_connection_toggle_redraws_and_undo_redo_preserve_topology(self):
        w = self.window
        before = w.serialize_model()
        w.ribbon.setCurrentIndex(2)
        QTest.mouseClick(w.connection_style_button, Qt.MouseButton.LeftButton)
        self.assertTrue(w.curved_connections_action.isChecked())
        self.assertEqual(w.root_scene.connection_style, "curved")
        self.assertEqual(w.serialize_model()["root"]["wires"], before["root"]["wires"])
        self.assertNotEqual(w.serialize_model(), w.saved_document)
        gain = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
        gain.setY(gain.pos().y()+40)
        for wire in w.root_scene.wires:
            path = wire.path()
            self.assertTrue(any(path.elementAt(i).isCurveTo() for i in range(path.elementCount())))
            end = path.elementAt(path.elementCount()-1)
            self.assertEqual((end.x, end.y), (wire.end_port.scene_pos().x(), wire.end_port.scene_pos().y()))
        w.on_undo_clicked()
        self.assertEqual(w.serialize_model(), before)
        self.assertFalse(w.curved_connections_action.isChecked())
        w.on_redo_clicked()
        self.assertTrue(w.curved_connections_action.isChecked())
        self.assertEqual(w.root_scene.connection_style, "curved")

    def test_diagram_styles_are_independent_and_round_trip_with_subsystems(self):
        w = self.window
        for block in w.root_scene.blocks:
            if block.block_type in ("Gain", "Integrator"):
                block.setSelected(True)
        w.on_create_subsystem_clicked()
        sub = next(b for b in w.root_scene.blocks if b.block_type == "Subsystem")
        w.curved_connections_action.trigger()
        w.open_subsystem_scene(sub.sub_scene)
        self.assertFalse(w.curved_connections_action.isChecked())
        w.curved_connections_action.trigger()
        self.assertEqual(sub.sub_scene.connection_style, "curved")
        w.curved_connections_action.trigger()
        self.assertEqual(sub.sub_scene.connection_style, "orthogonal")
        self.assertEqual(w.root_scene.connection_style, "curved")
        w.on_navigate_up_clicked()
        self.assertTrue(w.curved_connections_action.isChecked())
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/".tmp") as directory:
            path = Path(directory)/"styles.json"
            self.assertTrue(w.save_model(path=path))
            saved = w.serialize_model()
            w.set_curved_connections(False)
            w.load_model_from_file(path)
            self.assertEqual(w.serialize_model(), saved)
        sub = next(b for b in w.root_scene.blocks if b.block_type == "Subsystem")
        w.open_subsystem_scene(sub.sub_scene)
        self.assertFalse(w.curved_connections_action.isChecked())
        for wire in sub.sub_scene.wires:
            self.assertFalse(any(wire.path().elementAt(i).isCurveTo() for i in range(wire.path().elementCount())))

    def test_legacy_style_default_and_invalid_style_control(self):
        w = self.window
        legacy = w.serialize_model()
        legacy["root"].pop("connection_style")
        w.set_curved_connections(True)
        w._restore_from_dict(legacy)
        self.assertEqual(w.root_scene.connection_style, "orthogonal")
        self.assertFalse(w.curved_connections_action.isChecked())
        validate_document(legacy, BLOCK_SPECS)
        bad = copy.deepcopy(legacy)
        bad["root"]["connection_style"] = "unknown"
        with self.assertRaisesRegex(ValueError, "connection style"):
            validate_document(bad, BLOCK_SPECS)

    def test_backend_preference_persists_and_missing_octave_preserves_model(self):
        w = self.window
        w.backend_combo.setCurrentIndex(w.backend_combo.findData("octave"))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/".tmp") as directory:
            path = Path(directory)/"backend.json"
            self.assertTrue(w.save_model(path=path))
            w.backend_combo.setCurrentIndex(w.backend_combo.findData("python"))
            w.load_model_from_file(path)
            self.assertEqual(w.backend_combo.currentData(), "octave")
        w.octave_executable = str(Path(__file__).parent/"does-not-exist.exe")
        before = w.serialize_model()
        w.on_run_clicked()
        self.assertIsNone(w.worker)
        self.assertEqual(w.serialize_model(), before)
        self.assertIn("GNU Octave was not found", w.diagnostics.toPlainText())

    def test_build_and_wire_new_model_using_canvas_gestures(self):
        w = self.window
        w.new_model()
        source = w.insert_block("Constant", QPointF(180, 180))
        integrator = w.insert_block("Integrator", QPointF(420, 180))
        sink = w.insert_block("Scope", QPointF(700, 180))
        w.current_scene.clearSelection()
        w.finish_layout()
        APP.processEvents()
        for output, input_port in ((source.out_ports[0], integrator.in_ports[0]),
                                   (integrator.out_ports[0], sink.in_ports[0])):
            start = w.view.mapFromScene(output.scene_pos())
            end = w.view.mapFromScene(input_port.scene_pos())
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(w.view.viewport(), end, delay=15)
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(w.root_scene.wires), 2)
        self.assertTrue(w.check_model())
        w.stop_time_edit.setText("1")
        w.open_scopes = lambda: None
        QTest.mouseClick(w.run_button, Qt.MouseButton.LeftButton)
        self.wait_for_worker()
        self.assertAlmostEqual(sink.scope_y[-1][0], 1., places=12)

    def wait_for_worker(self, limit=8):
        started = time.monotonic()
        while self.window.worker is not None and time.monotonic()-started < limit:
            APP.processEvents()
            QTest.qWait(10)
        self.assertIsNone(self.window.worker, "Worker did not terminate")

    def test_background_run_returns_analytic_results_and_restores_editor(self):
        w = self.window
        w.open_scopes = lambda: None
        w.stop_time_edit.setText("2")
        QTest.mouseClick(w.run_button, Qt.MouseButton.LeftButton)
        self.assertIsNotNone(w.worker)
        self.assertFalse(w.view.isEnabled())
        self.wait_for_worker()
        scope = next(b for b in w.root_scene.blocks if b.block_type == "Scope")
        self.assertEqual(scope.scope_t[-1], 2)
        self.assertAlmostEqual(scope.scope_y[-1][1], 1-__import__("math").exp(-2), places=6)
        self.assertTrue(w.view.isEnabled())
        self.assertFalse(w.stop_button.isEnabled())

    def test_cancel_is_responsive_and_does_not_publish_partial_results(self):
        w = self.window
        w.open_scopes = lambda: None
        w.stop_time_edit.setText("20")
        w.dt_edit.setText("0.0001")
        beats = []
        timer = QTimer()
        timer.timeout.connect(lambda: beats.append(True))
        timer.start(10)
        w.on_run_clicked()
        self.assertIsNotNone(w.worker)
        QTimer.singleShot(35, w.stop_simulation)
        self.wait_for_worker()
        timer.stop()
        self.assertTrue(beats, "Qt event loop did not run while simulating")
        scope = next(b for b in w.root_scene.blocks if b.block_type == "Scope")
        self.assertEqual(len(scope.scope_t), 0)
        self.assertIn("Simulation stopped", w.diagnostics.toPlainText())

    def test_model_negative_controls_and_positive_round_trip(self):
        good = self.window.serialize_model()
        validate_document(good, BLOCK_SPECS)
        for mutation in ("duplicate", "port", "nan", "version"):
            bad = copy.deepcopy(good)
            if mutation == "duplicate":
                bad["root"]["blocks"][1]["id"] = bad["root"]["blocks"][0]["id"]
            elif mutation == "port":
                bad["root"]["wires"][0]["to_port"] = 99
            elif mutation == "nan":
                bad["dt"] = "nan"
            else:
                bad["version"] = "999"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_document(bad, BLOCK_SPECS)
        scene = detached_graph(good, BLOCK_SPECS)
        self.assertEqual(len(scene.blocks), len(good["root"]["blocks"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
