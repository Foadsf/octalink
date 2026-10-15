"""Drive the real OctaLink GUI through UI Automation with the surfacekit toolkit.

Windows only. Each model is copied to a scratch directory, opened by a freshly
launched editor on a private hidden desktop (no window reaches the screen, no
focus is taken, memory is capped), and driven only through UIA control
patterns -- no synthetic keystrokes. Results are read back through UIA and from
the saved model file (the file format is the tier-0 surface).

    python tests/verify_gui_surface.py [model-stem ...] [--octave]

surfacekit.py is found through SURFACEKIT_HOME or C:\\dev\\scripts.
Exit 0 all checks passed, 1 a check failed, 3 the instrument could not tell.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("SURFACEKIT_HOME", r"C:\dev\scripts"))
sys.path.insert(0, str(KIT))
try:
    import surfacekit as sk
except ImportError:
    print(f"[COULD NOT TELL] surfacekit.py not found in {KIT}; set SURFACEKIT_HOME")
    sys.exit(3)

DEFAULT_MODELS = ("mwe_aircraft_pitch_lqr", "mwe_inverted_pendulum", "mwe_motor_speed_lag_lead",
                  "mwe_motor_position_digital", "mwe_house_heating", "mwe_inverted_pendulum_loop")
# A parameter each model exposes, edited through Model Browser + Property Inspector.
EDITS = {"mwe_aircraft_pitch_lqr": ("Nbar", "Gain", "1"),
         "mwe_inverted_pendulum": ("Impulse (1 N s)", "Amplitude", "500"),
         "mwe_inverted_pendulum_loop": ("Impulse (1 N s)", "Amplitude", "500"),
         "mwe_motor_speed_lag_lead": ("Lag compensator", "Numerator", "[40 40]"),
         "mwe_motor_position_digital": ("Controller", "Gain", "700"),
         "mwe_house_heating": ("Set Point (F)", "Value", "68")}
RUN_TIMEOUT = {"mwe_house_heating": 600, "mwe_motor_position_digital": 600, "mwe_inverted_pendulum_loop": 600}
SOLVER_LABELS = {"rk4": "RK4 (explicit)", "sdirk4": "SDIRK4 (implicit, stiff)"}   # as the editor shows them


class Session:
    def __init__(self, model_path, log):
        self.log = log
        self.app = sk.LaunchedApp(sys.executable, [str(ROOT / "octalink_gui.py"), str(model_path)],
                                  hidden=True, cwd=str(ROOT), title_has="OctaLink", timeout=60,
                                  output_to=str(model_path.with_suffix(".stdout.log")))
        self.desk = self.app.desktop.path

    def ops(self, *ops, hwnd=None):
        result = sk.uia_batch([dict(op, hwnd=hwnd or self.app.top) for op in ops], desktop=self.desk)
        if result is None:
            raise RuntimeError("UIA worker failed (could not tell)")
        return result

    def one(self, **op):
        return self.ops(op)[0]

    def diagnostics(self):
        r = self.one(op="get", name="Diagnostics", type="Edit")
        return r.get("value", "") if r.get("ok") else ""

    def wait_diag(self, needles, timeout, since=""):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            text = self.diagnostics()
            fresh = text[len(since):] if text.startswith(since) else text
            for needle in needles:
                if needle in fresh:
                    return needle, fresh
            time.sleep(0.5)
        return None, self.diagnostics()

    def windows(self):
        return {h: sk.window_text(h) or "" for h in self.app.desktop.windows(self.app.pid)
                if sk.window_text(h)}

    def window_titled(self, part, timeout=10):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for h, title in self.windows().items():
                if part in title:
                    return h
            time.sleep(0.25)
        return 0


def drive(stem, use_octave, results):
    work = Path(tempfile.mkdtemp(prefix="gui-surface-", dir=ROOT / ".tmp"))
    model = work / f"{stem}.json"
    shutil.copy(ROOT / "examples" / f"{stem}.json", model)
    original = json.loads(model.read_text(encoding="utf-8"))
    checks = []

    def check(name, passed, detail=""):
        checks.append((name, bool(passed), detail))
        print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f" -- {detail}" if detail else ""), flush=True)

    s = Session(model, print)
    try:
        title = sk.window_text(s.app.top) or ""
        check("launched on hidden desktop without focus", s.app.top and not s.app.focus_taken
              and not s.app.on_default_desktop, f"title={title!r}")
        check("title names the model", model.name in title)
        # Model Browser lists the hierarchy, including subsystem contents.
        # Rows scrolled out of the dock are absent from the UIA tree, so every
        # root block is reached through the filter box (one batched worker).
        probes = []
        for block in original["root"]["blocks"]:
            probes += [{"op": "set", "name": "Filter model blocks", "type": "Edit", "value": block["name"]},
                       {"op": "find", "name": block["name"], "type": "ListItem"}]
        found = s.ops(*probes, {"op": "set", "name": "Filter model blocks", "type": "Edit", "value": ""})
        missing = [b["name"] for b, r in zip(original["root"]["blocks"], found[1::2]) if not r.get("matches")]
        check("Model Browser reaches every root block", not missing, f"missing={missing}")
        before = s.diagnostics()
        s.one(op="invoke", name="Check Model", type="Button")
        hit, _ = s.wait_diag(["Model check passed", "Error:"], 30, before)
        check("Check Model passes", hit == "Model check passed")
        if stem.endswith("_loop"):
            time.sleep(0.5)
            report = s.diagnostics()[len(before):]
            check("Check Model reports the algebraic loop and its Newton variables",
                  "Algebraic loop of" in report and "solved by Newton" in report,
                  next((l for l in report.splitlines() if "Algebraic loop" in l), ""))
        solver = s.one(op="get", name="Solver", type="ComboBox")
        expected_solver = SOLVER_LABELS[original.get("solver", "rk4")]
        check("Solver control shows the model's solver", solver.get("value") == expected_solver,
              str(solver.get("value")))
        before = s.diagnostics()
        s.one(op="invoke", name="Run", type="Button")
        hit, text = s.wait_diag(["Simulation complete", "Error:"], RUN_TIMEOUT.get(stem, 240), before)
        check("Run completes on Local Python", hit == "Simulation complete" and f"{expected_solver} solver" in text,
              text.strip().splitlines()[-1] if text.strip() else "")
        scopes = [t for t in s.windows().values() if "Scope" in t]
        expected = sum(1 for _ in _scopes(original["root"]))
        check("every Scope opens a result window", len(scopes) == expected, f"{len(scopes)}/{expected}: {scopes}")
        # Reach a block inside a subsystem: filter the Model Browser, select its
        # path; the editor must enter that subsystem and inspect the block.
        sub = next((b for b in original["root"]["blocks"] if b["type"] == "Subsystem"), None)
        if sub:
            inner = next(b for b in sub["sub_scene"]["blocks"] if b["type"] not in ("Inport", "Outport"))
            s.one(op="set", name="Filter model blocks", type="Edit", value=sub["name"])
            time.sleep(0.5)
            r = s.one(op="select", name=f"{sub['name']} › {inner['name']}", type="ListItem")
            time.sleep(0.6)
            shown = s.one(op="get", name="Block name", type="Edit").get("value")
            crumbs = [e["name"] for e in s.one(op="find", type="Text").get("elements", []) if e["name"].startswith("Root")]
            check("Model Browser reaches a block inside a subsystem", r.get("ok") and shown == inner["name"]
                  and any(sub["name"] in c for c in crumbs), f"inspector={shown!r} breadcrumb={crumbs}")
            s.one(op="set", name="Filter model blocks", type="Edit", value="")
            time.sleep(0.4)
        # Edit a parameter through the accessible list and inspector.
        target, field, value = EDITS[stem]
        r = s.one(op="select", name=target, type="ListItem")
        check(f"Model Browser selects {target!r}", r.get("ok"), r.get("error", ""))
        time.sleep(0.6)
        name_box = s.one(op="get", name="Block name", type="Edit")
        check("Property Inspector shows the selected block", name_box.get("value") == target, str(name_box.get("value")))
        r = s.one(op="set", name=field, type="Edit", value=value)
        check(f"set {field} = {value} via ValuePattern", r.get("ok"), r.get("error", ""))
        before = s.diagnostics()
        s.one(op="invoke", name="Apply", type="Button")
        hit, _ = s.wait_diag([f"Updated {target}.", "Error:"], 15, before)
        check("Apply commits the edit", hit == f"Updated {target}.")
        dirty = sk.window_text(s.app.top) or ""
        check("title marks the model modified", dirty.startswith("*"), dirty)
        # Model Workspace: open, verify variables, cancel (no change).
        if original.get("variables"):
            s.one(op="select", name="Modeling", type="TabItem")
            time.sleep(0.3)
            s.one(op="click", name="Model Workspace", type="Button")     # posted: the dialog is modal
            dialog = s.window_titled("Model Workspace")
            check("Model Workspace dialog opens", dialog)
            if dialog:
                cells = s.one(op="find", type="DataItem", hwnd=dialog)
                cell_names = {e["name"] for e in cells.get("elements", [])}
                first = list(original["variables"])[:6]
                check("Model Workspace table shows the variables", all(k in cell_names for k in first),
                      f"{len(cell_names & set(original['variables']))}/{len(original['variables'])} rows exposed")
                # Rows below the fold are absent from UIA; the status line names
                # every evaluated variable, so it proves all of them resolved.
                status = s.one(op="find", type="Text", hwnd=dialog)
                text = next((e["name"] for e in status.get("elements", []) if e["name"].startswith("Valid.")), "")
                missing = [k for k in original["variables"] if not re.search(rf"(^|\s){re.escape(k)} =", text)]
                check("Model Workspace evaluates every variable", text and not missing, f"missing={missing}")
                s.one(op="invoke", name="Cancel", type="Button", hwnd=dialog)
                time.sleep(0.5)
                check("Cancel closes the Model Workspace dialog", not sk._u32.IsWindowVisible(dialog))
            s.one(op="select", name="Simulation", type="TabItem")
        if use_octave:
            # The combo's accessible value is read-only; the Simulation menu is the
            # accessible route: Simulation > Engine > GNU Octave.
            s.one(op="expand", name="Simulation", type="MenuItem")
            time.sleep(0.4)
            popup = next((h for h in s.app.desktop.windows(s.app.pid) if "Popup" in sk.class_name(h)), 0)
            if popup:
                s.one(op="expand", name="Engine", type="MenuItem", hwnd=popup)
                time.sleep(0.4)
                for h in s.app.desktop.windows(s.app.pid):
                    if "Popup" in sk.class_name(h):
                        hit = s.one(op="invoke", name="GNU Octave", type="MenuItem", hwnd=h)
                        if hit.get("ok"):
                            break
            time.sleep(0.4)
            engine = s.one(op="get", name="Simulation engine", type="ComboBox")
            check("engine switched to GNU Octave via the Simulation menu", engine.get("value") == "GNU Octave",
                  str(engine.get("value")))
            before = s.diagnostics()
            s.one(op="invoke", name="Run", type="Button")
            hit, text = s.wait_diag(["Simulation complete", "Error:"], RUN_TIMEOUT.get(stem, 240) * 2, before)
            check("Run completes on GNU Octave", hit == "Simulation complete" and "GNU Octave engine" in text,
                  text.strip().splitlines()[-1] if text.strip() else "")
        # Save through the toolstrip and read the file back.
        before = s.diagnostics()
        # Scope windows carry Matplotlib's own "Save" (figure) button: address
        # the model Save inside the Quick Access toolbar.
        s.one(op="invoke", name="Save", type="Button", under="Quick Access")
        hit, _ = s.wait_diag(["Saved ", "Error:"], 15, before)
        saved = json.loads(model.read_text(encoding="utf-8"))
        check("Save writes the file", hit == "Saved ")

        def find(scene):
            for b in scene["blocks"]:
                if b["name"] == target:
                    return b
                if "sub_scene" in b:
                    found = find(b["sub_scene"])
                    if found:
                        return found
        key = field.lower().replace(" ", "_")
        check("saved file holds the edited parameter", find(saved["root"])["params"].get(key) == value)
        check("saved file keeps provenance and variables",
              saved.get("provenance") == original.get("provenance") and saved.get("variables") == original.get("variables"))
        check("saved file keeps the solver", saved.get("solver") == original.get("solver", "rk4"), str(saved.get("solver")))
        clean = sk.window_text(s.app.top) or ""
        check("title clean after save", not clean.startswith("*"), clean)
        # Closing with unsaved changes must ask; Discard must then close.
        s.one(op="set", name="Stop time", type="Edit", value="1")
        time.sleep(0.6)
        sk._u32.PostMessageW(s.app.top, 0x0010, 0, 0)          # WM_CLOSE, as the title-bar X sends
        prompt = s.window_titled("Unsaved Model", timeout=8)
        check("close with unsaved changes asks to save", prompt,
              "" if prompt else f"windows={sorted(set(s.windows().values()))}")
        if prompt:
            s.one(op="invoke", name="Discard", type="Button", hwnd=prompt)
            try:
                s.app.proc.wait(10)
            except Exception:
                pass
            check("Discard closes the editor", s.app.proc.poll() is not None)
            check("Discard leaves the saved file untouched",
                  json.loads(model.read_text(encoding="utf-8"))["stop_time"] == saved["stop_time"])
    finally:
        closed = s.app.close(timeout=10)
        check("editor closes cleanly", closed)
    results[stem] = checks
    return all(passed for _, passed, _ in checks)


def _scopes(scene):
    for b in scene["blocks"]:
        if b["type"] == "Scope":
            yield b
        if "sub_scene" in b:
            yield from _scopes(b["sub_scene"])


def main(argv):
    use_octave = "--octave" in argv
    stems = [a for a in argv if not a.startswith("--")] or list(DEFAULT_MODELS)
    (ROOT / ".tmp").mkdir(exist_ok=True)
    results, ok = {}, True
    for stem in stems:
        print(f"== {stem}{' (+ GNU Octave)' if use_octave else ''}", flush=True)
        try:
            ok &= drive(stem, use_octave, results)
        except RuntimeError as exc:
            print(f"[COULD NOT TELL] {stem}: {exc}")
            return 3
    out = ROOT / "artifacts" / "verification" / "gui-surface.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({k: [{"check": n, "passed": p, "detail": d} for n, p, d in v]
                               for k, v in results.items()}, indent=2) + "\n", encoding="utf-8")
    total = sum(len(v) for v in results.values())
    failed = sum(1 for v in results.values() for _, p, _ in v if not p)
    print(f"GUI SURFACE: {total - failed}/{total} checks passed across {len(results)} models.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
