#!/usr/bin/env python3
"""Synchronize MVP modules/examples and build the pure-launcher Octave 0.1 package.

The existing octalink-1.0.0 source directory is retained. Prototype native bridge
sources are preserved there but excluded from the MVP archive.
"""

import os
import shutil
import tarfile


def pack_octalink_package():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    source_dir = os.path.join(current_dir, "octalink-1.0.0")
    output_tar = os.path.join(current_dir, "octalink-0.1.0.tar.gz")

    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    inst = os.path.join(source_dir, "inst")
    for name in ("octalink_gui.py", "mvp_editor.py", "mvp_model.py", "octalink_engine_support.py",
                 "simulation_service.py", "octave_backend.py", "c_export.py", "linear_analysis.py"):
        shutil.copy2(os.path.join(current_dir, name), os.path.join(inst, name))
        print(f"Synchronized {name}")
    examples = os.path.join(inst, "examples")
    os.makedirs(examples, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(current_dir, "examples"))):
        if name.endswith(".json"):
            shutil.copy2(os.path.join(current_dir, "examples", name), os.path.join(examples, name))

    print(f"Packaging {source_dir} -> {output_tar}...")
    with tarfile.open(output_tar, "w:gz") as tar:
        tar.add(source_dir, arcname="octalink-0.1.0",
                filter=lambda item: None if item.name.startswith("octalink-0.1.0/src") or "__pycache__" in item.name or item.name.endswith((".pyc", ".oct", ".o")) else item)

    file_size_kb = os.path.getsize(output_tar) / 1024.0
    print(f"Successfully generated {output_tar} ({file_size_kb:.1f} KB)")
    print("\nTo install in GNU Octave, run:")
    print('  octave --eval "pkg install octalink-0.1.0.tar.gz; pkg load octalink; octalink"')


if __name__ == "__main__":
    pack_octalink_package()
