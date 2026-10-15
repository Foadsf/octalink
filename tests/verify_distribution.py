"""Check release identity against the exact source that passed acceptance."""
from pathlib import Path
import hashlib
import json
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("octalink_gui.py", "mvp_editor.py", "mvp_model.py", "octalink_engine_support.py",
           "simulation_service.py", "octave_backend.py", "c_export.py", "linear_analysis.py")
archive = ROOT/"octalink-0.1.0.tar.gz"
wheel = ROOT/"artifacts"/"octalink-0.1.0-py3-none-any.whl"

def identical(actual, name):
    expected = (ROOT/name).read_bytes()
    if actual != expected:
        raise AssertionError(f"Distribution differs from verified source: {name}")

with tarfile.open(archive, "r:gz") as tar, zipfile.ZipFile(wheel) as packaged:
    assert not any("/src/" in entry for entry in tar.getnames())
    for name in MODULES:
        identical(tar.extractfile("octalink-0.1.0/inst/"+name).read(), name)
        identical(packaged.read(name), name)
    for model in (ROOT/"examples").glob("*.json"):
        relative = "examples/"+model.name
        identical(tar.extractfile("octalink-0.1.0/inst/"+relative).read(), relative)
        identical(packaged.read("octalink-0.1.0.data/data/share/octalink/"+relative), relative)
    # Same identity instrument must reject altered bytes.
    try:
        identical(b"changed implementation", "octalink_gui.py")
    except AssertionError:
        print("NEGATIVE CONTROL: altered module rejected by distribution identity check.")
    else:
        raise AssertionError("Distribution control failed to reject changed bytes")

hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (archive, wheel)}
for name in MODULES:
    hashes[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
(ROOT/"artifacts"/"SHA256.json").write_text(json.dumps(hashes, indent=2)+"\n", encoding="utf-8")
print(f"DISTRIBUTION IDENTITY OK: {len(MODULES)} modules + {len(list((ROOT/'examples').glob('*.json')))} example models match in Octave package and wheel.")
