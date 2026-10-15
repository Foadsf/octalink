#!/usr/bin/env python3
"""
Canonical Test Suite for OctaLink.
Runs the 6-stage self-test suite in headless offscreen mode:
1. Undo/Redo & Block Flipping (Ctrl+I) + Vector SVG Icons
2. Linear Analysis Advisor (linmod, Padé Delays, Poles, Bode/Nyquist, Stability Margins, Step Metrics)
3. Embedded ANSI C99 Code Generation & GCC Native Execution
4. Nonlinear Math, State-Space, Safe Regex Octave Function & Demux Blocks
5. Switch, Relay & To CSV Sink Blocks
6. Octave .m Script Exporter with Plotting & Legend Commands
"""

import os
import sys
from pathlib import Path
import subprocess
import tempfile
import re

def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, current_dir)
    scratch = Path(current_dir) / ".tmp"
    scratch.mkdir(exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(scratch)
    tempfile.tempdir = str(scratch)

    # Auto-detect MSYS2 / MinGW GCC on Windows if not on system PATH
    if sys.platform == "win32":
        for gcc_candidate in [r"C:\msys64\ucrt64\bin", r"C:\msys64\mingw64\bin", r"C:\mingw64\bin"]:
            if os.path.exists(os.path.join(gcc_candidate, "gcc.exe")):
                os.environ["PATH"] = os.environ["PATH"] + os.pathsep + gcc_candidate
                break

    os.environ["PYTHONIOENCODING"] = "utf-8"
    print("=" * 70)
    print("OctaLink Canonical Self-Test Runner (6 Stages)")
    print("=" * 70)
    # Each Qt suite owns exactly one application/process. Do not destroy the
    # legacy QApplication and then create another for unittest in the same VM.
    legacy = subprocess.run([sys.executable, str(Path(current_dir)/"octalink_gui.py"), "--self-test"],
                            cwd=current_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(legacy.stdout + legacy.stderr, end="")
    if legacy.returncode != 0:
        print(f"MVP ACCEPTANCE FAILED: legacy process exit {legacy.returncode}.")
        return 1
    print("=" * 70)
    print("Legacy prototype stages completed. Export execution is not numerical parity proof.")
    print("=" * 70)
    total_tests = 0
    for test_file in sorted((Path(current_dir)/"tests").glob("test_*.py")):
        # GUI/process-mocking suites do not share Qt/application or process
        # state with numerical and native compiler suites.
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", test_file.name, "-v"],
                                cwd=current_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(result.stdout + result.stderr, end="")
        count = re.search(r"Ran (\d+) tests", result.stdout + result.stderr)
        if result.returncode != 0 or count is None or int(count.group(1)) == 0:
            print(f"MVP ACCEPTANCE FAILED: {test_file.name} process exit {result.returncode}.")
            return 1
        total_tests += int(count.group(1))
    negative = subprocess.run([sys.executable, str(Path(current_dir)/"tests"/"test_engine_mvp.py"), "--mutation-control"],
                              cwd=current_dir, capture_output=True, text=True, encoding="utf-8", errors="replace")
    evidence = Path(current_dir)/"artifacts"/"verification"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence/"engine-mutation-control.log").write_text(negative.stdout+negative.stderr, encoding="utf-8")
    if negative.returncode != 1 or "3 analytical failures, 0 errors" not in negative.stdout+negative.stderr:
        print("MVP ACCEPTANCE FAILED: broken-integrator control did not fail as expected.")
        return 1
    print(f"MVP ACCEPTANCE OK: {total_tests} tests passed; 6 legacy stages completed; integrator mutation rejected (exit 1).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
