"""Native Qt acceptance workflows for the three sourced internet examples.

Only file-dialog path selection is mocked. Simulations, plot construction,
document handlers, parameter application and export writers remain real.
"""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
(ROOT/".tmp").mkdir(exist_ok=True)
# Keep child Octave working directories in this task's writable workspace.
os.environ["TEMP"] = os.environ["TMP"] = str(ROOT/".tmp")
tempfile.tempdir = str(ROOT/".tmp")
import numpy as np
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QFont, QFontMetricsF
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton
from octalink_gui import OctaLinkMainWindow, BLOCK_SPECS
from mvp_model import validate_document

APP = QApplication.instance() or QApplication([])
NAMES = ("dc_motor", "cruise_pi", "van_der_pol")


def pump_until(predicate, timeout=45, detail="Qt operation"):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        QTest.qWait(10)
    if not predicate():
        raise AssertionError(f"{detail} timed out after {timeout}s")
    APP.processEvents()


def scopes(window):
    blocks, _ = window.sim_engine.flatten_hierarchy(window.root_scene)
    return [b for b in blocks if b.block_type == "Scope"]


def close_window(window):
    if window.worker:
        window.stop_simulation()
        pump_until(lambda: window.worker is None, detail="worker cleanup")
    window.saved_document = window.serialize_model()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    APP.processEvents()


def run_via_button(window, backend="python", timeout=45):
    window.ribbon.setCurrentIndex(0)
    window.backend_combo.setCurrentIndex(window.backend_combo.findData(backend))
    processes = []
    real_popen = subprocess.Popen
    log_start = len(window.diagnostics.toPlainText())
    def observed_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process
    with patch("octave_backend.subprocess.Popen", side_effect=observed_popen):
        QTest.mouseClick(window.run_button, Qt.MouseButton.LeftButton)
        if window.worker is None:
            raise AssertionError("Run did not launch worker: " + window.diagnostics.toPlainText())
        pump_until(lambda: window.worker is None, timeout, "simulation completion")
    new_log = window.diagnostics.toPlainText()[log_start:]
    if not all(len(b.scope_t) for b in scopes(window)) or "Simulation complete." not in new_log:
        raise AssertionError("No complete scope data: " + window.diagnostics.toPlainText())
    if backend == "octave":
        assert len(processes) == 1, f"Expected one genuine Octave process, got {len(processes)}"
        assert processes[0].poll() == 0, "Octave process did not exit successfully"
    assert all(p.poll() is not None for p in processes), "Simulation leaked a process"
    assert window.view.isEnabled() and window.run_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert "Simulation complete." in new_log
    check_plot_data(window)
    return {b.block_id: (np.asarray(b.scope_t).copy(), np.asarray(b.scope_y).copy(), list(b.scope_labels))
            for b in scopes(window)}


def check_plot_data(window):
    sinks = scopes(window)
    assert len(window.scope_windows) == len(sinks), "Wrong number of scope dialogs"
    for sink, dialog in zip(sinks, window.scope_windows):
        axes = dialog.canvas.figure.axes
        assert len(axes) == 1
        lines = axes[0].lines
        values = np.asarray(sink.scope_y)
        assert len(lines) == values.shape[1] == len(sink.scope_labels)
        for ch, line in enumerate(lines):
            np.testing.assert_array_equal(line.get_xdata(), sink.scope_t)
            np.testing.assert_array_equal(line.get_ydata(), values[:, ch])
            assert line.get_label() == sink.scope_labels[ch]
        assert axes[0].get_xlabel() == "Time (s)"
        assert axes[0].get_title() == sink.params["title"]


def check_reference(name, traces):
    # Independent analytical/adaptive Octave ode45 references live beside this suite.
    from test_internet_mwes import reference_trace
    times = next(iter(traces.values()))[0]
    reference = reference_trace(name, times)
    offset = 0
    expected_scopes = {}
    for sink_id in sorted(traces):
        width = traces[sink_id][1].shape[1]
        expected = reference[:, offset:offset+width]
        offset += width
        np.testing.assert_allclose(traces[sink_id][1], expected, rtol=0, atol=2e-6,
                                   err_msg=f"{name} scope {sink_id} independent full trace")
        expected_scopes[sink_id] = expected
    return expected_scopes


def diagram_geometry(scene, curved):
    metrics = QFontMetricsF(QFont("Segoe UI", 8))
    for wire in scene.wires:
        path = wire.path()
        points = [path.elementAt(i) for i in range(path.elementCount())]
        assert points, "Empty wire path"
        for point, port in ((points[0], wire.start_port), (points[-1], wire.end_port)):
            assert abs(point.x-port.scene_pos().x()) < 1e-9
            assert abs(point.y-port.scene_pos().y()) < 1e-9
        if curved:
            assert any(p.isCurveTo() for p in points), "Curved wire contains no cubic segment"
        else:
            assert not any(p.isCurveTo() for p in points)
            assert all(a.x == b.x or a.y == b.y for a, b in zip(points, points[1:])), "Diagonal orthogonal wire"
    for index, block in enumerate(scene.blocks):
        label = block.name_label_rect()
        assert label.width() >= metrics.horizontalAdvance(block.name), f"Clipped name: {block.name}"
        assert block.boundingRect().contains(label), f"Name outside declared item bounds: {block.name}"
        body = QRectF(block.pos().x(), block.pos().y(), block.width, block.height)
        for other in scene.blocks[index+1:]:
            other_body = QRectF(other.pos().x(), other.pos().y(), other.width, other.height)
            assert not body.intersects(other_body), f"Overlapping bodies: {block.name}, {other.name}"


class InternetEditorTests(unittest.TestCase):
    def setUp(self):
        (ROOT/".tmp").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/".tmp")
        self.window = OctaLinkMainWindow()
        self.window.resize(1500, 950)
        self.window.show()
        APP.processEvents()
        self.window.finish_layout()

    def tearDown(self):
        close_window(self.window)
        self.tmp.cleanup()

    def open_example(self, name):
        w = self.window
        w.saved_document = w.serialize_model()
        path = ROOT/"examples"/f"mwe_{name}.json"
        with patch("mvp_editor.QFileDialog.getOpenFileName", return_value=(str(path), "")) as choice:
            w.actions_map["Open"].trigger()
            choice.assert_called_once()
        APP.processEvents()
        self.assertEqual(w.file_path, path.resolve())
        self.assertTrue(w.check_model(), w.diagnostics.toPlainText())

    def apply_gain(self, block_id, value):
        w = self.window
        w.current_scene.clearSelection()
        block = next(b for b in w.current_scene.blocks if b.block_id == block_id)
        block.setSelected(True)
        APP.processEvents()
        edit = w.property_edits["gain"]
        edit.selectAll()
        QTest.keyClicks(edit, str(value))
        button = next(b for b in w.property_host.findChildren(QPushButton) if b.text() == "Apply" and b.isVisible())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        APP.processEvents()

    def test_all_examples_run_in_both_engines_and_plots_match_full_traces(self):
        from octave_backend import discover_octave
        self.assertIsNotNone(discover_octave(), "Genuine Octave required; no backend substitution")
        for name in NAMES:
            with self.subTest(example=name):
                self.open_example(name)
                python = run_via_button(self.window, "python")
                expected = check_reference(name, python)
                octave = run_via_button(self.window, "octave")
                check_reference(name, octave)
                for sink in python:
                    np.testing.assert_allclose(octave[sink][1], python[sink][1], rtol=0, atol=1e-9)
                # A known corrupt trace must fail the same numeric comparator.
                sink = next(iter(expected))
                with self.assertRaises(AssertionError):
                    np.testing.assert_allclose(python[sink][1]+1, expected[sink], rtol=0, atol=2e-6)
                print(f"UI TRACE OK: {name}; python+octave; samples={len(python[sink][0])}; scopes={len(python)}; corrupt trace rejected", flush=True)

    def test_mu_property_apply_undo_redo_invalid_control_and_recovery(self):
        self.open_example("van_der_pol")
        w = self.window
        original = run_via_button(w)[10][1]
        self.apply_gain(7, "0")
        harmonic = run_via_button(w)[10]
        expected = np.column_stack((2*np.cos(harmonic[0]), -2*np.sin(harmonic[0])))
        np.testing.assert_allclose(harmonic[1], expected, rtol=0, atol=1e-7)
        self.assertGreater(float(np.max(np.abs(original-expected))), .1)
        w.actions_map["Undo"].trigger()
        np.testing.assert_allclose(run_via_button(w)[10][1], original, rtol=0, atol=1e-12)
        w.actions_map["Redo"].trigger()
        np.testing.assert_allclose(run_via_button(w)[10][1], expected, rtol=0, atol=1e-7)
        before = w.serialize_model()
        self.apply_gain(7, "not_a_number")
        self.assertEqual(w.serialize_model(), before, "Invalid Apply mutated document")
        self.assertIn("Error:", w.diagnostics.toPlainText())
        self.apply_gain(7, "0")
        np.testing.assert_allclose(run_via_button(w, "octave")[10][1], expected, rtol=0, atol=1e-7)
        print("UI MU OK: full harmonic trace; undo/redo numerics; invalid Apply rejected; Octave recovery", flush=True)

    def test_cruise_native_subsystem_edit_style_save_reopen_copy(self):
        self.open_example("cruise_pi")
        w = self.window
        baseline = run_via_button(w)[9][1]
        vehicle = next(b for b in w.root_scene.blocks if b.block_type == "Subsystem")
        w.fit_diagram()
        point = w.view.mapFromScene(vehicle.pos()+QPointF(vehicle.width/2, vehicle.height/2))
        QTest.mouseDClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        APP.processEvents()
        self.assertIs(w.current_scene, vehicle.sub_scene, "Canvas double click did not enter subsystem")
        self.apply_gain(106, "100")
        w.set_curved_connections(False)
        QTest.mouseClick(w.up_btn, Qt.MouseButton.LeftButton)
        self.assertIs(w.current_scene, w.root_scene)
        w.set_curved_connections(True)
        edited = w.serialize_model()
        path = Path(self.tmp.name)/"cruise-styles.json"
        with patch("mvp_editor.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            w.actions_map["Save As"].trigger()
        self.assertEqual(json.loads(path.read_text()), edited)
        with patch("mvp_editor.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            w.actions_map["Open"].trigger()
        self.assertEqual(w.serialize_model(), edited)
        child = next(b for b in w.root_scene.blocks if b.block_type == "Subsystem")
        self.assertEqual(w.root_scene.connection_style, "curved")
        self.assertEqual(child.sub_scene.connection_style, "orthogonal")
        changed = run_via_button(w, "octave")[9][1]
        self.assertGreater(float(np.max(np.abs(changed[:, 1]-baseline[:, 1]))), .1)
        # Reverse the styles and repeat actual Save As/Open handlers as well.
        w.set_curved_connections(False)
        w.open_subsystem_scene(child.sub_scene)
        w.set_curved_connections(True)
        QTest.mouseClick(w.up_btn, Qt.MouseButton.LeftButton)
        reverse = w.serialize_model()
        path = Path(self.tmp.name)/"cruise-reverse-styles.json"
        with patch("mvp_editor.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            w.actions_map["Save As"].trigger()
        with patch("mvp_editor.QFileDialog.getOpenFileName", return_value=(str(path), "")):
            w.actions_map["Open"].trigger()
        self.assertEqual(w.serialize_model(), reverse)
        child = next(b for b in w.root_scene.blocks if b.block_type == "Subsystem")
        self.assertEqual(w.root_scene.connection_style, "orthogonal")
        self.assertEqual(child.sub_scene.connection_style, "curved")
        w.root_scene.clearSelection()
        child.setSelected(True)
        w.actions_map["Copy"].trigger()
        w.actions_map["Paste"].trigger()
        copies = [b for b in w.root_scene.blocks if b.block_type == "Subsystem"]
        self.assertEqual(len(copies), 2)
        validate_document(w.serialize_model(), BLOCK_SPECS)
        self.assertEqual(len(copies[0].sub_scene.wires), len(copies[1].sub_scene.wires))
        ids = [[b.block_id for b in c.sub_scene.blocks] for c in copies]
        self.assertFalse(set(ids[0]) & set(ids[1]))
        def topology(scene):
            ids = {b.block_id: index for index, b in enumerate(scene.blocks)}
            return sorted((ids[a.start_port.parent_block.block_id], a.start_port.index,
                           ids[a.end_port.parent_block.block_id], a.end_port.index) for a in scene.wires)
        self.assertEqual(topology(copies[0].sub_scene), topology(copies[1].sub_scene))
        print("UI CRUISE OK: canvas child edit changed simulation; independent styles saved; copy topology and IDs", flush=True)

    def test_motor_create_subsystem_undo_redo_preserves_response(self):
        self.open_example("dc_motor")
        w = self.window
        baseline = run_via_button(w)[14][1]
        w.root_scene.clearSelection()
        for block in w.root_scene.blocks:
            block.setSelected(2 <= block.block_id <= 12)
        w.actions_map["Subsystem"].trigger()
        self.assertEqual(sum(b.block_type == "Subsystem" for b in w.root_scene.blocks), 1)
        np.testing.assert_allclose(run_via_button(w, "octave")[14][1], baseline, rtol=0, atol=1e-10)
        w.actions_map["Undo"].trigger()
        self.assertFalse(any(b.block_type == "Subsystem" for b in w.root_scene.blocks))
        np.testing.assert_allclose(run_via_button(w)[14][1], baseline, rtol=0, atol=1e-12)
        w.actions_map["Redo"].trigger()
        self.assertTrue(any(b.block_type == "Subsystem" for b in w.root_scene.blocks))
        np.testing.assert_allclose(run_via_button(w)[14][1], baseline, rtol=0, atol=1e-12)
        print("UI MOTOR OK: create subsystem and undo/redo preserve every sample", flush=True)

    def test_real_csv_m_c_export_handlers_and_invalid_open_recovery(self):
        self.open_example("cruise_pi")
        w = self.window
        traces = run_via_button(w, "octave")
        for sink in scopes(w):
            w.root_scene.clearSelection()
            sink.setSelected(True)
            path = Path(self.tmp.name)/f"scope-{sink.block_id}.csv"
            with patch("mvp_editor.QFileDialog.getSaveFileName", return_value=(str(path), "")):
                w.export_scope_csv()
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0], ["time"]+sink.scope_labels)
            np.testing.assert_array_equal(np.asarray(rows[1:], float), np.column_stack((sink.scope_t, sink.scope_y)))
        for handler, suffix in ((w.on_export_m_clicked, ".m"), (w.on_export_c_clicked, ".c")):
            path = Path(self.tmp.name)/("cruise_export"+suffix)
            with patch("mvp_editor.QFileDialog.getSaveFileName", return_value=(str(path), "")):
                handler()
            self.assertGreater(path.stat().st_size, 500)
            content = path.read_text()
            self.assertIn("function" if suffix == ".m" else "OctaLink_Step", content)
            if suffix == ".c":
                self.assertIn("OctaLink_Init", path.with_suffix(".h").read_text())
        before = w.serialize_model()
        bad = Path(self.tmp.name)/"invalid.json"
        bad.write_text('{"version":"4.0","root":', encoding="utf-8")
        w.saved_document = before
        with patch("mvp_editor.QFileDialog.getOpenFileName", return_value=(str(bad), "")):
            w.actions_map["Open"].trigger()
        self.assertEqual(w.serialize_model(), before)
        self.assertIn("Could not open model", w.diagnostics.toPlainText())
        recovered = run_via_button(w, "octave")
        for sink in traces:
            np.testing.assert_array_equal(recovered[sink][1], traces[sink][1])
        print("UI EXPORT OK: both scope CSV all rows exact; real .m/.c/.h; malformed open preserved model and rerun", flush=True)

    def test_both_wire_styles_attach_before_after_actual_block_drag(self):
        for name in NAMES:
            self.open_example(name)
            w = self.window
            for curved in (False, True):
                w.set_curved_connections(curved)
                w.fit_diagram()
                APP.processEvents()
                diagram_geometry(w.root_scene, curved)
                if name == NAMES[0] and not curved:
                    # Prove the body-overlap instrument rejects an actual bad scene.
                    first, second = w.root_scene.blocks[:2]
                    original_position = first.pos()
                    first.setPos(second.pos())
                    with self.assertRaisesRegex(AssertionError, "Overlapping bodies"):
                        diagram_geometry(w.root_scene, curved)
                    first.setPos(original_position)
                    diagram_geometry(w.root_scene, curved)
                block = next(b for b in w.root_scene.blocks if b.block_type == "Gain")
                before = block.pos()
                point = w.view.mapFromScene(block.pos()+QPointF(block.width/2, block.height/2))
                QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
                QTest.mouseMove(w.view.viewport(), point+QPoint(0, 24), delay=20)
                QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=point+QPoint(0, 24))
                APP.processEvents()
                self.assertNotEqual(block.pos(), before, "Native drag did not move block")
                diagram_geometry(w.root_scene, curved)
                w.actions_map["Undo"].trigger()
                diagram_geometry(w.root_scene, curved)
            print(f"UI GEOMETRY OK: {name}; 2 styles; attached paths; actual drag/undo; zero overlapping bodies", flush=True)

    def test_genuine_octave_cancel_keeps_complete_results_and_recovers(self):
        self.open_example("van_der_pol")
        w = self.window
        baseline = run_via_button(w, "octave")[10][1]
        w.stop_time_edit.setText("20")
        w.dt_edit.setText("0.001")
        processes = []
        original = subprocess.Popen
        def capture(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        beats = []
        timer = QTimer()
        timer.timeout.connect(lambda: beats.append(True))
        timer.start(10)
        try:
            with patch("octave_backend.subprocess.Popen", side_effect=capture):
                QTest.mouseClick(w.run_button, Qt.MouseButton.LeftButton)
                pump_until(lambda: bool(processes), detail="Octave launch for cancellation")
                QTest.mouseClick(w.stop_button, Qt.MouseButton.LeftButton)
                pump_until(lambda: w.worker is None, timeout=15, detail="Octave cancellation")
        finally:
            timer.stop()
        self.assertTrue(beats, "GUI event loop stopped during Octave work")
        self.assertTrue(processes and all(p.poll() is not None for p in processes), "Cancelled Octave process leaked")
        np.testing.assert_array_equal(scopes(w)[0].scope_y, baseline)
        self.assertIn("Simulation stopped", w.diagnostics.toPlainText())
        w.stop_time_edit.setText("10")
        w.dt_edit.setText("0.01")
        check_reference("van_der_pol", run_via_button(w, "octave"))
        print("UI CANCEL OK: genuine Octave terminated; GUI heartbeat; complete results preserved; rerun", flush=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
