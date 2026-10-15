# OctaLink first MVP - final acceptance, 2026-10-14

The subsequent three-public-example qualification, expanded 106-test run,
UI fixes and rebuilt distributions are recorded in
[INTERNET_MWE_ACCEPTANCE.md](INTERNET_MWE_ACCEPTANCE.md). The measurements
below preserve the original first-MVP baseline.

## Delivered behavior

Native Qt block editor, searchable categorized library, drag insertion/connection, quick insert, parameter inspector, subsystem navigation and copy/paste, reliable model persistence, undo/redo, and independently saved curved/orthogonal styles. Original 3.0/3.1 model files remain readable.

Run/Stop supports the local Python engine or **actual GNU Octave**, selected and saved in the model. Octave jobs own their process, report progress, reject failures and terminate on cancellation/timeout. The Octave package selects this backend automatically. The editor does not silently fall back to Python.

Linear analysis selects an input source, output channel and operating input, then plots Bode/Nyquist/poles/zeros with exact continuous local-Jacobian semantics. Missing crossings are N/A. Discrete delay/ZOH results use explicitly approximate first-order Pade models. Margin interpretation is shown in the UI.

Corrected C99 and standalone Octave exporters replace the prototype generators at the public engine API and in the GUI. Regenerated `examples/hybrid_model.c/.h/.m` and representative exports are included. Exported `.m` executes and renders a plot without Python. C has bounded steps and sticky status/error_block; output offsets are defined in its header.

## Measurement and verdict

| Measurement | Verdict | Raw evidence |
| --- | --- | --- |
| `python run_tests.py` exited 0: 87 tests, six retained prototype stages, failing disabled-integrator control | PASS within test scope | `artifacts/verification/acceptance.log` |
| Python/Octave four-model maximum discrepancy 2.71e-14 | PASS numerical equivalence at tested parameters | `artifacts/verification/cross-engine.log`, `cross-engine-results.json` |
| Compiled C hybrid: 1001 rows, maximum discrepancy 3.55e-14; final plant 0.8443338938132925 | PASS corrected exporter | `artifacts/verification/c-export-tests.log` |
| Independent adaptive ode45 Van der Pol reference error 5.11e-8; dt .01 -> .005 gives 4.32e-9 | PASS independent reference and refinement | `artifacts/verification/cross-engine.log` |
| Reversed-velocity reference error 5.36, rejected; disabled integration in Python, Octave and C each causes analytical assertion failures/exit 1 | PASS falsification controls | `cross-engine.log`, `engine-mutation-control.log`, `octave-backend-mutation.log`, `c-export-mutation.log` |
| Deliberately corrupted linearization fails the independent A=-2 check and exits 1 | PASS analysis control | `artifacts/verification/linear-analysis-mutation.log` |
| Real Windows native editor + Scope, GNU Octave selected: 301 samples, output 0.9816843610, curved connections retained | PASS actual GUI/backend exercise | `artifacts/verification/ui-octave-live.log`; `artifacts/editor-curved-octave.png` |
| Native analysis selection and four rendered panels; N/A and hypothetical-margin interpretation visible | PASS native analysis workflow | `artifacts/verification/analysis-ui-live.log`; `artifacts/linear-analysis.png` |
| Original examples load; a new constant/integrator/scope model was connected with mouse gestures and run; backend/style preferences survive persistence | PASS editing workflow | editor tests in `artifacts/verification/acceptance.log` |
| Canonical public C export API compiled and ran: 0.9816843610, exit 0 | PASS API exercise | `artifacts/verification/canonical-api.log` |
| Linux GCC compiled and ran the same model; disabled integration produced 0 and was rejected | PASS Linux C slice | `artifacts/verification/linux-c-export.log` |
| Project-local Octave package installs, loads and launches native backend; bad model child exits 1 | PASS package bridge | `artifacts/verification/octave-bridge.log` |
| Standalone `.m` calculates correct output, creates plots and renders actual PNG without Python | PASS exported runtime | `artifacts/verification/octave-export-plot.log`; `artifacts/octave-export-plot.png` |
| Eight modules and four model files byte-match their release artifacts; altered bytes rejected | PASS release identity | `artifacts/verification/distribution.log`; `artifacts/SHA256.json` |

Final accepted command output:

```text
MVP ACCEPTANCE OK: 87 tests passed; 6 legacy stages completed; integrator mutation rejected (exit 1).
```

The six retained prototype stages deliberately exercise preserved `_prototype_*` implementations. Their old `C99_FINAL_PLANT=-0.8957` is historical baseline output, **not** the new public exporter. The corrected generated C is verified separately against full Python traces and analytical controls.

## Traceability

The originating Gemini design conversation and Antigravity prototype are summarized in `docs/HISTORY.md`; their exports are kept privately.

The nonlinear reference adapts the installed GNU Octave 11.3.0 `ode45.m` Van der Pol example, lines 81-86 (`$OCTAVE_HOME/share/octave/11.3.0/m/ode/ode45.m`). A GPL source snapshot and independent ode45 adapter are in `tests/references/`. The model uses mu=1 and initial state [2,0], matching that case; it is a representative numerical example, not an asserted model of the user's equipment.

The UI follows the official [Simulink Editor](https://www.mathworks.com/help/simulink/slref/simulinkeditor.html) and [Library Browser](https://www.mathworks.com/help/simulink/slref/librarybrowser.html) interaction/layout references. Original prototype documentation/archive remain available.

## Environment and practical limits

Windows 11 host; Python 3.13.11; PyQt 6.10.2/Qt 6.10.0; GNU Octave 11.3.0. C99 was built with strict GNU GCC warnings on Windows/UCRT and with Linux/WSL GCC. The local Linux Python runtime lacks the editor dependencies and Octave, so Linux GUI/backend execution is not claimed. macOS is not tested.

Windows Qt teardown once crashed after all tests printed OK. The runner now isolates each suite in a child process and requires its exit code; the editor stops its timer/closes scopes on close, and tests flush deferred deletion. The exact original teardown cause was not established; no unsupported global-stability claim is made.

The host Octave CLI exposes FLTK/gnuplot rather than Qt graphics. FLTK image printing stalled; the exported traces were successfully rendered with gnuplot. Native editor Scopes and the analysis dashboard use Matplotlib/Qt and were exercised directly.

Known limits: fixed-step Relay/Switch crossings; scalar/SISO states with explicit Mux/Demux vector routing; no stiff/DAE solver, Stateflow/Simscape, SLX interchange or existing interactive Octave-workspace attachment. Exact discrete/hybrid stability and actual internal control-loop margins are not inferred from Pade/selected-transfer plots. MCU memory/timing, physical controller suitability and deployment remain unverified. This is the completed first-MVP scope, not full proprietary Simulink parity.
