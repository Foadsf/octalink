"""Independent cross-engine/reference acceptance for the completed MVP.

Runs actual GNU Octave and compares the block simulation to adaptive ode45 on
the installed Van der Pol example. Run with a workspace TEMP/TMP on Windows.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
scratch = ROOT/".tmp"
scratch.mkdir(exist_ok=True)
tempfile.tempdir = str(scratch)
os.environ["TEMP"] = os.environ["TMP"] = str(scratch)
import numpy as np
from mvp_model import read_document
from octalink_gui import BLOCK_SPECS
from octave_backend import discover_octave, export_octave_script
from simulation_service import simulate_document


def octave_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def compare(left, right, label, tolerance=1e-9):
    assert set(left) == set(right), f"{label}: sink IDs differ"
    worst = 0.
    for ident in left:
        t, y, labels = left[ident]
        other_t, other_y, other_labels = right[ident]
        assert labels == other_labels, f"{label}: channel labels differ"
        np.testing.assert_allclose(t, other_t, rtol=0, atol=1e-12)
        error = float(np.max(np.abs(np.asarray(y)-np.asarray(other_y))))
        assert error < tolerance, f"{label}: max error {error} >= {tolerance}"
        worst = max(worst, error)
    return worst


def main():
    executable = discover_octave()
    if not executable:
        raise RuntimeError("GNU Octave is required for final delivery acceptance.")
    report = {}
    for path in sorted((ROOT/"examples").glob("*.json")):
        document = read_document(path, BLOCK_SPECS)
        local = simulate_document(document, BLOCK_SPECS, backend="python")
        native = simulate_document(document, BLOCK_SPECS, backend="octave", executable=executable)
        error = compare(local, native, path.name)
        count = max(len(value[0]) for value in native.values())
        report[path.name] = {"samples": count, "python_octave_max_error": error}
        print(f"CROSS-ENGINE: {path.name}: {count} samples; max Python/Octave error {error:.3g}", flush=True)

    document = read_document(ROOT/"examples"/"van_der_pol.json", BLOCK_SPECS)
    native = simulate_document(document, BLOCK_SPECS, backend="octave", executable=executable)
    grid, values, labels = next(iter(native.values()))
    with tempfile.TemporaryDirectory(dir=scratch) as job:
        result_file = Path(job)/"ode45.csv"
        program = Path(job)/"reference.m"
        vector = "["+" ".join(format(float(v), ".17g") for v in grid)+"]'"
        program.write_text("addpath("+octave_string(ROOT/"tests"/"references")+");\n"
                           "data=van_der_pol_reference("+vector+");\n"
                           "dlmwrite("+octave_string(result_file)+",data,'precision','%.17g');\n", encoding="utf-8")
        completed = subprocess.run([executable, "--no-init-file", "--no-gui", "--quiet", str(program)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if completed.returncode:
            raise RuntimeError(completed.stderr or completed.stdout)
        reference = np.loadtxt(result_file, delimiter=",")
    error = float(np.max(np.abs(np.asarray(values)-reference[:, 1:])))
    assert error < 1e-5, f"Van der Pol ode45 reference mismatch {error}"
    print(f"INDEPENDENT ODE45: Van der Pol max error {error:.3g}", flush=True)
    report["van_der_pol_ode45_max_error"] = error
    # The same comparison must reject an actually wrong dynamics trace.
    altered = np.asarray(values).copy()
    altered[:, 1] *= -1
    bad_error = float(np.max(np.abs(altered-reference[:, 1:])))
    assert bad_error > 1e-5
    print(f"NEGATIVE CONTROL: reversed velocity rejected; reference error {bad_error:.3g}", flush=True)
    report["negative_control_error"] = bad_error

    finer = copy.deepcopy(document)
    finer["dt"] = ".005"
    fine = simulate_document(finer, BLOCK_SPECS, backend="octave", executable=executable)
    fine_t, fine_y, _ = next(iter(fine.values()))
    indices = np.searchsorted(np.asarray(fine_t), np.asarray(grid))
    np.testing.assert_allclose(np.asarray(fine_t)[indices], grid, atol=1e-12, rtol=0)
    fine_error = float(np.max(np.abs(np.asarray(fine_y)[indices]-reference[:, 1:])))
    assert fine_error < error / 8, f"RK4 refinement did not reduce error sufficiently: {error} -> {fine_error}"
    print(f"STEP REFINEMENT: dt .01 -> .005; error {error:.3g} -> {fine_error:.3g}", flush=True)
    report["refined_error"] = fine_error
    (ROOT/"artifacts"/"verification"/"cross-engine-results.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print("MVP DELIVERY REFERENCE ACCEPTANCE OK", flush=True)


if __name__ == "__main__":
    main()
