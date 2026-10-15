"""Capture the second public-MWE set in the real editor (offscreen Qt by default).

Windows/PowerShell: python tests/capture_public_mwes_2.py [--live]
Each model is opened, simulated with the Run button, and its editor (both wire
styles), every subsystem, every scope and the Model Workspace are grabbed into
artifacts/public-mwes-2/. Layout checks from test_internet_editor run on every
diagram first, so an image is only written for a diagram that passed them.
"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
if "--live" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "windows" if os.name == "nt" else "xcb"
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog
from test_internet_editor import APP, OctaLinkMainWindow, close_window, diagram_geometry, run_via_button

NAMES = ("motor_speed_lag_lead", "inverted_pendulum", "house_heating", "aircraft_pitch_lqr", "motor_position_digital")


def subsystems(scene, trail=()):
    for block in scene.blocks:
        if block.block_type == "Subsystem" and block.sub_scene is not None:
            yield trail + (block.name,), block.sub_scene
            yield from subsystems(block.sub_scene, trail + (block.name,))


def main():
    APP.setStyle("Fusion")
    output = ROOT / "artifacts" / "public-mwes-2"
    output.mkdir(parents=True, exist_ok=True)
    measurements = {}
    for name in NAMES:
        window = OctaLinkMainWindow(str(ROOT / "examples" / f"mwe_{name}.json"))
        images = []
        try:
            window.resize(1500, 950)
            window.show()
            APP.processEvents()
            window.finish_layout()
            traces = run_via_button(window, "python", timeout=600)
            for index, dialog in enumerate(window.scope_windows, 1):
                dialog.resize(1050, 650)
                APP.processEvents()
                path = output / f"{name}-scope-{index}.png"
                assert dialog.grab().save(str(path)), path
                images.append(path.name)
                dialog.hide()
            for curved in (False, True):
                window.open_subsystem_scene(window.root_scene)
                window.set_curved_connections(curved)
                window.fit_diagram()
                window.refresh_document_ui()
                APP.processEvents()
                diagram_geometry(window.root_scene, curved)
                path = output / f"{name}-editor-{'curved' if curved else 'orthogonal'}.png"
                assert window.grab().save(str(path)), path
                images.append(path.name)
            window.set_curved_connections(False)
            for trail, scene in subsystems(window.root_scene):
                window.open_subsystem_scene(scene)
                window.fit_diagram()
                APP.processEvents()
                diagram_geometry(scene, scene.connection_style == "curved")
                path = output / f"{name}-subsystem-{'-'.join(t.replace(' ', '_') for t in trail)}.png"
                path = path.with_name("".join(c for c in path.name if c.isalnum() or c in "-_.()"))
                assert window.grab().save(str(path)), path
                images.append(path.name)
            window.open_subsystem_scene(window.root_scene)

            def grab_workspace():
                dialog = next(w for w in APP.topLevelWidgets() if isinstance(w, QDialog)
                              and w.windowTitle() == "Model Workspace" and w.isVisible())
                path = output / f"{name}-model-workspace.png"
                assert dialog.grab().save(str(path)), path
                images.append(path.name)
                dialog.reject()
            QTimer.singleShot(300, grab_workspace)
            window.edit_model_workspace()
            measurements[name] = {"samples": len(next(iter(traces.values()))[0]), "scopes": len(traces), "images": images}
            print(f"CAPTURE OK: {name}; {len(images)} images", flush=True)
        finally:
            close_window(window)
    (output / "capture-measurements.json").write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
