# Six more public Simulink examples, 2026-10-15

This second set extends `docs/INTERNET_MWE_SOURCES.md`. The models are independently authored OctaLink diagrams. They do not import `.slx` files. Each one keeps the published parameters and equations, and every adaptation is listed below. Sources were read on 2026-10-15 in a browser (CTMS) or directly (MathWorks). No MathWorks model file or figure is redistributed.

| Model | Public source | What it exercises |
| --- | --- | --- |
| `examples/mwe_motor_speed_lag_lead.json` | [CTMS, DC Motor Speed: Simulink Controller Design](https://ctms.engin.umich.edu/CTMS/?example=MotorSpeed&section=SimulinkControl) | Lag `(44s+44)/(s+0.01)` and lead `(160000s+5.6e6)/(s+1035)` compensators, both biproper Transfer Fcn blocks with direct feedthrough. Two first-principles motor subsystems are copied from one source. Mux scopes show speed and control effort. Motor constants J, b, K, R and L live in the Model Workspace. |
| `examples/mwe_inverted_pendulum.json` | [CTMS, Inverted Pendulum: Simulink Modeling](https://ctms.engin.umich.edu/CTMS/?example=InvertedPendulum&section=SimulinkModeling) | The nonlinear cart-pendulum: M=0.5, m=0.2, b=0.1, l=0.3, I=0.006, θ(0)=π. A Pulse Generator (1000 N, period 10 s, width 0.01 %) approximates the 1 N·s impulse. Vector Octave Function blocks fed by a Mux use workspace variables. |
| `examples/mwe_house_heating.json` | [MathWorks, Thermal Model of a House](https://www.mathworks.com/help/simulink/slref/thermal-model-of-a-house.html) | Relay thermostat (±5 °F around 70 °F), heater, house and F/C converter subsystems, a Sine Wave outdoor temperature and the heat-cost integrator, over 48 h (172 800 s). |
| `examples/mwe_aircraft_pitch_lqr.json` | [CTMS, Aircraft Pitch: Simulink Controller Design](https://ctms.engin.umich.edu/CTMS/?example=AircraftPitch&section=SimulinkControl) and [State-Space design](https://ctms.engin.umich.edu/CTMS/?example=AircraftPitch&section=ControlStateSpace) | A State-Space block with full-state output (C = I), `K = [-0.6435 169.6950 7.0711]` as a Matrix(K*u) Gain, the precompensator Nbar = 7.0711, a 0.2 rad reference and a 0.2 rad disturbance at 3 s. |
| `examples/mwe_motor_position_digital.json` | [CTMS, DC Motor Position: Simulink Controller Design](https://ctms.engin.umich.edu/CTMS/?example=MotorPosition&section=SimulinkControl) | A Discrete Zero-Pole controller (zeros [0.95 0.80 0.80], poles [-0.98 0.6 1], gain 800, Ts = 1 ms) between two Zero-Order Holds. The stiff motor plant (L = 2.75e-6, pole at -1.45e6 rad/s) is integrated by the implicit SDIRK4 solver at 0.1 ms, ten steps per sample. A unit step disturbance enters at 0.03 s. |
| `examples/mwe_inverted_pendulum_loop.json` | [CTMS, Inverted Pendulum: Simulink Modeling](https://ctms.engin.umich.edu/CTMS/?example=InvertedPendulum&section=SimulinkModeling), equations (1), (2), (13), (14) | The pendulum as CTMS builds it: four Fcn blocks, each fed by a Mux, compute ẍ = (F − N − bẋ)/M, θ̈ = (−Nl cos θ − Pl sin θ)/I, N = m(ẍ − lθ̇² sin θ + lθ̈ cos θ) and P = m(lθ̇² cos θ + lθ̈ sin θ + g). ẍ and θ̈ feed N and P, which feed them back: an algebraic loop that OctaLink solves by Newton, as Simulink does. |

## Adaptations and local choices

- **Pendulum algebraic loop.** CTMS builds four Fcn blocks whose interaction forces form an algebraic loop, which Simulink solves iteratively. `mwe_inverted_pendulum_loop.json` keeps that structure, and OctaLink solves the loop by Newton. `mwe_inverted_pendulum.json` solves the same Newton–Euler equations explicitly for ẍ and θ̈. The acceptance test re-derives them from the Lagrangian and integrates that form independently with SciPy DOP853. The Mux input order for the N and P blocks is a local choice; the page specifies it only for ẍ and θ̈.
- **Motor-position solver.** The page simulates with ode15s. OctaLink has no variable-step solver, so the model uses the fixed-step implicit SDIRK4 solver at 0.1 ms. Explicit RK4 needs 1 µs and is still available (the strict C99 export runs that way).
- **House outdoor temperature.** The MathWorks page does not publish the average outdoor temperature or the daily amplitude. The model uses 50 °F ± 15 °F with a 24 h period. The geometry and thermal resistance come from MathWorks' published `thermdat.m` data script. The heater (50 °C, 1 kg/s), set point, band, initial temperature and $0.09/kWh come from the page itself. With these choices the two-day cost is **$30.35**, against the page's "about $30".
- **Time horizons.** CTMS gives no horizon for the lag/lead comparison (3 s is used, from its open-loop section) or for the aircraft pitch response (10 s is used).
- **Inter-sample ripple (motor position).** The controller pole at z = -0.98 cancels the sampled plant zero at z = -0.983. Seen at the sample instants, the loop matches the CTMS design exactly: samples 0, 0.8311, 0.9679, 1.0187, … and a peak of 1.0996, which is CTMS's "approximately 10 %" overshoot. The controller output still rings at the Nyquist rate, and the continuous shaft position, logged every 0.1 ms, departs from the sampled position by up to 0.67 rad between samples. Logging at the sample hits, as the CTMS figure effectively does, hides it. The scope therefore shows the continuous position and the sensor-ZOH sampled position side by side.

## Measured acceptance

Run `python -m unittest discover -s tests -p test_public_mwes_2.py -v`. Numbers are recorded in `artifacts/verification/public-mwe2-numerics.json`.

| Check | Result |
| --- | --- |
| Lag/lead vs closed-form 3-state solution (matrix exponential) | 1.3e-6 of channel peak; dt/2 gives 7.7e-8 (16.7×, RK4 truncation) |
| Pendulum vs SciPy DOP853 on the Lagrangian mass-matrix form | 2.8e-7 of peak after ten revolutions; dt/2 gives 1.8e-8 |
| Aircraft pitch vs piecewise matrix exponential | 3.0e-9; dt/2 gives 1.9e-10 |
| Digital motor position vs exact sampled-data loop (difference equation + exact ZOH plant) | 4.4e-11 at every sample instant with SDIRK4 at 0.1 ms; 5.3e-13 with RK4 at 1 µs (strict C99) |
| Pendulum, CTMS algebraic-loop form vs SciPy DOP853 and vs the explicit form | 2.8e-7; 8.0e-14 |
| House: heater energy = stored + conducted losses (logged outputs only) | imbalance 4.6e-8; 337 kWh; cost $30.35; indoor 64.98–75.04 °F |
| Linear analysis of the pendulum (force → angle) | poles −5.6041, −0.1428, 0, 5.5651, the CTMS values |
| Linear analysis of the pitch loop | closed-loop poles = eig(A − BK); DC gain 1.000000 (Nbar) |
| Native GNU Octave and standalone `.m` vs Python | ≤ 3.6e-11 on a 160 000 V channel; ≤ 2e-12 elsewhere |
| Strict C99 (`-std=c99 -pedantic -Wall -Wextra -Werror`) vs Python | ≤ 4.4e-16; the SDIRK4 motor and the loop pendulum are refused by C export, as documented |
| Negative controls (lead numerator, Nbar, pulse amplitude, controller gain, Mdot, gravity dropped from P) | all rejected by the same references |

## GUI acceptance through UI Automation

`python tests/verify_gui_surface.py --octave` drives the real editor. It uses the `surfacekit`/`appsurface` toolkit, which is separate from this repository (set `SURFACEKIT_HOME`). Each model is copied, opened on a private hidden desktop and operated only through UIA control patterns: Check Model, Run on Local RK4 and on GNU Octave (switched through Simulation › Engine), Scope windows, Model Browser selection including a block inside a subsystem, a Property Inspector edit with Apply, the Model Workspace dialog, Save, and close with unsaved changes. It also checks that the Solver control shows each model's solver, that Save keeps it, and that Check Model names the loop variables of the algebraic-loop pendulum (168/168 checks across six models on 2026-10-15). Results are read back through UIA and from the saved file, and are recorded in `artifacts/verification/gui-surface.json`. `appsurface probe` measured the route as tier 1 (UIA, 88 elements, 80 ValuePattern) with no focus taken.

Captures in the real editor (`python tests/capture_public_mwes_2.py`) are in `artifacts/public-mwes-2/`.

## Defects found and fixed while replicating these examples

| Defect | Fix |
| --- | --- |
| Scope legends named the primitive inside a subsystem, so the two motors both read "Speed w" | Legends name the signal as drawn: `DC Motor (lag)`, `Pendulum/Angle` |
| Saving discarded a model's `provenance`/`description` | Document metadata round-trips |
| Native Octave engine ran at ~8 ms/step; 15 000–86 000-step models exceeded the 120 s job limit | Generator emits typed locals, one vectorised finiteness check per evaluation, hoisted constants and inline small powers: about 10× faster with identical results; the default job limit is now 600 s and Stop still cancels |
| Python engine spent 45 % of its time in per-signal NumPy reductions | Scalar `math.isfinite`: 2.1× faster, same semantics |
| Orthogonal router let two different signals share one lane (the lag and lead voltages looked connected) | Routes are penalised for running along another signal's segment; branches of one signal may still share |
| Subsystem blocks showed "Subsystem (Double-Click)" | Simulink-style inport/outport labels on the block face |
| UIA could not reach blocks (canvas), the engine choice (read-only combo value) or several unnamed controls | Model Browser (filterable, path-named rows), a Simulation menu with Engine choices, and accessible/object names |
| Qt's tree accessibility selects the wrong row around expanded parents | The Model Browser is a flat list of paths (`Thermostat › Relay`) |
| An existing Octave parity test used an absolute tolerance unsuitable for large-gain channels | Tolerance scales with each channel's magnitude |

Canonical Simulink capabilities added for these examples:

- Model Workspace variables (scalars and arrays, evaluated in order).
- Pulse Generator.
- Discrete Transfer Fcn and Discrete Zero-Pole.
- State-Space with a vector output.
- Gain in element-wise and Matrix(K*u) modes.
- Sum/Product with any input count and Simulink sign syntax (`|+-`, `3`).
- MATLAB array spacing: `[1 -2]` is two elements, `[1 - 2]` is one.

Each capability is implemented in the Python engine, the native Octave backend, the `.m` exporter and the C99 exporter.

## Solvers added for the stiff plant and the algebraic loop

Two capabilities exist in the Python engine, the native Octave backend and the `.m` export. The C99 export refuses them before writing files.

- **Implicit SDIRK4 solver** (`"solver": "sdirk4"` in the model; Simulation › Solver, or the Solver box under Solver Settings). This is the five-stage, fourth-order, L-stable and stiffly accurate SDIRK of Hairer and Wanner (*Solving ODEs II*, Table IV.6.5). Each step computes one forward-difference Jacobian of the block network, factors I − (h/4)J once, and runs a simplified Newton iteration per stage. The step aborts with a message if Newton fails to converge in 10 iterations. Discrete hits, Step and Pulse events, and left-limit end points are handled as in RK4. Explicit RK4 stays the default (`"rk4"`, or no key).
- **Algebraic loops.** Each strongly connected set of direct-feedthrough blocks is cut at scalar signals, choosing the block with the most loop inputs × outputs first (Mux and Demux are never cut). At every evaluation, each loop is solved by Newton on its cut signals, with a forward-difference Jacobian, a halving line search and a warm start from the previous solution. Held values the loop updates at a major step are restored before every trial. Check Model names the loop variables. A loop with no unique solution (singular Jacobian) or no scalar signal to cut is reported as an error.
- **Why SDIRK4 and not trapezoidal or BDF2.** A prototype on the motor-position loop at dt = 0.1 ms gave a sampled error of 6.0e-5 for TR-BDF2 and 2.2e-7 for SDIRK3, against 4.4e-11 for SDIRK4. Backward Euler blew up, because the Nyquist-rate controller mode is marginal. The trapezoidal rule is not L-stable: at hλ = −145 the armature mode would ring with |R| ≈ 0.97 per step.

| Check (`tests/test_solvers.py`, `tests/test_public_mwes_2.py`) | Result |
| --- | --- |
| Motor position, SDIRK4 at dt = 1e-4 vs exact sampled-data loop | 4.4e-11 at every sample; 801 steps take about 2 s in Python (RK4 needed 80 000 steps, about 45 s) and about 8 s in Octave (about 1.5 min) |
| Same model with RK4 at dt = 1e-4 | diverges (non-finite), as the −1.45e6 rad/s pole requires |
| Stiff linear plant (poles −1e6, −1) vs matrix exponential | 1.7e-12 at dt = 0.01; dt/2 gives 1.0e-13 (fourth order); RK4 at dt = 0.01 diverges |
| Van der Pol, μ = 1000, 0.7 s, vs SciPy Radau (rtol 1e-12) | 1.8e-6 at dt = 1e-3; 8.2e-8 at dt/2; RK4 at the same step diverges |
| CTMS pendulum, four-Fcn loop form vs explicit form | 8.0e-14 (both integrated by RK4 at 1 ms); vs SciPy DOP853 2.8e-7, the same as the explicit form |
| Loop with dynamics y = 1 − x − 3y, x' = y, vs closed form | 9.9e-14 |
| Self-loop y = cos(y) vs Brent's root | 0.739085133215161, error < 1e-12 |
| Native Octave and standalone `.m` vs Python | loop pendulum 7.2e-12, SDIRK4 motor 5.8e-14; the unit models 7e-18 or identical |
| Negative controls | unsolvable loop y = 1 + y refused (singular), in Python and Octave; Mux/Demux-only loop refused; wrong loop gain and a sign-flipped N expression rejected by the same references; C export refuses both features and writes no files; an unknown solver name is rejected |

## Limits that remain

- There is no variable-step solver. SDIRK4 is fixed-step, and the user picks the step: it cannot resolve near-discontinuous fast transients, such as the jump of the stiff Van der Pol oscillator at t ≈ 0.807 s.
- The C99 export implements RK4 only. It refuses SDIRK4 models and algebraic loops. The motor-position model still exports with RK4 at dt = 1e-6 (verified against the exact sampled-data reference).
- Algebraic loops are cut only at scalar signals. Every loop evaluation costs several network evaluations: the loop-form pendulum takes about 53 s in Python and about 1.5 min in Octave, against seconds for the explicit form. The loop Jacobian is not reused between evaluations.
- Only algebraic loops are handled; general DAEs and mass-matrix systems are not.
- The two-day house model takes tens of seconds in Python and about 1.5 min in Octave.
- Linear analysis does not handle discrete transfer blocks.
- The canvas itself is not in the UIA tree; the Model Browser covers selection.
- Library Browser rows below an expanded category are still subject to the Qt tree row mapping when driven through UIA.
- The house outdoor-temperature constants are a local choice, checked only against the published cost.
