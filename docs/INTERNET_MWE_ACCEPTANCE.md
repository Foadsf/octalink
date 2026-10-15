# Three public Simulink MWEs: acceptance, 2026-10-15

> A second set of five public examples, with its own references, GUI automation evidence and defect list, is in [PUBLIC_MWES_2.md](PUBLIC_MWES_2.md).

The three editable models reproduce published equations in OctaLink. They
exercise coupled electrical/mechanical states, PI feedback with a nested
vehicle model, and explicit nonlinear dynamics. They do not import SLX files
or require MATLAB. [Sources and adaptation choices](INTERNET_MWE_SOURCES.md)
distinguish published parameters from local simulation and layout choices.

Open these files in OctaLink and click Run:

- `examples/mwe_dc_motor.json`: 1 V armature-controlled motor; speed and current.
- `examples/mwe_cruise_pi.json`: 10 m/s reference, continuous PI, Vehicle subsystem,
  and separate speed/effort scopes.
- `examples/mwe_van_der_pol.json`: explicit nonlinear force blocks; change Mu
  from 1 to 0 to obtain the analytically checkable harmonic oscillator.

Both simulation backends and both per-diagram connection styles were
exercised. Independent standalone `.m` and C99 exports are retained in
`artifacts/internet-mwes/exports/`.

## Measurements and verdicts

| Measurement | Verdict | Evidence |
| --- | --- | --- |
| `python run_tests.py` exited 0: 106 tests, six retained prototype stages, broken-integrator mutation rejected | PASS complete acceptance run | `artifacts/verification/internet-mwe-acceptance.log` |
| Motor: 601 samples, full speed/current trace maximum error 4.9761e-10 against independent analytical equations | PASS at dt=0.005 over 3 s | `artifacts/verification/internet-mwe-numerics-parent.log` |
| Cruise: 1001 samples, all reference/speed/force channels maximum error 9.4810e-8 N | PASS at dt=0.01 over 10 s | Same log; `internet-mwe-numerics.json` records each backend |
| Van der Pol: 1001 samples, both states maximum error 5.1142e-8 against independent adaptive Octave ode45 | PASS at dt=0.01 over 10 s | Same log |
| Python, native Octave, standalone exported `.m`, and strictly compiled C99 each compared against those references; C/Python differences zero in these traces | PASS numerical/export fidelity for the three models | Same log; eight tests exited 0 |
| Halving dt reduced motor error to 3.0457e-11, cruise force error to 5.9044e-9 N, nonlinear error to 4.3199e-9; Mu=0 harmonic error 1.5809e-9 | PASS independent refinement and analytic controls | Same log |
| Motor poles -9.997499 and -2.002501, DC gain 0.0999001; cruise realization poles -0.8 and -0.05, DC gain 1; explicit A/B/C/D verified | PASS selected-transfer analysis | Same log |
| Changed motor torque, positive cruise feedback, and Mu=0 substituted for Mu=1 produced errors 0.0994, 2.5337e7, and 2.2736, respectively; all rejected by the same comparisons | PASS dynamics falsification | Same log |
| Missing integrator input, nonexistent source port, swapped scope channels, malformed open, invalid gain, and overlapping bodies were rejected | PASS tested invalid-input controls | Numerical log and `artifacts/verification/internet-mwe-ui.log` |
| Seven GUI tests: real Run clicks for both backends, plotted arrays/labels, CSV values, export handlers, numerical undo/redo, child editing, subsystem creation/copy, style save/reopen, cancellation and rerun | PASS exercised native Qt workflows | UI log; full-run copy in `internet-mwe-acceptance.log` |
| Final compact layouts: body overlap, complete label extent, both styles, attachment after real drag and undo | PASS geometry at the tested layouts | `artifacts/verification/internet-mwe-final-layout.log` |
| All three models run through the visible Windows editor with real Octave; 11 editor/scope images captured and visually reviewed | PASS Windows native exercise | `artifacts/verification/internet-mwe-capture-live.log`; `artifacts/internet-mwes/capture-measurements.json` |
| All new MWE routes avoid unrelated block bodies in both styles; disabling curved collision checks produced three crossing failures on the final compact layouts | PASS tested route geometry and falsification | `artifacts/verification/routing-after.log`, `routing-curved-control-final.log` |
| Missing obstacle context and the original connected-wires-only movement callback each produced one real crossing assertion failure, zero harness errors, exit 1 | PASS original-mechanism controls | `artifacts/verification/routing-context-control.log`, `routing-movement-control.log` |

The cruise error above is an absolute error in the 8000 N initial control
effort, not a speed error of that magnitude. The analytical reference retains
both realization poles even though the selected reference-to-speed transfer
contains a pole/zero cancellation. These results do not infer the margins of
the actual internal loop from a selected-transfer plot.

## Diagnosed defects and canonical fixes

1. **New orthogonal paths ignored obstacles.** Path construction happens
   before the wire enters its scene. The router previously inspected only
   `wire.scene()`. It now obtains the diagram from the source block when
   necessary. Insertion also refreshes existing routes.
2. **Moving an unconnected block left other wires underneath it.** The
   position callback updated only that block's attached signals. It now
   updates every wire in the diagram because every block is an obstacle.
3. **Bowed feedback curves could intersect unrelated blocks.** Endpoint
   bounding-box heuristics missed the actual cubic trajectory. The router now
   checks the open-path stroke and, when needed, rounds an obstacle-aware
   orthogonal guide. Clear original Bezier connections are retained.
4. **Property Apply committed invalid numerical text.** Document validation
   checked structure, while semantic parsing happened only on Run. The
   inspector and compiler now share `SimulationEngine.prepare_blocks`.
   Validation runs on the detached candidate before changing the live block
   or undo history. Unwired drafts can still accept valid parameters.
   Regression cases cover gain expressions, sample time, saturation bounds,
   improper transfer functions, state-space dimensions and unsafe expressions.
5. **Long names were clipped, especially under Mux blocks.** The fixed
   body-width label rectangle was too narrow. `BlockItem.name_label_rect`
   measures the actual font; painting and scene bounds share that extent.
   Renaming invalidates geometry before changing the name.
6. **Short forward connections took unnecessary feedback detours.** Fixed
   22-unit endpoint stubs overlapped across narrow gaps. Forward stubs now
   scale to the available gap. The routing regression checks an unobstructed
   20-unit connection has length 20; a detour control exceeds that by over 100.

The permanent checks are in `tests/test_routing_regressions.py`,
`tests/test_editor_mvp.py`, `tests/test_internet_editor.py`, and
`tests/test_internet_mwes.py`. No proprietary solver or SLX loader was added.

## Reproduce

From the repository root, Windows/PowerShell, with the Python dependencies,
GNU Octave and GCC already installed:

```powershell
$env:TEMP = Join-Path $PWD '.tmp'
$env:TMP = $env:TEMP
python run_tests.py
python tests/capture_internet_mwes.py --live
python tests/verify_distribution.py

# Each routing fault injection must exit 1 with crossing failures, zero errors.
$env:PYTHONPATH = $PWD
python tests/test_routing_regressions.py --mutation-control
python tests/test_routing_regressions.py --movement-control
python tests/test_routing_regressions.py --curved-control
```

`artifacts/verification/internet-mwe-acceptance.log` records the complete
acceptance command and exit is checked by the invoking shell. Distribution
identity and altered-byte rejection are recorded in
`artifacts/verification/mwe-distribution.log`; the rebuilt Octave archive and
wheel include all eight modules and seven example models. Hashes are in
`artifacts/SHA256.json`.

Accepted output:

```text
MVP ACCEPTANCE OK: 106 tests passed; 6 legacy stages completed; integrator mutation rejected (exit 1).
```

The final short-gap refinement was followed by the three focused routing
regressions (exit 0), a new visible three-model Octave capture (exit 0), and
rebuilt-distribution identity checking. No numerical behavior changed in that
last routing-only refinement.

## Limits and unverified behavior

These finite examples establish the stated numerical and interaction checks;
they cannot establish universal perfection. Simulink itself was not run, and
no UI screenshot comparison or binary SLX compatibility is claimed. The
references use published equations, analytical solutions and an independent
adaptive solver. Wire crossings between different signals can remain;
avoidance is checked for block bodies in these layouts, not arbitrary dense
diagrams or every possible label/line collision.

macOS/Linux GUI execution, stiff/DAE systems, Stateflow/Simscape networks,
physical parameter identification and hardware deployment remain unverified
or outside this MVP. The cruise controller is unsaturated and continuous;
there is no claim of actuator limits, anti-windup or physical vehicle safety.
The original release's qualification and remaining capability boundaries are
retained in [ACCEPTANCE.md](ACCEPTANCE.md).
