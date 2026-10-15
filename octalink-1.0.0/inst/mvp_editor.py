"""First-MVP editor layered on the original native Qt application."""
import copy
import csv
import json
import math
import os
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QPointF, QRectF, QMimeData, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import (QAction, QActionGroup, QKeySequence, QDrag, QPainterPath, QPainterPathStroker,
                         QColor, QFont, QFontDatabase)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QPushButton, QDockWidget, QTreeWidget, QTreeWidgetItem, QTabWidget,
    QToolBar, QToolButton, QGroupBox, QDialog, QListWidget, QListWidgetItem,
    QDialogButtonBox, QFileDialog, QMessageBox, QPlainTextEdit, QProgressBar,
    QScrollArea, QSplitter, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
)
from mvp_model import read_document, save_document, validate_document, detached_graph, DOCUMENT_VERSION
from octalink_engine_support import SOLVER_LABELS, port_counts, resolve_variables
from simulation_service import simulate_document


STYLE = """
QMainWindow, QDialog { background: #f5f5f5; color: #242424; }
QWidget { font-family: 'Segoe UI'; font-size: 12px; }
QMenuBar, QToolBar { background: #fafafa; border-bottom: 1px solid #d4d4d4; }
QToolBar { spacing: 4px; padding: 3px; }
QTabWidget::pane { border: 0; border-bottom: 1px solid #ccc; background: #f5f5f5; }
QTabBar::tab { padding: 8px 19px; background: #eee; border: 0; }
QTabBar::tab:selected { background: #fff; color: #0067b1; border-bottom: 3px solid #0078d4; }
QGroupBox { border: 0; border-right: 1px solid #d3d3d3; margin-top: 0; }
QToolButton { padding: 5px 9px; border: 1px solid transparent; border-radius: 2px; }
QToolButton:hover { background: #e5f1fb; border: 1px solid #a3c9e7; }
QToolButton:checked { background: #d8eaf9; border: 1px solid #80b8de; }
QToolButton:disabled { color: #999; }
QPushButton { padding: 6px 10px; border: 1px solid #c5c5c5; background: #fafafa; border-radius: 2px; }
QPushButton:hover { background: #e5f1fb; border-color: #80b8de; }
QLineEdit { padding: 5px; background: white; border: 1px solid #b9b9b9; border-radius: 1px; }
QLineEdit:focus { border-color: #0078d4; }
QDockWidget { font-weight: 600; }
QDockWidget::title { background: #eaeaea; padding: 7px; border-bottom: 1px solid #ccc; }
QTreeWidget, QListWidget, QPlainTextEdit { background: white; border: 1px solid #dedede; }
QTreeWidget::item { padding: 5px 2px; }
QListWidget::item { padding: 4px 4px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #d8eaf9; color: #222; }
QStatusBar { background: #f0f0f0; border-top: 1px solid #d2d2d2; }
QProgressBar { border: 1px solid #ccc; background: white; text-align: center; }
QProgressBar::chunk { background: #4b9bd5; }
"""


class LibraryTree(QTreeWidget):
    def startDrag(self, supported_actions):
        item = self.currentItem()
        kind = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not kind:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-octalink-block", kind.encode())
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class SimulationWorker(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, document, module, parent=None, octave_executable=None):
        super().__init__(parent)
        self.document, self.module = document, module
        self.cancel_event = threading.Event()
        self.octave_executable = octave_executable

    def run(self):
        try:
            results = simulate_document(self.document, self.module.BLOCK_SPECS,
                                        executable=self.octave_executable,
                                        cancel_check=self.cancel_event.is_set,
                                        progress_callback=lambda value: self.progress.emit(int(value * 100)))
            if not self.cancel_event.is_set():
                self.result.emit(results)
        except Exception as exc:
            if not self.cancel_event.is_set():
                self.failed.emit(str(exc))


def install_canvas_behaviour(module):
    """Keep prototype item types and undo semantics while adding editor gestures."""
    view = module.SimCanvasView
    original_press = module.BlockItem.mousePressEvent
    original_release = module.BlockItem.mouseReleaseEvent
    curved_path = module.WireItem.update_path

    def press(block, event):
        block._mvp_start_position = block.pos()
        # Capture every selected block before the drag, including multi-selection.
        if block.parent_window and not block.parent_window._restoring_snapshot:
            block._mvp_drag_document = block.parent_window.serialize_model()
        original_press(block, event)

    def release(block, event):
        original_release(block, event)
        window = block.parent_window
        before = getattr(block, "_mvp_drag_document", None)
        if window and before is not None and block.pos() != getattr(block, "_mvp_start_position", block.pos()):
            window.undo_stack.append(json.dumps(before))
            window.undo_stack[:] = window.undo_stack[-40:]
            window.redo_stack.clear()
        block._mvp_drag_document = None

    module.BlockItem.mousePressEvent = press
    module.BlockItem.mouseReleaseEvent = release

    def accept_parameters(dialog):
        parent = dialog.block.parent_window
        params = {key: edit.text().strip() for key, edit in dialog.inputs.items()}
        if parent and hasattr(parent, "apply_block_parameters"):
            if parent.apply_block_parameters(dialog.block, dialog.name_edit.text().strip(), params):
                QDialog.accept(dialog)
        else:
            dialog.block.name = dialog.name_edit.text().strip() or dialog.block.name
            dialog.block.params = params
            dialog.block.rebuild_ports()
            QDialog.accept(dialog)

    module.ParamDialog.accept = accept_parameters

    def drag_enter(self, event):
        if event.mimeData().hasFormat("application/x-octalink-block"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def drop(self, event):
        kind = bytes(event.mimeData().data("application/x-octalink-block")).decode()
        if kind in module.BLOCK_SPECS:
            point = self.mapToScene(event.position().toPoint())
            self.scene().parent_window.insert_block(kind, point)
            event.acceptProposedAction()

    view.dragEnterEvent = drag_enter
    view.dragMoveEvent = drag_enter
    view.dropEvent = drop
    original_double = module.SimCanvasScene.mouseDoubleClickEvent

    def double_click(scene, event):
        item = scene.itemAt(event.scenePos(), scene.views()[0].transform()) if scene.views() else None
        if item is None and scene.parent_window:
            scene.parent_window.quick_insert(event.scenePos())
            event.accept()
        else:
            original_double(scene, event)

    module.SimCanvasScene.mouseDoubleClickEvent = double_click

    def orthogonal_path(wire):
        start = wire.start_port.scene_pos()
        end = wire.end_port.scene_pos() if wire.end_port else wire.temp_end_pos
        ds = -1 if wire.start_port.parent_block.flipped else 1
        de = 1 if wire.end_port and wire.end_port.parent_block.flipped else -1
        # Close forward-facing ports need shorter stubs; fixed 22-unit stubs
        # overlap across a narrow gap and incorrectly turn it into feedback.
        stub = 22
        if ds == -de and (end.x()-start.x()) * ds > 0:
            stub = min(stub, abs(end.x()-start.x())/3)
        a, b = QPointF(start.x() + ds * stub, start.y()), QPointF(end.x() + de * stub, end.y())
        obstacles = []
        # connect_ports constructs the path before adding the wire to the
        # scene; the source block already identifies the diagram's obstacles.
        scene = wire.scene() or wire.start_port.parent_block.scene()
        if scene:
            for block in getattr(scene, "blocks", []):
                if block not in (wire.start_port.parent_block, getattr(wire.end_port, "parent_block", None)):
                    obstacles.append((block.pos().x()-8, block.pos().y()-8,
                                      block.pos().x()+block.width+8, block.pos().y()+block.height+25))
        candidates = []
        if (b.x() - a.x()) * ds >= 0 and ds == -de:
            # Extra lanes just beside the stub let a signal step off a lane
            # another signal already uses.
            lanes_x = [(a.x()+b.x())/2, a.x(), b.x(), a.x()+ds*12, a.x()+ds*24, b.x()+de*12]
            for x in lanes_x + [x for rect in obstacles for x in (rect[0]-10, rect[2]+10)]:
                candidates.append([start, a, QPointF(x, a.y()), QPointF(x, b.y()), b, end])
        lanes = [min(a.y(), b.y())-60, max(a.y(), b.y())+75]
        lanes += [y for rect in obstacles for y in (rect[1]-15, rect[3]+15)]
        for y in lanes:
            candidates.append([start, a, QPointF(a.x(), y), QPointF(b.x(), y), b, end])

        # Segments of OTHER signals already drawn: running along one of them
        # makes two signals look connected. Branches of the same output may share.
        occupied = []
        if scene:
            for other in getattr(scene, "wires", []):
                if other is wire or other.start_port is wire.start_port:
                    continue
                path = other.path()
                if any(path.elementAt(i).isCurveTo() for i in range(path.elementCount())):
                    continue
                corners = [QPointF(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())]
                occupied += list(zip(corners, corners[1:]))

        def overlap(p, q):
            shared = 0.0
            for r, s in occupied:
                if abs(p.x()-q.x()) < .5 and abs(r.x()-s.x()) < .5 and abs(p.x()-r.x()) < 3:
                    shared += max(0.0, min(max(p.y(), q.y()), max(r.y(), s.y())) - max(min(p.y(), q.y()), min(r.y(), s.y())))
                elif abs(p.y()-q.y()) < .5 and abs(r.y()-s.y()) < .5 and abs(p.y()-r.y()) < 3:
                    shared += max(0.0, min(max(p.x(), q.x()), max(r.x(), s.x())) - max(min(p.x(), q.x()), min(r.x(), s.x())))
            return shared

        def cost(points):
            collisions, length, shared = 0, 0, 0.0
            for p, q in zip(points, points[1:]):
                length += abs(p.x()-q.x()) + abs(p.y()-q.y())
                shared += overlap(p, q)
                for left, top, right, bottom in obstacles:
                    if p.x() == q.x() and left < p.x() < right and max(p.y(), q.y()) > top and min(p.y(), q.y()) < bottom:
                        collisions += 1
                    if p.y() == q.y() and top < p.y() < bottom and max(p.x(), q.x()) > left and min(p.x(), q.x()) < right:
                        collisions += 1
            return collisions * 100000 + shared * 20 + length

        if (b.x() - a.x()) * ds < 0:
            # Returning feedback goes below the signal chain, matching the
            # familiar left-to-right forward / right-to-left feedback layout.
            below = [points for points in candidates if len(points) > 3 and points[2].y() > max(a.y(), b.y())]
            points = min(below or candidates, key=cost)
        else:
            points = min(candidates, key=cost)
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        wire.setPath(path)

    def update_wire_path(wire):
        # A new wire computes its path before addItem attaches it to the scene.
        scene = wire.scene() or wire.start_port.parent_block.scene()
        if getattr(scene, "connection_style", "orthogonal") == "curved":
            curved_path(wire)
            # Keep the prototype's smooth curves, but bow long branches around
            # the block chain instead of drawing through intermediate blocks.
            if scene and wire.end_port and scene.blocks:
                start, end = wire.start_port.scene_pos(), wire.end_port.scene_pos()
                ds = -1 if wire.start_port.parent_block.flipped else 1
                de = 1 if wire.end_port.parent_block.flipped else -1
                # A right-to-left wire into a port that faces back toward the
                # source (a flipped block) is a plain C-curve, not a bowed return.
                returning = (end.x()-start.x()) * ds < 0 and de == -ds
                crosses = any(
                    b not in (wire.start_port.parent_block, wire.end_port.parent_block)
                    and min(start.x(), end.x()) < b.pos().x()+b.width
                    and max(start.x(), end.x()) > b.pos().x()
                    and min(start.y(), end.y()) < b.pos().y()+b.height
                    and max(start.y(), end.y()) > b.pos().y()
                    for b in scene.blocks)
                if returning or crosses:
                    lane = (max(b.pos().y()+b.height for b in scene.blocks)+75 if returning
                            else min(b.pos().y() for b in scene.blocks)-55)
                    middle = QPointF((start.x()+end.x())/2, lane)
                    path = QPainterPath(start)
                    path.cubicTo(QPointF(start.x()+ds*45, start.y()), QPointF(start.x()+ds*45, lane), middle)
                    path.cubicTo(QPointF(end.x()+de*45, lane), QPointF(end.x()+de*45, end.y()), end)
                    wire.setPath(path)
                # A bowed cubic can intersect blocks outside the bounding box
                # between its endpoints. Check the actual open-path stroke;
                # QPainterPath.intersects alone would implicitly close/fill it.
                stroke = QPainterPathStroker()
                stroke.setWidth(2)
                obstacles = [QRectF(b.pos().x()-2, b.pos().y()-2, b.width+4, b.height+4)
                             for b in scene.blocks
                             if b not in (wire.start_port.parent_block, wire.end_port.parent_block)]
                def clear(path):
                    painted = stroke.createStroke(path)
                    return not any(painted.intersects(rect) for rect in obstacles)
                if not clear(wire.path()):
                    # Reuse the obstacle-aware route as a guide, rounding its
                    # corners while retaining the smooth connection option.
                    orthogonal_path(wire)
                    guide = wire.path()
                    points = []
                    for index in range(guide.elementCount()):
                        element = guide.elementAt(index)
                        point = QPointF(element.x, element.y)
                        if points and point == points[-1]:
                            continue
                        while len(points) >= 2:
                            a, b = points[-2], points[-1]
                            cross = (b.x()-a.x())*(point.y()-b.y())-(b.y()-a.y())*(point.x()-b.x())
                            dot = (b.x()-a.x())*(point.x()-b.x())+(b.y()-a.y())*(point.y()-b.y())
                            if abs(cross) > 1e-8 or dot < 0:
                                break
                            points.pop()
                        points.append(point)
                    for radius in (48, 24, 12, 6):
                        rounded = QPainterPath(points[0])
                        for previous, corner, following in zip(points, points[1:], points[2:]):
                            incoming = math.hypot(corner.x()-previous.x(), corner.y()-previous.y())
                            outgoing = math.hypot(following.x()-corner.x(), following.y()-corner.y())
                            distance = min(radius, incoming/2, outgoing/2)
                            entry = corner+(previous-corner)*(distance/incoming)
                            leave = corner+(following-corner)*(distance/outgoing)
                            rounded.lineTo(entry)
                            rounded.quadTo(corner, leave)
                        rounded.lineTo(points[-1])
                        if clear(rounded):
                            wire.setPath(rounded)
                            break
        else:
            orthogonal_path(wire)

    module.WireItem.update_path = update_wire_path


def create_mvp_window(base, module):
    install_canvas_behaviour(module)

    class MVPWindow(base):
        def _build_default_hybrid_model(self):
            # A small, analytically checkable starter: y' = 2 (r-y).
            scene = self.root_scene
            step = scene.add_sim_block("Step", 80, 200, name="Step", params={"step_time": "1"})
            summ = scene.add_sim_block("Sum", 250, 202, name="Sum", params={"signs": "+-"})
            gain = scene.add_sim_block("Gain", 390, 200, name="Gain", params={"gain": "2"})
            plant = scene.add_sim_block("Integrator", 550, 200, name="Integrator")
            mux = scene.add_sim_block("Mux", 750, 180, name="Signals", params={"inputs": "2"})
            scope = scene.add_sim_block("Scope", 855, 185, name="Scope", params={"title": "Reference and output"})
            scene.connect_ports(step.out_ports[0], summ.in_ports[0])
            scene.connect_ports(summ.out_ports[0], gain.in_ports[0])
            scene.connect_ports(gain.out_ports[0], plant.in_ports[0])
            scene.connect_ports(plant.out_ports[0], summ.in_ports[1])
            scene.connect_ports(step.out_ports[0], mux.in_ports[0])
            scene.connect_ports(plant.out_ports[0], mux.in_ports[1])
            scene.connect_ports(mux.out_ports[0], scope.in_ports[0])
            self.view.centerOn(510, 240)

        def __init__(self, initial_json=None):
            # Qt offscreen and minimal Linux installations may have no font
            # discovery. Matplotlib ships a redistributable DejaVu font.
            import matplotlib
            font_path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if "Segoe UI" in QFontDatabase.families():
                family = "Segoe UI"
                module.QApplication.instance().setFont(QFont(family, 9))
            elif font_id >= 0:
                family = QFontDatabase.applicationFontFamilies(font_id)[0]
                QFont.insertSubstitution("Segoe UI", family)
                QFont.insertSubstitution("Arial", family)
                module.QApplication.instance().setFont(QFont(family, 9))
            else:
                family = "Sans Serif"
            self.ui_font_family = family
            self.file_path = None
            self.saved_document = None
            self.worker = None
            self.octave_executable = None
            self.scope_windows = []
            self._clipboard = None
            self._properties_block = None
            self._last_csv = {}
            self.analysis_selection = None
            super().__init__(initial_json)
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.saved_document = self.serialize_model()
            self.resize(1440, 860)
            self.fit_diagram()
            self.refresh_document_ui()
            self.document_timer = QTimer(self)
            self.document_timer.timeout.connect(self.refresh_document_ui)
            self.document_timer.start(400)
            QTimer.singleShot(0, self.finish_layout)

        def finish_layout(self):
            self.resizeDocks([self.library_dock, self.properties_dock], [225, 260], Qt.Orientation.Horizontal)
            self.fit_diagram()

        def action(self, text, callback, shortcut=None):
            action = QAction(text, self)
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            self.addAction(action)
            return action

        def _setup_ui(self):
            self.setStyleSheet(STYLE.replace("'Segoe UI'", f"'{self.ui_font_family}'"))
            self.actions_map = {
                "New": self.action("New Model", self.new_model, "Ctrl+N"),
                "Open": self.action("Open...", self.on_load_json_clicked, "Ctrl+O"),
                "Save": self.action("Save", self.on_save_json_clicked, "Ctrl+S"),
                "Save As": self.action("Save As...", lambda: self.save_model(True), "Ctrl+Shift+S"),
                "Undo": self.action("Undo", self.on_undo_clicked, "Ctrl+Z"),
                "Redo": self.action("Redo", self.on_redo_clicked, "Ctrl+Y"),
                "Copy": self.action("Copy", self.copy_selection, "Ctrl+C"),
                "Paste": self.action("Paste", self.paste_selection, "Ctrl+V"),
                "Delete": self.action("Delete", self.delete_selection),
                "Flip": self.action("Flip Block", self.on_flip_selected_clicked, "Ctrl+I"),
                "Subsystem": self.action("Create Subsystem", self.on_create_subsystem_clicked, "Ctrl+G"),
                "Fit": self.action("Fit to View", self.fit_diagram, "Ctrl+0"),
                "Run": self.action("Run", self.on_run_clicked, "Ctrl+R"),
                "Check": self.action("Check Model", self.check_model, "Ctrl+D"),
                "Workspace": self.action("Model Workspace...", self.edit_model_workspace, "Ctrl+Shift+W"),
            }
            file_menu = self.menuBar().addMenu("File")
            for key in ("New", "Open", "Save", "Save As"):
                file_menu.addAction(self.actions_map[key])
            examples_menu = file_menu.addMenu("Examples")
            examples_dir = Path(__file__).parent / "examples"
            if not examples_dir.is_dir():
                examples_dir = Path(sys.prefix) / "share" / "octalink" / "examples"
            for path in sorted(examples_dir.glob("*.json")):
                examples_menu.addAction(path.stem.replace("_", " ").title(), lambda checked=False, p=path: self.open_document(p))
            file_menu.addSeparator()
            file_menu.addAction("Exit", self.close)
            edit = self.menuBar().addMenu("Edit")
            for key in ("Undo", "Redo", "Copy", "Paste", "Delete", "Flip", "Subsystem"):
                edit.addAction(self.actions_map[key])
            modeling_menu = self.menuBar().addMenu("Modeling")
            modeling_menu.addAction(self.actions_map["Workspace"])
            modeling_menu.addAction(self.actions_map["Check"])
            # Simulation menu: every run control is also a menu action, which
            # keyboard users and UI Automation can reach (the engine combo's
            # accessible value is read-only).
            simulation_menu = self.menuBar().addMenu("Simulation")
            simulation_menu.addAction(self.actions_map["Run"])
            self.stop_action = QAction("Stop", self)
            self.stop_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
            self.stop_action.triggered.connect(self.stop_simulation)
            self.stop_action.setEnabled(False)
            self.addAction(self.stop_action)
            simulation_menu.addAction(self.stop_action)
            simulation_menu.addAction(self.actions_map["Check"])
            engine_menu = simulation_menu.addMenu("Engine")
            self.engine_actions = QActionGroup(self)
            for label, value in (("Local Python", "python"), ("GNU Octave", "octave")):
                engine = QAction(label, self, checkable=True)
                engine.setData(value)
                engine.triggered.connect(lambda checked=False, v=value: self.backend_combo.setCurrentIndex(self.backend_combo.findData(v)))
                self.engine_actions.addAction(engine)
                engine_menu.addAction(engine)
                self.actions_map["Engine " + label] = engine
            solver_menu = simulation_menu.addMenu("Solver")
            self.solver_actions = QActionGroup(self)
            for value, label in SOLVER_LABELS.items():
                solver = QAction(label, self, checkable=True)
                solver.setData(value)
                solver.triggered.connect(lambda checked=False, v=value: self.solver_combo.setCurrentIndex(self.solver_combo.findData(v)))
                self.solver_actions.addAction(solver)
                solver_menu.addAction(solver)
                self.actions_map["Solver " + label] = solver
            view_menu = self.menuBar().addMenu("View")
            view_menu.addAction(self.actions_map["Fit"])
            self.curved_connections_action = self.action("Curved Connections", self.set_curved_connections)
            self.curved_connections_action.setCheckable(True)
            self.curved_connections_action.setToolTip("Toggle curved or orthogonal connections for this diagram only.")
            self.actions_map["Curved Connections"] = self.curved_connections_action
            view_menu.addAction(self.curved_connections_action)
            view_menu.addAction("Zoom In", lambda: self.view.scale(1.15, 1.15))
            view_menu.addAction("Zoom Out", lambda: self.view.scale(1/1.15, 1/1.15))
            help_menu = self.menuBar().addMenu("Help")
            help_menu.addAction("Editing Shortcuts", self.show_help)
            help_menu.addAction("About OctaLink", lambda: QMessageBox.about(self, "OctaLink MVP", "OctaLink MVP 0.1\nNative visual modeling for GNU Octave.\nFixed-step RK4 or implicit SDIRK4, algebraic-loop Newton,\nand discrete event scheduling.\nSimulink-inspired editor; independent implementation."))

            quick = QToolBar("Quick Access", self)
            quick.setMovable(False)
            for key in ("New", "Open", "Save", "Undo", "Redo"):
                quick.addAction(self.actions_map[key])
            self.addToolBar(quick)
            self.addToolBarBreak()
            ribbon_host = QToolBar("Toolstrip", self)
            ribbon_host.setMovable(False)
            self.ribbon = QTabWidget()
            self.ribbon.setFixedHeight(123)
            self.ribbon.setMinimumWidth(620)
            ribbon_host.addWidget(self.ribbon)
            self.addToolBar(ribbon_host)

            def tab(name):
                panel = QWidget()
                layout = QHBoxLayout(panel)
                layout.setContentsMargins(8, 4, 8, 2)
                self.ribbon.addTab(panel, name)
                return layout

            def group(layout, caption):
                host = QGroupBox()
                outer = QVBoxLayout(host)
                outer.setContentsMargins(9, 0, 12, 0)
                row = QHBoxLayout()
                outer.addLayout(row)
                label = QLabel(caption)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setStyleSheet("color: #666; font-size: 10px;")
                outer.addWidget(label)
                layout.addWidget(host)
                return row

            def tool(row, label, callback, icon=None):
                button = QToolButton()
                button.setText(label)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                button.setIconSize(QSize(24, 24))
                if icon:
                    button.setIcon(module.make_svg_icon(icon, 24))
                button.clicked.connect(callback)
                button.setMinimumHeight(50)
                row.addWidget(button)
                return button

            simulation = tab("Simulation")
            row = group(simulation, "Library")
            tool(row, "Library Browser", lambda: self.library_dock.setVisible(not self.library_dock.isVisible()), "cat_Sources")
            tool(row, "Check Model", self.check_model, "subsystem")
            row = group(simulation, "Simulation")
            self.run_button = tool(row, "Run", self.on_run_clicked, "run")
            self.stop_button = tool(row, "Stop", self.stop_simulation)
            self.stop_button.setStyleSheet("color: #b83030; font-weight: bold;")
            self.stop_button.setEnabled(False)
            row = group(simulation, "Solver Settings")
            timing = QFormLayout()
            self.stop_time_edit = QLineEdit("10.0")
            self.dt_edit = QLineEdit("0.01")
            self.stop_time_edit.setFixedWidth(80)
            self.dt_edit.setFixedWidth(80)
            timing.addRow("Stop time", self.stop_time_edit)
            timing.addRow("Fixed step", self.dt_edit)
            row.addLayout(timing)
            engines = QVBoxLayout()
            self.backend_combo = QComboBox()
            self.backend_combo.addItem("Local Python", "python")
            self.backend_combo.addItem("GNU Octave", "octave")
            self.backend_combo.setToolTip("Choose where this model's simulation executes.")
            # Accessible names/object names: screen readers and UI Automation
            # (appsurface/surfacekit) address these controls by name.
            self.backend_combo.setAccessibleName("Simulation engine")
            self.backend_combo.setObjectName("simulationEngine")
            def sync_engine_menu(_index=None):
                for engine in self.engine_actions.actions():
                    engine.setChecked(engine.data() == self.backend_combo.currentData())
            self.backend_combo.currentIndexChanged.connect(sync_engine_menu)
            sync_engine_menu()
            self.stop_time_edit.setObjectName("stopTime")
            self.dt_edit.setObjectName("fixedStep")
            engines.addWidget(self.backend_combo)
            # Fixed-step solver, saved in the model: explicit RK4, or implicit
            # SDIRK4 for stiff plants. Either engine runs either solver.
            self.solver_combo = QComboBox()
            for value, label in SOLVER_LABELS.items():
                self.solver_combo.addItem(label, value)
            self.solver_combo.setToolTip("Fixed-step solver. SDIRK4 is implicit (Newton on a numerical Jacobian) "
                                         "and allows large steps on stiff plants.")
            self.solver_combo.setAccessibleName("Solver")
            self.solver_combo.setObjectName("solver")

            def sync_solver_menu(_index=None):
                for solver in self.solver_actions.actions():
                    solver.setChecked(solver.data() == self.solver_combo.currentData())
            self.solver_combo.currentIndexChanged.connect(sync_solver_menu)
            sync_solver_menu()
            engines.addWidget(self.solver_combo)
            self.octave_settings_button = QPushButton("Octave Settings…")
            self.octave_settings_button.clicked.connect(self.configure_octave)
            engines.addWidget(self.octave_settings_button)
            row.addLayout(engines)
            row = group(simulation, "Results")
            tool(row, "Open Scopes", self.open_scopes, "cat_Sinks")
            tool(row, "Export CSV", self.export_scope_csv)
            simulation.addStretch()
            modeling = tab("Modeling")
            row = group(modeling, "Model")
            for key in ("New", "Open", "Save"):
                button = QToolButton()
                button.setDefaultAction(self.actions_map[key])
                row.addWidget(button)
            row = group(modeling, "Edit")
            for key in ("Undo", "Redo", "Copy", "Paste", "Delete"):
                button = QToolButton()
                button.setDefaultAction(self.actions_map[key])
                row.addWidget(button)
            row = group(modeling, "Components")
            tool(row, "Subsystem", self.on_create_subsystem_clicked, "subsystem")
            tool(row, "Flip", self.on_flip_selected_clicked, "flip")
            row = group(modeling, "Design Data")
            tool(row, "Model Workspace", self.edit_model_workspace, "m_code")
            modeling.addStretch()
            formatting = tab("Format")
            row = group(formatting, "Layout")
            tool(row, "Align Centers", lambda: self.align_selection(False))
            tool(row, "Align Middles", lambda: self.align_selection(True))
            tool(row, "Fit to View", self.fit_diagram)
            tool(row, "100%", lambda: self.view.resetTransform())
            row = group(formatting, "Connections")
            self.connection_style_button = QToolButton()
            self.connection_style_button.setDefaultAction(self.curved_connections_action)
            row.addWidget(self.connection_style_button)
            formatting.addStretch()
            analysis = tab("Analysis")
            row = group(analysis, "Linear Model Analysis")
            tool(row, "Linear Analysis", self.on_linear_analysis_clicked, "bode")
            row.addWidget(QLabel("Choose an input source and logged output.\nDiscrete delays use approximate Padé models."))
            analysis.addStretch()
            export = tab("Export")
            row = group(export, "Code Generation")
            tool(row, "Octave .m", self.on_export_m_clicked, "m_code")
            tool(row, "ANSI C", self.on_export_c_clicked, "c_code")
            row.addWidget(QLabel("Export a standalone model for GNU Octave or C99.\nValidate against the intended application before deployment."))
            export.addStretch()

            central = QWidget()
            layout = QVBoxLayout(central)
            layout.setContentsMargins(0, 0, 0, 0)
            navigation = QHBoxLayout()
            navigation.setContentsMargins(10, 5, 10, 5)
            self.up_btn = QPushButton("↑  Up")
            self.up_btn.clicked.connect(self.on_navigate_up_clicked)
            self.up_btn.setEnabled(False)
            navigation.addWidget(self.up_btn)
            self.breadcrumb_label = QLabel("Root")
            navigation.addWidget(self.breadcrumb_label)
            navigation.addStretch()
            self.model_caption = QLabel("untitled.octalink.json")
            self.model_caption.setStyleSheet("color: #666;")
            navigation.addWidget(self.model_caption)
            layout.addLayout(navigation)
            self.view = module.SimCanvasView(self.root_scene)
            self.view.setAcceptDrops(True)
            self.view.setBackgroundBrush(QColor("white"))
            layout.addWidget(self.view)
            self.setCentralWidget(central)

            self.library_dock = QDockWidget("Library Browser", self)
            self.library_dock.setObjectName("libraryBrowser")
            self.library_dock.setMinimumWidth(205)
            library_host = QWidget()
            lib_layout = QVBoxLayout(library_host)
            lib_layout.setContentsMargins(8, 8, 8, 8)
            self.library_search = QLineEdit()
            self.library_search.setPlaceholderText("Search blocks...")
            self.library_search.setAccessibleName("Search blocks")
            self.library_search.setObjectName("librarySearch")
            lib_layout.addWidget(self.library_search)
            self.lib_tree = LibraryTree()
            self.lib_tree.setAccessibleName("Block library")
            self.lib_tree.setHeaderLabel("Blocks")   # hidden headers shift Qt's accessible rows
            self.lib_tree.setDragEnabled(True)
            self.lib_tree.setIndentation(14)
            categories = {}
            for kind, spec in module.BLOCK_SPECS.items():
                category = spec["category"]
                if category not in categories:
                    parent = QTreeWidgetItem(self.lib_tree, [category])
                    parent.setExpanded(True)
                    categories[category] = parent
                child = QTreeWidgetItem(categories[category], [kind])
                child.setData(0, Qt.ItemDataRole.UserRole, kind)
                child.setToolTip(0, "Drag onto the canvas or double-click to insert.")
            self.lib_tree.itemDoubleClicked.connect(lambda item, col: self.insert_block(item.data(0, Qt.ItemDataRole.UserRole)) if item.data(0, Qt.ItemDataRole.UserRole) else None)
            self.library_search.textChanged.connect(self.filter_library)
            lib_layout.addWidget(self.lib_tree)
            hint = QLabel("Drag blocks to the canvas.\nDouble-click empty space to search.")
            hint.setStyleSheet("color: #666; font-size: 11px;")
            lib_layout.addWidget(hint)
            self.library_dock.setWidget(library_host)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)

            self.properties_dock = QDockWidget("Property Inspector", self)
            self.properties_dock.setObjectName("propertyInspector")
            self.properties_dock.setMinimumWidth(240)
            self.property_host = QWidget()
            self.properties_layout = QVBoxLayout(self.property_host)
            self.properties_layout.setContentsMargins(10, 10, 10, 10)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.property_host)
            self.properties_dock.setWidget(scroll)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)
            self.root_scene.selectionChanged.connect(self.show_properties)
            self.show_properties()

            # Model Browser: every block of the hierarchy as an accessible list.
            # Blocks on the QGraphicsView canvas are invisible to UI Automation
            # and screen readers; selecting a row selects the block on the canvas
            # (entering its subsystem). Rows are named by path ("House › Troom"),
            # so names are unique. A flat list is deliberate: Qt's tree
            # accessibility selects the wrong row around expanded parents (measured).
            self.browser_dock = QDockWidget("Model Browser", self)
            self.browser_dock.setObjectName("modelBrowser")
            self.model_tree = QListWidget()
            self.model_tree.setObjectName("modelTree")
            self.model_tree.setAccessibleName("Model hierarchy")
            self.model_tree.itemSelectionChanged.connect(self.select_from_browser)
            self.model_tree.itemDoubleClicked.connect(self.open_from_browser)
            browser_host = QWidget()
            browser_layout = QVBoxLayout(browser_host)
            browser_layout.setContentsMargins(8, 6, 8, 6)
            self.browser_filter = QLineEdit()
            self.browser_filter.setPlaceholderText("Filter blocks...")
            self.browser_filter.setAccessibleName("Filter model blocks")
            self.browser_filter.setObjectName("modelFilter")
            self.browser_filter.textChanged.connect(self.filter_model_browser)
            browser_layout.addWidget(self.browser_filter)
            browser_layout.addWidget(self.model_tree)
            self.browser_dock.setWidget(browser_host)
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.browser_dock)
            self.splitDockWidget(self.library_dock, self.browser_dock, Qt.Orientation.Vertical)
            self._browser_signature = None

            self.diagnostics_dock = QDockWidget("Diagnostic Viewer", self)
            self.diagnostics_dock.setObjectName("diagnosticViewer")
            self.diagnostics = QPlainTextEdit()
            self.diagnostics.setReadOnly(True)
            self.diagnostics.setAccessibleName("Diagnostics")
            self.diagnostics.setObjectName("diagnostics")
            self.diagnostics.setMaximumBlockCount(200)
            self.diagnostics.setMaximumHeight(110)
            self.diagnostics.appendPlainText("Ready. Edit the example or create a new model. Run uses the local Python engine.")
            self.diagnostics_dock.setWidget(self.diagnostics)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.diagnostics_dock)
            for dock in (self.library_dock, self.browser_dock, self.properties_dock, self.diagnostics_dock):
                view_menu.addAction(dock.toggleViewAction())
            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setFixedWidth(130)
            self.progress.hide()
            self.statusBar().addPermanentWidget(self.progress)
            self.zoom_label = QLabel("100%")
            self.statusBar().addPermanentWidget(self.zoom_label)
            self.statusBar().showMessage("Ready  |  Wheel: zoom  •  Middle-drag: pan  •  Double-click: parameters")
            self.resizeDocks([self.library_dock, self.properties_dock], [225, 260], Qt.Orientation.Horizontal)

        def _setup_shortcuts(self):
            # QAction shortcuts include menu feedback and avoid duplicate QShortcuts.
            pass

        def filter_library(self, text):
            text = text.casefold().strip()
            for i in range(self.lib_tree.topLevelItemCount()):
                category = self.lib_tree.topLevelItem(i)
                visible = False
                for j in range(category.childCount()):
                    item = category.child(j)
                    matched = text in (item.text(0) + " " + category.text(0)).casefold()
                    item.setHidden(not matched)
                    visible |= matched
                category.setHidden(not visible)

        def insert_block(self, kind, point=None):
            if self.worker or kind not in module.BLOCK_SPECS:
                return
            if point is None:
                point = self.view.mapToScene(self.view.viewport().rect().center())
            self.push_undo_snapshot()
            self.current_scene.clearSelection()
            block = self.current_scene.add_sim_block(kind, round(point.x()/10)*10, round(point.y()/10)*10)
            block.setSelected(True)
            self.view.setFocus()
            return block

        def quick_insert(self, point):
            dialog = QDialog(self)
            dialog.setWindowTitle("Insert Block")
            dialog.resize(320, 350)
            layout = QVBoxLayout(dialog)
            search = QLineEdit()
            search.setPlaceholderText("Type a block name...")
            choices = QListWidget()
            choices.addItems(list(module.BLOCK_SPECS))
            layout.addWidget(search)
            layout.addWidget(choices)
            def filter_choices(text):
                first = None
                for i in range(choices.count()):
                    item = choices.item(i)
                    item.setHidden(text.casefold() not in item.text().casefold())
                    if not item.isHidden() and first is None:
                        first = item
                choices.setCurrentItem(first)
            search.textChanged.connect(filter_choices)
            filter_choices("")
            choices.itemDoubleClicked.connect(dialog.accept)
            search.returnPressed.connect(dialog.accept)
            search.setFocus()
            if dialog.exec() == QDialog.DialogCode.Accepted and choices.currentItem():
                self.insert_block(choices.currentItem().text(), point)

        def show_properties(self):
            while self.properties_layout.count():
                item = self.properties_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    while item.layout().count():
                        child = item.layout().takeAt(0)
                        if child.widget():
                            child.widget().deleteLater()
            selected = [b for b in self.current_scene.selectedItems() if isinstance(b, module.BlockItem)]
            self._properties_block = selected[0] if len(selected) == 1 else None
            if self._properties_block is None:
                label = QLabel("Select a block to inspect\nand edit its parameters.")
                label.setWordWrap(True)
                self.properties_layout.addWidget(label)
                self.properties_layout.addStretch()
                return
            block = self._properties_block
            self.properties_layout.addWidget(QLabel(block.block_type))
            form = QFormLayout()
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            self.property_name = QLineEdit(block.name)
            self.property_name.setAccessibleName("Block name")
            form.addRow("Name", self.property_name)
            self.property_edits = {}
            for key, value in block.params.items():
                edit = QLineEdit(str(value))
                edit.setToolTip(key)
                edit.setAccessibleName(key.replace("_", " ").title())
                form.addRow(key.replace("_", " ").title(), edit)
                self.property_edits[key] = edit
            self.properties_layout.addLayout(form)
            apply = QPushButton("Apply")
            apply.clicked.connect(self.apply_properties)
            self.properties_layout.addWidget(apply)
            self.properties_layout.addStretch()

        def apply_properties(self):
            block = self._properties_block
            if block is None or self.worker:
                return
            name = self.property_name.text().strip()
            params = {key: edit.text().strip() for key, edit in self.property_edits.items()}
            self.apply_block_parameters(block, name, params)

        def apply_block_parameters(self, block, name, params):
            if self.worker:
                return False
            before = self.serialize_model()
            candidate = copy.deepcopy(before)
            def amend(scene):
                for entry in scene["blocks"]:
                    if entry["id"] == block.block_id:
                        entry.update(name=name, params=params)
                        # Remove wires to ports that disappear, consistently with Qt rebuild_ports.
                        ni, no = len(block.in_ports), len(block.out_ports)
                        if block.block_type in ("Mux", "Demux", "Sum", "Product"):
                            ni, no = port_counts(block.block_type, dict(block.spec["params"], **params), block.spec)
                        scene["wires"] = [w for w in scene["wires"] if not ((w["to_block"] == block.block_id and w["to_port"] >= ni) or (w["from_block"] == block.block_id and w["from_port"] >= no))]
                    if "sub_scene" in entry:
                        amend(entry["sub_scene"])
            try:
                if not name:
                    raise ValueError("Block name cannot be empty.")
                self.sim_engine.set_variables(candidate.get("variables"))
                amend(candidate["root"])
                validate_document(candidate, module.BLOCK_SPECS)
                # Validate the edited block with the compiler's semantic gate.
                # Draft models may still contain deliberately unwired blocks.
                def find_edited(scene):
                    for entry in scene.blocks:
                        if entry.block_id == block.block_id:
                            return entry
                        if entry.sub_scene is not None:
                            found = find_edited(entry.sub_scene)
                            if found is not None:
                                return found
                    return None
                edited = find_edited(detached_graph(candidate, module.BLOCK_SPECS))
                self.sim_engine.prepare_blocks([edited])
            except (ValueError, TypeError) as exc:
                self.report_error(str(exc))
                return False
            self.push_undo_snapshot()
            block.prepareGeometryChange()
            block.name, block.params = name, params
            block.rebuild_ports()
            if block.scene() and block.scene().owner_subsystem:
                block.scene().owner_subsystem.rebuild_ports()
            block.update()
            self.log(f"Updated {name}.")
            return True

        def open_subsystem_scene(self, scene):
            super().open_subsystem_scene(scene)
            self.curved_connections_action.setChecked(getattr(scene, "connection_style", "orthogonal") == "curved")
            try:
                scene.selectionChanged.disconnect(self.show_properties)
            except TypeError:
                pass
            scene.selectionChanged.connect(self.show_properties)
            self.show_properties()

        def set_curved_connections(self, curved):
            style = "curved" if curved else "orthogonal"
            if self.worker:
                self.curved_connections_action.setChecked(getattr(self.current_scene, "connection_style", "orthogonal") == "curved")
                return
            if style != getattr(self.current_scene, "connection_style", "orthogonal"):
                self.push_undo_snapshot()
                self.current_scene.connection_style = style
                for wire in self.current_scene.wires:
                    wire.update_path()
                if self.current_scene.active_wire:
                    self.current_scene.active_wire.update_path()
                self.log(f"This diagram now uses {style} connections.")
            self.curved_connections_action.setChecked(curved)
            self.refresh_document_ui()

        def fit_diagram(self):
            if self.current_scene.blocks:
                rect = self.current_scene.itemsBoundingRect().adjusted(-65, -65, 65, 65)
                self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
                if self.view.transform().m11() > 1.25:
                    self.view.resetTransform()
                    self.view.scale(1.25, 1.25)
                    self.view.centerOn(rect.center())
            else:
                self.view.resetTransform()
                self.view.centerOn(450, 300)

        def align_selection(self, horizontal):
            blocks = [b for b in self.current_scene.selectedItems() if isinstance(b, module.BlockItem)]
            if len(blocks) < 2:
                return
            self.push_undo_snapshot()
            center = sum(b.pos().y()+b.height/2 if horizontal else b.pos().x()+b.width/2 for b in blocks)/len(blocks)
            for block in blocks:
                if horizontal:
                    block.setY(center-block.height/2)
                else:
                    block.setX(center-block.width/2)

        def copy_selection(self):
            ids = {b.block_id for b in self.current_scene.selectedItems() if isinstance(b, module.BlockItem)}
            if not ids:
                return
            data = self._serialize_scene(self.current_scene)
            self._clipboard = copy.deepcopy({"blocks": [b for b in data["blocks"] if b["id"] in ids],
                                             "wires": [w for w in data["wires"] if w["from_block"] in ids and w["to_block"] in ids]})

        def paste_selection(self):
            if not self._clipboard or self.worker:
                return
            data = copy.deepcopy(self._clipboard)
            def reidentify(scene):
                mapping = {}
                for entry in scene["blocks"]:
                    mapping[entry["id"]] = module.BlockItem._id_counter
                    entry["id"] = module.BlockItem._id_counter
                    module.BlockItem._id_counter += 1
                    entry["name"] += "_copy"
                    entry["x"] += 35
                    entry["y"] += 35
                    if "sub_scene" in entry:
                        reidentify(entry["sub_scene"])
                for wire in scene["wires"]:
                    wire["from_block"] = mapping[wire["from_block"]]
                    wire["to_block"] = mapping[wire["to_block"]]
            self.push_undo_snapshot()
            reidentify(data)
            self.current_scene.clearSelection()
            before = set(self.current_scene.blocks)
            self._deserialize_scene(self.current_scene, data)
            for block in set(self.current_scene.blocks)-before:
                block.setSelected(True)

        def delete_selection(self):
            from PyQt6.QtGui import QKeyEvent
            if not self.worker:
                self.current_scene.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))

        def serialize_model(self):
            data = super().serialize_model()
            data["version"] = DOCUMENT_VERSION
            data["backend"] = self.backend_combo.currentData()
            data["solver"] = self.solver_combo.currentData()
            variables = getattr(self.root_scene, "variables", None)
            if variables:
                data["variables"] = copy.deepcopy(variables)
            # Saving must not discard the document's description/provenance.
            data.update(copy.deepcopy(getattr(self, "document_metadata", {})))
            return data

        def _serialize_scene(self, scene):
            data = super()._serialize_scene(scene)
            data["connection_style"] = getattr(scene, "connection_style", "orthogonal")
            return data

        def _deserialize_scene(self, scene, data):
            # Copy/paste adds a partial diagram: preserve its destination style.
            scene.connection_style = data.get("connection_style", getattr(scene, "connection_style", "orthogonal"))
            super()._deserialize_scene(scene, data)

        def _restore_from_dict(self, data):
            # Older model files have no style and retain the MVP's original look.
            self.root_scene.connection_style = "orthogonal"
            self.root_scene.variables = copy.deepcopy(data.get("variables", {}))
            self.document_metadata = {key: data[key] for key in ("description", "provenance") if key in data}
            super()._restore_from_dict(data)
            self.backend_combo.setCurrentIndex(self.backend_combo.findData(data.get("backend", "python")))
            self.solver_combo.setCurrentIndex(self.solver_combo.findData(data.get("solver", "rk4")))
            self.curved_connections_action.setChecked(self.root_scene.connection_style == "curved")

        def _find_block(self, block_id, scene=None):
            """(scene, block) for a document ID anywhere in the hierarchy."""
            scene = scene or self.root_scene
            for block in scene.blocks:
                if block.block_id == block_id:
                    return scene, block
                if block.block_type == "Subsystem" and block.sub_scene is not None:
                    found = self._find_block(block_id, block.sub_scene)
                    if found:
                        return found
            return None

        def refresh_model_browser(self):
            def signature(scene):
                return tuple((b.block_id, b.name, b.block_type,
                              signature(b.sub_scene) if b.block_type == "Subsystem" and b.sub_scene else ())
                             for b in scene.blocks)
            current = (str(self.file_path), signature(self.root_scene))
            if current == self._browser_signature:
                return
            self._browser_signature = current
            self.model_tree.blockSignals(True)
            self.model_tree.clear()

            def fill(scene, trail):
                for block in sorted(scene.blocks, key=lambda b: (b.pos().x(), b.pos().y())):
                    path = trail + (block.name,)
                    item = QListWidgetItem(" › ".join(path))
                    item.setData(Qt.ItemDataRole.UserRole, block.block_id)
                    item.setToolTip(f"{block.block_type} [{block.block_id}]")
                    self.model_tree.addItem(item)
                    if block.block_type == "Subsystem" and block.sub_scene is not None:
                        fill(block.sub_scene, path)
            fill(self.root_scene, ())
            self.model_tree.blockSignals(False)
            self.filter_model_browser(self.browser_filter.text())

        def filter_model_browser(self, text):
            """Show blocks whose path matches (a subsystem name lists its contents)."""
            needle = text.casefold().strip()
            for i in range(self.model_tree.count()):
                item = self.model_tree.item(i)
                item.setHidden(bool(needle) and needle not in item.text().casefold())

        def select_from_browser(self):
            items = self.model_tree.selectedItems()
            block_id = items[0].data(Qt.ItemDataRole.UserRole) if items else None
            found = self._find_block(block_id) if block_id is not None else None
            if not found or self.worker:
                return
            scene, block = found
            if scene is not self.current_scene:
                self.open_subsystem_scene(scene)
            self.current_scene.clearSelection()
            block.setSelected(True)
            self.view.centerOn(block)

        def open_from_browser(self, item):
            found = self._find_block(item.data(Qt.ItemDataRole.UserRole))
            if found and found[1].block_type == "Subsystem" and not self.worker:
                self.open_subsystem_scene(found[1].sub_scene)
                self.fit_diagram()

        def refresh_document_ui(self):
            self.refresh_model_browser()
            dirty = self.saved_document is not None and self.serialize_model() != self.saved_document
            name = self.file_path.name if self.file_path else "untitled.octalink.json"
            self.setWindowTitle(f"{'*' if dirty else ''}{name} — OctaLink MVP")
            self.model_caption.setText(name + ("  •  modified" if dirty else ""))
            self.zoom_label.setText(f"{self.view.transform().m11()*100:.0f}%")
            self.actions_map["Undo"].setEnabled(bool(self.undo_stack) and not self.worker)
            self.actions_map["Redo"].setEnabled(bool(self.redo_stack) and not self.worker)

        def confirm_discard(self):
            if self.worker:
                self.log("Stop the running simulation before changing models.")
                return False
            if self.saved_document is None or self.serialize_model() == self.saved_document:
                return True
            answer = QMessageBox.question(self, "Unsaved Model", "Save changes to this model?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Save:
                return self.save_model()
            return answer == QMessageBox.StandardButton.Discard

        def new_model(self):
            if not self.confirm_discard():
                return
            self._restore_from_dict({"version": "4.0", "stop_time": "10", "dt": "0.01", "root": {"blocks": [], "wires": []}})
            self.file_path = None
            self.saved_document = self.serialize_model()
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.fit_diagram()

        def load_model_from_file(self, path):
            # Validate the whole document before replacing any live diagram.
            data = read_document(path, module.BLOCK_SPECS)
            self._restore_from_dict(data)
            self.file_path = Path(path).resolve()
            self.saved_document = self.serialize_model()
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.log(f"Opened {self.file_path.name}.")

        def open_document(self, path):
            if not self.confirm_discard():
                return
            try:
                self.load_model_from_file(path)
                self.fit_diagram()
            except Exception as exc:
                self.report_error(f"Could not open model: {exc}")

        def on_load_json_clicked(self):
            path, _ = QFileDialog.getOpenFileName(self, "Open Model", "", "OctaLink models (*.json)")
            if path:
                self.open_document(path)

        def save_model(self, save_as=False, path=None):
            if self.worker:
                return False
            if path is None:
                path = self.file_path
                if save_as or path is None:
                    path, _ = QFileDialog.getSaveFileName(self, "Save Model", str(path or "untitled.octalink.json"), "OctaLink models (*.json)")
                    if not path:
                        return False
            try:
                self.file_path = save_document(path, self.serialize_model(), module.BLOCK_SPECS)
                self.saved_document = self.serialize_model()
                self.refresh_document_ui()
                self.log(f"Saved {self.file_path.name}.")
                return True
            except Exception as exc:
                self.report_error(f"Could not save model: {exc}")
                return False

        def on_save_json_clicked(self):
            return self.save_model()

        def log(self, message):
            self.diagnostics.appendPlainText(message)
            self.statusBar().showMessage(message)

        def report_error(self, message):
            self.diagnostics_dock.show()
            self.log("Error: " + message)

        def configure_octave(self):
            from octave_backend import discover_octave
            dialog = QDialog(self)
            dialog.setWindowTitle("GNU Octave Settings")
            dialog.resize(540, 160)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("Choose octave-cli (recommended) or octave.\nLeave blank to discover it automatically, or set OCTALINK_OCTAVE."))
            row = QHBoxLayout()
            edit = QLineEdit(self.octave_executable or discover_octave() or "")
            edit.setPlaceholderText("Octave executable path")
            browse = QPushButton("Browse…")
            def choose():
                path, _ = QFileDialog.getOpenFileName(dialog, "Select GNU Octave Executable", edit.text(), "Executable (*)")
                if path:
                    edit.setText(path)
            browse.clicked.connect(choose)
            row.addWidget(edit)
            row.addWidget(browse)
            layout.addLayout(row)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            def accept():
                path = edit.text().strip() or None
                resolved = discover_octave(path)
                if path and not resolved:
                    self.report_error("The selected GNU Octave executable was not found.")
                    return
                self.octave_executable = resolved
                self.log("Octave executable configured." if resolved else "Octave discovery remains automatic.")
                dialog.accept()
            buttons.accepted.connect(accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.exec()

        def edit_model_workspace(self):
            """Edit ordered model variables used by block parameters and expressions."""
            if self.worker:
                return
            current = dict(getattr(self.root_scene, "variables", None) or {})
            dialog = QDialog(self)
            dialog.setWindowTitle("Model Workspace")
            # Tall enough for typical workspaces (the house model has 24 variables).
            dialog.resize(620, min(820, 300 + 30 * max(4, len(current))))
            layout = QVBoxLayout(dialog)
            intro = QLabel("Variables are evaluated in order and can be used in any block parameter, "
                           "e.g. J = 0.01 then Gain = 1/J. Arrays use brackets: K = [-0.64 169.7 7.07].")
            intro.setWordWrap(True)
            layout.addWidget(intro)
            table = QTableWidget(0, 2)
            table.setObjectName("modelWorkspaceTable")
            table.setHorizontalHeaderLabels(["Name", "Value"])
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            for name, value in current.items():
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(name))
                table.setItem(row, 1, QTableWidgetItem(str(value)))
            layout.addWidget(table)
            buttons_row = QHBoxLayout()
            add, remove = QPushButton("Add Variable"), QPushButton("Remove")
            buttons_row.addWidget(add)
            buttons_row.addWidget(remove)
            buttons_row.addStretch()
            layout.addLayout(buttons_row)
            status = QLabel()
            status.setWordWrap(True)
            layout.addWidget(status)

            def collect():
                values = {}
                for row in range(table.rowCount()):
                    name = (table.item(row, 0).text() if table.item(row, 0) else "").strip()
                    value = (table.item(row, 1).text() if table.item(row, 1) else "").strip()
                    if not name and not value:
                        continue
                    if name in values:
                        raise ValueError(f"Variable {name} is defined twice.")
                    if not value:
                        raise ValueError(f"Variable {name or '(unnamed)'} needs a value.")
                    values[name] = value
                return values

            def refresh(*_):
                try:
                    scalars, arrays = resolve_variables(collect())
                    shown = [f"{k} = {v:.6g}" for k, v in scalars.items()]
                    shown += [f"{k} = {len(rows)}×{len(rows[0]) if rows else 0} array" for k, rows in arrays.items()]
                    status.setStyleSheet("color: #2e6b2e;")
                    status.setText("Valid.  " + ("   ".join(shown) if shown else "No variables defined."))
                    return True
                except ValueError as exc:
                    status.setStyleSheet("color: #b83030;")
                    status.setText(str(exc))
                    return False

            def add_row():
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(""))
                table.setItem(row, 1, QTableWidgetItem(""))
                table.setCurrentCell(row, 0)
                table.editItem(table.item(row, 0))

            def remove_rows():
                for row in sorted({index.row() for index in table.selectedIndexes()}, reverse=True):
                    table.removeRow(row)
                refresh()

            add.clicked.connect(add_row)
            remove.clicked.connect(remove_rows)
            table.itemChanged.connect(refresh)
            refresh()
            box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            def accept():
                if not refresh():
                    return
                dialog.accept()
            box.accepted.connect(accept)
            box.rejected.connect(dialog.reject)
            layout.addWidget(box)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            updated = collect()
            if updated == current:
                return
            self.push_undo_snapshot()
            self.root_scene.variables = updated
            for scene_block in self.root_scene.blocks:
                scene_block.update()
            self.refresh_document_ui()
            self.log(f"Model Workspace updated: {len(updated)} variable(s).")

        def on_linear_analysis_clicked(self):
            try:
                from linear_analysis import analyze_model
                data = self.serialize_model()
                scene = detached_graph(data, module.BLOCK_SPECS)
                blocks, sources, *_ = self.sim_engine.compile_graph(scene)
                from linear_analysis import SOURCE_TYPES
                inputs = [b for b in blocks if b.block_type in SOURCE_TYPES]
                sinks = [b for b in blocks if b.block_type == "Scope"] or [b for b in blocks if b.block_type == "To CSV"]
                if not inputs or not sinks:
                    raise ValueError("Transfer analysis needs an input Source and an output Scope or To CSV block.")
                dialog = QDialog(self)
                dialog.setWindowTitle("Linear Analysis Selection")
                dialog.resize(520, 280)
                layout = QVBoxLayout(dialog)
                description = QLabel("Select the source to perturb and the logged output to measure.\nThe model is linearized around its initial state and the operating input below.")
                description.setWordWrap(True)
                layout.addWidget(description)
                form = QFormLayout()
                input_box, output_box = QComboBox(), QComboBox()
                for block in inputs:
                    input_box.addItem(f"{block.name}  [{block.block_id}]", block.block_id)
                for sink in sinks:
                    labels = self.sim_engine._resolve_scope_labels(sink, sources)
                    for channel, label in enumerate(labels):
                        output_box.addItem(f"{sink.name} / {label}", (sink.block_id, channel))
                labels = self.sim_engine._resolve_scope_labels(sinks[0], sources)
                output_box.setCurrentIndex(max(0, len(labels)-1))
                if self.analysis_selection:
                    old_input, old_output = self.analysis_selection
                    idx = input_box.findData(old_input)
                    if idx >= 0:
                        input_box.setCurrentIndex(idx)
                    idx = output_box.findData(old_output)
                    if idx >= 0:
                        output_box.setCurrentIndex(idx)
                operating = QLineEdit("0")
                form.addRow("Input source", input_box)
                form.addRow("Output channel", output_box)
                form.addRow("Operating input", operating)
                layout.addLayout(form)
                note = QLabel("Frequency response is for this selected transfer.\nDisplayed feedback margins do not automatically describe the model's internal control loop.")
                note.setWordWrap(True)
                layout.addWidget(note)
                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                layout.addWidget(buttons)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                source_id = input_box.currentData()
                sink_id, channel = output_box.currentData()
                self.analysis_selection = (source_id, (sink_id, channel))
                result = analyze_model(data, module.BLOCK_SPECS, source_id=source_id,
                                       sink_id=sink_id, channel=channel,
                                       operating_input=float(operating.text()))
                self.log(f"Linear analysis: {input_box.currentText()} → {output_box.currentText()}.")
                viewer = module.LinearAnalysisDialog(result, self)
                viewer.setWindowTitle(f"Linear Analysis — {input_box.currentText()} → {output_box.currentText()}")
                viewer.exec()
            except Exception as exc:
                self.report_error(str(exc))

        def on_export_m_clicked(self):
            path, _ = QFileDialog.getSaveFileName(self, "Export GNU Octave Model", "octalink_model.m", "Octave Function (*.m)")
            if not path:
                return
            try:
                from octave_backend import export_octave_script
                export_octave_script(self.serialize_model(), module.BLOCK_SPECS, path)
                self.log(f"Exported standalone GNU Octave model to {Path(path).name}.")
            except Exception as exc:
                self.report_error(str(exc))

        def on_export_c_clicked(self):
            path, _ = QFileDialog.getSaveFileName(self, "Export C99 Model", "octalink_model.c", "C99 Source (*.c)")
            if not path:
                return
            try:
                from c_export import export_c_model
                header, source = export_c_model(self.serialize_model(), module.BLOCK_SPECS,
                                                float(self.dt_edit.text()), path)
                self.log(f"Exported {Path(header).name} and {Path(source).name}.")
            except Exception as exc:
                self.report_error(str(exc))

        def check_model(self):
            try:
                data = validate_document(self.serialize_model(), module.BLOCK_SPECS)
                scene = detached_graph(data, module.BLOCK_SPECS)
                self.sim_engine.compile_graph(scene)
                if data.get("backend") == "octave":
                    from octave_backend import discover_octave
                    if not discover_octave(self.octave_executable):
                        raise ValueError("GNU Octave was not found. Select its executable in Octave Settings or set OCTALINK_OCTAVE.")
                self.log("Model check passed: parameters, ports and signal dependencies are valid.")
                for loop in self.sim_engine.algebraic_loops:
                    self.log(f"Algebraic loop of {len(loop.members)} blocks: solved by Newton on {loop.name}.")
                return True
            except Exception as exc:
                self.report_error(str(exc))
                return False

        def set_running(self, running):
            self.view.setEnabled(not running)
            self.library_dock.setEnabled(not running)
            self.browser_dock.setEnabled(not running)
            self.properties_dock.setEnabled(not running)
            self.stop_time_edit.setEnabled(not running)
            self.dt_edit.setEnabled(not running)
            self.backend_combo.setEnabled(not running)
            self.solver_combo.setEnabled(not running)
            self.octave_settings_button.setEnabled(not running)
            self.up_btn.setEnabled(not running and self.current_scene.owner_subsystem is not None)
            for action in self.actions_map.values():
                action.setEnabled(not running)
            self.stop_action.setEnabled(running)
            self.run_button.setEnabled(not running)
            self.stop_button.setEnabled(running)
            # Keep Simulation/Stop accessible; block other tabs during a run.
            self.ribbon.setCurrentIndex(0)
            for i in range(1, self.ribbon.count()):
                self.ribbon.setTabEnabled(i, not running)
            self.progress.setVisible(running)
            self.progress.setValue(0)

        def on_run_clicked(self):
            if self.worker or not self.check_model():
                return
            for scope in self.scope_windows:
                scope.close()
            self.scope_windows.clear()
            self.worker = SimulationWorker(self.serialize_model(), module, self,
                                           octave_executable=self.octave_executable)
            self.worker.progress.connect(self.progress.setValue)
            self.worker.result.connect(self.simulation_result)
            self.worker.failed.connect(self.report_error)
            self.worker.finished.connect(self.simulation_finished)
            self.set_running(True)
            self.log(f"Simulation running...  {self.backend_combo.currentText()} engine, "
                     f"{self.solver_combo.currentText()} solver")
            self.worker.start()

        def stop_simulation(self):
            if self.worker:
                self.worker.cancel_event.set()
                self.log("Stopping simulation...")

        def simulation_result(self, results):
            self._last_csv = results
            blocks, _ = self.sim_engine.flatten_hierarchy(self.root_scene)
            for block in blocks:
                if block.block_id in results:
                    block.scope_t, block.scope_y, block.scope_labels = results[block.block_id]
            count = max((len(value[0]) for value in results.values()), default=0)
            self.log(f"Simulation complete. Stop time {self.stop_time_edit.text()} s; {count} logged samples.")
            self.open_scopes()

        def simulation_finished(self):
            cancelled = self.worker.cancel_event.is_set()
            self.worker.deleteLater()
            self.worker = None
            self.set_running(False)
            self.refresh_document_ui()
            if cancelled:
                self.log("Simulation stopped. Previous complete results were preserved.")

        def open_scopes(self):
            blocks, _ = self.sim_engine.flatten_hierarchy(self.root_scene)
            for block in blocks:
                if block.block_type == "Scope":
                    dialog = module.ScopeDialog(block, self)
                    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                    dialog.setModal(False)
                    dialog.show()
                    self.scope_windows.append(dialog)
                    dialog.destroyed.connect(lambda obj=None, d=dialog: self.scope_windows.remove(d) if d in self.scope_windows else None)

        def export_scope_csv(self):
            blocks, _ = self.sim_engine.flatten_hierarchy(self.root_scene)
            selected = [b for b in self.current_scene.selectedItems() if isinstance(b, module.BlockItem)]
            choices = [b for b in blocks if b.block_type in ("Scope", "To CSV") and len(b.scope_t)]
            if not choices:
                self.report_error("Run a simulation before exporting results.")
                return
            block = next((b for b in selected if b in choices), choices[0])
            path, _ = QFileDialog.getSaveFileName(self, "Export Scope Data", block.name + ".csv", "CSV (*.csv)")
            if path:
                try:
                    with open(path, "w", newline="", encoding="utf-8") as stream:
                        writer = csv.writer(stream)
                        writer.writerow(["time"] + block.scope_labels)
                        for t, values in zip(block.scope_t, block.scope_y):
                            writer.writerow([t] + list(values))
                    self.log(f"Exported {len(block.scope_t)} samples to {Path(path).name}.")
                except OSError as exc:
                    self.report_error(str(exc))

        def show_help(self):
            QMessageBox.information(self, "Editing Shortcuts", "Drag from Library Browser to insert.\nDouble-click blank canvas to search blocks.\nDrag output port to input port to connect.\nDouble-click block to edit; Scope opens results.\n\nCtrl+N/O/S: New/Open/Save\nCtrl+Z/Y: Undo/Redo\nCtrl+C/V: Copy/Paste\nCtrl+G: Create Subsystem\nCtrl+I: Flip\nCtrl+0: Fit to view\nCtrl+D: Check model\nCtrl+R: Run\nDelete: Remove selection\nWheel: Zoom; Middle-drag or Space+drag: Pan")

        def closeEvent(self, event):
            if self.worker:
                self.stop_simulation()
                event.ignore()
                self.log("Stopping simulation. Close again after it stops.")
                return
            if self.confirm_discard():
                self.document_timer.stop()
                for scope in list(self.scope_windows):
                    scope.close()
                event.accept()
            else:
                event.ignore()

    return MVPWindow
