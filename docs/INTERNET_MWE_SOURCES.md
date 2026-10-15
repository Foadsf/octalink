# Public Simulink examples adapted to OctaLink

These editable JSON diagrams reproduce the equations and listed parameters of
three public examples. They are independently authored signal-flow models;
they do not import `.slx` files or execute Simulink/Simscape. Public source
figures and MathWorks model files are not redistributed. Source pages were
checked on 2026-10-15; parameter attribution and local modeling choices follow.

Retrieval: MathWorks content was read directly. CTMS parameters and modeling
instructions were retrieved from indexed page extracts; direct page opens
returned HTTP 403. No authenticated access or downloaded Simulink model was
used. The force-balance equations are implemented independently below.

| Model | Public source | Parameters and physics retained |
| --- | --- | --- |
| `examples/mwe_dc_motor.json` | [University of Michigan CTMS, Motor Speed: Simulink Modeling](https://ctms.engin.umich.edu/CTMS/?example=MotorSpeed&section=SimulinkModeling) | `J=0.01`, `b=0.1`, `Kt=Ke=0.01`, `R=1`, `L=0.5`, SI units. Armature inductance and shaft inertia remain separate integrators. |
| `examples/mwe_cruise_pi.json` | [CTMS, Cruise Control: Simulink Control](https://ctms.engin.umich.edu/CTMS/?example=CruiseControl&section=SimulinkControl), and [CTMS, Cruise Control: Simulink Simscape](https://ctms.engin.umich.edu/CTMS/?example=CruiseControl&section=SimulinkSimscape) | `m=1000 kg`, `b=50 N s/m`, `Kp=800`, `Ki=40`; the latter page supplies these PI values. The mechanical force-balance plant is adapted to explicit signal-flow blocks inside a real subsystem. |
| `examples/mwe_van_der_pol.json` | [MathWorks, Van der Pol Oscillator](https://www.mathworks.com/help/simulink/slref/van-der-pol-oscillator.html) | `x'=v`, `v'=Mu*(1-x^2)*v-x`; `Mu=1` by default, and editable as a Gain. `Mu=0` provides the harmonic control. |

The motor equations are `i'=(V-R*i-Ke*w)/L` and
`w'=(Kt*i-b*w)/J`. The local input is a 1 V step at time zero, with both
states initially zero. The local horizon is 3 s and fixed RK4 step is 0.005 s.
Scope channel order is speed in rad/s, then current in A. The model contains
explicit resistance, back EMF, torque, drag, and inverse-inertia gains.

The cruise equations are `v'=(F-b*v)/m`, `e=r-v`, and
`F=Kp*e+Ki*integral(e)`. The local reference is a 10 m/s step at time zero,
all states start at zero, and the local horizon is 10 s with step 0.01 s.
The controller is continuous and unsaturated. It has no actuator dynamics,
road gradient, gear changes, aerodynamic quadratic drag, or anti-windup.
The `Vehicle` subsystem has genuine Inport/Outport boundaries and an internal
velocity integrator and drag feedback. Scope 9 records reference and speed;
Scope 10 records commanded force. This is a signal-flow adaptation of the
force balance, with no claim of Simscape physical-network parity.

The Van der Pol initial state `[x,v]=[2,0]` follows the already-retained installed
GNU Octave example in `tests/references/ode45-upstream.m` and
`tests/references/van_der_pol_reference.m` (GNU GPL-3.0-or-later). That initial
state, 10 s horizon, and fixed step 0.01 s are local choices. `x squared` is a
Product block with both inputs connected to displacement; subsequent Sum,
Gain, and Product blocks expose the entire nonlinear force. It does not hide
the ODE in an expression block. Scope order is displacement, then velocity.

Existing local starting points were `examples/first_order_feedback.json`,
`examples/van_der_pol.json`, the reusable `Document` and strict C99 compiler
harness in `tests/test_c_export.py`, and the independent adaptive Octave
reference in `tests/references/van_der_pol_reference.m`. These retain the
repository's established persistence and graph APIs.

## Reproducible numerical acceptance

From the repository root, Windows/PowerShell:

```powershell
python -m unittest discover -s tests -p test_internet_mwes.py -v
```

The eight tests require native GNU Octave and installed gcc. They fail if
either tool is absent. Every sample and every scope channel is compared for
the Python engine, native Octave engine, independently executable `.m` export,
and C export compiled with `-std=c99 -pedantic -Wall -Wextra -Werror -O2`.
Linear models use an independent analytical matrix-exponential solution via
NumPy eigendecomposition. Van der Pol uses a separate adaptive Octave `ode45`
solution at tight tolerances; the generated block network uses RK4. Checks
also compare the selected linear matrices, poles, and DC gain to explicit
physics matrices. `Mu=0` is compared with `[2*cos(t),-2*sin(t)]`; halving the
nonlinear step must reduce its maximum error by more than eightfold.

Negative controls actually change the source motor torque gain, cruise
feedback sign, and nonlinear Mu. The same full-trace reference comparisons
must reject them. Separate controls require missing-input and invalid-port
validation failures, and reject the otherwise-valid motor model with swapped
scope channels. Runtime measurements are written to
`artifacts/verification/internet-mwe-numerics.json`.

The numerical checks establish fidelity of these equations over these finite
intervals. They do not establish hardware behavior, physical parameter
identification, stiff/DAE solver behavior, or compatibility with arbitrary
Simulink files.
