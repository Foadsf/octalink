"""Verify each robotics OctaLink model: Python sim vs C99 codegen truth.

For every examples/robotics_*.json:
  1. read_document + simulate_document (python backend) -> engine truth
  2. export_c_model -> MSYS gcc compile -> native run -> compare allclose
  3. write per-sink CSVs to output/csv/<model>/ for Octave PNG export

Exit nonzero if any model fails.
"""
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np
from c_export import export_c_model
from mvp_model import read_document
from octalink_gui import BLOCK_SPECS, SimulationEngine
from simulation_service import simulate_document

CC = os.environ.get("OCTALINK_CC")
if not CC:
    from octalink_gui import _msys_gcc_toolchain
    _MSYS_CMD, _MSYS_ENV, _MSYS_FLAGS = _msys_gcc_toolchain()
    CC = _MSYS_CMD[0]
    USE_MSYS = True
else:
    USE_MSYS = False

CSV_OUT = ROOT / "output" / "csv"
CSV_OUT.mkdir(parents=True, exist_ok=True)

FAILURES = []


def c_compile_and_run(doc, stop, dt, directory):
    header, source = export_c_model(doc, BLOCK_SPECS, dt, directory / "model")
    runner_text = (
        '#include "model.h"\n#include <math.h>\n#include <stdio.h>\n'
        'int main(void) {\n'
        '    OctaLink_State st;\n'
        '    OctaLink_Init(&st);\n'
        '    for (;;) {\n'
        '        if (st.status) {\n'
        '            fprintf(stderr, "STATUS=%d BLOCK=%u TIME=%.17g\\n", '
        'st.status, st.error_block, st.t); return st.status; }\n'
        '        printf("%.17g", st.t);\n'
        '        for (int i = 0; i < OCTALINK_NUM_OUTPUTS; ++i)\n'
        '            printf(",%.17g", st.y_out[i]);\n'
        '        puts("");\n'
        '        if (st.t >= __STOP__) break;\n'
        '        OctaLink_Step(&st, __DT__);\n'
        '    }\n'
        '    return 0;\n'
        '}\n'
    ).replace("__STOP__", repr(stop)).replace("__DT__", repr(dt))
    runner = directory / "runner.c"
    runner.write_text(runner_text)
    executable = directory / ("run.exe" if os.name == "nt" else "run")
    env = dict(os.environ)
    if USE_MSYS:
        env.update(_MSYS_ENV)
        gcc_cmd = (list(_MSYS_CMD) + ["-std=c99", "-pedantic", "-Wall",
                                      "-Wextra", "-Werror", "-O2"] +
                   _MSYS_FLAGS)
    else:
        env["PATH"] = str(Path(CC).resolve().parent) + os.pathsep + \
            env.get("PATH", "")
        gcc_cmd = [CC, "-std=c99", "-pedantic", "-Wall", "-Wextra",
                   "-Werror", "-O2"]
    gcc_cmd += [str(source), str(runner), "-lm", "-o", str(executable)]
    res = subprocess.run(gcc_cmd, capture_output=True, text=True, env=env,
                         timeout=60)
    if res.returncode != 0:
        raise RuntimeError("C compile failed:\n" + res.stdout + res.stderr)
    res = subprocess.run([str(executable)], capture_output=True, text=True,
                         env=env, timeout=60)
    if res.returncode != 0:
        raise RuntimeError("C run failed: " + res.stderr)
    rows = np.array([[float(v) for v in line.split(",")]
                     for line in res.stdout.splitlines() if line.strip()])
    # Drop a possible final row that lands just past `stop` due to fp time
    # accumulation (Python engine records t <= stop).
    rows = rows[rows[:, 0] <= stop + 1e-9]
    return rows


def verify(name):
    path = ROOT / "examples" / f"{name}.json"
    doc = read_document(str(path), BLOCK_SPECS)
    stop = float(doc["stop_time"])
    dt = float(doc["dt"])
    # --- Python engine truth ----------------------------------------------
    results = simulate_document(doc, BLOCK_SPECS, backend="python")
    if not results:
        FAILURES.append((name, "no sink results"))
        print(f"FAIL {name}: no sink blocks")
        return
    truth_cols = [np.array(results[bid][0]) for bid in results]
    time = truth_cols[0]
    values = np.concatenate(
        [np.array(results[bid][1]) for bid in results], axis=1)
    truth = np.column_stack([time, values])
    if not np.all(np.isfinite(truth)):
        FAILURES.append((name, "non-finite python output"))
        print(f"FAIL {name}: non-finite python output")
        return
    # --- CSV for Octave ----------------------------------------------------
    model_csv = CSV_OUT / name
    model_csv.mkdir(parents=True, exist_ok=True)
    for bid, (t, v, labels) in results.items():
        v = np.atleast_2d(np.array(v))
        labels = labels or [f"ch{j}" for j in range(v.shape[1])]
        with open(model_csv / f"{int(bid):03d}_sink.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t"] + [str(l) for l in labels])
            for row, vals in zip(t, v):
                w.writerow([f"{row:.17g}"] + [f"{float(x):.17g}" for x in vals])
    # --- C99 codegen vs Python truth ---------------------------------------
    with tempfile.TemporaryDirectory(prefix=f"c-{name}-", dir=ROOT) as td:
        td = Path(td)
        actual = c_compile_and_run(doc, stop, dt, td)
    if name == "robotics_perception_conditioning":
        print("DEBUG truth[299:302]=", repr(truth[299:302]))
        print("DEBUG actual[299:302]=", repr(actual[299:302]))
    if actual.shape != truth.shape:
        FAILURES.append((name, f"shape mismatch C {actual.shape} vs "
                         f"python {truth.shape}"))
        print(f"FAIL {name}: shape mismatch C {actual.shape} vs python "
              f"{truth.shape}")
        return
    np.testing.assert_allclose(actual[:, 0], truth[:, 0], atol=1e-9, rtol=0)
    np.testing.assert_allclose(actual[:, 1:], truth[:, 1:], atol=1e-9,
                               rtol=1e-9)
    err = float(np.max(np.abs(actual[:, 1:] - truth[:, 1:])))
    print(f"PASS {name}: {actual.shape[0]} samples x {actual.shape[1]-1} "
          f"channels, max |C-Python| error = {err:.3g}, "
          f"final t = {actual[-1, 0]:.4f} s")


def main():
    names = sorted(p.stem for p in (ROOT / "examples").glob("robotics_*.json"))
    if not names:
        print("No robotics_*.json models found in examples/")
        return 1
    for n in names:
        try:
            verify(n)
        except Exception as exc:
            FAILURES.append((n, str(exc)))
            print(f"FAIL {n}: {exc}")
    print("-" * 60)
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{len(names)} models:")
        for n, e in FAILURES:
            print(f"  - {n}: {e}")
        return 1
    print(f"ALL {len(names)} robotics models PASS (Python sim == C99 codegen).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
