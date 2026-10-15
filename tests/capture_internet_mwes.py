"""Capture actual native Qt Octave workflows; --live uses visible Windows Qt.

Windows/PowerShell: python tests/capture_internet_mwes.py [--live]
Every image follows a successful real Run-button simulation and plot/reference
checks. No external application or existing desktop session is touched.
"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/"tests"))
if "--live" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "windows" if os.name == "nt" else "xcb"
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from test_internet_editor import (APP, NAMES, OctaLinkMainWindow,
    check_reference, close_window, diagram_geometry, run_via_button)


def main():
    APP.setStyle("Fusion")
    output = ROOT/"artifacts"/"internet-mwes"
    output.mkdir(parents=True, exist_ok=True)
    measurements = {}
    for name in NAMES:
        window = OctaLinkMainWindow(str(ROOT/"examples"/f"mwe_{name}.json"))
        try:
            window.resize(1500, 950)
            window.show()
            APP.processEvents()
            window.finish_layout()
            traces = run_via_button(window, "octave", timeout=60)
            expected = check_reference(name, traces)
            measurements[name] = {"backend": "octave", "scopes": len(traces),
                "samples": len(next(iter(traces.values()))[0]),
                "reference_max_error": max(float(abs(traces[sink][1]-expected[sink]).max()) for sink in expected),
                "images": []}
            scope_dialog = window.scope_windows[0]
            scope_dialog.resize(1050, 650)
            APP.processEvents()
            scope_path = output/f"{name}-scope.png"
            assert scope_dialog.grab().save(str(scope_path)), scope_path
            measurements[name]["images"].append(scope_path.name)
            # Cruise has two independently checked plots; retain both artifacts.
            for index, dialog in enumerate(window.scope_windows[1:], 2):
                dialog.resize(1050, 650)
                APP.processEvents()
                path = output/f"{name}-scope-{index}.png"
                assert dialog.grab().save(str(path)), path
                measurements[name]["images"].append(path.name)
            for dialog in window.scope_windows:
                dialog.hide()
            for curved in (False, True):
                window.set_curved_connections(curved)
                window.fit_diagram()
                window.refresh_document_ui()
                APP.processEvents()
                diagram_geometry(window.root_scene, curved)
                style = "curved" if curved else "orthogonal"
                path = output/f"{name}-editor-{style}.png"
                assert window.grab().save(str(path)), path
                measurements[name]["images"].append(path.name)
            if name == "cruise_pi":
                vehicle = next(b for b in window.root_scene.blocks if b.block_type == "Subsystem")
                point = window.view.mapFromScene(vehicle.pos()+QPointF(vehicle.width/2, vehicle.height/2))
                QTest.mouseDClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
                APP.processEvents()
                assert window.current_scene is vehicle.sub_scene, "Native subsystem navigation failed"
                window.fit_diagram()
                APP.processEvents()
                diagram_geometry(window.current_scene, False)
                path = output/f"{name}-subsystem.png"
                assert window.grab().save(str(path)), path
                measurements[name]["images"].append(path.name)
            print(f"INTERNET CAPTURE OK: {name}; genuine Octave; samples={measurements[name]['samples']}; "
                  f"scopes={len(traces)}; reference error={measurements[name]['reference_max_error']:.3g}; "
                  f"images={len(measurements[name]['images'])}", flush=True)
        finally:
            close_window(window)
    (output/"capture-measurements.json").write_text(json.dumps(measurements, indent=2)+"\n", encoding="utf-8")
    print("INTERNET CAPTURE ACCEPTANCE OK: 3 examples; native editor and scope captures; independent full traces", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
