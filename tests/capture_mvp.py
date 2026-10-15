"""Render the real editor and scope after an actual background simulation."""
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if "--live" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from octalink_gui import OctaLinkMainWindow

app = QApplication([])
app.setStyle("Fusion")
window = OctaLinkMainWindow(str(ROOT/"examples"/"first_order_feedback.json"))
window.show()
count = 0

def start():
    window.finish_layout()
    if "--octave" in sys.argv:
        window.backend_combo.setCurrentIndex(window.backend_combo.findData("octave"))
    if "--curved" in sys.argv:
        window.ribbon.setCurrentIndex(2)
        QTest.mouseClick(window.connection_style_button, Qt.MouseButton.LeftButton)
        assert window.root_scene.connection_style == "curved"
    window.on_run_clicked()

def capture():
    global count
    count += 1
    if window.worker:
        if count > 300:
            window.stop_simulation()
            print("UI CAPTURE FAILED: simulation timeout")
            app.exit(1)
        return
    blocks = window.root_scene.blocks
    scope = next(b for b in blocks if b.block_type == "Scope")
    if not scope.scope_t:
        return
    window.refresh_document_ui()
    assert abs(scope.scope_t[-1]-3) < 1e-12
    assert abs(scope.scope_y[-1][1]-(1-__import__("math").exp(-4))) < 1e-7
    suffix = "-curved" if "--curved" in sys.argv else ""
    if "--octave" in sys.argv:
        suffix += "-octave"
    if "--curved" in sys.argv:
        assert all(any(w.path().elementAt(i).isCurveTo() for i in range(w.path().elementCount())) for w in window.root_scene.wires)
    assert window.grab().save(str(ROOT/"artifacts"/f"editor{suffix}.png"))
    assert window.scope_windows[0].grab().save(str(ROOT/"artifacts"/f"scope{suffix}.png"))
    print(f"UI CAPTURE OK: editor + scope; {len(scope.scope_t)} samples; output={scope.scope_y[-1][1]:.10f}; connections={getattr(window.root_scene, 'connection_style', 'orthogonal')}; backend={window.backend_combo.currentData()}")
    timer.stop()
    window.saved_document = window.serialize_model()
    window.close()
    app.quit()

QTimer.singleShot(300, start)
timer = QTimer()
timer.timeout.connect(capture)
timer.start(100)
QTimer.singleShot(30000, lambda: app.exit(1))
sys.exit(app.exec())
