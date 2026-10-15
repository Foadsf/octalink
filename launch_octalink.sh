#!/bin/sh
# POSIX shell (Linux/macOS). Prefer the project virtual environment.
set -eu
task_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_python=${OCTALINK_PYTHON:-python3}
if [ -x "$task_dir/.venv/bin/python" ]; then
    task_python="$task_dir/.venv/bin/python"
fi
exec "$task_python" "$task_dir/octalink_gui.py" "$@"
