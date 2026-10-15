"""Exercise the real analysis selection dialog and render its four-panel view."""
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if "--live" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QComboBox, QLabel
from octalink_gui import OctaLinkMainWindow, LinearAnalysisDialog

app = QApplication([])
app.setStyle("Fusion")
window = OctaLinkMainWindow(str(ROOT/"examples"/"first_order_feedback.json"))
window.show()
saved = False

def choose_selection():
    dialog = app.activeModalWidget()
    if isinstance(dialog, QDialog) and dialog.windowTitle() == "Linear Analysis Selection":
        boxes = dialog.findChildren(QComboBox)
        assert len(boxes) == 2
        assert boxes[1].currentText().endswith("Integrator")
        dialog.accept()

def capture():
    global saved
    viewer = next((widget for widget in app.topLevelWidgets() if isinstance(widget, LinearAnalysisDialog) and widget.isVisible()), None)
    if viewer:
        assert len(viewer.canvas.figure.axes) == 4
        labels = " ".join(label.text() for label in viewer.findChildren(QLabel))
        assert "N/A" in labels
        assert "hypothetical" in labels
        assert viewer.grab().save(str(ROOT/"artifacts"/"linear-analysis.png"))
        print("ANALYSIS UI CAPTURE OK: source/output selection; 4 panels; missing crossings=N/A; margin interpretation visible", flush=True)
        saved = True
        timer.stop()
        viewer.accept()

QTimer.singleShot(300, choose_selection)
QTimer.singleShot(200, window.on_linear_analysis_clicked)
timer = QTimer()
timer.timeout.connect(capture)
timer.start(100)
def finish():
    if saved:
        window.saved_document = window.serialize_model()
        window.close()
        app.quit()
    else:
        QTimer.singleShot(100, finish)
QTimer.singleShot(500, finish)
QTimer.singleShot(15000, lambda: app.exit(1))
sys.exit(app.exec())
