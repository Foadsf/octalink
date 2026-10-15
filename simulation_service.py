"""One simulation entry point for the editor, CLI and release checks."""
from mvp_model import validate_document, detached_graph


def simulate_document(document, specs, backend=None, executable=None,
                      cancel_check=None, progress_callback=None):
    data = validate_document(document, specs)
    selected = backend or data.get("backend", "python")
    if selected not in ("python", "octave"):
        raise ValueError("Simulation backend must be python or octave.")
    if selected == "octave":
        from octave_backend import run_octave_simulation
        return run_octave_simulation(data, specs, executable=executable,
                                     cancel_check=cancel_check, progress_callback=progress_callback)
    from octalink_gui import SimulationEngine
    scene = detached_graph(data, specs)
    results = SimulationEngine().run_simulation(
        scene, float(data.get("stop_time", 10)), float(data.get("dt", .01)),
        cancel_check=cancel_check, progress_callback=progress_callback, write_csv=False,
        solver=data.get("solver", "rk4"))
    return {block.block_id: (record["time"], record["values"], record["labels"])
            for block, record in results.items()}
