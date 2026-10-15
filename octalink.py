import sys
import math
from collections import deque
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPathItem,
    QListWidget, QListWidgetItem, QToolBar, QLabel, QLineEdit,
    QDialog, QFormLayout, QDialogButtonBox, QDockWidget, QMessageBox,
    QPushButton, QStatusBar
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPainterPath, QAction, QPolygonF
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Optional GNU Octave Bridge
try:
    from oct2py import Oct2Py
    OCTAVE_AVAILABLE = True
except Exception:
    OCTAVE_AVAILABLE = False

# ============================================================================
# 1. BLOCK DEFINITIONS & METADATA
# ============================================================================
BLOCK_Specs = {
    "Step": {
        "category": "Sources",
        "inputs": 0,
        "outputs": 1,
        "direct_feedthrough": False,
        "params": {"step_time": "1.0", "initial_val": "0.0", "final_val": "1.0"},
        "color": "#E8F4F8",
        "symbol": "Step"
    },
    "Sine Wave": {
        "category": "Sources",
        "inputs": 0,
        "outputs": 1,
        "direct_feedthrough": False,
        "params": {"amplitude": "1.0", "frequency": "2.0", "phase": "0.0"},
        "color": "#E8F4F8",
        "symbol": "~"
    },
    "Constant": {
        "category": "Sources",
        "inputs": 0,
        "outputs": 1,
        "direct_feedthrough": False,
        "params": {"value": "1.0"},
        "color": "#E8F4F8",
        "symbol": "C"
    },
    "Sum": {
        "category": "Math Operations",
        "inputs": 2,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"signs": "+-"},
        "color": "#FFFFFF",
        "symbol": "∑"
    },
    "Gain": {
        "category": "Math Operations",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"gain": "5.0"},
        "color": "#FFF9E6",
        "symbol": "K"
    },
    "Integrator": {
        "category": "Continuous",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": False,  # Breaks algebraic loops!
        "params": {"initial_condition": "0.0"},
        "color": "#E8F8F0",
        "symbol": "1/s"
    },
    "Scope": {
        "category": "Sinks",
        "inputs": 1,
        "outputs": 0,
        "direct_feedthrough": True,
        "params": {"title": "Scope Output"},
        "color": "#F4ECF8",
        "symbol": "📈"
    }
}

# ============================================================================
# 2. VISUAL CANVAS ITEMS (PORTS, WIRES, BLOCKS)
# ============================================================================
class PortItem(QGraphicsItem):
    def __init__(self, parent_block, is_output, index):
        super().__init__(parent_block)
        self.parent_block = parent_block
        self.is_output = is_output
        self.index = index
        self.radius = 6
        self.wires = []
        self.setAcceptHoverEvents(True)
        self.hovered = False

    def boundingRect(self):
        return QRectF(-self.radius - 2, -self.radius - 2,
                      (self.radius + 2) * 2, (self.radius + 2) * 2)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#007ACC") if self.hovered else QColor("#222222")
        painter.setPen(QPen(color, 1.8))
        painter.setBrush(QBrush(QColor("#FFFFFF") if not self.hovered else QColor("#007ACC")))

        # Draw Simulink-style chevron/port indicator
        if self.is_output:
            poly = QPolygonF([QPointF(-4, -5), QPointF(5, 0), QPointF(-4, 5)])
            painter.drawPolygon(poly)
        else:
            painter.drawEllipse(QPointF(0, 0), self.radius - 1, self.radius - 1)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def scene_pos(self):
        return self.scenePos()

class WireItem(QGraphicsPathItem):
    def __init__(self, start_port, end_port=None):
        super().__init__()
        self.start_port = start_port
        self.end_port = end_port
        self.temp_end_pos = start_port.scene_pos()
        self.setZValue(-1)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.update_path()

    def update_path(self):
        p1 = self.start_port.scene_pos()
        p2 = self.end_port.scene_pos() if self.end_port else self.temp_end_pos

        path = QPainterPath(p1)
        dx = max(abs(p2.x() - p1.x()) * 0.5, 40)
        c1 = QPointF(p1.x() + dx, p1.y())
        c2 = QPointF(p2.x() - dx, p2.y())
        path.cubicTo(c1, c2, p2)
        self.setPath(path)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_sel = self.isSelected()
        pen = QPen(QColor("#007ACC") if is_sel else QColor("#1E1E1E"), 2.5 if is_sel else 1.8)
        painter.setPen(pen)
        painter.drawPath(self.path())

class BlockItem(QGraphicsItem):
    _id_counter = 1

    def __init__(self, block_type, x=0, y=0):
        super().__init__()
        self.block_id = BlockItem._id_counter
        BlockItem._id_counter += 1

        self.block_type = block_type
        self.spec = BLOCK_Specs[block_type]
        self.name = f"{block_type}_{self.block_id}"
        self.params = dict(self.spec["params"])

        self.width = 90
        self.height = 60
        if block_type == "Sum":
            self.width = 56
            self.height = 56

        self.setPos(x, y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )

        # Create input/output ports
        self.in_ports = []
        self.out_ports = []
        num_in = self.spec["inputs"]
        num_out = self.spec["outputs"]

        for i in range(num_in):
            port = PortItem(self, is_output=False, index=i)
            y_offset = (self.height / (num_in + 1)) * (i + 1)
            port.setPos(0, y_offset)
            self.in_ports.append(port)

        for i in range(num_out):
            port = PortItem(self, is_output=True, index=i)
            y_offset = (self.height / (num_out + 1)) * (i + 1)
            port.setPos(self.width, y_offset)
            self.out_ports.append(port)

        # Scope data storage
        self.scope_t = []
        self.scope_y = []

    def boundingRect(self):
        return QRectF(-10, -10, self.width + 20, self.height + 35)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Drop shadow
        shadow_rect = QRectF(3, 3, self.width, self.height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 30))
        if self.block_type == "Sum":
            painter.drawEllipse(shadow_rect)
        else:
            painter.drawRoundedRect(shadow_rect, 6, 6)

        # Main body
        rect = QRectF(0, 0, self.width, self.height)
        border_col = QColor("#007ACC") if self.isSelected() else QColor("#333333")
        painter.setPen(QPen(border_col, 2.2 if self.isSelected() else 1.5))
        painter.setBrush(QBrush(QColor(self.spec["color"])))

        if self.block_type == "Sum":
            painter.drawEllipse(rect)
        elif self.block_type == "Gain":
            poly = QPolygonF([
                QPointF(0, 0),
                QPointF(self.width, self.height / 2),
                QPointF(0, self.height)
            ])
            painter.drawPolygon(poly)
        else:
            painter.drawRoundedRect(rect, 6, 6)

        # Symbol inside block
        painter.setPen(QColor("#111111"))
        font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        painter.setFont(font)
        symbol_text = self.spec["symbol"]
        if self.block_type == "Gain":
            symbol_text = self.params.get("gain", "K")
            painter.drawText(QRectF(0, 0, self.width * 0.7, self.height),
                             Qt.AlignmentFlag.AlignCenter, symbol_text)
        elif self.block_type == "Sum":
            signs = self.params.get("signs", "+-")
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            for idx, s in enumerate(signs[:len(self.in_ports)]):
                py = self.in_ports[idx].pos().y()
                painter.drawText(QPointF(10, py + 4), s)
        else:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, symbol_text)

        # Block Label underneath (Simulink convention)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#333333"))
        label_rect = QRectF(-15, self.height + 4, self.width + 30, 20)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.name)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for port in self.in_ports + self.out_ports:
                for wire in port.wires:
                    wire.update_path()
        return super().itemChange(change, value)

# ============================================================================
# 3. INTERACTIVE SCENE & PARAMETER / SCOPE DIALOGS
# ============================================================================
class ScopeDialog(QDialog):
    def __init__(self, block: BlockItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Simulink Scope - {block.name}")
        self.resize(680, 420)
        layout = QVBoxLayout(self)

        fig = Figure(figsize=(6, 4), dpi=100)
        fig.patch.set_facecolor("#1E1E1E")
        self.canvas = FigureCanvas(fig)
        layout.addWidget(self.canvas)

        ax = fig.add_subplot(111)
        ax.set_facecolor("#121212")
        if len(block.scope_t) > 0:
            ax.plot(block.scope_t, block.scope_y, color="#00E676", linewidth=2.0, label=block.name)
            ax.legend(facecolor="#1E1E1E", edgecolor="#444444", labelcolor="white")
        else:
            ax.text(0.5, 0.5, "No simulation data yet. Click '▶ Run' first.",
                    color="#AAAAAA", ha="center", va="center", transform=ax.transAxes)

        ax.set_title(block.params.get("title", "Scope"), color="white", fontsize=11)
        ax.set_xlabel("Time (s)", color="#CCCCCC")
        ax.set_ylabel("Amplitude", color="#CCCCCC")
        ax.tick_params(colors="#CCCCCC")
        ax.grid(True, linestyle="--", alpha=0.3, color="#888888")
        fig.tight_layout()

class ParamDialog(QDialog):
    def __init__(self, block: BlockItem, parent=None):
        super().__init__(parent)
        self.block = block
        self.setWindowTitle(f"Block Parameters: {block.name}")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.inputs = {}

        for key, val in block.params.items():
            edit = QLineEdit(str(val))
            self.inputs[key] = edit
            form.addRow(QLabel(f"{key.replace('_', ' ').title()}:"), edit)

        layout.addLayout(form)
        note = QLabel("Tip: You can enter numbers or GNU Octave expressions (e.g., 2*pi, sqrt(2)).")
        note.setStyleSheet("color: #666666; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        for k, edit in self.inputs.items():
            self.block.params[k] = edit.text().strip()
        self.block.update()
        super().accept()

class SimCanvasScene(QGraphicsScene):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setSceneRect(0, 0, 2000, 1400)
        self.active_wire = None
        self.blocks = []
        self.wires = []

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#F7F8FA"))
        # Subtle Simulink dot/grid pattern
        grid_size = 20
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)
        pen = QPen(QColor("#DCE0E6"), 1.5)
        painter.setPen(pen)
        for x in range(left, int(rect.right()), grid_size):
            for y in range(top, int(rect.bottom()), grid_size):
                painter.drawPoint(x, y)

    def add_sim_block(self, block_type, x, y):
        blk = BlockItem(block_type, x, y)
        self.addItem(blk)
        self.blocks.append(blk)
        return blk

    def connect_ports(self, out_port: PortItem, in_port: PortItem):
        # Ensure an input port only has one incoming wire
        for existing in list(in_port.wires):
            self.remove_wire(existing)

        wire = WireItem(out_port, in_port)
        self.addItem(wire)
        out_port.wires.append(wire)
        in_port.wires.append(wire)
        self.wires.append(wire)
        return wire

    def remove_wire(self, wire: WireItem):
        if wire in self.wires:
            self.wires.remove(wire)
        if wire in wire.start_port.wires:
            wire.start_port.wires.remove(wire)
        if wire.end_port and wire in wire.end_port.wires:
            wire.end_port.wires.remove(wire)
        self.removeItem(wire)

    def mousePressEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if isinstance(item, PortItem) and item.is_output:
            self.active_wire = WireItem(item)
            self.addItem(self.active_wire)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_wire:
            self.active_wire.temp_end_pos = event.scenePos()
            self.active_wire.update_path()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.active_wire:
            item = self.itemAt(event.scenePos(), self.views()[0].transform())
            if isinstance(item, PortItem) and not item.is_output and item.parent_block != self.active_wire.start_port.parent_block:
                self.connect_ports(self.active_wire.start_port, item)
            self.removeItem(self.active_wire)
            self.active_wire = None
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform())
        if isinstance(item, PortItem):
            item = item.parent_block
        if isinstance(item, BlockItem):
            if item.block_type == "Scope":
                dlg = ScopeDialog(item, self.parent_window)
                dlg.exec()
            else:
                dlg = ParamDialog(item, self.parent_window)
                dlg.exec()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for item in list(self.selectedItems()):
                if isinstance(item, WireItem):
                    self.remove_wire(item)
                elif isinstance(item, BlockItem):
                    for port in item.in_ports + item.out_ports:
                        for w in list(port.wires):
                            self.remove_wire(w)
                    self.blocks.remove(item)
                    self.removeItem(item)
        super().keyPressEvent(event)

# ============================================================================
# 4. SIMULATION COMPILER & GNU OCTAVE ENGINE BRIDGE
# ============================================================================
class SimulationEngine:
    def __init__(self):
        self.octave = Oct2Py() if OCTAVE_AVAILABLE else None

    def eval_param(self, expr_str: str) -> float:
        """Evaluates parameter expressions via GNU Octave or safe math fallback."""
        try:
            return float(expr_str)
        except ValueError:
            if self.octave:
                return float(self.octave.eval(expr_str))
            allowed = {"pi": math.pi, "e": math.e, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos}
            return float(eval(expr_str, {"__builtins__": {}}, allowed))

    def run_simulation(self, blocks, t_stop=10.0, dt=0.01):
        # 1. Parse all block parameters
        parsed_params = {}
        for b in blocks:
            parsed_params[b] = {
                k: (self.eval_param(v) if k not in ("signs", "title") else v)
                for k, v in b.params.items()
            }
            b.scope_t = []
            b.scope_y = []

        # 2. Separate non-direct feedthrough blocks (Sources + Integrators) from direct feedthrough
        integrators = [b for b in blocks if b.block_type == "Integrator"]
        direct_blocks = [b for b in blocks if b.spec["direct_feedthrough"]]

        # 3. Topological Sort on Direct Feedthrough blocks (Kahn's Algorithm)
        in_degree = {b: 0 for b in direct_blocks}
        adj = {b: [] for b in direct_blocks}

        for b in direct_blocks:
            for in_port in b.in_ports:
                for w in in_port.wires:
                    src_blk = w.start_port.parent_block
                    if src_blk in direct_blocks:
                        adj[src_blk].append(b)
                        in_degree[b] += 1

        queue = deque([b for b in direct_blocks if in_degree[b] == 0])
        sorted_direct = []
        while queue:
            curr = queue.popleft()
            sorted_direct.append(curr)
            for nxt in adj[curr]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if len(sorted_direct) != len(direct_blocks):
            raise RuntimeError(
                "Algebraic Loop Detected! Place an Integrator block in the feedback loop."
            )

        # 4. Helper to evaluate all algebraic signals at time t given integrator states
        def evaluate_network(t, state_map):
            out_signals = {}

            # A. Seed Sources & Integrators
            for b in blocks:
                p = parsed_params[b]
                if b.block_type == "Step":
                    out_signals[b] = p["final_val"] if t >= p["step_time"] else p["initial_val"]
                elif b.block_type == "Sine Wave":
                    out_signals[b] = p["amplitude"] * math.sin(p["frequency"] * t + p["phase"])
                elif b.block_type == "Constant":
                    out_signals[b] = p["value"]
                elif b.block_type == "Integrator":
                    out_signals[b] = state_map[b]

            # B. Propagate through topologically sorted Direct Feedthrough blocks
            for b in sorted_direct:
                p = parsed_params[b]
                inputs = []
                for in_port in b.in_ports:
                    if in_port.wires:
                        src_blk = in_port.wires[0].start_port.parent_block
                        inputs.append(out_signals.get(src_blk, 0.0))
                    else:
                        inputs.append(0.0)

                if b.block_type == "Gain":
                    out_signals[b] = p["gain"] * inputs[0]
                elif b.block_type == "Sum":
                    signs = p["signs"]
                    total = 0.0
                    for idx, val in enumerate(inputs):
                        s = signs[idx] if idx < len(signs) else "+"
                        total += val if s == "+" else -val
                    out_signals[b] = total
                elif b.block_type == "Scope":
                    out_signals[b] = inputs[0]

            # C. Compute state derivatives for Integrators
            derivs = {}
            for b in integrators:
                if b.in_ports[0].wires:
                    src_blk = b.in_ports[0].wires[0].start_port.parent_block
                    derivs[b] = out_signals.get(src_blk, 0.0)
                else:
                    derivs[b] = 0.0

            return out_signals, derivs

        # 5. Runge-Kutta 4th Order (RK4) Time Stepping
        states = {b: parsed_params[b]["initial_condition"] for b in integrators}
        num_steps = int(t_stop / dt) + 1

        for step in range(num_steps):
            t = step * dt
            signals, k1 = evaluate_network(t, states)

            # Record Scope sinks
            for b in blocks:
                if b.block_type == "Scope":
                    b.scope_t.append(t)
                    b.scope_y.append(signals.get(b, 0.0))

            if integrators:
                s2 = {b: states[b] + 0.5 * dt * k1[b] for b in integrators}
                _, k2 = evaluate_network(t + 0.5 * dt, s2)

                s3 = {b: states[b] + 0.5 * dt * k2[b] for b in integrators}
                _, k3 = evaluate_network(t + 0.5 * dt, s3)

                s4 = {b: states[b] + dt * k3[b] for b in integrators}
                _, k4 = evaluate_network(t + dt, s4)

                for b in integrators:
                    states[b] += (dt / 6.0) * (k1[b] + 2 * k2[b] + 2 * k3[b] + k4[b])

        # Sync final scope arrays to GNU Octave workspace if available
        if self.octave:
            for b in blocks:
                if b.block_type == "Scope":
                    self.octave.push(f"{b.name}_t", np.array(b.scope_t))
                    self.octave.push(f"{b.name}_y", np.array(b.scope_y))

# ============================================================================
# 5. MAIN APPLICATION WINDOW
# ============================================================================
class OctaLinkMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OctaLink — Visual Block Modeling Environment for GNU Octave")
        self.resize(1180, 720)
        self.sim_engine = SimulationEngine()

        self._setup_ui()
        self._build_default_control_loop()

    def _setup_ui(self):
        # Toolbar (Simulink Action Bar style)
        toolbar = QToolBar("Simulation Controls")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("""
            QToolBar { background: #2D2D30; spacing: 10px; padding: 6px; border-bottom: 1px solid #1E1E1E; }
            QLabel { color: #FFFFFF; font-weight: bold; }
            QLineEdit { background: #1E1E1E; color: #00E676; border: 1px solid #555; padding: 4px; border-radius: 4px; }
            QPushButton { background: #007ACC; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px; }
            QPushButton:hover { background: #1C97EA; }
        """)
        self.addToolBar(toolbar)

        run_btn = QPushButton("▶ Run Simulation")
        run_btn.clicked.connect(self.on_run_clicked)
        toolbar.addWidget(run_btn)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Stop Time (s):"))
        self.stop_time_edit = QLineEdit("10.0")
        self.stop_time_edit.setFixedWidth(70)
        toolbar.addWidget(self.stop_time_edit)

        toolbar.addWidget(QLabel("Step Size (dt):"))
        self.dt_edit = QLineEdit("0.02")
        self.dt_edit.setFixedWidth(70)
        toolbar.addWidget(self.dt_edit)

        clear_btn = QPushButton("Clear Canvas")
        clear_btn.setStyleSheet("background: #444444;")
        clear_btn.clicked.connect(self.on_clear_clicked)
        toolbar.addWidget(clear_btn)

        # Left Dock: Simulink Library Browser
        dock = QDockWidget("Library Browser", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock_widget = QWidget()
        dock_layout = QVBoxLayout(dock_widget)

        inst_label = QLabel("Double-click a block below to add it to your model:")
        inst_label.setWordWrap(True)
        inst_label.setStyleSheet("color: #444; font-size: 11px; margin-bottom: 4px;")
        dock_layout.addWidget(inst_label)

        self.lib_list = QListWidget()
        self.lib_list.setStyleSheet("""
            QListWidget { font-size: 13px; padding: 4px; }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #EEEEEE; }
            QListWidget::item:hover { background: #E5F3FF; }
        """)
        for btype, spec in BLOCK_Specs.items():
            item = QListWidgetItem(f"[{spec['category']}]  {btype} ({spec['symbol']})")
            item.setData(Qt.ItemDataRole.UserRole, btype)
            self.lib_list.addItem(item)
        self.lib_list.itemDoubleClicked.connect(self.on_library_item_double_clicked)
        dock_layout.addWidget(self.lib_list)

        dock.setWidget(dock_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        # Central Canvas View
        self.scene = SimCanvasScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setCentralWidget(self.view)

        # Status Bar
        status = QStatusBar()
        self.setStatusBar(status)
        octave_status = "Connected (oct2py active)" if OCTAVE_AVAILABLE else "Fallback RK4 Engine (Install oct2py + Octave for workspace sync)"
        status.showMessage(f"Engine Status: {octave_status}  |  Drag from output chevron (▶) to input port (●) to wire blocks. Double-click blocks to configure/view Scope.")

    def on_library_item_double_clicked(self, item):
        btype = item.data(Qt.ItemDataRole.UserRole)
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.scene.add_sim_block(btype, center.x() - 45, center.y() - 30)

    def _build_default_control_loop(self):
        """Pre-loads a classic closed-loop feedback control system."""
        step = self.scene.add_sim_block("Step", 120, 220)
        summ = self.scene.add_sim_block("Sum", 280, 222)
        gain = self.scene.add_sim_block("Gain", 410, 220)
        integ = self.scene.add_sim_block("Integrator", 570, 220)
        scope = self.scene.add_sim_block("Scope", 740, 220)

        # Wire forward path: Step -> Sum(+) -> Gain -> Integrator -> Scope
        self.scene.connect_ports(step.out_ports[0], summ.in_ports[0])
        self.scene.connect_ports(summ.out_ports[0], gain.in_ports[0])
        self.scene.connect_ports(gain.out_ports[0], integ.in_ports[0])
        self.scene.connect_ports(integ.out_ports[0], scope.in_ports[0])

        # Wire negative feedback path: Integrator -> Sum(-)
        self.scene.connect_ports(integ.out_ports[0], summ.in_ports[1])
        self.view.centerOn(430, 250)

    def on_clear_clicked(self):
        for w in list(self.scene.wires):
            self.scene.remove_wire(w)
        for b in list(self.scene.blocks):
            self.scene.removeItem(b)
        self.scene.blocks.clear()

    def on_run_clicked(self):
        try:
            t_stop = float(self.stop_time_edit.text())
            dt = float(self.dt_edit.text())
            self.sim_engine.run_simulation(self.scene.blocks, t_stop=t_stop, dt=dt)
            self.statusBar().showMessage(f"Simulation completed successfully (t = 0 to {t_stop}s). Double-click any Scope block to inspect waveforms.")

            # Automatically pop open the first Scope block if one exists
            for b in self.scene.blocks:
                if b.block_type == "Scope":
                    dlg = ScopeDialog(b, self)
                    dlg.exec()
                    break
        except Exception as e:
            QMessageBox.critical(self, "Simulation Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = OctaLinkMainWindow()
    win.show()
    sys.exit(app.exec())
