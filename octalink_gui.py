import sys
import os
import re
import csv
import json
import math
import shutil
import subprocess
import tempfile
from collections import deque
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPathItem,
    QListWidget, QListWidgetItem, QToolBar, QLabel, QLineEdit,
    QDialog, QFormLayout, QDialogButtonBox, QDockWidget, QMessageBox,
    QPushButton, QStatusBar, QFileDialog
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QByteArray, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPainterPath, QPolygonF,
    QKeySequence, QShortcut, QIcon, QPixmap, QFontMetricsF
)

try:
    from PyQt6.QtSvg import QSvgRenderer
    SVG_AVAILABLE = True
except Exception:
    SVG_AVAILABLE = False

from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)
from matplotlib.figure import Figure

# Auto-detect MSYS2 / MinGW GCC on Windows if not on system PATH
if sys.platform == "win32" and not shutil.which("gcc"):
    for gcc_candidate in [r"C:\msys64\ucrt64\bin", r"C:\msys64\mingw64\bin", r"C:\mingw64\bin"]:
        if os.path.exists(os.path.join(gcc_candidate, "gcc.exe")):
            os.environ["PATH"] = os.environ["PATH"] + os.pathsep + gcc_candidate
            break

# The MVP simulation engine is local and deterministic. Importing oct2py can
# launch an Octave process as a side effect, so the GUI never imports it eagerly.
OCTAVE_AVAILABLE = False


# ============================================================================
# 0. VECTOR SVG ICON ENGINE (TOOLBAR, WINDOW & LIBRARY BROWSER ICONS)
# ============================================================================
SVG_ICON_PATHS = {
    "app": """<svg viewBox="0 0 24 24" fill="none" stroke="#00B0FF" stroke-width="2">
        <rect x="2" y="4" width="7" height="6" rx="1.5" fill="#1E1E1E"/>
        <rect x="15" y="4" width="7" height="6" rx="1.5" fill="#1E1E1E"/>
        <rect x="8.5" y="14" width="7" height="6" rx="1.5" fill="#1E1E1E"/>
        <path d="M9 7h6M18.5 10v7h-3M5.5 10v7h3" stroke="#00E676" stroke-linecap="round"/>
    </svg>""",
    "run": """<svg viewBox="0 0 24 24"><polygon points="6,4 20,12 6,20" fill="#00E676"/></svg>""",
    "bode": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2">
        <path d="M3 3v18h18" stroke="#B0BEC5"/>
        <path d="M5 7h6l4 4 5 7" stroke="#00E676" stroke-linecap="round"/>
        <path d="M5 16c4 0 6-6 14-6" stroke="#FFE600" stroke-dasharray="2,2"/>
    </svg>""",
    "c_code": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2">
        <rect x="5" y="5" width="14" height="14" rx="2"/>
        <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>
        <path d="M14 9.5a3 3 0 1 0 0 5" stroke="#FFE600" stroke-linecap="round"/>
    </svg>""",
    "m_code": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <path d="M8 17v-5l2.5 3 2.5-3v5" stroke="#A5D6A7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>""",
    "flip": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="17 2 21 6 17 10"/><path d="M3 6h18"/>
        <polyline points="7 14 3 18 7 22"/><path d="M21 18H3"/>
    </svg>""",
    "undo": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>
    </svg>""",
    "redo": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 14 20 9 15 4"/><path d="M4 20v-7a4 4 0 0 1 4-4h12"/>
    </svg>""",
    "subsystem": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2">
        <rect x="3" y="4" width="18" height="16" rx="2"/>
        <rect x="7" y="8" width="10" height="8" rx="1" stroke="#FFD54F"/>
        <path d="M3 12h4M17 12h4"/>
    </svg>""",
    "up": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 10 20 15 15 20" transform="rotate(-90 12 12)"/>
        <path d="M4 20h7a4 4 0 0 0 4-4V4"/>
    </svg>""",
    "save": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
        <polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>
    </svg>""",
    "load": """<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>""",
    "cat_Sources": """<svg viewBox="0 0 24 24" fill="none" stroke="#0277BD" stroke-width="2">
        <rect x="2" y="3" width="20" height="18" rx="3" fill="#E8F4F8"/>
        <path d="M5 16h5V8h9" stroke="#01579B" stroke-width="2.2" stroke-linecap="round"/>
    </svg>""",
    "cat_Math Operations": """<svg viewBox="0 0 24 24" fill="none" stroke="#F57F17" stroke-width="2">
        <circle cx="12" cy="12" r="9" fill="#FFF9E6"/>
        <path d="M8 12h8M12 8v8" stroke="#E65100" stroke-width="2.2" stroke-linecap="round"/>
    </svg>""",
    "cat_User-Defined": """<svg viewBox="0 0 24 24" fill="none" stroke="#6A1B9A" stroke-width="2">
        <rect x="2" y="3" width="20" height="18" rx="3" fill="#F3E5F5"/>
        <path d="M9 17c1-8 3-10 6-10M7 12h6" stroke="#4A148C" stroke-width="2.2" stroke-linecap="round"/>
    </svg>""",
    "cat_Discontinuities": """<svg viewBox="0 0 24 24" fill="none" stroke="#C62828" stroke-width="2">
        <rect x="2" y="3" width="20" height="18" rx="3" fill="#FCE8E6"/>
        <path d="M5 17h4l6-10h4" stroke="#B71C1C" stroke-width="2.2" stroke-linecap="round"/>
    </svg>""",
    "cat_Continuous": """<svg viewBox="0 0 24 24" fill="none" stroke="#2E7D32" stroke-width="2">
        <rect x="2" y="3" width="20" height="18" rx="3" fill="#E8F8F0"/>
        <path d="M14 6c-3 0-3 12-6 12" stroke="#1B5E20" stroke-width="2.2" stroke-linecap="round"/>
    </svg>""",
    "cat_Discrete": """<svg viewBox="0 0 24 24" fill="none" stroke="#00695C" stroke-width="2">
        <rect x="2" y="3" width="20" height="18" rx="3" fill="#E0F2F1"/>
        <path d="M5 16h4v-6h5v4h5" stroke="#004D40" stroke-width="2.0" stroke-linecap="round"/>
    </svg>""",
    "cat_Signal Routing": """<svg viewBox="0 0 24 24" fill="none" stroke="#212121" stroke-width="2">
        <rect x="10" y="3" width="4" height="18" rx="1" fill="#212121"/>
        <path d="M3 7h7M3 12h7M3 17h7M14 12h7" stroke="#007ACC" stroke-width="2"/>
    </svg>""",
    "cat_Ports & Subsystems": """<svg viewBox="0 0 24 24" fill="none" stroke="#37474F" stroke-width="2">
        <rect x="3" y="4" width="18" height="16" rx="3" fill="#ECEFF1"/>
        <rect x="7" y="8" width="10" height="8" rx="1" stroke="#007ACC"/>
    </svg>""",
    "cat_Sinks": """<svg viewBox="0 0 24 24" fill="none" stroke="#4A148C" stroke-width="2">
        <rect x="2" y="3" width="20" height="18" rx="3" fill="#1E1E1E"/>
        <path d="M4 13c3-6 5 6 8 0s5 6 8 0" stroke="#00E676" stroke-width="2.0" stroke-linecap="round"/>
    </svg>"""
}


def make_svg_icon(key: str, size: int = 20) -> QIcon:
    """Renders an inline SVG string into a sharp, high-DPI QIcon."""
    svg_xml = SVG_ICON_PATHS.get(key, SVG_ICON_PATHS["app"])
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if SVG_AVAILABLE:
        renderer = QSvgRenderer(QByteArray(svg_xml.encode("utf-8")))
        renderer.render(painter, QRectF(0, 0, size * 2, size * 2))
    else:
        painter.setPen(QPen(QColor("#00B0FF"), 3))
        painter.drawRoundedRect(4, 4, size * 2 - 8, size * 2 - 8, 6, 6)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


# ============================================================================
# 1. CANONICAL BLOCK DEFINITIONS & STATE-SPACE REALIZATION
# ============================================================================
BLOCK_SPECS = {
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
        "symbol": "sin"
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
    "Pulse Generator": {
        "category": "Sources",
        "inputs": 0,
        "outputs": 1,
        "direct_feedthrough": False,
        # Simulink time-based pulse: width is a percentage of the period.
        "params": {"amplitude": "1.0", "period": "2.0", "pulse_width": "50", "phase_delay": "0.0"},
        "color": "#E8F4F8",
        "symbol": "Pulse"
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
    "Product": {
        "category": "Math Operations",
        "inputs": 2,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"ops": "**"},
        "color": "#FFFFFF",
        "symbol": "×"
    },
    "Gain": {
        "category": "Math Operations",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"gain": "2.0", "multiplication": "Element-wise(K.*u)"},
        "color": "#FFF9E6",
        "symbol": "K"
    },
    "Trig": {
        "category": "Math Operations",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"operator": "sin"},
        "color": "#FFF9E6",
        "symbol": "sin(u)"
    },
    "Octave Function": {
        "category": "User-Defined",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"expression": "u + 0.05 * sin(t)"},
        "color": "#F3E5F5",
        "symbol": "f(u,t)"
    },
    "Saturation": {
        "category": "Discontinuities",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"lower_limit": "-10.0", "upper_limit": "10.0"},
        "color": "#FCE8E6",
        "symbol": "Sat"
    },
    "Relay": {
        "category": "Discontinuities",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {
            "switch_on_point": "0.5",
            "switch_off_point": "-0.5",
            "on_val": "1.0",
            "off_val": "0.0"
        },
        "color": "#FCE8E6",
        "symbol": "Relay"
    },
    "PID Controller": {
        "category": "Continuous",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"Kp": "6.0", "Ki": "4.0", "Kd": "1.5", "N": "100.0"},
        "color": "#FFF0D6",
        "symbol": "PID(s)"
    },
    "Integrator": {
        "category": "Continuous",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": False,
        "params": {"initial_condition": "0.0"},
        "color": "#E8F8F0",
        "symbol": "1/s"
    },
    "Transfer Fcn": {
        "category": "Continuous",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": False,
        "params": {"numerator": "[1]", "denominator": "[1, 1.4, 1]"},
        "color": "#E8F8F0",
        "symbol": "G(s)"
    },
    "State-Space": {
        "category": "Continuous",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": False,
        "params": {
            "A": "[-1.4, -1.0; 1.0, 0.0]",
            "B": "[1.0; 0.0]",
            "C": "[0.0, 1.0]",
            "D": "0.0",
            "x0": "[0.0; 0.0]"
        },
        "color": "#E8F8F0",
        "symbol": "x'=Ax+Bu"
    },
    "Unit Delay": {
        "category": "Discrete",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": False,
        "params": {"initial_condition": "0.0", "sample_time": "0.1"},
        "color": "#E0F2F1",
        "symbol": "1/z"
    },
    "Zero-Order Hold": {
        "category": "Discrete",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"sample_time": "0.1"},
        "color": "#E0F2F1",
        "symbol": "ZOH"
    },
    "Discrete Transfer Fcn": {
        "category": "Discrete",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": False,  # True when the realization has D != 0
        "params": {"numerator": "[1]", "denominator": "[1, 0.5]", "sample_time": "0.1"},
        "color": "#E0F2F1",
        "symbol": "H(z)"
    },
    "Discrete Zero-Pole": {
        "category": "Discrete",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": False,  # True when the realization has D != 0
        "params": {"zeros": "[1]", "poles": "[0, 0.5]", "gain": "1", "sample_time": "0.1"},
        "color": "#E0F2F1",
        "symbol": "ZPK(z)"
    },
    "Switch": {
        "category": "Signal Routing",
        "inputs": 3,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"threshold": "0.0"},
        "color": "#ECEFF1",
        "symbol": "Sw"
    },
    "Mux": {
        "category": "Signal Routing",
        "inputs": 3,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"inputs": "3"},
        "color": "#222222",
        "symbol": "Mux"
    },
    "Demux": {
        "category": "Signal Routing",
        "inputs": 1,
        "outputs": 2,
        "direct_feedthrough": True,
        "params": {"outputs": "2"},
        "color": "#222222",
        "symbol": "Demux"
    },
    "Subsystem": {
        "category": "Ports & Subsystems",
        "inputs": 1,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {},
        "color": "#ECEFF1",
        "symbol": "Sub"
    },
    "Inport": {
        "category": "Ports & Subsystems",
        "inputs": 0,
        "outputs": 1,
        "direct_feedthrough": True,
        "params": {"port_number": "1"},
        "color": "#FFF8E1",
        "symbol": "In"
    },
    "Outport": {
        "category": "Ports & Subsystems",
        "inputs": 1,
        "outputs": 0,
        "direct_feedthrough": True,
        "params": {"port_number": "1"},
        "color": "#FFF8E1",
        "symbol": "Out"
    },
    "Scope": {
        "category": "Sinks",
        "inputs": 1,
        "outputs": 0,
        "direct_feedthrough": True,
        "params": {"title": "Multi-Channel Scope Output"},
        "color": "#F4ECF8",
        "symbol": "Scope"
    },
    "To CSV": {
        "category": "Sinks",
        "inputs": 1,
        "outputs": 0,
        "direct_feedthrough": True,
        "params": {"filename": "octalink_out.csv"},
        "color": "#E8EAF6",
        "symbol": "CSV"
    }
}


def tf2ss_canonical(num_list, den_list):
    """Converts transfer function polynomials into Controllable Canonical Form (A, B, C, D)."""
    num = np.array(num_list, dtype=float).flatten()
    den = np.array(den_list, dtype=float).flatten()
    if len(den) == 0 or abs(den[0]) < 1e-15:
        raise ValueError("Transfer Fcn denominator leading coefficient must be non-zero.")

    num = num / den[0]
    den = den / den[0]
    n = len(den) - 1
    if len(num) > len(den):
        raise ValueError("Improper Transfer Fcn: deg(numerator) > deg(denominator).")

    padded_num = np.zeros(n + 1, dtype=float)
    padded_num[(n + 1 - len(num)):] = num

    D = float(padded_num[0])
    if n == 0:
        return np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0)), D

    A = np.zeros((n, n), dtype=float)
    A[0, :] = -den[1:]
    if n > 1:
        A[1:, :-1] = np.eye(n - 1)

    B = np.zeros((n, 1), dtype=float)
    B[0, 0] = 1.0

    C = (padded_num[1:] - den[1:] * D).reshape(1, n)
    return A, B, C, D


# ============================================================================
# 2. VISUAL CANVAS ITEMS (WITH VECTORIZED BLOCK SCHEMATICS & CTRL+I FLIPPING)
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

        if self.is_output:
            if getattr(self.parent_block, "flipped", False):
                poly = QPolygonF([QPointF(4, -5), QPointF(-5, 0), QPointF(4, 5)])
            else:
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
        dist = max(abs(p2.x() - p1.x()) * 0.5, 45.0)
        start_dir = -1.0 if getattr(self.start_port.parent_block, "flipped", False) else 1.0
        if self.end_port is not None:
            end_dir = 1.0 if getattr(self.end_port.parent_block, "flipped", False) else -1.0
        else:
            end_dir = -start_dir

        c1 = QPointF(p1.x() + start_dir * dist, p1.y())
        c2 = QPointF(p2.x() + end_dir * dist, p2.y())
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

    def __init__(self, block_type, x=0, y=0, block_id=None, name=None,
                 params=None, flipped=False, parent_window=None):
        super().__init__()
        if block_id is not None:
            self.block_id = block_id
            BlockItem._id_counter = max(BlockItem._id_counter, block_id + 1)
        else:
            self.block_id = BlockItem._id_counter
            BlockItem._id_counter += 1

        self.block_type = block_type
        self.spec = BLOCK_SPECS[block_type]
        safe_prefix = block_type.replace(" ", "_").replace("-", "_")
        self.name = name if name else f"{safe_prefix}_{self.block_id}"
        self.params = dict(self.spec["params"])
        if params:
            self.params.update(params)

        self.flipped = bool(flipped)
        self.parent_window = parent_window
        self.sub_scene = None
        if block_type == "Subsystem":
            self.sub_scene = SimCanvasScene(parent_window, owner_subsystem=self)

        self._compute_dimensions()
        self.setPos(x, y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )

        self.in_ports = []
        self.out_ports = []
        self.rebuild_ports()

        self.scope_t = []
        self.scope_y = []
        self.scope_labels = []

    def _input_count_hint(self):
        from octalink_engine_support import port_counts
        try:
            return port_counts(self.block_type, self.params, self.spec)[0]
        except (ValueError, KeyError):
            return self.spec["inputs"]

    def _compute_dimensions(self):
        if self.block_type == "Sum":
            size = max(56, self._input_count_hint() * 22)
            self.width, self.height = size, size
        elif self.block_type == "Product":
            self.width, self.height = 88, max(60, self._input_count_hint() * 22)
        elif self.block_type == "Mux":
            num_in = max(2, int(self.params.get("inputs", 3)))
            self.width, self.height = 14, max(54, num_in * 20)
        elif self.block_type == "Demux":
            num_out = max(2, int(self.params.get("outputs", 2)))
            self.width, self.height = 14, max(54, num_out * 20)
        elif self.block_type in ("Inport", "Outport"):
            self.width, self.height = 54, 34
        elif self.block_type == "Subsystem":
            self.width, self.height = 115, 74
        elif self.block_type in ("Transfer Fcn", "PID Controller", "Zero-Order Hold", "State-Space", "Octave Function",
                                 "Discrete Transfer Fcn", "Discrete Zero-Pole"):
            self.width, self.height = 110, 60
        elif self.block_type == "Pulse Generator":
            self.width, self.height = 88, 60
        elif self.block_type == "Switch":
            self.width, self.height = 92, 66
        else:
            self.width, self.height = 88, 60

    def toggle_flip(self):
        self.flipped = not self.flipped
        self.rebuild_ports()

    def rebuild_ports(self):
        self.prepareGeometryChange()
        self._compute_dimensions()

        if self.block_type == "Mux":
            num_in = max(2, int(self.params.get("inputs", 3)))
            num_out = 1
        elif self.block_type == "Demux":
            num_in = 1
            num_out = max(2, int(self.params.get("outputs", 2)))
        elif self.block_type == "Subsystem" and self.sub_scene is not None:
            inports = [b for b in self.sub_scene.blocks if b.block_type == "Inport"]
            outports = [b for b in self.sub_scene.blocks if b.block_type == "Outport"]
            num_in = len(inports)
            num_out = len(outports)
        else:
            from octalink_engine_support import port_counts
            try:
                num_in, num_out = port_counts(self.block_type, self.params, self.spec)
            except (ValueError, KeyError):
                # Invalid drafts keep their current ports; Apply reports the error.
                num_in = len(self.in_ports) or self.spec["inputs"]
                num_out = len(self.out_ports) or self.spec["outputs"]

        while len(self.in_ports) > num_in:
            p = self.in_ports.pop()
            if self.scene():
                for w in list(p.wires):
                    self.scene().remove_wire(w)
            p.setParentItem(None)
        while len(self.in_ports) < num_in:
            p = PortItem(self, is_output=False, index=len(self.in_ports))
            self.in_ports.append(p)

        in_x = self.width if self.flipped else 0
        for i, p in enumerate(self.in_ports):
            p.index = i
            p.setPos(in_x, (self.height / (num_in + 1)) * (i + 1))
            p.update()
            for w in p.wires:
                w.update_path()

        while len(self.out_ports) > num_out:
            p = self.out_ports.pop()
            if self.scene():
                for w in list(p.wires):
                    self.scene().remove_wire(w)
            p.setParentItem(None)
        while len(self.out_ports) < num_out:
            p = PortItem(self, is_output=True, index=len(self.out_ports))
            self.out_ports.append(p)

        out_x = 0 if self.flipped else self.width
        for i, p in enumerate(self.out_ports):
            p.index = i
            p.setPos(out_x, (self.height / (num_out + 1)) * (i + 1))
            p.update()
            for w in p.wires:
                w.update_path()

        self.update()

    def name_label_rect(self):
        # Mux/Demux bodies are intentionally narrow; their names must not be
        # clipped to that body width. Share the measured extent with the scene
        # so fitting/selecting/exporting includes the entire visible label.
        metrics = QFontMetricsF(QFont("Segoe UI", 8))
        width = max(self.width + 50, metrics.horizontalAdvance(self.name) + 8)
        return QRectF((self.width-width)/2, self.height + 4, width, 20)

    def boundingRect(self):
        return QRectF(-25, -12, self.width + 50, self.height + 38).united(self.name_label_rect())

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width, self.height)
        border_col = QColor("#007ACC") if self.isSelected() else QColor("#333333")

        if self.block_type in ("Mux", "Demux"):
            painter.setPen(QPen(border_col, 2.0 if self.isSelected() else 1.0))
            painter.setBrush(QBrush(QColor("#1E1E1E")))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#333333"))
            painter.drawText(
                self.name_label_rect(),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self.name
            )
            return

        painter.setPen(QPen(border_col, 2.2 if self.isSelected() else 1.5))
        painter.setBrush(QBrush(QColor("#FFFFFF")))

        if self.block_type == "Sum":
            painter.drawEllipse(rect)
        elif self.block_type == "Gain":
            if self.flipped:
                poly = QPolygonF([QPointF(self.width, 0), QPointF(0, self.height / 2), QPointF(self.width, self.height)])
            else:
                poly = QPolygonF([QPointF(0, 0), QPointF(self.width, self.height / 2), QPointF(0, self.height)])
            painter.drawPolygon(poly)
        elif self.block_type in ("Inport", "Outport"):
            painter.drawRoundedRect(rect, 14, 14)
        elif self.block_type == "Subsystem":
            painter.drawRect(rect)
            painter.drawRect(QRectF(4, 4, self.width - 8, self.height - 8))
        else:
            painter.drawRect(rect)

        # ---- VECTORIZED SCHEMATIC BLOCK INTERIORS ----
        painter.setPen(QColor("#111111"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))

        if self.block_type == "Step":
            painter.setPen(QPen(QColor("#90A4AE"), 1.0))
            painter.drawLine(QPointF(16, 46), QPointF(self.width - 16, 46))
            painter.drawLine(QPointF(22, 12), QPointF(22, 50))
            painter.setPen(QPen(QColor("#0277BD"), 2.4))
            step_path = QPainterPath(QPointF(18, 42))
            step_path.lineTo(QPointF(44, 42))
            step_path.lineTo(QPointF(44, 18))
            step_path.lineTo(QPointF(self.width - 18, 18))
            painter.drawPath(step_path)

        elif self.block_type == "Sine Wave":
            painter.setPen(QPen(QColor("#90A4AE"), 1.0))
            painter.drawLine(QPointF(14, self.height / 2), QPointF(self.width - 14, self.height / 2))
            painter.drawLine(QPointF(20, 12), QPointF(20, self.height - 12))
            painter.setPen(QPen(QColor("#0277BD"), 2.2))
            sine_path = QPainterPath(QPointF(20, self.height / 2))
            w_span = self.width - 36
            for i in range(1, 33):
                u = i / 32.0
                px = 20 + u * w_span
                py = (self.height / 2) - 16.0 * math.sin(2.0 * math.pi * u)
                sine_path.lineTo(QPointF(px, py))
            painter.drawPath(sine_path)

        elif self.block_type == "Constant":
            painter.setPen(QPen(QColor("#90A4AE"), 1.0))
            painter.drawLine(QPointF(16, 44), QPointF(self.width - 16, 44))
            painter.setPen(QPen(QColor("#01579B"), 2.2))
            painter.drawLine(QPointF(16, 34), QPointF(self.width - 16, 34))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(QRectF(0, 8, self.width, 22), Qt.AlignmentFlag.AlignCenter,
                             str(self.params.get("value", "1.0")))

        elif self.block_type == "Gain":
            x_off = self.width * 0.28 if self.flipped else 0
            text = str(self.params.get("gain", "K"))
            if len(text) > 9:
                # Long matrices/vectors show the Simulink-style placeholder.
                painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                text = "K*u" if str(self.params.get("multiplication", "")).casefold().startswith("matrix") else "-K-"
            painter.drawText(QRectF(x_off, 0, self.width * 0.72, self.height),
                             Qt.AlignmentFlag.AlignCenter, text)

        elif self.block_type == "Sum":
            from octalink_engine_support import normalize_operators
            painter.setPen(QPen(QColor("#B0BEC5"), 1.0))
            painter.drawLine(QPointF(self.width / 2, 10), QPointF(self.width / 2, self.height - 10))
            painter.drawLine(QPointF(10, self.height / 2), QPointF(self.width - 10, self.height / 2))
            painter.setPen(QColor("#111111"))
            try:
                signs = normalize_operators(self.params.get("signs", "+-"), "+-")
            except ValueError:
                signs = "?" * len(self.in_ports)
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            sx = self.width - 18 if self.flipped else 10
            for idx, s in enumerate(signs[:len(self.in_ports)]):
                py = self.in_ports[idx].pos().y()
                painter.drawText(QPointF(sx, py + 4), s)

        elif self.block_type == "Product":
            from octalink_engine_support import normalize_operators
            try:
                ops = normalize_operators(self.params.get("ops", "**"), "*/")
            except ValueError:
                ops = "?"
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "×" if set(ops) == {"*"} else "÷×")
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            sx = self.width - 14 if self.flipped else 6
            for idx, op in enumerate(ops[:len(self.in_ports)]):
                py = self.in_ports[idx].pos().y()
                painter.drawText(QPointF(sx, py + 4), "×" if op == "*" else "÷")

        elif self.block_type == "Pulse Generator":
            painter.setPen(QPen(QColor("#90A4AE"), 1.0))
            painter.drawLine(QPointF(12, 44), QPointF(self.width - 12, 44))
            painter.setPen(QPen(QColor("#0277BD"), 2.2))
            pulse = QPainterPath(QPointF(12, 44))
            for x0 in (20, 50):
                pulse.lineTo(QPointF(x0, 44))
                pulse.lineTo(QPointF(x0, 18))
                pulse.lineTo(QPointF(x0 + 14, 18))
                pulse.lineTo(QPointF(x0 + 14, 44))
            pulse.lineTo(QPointF(self.width - 12, 44))
            painter.drawPath(pulse)

        elif self.block_type in ("Discrete Transfer Fcn", "Discrete Zero-Pole"):
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            if self.block_type == "Discrete Transfer Fcn":
                top = str(self.params.get("numerator", "[1]"))
                bottom = str(self.params.get("denominator", "[1 0.5]"))
            else:
                top = f"{self.params.get('gain', '1')}·Z{self.params.get('zeros', '[]')}"
                bottom = f"P{self.params.get('poles', '[]')}"
            top = top if len(top) <= 18 else top[:16] + "…"
            bottom = bottom if len(bottom) <= 18 else bottom[:16] + "…"
            painter.drawText(QRectF(4, 4, self.width - 8, 20), Qt.AlignmentFlag.AlignCenter, top)
            painter.drawLine(QPointF(10, self.height / 2 - 4), QPointF(self.width - 10, self.height / 2 - 4))
            painter.drawText(QRectF(4, self.height / 2 - 2, self.width - 8, 18), Qt.AlignmentFlag.AlignCenter, bottom)
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(QRectF(0, self.height - 16, self.width, 14), Qt.AlignmentFlag.AlignCenter,
                             f"z-domain, Ts={self.params.get('sample_time', '0.1')}")

        elif self.block_type == "Trig":
            op = self.params.get("operator", "sin")
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{op}(u)")

        elif self.block_type == "Octave Function":
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            expr = self.params.get("expression", "f(u,t)")
            disp = expr if len(expr) <= 16 else expr[:14] + "…"
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"f(u,t):\n{disp}")

        elif self.block_type == "Integrator":
            painter.setPen(QPen(QColor("#1B5E20"), 2.2))
            int_path = QPainterPath(QPointF(30, 14))
            int_path.cubicTo(QPointF(24, 14), QPointF(26, 46), QPointF(20, 46))
            painter.drawPath(int_path)
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(QRectF(28, 0, self.width - 32, self.height),
                             Qt.AlignmentFlag.AlignCenter, "1/s")

        elif self.block_type == "PID Controller":
            painter.setPen(QPen(QColor("#E65100"), 1.6))
            painter.drawLine(QPointF(16, 30), QPointF(30, 16))
            painter.drawLine(QPointF(16, 30), QPointF(30, 30))
            painter.drawLine(QPointF(16, 30), QPointF(30, 44))
            painter.setPen(QColor("#111111"))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(QRectF(28, 10, self.width - 32, 24), Qt.AlignmentFlag.AlignCenter, "PID(s)")
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(
                QRectF(24, 32, self.width - 28, 20), Qt.AlignmentFlag.AlignCenter,
                f"P:{self.params.get('Kp','')} I:{self.params.get('Ki','')} D:{self.params.get('Kd','')}"
            )

        elif self.block_type == "Transfer Fcn":
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            num_str = self.params.get("numerator", "[1]")
            den_str = self.params.get("denominator", "[1, 1]")
            painter.drawText(QRectF(4, 6, self.width - 8, 22), Qt.AlignmentFlag.AlignCenter, num_str)
            painter.drawLine(QPointF(10, self.height / 2), QPointF(self.width - 10, self.height / 2))
            painter.drawText(QRectF(4, self.height / 2 + 2, self.width - 8, 22),
                             Qt.AlignmentFlag.AlignCenter, den_str)

        elif self.block_type == "State-Space":
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "x' = Ax + Bu\ny  = Cx + Du")

        elif self.block_type == "Saturation":
            painter.setPen(QPen(QColor("#888888"), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(18, self.height / 2), QPointF(self.width - 18, self.height / 2))
            painter.drawLine(QPointF(self.width / 2, 10), QPointF(self.width / 2, self.height - 10))
            painter.setPen(QPen(QColor("#C62828"), 2.2))
            sat_path = QPainterPath(QPointF(20, self.height - 14))
            sat_path.lineTo(QPointF(34, self.height - 14))
            sat_path.lineTo(QPointF(self.width - 34, 14))
            sat_path.lineTo(QPointF(self.width - 20, 14))
            painter.drawPath(sat_path)

        elif self.block_type == "Relay":
            painter.setPen(QPen(QColor("#888888"), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(16, self.height / 2), QPointF(self.width - 16, self.height / 2))
            painter.drawLine(QPointF(self.width / 2, 10), QPointF(self.width / 2, self.height - 10))
            painter.setPen(QPen(QColor("#B71C1C"), 2.0))
            painter.drawLine(QPointF(20, 44), QPointF(54, 44))
            painter.drawLine(QPointF(54, 44), QPointF(54, 16))
            painter.drawLine(QPointF(34, 16), QPointF(68, 16))
            painter.drawLine(QPointF(34, 16), QPointF(34, 44))

        elif self.block_type == "Switch":
            painter.setPen(QPen(QColor("#37474F"), 2.0))
            painter.drawEllipse(QPointF(24, 16), 3, 3)
            painter.drawEllipse(QPointF(24, 50), 3, 3)
            painter.drawEllipse(QPointF(64, 33), 3, 3)
            painter.drawLine(QPointF(61, 33), QPointF(27, 18))
            painter.setPen(QPen(QColor("#007ACC"), 1.4, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(14, 33), QPointF(44, 33))
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QColor("#222222"))
            painter.drawText(QRectF(28, 42, 48, 16), Qt.AlignmentFlag.AlignCenter,
                             f"≥{self.params.get('threshold', '0')}")

        elif self.block_type == "Zero-Order Hold":
            painter.setPen(QPen(QColor("#00695C"), 2.0))
            zoh_path = QPainterPath(QPointF(18, 42))
            zoh_path.lineTo(QPointF(38, 42))
            zoh_path.lineTo(QPointF(38, 20))
            zoh_path.lineTo(QPointF(62, 20))
            zoh_path.lineTo(QPointF(62, 32))
            zoh_path.lineTo(QPointF(85, 32))
            painter.drawPath(zoh_path)
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(QRectF(0, 42, self.width, 16), Qt.AlignmentFlag.AlignCenter,
                             f"Ts={self.params.get('sample_time', '0.1')}")

        elif self.block_type == "Unit Delay":
            painter.drawText(QRectF(0, 6, self.width, 32), Qt.AlignmentFlag.AlignCenter, "1/z")
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(QRectF(0, 38, self.width, 18), Qt.AlignmentFlag.AlignCenter,
                             f"Ts={self.params.get('sample_time', '0.1')}")

        elif self.block_type in ("Inport", "Outport"):
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             f"{self.spec['symbol']}{self.params.get('port_number', '1')}")

        elif self.block_type == "Subsystem":
            # Simulink-style face: each port is labelled with its Inport/Outport
            # name inside the block, so the interface reads without opening it.
            boundary = {kind: sorted([b for b in (self.sub_scene.blocks if self.sub_scene else [])
                                      if b.block_type == kind],
                                     key=lambda b: int(b.params.get("port_number", 1)))
                        for kind in ("Inport", "Outport")}
            font = QFont("Segoe UI", 7)
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            painter.setPen(QColor("#1A3A5C"))
            half = self.width / 2 - 6
            for kind, ports in (("Inport", self.in_ports), ("Outport", self.out_ports)):
                left = (kind == "Inport") != self.flipped
                for port, boundary_block in zip(ports, boundary[kind]):
                    text = metrics.elidedText(boundary_block.name, Qt.TextElideMode.ElideRight, half)
                    y = port.pos().y() - 8
                    rect = QRectF(6, y, half, 16) if left else QRectF(self.width / 2, y, half, 16)
                    align = Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight
                    painter.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, text)
            if not boundary["Inport"] and not boundary["Outport"]:
                painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                painter.drawText(QRectF(0, 0, self.width, self.height), Qt.AlignmentFlag.AlignCenter, "Subsystem")

        elif self.block_type == "Scope":
            scr = QRectF(14, 10, self.width - 28, self.height - 20)
            painter.setPen(QPen(QColor("#37474F"), 1.5))
            painter.setBrush(QBrush(QColor("#121212")))
            painter.drawRoundedRect(scr, 4, 4)
            painter.setPen(QPen(QColor("#2E3B4E"), 0.8, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(scr.left(), scr.center().y()), QPointF(scr.right(), scr.center().y()))
            painter.drawLine(QPointF(scr.center().x(), scr.top()), QPointF(scr.center().x(), scr.bottom()))
            painter.setPen(QPen(QColor("#00E676"), 1.8))
            trace = QPainterPath(QPointF(scr.left() + 4, scr.center().y() + 6))
            trace.cubicTo(
                QPointF(scr.left() + 18, scr.top() + 2),
                QPointF(scr.right() - 18, scr.bottom() - 2),
                QPointF(scr.right() - 4, scr.center().y() - 6)
            )
            painter.drawPath(trace)

        elif self.block_type == "To CSV":
            doc = QRectF(24, 8, 40, 44)
            painter.setPen(QPen(QColor("#283593"), 1.6))
            painter.setBrush(QBrush(QColor("#FFFFFF")))
            painter.drawRoundedRect(doc, 3, 3)
            painter.drawLine(QPointF(30, 20), QPointF(58, 20))
            painter.drawLine(QPointF(30, 28), QPointF(58, 28))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(24, 32, 40, 18), Qt.AlignmentFlag.AlignCenter, "CSV")

        else:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.spec["symbol"])

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#333333"))
        label_rect = self.name_label_rect()
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.name)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Every block is a routing obstacle, even for signals it does not
            # drive. Moving it must refresh those routes as well as its ports.
            scene = self.scene()
            wires = set(getattr(scene, "wires", []))
            for port in self.in_ports + self.out_ports:
                wires.update(port.wires)
            for wire in wires:
                wire.update_path()
        return super().itemChange(change, value)


# ============================================================================
# 3. SCOPE, LINEAR ANALYSIS ADVISOR, ZOOM/PAN VIEW & SCENE
# ============================================================================
SIMULINK_TRACE_COLORS = ["#FFE600", "#00E676", "#00B0FF", "#FF5252", "#E040FB", "#FFAB40"]


class ScopeDialog(QDialog):
    def __init__(self, block: BlockItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"OctaLink Multi-Channel Scope — {block.name}")
        self.setWindowIcon(make_svg_icon("cat_Sinks"))
        self.resize(780, 520)
        layout = QVBoxLayout(self)

        fig = Figure(figsize=(7.2, 4.4), dpi=100)
        fig.patch.set_facecolor("#1E1E1E")
        self.canvas = FigureCanvas(fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setStyleSheet("background: #F0F0F0; color: #242424; border: none;")
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        ax = fig.add_subplot(111)
        ax.set_facecolor("#121212")
        if len(block.scope_t) > 0 and len(block.scope_y) > 0:
            y_matrix = np.array(block.scope_y, dtype=float)
            if y_matrix.ndim == 1:
                y_matrix = y_matrix.reshape(-1, 1)

            num_channels = y_matrix.shape[1]
            for ch in range(num_channels):
                color = SIMULINK_TRACE_COLORS[ch % len(SIMULINK_TRACE_COLORS)]
                label = (
                    block.scope_labels[ch]
                    if ch < len(block.scope_labels) else f"Channel {ch + 1}"
                )
                ax.plot(block.scope_t, y_matrix[:, ch], color=color, linewidth=2.0, label=label)

            ax.legend(facecolor="#1E1E1E", edgecolor="#444444", labelcolor="white", loc="best")
        else:
            ax.text(0.5, 0.5, "No simulation data yet. Click 'Run' first.",
                    color="#AAAAAA", ha="center", va="center", transform=ax.transAxes)

        ax.set_title(block.params.get("title", "Scope"), color="white", fontsize=11)
        ax.set_xlabel("Time (s)", color="#CCCCCC")
        ax.set_ylabel("Amplitude", color="#CCCCCC")
        ax.tick_params(colors="#CCCCCC")
        ax.grid(True, linestyle="--", alpha=0.3, color="#888888")
        fig.tight_layout()


class LinearAnalysisDialog(QDialog):
    """
    Displays the 4-panel Bode Magnitude, Bode Phase, Nyquist Plot, and Pole-Zero Map
    alongside Gain/Phase Stability Margins, Padé Delay order, and Step Response Metrics.
    """
    def __init__(self, analysis_data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OctaLink Linear Analysis Advisor (linmod + Padé Delays + Bode / Nyquist / Margins)")
        self.setWindowIcon(make_svg_icon("bode"))
        self.resize(1060, 720)
        layout = QVBoxLayout(self)

        metrics = analysis_data["step_metrics"]
        margins = analysis_data["margins"]
        poles = analysis_data["poles"]
        zeros = analysis_data["zeros"]
        poles_str = ", ".join(f"{p.real:.3f}{p.imag:+.3f}j" if abs(p.imag) > 1e-6 else f"{p.real:.3f}" for p in poles)
        zeros_str = ", ".join(f"{z.real:.3f}{z.imag:+.3f}j" if abs(z.imag) > 1e-6 else f"{z.real:.3f}" for z in zeros) or "None"

        gm_str = f"{margins['gain_margin_db']:.2f} dB (at {margins['w_pc']:.2f} rad/s)" if math.isfinite(margins["gain_margin_db"]) else "N/A (no measured crossover)"
        pm_str = f"{margins['phase_margin_deg']:.2f} deg (at {margins['w_gc']:.2f} rad/s)" if math.isfinite(margins["phase_margin_deg"]) else "N/A (no measured crossover)"

        summary_lbl = QLabel(
            f"<b>Realization Poles ({len(poles)} states):</b> [{poles_str}] &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>Zeros:</b> [{zeros_str}]<br>"
            f"<b>Selected Transfer Feedback Margins:</b> &nbsp; Gain Margin: <b>{gm_str}</b> &nbsp;|&nbsp; "
            f"Phase Margin: <b>{pm_str}</b><br>"
            f"<b>Step Response Metrics:</b> &nbsp; "
            f"Rise Time (10%→90%): <b>{metrics['rise_time']:.3f} s</b> &nbsp;|&nbsp; "
            f"Settling Time (±2%): <b>{metrics['settling_time']:.3f} s</b> &nbsp;|&nbsp; "
            f"Overshoot: <b>{metrics['overshoot_pct']:.2f}%</b> &nbsp;|&nbsp; "
            f"Steady-State Error: <b>{metrics['ss_error']:.4f}</b>"
        )
        summary_lbl.setStyleSheet(
            "background: #252526; color: #E0E0E0; padding: 10px; border-radius: 5px; font-size: 12px;"
        )
        summary_lbl.setWordWrap(True)
        layout.addWidget(summary_lbl)
        if analysis_data.get("notes"):
            notes = list(analysis_data["notes"])
            if margins.get("interpretation"):
                notes.append(margins["interpretation"])
            explanation = QLabel("\n".join(notes))
            explanation.setWordWrap(True)
            explanation.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(explanation)

        fig = Figure(figsize=(9.8, 5.6), dpi=100)
        fig.patch.set_facecolor("#1E1E1E")
        self.canvas = FigureCanvas(fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setStyleSheet("background: #F0F0F0; color: #242424; border: none;")
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        w = analysis_data["omega"]
        mag_db = analysis_data["mag_db"]
        phase_deg = analysis_data["phase_deg"]
        H = analysis_data["freq_resp"]

        # 1. Bode Magnitude
        ax1 = fig.add_subplot(221)
        ax1.set_facecolor("#121212")
        ax1.semilogx(w, mag_db, color="#00E676", linewidth=2.0, label="|T(jω)|")
        ax1.axhline(0.0, color="#777777", linestyle=":", linewidth=1.0)
        ax1.set_title("Bode Magnitude (dB)", color="white", fontsize=10)
        ax1.set_xlabel("Frequency (rad/s)", color="#CCCCCC", fontsize=9)
        ax1.set_ylabel("Magnitude (dB)", color="#CCCCCC", fontsize=9)
        ax1.tick_params(colors="#CCCCCC")
        ax1.grid(True, which="both", linestyle="--", alpha=0.3, color="#888888")

        # 2. Bode Phase
        ax2 = fig.add_subplot(223)
        ax2.set_facecolor("#121212")
        ax2.semilogx(w, phase_deg, color="#00B0FF", linewidth=2.0, label="∠T(jω)")
        ax2.axhline(-180.0, color="#FF5252", linestyle=":", linewidth=1.0)
        ax2.set_title("Bode Phase (deg)", color="white", fontsize=10)
        ax2.set_xlabel("Frequency (rad/s)", color="#CCCCCC", fontsize=9)
        ax2.set_ylabel("Phase (deg)", color="#CCCCCC", fontsize=9)
        ax2.tick_params(colors="#CCCCCC")
        ax2.grid(True, which="both", linestyle="--", alpha=0.3, color="#888888")

        # 3. Nyquist Diagram
        ax3 = fig.add_subplot(222)
        ax3.set_facecolor("#121212")
        ax3.plot(H.real, H.imag, color="#FFE600", linewidth=2.0, label="ω ≥ 0")
        ax3.plot(H.real, -H.imag, color="#FFE600", linewidth=1.2, linestyle="--", alpha=0.6, label="ω < 0")
        ax3.plot([-1.0], [0.0], marker="+", color="#FF5252", markersize=10, markeredgewidth=2, label="Critical (-1, 0)")
        ax3.set_title("Nyquist Contour", color="white", fontsize=10)
        ax3.set_xlabel("Real Axis", color="#CCCCCC", fontsize=9)
        ax3.set_ylabel("Imaginary Axis", color="#CCCCCC", fontsize=9)
        ax3.tick_params(colors="#CCCCCC")
        ax3.legend(facecolor="#1E1E1E", edgecolor="#444", labelcolor="white", fontsize=8)
        ax3.grid(True, linestyle="--", alpha=0.3, color="#888888")

        # 4. s-Plane Pole-Zero Map
        ax4 = fig.add_subplot(224)
        ax4.set_facecolor("#121212")
        ax4.axhline(0, color="#666666", linewidth=1.0)
        ax4.axvline(0, color="#666666", linewidth=1.0)
        if len(poles) > 0:
            ax4.scatter(poles.real, poles.imag, marker="x", color="#FF5252", s=80, linewidths=2.2, label="Poles (×)")
        if len(zeros) > 0:
            ax4.scatter(zeros.real, zeros.imag, marker="o", facecolors="none", edgecolors="#00E676", s=80, linewidths=2.0, label="Zeros (○)")
        ax4.set_title("s-Plane Pole-Zero Map", color="white", fontsize=10)
        ax4.set_xlabel("Real Axis (σ)", color="#CCCCCC", fontsize=9)
        ax4.set_ylabel("Imaginary Axis (jω)", color="#CCCCCC", fontsize=9)
        ax4.tick_params(colors="#CCCCCC")
        ax4.legend(facecolor="#1E1E1E", edgecolor="#444", labelcolor="white", fontsize=8)
        ax4.grid(True, linestyle="--", alpha=0.3, color="#888888")

        fig.tight_layout()


class ParamDialog(QDialog):
    def __init__(self, block: BlockItem, parent=None):
        super().__init__(parent)
        self.block = block
        self.setWindowTitle(f"Block Parameters: {block.name}")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(block.name)
        form.addRow(QLabel("Block Name:"), self.name_edit)

        self.inputs = {}
        for key, val in block.params.items():
            edit = QLineEdit(str(val))
            self.inputs[key] = edit
            form.addRow(QLabel(f"{key.replace('_', ' ').title()}:"), edit)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if self.block.parent_window:
            self.block.parent_window.push_undo_snapshot()
        new_name = self.name_edit.text().strip().replace(" ", "_")
        if new_name:
            self.block.name = new_name
        for k, edit in self.inputs.items():
            self.block.params[k] = edit.text().strip()
        self.block.rebuild_ports()
        if self.block.scene() and self.block.scene().owner_subsystem:
            self.block.scene().owner_subsystem.rebuild_ports()
        super().accept()


class SimCanvasView(QGraphicsView):
    """
    Simulink-style hardware-accelerated canvas view supporting cursor-anchored
    mouse-wheel zoom, middle-mouse panning, and Spacebar + Left-Click panning.
    """
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._panning = False
        self._space_pressed = False
        self._pan_start = QPointF()

    def wheelEvent(self, event):
        zoom_in = 1.15
        zoom_out = 1.0 / zoom_in
        factor = zoom_in if event.angleDelta().y() > 0 else zoom_out
        curr_scale = self.transform().m11()
        if 0.25 <= curr_scale * factor <= 4.0:
            self.scale(factor, factor)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_pressed
        ):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._space_pressed else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SimCanvasScene(QGraphicsScene):
    def __init__(self, parent_window, owner_subsystem=None):
        super().__init__()
        self.parent_window = parent_window
        self.owner_subsystem = owner_subsystem
        self.setSceneRect(0, 0, 2400, 1500)
        self.active_wire = None
        self.blocks = []
        self.wires = []

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#FFFFFF"))
        grid_size = 20
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)
        pen = QPen(QColor("#E6E6E6"), 1.0)
        painter.setPen(pen)
        for x in range(left, int(rect.right()), grid_size):
            for y in range(top, int(rect.bottom()), grid_size):
                painter.drawPoint(x, y)

    def add_sim_block(self, block_type, x, y, block_id=None, name=None, params=None, flipped=False):
        blk = BlockItem(
            block_type, x, y,
            block_id=block_id, name=name, params=params,
            flipped=flipped, parent_window=self.parent_window
        )
        self.addItem(blk)
        self.blocks.append(blk)
        for wire in self.wires:
            wire.update_path()
        if self.owner_subsystem and block_type in ("Inport", "Outport"):
            self.owner_subsystem.rebuild_ports()
        return blk

    def connect_ports(self, out_port: PortItem, in_port: PortItem):
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
        if self.views():
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
        if self.active_wire and self.views():
            item = self.itemAt(event.scenePos(), self.views()[0].transform())
            if (isinstance(item, PortItem) and not item.is_output and
                    item.parent_block != self.active_wire.start_port.parent_block):
                if self.parent_window:
                    self.parent_window.push_undo_snapshot()
                self.connect_ports(self.active_wire.start_port, item)
            self.removeItem(self.active_wire)
            self.active_wire = None
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.views():
            item = self.itemAt(event.scenePos(), self.views()[0].transform())
            if isinstance(item, PortItem):
                item = item.parent_block
            if isinstance(item, BlockItem):
                if item.block_type == "Subsystem":
                    self.parent_window.open_subsystem_scene(item.sub_scene)
                elif item.block_type == "Scope":
                    ScopeDialog(item, self.parent_window).exec()
                else:
                    ParamDialog(item, self.parent_window).exec()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selectedItems() and self.parent_window:
                self.parent_window.push_undo_snapshot()
            for item in list(self.selectedItems()):
                if isinstance(item, WireItem):
                    self.remove_wire(item)
                elif isinstance(item, BlockItem):
                    for port in item.in_ports + item.out_ports:
                        for w in list(port.wires):
                            self.remove_wire(w)
                    self.blocks.remove(item)
                    self.removeItem(item)
                    if self.owner_subsystem and item.block_type in ("Inport", "Outport"):
                        self.owner_subsystem.rebuild_ports()
        super().keyPressEvent(event)


# ============================================================================
# 4. COMPILER, PADE LINMOD ANALYZER, OCTAVE .M & EMBEDDED ANSI C99 GENERATOR
# ============================================================================
class SimulationEngine:
    def __init__(self):
        # The MVP runs locally with NumPy/RK4. Installing oct2py must not
        # launch a subprocess or make opening the editor depend on Octave.
        self.octave = None
        # Model Workspace: resolved scalar and array variables (see
        # octalink_engine_support.resolve_variables). compile_graph sets them
        # from the root diagram's ``variables`` record.
        self.variables = {}
        self.array_variables = {}
        self.signal_widths = {}
        self.algebraic_loops = []

    def set_variables(self, raw):
        from octalink_engine_support import resolve_variables
        self.variables, self.array_variables = resolve_variables(raw or {})

    @staticmethod
    def _translate_expr_to_c(expr_str: str, u_ref: str) -> str:
        """Word-boundary safe translation of user Octave expressions into C99."""
        s = re.sub(r"\bu\b", f"({u_ref})", expr_str.strip())
        s = re.sub(
            r"(\([^)]+\)|[A-Za-z0-9_.]+)\s*\^\s*(\([^)]+\)|[A-Za-z0-9_.]+)",
            r"pow(\1, \2)",
            s
        )
        return s

    @staticmethod
    def _translate_expr_to_m(expr_str: str, u_ref: str) -> str:
        """Word-boundary safe translation of user Octave expressions into .m code."""
        return re.sub(r"\bu\b", f"({u_ref})", expr_str.strip())

    def eval_scalar(self, expr_str: str) -> float:
        from octalink_engine_support import evaluate_expression
        text = str(expr_str).strip()
        if text in self.array_variables:
            raise ValueError(f"{text} is an array variable; this parameter requires a scalar.")
        return evaluate_expression(text, variables=self.variables)

    def _array_rows(self, expr_str):
        from octalink_engine_support import parse_array
        s = str(expr_str).strip()
        if s in self.array_variables:
            return [list(row) for row in self.array_variables[s]]
        if s.startswith("["):
            # MATLAB spacing: "[1 -2]" has two elements, "[1 - 2]" one.
            return parse_array(s, self.variables)
        if "[" in s or "]" in s:
            raise ValueError("Array expression has an unmatched bracket.")
        return [[self.eval_scalar(s)]]

    def eval_vector(self, expr_str: str):
        return [value for row in self._array_rows(expr_str) for value in row]

    def eval_matrix(self, expr_str: str) -> np.ndarray:
        rows = self._array_rows(expr_str)
        if not rows:
            return np.zeros((0, 0), dtype=float)
        if len({len(row) for row in rows}) != 1:
            raise ValueError("Matrix rows must all have the same length.")
        return np.array(rows, dtype=float)

    def eval_user_expr(self, expr_str: str, u_val, t_val: float) -> float:
        from octalink_engine_support import evaluate_expression
        u_arr = self._as_vector(u_val)
        u_scalar = u_arr[0] if len(u_arr) > 0 else 0.0
        return evaluate_expression(expr_str, {"u": u_scalar, "u_vec": u_arr, "t": float(t_val)},
                                   variables=self.variables)

    def flatten_hierarchy(self, root_scene: SimCanvasScene):
        prim_blocks = []

        def collect(scene: SimCanvasScene):
            for b in scene.blocks:
                if b.block_type == "Subsystem":
                    collect(b.sub_scene)
                elif b.block_type not in ("Inport", "Outport"):
                    prim_blocks.append(b)

        collect(root_scene)

        def resolve_source(in_port: PortItem, visited=None):
            if visited is None:
                visited = set()
            if in_port in visited or not in_port.wires:
                return None
            if len(in_port.wires) != 1:
                raise ValueError("An input port must have exactly one incoming wire.")
            visited.add(in_port)

            src_port = in_port.wires[0].start_port
            src_blk = src_port.parent_block

            if src_blk.block_type == "Inport":
                parent_sub = src_blk.scene().owner_subsystem
                if parent_sub is None:
                    return None
                inports = sorted(
                    [b for b in src_blk.scene().blocks if b.block_type == "Inport"],
                    key=lambda b: int(b.params.get("port_number", 1))
                )
                idx = inports.index(src_blk)
                if idx < len(parent_sub.in_ports):
                    return resolve_source(parent_sub.in_ports[idx], visited)
                return None

            if src_blk.block_type == "Subsystem":
                outports = sorted(
                    [b for b in src_blk.sub_scene.blocks if b.block_type == "Outport"],
                    key=lambda b: int(b.params.get("port_number", 1))
                )
                if src_port.index < len(outports):
                    out_blk = outports[src_port.index]
                    return resolve_source(out_blk.in_ports[0], visited)
                return None

            return (src_blk, src_port.index)

        def visible_name(in_port):
            # The signal as drawn in the consumer's own diagram: a subsystem's
            # name (plus its outport when it has several), never a primitive
            # hidden inside it -- two motor subsystems must not both read "Speed".
            if len(in_port.wires) != 1:
                return None
            src_port = in_port.wires[0].start_port
            src_blk = src_port.parent_block
            if src_blk.block_type == "Subsystem" and len(src_blk.out_ports) > 1:
                outports = sorted([b for b in src_blk.sub_scene.blocks if b.block_type == "Outport"],
                                  key=lambda b: int(b.params.get("port_number", 1)))
                if src_port.index < len(outports):
                    return f"{src_blk.name}/{outports[src_port.index].name}"
            return src_blk.name

        source_map = {}
        self.signal_names = {}
        for b in prim_blocks:
            source_map[b] = [resolve_source(p) for p in b.in_ports]
            for index, port in enumerate(b.in_ports):
                self.signal_names[(b, index)] = visible_name(port)

        return prim_blocks, source_map

    def prepare_blocks(self, blocks):
        """Parse and validate block semantics independently of draft wiring.

        The inspector and compiler share this gate, so applying a parameter
        cannot commit text that the simulation engine would reject.
        """
        parsed = {}
        state_slices = {}
        ss_models = {}
        has_direct_ft = {}
        total_states = 0

        from octalink_engine_support import normalize_operators
        for b in blocks:
            p = {}
            for k, v in b.params.items():
                try:
                    if k in ("signs", "ops", "operator", "expression", "title", "filename", "multiplication"):
                        p[k] = str(v).strip()
                    elif k in ("numerator", "denominator", "x0", "zeros", "poles"):
                        p[k] = self.eval_vector(v)
                    elif k in ("A", "B", "C", "D") or (k == "gain" and b.block_type == "Gain"):
                        p[k] = self.eval_matrix(v)
                    else:
                        p[k] = self.eval_scalar(v)
                except ValueError as exc:
                    raise ValueError(f"{b.name}: invalid {k}: {exc}") from exc
            discrete = ("Unit Delay", "Zero-Order Hold", "Discrete Transfer Fcn", "Discrete Zero-Pole")
            if b.block_type in discrete and p["sample_time"] <= 0:
                raise ValueError(f"{b.name}: sample_time must be positive.")
            if b.block_type == "Saturation" and p["lower_limit"] > p["upper_limit"]:
                raise ValueError(f"{b.name}: lower_limit must not exceed upper_limit.")
            if b.block_type == "Relay" and p["switch_off_point"] > p["switch_on_point"]:
                raise ValueError(f"{b.name}: switch_off_point must not exceed switch_on_point.")
            for kind, key, allowed in (("Sum", "signs", "+-"), ("Product", "ops", "*/")):
                if b.block_type == kind:
                    try:
                        p[key] = normalize_operators(p[key], allowed)
                    except ValueError as exc:
                        raise ValueError(f"{b.name}: invalid {key}: {exc}") from None
                    if len(p[key]) != len(b.in_ports):
                        raise ValueError(f"{b.name}: {key} must provide {' or '.join(allowed)} for each input.")
            if b.block_type == "Gain":
                gain = p["gain"]
                if gain.size == 0:
                    raise ValueError(f"{b.name}: gain must not be empty.")
                mode = p["multiplication"].replace(" ", "").casefold()
                if mode.startswith("matrix"):
                    p["matrix_gain"] = True
                elif mode.startswith("element"):
                    p["matrix_gain"] = False
                else:
                    raise ValueError(f"{b.name}: multiplication must be Element-wise(K.*u) or Matrix(K*u).")
                if not p["matrix_gain"] and gain.ndim == 2 and min(gain.shape) > 1:
                    raise ValueError(f"{b.name}: element-wise gain must be a scalar or vector; use Matrix(K*u).")
                p["gain"] = float(gain[0, 0]) if gain.shape == (1, 1) else gain
            if b.block_type == "Pulse Generator":
                if p["period"] <= 0:
                    raise ValueError(f"{b.name}: period must be positive.")
                if not 0 < p["pulse_width"] < 100:
                    raise ValueError(f"{b.name}: pulse_width must be a percentage strictly between 0 and 100.")
                if p["phase_delay"] < 0:
                    raise ValueError(f"{b.name}: phase_delay must be nonnegative.")
            if b.block_type == "Trig" and p["operator"] not in ("sin", "cos", "tan", "asin", "acos", "atan", "tanh"):
                raise ValueError(f"{b.name}: unsupported trigonometric operator.")
            if b.block_type in ("Mux", "Demux"):
                key = "inputs" if b.block_type == "Mux" else "outputs"
                count = p[key]
                actual = len(b.in_ports) if key == "inputs" else len(b.out_ports)
                if count != int(count) or not 2 <= count <= 256 or count != actual:
                    raise ValueError(f"{b.name}: {key} must match the port count (2 to 256).")
            if b.block_type == "PID Controller" and p["N"] <= 0:
                raise ValueError(f"{b.name}: derivative filter N must be positive.")
            if b.block_type == "Octave Function":
                from octalink_engine_support import parse_expression
                try:
                    parse_expression(p["expression"], allow_signal=True,
                                     variable_names=frozenset(self.variables))
                except ValueError as exc:
                    raise ValueError(f"{b.name}: invalid expression: {exc}") from exc
            parsed[b] = p

            if b.block_type == "Integrator":
                state_slices[b] = slice(total_states, total_states + 1)
                total_states += 1
                has_direct_ft[b] = False
            elif b.block_type == "PID Controller":
                state_slices[b] = slice(total_states, total_states + 2)
                total_states += 2
                has_direct_ft[b] = True
            elif b.block_type == "Transfer Fcn":
                if not p["numerator"] or not p["denominator"]:
                    raise ValueError(f"{b.name}: transfer polynomials must not be empty.")
                A, B, C, D = tf2ss_canonical(p["numerator"], p["denominator"])
                if not all(np.all(np.isfinite(value)) for value in (A, B, C, D)):
                    raise ValueError(f"{b.name}: transfer realization is non-finite.")
                ss_models[b] = (A, B, C, D)
                n_s = A.shape[0]
                state_slices[b] = slice(total_states, total_states + n_s)
                total_states += n_s
                has_direct_ft[b] = D != 0.0
            elif b.block_type == "State-Space":
                A = p["A"]
                n_s = A.shape[0]
                if n_s < 1 or A.shape != (n_s, n_s):
                    raise ValueError(f"{b.name}: A must be a nonempty square matrix.")
                # Single input; C may have several rows (vector output, e.g.
                # C = eye(n) for full-state feedback). D is p-by-1 or 0.
                n_out = p["C"].shape[0]
                if p["B"].shape != (n_s, 1) or p["C"].ndim != 2 or p["C"].shape[1] != n_s or not 1 <= n_out <= 64:
                    raise ValueError(f"{b.name}: B must be n-by-1 and C must be p-by-n (1 <= p <= 64).")
                if len(p["x0"]) != n_s:
                    raise ValueError(f"{b.name}: x0 must contain exactly {n_s} initial states.")
                D = p["D"]
                if D.shape == (1, 1) and (n_out == 1 or D[0, 0] == 0):
                    D = np.full((n_out, 1), D[0, 0])
                if D.shape != (n_out, 1):
                    raise ValueError(f"{b.name}: D must be p-by-1 ({n_out}-by-1) or a scalar.")
                B = p["B"]
                C = p["C"]
                D = float(D[0, 0]) if n_out == 1 else D
                ss_models[b] = (A, B, C, D)
                state_slices[b] = slice(total_states, total_states + n_s)
                total_states += n_s
                has_direct_ft[b] = bool(np.any(np.asarray(D) != 0.0))
            elif b.block_type in ("Discrete Transfer Fcn", "Discrete Zero-Pole"):
                if b.block_type == "Discrete Zero-Pole":
                    if len(p["zeros"]) > len(p["poles"]):
                        raise ValueError(f"{b.name}: improper zero-pole model (more zeros than poles).")
                    numerator = list(p["gain"] * np.poly(p["zeros"])) if p["zeros"] else [p["gain"]]
                    denominator = list(np.poly(p["poles"])) if p["poles"] else [1.0]
                else:
                    numerator, denominator = p["numerator"], p["denominator"]
                if not numerator or not denominator:
                    raise ValueError(f"{b.name}: transfer polynomials must not be empty.")
                # Same controllable canonical algebra as the continuous block,
                # in powers of z; states advance only at sample hits.
                A, B, C, D = tf2ss_canonical(numerator, denominator)
                if not all(np.all(np.isfinite(value)) for value in (A, B, C, D)):
                    raise ValueError(f"{b.name}: transfer realization is non-finite.")
                ss_models[b] = (A, B, C, D)
                has_direct_ft[b] = D != 0.0
            else:
                has_direct_ft[b] = b.spec["direct_feedthrough"]

        return parsed, state_slices, ss_models, has_direct_ft, total_states

    def compile_graph(self, root_scene: SimCanvasScene):
        self.set_variables(getattr(root_scene, "variables", None))
        blocks, source_map = self.flatten_hierarchy(root_scene)
        if not blocks:
            raise ValueError("The model contains no simulation blocks.")
        for block in blocks:
            for index, source in enumerate(source_map[block]):
                if source is None:
                    raise ValueError(f"{block.name}: input {index + 1} is unconnected or unresolved.")
                if source[0] not in blocks or not 0 <= source[1] < len(source[0].out_ports):
                    raise ValueError(f"{block.name}: input {index + 1} has an invalid source port.")
        parsed, state_slices, ss_models, has_direct_ft, total_states = self.prepare_blocks(blocks)
        sorted_direct, self.algebraic_loops = self.order_direct(blocks, source_map, has_direct_ft)
        self.signal_widths = self._infer_widths(blocks, source_map, parsed, ss_models,
                                                has_direct_ft, sorted_direct, self.algebraic_loops)
        return blocks, source_map, parsed, state_slices, ss_models, has_direct_ft, sorted_direct, total_states

    class AlgebraicLoop:
        """A cycle of direct-feedthrough blocks, solved by Newton on its cut signals.

        ``members`` is an evaluation order of the loop in which each cut block's
        consumers read the current guess; ``cuts`` are scalar loop variables.
        """
        def __init__(self, cuts, members):
            self.cuts, self.members = cuts, members
            self.cut_set = frozenset(cuts)
            self.name = ", ".join(b.name for b in cuts)

    # Never loop variables: their outputs are vectors by construction.
    UNCUTTABLE = ("Mux", "Demux", "Scope", "To CSV")

    def order_direct(self, blocks, source_map, has_direct_ft):
        """Evaluation order of direct-feedthrough blocks, plus algebraic loops.

        Acyclic diagrams keep the original Kahn order. Each strongly connected
        component is cut greedily (largest in*out degree first) until the rest
        is acyclic, as Simulink's algebraic-loop solver chooses loop variables.
        """
        from octalink_engine_support import AlgebraicLoopError, cyclic_components
        direct_blocks = [b for b in blocks if has_direct_ft[b]]
        position = {b: i for i, b in enumerate(blocks)}
        successors = {b: [] for b in direct_blocks}
        for b in direct_blocks:
            for conn in source_map[b]:
                if conn is not None and conn[0] in successors:
                    successors[conn[0]].append(b)

        def kahn(nodes, edges):
            degree = {b: 0 for b in nodes}
            for b in nodes:
                for nxt in edges[b]:
                    degree[nxt] += 1
            queue = deque([b for b in nodes if degree[b] == 0])
            order = []
            while queue:
                curr = queue.popleft()
                order.append(curr)
                for nxt in edges[curr]:
                    degree[nxt] -= 1
                    if degree[nxt] == 0:
                        queue.append(nxt)
            return order

        cyclic = cyclic_components(direct_blocks, successors)
        if not cyclic:
            return kahn(direct_blocks, successors), []
        loops = []
        for component in cyclic:
            members = sorted(component, key=position.get)
            cuts = []
            while True:
                rest = [b for b in members if b not in cuts]
                kept = set(rest)
                rest_edges = {b: [n for n in successors[b] if n in kept] for b in rest}
                remaining = cyclic_components(rest, rest_edges)
                if not remaining:
                    break
                for cycle in remaining:
                    inside = set(cycle)
                    candidates = [b for b in cycle if b.block_type not in self.UNCUTTABLE]
                    if not candidates:
                        raise AlgebraicLoopError(
                            "Algebraic loop through " + ", ".join(b.name for b in sorted(cycle, key=position.get))
                            + " has no scalar signal to solve for; insert a Unit Delay, Integrator or "
                              "strictly proper block in the loop.")

                    def score(b):
                        fan_in = sum(rest_edges[p].count(b) for p in cycle)
                        fan_out = sum(1 for n in rest_edges[b] if n in inside)
                        return (-fan_in * fan_out, position[b])
                    cuts.append(min(candidates, key=score))
            cuts.sort(key=position.get)
            inside = set(members)
            loop_edges = {b: [] if b in cuts else [n for n in successors[b] if n in inside] for b in members}
            loops.append(self.AlgebraicLoop(cuts, kahn(members, loop_edges)))
        # Condensation order: each loop is evaluated as one unit, after its inputs.
        unit = {b: b for b in direct_blocks}
        for loop in loops:
            for b in loop.members:
                unit[b] = loop
        units = list(dict.fromkeys(unit[b] for b in direct_blocks))
        unit_edges = {u: [] for u in units}
        for b in direct_blocks:
            for nxt in successors[b]:
                if unit[nxt] is not unit[b]:
                    unit_edges[unit[b]].append(unit[nxt])
        order = []
        for u in kahn(units, unit_edges):
            order.extend(u.members if isinstance(u, self.AlgebraicLoop) else [u])
        return order, loops

    VECTOR_INPUT_BLOCKS = ("Mux", "Demux", "Scope", "To CSV", "Octave Function", "Gain")
    DISCRETE_BLOCKS = ("Unit Delay", "Zero-Order Hold", "Discrete Transfer Fcn", "Discrete Zero-Pole")

    def _infer_widths(self, blocks, source_map, parsed, ss_models, has_direct_ft, sorted_direct, loops=()):
        """Static output widths; Demux records its channel count (1 per port).

        Scalar-only blocks reject vectors before any simulation starts.
        Algebraic-loop cuts are read before they are computed, so they are
        scalar by contract and checked once their own width is known.
        """
        widths = {c: 1 for loop in loops for c in loop.cuts}
        cut_blocks = set(widths)

        def input_width(conn):
            src, _ = conn
            return 1 if src.block_type == "Demux" else widths[src]

        def output_width(b):
            kind, p = b.block_type, parsed[b]
            if kind == "State-Space":
                return ss_models[b][2].shape[0]
            if kind == "Demux":
                return int(p["outputs"])
            if not has_direct_ft[b]:
                return 1
            inputs = [input_width(c) for c in source_map[b]]
            if kind == "Mux":
                return sum(inputs)
            if kind == "Demux":
                return int(p["outputs"])
            if kind in ("Scope", "To CSV"):
                return inputs[0]
            if kind == "Gain":
                gain, n = p["gain"], inputs[0]
                if isinstance(gain, float):
                    return n
                if p["matrix_gain"]:
                    if gain.shape[1] != n:
                        raise ValueError(f"{b.name}: Matrix(K*u) needs K with {n} columns; K is "
                                         f"{gain.shape[0]}-by-{gain.shape[1]}.")
                    return gain.shape[0]
                if n not in (1, gain.size):
                    raise ValueError(f"{b.name}: element-wise gain has {gain.size} elements but the input has {n}.")
                return gain.size
            return 1

        for b in [b for b in blocks if not has_direct_ft[b]] + sorted_direct:
            widths[b] = output_width(b)
            if b in cut_blocks and widths[b] != 1:
                from octalink_engine_support import AlgebraicLoopError
                raise AlgebraicLoopError(f"{b.name}: an algebraic loop variable must be a scalar signal; "
                                         f"this block outputs {widths[b]} channels.")
        for b in blocks:
            if b.block_type in self.VECTOR_INPUT_BLOCKS and b.block_type != "Demux":
                continue
            for index, conn in enumerate(source_map[b]):
                width = input_width(conn)
                if b.block_type == "Demux":
                    if width != int(parsed[b]["outputs"]):
                        raise ValueError(f"{b.name}: Demux expects {int(parsed[b]['outputs'])} channels, receives {width}.")
                elif width != 1:
                    raise ValueError(f"{b.name}: input {index + 1} receives a {width}-element vector; "
                                     "this block is scalar, use Demux to select a channel.")
        return widths

    @staticmethod
    def _is_sample_hit(step: int, dt: float, ts: float) -> bool:
        if ts <= 0 or step == 0:
            return True
        t_curr = step * dt
        t_prev = (step - 1) * dt
        eps = 1e-9 * max(1.0, ts)
        return math.floor((t_curr + eps) / ts) > math.floor((t_prev + eps) / ts)

    @staticmethod
    def _as_scalar(val) -> float:
        if isinstance(val, (list, tuple, np.ndarray)):
            if len(val) != 1:
                raise ValueError("A scalar block received a vector; use Demux to select a channel.")
            return float(val[0])
        return float(val)

    @staticmethod
    def _as_vector(val) -> list:
        if isinstance(val, (list, tuple, np.ndarray)):
            return [float(x) for x in val]
        return [float(val)]

    @staticmethod
    def _extract_port_signal(out_signals: dict, conn):
        if conn is None:
            raise ValueError("An input is unconnected.")
        src_blk, port_idx = conn
        if src_blk not in out_signals:
            raise ValueError(f"Signal from {src_blk.name} is unavailable in the evaluation order.")
        val = out_signals[src_blk]
        if src_blk.block_type == "Demux":
            vec = val if isinstance(val, list) else [float(val)]
            if port_idx >= len(vec):
                raise ValueError(f"{src_blk.name}: unavailable Demux output {port_idx + 1}.")
            return vec[port_idx]
        return val

    def _resolve_scope_labels(self, scope_blk, source_map):
        names = getattr(self, "signal_names", {})

        def channel_labels(block, index):
            source = source_map[block][index] if len(source_map[block]) > index else None
            if source is None:
                raise ValueError("A scope input is unconnected.")
            src, port_idx = source
            if src.block_type == "Mux":
                return [label for i in range(len(source_map[src])) for label in channel_labels(src, i)]
            visible = names.get((block, index)) or src.name
            hidden = visible != src.name          # the driver lives inside a subsystem
            if src.block_type == "Demux":
                return [visible if hidden else f"{src.name}[{port_idx + 1}]"]
            width = self.signal_widths.get(src, 1)
            return [f"{visible}[{i + 1}]" for i in range(width)] if width > 1 else [visible]
        return channel_labels(scope_blk, 0)

    @staticmethod
    def pulse_value(p, t):
        """Simulink time-based Pulse Generator, right-continuous at edges.

        The edge arithmetic (phase + k*period, + period*width/100) is emitted
        identically by the Octave and C generators.
        """
        phase, period = p["phase_delay"], p["period"]
        if t < phase:
            return 0.0
        k = math.floor((t - phase) / period)
        if phase + k * period > t:
            k -= 1
        elif phase + (k + 1) * period <= t:
            k += 1
        start = phase + k * period
        return p["amplitude"] if t < start + period * p["pulse_width"] / 100.0 else 0.0

    @staticmethod
    def source_events(blocks, parsed, t_stop):
        """Source discontinuities in (0, t_stop]: Step times and pulse edges."""
        events = {parsed[b]["step_time"] for b in blocks if b.block_type == "Step"
                  and 0 < parsed[b]["step_time"] <= t_stop}
        for b in blocks:
            if b.block_type != "Pulse Generator":
                continue
            p = parsed[b]
            count = math.floor((t_stop - p["phase_delay"]) / p["period"]) + 1 if t_stop >= p["phase_delay"] else 0
            if count > 250000:
                raise ValueError(f"{b.name}: more than 250000 pulses before the stop time; increase the period.")
            for k in range(max(0, count)):
                start = p["phase_delay"] + k * p["period"]
                for edge in (start, start + p["period"] * p["pulse_width"] / 100.0):
                    if 0 < edge <= t_stop:
                        events.add(edge)
        return events

    def _initial_state_vector(self, state_slices, parsed, total_states):
        X = np.zeros(total_states, dtype=float)
        for b, sl in state_slices.items():
            if b.block_type == "Integrator":
                X[sl] = parsed[b]["initial_condition"]
            elif b.block_type == "State-Space":
                x0_vec = parsed[b]["x0"]
                n_s = sl.stop - sl.start
                for i in range(min(n_s, len(x0_vec))):
                    X[sl.start + i] = x0_vec[i]
        return X

    def _build_evaluator(self, blocks, source_map, parsed, state_slices, ss_models,
                         has_direct_ft, sorted_direct, total_states, Z_delay, Z_zoh, Z_relay, dt=0.01,
                         Z_dtf=None, algebraic_loops=()):
        Z_dtf = {} if Z_dtf is None else Z_dtf
        discrete_tf = ("Discrete Transfer Fcn", "Discrete Zero-Pole")

        def hit_now(b, update_discrete, step_idx, sample_hits):
            if not update_discrete:
                return False
            if sample_hits is not None:
                return b in sample_hits
            return self._is_sample_hit(step_idx, dt, parsed[b]["sample_time"])

        def state_output(b, state_vec):
            A, B, C, D = ss_models[b]
            if not A.shape[0]:
                return 0.0
            y = C @ state_vec[state_slices[b]].reshape(-1, 1)
            return float(y[0, 0]) if y.shape[0] == 1 else [float(v) for v in y.ravel()]

        def direct_output(b, t, state_vec, out_signals, update_discrete, step_idx, sample_hits):
            """Output of one direct-feedthrough block from the signals computed so far."""
            p = parsed[b]
            raw_inputs = [
                self._extract_port_signal(out_signals, conn)
                for conn in source_map[b]
            ]
            vector_block = b.block_type in self.VECTOR_INPUT_BLOCKS
            u0 = self._as_scalar(raw_inputs[0]) if raw_inputs and not vector_block else 0.0

            if b.block_type == "Gain":
                gain, u_vec = p["gain"], self._as_vector(raw_inputs[0])
                if isinstance(gain, float):
                    result = [gain * value for value in u_vec]
                elif p["matrix_gain"]:
                    if gain.shape[1] != len(u_vec):
                        raise ValueError(f"{b.name}: Matrix(K*u) dimension mismatch.")
                    result = [float(v) for v in gain @ np.asarray(u_vec)]
                else:
                    flat = gain.ravel()
                    if len(u_vec) not in (1, flat.size):
                        raise ValueError(f"{b.name}: element-wise gain dimension mismatch.")
                    result = [float(k * u) for k, u in zip(flat, u_vec * flat.size if len(u_vec) == 1 else u_vec)]
                return result[0] if len(result) == 1 else result
            elif b.block_type in discrete_tf:
                if hit_now(b, update_discrete, step_idx, sample_hits):
                    A, B, C, D = ss_models[b]
                    cx = float((C @ Z_dtf[b]["x"].reshape(-1, 1))[0, 0]) if A.shape[0] else 0.0
                    Z_dtf[b]["y"] = cx + D * u0
                return Z_dtf[b]["y"]
            elif b.block_type == "Saturation":
                return min(max(u0, p["lower_limit"]), p["upper_limit"])
            elif b.block_type == "Relay":
                if update_discrete:
                    if u0 >= p["switch_on_point"]:
                        Z_relay[b] = p["on_val"]
                    elif u0 <= p["switch_off_point"]:
                        Z_relay[b] = p["off_val"]
                return Z_relay[b]
            elif b.block_type == "Switch":
                u1 = self._as_scalar(raw_inputs[1]) if len(raw_inputs) > 1 else 0.0
                u2 = self._as_scalar(raw_inputs[2]) if len(raw_inputs) > 2 else 0.0
                return u0 if u1 >= p["threshold"] else u2
            elif b.block_type == "Trig":
                op = p["operator"]
                trig_map = {
                    "sin": math.sin, "cos": math.cos, "tan": math.tan,
                    "asin": math.asin, "acos": math.acos, "atan": math.atan, "tanh": math.tanh
                }
                return trig_map.get(op, math.sin)(u0)
            elif b.block_type == "Octave Function":
                return self.eval_user_expr(p["expression"], raw_inputs[0] if raw_inputs else 0.0, t)
            elif b.block_type == "Product":
                ops = p["ops"]
                acc = 1.0
                for idx, val in enumerate(raw_inputs):
                    op_ch = ops[idx] if idx < len(ops) else "*"
                    s_val = self._as_scalar(val)
                    if op_ch == "/":
                        if s_val == 0.0:
                            raise ValueError(f"{b.name}: division by zero at t={t:g}.")
                        acc = acc / s_val
                    else:
                        acc = acc * s_val
                return acc
            elif b.block_type == "Zero-Order Hold":
                hit = b in sample_hits if sample_hits is not None else self._is_sample_hit(step_idx, dt, p["sample_time"])
                if update_discrete and hit:
                    Z_zoh[b] = u0
                return Z_zoh[b]
            elif b.block_type == "Sum":
                signs = p["signs"]
                total = 0.0
                for idx, val in enumerate(raw_inputs):
                    s = signs[idx] if idx < len(signs) else "+"
                    scalar_val = self._as_scalar(val)
                    total += scalar_val if s == "+" else -scalar_val
                return total
            elif b.block_type == "PID Controller":
                x_I, x_D = state_vec[state_slices[b]]
                Kp, Ki, Kd, N = p["Kp"], p["Ki"], p["Kd"], p["N"]
                return Kp * u0 + Ki * x_I + Kd * N * (u0 - x_D)
            elif b.block_type in ("Transfer Fcn", "State-Space"):
                D = ss_models[b][3]
                cx = state_output(b, state_vec)
                if isinstance(cx, list):
                    return [c + float(d) * u0 for c, d in zip(cx, np.ravel(D))]
                else:
                    return cx + D * u0
            elif b.block_type == "Mux":
                vec = []
                for val in raw_inputs:
                    vec.extend(self._as_vector(val))
                return vec
            elif b.block_type == "Demux":
                in_vec = self._as_vector(raw_inputs[0]) if raw_inputs else [0.0]
                num_out = max(2, int(p["outputs"]))
                if len(in_vec) != num_out:
                    raise ValueError(f"{b.name}: Demux expects {num_out} channels, received {len(in_vec)}.")
                return in_vec
            elif b.block_type in ("Scope", "To CSV"):
                return self._as_vector(raw_inputs[0]) if raw_inputs else [0.0]

        from octalink_engine_support import solve_algebraic_loop
        loop_of = {b: loop for loop in algebraic_loops for b in loop.members}
        plan = list(dict.fromkeys(loop_of.get(b, b) for b in sorted_direct))
        # Warm starts persist across evaluations of this run (as Simulink's do).
        guesses = {loop: np.zeros(len(loop.cuts)) for loop in algebraic_loops}

        def solve_loop(loop, t, state_vec, out_signals, update_discrete, step_idx, sample_hits):
            # Held values a member may set at this major step are restored before
            # every trial, so each residual is a function of the guess alone.
            held = []
            if update_discrete:
                for b in loop.members:
                    if b in Z_zoh:
                        held.append((Z_zoh, b, Z_zoh[b]))
                    elif b in Z_relay:
                        held.append((Z_relay, b, Z_relay[b]))
                    elif b in Z_dtf:
                        held.append((Z_dtf[b], "y", Z_dtf[b]["y"]))

            def residual(z):
                for store, key, value in held:
                    store[key] = value
                for cut, value in zip(loop.cuts, z):
                    out_signals[cut] = float(value)
                computed = {}
                for b in loop.members:
                    value = direct_output(b, t, state_vec, out_signals, update_discrete, step_idx, sample_hits)
                    if b in loop.cut_set:
                        computed[b] = value
                    else:
                        out_signals[b] = value
                return [self._as_scalar(computed[cut]) - out_signals[cut] for cut in loop.cuts]

            solution = solve_algebraic_loop(residual, guesses[loop], loop.name, t)
            residual(solution)          # leave every member at the converged loop values
            guesses[loop] = solution

        def evaluate_network(t, state_vec, update_discrete=False, step_idx=0, source_override=None, sample_hits=None):
            out_signals = {}

            # Phase A: Non-Direct Feedthrough blocks
            for b in blocks:
                if not has_direct_ft[b]:
                    p = parsed[b]
                    if source_override and b in source_override:
                        out_signals[b] = source_override[b]
                    elif b.block_type == "Step":
                        out_signals[b] = p["final_val"] if t >= p["step_time"] else p["initial_val"]
                    elif b.block_type == "Sine Wave":
                        out_signals[b] = p["amplitude"] * math.sin(p["frequency"] * t + p["phase"])
                    elif b.block_type == "Constant":
                        out_signals[b] = p["value"]
                    elif b.block_type == "Pulse Generator":
                        out_signals[b] = self.pulse_value(p, t)
                    elif b.block_type == "Integrator":
                        out_signals[b] = float(state_vec[state_slices[b]][0])
                    elif b.block_type == "Unit Delay":
                        out_signals[b] = float(Z_delay[b])
                    elif b.block_type in ("Transfer Fcn", "State-Space"):
                        out_signals[b] = state_output(b, state_vec)
                    elif b.block_type in discrete_tf:
                        # Strictly proper: the held output is C*x[k], set at the hit.
                        if hit_now(b, update_discrete, step_idx, sample_hits):
                            Z_dtf[b]["y"] = float((ss_models[b][2] @ Z_dtf[b]["x"].reshape(-1, 1))[0, 0]) \
                                if ss_models[b][0].shape[0] else 0.0
                        out_signals[b] = Z_dtf[b]["y"]

            # Phase B: Topologically sorted Direct Feedthrough blocks; each
            # algebraic loop is solved as one unit after its inputs.
            for item in plan:
                if isinstance(item, SimulationEngine.AlgebraicLoop):
                    solve_loop(item, t, state_vec, out_signals, update_discrete, step_idx, sample_hits)
                else:
                    out_signals[item] = direct_output(item, t, state_vec, out_signals,
                                                      update_discrete, step_idx, sample_hits)

            # Scalar math.isfinite: numpy's reduction per signal was ~45% of runtime.
            isfinite = math.isfinite
            for b, value in out_signals.items():
                if not (isfinite(value) if not isinstance(value, list) else all(map(isfinite, value))):
                    raise ValueError(f"{b.name}: non-finite signal at t={t:g}; reduce dt or check the model.")

            # Phase C: Compute continuous state derivatives dX/dt
            dX = np.zeros(total_states, dtype=float)
            for b, sl in state_slices.items():
                conn = source_map[b][0] if source_map[b] else None
                u_in = self._as_scalar(self._extract_port_signal(out_signals, conn))
                if b.block_type == "Integrator":
                    dX[sl] = u_in
                elif b.block_type == "PID Controller":
                    p = parsed[b]
                    x_I, x_D = state_vec[sl]
                    dX[sl] = [u_in, p["N"] * (u_in - x_D)]
                elif b.block_type in ("Transfer Fcn", "State-Space"):
                    A, B, C, D = ss_models[b]
                    if A.shape[0] > 0:
                        xb = state_vec[sl].reshape(-1, 1)
                        dX[sl] = (A @ xb + B * u_in).flatten()

            if not np.all(np.isfinite(dX)):
                raise ValueError(f"Non-finite state derivative at t={t:g}; reduce dt or check the model.")
            return out_signals, dX

        return evaluate_network

    def run_simulation(self, root_scene: SimCanvasScene, t_stop=10.0, dt=0.01,
                       cancel_check=None, progress_callback=None, write_csv=True, solver="rk4"):
        """Run a bounded fixed-maximum-step solver with exact discrete sample events.

        ``solver`` is "rk4" (explicit) or "sdirk4" (implicit, L-stable, for
        stiff plants; Newton on a numerical Jacobian at every step). Algebraic
        loops are solved by Newton on their cut signals at every evaluation.
        Scopes include the regular output grid, source Step discontinuities,
        discrete sample events and the exact stop time. Discrete outputs remain
        constant between sample events. Callbacks run in the caller's thread.
        ``cancel_check()`` returns a bool; ``progress_callback(fraction)`` gets
        monotone values in [0, 1]. Run against a detached model in GUI workers.
        Scope results and CSV sinks are published only on successful completion.
        """
        from octalink_engine_support import SOLVERS, SimulationCancelled, sdirk4_step
        if solver not in SOLVERS:
            raise ValueError(f"Solver must be one of: {', '.join(SOLVERS)}.")
        t_stop, dt = float(t_stop), float(dt)
        if not math.isfinite(t_stop) or t_stop < 0:
            raise ValueError("Stop time must be finite and nonnegative.")
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("Time step must be finite and positive.")
        max_intervals = 250000
        if not math.isfinite(t_stop / dt) or t_stop / dt > max_intervals:
            raise ValueError(f"Simulation exceeds {max_intervals} time intervals; increase dt.")

        def check_cancelled():
            if cancel_check is not None and cancel_check():
                raise SimulationCancelled("Simulation cancelled.")

        check_cancelled()
        (blocks, source_map, parsed, state_slices,
         ss_models, has_direct_ft, sorted_direct, total_states) = self.compile_graph(root_scene)

        sinks = [b for b in blocks if b.block_type in ("Scope", "To CSV")]
        logged = {b: ([], []) for b in sinks}
        labels = {b: self._resolve_scope_labels(b, source_map) for b in sinks}
        sample_periods = {b: parsed[b]["sample_time"] for b in blocks
                          if b.block_type in self.DISCRETE_BLOCKS}

        # Include sample times even when Ts is not a multiple of dt. Reject
        # pathological sample schedules before allocating the time array.
        times = [i * dt for i in range(int(math.floor(t_stop / dt)) + 1)]
        times.append(t_stop)
        for ts in set(sample_periods.values()):
            ratio = t_stop / ts
            if not math.isfinite(ratio) or ratio > max_intervals:
                raise ValueError(f"Sample time requires more than {max_intervals} intervals.")
            if len(times) + int(math.floor(ratio)) + 1 > 4 * max_intervals:
                raise ValueError("Combined sample schedule is too large.")
            times.extend(i * ts for i in range(int(math.floor(ratio)) + 1))
        step_events = self.source_events(blocks, parsed, t_stop)
        times.extend(step_events)
        times.sort()
        epsilon = 16 * np.finfo(float).eps * t_stop
        schedule = []
        for time in times:
            if time > t_stop:
                continue
            if not schedule or time - schedule[-1] > epsilon:
                schedule.append(time)
            elif time == t_stop or time in step_events:
                schedule[-1] = time
        if len(schedule) > max_intervals + 1:
            raise ValueError(f"Combined sample schedule exceeds {max_intervals} intervals.")
        if len(schedule) * max(1, len(sinks)) > 2000000:
            raise ValueError("Scope result allocation is too large; increase dt or reduce stop time.")

        X = self._initial_state_vector(state_slices, parsed, total_states)
        Z_delay = {b: parsed[b]["initial_condition"] for b in blocks if b.block_type == "Unit Delay"}
        pending_delay = {}
        Z_zoh = {b: 0.0 for b in blocks if b.block_type == "Zero-Order Hold"}
        Z_relay = {b: parsed[b]["off_val"] for b in blocks if b.block_type == "Relay"}
        Z_dtf = {b: {"x": np.zeros(ss_models[b][0].shape[0]), "y": 0.0} for b in blocks
                 if b.block_type in ("Discrete Transfer Fcn", "Discrete Zero-Pole")}

        evaluate_network = self._build_evaluator(
            blocks, source_map, parsed, state_slices, ss_models,
            has_direct_ft, sorted_direct, total_states, Z_delay, Z_zoh, Z_relay, dt=dt, Z_dtf=Z_dtf,
            algebraic_loops=self.algebraic_loops
        )

        next_sample = {b: 0 for b in sample_periods}
        if progress_callback is not None:
            progress_callback(0.0)
        progress_stride = max(1, len(schedule) // 100)
        for step, t in enumerate(schedule):
            check_cancelled()
            hits = set()
            for b, ts in sample_periods.items():
                if abs(t - next_sample[b] * ts) <= epsilon:
                    hits.add(b)
                    next_sample[b] += 1
            # All delay outputs commit simultaneously. Inputs captured below
            # are pending until the next sample; RK stages see the held output.
            for b in hits:
                if b in pending_delay:
                    Z_delay[b] = pending_delay[b]
            signals, k1 = evaluate_network(t, X, update_discrete=True, step_idx=step, sample_hits=hits)
            for b in sinks:
                logged[b][0].append(t)
                logged[b][1].append(list(signals[b]))
            for b in hits:
                if b in Z_delay:
                    pending_delay[b] = self._as_scalar(self._extract_port_signal(signals, source_map[b][0]))
                elif b in Z_dtf and ss_models[b][0].shape[0]:
                    # x[k+1] = A x[k] + B u[k]; the output stays held until the next hit.
                    A, B, _, _ = ss_models[b]
                    u_k = self._as_scalar(self._extract_port_signal(signals, source_map[b][0]))
                    Z_dtf[b]["x"] = A @ Z_dtf[b]["x"] + B[:, 0] * u_k
                    if not np.all(np.isfinite(Z_dtf[b]["x"])):
                        raise ValueError(f"{b.name}: non-finite discrete state at t={t:g}.")

            if total_states > 0 and step + 1 < len(schedule):
                t_next = schedule[step + 1]
                h = t_next - t
                # Source discontinuities are right-continuous in recorded
                # outputs, but the preceding interval integrates their left
                # limit (otherwise RK4 adds a spurious h/6 impulse).
                t_end = math.nextafter(t_next, t) if t_next in step_events else t_next
                if solver == "sdirk4":
                    X = sdirk4_step(lambda time, state: evaluate_network(time, state)[1], t, X, k1, h, t_end)
                else:
                    _, k2 = evaluate_network(t + 0.5 * h, X + 0.5 * h * k1)
                    _, k3 = evaluate_network(t + 0.5 * h, X + 0.5 * h * k2)
                    _, k4 = evaluate_network(t_end, X + h * k3)
                    X = X + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
                if not np.all(np.isfinite(X)):
                    raise ValueError(f"Non-finite state at t={t_next:g}; reduce dt or check the model.")
            if progress_callback is not None and step % progress_stride == 0:
                progress_callback((step + 1) / len(schedule))

        check_cancelled()
        for b in sinks:
            b.scope_t, b.scope_y = logged[b]
            b.scope_labels = labels[b]

        # Write CSV sinks to disk
        for b in blocks:
            if write_csv and b.block_type == "To CSV":
                csv_path = parsed[b]["filename"]
                if csv_path:
                    with open(csv_path, "w", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow(["time"] + b.scope_labels)
                        for t_val, y_row in zip(b.scope_t, b.scope_y):
                            writer.writerow([f"{t_val:.17g}"] + [f"{val:.17g}" for val in y_row])

        if progress_callback is not None:
            progress_callback(1.0)
        return {b: {"time": b.scope_t, "values": b.scope_y, "labels": b.scope_labels} for b in sinks}

    def perform_linear_analysis(self, root_scene: SimCanvasScene, t_stop=10.0, dt=0.01, use_pade=True):
        from linear_analysis import analyze_scene
        return analyze_scene(root_scene, self, t_stop=t_stop, dt=dt, use_pade=use_pade)

    def _prototype_perform_linear_analysis(self, root_scene: SimCanvasScene, t_stop=10.0, dt=0.01, use_pade=True):
        """
        Executes numerical linearization (linmod) around the operating point.
        When `use_pade=True`, `Zero-Order Hold` (tau = Ts/2) and `Unit Delay` (tau = Ts)
        are augmented with 1st-order Padé state-space realizations:
            P1(s) = (1 - s*tau/2) / (1 + s*tau/2)  -->  dx = -(2/tau)*x + u, y = (4/tau)*x - u
        Computes (A, B, C, D), Poles, Zeros, Bode, Nyquist, Gain/Phase Margins, and Step Metrics.
        """
        self.run_simulation(root_scene, t_stop=t_stop, dt=dt)
        (blocks, source_map, parsed, state_slices,
         ss_models, has_direct_ft, sorted_direct, total_states) = self.compile_graph(root_scene)

        sources = [b for b in blocks if b.block_type in ("Step", "Sine Wave", "Constant")]
        scopes = [b for b in blocks if b.block_type == "Scope"]
        if not sources or not scopes:
            raise RuntimeError("Linear Analysis requires at least one Source block and one Scope block.")

        src_blk = sources[0]
        scope_blk = scopes[0]

        lin_slices = dict(state_slices)
        pade_taus = {}
        n_lin = total_states

        if use_pade:
            for b in blocks:
                if b.block_type == "Zero-Order Hold":
                    ts = parsed[b]["sample_time"]
                    if ts > 0:
                        pade_taus[b] = 0.5 * ts
                        lin_slices[b] = slice(n_lin, n_lin + 1)
                        n_lin += 1
                elif b.block_type == "Unit Delay":
                    ts = parsed[b]["sample_time"]
                    if ts > 0:
                        pade_taus[b] = ts
                        lin_slices[b] = slice(n_lin, n_lin + 1)
                        n_lin += 1

        has_ft_lin = dict(has_direct_ft)
        for b in blocks:
            if b.block_type == "Unit Delay":
                has_ft_lin[b] = True

        direct_lin = [b for b in blocks if has_ft_lin[b]]
        in_deg = {b: 0 for b in direct_lin}
        adj = {b: [] for b in direct_lin}
        for b in direct_lin:
            for conn in source_map[b]:
                if conn and conn[0] in direct_lin:
                    adj[conn[0]].append(b)
                    in_deg[b] += 1
        q = deque([b for b in direct_lin if in_deg[b] == 0])
        sorted_lin = []
        while q:
            c = q.popleft()
            sorted_lin.append(c)
            for nxt in adj[c]:
                in_deg[nxt] -= 1
                if in_deg[nxt] == 0:
                    q.append(nxt)

        delay_full_pade = True
        if len(sorted_lin) != len(direct_lin):
            sorted_lin = sorted_direct
            has_ft_lin = has_direct_ft
            delay_full_pade = False

        def eval_perturbation(x_vec, u_val):
            out_sig = {}
            for b in blocks:
                if not has_ft_lin[b]:
                    if b == src_blk:
                        out_sig[b] = u_val
                    elif b.block_type in ("Step", "Sine Wave", "Constant"):
                        out_sig[b] = 0.0
                    elif b.block_type == "Integrator":
                        out_sig[b] = float(x_vec[lin_slices[b]][0])
                    elif b.block_type == "Unit Delay":
                        if b in pade_taus:
                            tau = pade_taus[b]
                            xp = float(x_vec[lin_slices[b]][0])
                            out_sig[b] = (1.0 / tau) * xp
                        else:
                            out_sig[b] = 0.0
                    elif b.block_type in ("Transfer Fcn", "State-Space"):
                        A, B, C, D = ss_models[b]
                        xb = x_vec[lin_slices[b]].reshape(-1, 1)
                        out_sig[b] = float((C @ xb)[0, 0]) if A.shape[0] > 0 else 0.0

            for b in sorted_lin:
                p = parsed[b]
                raw_in = [self._extract_port_signal(out_sig, conn) for conn in source_map[b]]
                vector_block = b.block_type in ("Mux", "Demux", "Scope", "To CSV", "Octave Function")
                u0 = self._as_scalar(raw_in[0]) if raw_in and not vector_block else 0.0
                if b.block_type == "Gain":
                    out_sig[b] = p["gain"] * u0
                elif b.block_type == "Saturation":
                    out_sig[b] = min(max(u0, p["lower_limit"]), p["upper_limit"])
                elif b.block_type == "Relay":
                    out_sig[b] = u0
                elif b.block_type == "Switch":
                    u1 = self._as_scalar(raw_in[1]) if len(raw_in) > 1 else 0.0
                    u2 = self._as_scalar(raw_in[2]) if len(raw_in) > 2 else 0.0
                    out_sig[b] = u0 if u1 >= p["threshold"] else u2
                elif b.block_type in ("Zero-Order Hold", "Unit Delay"):
                    if b in pade_taus:
                        tau = pade_taus[b]
                        xp = float(x_vec[lin_slices[b]][0])
                        out_sig[b] = (4.0 / tau) * xp - u0
                    else:
                        out_sig[b] = u0
                elif b.block_type == "Trig":
                    op = p["operator"]
                    trig_map = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "atan": math.atan, "tanh": math.tanh}
                    out_sig[b] = trig_map.get(op, math.sin)(u0)
                elif b.block_type == "Octave Function":
                    out_sig[b] = self.eval_user_expr(p["expression"], raw_in[0] if raw_in else 0.0, 0.0)
                elif b.block_type == "Product":
                    ops = p["ops"]
                    acc = 1.0
                    for idx, val in enumerate(raw_in):
                        s_val = self._as_scalar(val)
                        acc = acc / (s_val if abs(s_val) > 1e-12 else 1e-12) if (idx < len(ops) and ops[idx] == "/") else acc * s_val
                    out_sig[b] = acc
                elif b.block_type == "Sum":
                    signs = p["signs"]
                    out_sig[b] = sum(
                        self._as_scalar(val) if (idx >= len(signs) or signs[idx] == "+") else -self._as_scalar(val)
                        for idx, val in enumerate(raw_in)
                    )
                elif b.block_type == "PID Controller":
                    x_I, x_D = x_vec[lin_slices[b]]
                    out_sig[b] = p["Kp"] * u0 + p["Ki"] * x_I + p["Kd"] * p["N"] * (u0 - x_D)
                elif b.block_type in ("Transfer Fcn", "State-Space"):
                    A, B, C, D = ss_models[b]
                    xb = x_vec[lin_slices[b]].reshape(-1, 1)
                    cx = float((C @ xb)[0, 0]) if A.shape[0] > 0 else 0.0
                    out_sig[b] = cx + D * u0
                elif b.block_type == "Mux":
                    vec = []
                    for val in raw_in:
                        vec.extend(self._as_vector(val))
                    out_sig[b] = vec
                elif b.block_type == "Demux":
                    in_v = self._as_vector(raw_in[0]) if raw_in else [0.0]
                    n_o = max(2, int(p["outputs"]))
                    out_sig[b] = [in_v[i] if i < len(in_v) else 0.0 for i in range(n_o)]
                elif b.block_type in ("Scope", "To CSV"):
                    out_sig[b] = self._as_vector(raw_in[0]) if raw_in else [0.0]

            dX = np.zeros(n_lin, dtype=float)
            for b, sl in lin_slices.items():
                conn = source_map[b][0] if source_map[b] else None
                u_in = self._as_scalar(self._extract_port_signal(out_sig, conn))
                if b.block_type == "Integrator":
                    dX[sl] = u_in
                elif b.block_type == "PID Controller":
                    p = parsed[b]
                    x_I, x_D = x_vec[sl]
                    dX[sl] = [u_in, p["N"] * (u_in - x_D)]
                elif b.block_type in ("Transfer Fcn", "State-Space"):
                    A, B, C, D = ss_models[b]
                    if A.shape[0] > 0:
                        xb = x_vec[sl].reshape(-1, 1)
                        dX[sl] = (A @ xb + B * u_in).flatten()
                elif b in pade_taus:
                    tau = pade_taus[b]
                    xp = float(x_vec[sl][0])
                    if b.block_type == "Unit Delay" and not delay_full_pade:
                        dX[sl] = -(1.0 / tau) * xp + u_in
                    else:
                        dX[sl] = -(2.0 / tau) * xp + u_in

            y_vec = out_sig.get(scope_blk, [0.0])
            y_out = float(y_vec[-1]) if len(y_vec) > 0 else 0.0
            return dX, y_out

        # Central finite-difference Jacobian linearization
        n = n_lin
        eps = 1e-5
        x0 = np.zeros(n, dtype=float)
        u0 = 0.0

        A_lin = np.zeros((n, n), dtype=float)
        B_lin = np.zeros((n, 1), dtype=float)
        C_lin = np.zeros((1, n), dtype=float)

        for j in range(n):
            dx = np.zeros(n, dtype=float)
            dx[j] = eps
            f_plus, y_plus = eval_perturbation(x0 + dx, u0)
            f_minus, y_minus = eval_perturbation(x0 - dx, u0)
            A_lin[:, j] = (f_plus - f_minus) / (2.0 * eps)
            C_lin[0, j] = (y_plus - y_minus) / (2.0 * eps)

        f_up, y_up = eval_perturbation(x0, u0 + eps)
        f_um, y_um = eval_perturbation(x0, u0 - eps)
        if n > 0:
            B_lin[:, 0] = (f_up - f_um) / (2.0 * eps)
        D_lin = float((y_up - y_um) / (2.0 * eps))

        poles = np.linalg.eigvals(A_lin) if n > 0 else np.array([])

        omega = np.logspace(-2, 2, 400)
        H = np.zeros_like(omega, dtype=complex)
        I_n = np.eye(n)
        for idx, w_val in enumerate(omega):
            if n > 0:
                try:
                    resolvent = np.linalg.solve(1j * w_val * I_n - A_lin, B_lin)
                    H[idx] = (C_lin @ resolvent)[0, 0] + D_lin
                except np.linalg.LinAlgError:
                    H[idx] = D_lin
            else:
                H[idx] = D_lin

        mag = np.maximum(np.abs(H), 1e-12)
        mag_db = 20.0 * np.log10(mag)
        phase_deg = np.rad2deg(np.unwrap(np.angle(H)))

        # Compute Loop Transfer L(jw) = T(jw) / (1 - T(jw)) if unity feedback is present
        has_feedback = any(b.block_type == "Sum" and "-" in parsed[b].get("signs", "") for b in blocks)
        if has_feedback:
            denom = np.where(np.abs(1.0 - H) < 1e-9, 1e-9 + 0j, 1.0 - H)
            L_jw = H / denom
        else:
            L_jw = H

        L_mag_db = 20.0 * np.log10(np.maximum(np.abs(L_jw), 1e-12))
        L_phase_deg = np.rad2deg(np.unwrap(np.angle(L_jw)))

        # Phase Margin at Gain Crossover (|L(jw)| = 0 dB)
        w_gc, phase_margin_deg = float("nan"), float("inf")
        gc_indices = np.where(np.diff(np.signbit(L_mag_db)))[0]
        if len(gc_indices) > 0:
            i0 = gc_indices[0]
            frac = abs(L_mag_db[i0]) / max(abs(L_mag_db[i0] - L_mag_db[i0 + 1]), 1e-12)
            w_gc = float(omega[i0] + frac * (omega[i0 + 1] - omega[i0]))
            ph_at_gc = float(L_phase_deg[i0] + frac * (L_phase_deg[i0 + 1] - L_phase_deg[i0]))
            phase_margin_deg = 180.0 + ph_at_gc

        # Gain Margin at Phase Crossover (angle(L(jw)) = -180 deg)
        w_pc, gain_margin_db = float("nan"), float("inf")
        pc_indices = np.where(np.diff(np.signbit(L_phase_deg + 180.0)))[0]
        if len(pc_indices) > 0:
            i0 = pc_indices[0]
            frac = abs(L_phase_deg[i0] + 180.0) / max(abs(L_phase_deg[i0] - L_phase_deg[i0 + 1]), 1e-12)
            w_pc = float(omega[i0] + frac * (omega[i0 + 1] - omega[i0]))
            mag_at_pc = float(L_mag_db[i0] + frac * (L_mag_db[i0 + 1] - L_mag_db[i0]))
            gain_margin_db = -mag_at_pc

        zeros = np.array([])
        if n > 0 and abs(D_lin) > 1e-9:
            zeros = np.linalg.eigvals(A_lin - (B_lin @ C_lin) / D_lin)

        t_arr = np.array(scope_blk.scope_t, dtype=float)
        y_mat = np.array(scope_blk.scope_y, dtype=float)
        if y_mat.ndim == 1:
            y_mat = y_mat.reshape(-1, 1)
        y_plant = y_mat[:, -1]
        y_target = float(parsed[src_blk].get("final_val", 1.0)) if src_blk.block_type == "Step" else 1.0
        t_step_offset = float(parsed[src_blk].get("step_time", 0.0)) if src_blk.block_type == "Step" else 0.0

        y_final = float(y_plant[-1])
        ss_error = abs(y_target - y_final)
        span = y_final - float(y_plant[0])
        if abs(span) > 1e-9:
            norm_y = (y_plant - float(y_plant[0])) / span
            idx_10 = np.where(norm_y >= 0.10)[0]
            idx_90 = np.where(norm_y >= 0.90)[0]
            rise_time = float(t_arr[idx_90[0]] - t_arr[idx_10[0]]) if (len(idx_10) > 0 and len(idx_90) > 0) else 0.0
            peak_val = float(np.max(norm_y))
            overshoot_pct = max(0.0, (peak_val - 1.0) * 100.0)
            outside_band = np.where(np.abs(norm_y - 1.0) > 0.02)[0]
            settling_time = max(0.0, float(t_arr[outside_band[-1]] - t_step_offset)) if len(outside_band) > 0 else 0.0
        else:
            rise_time, overshoot_pct, settling_time = 0.0, 0.0, 0.0

        return {
            "A": A_lin, "B": B_lin, "C": C_lin, "D": D_lin,
            "poles": poles, "zeros": zeros,
            "omega": omega, "freq_resp": H, "mag_db": mag_db, "phase_deg": phase_deg,
            "margins": {
                "gain_margin_db": gain_margin_db,
                "phase_margin_deg": phase_margin_deg,
                "w_gc": w_gc,
                "w_pc": w_pc
            },
            "step_metrics": {
                "rise_time": rise_time,
                "settling_time": settling_time,
                "overshoot_pct": overshoot_pct,
                "ss_error": ss_error
            }
        }

    def export_embedded_c_code(self, root_scene: SimCanvasScene, dt: float, base_filepath: str):
        from c_export import export_c_model
        from mvp_model import document_from_scene
        return export_c_model(document_from_scene(root_scene, dt=dt), BLOCK_SPECS, dt, base_filepath)

    def _prototype_export_embedded_c_code(self, root_scene: SimCanvasScene, dt: float, base_filepath: str):
        (blocks, source_map, parsed, state_slices,
         ss_models, has_direct_ft, sorted_direct, total_states) = self.compile_graph(root_scene)

        base_no_ext = os.path.splitext(base_filepath)[0]
        h_path = base_no_ext + ".h"
        c_path = base_no_ext + ".c"
        header_guard = "OCTALINK_GENERATED_MODEL_H"
        n_states = max(total_states, 1)

        scopes = [b for b in blocks if b.block_type in ("Scope", "To CSV")]
        num_scope_channels = 1
        if scopes:
            labels = self._resolve_scope_labels(scopes[0], source_map)
            num_scope_channels = max(1, len(labels))

        h_lines = [
            f"#ifndef {header_guard}",
            f"#define {header_guard}",
            "",
            "#include <stdint.h>",
            "#include <math.h>",
            "",
            "#ifdef __cplusplus",
            "extern \"C\" {",
            "#endif",
            "",
            f"#define OCTALINK_NUM_STATES {n_states}",
            f"#define OCTALINK_NUM_OUTPUTS {num_scope_channels}",
            "",
            "typedef struct {",
            "    double t;",
            "    uint32_t step_idx;",
            f"    double X[{n_states}];",
        ]
        for b in blocks:
            if b.block_type == "Unit Delay":
                h_lines.append(f"    double delay_{b.name};")
            elif b.block_type == "Zero-Order Hold":
                h_lines.append(f"    double zoh_{b.name};")
            elif b.block_type == "Relay":
                h_lines.append(f"    double relay_{b.name};")
        h_lines.extend([
            f"    double y_out[{num_scope_channels}];",
            "} OctaLink_State;",
            "",
            "void OctaLink_Init(OctaLink_State *st);",
            "void OctaLink_Step(OctaLink_State *st, double dt);",
            "",
            "#ifdef __cplusplus",
            "}",
            "#endif",
            "",
            f"#endif /* {header_guard} */"
        ])

        with open(h_path, "w", encoding="utf-8") as f:
            f.write("\n".join(h_lines) + "\n")

        c_lines = [
            "/* ======================================================================== */",
            "/* Automatically generated by OctaLink Embedded ANSI C99 Code Generator     */",
            "/* Hardware-agnostic C99 runtime for MCUs (RP2040, STM32, AVR) & Linux RT   */",
            "/* ======================================================================== */",
            f"#include \"{os.path.basename(h_path)}\"",
            "",
            "static int octalink_is_hit(uint32_t step_idx, double dt, double ts) {",
            "    if (ts <= 0.0 || step_idx == 0U) return 1;",
            "    double t_curr = (double)step_idx * dt;",
            "    double t_prev = (double)(step_idx - 1U) * dt;",
            "    double eps = 1e-9 * ((ts > 1.0) ? ts : 1.0);",
            "    return (floor((t_curr + eps) / ts) > floor((t_prev + eps) / ts)) ? 1 : 0;",
            "}",
            "",
            "void OctaLink_Init(OctaLink_State *st) {",
            "    st->t = 0.0;",
            "    st->step_idx = 0U;",
            f"    for (int i = 0; i < {n_states}; ++i) st->X[i] = 0.0;",
            f"    for (int i = 0; i < {num_scope_channels}; ++i) st->y_out[i] = 0.0;"
        ]

        x0 = self._initial_state_vector(state_slices, parsed, total_states)
        for i, val in enumerate(x0):
            if abs(val) > 0.0:
                c_lines.append(f"    st->X[{i}] = {val:.10g};")

        for b in blocks:
            if b.block_type == "Unit Delay":
                c_lines.append(f"    st->delay_{b.name} = {parsed[b]['initial_condition']:.10g};")
            elif b.block_type == "Zero-Order Hold":
                c_lines.append(f"    st->zoh_{b.name} = 0.0;")
            elif b.block_type == "Relay":
                c_lines.append(f"    st->relay_{b.name} = {parsed[b]['off_val']:.10g};")
        c_lines.extend(["}", ""])

        def c_sig_ref(conn):
            if conn is None:
                return "0.0"
            s_blk, p_idx = conn
            if s_blk.block_type in ("Mux", "Demux"):
                return f"y_{s_blk.name}[{p_idx}]"
            return f"y_{s_blk.name}"

        c_lines.extend([
            "static void OctaLink_Eval(OctaLink_State *st, double t, const double *x, double *dxdt, int is_major_step, double dt) {"
        ])

        c_lines.append("    /* --- Phase A: Sources & Non-Direct Feedthrough States --- */")
        for b in blocks:
            if not has_direct_ft[b]:
                p = parsed[b]
                if b.block_type == "Step":
                    c_lines.append(
                        f"    double y_{b.name} = (t >= {p['step_time']:.10g}) ? {p['final_val']:.10g} : {p['initial_val']:.10g};"
                    )
                elif b.block_type == "Sine Wave":
                    c_lines.append(
                        f"    double y_{b.name} = {p['amplitude']:.10g} * sin({p['frequency']:.10g} * t + {p['phase']:.10g});"
                    )
                elif b.block_type == "Constant":
                    c_lines.append(f"    double y_{b.name} = {p['value']:.10g};")
                elif b.block_type == "Integrator":
                    c_lines.append(f"    double y_{b.name} = x[{state_slices[b].start}];")
                elif b.block_type == "Unit Delay":
                    c_lines.append(f"    double y_{b.name} = st->delay_{b.name};")
                elif b.block_type in ("Transfer Fcn", "State-Space"):
                    A, B, C, D = ss_models[b]
                    sl = state_slices[b]
                    terms = [f"({C[0, j]:.10g} * x[{sl.start + j}])" for j in range(A.shape[0]) if abs(C[0, j]) > 0.0]
                    expr = " + ".join(terms) if terms else "0.0"
                    c_lines.append(f"    double y_{b.name} = {expr};")

        c_lines.append("")
        c_lines.append("    /* --- Phase B: Topologically Sorted Direct Feedthrough Network --- */")
        for b in sorted_direct:
            p = parsed[b]
            in_refs = [c_sig_ref(conn) for conn in source_map[b]]
            u0 = in_refs[0] if in_refs else "0.0"

            if b.block_type == "Gain":
                c_lines.append(f"    double y_{b.name} = {p['gain']:.10g} * ({u0});")
            elif b.block_type == "Saturation":
                lo, hi = p["lower_limit"], p["upper_limit"]
                c_lines.append(
                    f"    double y_{b.name} = (({u0}) < {lo:.10g}) ? {lo:.10g} : ((({u0}) > {hi:.10g}) ? {hi:.10g} : ({u0}));"
                )
            elif b.block_type == "Relay":
                c_lines.append(
                    f"    if (is_major_step) {{ if (({u0}) >= {p['switch_on_point']:.10g}) st->relay_{b.name} = {p['on_val']:.10g}; "
                    f"else if (({u0}) <= {p['switch_off_point']:.10g}) st->relay_{b.name} = {p['off_val']:.10g}; }}"
                )
                c_lines.append(f"    double y_{b.name} = st->relay_{b.name};")
            elif b.block_type == "Switch":
                u1 = in_refs[1] if len(in_refs) > 1 else "0.0"
                u2 = in_refs[2] if len(in_refs) > 2 else "0.0"
                c_lines.append(f"    double y_{b.name} = (({u1}) >= {p['threshold']:.10g}) ? ({u0}) : ({u2});")
            elif b.block_type == "Trig":
                op = p["operator"]
                c_lines.append(f"    double y_{b.name} = {op}({u0});")
            elif b.block_type == "Octave Function":
                c_expr = self._translate_expr_to_c(p["expression"], u0)
                c_lines.append(f"    double y_{b.name} = {c_expr};")
            elif b.block_type == "Product":
                ops = p["ops"]
                terms = []
                for idx, ref in enumerate(in_refs):
                    op_ch = ops[idx] if idx < len(ops) else "*"
                    terms.append(f"/ ({ref})" if op_ch == "/" else f"* ({ref})")
                expr = "1.0 " + " ".join(terms) if terms else "0.0"
                c_lines.append(f"    double y_{b.name} = {expr};")
            elif b.block_type == "Zero-Order Hold":
                ts = p["sample_time"]
                c_lines.append(
                    f"    if (is_major_step && octalink_is_hit(st->step_idx, dt, {ts:.10g})) st->zoh_{b.name} = {u0};"
                )
                c_lines.append(f"    double y_{b.name} = st->zoh_{b.name};")
            elif b.block_type == "Sum":
                signs = p["signs"]
                terms = [
                    f"{(signs[idx] if idx < len(signs) else '+')} ({ref})"
                    for idx, ref in enumerate(in_refs)
                ]
                c_lines.append(f"    double y_{b.name} = {' '.join(terms) if terms else '0.0'};")
            elif b.block_type == "PID Controller":
                sl = state_slices[b]
                c_lines.append(
                    f"    double y_{b.name} = {p['Kp']:.10g}*({u0}) + {p['Ki']:.10g}*x[{sl.start}] + "
                    f"{p['Kd']:.10g}*{p['N']:.10g}*(({u0}) - x[{sl.start + 1}]);"
                )
            elif b.block_type in ("Transfer Fcn", "State-Space"):
                A, B, C, D = ss_models[b]
                sl = state_slices[b]
                terms = [f"({C[0, j]:.10g} * x[{sl.start + j}])" for j in range(A.shape[0]) if abs(C[0, j]) > 0.0]
                cx = " + ".join(terms) if terms else "0.0"
                c_lines.append(f"    double y_{b.name} = ({cx}) + ({D:.10g} * ({u0}));")
            elif b.block_type == "Mux":
                n_in = len(in_refs)
                c_lines.append(f"    double y_{b.name}[{max(1, n_in)}] = {{ {', '.join(in_refs) if in_refs else '0.0'} }};")
            elif b.block_type == "Demux":
                n_out = max(2, int(p["outputs"]))
                conn0 = source_map[b][0] if source_map[b] else None
                if conn0 and conn0[0].block_type == "Mux":
                    mux_blk = conn0[0]
                    elems = [f"y_{mux_blk.name}[{i}]" for i in range(n_out)]
                else:
                    elems = [u0 if i == 0 else "0.0" for i in range(n_out)]
                c_lines.append(f"    double y_{b.name}[{n_out}] = {{ {', '.join(elems)} }};")
            elif b.block_type in ("Scope", "To CSV") and scopes and b == scopes[0]:
                conn0 = source_map[b][0] if source_map[b] else None
                if conn0 and conn0[0].block_type == "Mux":
                    mux_blk = conn0[0]
                    n_ch = len(source_map[mux_blk])
                    c_lines.append("    if (is_major_step) {")
                    for ch in range(n_ch):
                        c_lines.append(f"        st->y_out[{ch}] = y_{mux_blk.name}[{ch}];")
                    c_lines.append("    }")
                else:
                    c_lines.append(f"    if (is_major_step) st->y_out[0] = {u0};")

        c_lines.append("")
        c_lines.append("    /* --- Phase C: Discrete State Updates & Continuous Derivatives --- */")
        for b in blocks:
            if b.block_type == "Unit Delay":
                ts = parsed[b]["sample_time"]
                u_in = c_sig_ref(source_map[b][0] if source_map[b] else None)
                c_lines.append(
                    f"    if (is_major_step && octalink_is_hit(st->step_idx, dt, {ts:.10g})) st->delay_{b.name} = {u_in};"
                )

        c_lines.append(f"    for (int i = 0; i < {n_states}; ++i) dxdt[i] = 0.0;")
        for b, sl in state_slices.items():
            u_in = c_sig_ref(source_map[b][0] if source_map[b] else None)
            if b.block_type == "Integrator":
                c_lines.append(f"    dxdt[{sl.start}] = {u_in};")
            elif b.block_type == "PID Controller":
                p = parsed[b]
                c_lines.append(f"    dxdt[{sl.start}] = {u_in};")
                c_lines.append(f"    dxdt[{sl.start + 1}] = {p['N']:.10g} * (({u_in}) - x[{sl.start + 1}]);")
            elif b.block_type in ("Transfer Fcn", "State-Space"):
                A, B, C, D = ss_models[b]
                for r in range(A.shape[0]):
                    a_terms = [f"({A[r, c]:.10g} * x[{sl.start + c}])" for c in range(A.shape[1]) if abs(A[r, c]) > 0.0]
                    b_term = f"({B[r, 0]:.10g} * ({u_in}))" if abs(B[r, 0]) > 0.0 else ""
                    all_terms = a_terms + ([b_term] if b_term else [])
                    c_lines.append(f"    dxdt[{sl.start + r}] = {' + '.join(all_terms) if all_terms else '0.0'};")

        c_lines.extend([
            "}",
            "",
            "void OctaLink_Step(OctaLink_State *st, double dt) {",
            f"    double k1[{n_states}], k2[{n_states}], k3[{n_states}], k4[{n_states}], x_tmp[{n_states}];",
            "    OctaLink_Eval(st, st->t, st->X, k1, 1, dt);",
            f"    for (int i = 0; i < {n_states}; ++i) x_tmp[i] = st->X[i] + 0.5 * dt * k1[i];",
            "    OctaLink_Eval(st, st->t + 0.5 * dt, x_tmp, k2, 0, dt);",
            f"    for (int i = 0; i < {n_states}; ++i) x_tmp[i] = st->X[i] + 0.5 * dt * k2[i];",
            "    OctaLink_Eval(st, st->t + 0.5 * dt, x_tmp, k3, 0, dt);",
            f"    for (int i = 0; i < {n_states}; ++i) x_tmp[i] = st->X[i] + dt * k3[i];",
            "    OctaLink_Eval(st, st->t + dt, x_tmp, k4, 0, dt);",
            f"    for (int i = 0; i < {n_states}; ++i) {{",
            "        st->X[i] += (dt / 6.0) * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]);",
            "    }",
            "    st->step_idx += 1U;",
            "    st->t = (double)st->step_idx * dt;",
            "}"
        ])

        with open(c_path, "w", encoding="utf-8") as f:
            f.write("\n".join(c_lines) + "\n")

        return h_path, c_path

    def export_octave_m_script(self, root_scene: SimCanvasScene, t_stop: float, dt: float, filepath: str):
        from octave_backend import export_octave_script
        from mvp_model import document_from_scene
        return export_octave_script(document_from_scene(root_scene, t_stop=t_stop, dt=dt), BLOCK_SPECS, filepath)

    def _prototype_export_octave_m_script(self, root_scene: SimCanvasScene, t_stop: float, dt: float, filepath: str):
        (blocks, source_map, parsed, state_slices,
         ss_models, has_direct_ft, sorted_direct, total_states) = self.compile_graph(root_scene)

        def mat_str(arr):
            if arr.size == 0:
                return "[]"
            rows = [" ".join(f"{val:.8g}" for val in row) for row in arr]
            return "[" + "; ".join(rows) + "]"

        def m_sig_ref(conn):
            if conn is None:
                return "0"
            s_blk, p_idx = conn
            if s_blk.block_type in ("Mux", "Demux"):
                return f"y_{s_blk.name}({p_idx + 1})"
            return f"y_{s_blk.name}"

        lines = [
            "%% ========================================================================",
            "%% Automatically generated by OctaLink — Hybrid Simulink Compiler for Octave",
            "%% ========================================================================",
            "clear; clc; close all;",
            f"t_stop = {t_stop};",
            f"dt = {dt};",
            ""
        ]

        x0 = self._initial_state_vector(state_slices, parsed, max(total_states, 1))
        lines.append(f"x0 = [{'; '.join(f'{v:.8g}' for v in x0)}];")
        lines.append("z_state = struct();")
        for b in blocks:
            if b.block_type == "Unit Delay":
                lines.append(f"z_state.delay_{b.name} = {parsed[b]['initial_condition']};")
            elif b.block_type == "Zero-Order Hold":
                lines.append(f"z_state.zoh_{b.name} = 0.0;")
            elif b.block_type == "Relay":
                lines.append(f"z_state.relay_{b.name} = {parsed[b]['off_val']};")
        lines.append("")

        scopes = [b for b in blocks if b.block_type == "Scope"]
        lines.append("function [dxdt, scope_out, z_next] = octalink_step(t, x, z_state, is_hit, dt)")
        lines.append("  z_next = z_state;")
        for b in blocks:
            if b.block_type in ("Transfer Fcn", "State-Space"):
                A, B, C, D = ss_models[b]
                lines.append(f"  A_{b.name} = {mat_str(A)}; B_{b.name} = {mat_str(B)};")
                lines.append(f"  C_{b.name} = {mat_str(C)}; D_{b.name} = {D:.8g};")

        lines.append("  % --- Phase A ---")
        for b in blocks:
            if not has_direct_ft[b]:
                p = parsed[b]
                if b.block_type == "Step":
                    lines.append(f"  if t >= {p['step_time']}, y_{b.name} = {p['final_val']}; else, y_{b.name} = {p['initial_val']}; endif")
                elif b.block_type == "Sine Wave":
                    lines.append(f"  y_{b.name} = {p['amplitude']} * sin({p['frequency']} * t + {p['phase']});")
                elif b.block_type == "Constant":
                    lines.append(f"  y_{b.name} = {p['value']};")
                elif b.block_type == "Integrator":
                    lines.append(f"  y_{b.name} = x({state_slices[b].start + 1});")
                elif b.block_type == "Unit Delay":
                    lines.append(f"  y_{b.name} = z_state.delay_{b.name};")
                elif b.block_type in ("Transfer Fcn", "State-Space"):
                    sl = state_slices[b]
                    lines.append(f"  y_{b.name} = C_{b.name} * x({sl.start + 1}:{sl.stop});" if sl.stop > sl.start else f"  y_{b.name} = 0;")

        lines.append("  % --- Phase B ---")
        for b in sorted_direct:
            p = parsed[b]
            in_vars = [m_sig_ref(conn) for conn in source_map[b]]
            u0 = in_vars[0] if in_vars else "0"
            if b.block_type == "Gain":
                lines.append(f"  y_{b.name} = {p['gain']} * ({u0});")
            elif b.block_type == "Saturation":
                lines.append(f"  y_{b.name} = min(max({u0}, {p['lower_limit']}), {p['upper_limit']});")
            elif b.block_type == "Relay":
                lines.append(
                    f"  if is_hit, if ({u0}) >= {p['switch_on_point']}, z_next.relay_{b.name} = {p['on_val']}; "
                    f"elseif ({u0}) <= {p['switch_off_point']}, z_next.relay_{b.name} = {p['off_val']}; endif; endif"
                )
                lines.append(f"  y_{b.name} = z_next.relay_{b.name};")
            elif b.block_type == "Switch":
                u1 = in_vars[1] if len(in_vars) > 1 else "0"
                u2 = in_vars[2] if len(in_vars) > 2 else "0"
                lines.append(f"  if ({u1}) >= {p['threshold']}, y_{b.name} = {u0}; else, y_{b.name} = {u2}; endif")
            elif b.block_type == "Trig":
                lines.append(f"  y_{b.name} = {p['operator']}({u0});")
            elif b.block_type == "Octave Function":
                expr = self._translate_expr_to_m(p["expression"], u0)
                lines.append(f"  y_{b.name} = {expr};")
            elif b.block_type == "Product":
                ops = p["ops"]
                terms = [f"/ ({v})" if (i < len(ops) and ops[i] == "/") else f"* ({v})" for i, v in enumerate(in_vars)]
                lines.append(f"  y_{b.name} = 1.0 {' '.join(terms)};")
            elif b.block_type == "Zero-Order Hold":
                ts = p["sample_time"]
                lines.append(
                    f"  if is_hit && (t == 0 || floor((t + 1e-9)/{ts}) > floor((t - dt + 1e-9)/{ts})), z_next.zoh_{b.name} = {u0}; endif"
                )
                lines.append(f"  y_{b.name} = z_next.zoh_{b.name};")
            elif b.block_type == "Sum":
                signs = p["signs"]
                terms = [f"{(signs[i] if i < len(signs) else '+')} ({v})" for i, v in enumerate(in_vars)]
                lines.append(f"  y_{b.name} = {' '.join(terms) if terms else '0'};")
            elif b.block_type == "PID Controller":
                sl = state_slices[b]
                lines.append(
                    f"  y_{b.name} = {p['Kp']}*({u0}) + {p['Ki']}*x({sl.start + 1}) + {p['Kd']}*{p['N']}*(({u0}) - x({sl.start + 2}));"
                )
            elif b.block_type in ("Transfer Fcn", "State-Space"):
                sl = state_slices[b]
                cx = f"C_{b.name} * x({sl.start + 1}:{sl.stop})" if sl.stop > sl.start else "0"
                lines.append(f"  y_{b.name} = {cx} + D_{b.name} * ({u0});")
            elif b.block_type in ("Mux", "Demux"):
                lines.append(f"  y_{b.name} = [{', '.join(in_vars)}];")
            elif b.block_type in ("Scope", "To CSV"):
                conn0 = source_map[b][0] if source_map[b] else None
                lines.append(f"  y_{b.name} = y_{conn0[0].name};" if conn0 else f"  y_{b.name} = 0;")

        lines.append("  % --- Phase C ---")
        for b in blocks:
            if b.block_type == "Unit Delay":
                ts = parsed[b]["sample_time"]
                u_in = m_sig_ref(source_map[b][0] if source_map[b] else None)
                lines.append(
                    f"  if is_hit && (t == 0 || floor((t + 1e-9)/{ts}) > floor((t - dt + 1e-9)/{ts})), z_next.delay_{b.name} = {u_in}; endif"
                )

        lines.append(f"  dxdt = zeros({max(total_states, 1)}, 1);")
        for b, sl in state_slices.items():
            u_in = m_sig_ref(source_map[b][0] if source_map[b] else None)
            if b.block_type == "Integrator":
                lines.append(f"  dxdt({sl.start + 1}) = {u_in};")
            elif b.block_type == "PID Controller":
                p = parsed[b]
                lines.append(f"  dxdt({sl.start + 1}) = {u_in};")
                lines.append(f"  dxdt({sl.start + 2}) = {p['N']} * (({u_in}) - x({sl.start + 2}));")
            elif b.block_type in ("Transfer Fcn", "State-Space"):
                if sl.stop > sl.start:
                    lines.append(f"  dxdt({sl.start + 1}:{sl.stop}) = A_{b.name} * x({sl.start + 1}:{sl.stop}) + B_{b.name} * ({u_in});")

        lines.append(f"  scope_out = y_{scopes[0].name};" if scopes else "  scope_out = [];")
        lines.append("endfunction\n")

        lines.extend([
            "T_log = (0:dt:t_stop)'; x_curr = x0; Y_log = [];",
            "opts = odeset('RelTol', 1e-6, 'AbsTol', 1e-8);",
            "for k = 1:length(T_log)",
            "  t_k = T_log(k);",
            "  [~, s_out, z_state] = octalink_step(t_k, x_curr, z_state, true, dt);",
            "  Y_log = [Y_log; s_out];",
            "  if k < length(T_log)",
            "    [~, X_seg] = ode45(@(t, x) octalink_step(t, x, z_state, false, dt), [t_k, T_log(k+1)], x_curr, opts);",
            "    x_curr = X_seg(end, :)';",
            "  endif",
            "endfor"
        ])

        if scopes:
            labels = self._resolve_scope_labels(scopes[0], source_map)
            legend_str = ", ".join(f"'{lbl}'" for lbl in labels)
            lines.extend([
                "",
                "figure('Name', 'OctaLink Hybrid Simulation Results', 'NumberTitle', 'off');",
                "plot(T_log, Y_log, 'LineWidth', 2);",
                "grid on; xlabel('Time (s)'); ylabel('Amplitude');",
                f"legend({legend_str});",
                "title('OctaLink Hybrid Continuous-Discrete Simulation (ode45)');"
            ])

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


# ============================================================================
# 5. MAIN APPLICATION WINDOW (WITH VECTOR SVG ICONS, UNDO/REDO, FLIP & CODER)
# ============================================================================
class OctaLinkMainWindow(QMainWindow):
    def __init__(self, initial_json=None):
        super().__init__()
        self.setWindowTitle("OctaLink — Canonical Simulink Modeling, Linear Analysis & Embedded C Suite")
        self.setWindowIcon(make_svg_icon("app", 24))
        self.resize(1380, 780)
        self.sim_engine = SimulationEngine()

        self.undo_stack = []
        self.redo_stack = []
        self._restoring_snapshot = False

        self.root_scene = SimCanvasScene(self, owner_subsystem=None)
        self.current_scene = self.root_scene

        self._setup_ui()
        self._setup_shortcuts()
        if initial_json:
            self.load_model_from_file(initial_json)
        else:
            self._build_default_hybrid_model()

    def _setup_ui(self):
        toolbar = QToolBar("Simulation, Linear Analysis & Code Generation")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setStyleSheet("""
            QToolBar { background: #2D2D30; spacing: 6px; padding: 6px; border-bottom: 1px solid #1E1E1E; }
            QLabel { color: #FFFFFF; font-weight: bold; }
            QLineEdit { background: #1E1E1E; color: #00E676; border: 1px solid #555; padding: 4px; border-radius: 4px; }
            QPushButton { background: #007ACC; color: white; font-weight: bold; padding: 6px 9px; border-radius: 4px; }
            QPushButton:hover { background: #1C97EA; }
        """)
        self.addToolBar(toolbar)

        run_btn = QPushButton(make_svg_icon("run"), "Run")
        run_btn.clicked.connect(self.on_run_clicked)
        toolbar.addWidget(run_btn)

        toolbar.addWidget(QLabel("Stop:"))
        self.stop_time_edit = QLineEdit("10.0")
        self.stop_time_edit.setFixedWidth(50)
        toolbar.addWidget(self.stop_time_edit)

        toolbar.addWidget(QLabel("dt:"))
        self.dt_edit = QLineEdit("0.01")
        self.dt_edit.setFixedWidth(50)
        toolbar.addWidget(self.dt_edit)

        toolbar.addSeparator()
        lin_btn = QPushButton(make_svg_icon("bode"), "Linear Analysis")
        lin_btn.setStyleSheet("background: #00838F;")
        lin_btn.clicked.connect(self.on_linear_analysis_clicked)
        toolbar.addWidget(lin_btn)

        c_btn = QPushButton(make_svg_icon("c_code"), "Export ANSI C")
        c_btn.setStyleSheet("background: #AD1457;")
        c_btn.clicked.connect(self.on_export_c_clicked)
        toolbar.addWidget(c_btn)

        export_btn = QPushButton(make_svg_icon("m_code"), "Export .m")
        export_btn.setStyleSheet("background: #2E7D32;")
        export_btn.clicked.connect(self.on_export_m_clicked)
        toolbar.addWidget(export_btn)

        toolbar.addSeparator()
        flip_btn = QPushButton(make_svg_icon("flip"), "Flip (Ctrl+I)")
        flip_btn.setStyleSheet("background: #455A64;")
        flip_btn.clicked.connect(self.on_flip_selected_clicked)
        toolbar.addWidget(flip_btn)

        undo_btn = QPushButton(make_svg_icon("undo"), "Undo")
        undo_btn.setStyleSheet("background: #3A3D41;")
        undo_btn.clicked.connect(self.on_undo_clicked)
        toolbar.addWidget(undo_btn)

        redo_btn = QPushButton(make_svg_icon("redo"), "Redo")
        redo_btn.setStyleSheet("background: #3A3D41;")
        redo_btn.clicked.connect(self.on_redo_clicked)
        toolbar.addWidget(redo_btn)

        sub_btn = QPushButton(make_svg_icon("subsystem"), "Subsystem")
        sub_btn.setStyleSheet("background: #6A1B9A;")
        sub_btn.clicked.connect(self.on_create_subsystem_clicked)
        toolbar.addWidget(sub_btn)

        self.up_btn = QPushButton(make_svg_icon("up"), "Up")
        self.up_btn.setStyleSheet("background: #E65100;")
        self.up_btn.clicked.connect(self.on_navigate_up_clicked)
        self.up_btn.setEnabled(False)
        toolbar.addWidget(self.up_btn)

        self.breadcrumb_label = QLabel("Root")
        self.breadcrumb_label.setStyleSheet("color: #FFD54F; margin-left: 4px; margin-right: 4px;")
        toolbar.addWidget(self.breadcrumb_label)

        toolbar.addSeparator()
        save_btn = QPushButton(make_svg_icon("save"), "Save")
        save_btn.setStyleSheet("background: #3A3D41;")
        save_btn.clicked.connect(self.on_save_json_clicked)
        toolbar.addWidget(save_btn)

        load_btn = QPushButton(make_svg_icon("load"), "Load")
        load_btn.setStyleSheet("background: #3A3D41;")
        load_btn.clicked.connect(self.on_load_json_clicked)
        toolbar.addWidget(load_btn)

        # Left Dock: Library Browser with Vector SVG Category Icons
        dock = QDockWidget("Library Browser", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock_widget = QWidget()
        dock_layout = QVBoxLayout(dock_widget)

        inst_label = QLabel("Double-click to insert  |  Wheel: Zoom  |  Space/Mid-Drag: Pan")
        inst_label.setWordWrap(True)
        inst_label.setStyleSheet("color: #444; font-size: 11px; margin-bottom: 4px;")
        dock_layout.addWidget(inst_label)

        self.lib_list = QListWidget()
        self.lib_list.setIconSize(QSize(22, 22))
        self.lib_list.setStyleSheet("""
            QListWidget { font-size: 13px; padding: 4px; }
            QListWidget::item { padding: 6px; border-bottom: 1px solid #EEEEEE; }
            QListWidget::item:hover { background: #E5F3FF; }
        """)
        for btype, spec in BLOCK_SPECS.items():
            cat_icon = make_svg_icon(f"cat_{spec['category']}", 22)
            item = QListWidgetItem(cat_icon, f"[{spec['category']}]  {btype}")
            item.setData(Qt.ItemDataRole.UserRole, btype)
            self.lib_list.addItem(item)
        self.lib_list.itemDoubleClicked.connect(self.on_library_item_double_clicked)
        dock_layout.addWidget(self.lib_list)

        dock.setWidget(dock_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.view = SimCanvasView(self.root_scene)
        self.setCentralWidget(self.view)

        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage(
            "Ready  |  Ctrl+I: Flip Block  |  Ctrl+Z / Ctrl+Y: Undo/Redo  |  Wheel: Zoom  |  Space+Left-Drag or Mid-Drag: Pan"
        )

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self.on_flip_selected_clicked)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.on_undo_clicked)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.on_redo_clicked)

    def push_undo_snapshot(self):
        if self._restoring_snapshot:
            return
        self.undo_stack.append(json.dumps(self.serialize_model()))
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def on_undo_clicked(self):
        if not self.undo_stack:
            self.statusBar().showMessage("Nothing to undo.")
            return
        self._restoring_snapshot = True
        self.redo_stack.append(json.dumps(self.serialize_model()))
        snap = json.loads(self.undo_stack.pop())
        self._restore_from_dict(snap)
        self._restoring_snapshot = False
        self.statusBar().showMessage("Undo applied.")

    def on_redo_clicked(self):
        if not self.redo_stack:
            self.statusBar().showMessage("Nothing to redo.")
            return
        self._restoring_snapshot = True
        self.undo_stack.append(json.dumps(self.serialize_model()))
        snap = json.loads(self.redo_stack.pop())
        self._restore_from_dict(snap)
        self._restoring_snapshot = False
        self.statusBar().showMessage("Redo applied.")

    def on_flip_selected_clicked(self):
        selected = [item for item in self.current_scene.selectedItems() if isinstance(item, BlockItem)]
        if not selected:
            return
        self.push_undo_snapshot()
        for blk in selected:
            blk.toggle_flip()

    def open_subsystem_scene(self, scene: SimCanvasScene):
        self.current_scene = scene
        self.view.setScene(scene)
        path_names = []
        curr = scene
        while curr.owner_subsystem is not None:
            path_names.append(curr.owner_subsystem.name)
            curr = curr.owner_subsystem.scene()
        path_names.append("Root")
        path_names.reverse()
        self.breadcrumb_label.setText(" > ".join(path_names))
        self.up_btn.setEnabled(scene.owner_subsystem is not None)

    def on_navigate_up_clicked(self):
        if self.current_scene.owner_subsystem is not None:
            parent_scene = self.current_scene.owner_subsystem.scene()
            self.current_scene.owner_subsystem.rebuild_ports()
            self.open_subsystem_scene(parent_scene)

    def on_library_item_double_clicked(self, item):
        self.push_undo_snapshot()
        btype = item.data(Qt.ItemDataRole.UserRole)
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.current_scene.add_sim_block(btype, center.x() - 45, center.y() - 30)

    def collapse_selection_into_subsystem(self, selected_blocks, sub_name="Controller_Sub"):
        scene = self.current_scene
        sel_set = set(selected_blocks)
        if len(sel_set) < 1:
            return None

        avg_x = sum(b.pos().x() for b in sel_set) / len(sel_set)
        avg_y = sum(b.pos().y() for b in sel_set) / len(sel_set)

        sub_blk = scene.add_sim_block("Subsystem", avg_x, avg_y, name=sub_name)
        sub_scene = sub_blk.sub_scene

        internal_wires, incoming_wires, outgoing_wires = [], [], []
        for w in list(scene.wires):
            s_blk = w.start_port.parent_block
            e_blk = w.end_port.parent_block
            if s_blk in sel_set and e_blk in sel_set:
                internal_wires.append((s_blk, w.start_port.index, e_blk, w.end_port.index))
                scene.remove_wire(w)
            elif s_blk not in sel_set and e_blk in sel_set:
                incoming_wires.append((w.start_port, e_blk, w.end_port.index))
                scene.remove_wire(w)
            elif s_blk in sel_set and e_blk not in sel_set:
                outgoing_wires.append((s_blk, w.start_port.index, w.end_port))
                scene.remove_wire(w)

        min_x = min(b.pos().x() for b in sel_set)
        min_y = min(b.pos().y() for b in sel_set)
        for b in sel_set:
            scene.blocks.remove(b)
            scene.removeItem(b)
            b.setPos(b.pos().x() - min_x + 220, b.pos().y() - min_y + 180)
            sub_scene.addItem(b)
            sub_scene.blocks.append(b)

        for s_blk, s_idx, e_blk, e_idx in internal_wires:
            sub_scene.connect_ports(s_blk.out_ports[s_idx], e_blk.in_ports[e_idx])

        ext_in_connections = []
        for idx, (ext_src_port, int_dst_blk, int_dst_idx) in enumerate(incoming_wires):
            inport = sub_scene.add_sim_block(
                "Inport", 90, 180 + idx * 70,
                name=f"In_{idx + 1}", params={"port_number": str(idx + 1)}
            )
            sub_scene.connect_ports(inport.out_ports[0], int_dst_blk.in_ports[int_dst_idx])
            ext_in_connections.append((ext_src_port, idx))

        ext_out_connections = []
        out_map = {}
        for int_src_blk, int_src_idx, ext_dst_port in outgoing_wires:
            key = (int_src_blk, int_src_idx)
            if key not in out_map:
                out_idx = len(out_map)
                outport = sub_scene.add_sim_block(
                    "Outport", 620, 180 + out_idx * 70,
                    name=f"Out_{out_idx + 1}", params={"port_number": str(out_idx + 1)}
                )
                sub_scene.connect_ports(int_src_blk.out_ports[int_src_idx], outport.in_ports[0])
                out_map[key] = out_idx
            ext_out_connections.append((out_map[key], ext_dst_port))

        sub_blk.rebuild_ports()
        for ext_src_port, sub_in_idx in ext_in_connections:
            scene.connect_ports(ext_src_port, sub_blk.in_ports[sub_in_idx])
        for sub_out_idx, ext_dst_port in ext_out_connections:
            scene.connect_ports(sub_blk.out_ports[sub_out_idx], ext_dst_port)

        return sub_blk

    def on_create_subsystem_clicked(self):
        selected = [
            item for item in self.current_scene.selectedItems()
            if isinstance(item, BlockItem) and item.block_type not in ("Inport", "Outport")
        ]
        if not selected:
            QMessageBox.information(
                self, "Create Subsystem",
                "Select one or more blocks on the canvas first, then click 'Subsystem'."
            )
            return
        self.push_undo_snapshot()
        self.collapse_selection_into_subsystem(selected)

    def _build_default_hybrid_model(self):
        s = self.root_scene
        step = s.add_sim_block("Step", 60, 210, name="Step_Ref")
        summ = s.add_sim_block("Sum", 200, 212, name="Error_Sum")

        pid = s.add_sim_block("PID Controller", 310, 210, name="PID_Ctrl",
                              params={"Kp": "4.5", "Ki": "2.8", "Kd": "1.2", "N": "50.0"})
        sat = s.add_sim_block("Saturation", 450, 210, name="Actuator_Lim",
                              params={"lower_limit": "-6.0", "upper_limit": "6.0"})
        zoh = s.add_sim_block("Zero-Order Hold", 580, 210, name="DAC_ZOH",
                              params={"sample_time": "0.15"})
        plant = s.add_sim_block("Transfer Fcn", 720, 210, name="Plant_G",
                                params={"numerator": "[1]", "denominator": "[1, 1.2, 1]"})
        delay = s.add_sim_block("Unit Delay", 460, 350, name="Sensor_1_z",
                                params={"initial_condition": "0.0", "sample_time": "0.15"},
                                flipped=True)

        mux = s.add_sim_block("Mux", 900, 185, name="Signal_Mux", params={"inputs": "3"})
        scope = s.add_sim_block("Scope", 965, 188, name="Main_Scope",
                                params={"title": "Step Reference vs. ZOH Actuator vs. Plant Output"})

        s.connect_ports(step.out_ports[0], summ.in_ports[0])
        s.connect_ports(summ.out_ports[0], pid.in_ports[0])
        s.connect_ports(pid.out_ports[0], sat.in_ports[0])
        s.connect_ports(sat.out_ports[0], zoh.in_ports[0])
        s.connect_ports(zoh.out_ports[0], plant.in_ports[0])
        s.connect_ports(plant.out_ports[0], delay.in_ports[0])
        s.connect_ports(delay.out_ports[0], summ.in_ports[1])

        s.connect_ports(step.out_ports[0], mux.in_ports[0])
        s.connect_ports(zoh.out_ports[0], mux.in_ports[1])
        s.connect_ports(plant.out_ports[0], mux.in_ports[2])
        s.connect_ports(mux.out_ports[0], scope.in_ports[0])

        self.collapse_selection_into_subsystem([pid, sat], sub_name="Controller_Sub")
        self.view.centerOn(520, 250)

    def _serialize_scene(self, scene: SimCanvasScene):
        blocks_data = []
        for b in scene.blocks:
            bdict = {
                "id": b.block_id,
                "type": b.block_type,
                "name": b.name,
                "x": b.pos().x(),
                "y": b.pos().y(),
                "flipped": b.flipped,
                "params": b.params
            }
            if b.block_type == "Subsystem" and b.sub_scene is not None:
                bdict["sub_scene"] = self._serialize_scene(b.sub_scene)
            blocks_data.append(bdict)

        wires_data = [
            {
                "from_block": w.start_port.parent_block.block_id,
                "from_port": w.start_port.index,
                "to_block": w.end_port.parent_block.block_id,
                "to_port": w.end_port.index
            }
            for w in scene.wires if w.end_port is not None
        ]
        return {"blocks": blocks_data, "wires": wires_data}

    def serialize_model(self):
        return {
            "version": "3.1",
            "stop_time": self.stop_time_edit.text(),
            "dt": self.dt_edit.text(),
            "root": self._serialize_scene(self.root_scene)
        }

    def _deserialize_scene(self, scene: SimCanvasScene, sdata: dict):
        id_map = {}
        for bdata in sdata.get("blocks", []):
            blk = scene.add_sim_block(
                bdata["type"], bdata["x"], bdata["y"],
                block_id=bdata["id"], name=bdata.get("name"),
                params=bdata.get("params"), flipped=bdata.get("flipped", False)
            )
            if blk.block_type == "Subsystem" and "sub_scene" in bdata:
                self._deserialize_scene(blk.sub_scene, bdata["sub_scene"])
                blk.rebuild_ports()
            id_map[blk.block_id] = blk

        for wdata in sdata.get("wires", []):
            src = id_map.get(wdata["from_block"])
            dst = id_map.get(wdata["to_block"])
            if src and dst:
                scene.connect_ports(src.out_ports[wdata["from_port"]], dst.in_ports[wdata["to_port"]])

    def _restore_from_dict(self, data: dict):
        self.open_subsystem_scene(self.root_scene)
        for w in list(self.root_scene.wires):
            self.root_scene.remove_wire(w)
        for b in list(self.root_scene.blocks):
            self.root_scene.removeItem(b)
        self.root_scene.blocks.clear()
        BlockItem._id_counter = 1

        self.stop_time_edit.setText(str(data.get("stop_time", "10.0")))
        self.dt_edit.setText(str(data.get("dt", "0.01")))
        root_data = data.get("root", data)
        self._deserialize_scene(self.root_scene, root_data)

    def load_model_from_file(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._restore_from_dict(data)
        self.statusBar().showMessage(f"Loaded hierarchical model from {path}")

    def on_save_json_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save OctaLink Model", "hybrid_model.octalink.json", "OctaLink JSON (*.json)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.serialize_model(), f, indent=2)
            self.statusBar().showMessage(f"Saved model to {path}")

    def on_load_json_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load OctaLink Model", "", "OctaLink JSON (*.json)"
        )
        if path:
            self.load_model_from_file(path)

    def on_linear_analysis_clicked(self):
        try:
            t_stop = float(self.stop_time_edit.text())
            dt = float(self.dt_edit.text())
            analysis_data = self.sim_engine.perform_linear_analysis(self.root_scene, t_stop=t_stop, dt=dt)
            LinearAnalysisDialog(analysis_data, self).exec()
        except Exception as e:
            QMessageBox.critical(self, "Linear Analysis Error", str(e))

    def on_export_c_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Embedded ANSI C99 Library", "octalink_model.c", "ANSI C Source (*.c)"
        )
        if not path:
            return
        try:
            dt = float(self.dt_edit.text())
            h_path, c_path = self.sim_engine.export_embedded_c_code(self.root_scene, dt, path)
            self.statusBar().showMessage(f"Exported ANSI C99 library: {h_path} & {c_path}")
            QMessageBox.information(
                self, "Embedded ANSI C99 Export Complete",
                f"Generated standalone C99 files:\n• {h_path}\n• {c_path}\n\n"
                "Call OctaLink_Init(&state) at startup and OctaLink_Step(&state, dt) inside your timer ISR."
            )
        except Exception as e:
            QMessageBox.critical(self, "C Code Export Error", str(e))

    def on_export_m_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Standalone GNU Octave Script", "octalink_hybrid_sim.m", "Octave Script (*.m)"
        )
        if not path:
            return
        try:
            t_stop = float(self.stop_time_edit.text())
            dt = float(self.dt_edit.text())
            self.sim_engine.export_octave_m_script(self.root_scene, t_stop, dt, path)
            self.statusBar().showMessage(f"Exported standalone hybrid ode45 script to {path}")
            QMessageBox.information(
                self, "Export Complete",
                f"Standalone GNU Octave script exported to:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def on_run_clicked(self):
        try:
            t_stop = float(self.stop_time_edit.text())
            dt = float(self.dt_edit.text())
            self.sim_engine.run_simulation(self.root_scene, t_stop=t_stop, dt=dt)
            self.statusBar().showMessage(f"Simulation completed (t = 0 to {t_stop}s).")

            prim_blocks, _ = self.sim_engine.flatten_hierarchy(self.root_scene)
            for b in prim_blocks:
                if b.block_type == "Scope":
                    ScopeDialog(b, self).exec()
                    break
        except Exception as e:
            QMessageBox.critical(self, "Simulation Error", str(e))


# Preserve the original engine qualification harness while using the MVP editor
# for all ordinary application launches.
PrototypeMainWindow = OctaLinkMainWindow
from mvp_editor import create_mvp_window
OctaLinkMainWindow = create_mvp_window(PrototypeMainWindow, sys.modules[__name__])

# ============================================================================
# 6. CANONICAL SELF-TEST SUITE (--self-test)
# ============================================================================
def run_canonical_self_test():
    print("[1/6] Initializing OctaLink, Vector SVG Icons & testing Undo/Redo + Block Flipping...")
    app = QApplication(sys.argv)
    win = PrototypeMainWindow()

    assert not make_svg_icon("app").isNull(), "SVG Icon renderer failed to produce valid QIcon"
    delays = [b for b in win.root_scene.blocks if b.block_type == "Unit Delay"]
    assert len(delays) == 1 and delays[0].flipped is True, "Feedback Unit Delay should be flipped"

    initial_count = len(win.root_scene.blocks)
    win.push_undo_snapshot()
    win.root_scene.add_sim_block("Constant", 100, 450, name="Temp_Const")
    assert len(win.root_scene.blocks) == initial_count + 1
    win.on_undo_clicked()
    assert len(win.root_scene.blocks) == initial_count
    win.on_redo_clicked()
    assert len(win.root_scene.blocks) == initial_count + 1
    win.on_undo_clicked()

    print("[2/6] Verifying Padé Delay Linearization (linmod), Poles, Bode/Nyquist & Stability Margins...")
    analysis_pade = win.sim_engine._prototype_perform_linear_analysis(win.root_scene, t_stop=10.0, dt=0.01, use_pade=True)
    assert analysis_pade["A"].shape == (6, 6), (
        f"Expected 6x6 Padé-augmented A matrix (2 PID + 2 Plant + 1 ZOH Padé + 1 Delay Padé), got {analysis_pade['A'].shape}"
    )
    margins = analysis_pade["margins"]
    metrics = analysis_pade["step_metrics"]
    print(f"      -> 6-State Padé Poles: {[round(p.real, 3) for p in analysis_pade['poles']]}")
    print(f"      -> Gain Margin: {margins['gain_margin_db']:.2f} dB | Phase Margin: {margins['phase_margin_deg']:.2f} deg")
    print(f"      -> Step Metrics: Tr={metrics['rise_time']:.3f}s, Ts={metrics['settling_time']:.3f}s, "
          f"OS={metrics['overshoot_pct']:.2f}%, ess={metrics['ss_error']:.4f}")

    print("[3/6] Verifying Embedded ANSI C99 Code Generation (.h / .c) & GCC Compilation...")
    tmpdir = tempfile.mkdtemp()
    try:
        c_base = os.path.join(tmpdir, "octalink_model.c")
        h_path, c_path = win.sim_engine._prototype_export_embedded_c_code(win.root_scene, 0.01, c_base)
        assert os.path.exists(h_path) and os.path.exists(c_path)

        if shutil.which("gcc"):
            test_main = os.path.join(tmpdir, "main.c")
            with open(test_main, "w", encoding="utf-8") as f:
                f.write(
                    '#include <stdio.h>\n#include "octalink_model.h"\n'
                    'int main(void) {\n'
                    '    OctaLink_State st;\n'
                    '    OctaLink_Init(&st);\n'
                    '    for (int k = 0; k < 1000; ++k) OctaLink_Step(&st, 0.01);\n'
                    '    printf("C99_FINAL_PLANT=%.4f\\n", st.y_out[2]);\n'
                    '    return 0;\n}\n'
                )
            bin_path = os.path.join(tmpdir, "test_sim")
            subprocess.run(["gcc", "-std=c99", "-O2", "-Wall", test_main, c_path, "-lm", "-o", bin_path], check=True)
            out = subprocess.check_output([bin_path], text=True).strip()
            print(f"      -> Compiled & Executed Native C99 Binary: {out}")
    finally:
        shutil.rmtree(tmpdir)

    print("[4/6] Verifying Nonlinear Math, State-Space, Safe Regex Octave Function & Demux...")
    test_scene = SimCanvasScene(win)
    c1 = test_scene.add_sim_block("Constant", 0, 0, params={"value": "2.0"})
    c2 = test_scene.add_sim_block("Constant", 0, 80, params={"value": "3.0"})
    prod = test_scene.add_sim_block("Product", 120, 40, params={"ops": "**"})
    trig = test_scene.add_sim_block("Trig", 240, 40, params={"operator": "cos"})
    # Expression includes 'sqrt' (contains letter 'u') to verify word-boundary regex replacement!
    ufcn = test_scene.add_sim_block("Octave Function", 360, 40, params={"expression": "2*u + sqrt(1.0)"})
    ss_blk = test_scene.add_sim_block("State-Space", 500, 40, params={
        "A": "[-2.0, -1.0; 1.0, 0.0]", "B": "[1.0; 0.0]", "C": "[0.0, 1.0]", "D": "0.0", "x0": "[0.0; 0.0]"
    })
    mux2 = test_scene.add_sim_block("Mux", 640, 40, params={"inputs": "2"})
    demux2 = test_scene.add_sim_block("Demux", 700, 40, params={"outputs": "2"})
    sc_test = test_scene.add_sim_block("Scope", 800, 40)

    test_scene.connect_ports(c1.out_ports[0], prod.in_ports[0])
    test_scene.connect_ports(c2.out_ports[0], prod.in_ports[1])
    test_scene.connect_ports(prod.out_ports[0], trig.in_ports[0])
    test_scene.connect_ports(trig.out_ports[0], ufcn.in_ports[0])
    test_scene.connect_ports(ufcn.out_ports[0], ss_blk.in_ports[0])
    test_scene.connect_ports(ufcn.out_ports[0], mux2.in_ports[0])
    test_scene.connect_ports(ss_blk.out_ports[0], mux2.in_ports[1])
    test_scene.connect_ports(mux2.out_ports[0], demux2.in_ports[0])
    test_scene.connect_ports(demux2.out_ports[1], sc_test.in_ports[0])

    win.sim_engine.run_simulation(test_scene, t_stop=10.0, dt=0.01)
    expected_u = 2.0 * math.cos(6.0) + 1.0
    actual_ss = sc_test.scope_y[-1][0]
    assert abs(actual_ss - expected_u) < 0.05, f"Expected steady-state ~{expected_u:.4f}, got {actual_ss:.4f}"
    print(f"      -> Nonlinear + State-Space + Demux Channel[2] Output: {actual_ss:.4f} (Target: {expected_u:.4f})")

    print("[5/6] Verifying Switch, Relay & To CSV Sink Blocks...")
    tmpdir_csv = tempfile.mkdtemp()
    try:
        csv_file = os.path.join(tmpdir_csv, "test_out.csv")
        sw_scene = SimCanvasScene(win)
        sine_src = sw_scene.add_sim_block("Sine Wave", 0, 0, params={"amplitude": "1.0", "frequency": "2.0", "phase": "0.0"})
        relay_blk = sw_scene.add_sim_block("Relay", 140, 0, params={
            "switch_on_point": "0.5", "switch_off_point": "-0.5", "on_val": "5.0", "off_val": "-5.0"
        })
        alt_const = sw_scene.add_sim_block("Constant", 140, 90, params={"value": "-1.0"})
        sw_blk = sw_scene.add_sim_block("Switch", 300, 20, params={"threshold": "0.0"})
        csv_sink = sw_scene.add_sim_block("To CSV", 440, 20, params={"filename": csv_file})

        sw_scene.connect_ports(relay_blk.out_ports[0], sw_blk.in_ports[0])
        sw_scene.connect_ports(sine_src.out_ports[0], relay_blk.in_ports[0])
        sw_scene.connect_ports(sine_src.out_ports[0], sw_blk.in_ports[1])
        sw_scene.connect_ports(alt_const.out_ports[0], sw_blk.in_ports[2])
        sw_scene.connect_ports(sw_blk.out_ports[0], csv_sink.in_ports[0])

        win.sim_engine.run_simulation(sw_scene, t_stop=2.0, dt=0.05)
        assert os.path.exists(csv_file) and os.path.getsize(csv_file) > 100, "To CSV block did not write CSV file"
        print(f"      -> Switch + Relay + To CSV verified ({os.path.getsize(csv_file)} bytes written)")
    finally:
        shutil.rmtree(tmpdir_csv)

    print("[6/6] Verifying Octave .m Export with Plotting Commands Restored...")
    with tempfile.NamedTemporaryFile(suffix=".m", delete=False) as tf_m:
        m_path = tf_m.name
    win.sim_engine._prototype_export_octave_m_script(win.root_scene, 5.0, 0.01, m_path)
    with open(m_path, "r", encoding="utf-8") as f:
        m_content = f.read()
    assert "plot(T_log, Y_log" in m_content and "legend(" in m_content, "Missing plot commands in exported .m script"
    os.remove(m_path)
    print("ALL 6 CANONICAL SELF-TESTS PASSED SUCCESSFULLY.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OctaLink native visual modeling MVP")
    parser.add_argument("model", nargs="?", help="OctaLink JSON model to open")
    parser.add_argument("--self-test", action="store_true", help="run the retained prototype harness")
    parser.add_argument("--check", action="store_true", help="validate and simulate a JSON model without opening the GUI")
    parser.add_argument("--backend", choices=("python", "octave"), help="select the simulation engine")
    parser.add_argument("--octave", help="GNU Octave executable path")
    args = parser.parse_args()
    if args.check:
        from mvp_model import read_document
        from simulation_service import simulate_document
        if not args.model:
            parser.error("--check requires a model JSON path")
        try:
            data = read_document(args.model, BLOCK_SPECS)
            results = simulate_document(data, BLOCK_SPECS, backend=args.backend, executable=args.octave)
            samples = max((len(r[0]) for r in results.values()), default=0)
            print(f"MODEL CHECK OK: {len(data.get('root',data)['blocks'])} root blocks; {samples} samples; stop time {data.get('stop_time', 10)} s; backend={args.backend or data.get('backend','python')}")
            return 0
        except Exception as exc:
            print(f"MODEL CHECK FAILED: {exc}", file=sys.stderr)
            return 1
    if args.self_test:
        run_canonical_self_test()
        return 0

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = OctaLinkMainWindow()
    win.octave_executable = args.octave
    if args.model:
        try:
            win.load_model_from_file(args.model)
        except Exception as exc:
            win.report_error(f"Could not open startup model: {exc}")
    if args.backend:
        win.backend_combo.setCurrentIndex(win.backend_combo.findData(args.backend))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
