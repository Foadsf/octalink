# OctaLink MVP 0.1

A native, Simulink-inspired visual block editor built on the Antigravity/Gemini prototype. Create diagrams, connect blocks, configure parameters, simulate continuous/discrete systems in Python or GNU Octave, inspect multi-channel scopes, analyze selected transfers and export standalone C99/Octave models.

The editor uses a light toolstrip, docked searchable Library Browser, Property Inspector, white block canvas, orthogonal signal lines, subsystem breadcrumbs, and familiar keyboard shortcuts. This is the first MVP, with a deliberately bounded solver and capability envelope.

## Run

Python 3.10+ with PyQt6, NumPy and Matplotlib is required. GNU Octave is optional for the standalone editor.

```text
python -m pip install -r requirements.txt
python octalink_gui.py
```

On Windows, double-click `launch_octalink.bat`, or run `./launch_octalink.ps1` in PowerShell. On Linux/macOS, run `sh launch_octalink.sh`. Launchers prefer the project `.venv`; `OCTALINK_PYTHON` can name another Python executable.

Install the Python distribution with `python -m pip install .`, then run `octalink-gui`. The packaged wheel is in `artifacts/`.

The default model is a closed-loop first-order response. Click **Run** to open its Scope. The expected output is zero before one second, then `1 - exp(-2*(t-1))`.

## Nine public Simulink MWEs

Use **Open** (or File › Examples) to load one of these editable models, then **Run**. Each works with the Local Python engine or GNU Octave and either connection style.

| Model file | What it exercises |
| --- | --- |
| `examples/mwe_dc_motor.json` | CTMS armature-controlled DC motor: coupled electrical/mechanical integrators, back EMF, torque, two-channel scope. |
| `examples/mwe_cruise_pi.json` | CTMS cruise controller: continuous PI, editable Vehicle subsystem, reference/speed and control-effort scopes. |
| `examples/mwe_van_der_pol.json` | MathWorks nonlinear oscillator: explicit Product/Sum/Gain blocks; edit Mu to zero for a harmonic oscillator. |
| `examples/mwe_motor_speed_lag_lead.json` | CTMS motor speed: biproper lag and lead Transfer Fcn compensators around two copies of a motor subsystem; motor constants in the Model Workspace. |
| `examples/mwe_inverted_pendulum.json` | CTMS nonlinear cart-pendulum: Pulse Generator impulse, vector Octave Functions using workspace variables, linearization matching CTMS poles. |
| `examples/mwe_house_heating.json` | MathWorks thermal model of a house: Relay thermostat, heater/house/F–C subsystems, two-day heating cost (about $30). |
| `examples/mwe_aircraft_pitch_lqr.json` | CTMS aircraft pitch: full-state State-Space output, Matrix(K*u) LQR gain, precompensator, step disturbance. |
| `examples/mwe_motor_position_digital.json` | CTMS digital motor position: Discrete Zero-Pole controller between Zero-Order Holds, stiff plant on the implicit SDIRK4 solver at 0.1 ms, disturbance rejection; shows inter-sample ripple. |
| `examples/mwe_inverted_pendulum_loop.json` | The CTMS pendulum as CTMS builds it: four Fcn blocks whose interaction forces N and P form an algebraic loop, solved by Newton. |

See [source equations and adaptation choices](docs/INTERNET_MWE_SOURCES.md), [measured acceptance and bug fixes](docs/INTERNET_MWE_ACCEPTANCE.md) and, for the last six, [their sources, references and the defects they exposed](docs/PUBLIC_MWES_2.md). Exports and captures are in `artifacts/internet-mwes/` and `artifacts/public-mwes-2/`.

## Edit

- Drag a block from Library Browser, or double-click blank canvas for quick insert.
- Drag an output port to an input port. An input accepts one driver; outputs can branch.
- Double-click a block to edit its parameters, or select it and use Property Inspector / Apply.
- Select blocks and use Ctrl+G to create a subsystem. Double-click it to enter; Up returns to the parent.
- **Model Browser** lists every block by path (`House › Troom`); selecting a row selects the block, entering its subsystem if needed. Type in its filter box to narrow the list.
- **Modeling › Model Workspace** (Ctrl+Shift+W) holds named variables, evaluated in order, e.g. `J = 0.01` and a Gain of `1/J`; arrays use brackets (`K = [-0.64 169.7 7.07]`). Variables are saved with the model and resolved into exported `.m` and C code.
- Sum and Product take any input count: `+-+`, Simulink's spacer form `|+-`, or a count such as `3`.
- **Simulation** menu: Run, Stop, Check Model, and the Engine and Solver choices (also reachable from assistive technology).
- Ctrl+N/O/S: New/Open/Save. Ctrl+Shift+S: Save As. Ctrl+Z/Y: Undo/Redo.
- Ctrl+C/V: Copy/Paste. Ctrl+I: Flip. Delete: Remove. Ctrl+0: Fit. Ctrl+D: Check Model. Ctrl+R: Run.
- Wheel: zoom. Middle-drag or Space+drag: pan.
- **Format > Curved Connections** (also in View) toggles curved/orthogonal lines for the current diagram. Each subsystem has its own setting, saved with the model and included in Undo/Redo.
- Run executes in a background worker. Stop cancels without publishing partial results. Complete scopes open independently.
- Export CSV writes the selected logged Scope/To CSV block, or the first available sink. GUI simulations do not automatically write a To CSV block's filename.
- In Simulation / Solver Settings, choose **Local Python** or **GNU Octave**, and the fixed-step solver: **RK4 (explicit)** or **SDIRK4 (implicit, stiff)**. Both choices are saved in the model (`"backend"`, `"solver"`). Octave Settings can select a local executable; otherwise discovery uses installed locations or `OCTALINK_OCTAVE`. Octave jobs run in owned local processes with cancellation and timeout; a failure is reported without silently changing engines.

Saving validates the document and replaces the file atomically. Opening validates the complete document before replacing the active diagram. New/Open/Close prompt for unsaved changes.

## GNU Octave package

Build with `python pack_package.py`, then in GNU Octave:

```octave
pkg install octalink-0.1.0.tar.gz
pkg load octalink
setenv ("OCTALINK_PYTHON", "/path/to/python-with-dependencies");
octalink
```

On Windows, use the full Windows Python path in `OCTALINK_PYTHON`. The package requires no native C++ compilation or control package. Its portable `.m` launcher starts the Qt editor with **GNU Octave** selected as the simulation backend. Derivatives, state updates and discrete events execute in a separate real Octave process. It does not attach to an existing interactive workspace.

A synchronous package check is also available:

```octave
[status, output] = octalink ("", "", "check");
disp (output);
assert (status == 0);
```

Windows paths containing quotes, percent signs, exclamation marks or newlines are rejected rather than passed through shell expansion. The existing `octalink-1.0.0/` directory remains the package-source location; the MVP package version and archive are **0.1.0**.

## Simulation scope

Both engines offer two fixed-step solvers: explicit RK4, and implicit SDIRK4 (Hairer–Wanner, order 4, L-stable, with Newton iterations on a numerical Jacobian) for stiff plants. Both split integration at Step and Pulse Generator transitions and discrete sample events, resolve state-breaking feedback, and reject unconnected inputs. Direct-feedthrough cycles are algebraic loops: each loop is cut at scalar signals and solved by Newton at every evaluation, warm-started from the previous solution, as Simulink does. A loop with no unique solution (a singular Jacobian) or no scalar signal to cut is reported as an error. Supported blocks include Step, Sine Wave, Constant and Pulse Generator sources; Sum/Product (any input count), Gain (element-wise or Matrix(K*u)), Trig and Octave Function; Integrator, proper Transfer Fcn, State-Space (single input, vector output), filtered PID; Saturation, Relay, Switch; Unit Delay, Zero-Order Hold, Discrete Transfer Fcn and Discrete Zero-Pole; Mux/Demux; subsystems and logging sinks. Model versions 3.0–4.0 remain readable; saving writes 4.1.

Parameter expressions support bounded real arithmetic, `pi`, `e`, named mathematical functions and Model Workspace variables. Octave Function is a local mathematical expression using `u`, `t`, zero-based `u_vec[index]` and workspace variables; arbitrary Octave programs are outside this release.

Limits: 5000 document blocks, 24 subsystem levels, 64 ports per block, 250000 simulation intervals, 256 workspace variables. Integrators, transfer blocks and most math blocks are scalar; vectors flow through Mux/Demux, Gain, State-Space outputs, Octave Function inputs and sinks. Fixed-step nonlinear switching is an approximation. There is no variable-step solver, and DAEs beyond algebraic loops are not supported. Fixed steps cannot resolve near-discontinuous fast transients, such as the jump of a strongly stiff Van der Pol oscillator. C export supports RK4 only and refuses SDIRK4 models and algebraic loops; the `.m` export supports both. GNU Octave runs are limited to 600 s by default (`OCTALINK_OCTAVE_TIMEOUT`).

**Analysis** lets you select a source, logged output channel and operating input. Bode, Nyquist, poles/zeros and step metrics describe that local transfer. Missing crossings display N/A. Reported feedback margins treat the selected transfer as a hypothetical unity-negative-feedback loop; they do not automatically describe an internal controller loop. Discrete delay/ZOH analysis uses labelled first-order Pade approximations, not exact discrete stability results.

**Export** now generates corrected standalone C99 and `.m` models. Both were executed and compared with the Python engine across all four examples; the hybrid C output agrees within 3.55e-14. The `.m` script needs no Python and returns `octalink_results`, writes per-sink CSVs and plots unless `OCTALINK_NO_PLOT=1`. The C header provides `OctaLink_Init`, `OctaLink_Step` and `OctaLink_NextTime`; inspect `status/error_block` before using `y_out`. Output channel offsets are defined in the header. Generated C was also compiled/executed under Linux GCC with a failing disabled-integrator control. MCU timing/memory and application suitability remain outside these numerical checks.

The existing `examples/hybrid_model.c/.h/.m` were regenerated with these corrected exporters. The Van der Pol model adapts the installed GNU Octave `ode45.m` example; its independent adaptive reference and source snapshot are in `tests/references/`.

## Verify

```text
python run_tests.py
python octalink_gui.py --check examples/first_order_feedback.json
python octalink_gui.py --check examples/hybrid_control_loop.json --backend octave
python tests/capture_mvp.py
python tests/verify_gui_surface.py --octave
```

`tests/test_public_mwes_2.py` (part of `run_tests.py`) checks the five newer examples against independent references: closed-form solutions, SciPy DOP853 on a Lagrangian, an exact sampled-data loop and an energy balance. It also checks native Octave, standalone `.m` and strict C99 parity, CTMS linearization values and negative controls. SciPy is needed for that suite only. `tests/verify_gui_surface.py` drives the real editor through Windows UI Automation using the separate `surfacekit` UI Automation toolkit, which is not part of this repository; point `SURFACEKIT_HOME` at it. Each model opens on a private hidden desktop, without keystrokes or focus changes, and the script checks Run on both engines, Model Browser selection, parameter edits, the Model Workspace, Save and the unsaved-changes prompt.

`run_tests.py` runs 114 numerical/editor/native-export/analysis tests, the six retained prototype stages, and a broken-integrator mutation which must fail. The new internet-MWE suites require native Octave and GCC and fail if either is absent. Evidence, screenshots and measured limitations are in `docs/INTERNET_MWE_ACCEPTANCE.md`, the original `docs/ACCEPTANCE.md`, and `artifacts/verification/`. `python tests/verify_mvp_delivery.py` compares all seven models across both engines and checks Van der Pol against independent adaptive ode45 with step refinement and a reversed-velocity negative control. `python tests/capture_internet_mwes.py --live` runs all three internet models through the native editor and captures both wire styles and the actual scopes.

GNU Octave verification: set `OCTALINK_PYTHON`, then run `octave-cli --quiet tests/verify_octave_bridge.m`. It installs into `.tmp`, checks a real package-to-Python call, rejects a bad model, and solves an analytical ode45 reference. Windows CLI sessions should put Octave's bundled `usr/bin` archive tools before Windows tar on PATH, as its GUI launcher does.

Windows/Qt and GNU Octave 11.3.0 were exercised on this host. Exported C was exercised in Linux/WSL; the Linux editor/Octave backend and macOS execution remain unverified. Designed as a cross-platform implementation; full Simulink compatibility, SLX import/export, Stateflow, Simscape and hardware deployment are outside MVP scope.

Original prototype documentation is preserved in `docs/PROTOTYPE.md`. Source history and the originating Antigravity conversation are recorded in `docs/HISTORY.md`. License: GPL-3.0-or-later; see `COPYING`.
