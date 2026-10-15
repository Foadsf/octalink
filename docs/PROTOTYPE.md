# OctaLink: Simulink for GNU Octave

**OctaLink** is an open-source, cross-platform, hardware-agnostic visual block diagram modeling, simulation, linear control analysis, and embedded code generation environment designed for GNU Octave.

---

## 1. System Architecture

OctaLink is built on a modular four-layer architecture:

```
┌──────────────────────────────────────────────────────────────────┐
│                   Layer 1: Visual Canvas & GUI                   │
│      PyQt6 Hardware-Accelerated 2D Canvas (QGraphicsScene/View)  │
│  Vector SVG UI & Block Schematics • Bézier Routing • Flip (Ctrl+I)│
│  Space/Mid-Pan • Subsystem Drill-Down • Interactive Scope Toolbar│
└────────────────────────────────┬─────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────┐
│                    Layer 2: Graph Compiler                       │
│  Hierarchical Subsystem Flattener (Inport/Outport alias resolver)│
│  Feedthrough Partitioning: Direct (Sum, Gain) vs Non-Direct (1/s) │
│     Kahn Topological Sorter & Multi-Port Index Resolver          │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────┐
│              Layer 3: Solver & Execution Engines                 │
│  • Hybrid Continuous/Discrete RK4 Solver with Multi-Rate Hits    │
│  • oct2py Live GNU Octave Session Bridge                         │
│  • linmod Padé-Augmented Numerical Perturbation Jacobian Engine  │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────┐
│           Layer 4: Target Generators & Instrumentation           │
│  • Standalone ANSI C99 Code Generator (octalink_model.h / .c)    │
│  • GNU Octave ode45 Simulation Exporter (.m) with Plotting/Legend│
│  • Linear Analysis Advisor: Bode, Nyquist, Margins, Step Metrics │
│  • Multi-Channel Matplotlib Scope with NavigationToolbar2QT      │
└──────────────────────────────────────────────────────────────────┘
```

### Feedback Loop Resolution Without Deadlocks
A fundamental challenge in block diagram modeling is closed-loop feedback (wiring an output back to an earlier input). OctaLink resolves feedback loops without hanging by classifying blocks into two categories at each time step $t$:
1. **Non-Direct Feedthrough Blocks (`Integrator`, `Transfer Fcn`, `State-Space`, `Unit Delay`):**
   Their outputs $y(t)$ depend strictly on internal states $x(t)$ and not instantaneously on inputs $u(t)$.
2. **Direct Feedthrough Blocks (`Sum`, `Gain`, `Product`, `Trig`, `Saturation`, `Relay`, `Switch`, `PID`, `Mux`, `Demux`):**
   Their outputs require instantaneous knowledge of inputs $u(t)$.

During every integration step:
- **Phase A:** Sources and Non-Direct Feedthrough blocks compute and emit outputs. This breaks all feedback loops.
- **Phase B:** The direct feedthrough network is evaluated along topological order.
- **Phase C:** Inputs arriving at state blocks form derivatives $\dot{x}(t)$ for continuous continuous RK4 integration or discrete state register updates $z[k+1]$ on sample-time hits.

---

## 2. Directory Layout

```
Octave_SIMULINK/
└── octalink/
    ├── octalink_gui.py               # Complete canonical application (GUI + Engine + Linmod + Coder)
    ├── octalink.py                   # Lightweight single-file reference prototype
    ├── run_tests.py                  # Standalone 6-stage test runner (headless/CI)
    ├── requirements.txt              # Python package dependencies
    ├── launch_octalink.bat           # Windows CMD launcher
    ├── launch_octalink.ps1           # Windows PowerShell launcher
    ├── pack_package.py               # Auto-syncing packager for GNU Octave pkg tarball
    ├── octalink-1.0.0.tar.gz         # Official installable GNU Octave package
    ├── README.md                     # Comprehensive documentation
    ├── examples/                     # Pre-built model files & generated code
    │   ├── hybrid_control_loop.json  # Pre-loaded closed-loop PID + plant + ZOH model
    │   ├── nonlinear_statespace.json # Nonlinear trig + product + state-space + demux model
    │   ├── hybrid_model.h            # Sample generated ANSI C99 header
    │   ├── hybrid_model.c            # Sample generated ANSI C99 implementation
    │   └── hybrid_model.m            # Sample generated GNU Octave ode45 simulation script
    └── octalink-1.0.0/               # GNU Octave Package Source Tree
        ├── DESCRIPTION               # Octave package metadata
        ├── INDEX                     # Package function index
        ├── COPYING                   # GNU GPLv3 license
        ├── inst/
        │   ├── octalink.m            # Octave command window entry point
        │   └── octalink_gui.py       # GUI application packaged for Octave
        └── src/
            ├── Makefile              # mkoctfile build script
            └── __octalink__.cc       # Native C++ DLD bridge (liboctinterp/liboctave)
```

---

## 3. Block Catalog

| Category | Block | Symbol | Description & Parameters |
|---|---|---|---|
| **Sources** | `Step` | `Step` | Emits step transition at `step_time` (`initial_val`, `final_val`). |
| | `Sine Wave` | `sin` | Sinusoidal generator (`amplitude`, `frequency`, `phase`). |
| | `Constant` | `C` | Constant value output (`value`). |
| **Math Operations** | `Sum` | `∑` | Multi-input adder/subtractor (`signs`, e.g. `+-` or `++-`). |
| | `Product` | `×` | Element-wise multiply/divide (`ops`, e.g. `**` or `*/`). |
| | `Gain` | `K` | Scalar multiplier (`gain`). |
| | `Trig` | `trig(u)` | Trigonometric function (`sin`, `cos`, `tan`, `asin`, `acos`, `atan`). |
| **User-Defined** | `Octave Function` | `f(u,t)` | Custom mathematical expression evaluated at runtime (`expression`). |
| **Discontinuities** | `Saturation` | `Sat` | Dynamic actuator signal limiter (`lower_limit`, `upper_limit`). |
| | `Relay` | `Relay` | Hysteresis on/off switch (`switch_on_point`, `switch_off_point`, `on_val`, `off_val`). |
| **Continuous** | `PID Controller` | `PID(s)` | Parallel PID with derivative filter (`Kp`, `Ki`, `Kd`, `N`). |
| | `Integrator` | `1/s` | Continuous integrator $\int u\,dt$ (`initial_condition`). |
| | `Transfer Fcn` | `G(s)` | Continuous SISO rational transfer function (`numerator`, `denominator`). |
| | `State-Space` | `x'=Ax+Bu`| Continuous state-space realization (`A`, `B`, `C`, `D`, `x0`). |
| **Discrete** | `Unit Delay` | `1/z` | Discrete delay register $z^{-1}$ (`initial_condition`, `sample_time`). |
| | `Zero-Order Hold` | `ZOH` | Sample-and-hold staircase discretization (`sample_time`). |
| **Signal Routing** | `Switch` | `Sw` | 3-input conditional switch: pass $u_1$ if $u_2 \ge \text{threshold}$ else $u_3$ (`threshold`). |
| | `Mux` | `Mux` | Bundles $N$ scalar/vector signals into a composite bus (`inputs`). |
| | `Demux` | `Demux`| Splits a composite bus into separate output ports (`outputs`). |
| | `Subsystem` | `Sub` | Hierarchical container with internal canvas. |
| | `Inport` | `In` | Subsystem input boundary port. |
| | `Outport` | `Out` | Subsystem output boundary port. |
| **Sinks** | `Scope` | `Scope` | Multi-channel oscilloscope with interactive toolbar, pan/zoom, and legend. |
| | `To CSV` | `CSV` | Time-series data logger exporting to disk (`filename`). |

---

## 4. Getting Started

### Prerequisites
Install the required Python libraries:
```bash
pip install -r requirements.txt
```
*(Required: `PyQt6`, `numpy`, `matplotlib`. Optional: `oct2py` for live Octave workspace variable binding. If GNU Octave is not present, OctaLink automatically falls back to its internal RK4 hybrid solver).*

### Launching the Application
- **Windows (PowerShell):**
  ```powershell
  .\launch_octalink.ps1
  ```
- **Windows (Command Prompt):**
  ```cmd
  launch_octalink.bat
  ```
- **Direct Python:**
  ```bash
  python octalink_gui.py
  ```
- **Load a Model on Startup:**
  ```bash
  python octalink_gui.py examples/hybrid_control_loop.json
  ```

---

## 5. User Interface & Keybindings

- **Block Flipping (`Ctrl+I`):** Select any block and press `Ctrl+I` (or click `Flip`) to flip its port orientation horizontally. Essential for routing feedback blocks from right to left with zero wire crossings.
- **Undo / Redo (`Ctrl+Z` / `Ctrl+Y`):** Full snapshot undo/redo stack for block creation, movement, deletion, and parameter edits.
- **Mouse Navigation:**
  - **Zoom:** Scroll mouse wheel (cursor-anchored zoom in/out).
  - **Pan:** Middle-click and drag, or hold `Space` and left-click drag.
  - **Select:** Rubber-band box selection.
- **Subsystem Grouping & Navigation:**
  - Select any group of blocks and click **Subsystem** to collapse them into a single hierarchical block with auto-generated `Inport` and `Outport` terminals.
  - Double-click a `Subsystem` to drill down into its internal diagram.
  - Click **Up** (or breadcrumb bar) to return to the parent canvas.
- **Wire Connection:** Left-click on any output port chevron (▶) and drag to an input port circle (○) to draw an orthogonal/Bézier connection.

---

## 6. Advanced Capabilities

### 6.1. Linear Analysis Advisor (`linmod` + Padé Delays + Margins)
Click **Linear Analysis** in the toolbar to run numerical perturbation around operating point $(\mathbf{x}_0, u_0)$ with central finite differences ($\delta = 10^{-5}$):
- **Padé Delay Linearization:** Automatically augments `Zero-Order Hold` ($\tau = T_s / 2$) and `Unit Delay` ($\tau = T_s$) with 1st-order Padé state-space realizations $P_1(s) = \frac{1 - s\tau/2}{1 + s\tau/2}$, ensuring sampling phase lag appears accurately on frequency plots.
- **Stability Margins:** Computes **Gain Margin (dB)** at phase crossover and **Phase Margin (deg)** at gain crossover.
- **Interactive 4-Panel Dashboard:**
  1. **Bode Magnitude** ($20\log_{10}|G(j\omega)|$ dB vs $\omega$).
  2. **Bode Phase** ($\angle G(j\omega)^\circ$ vs $\omega$, with $-180^\circ$ reference).
  3. **Nyquist Diagram** ($\text{Im}(G)$ vs $\text{Re}(G)$ with critical $(-1, 0)$ marker).
  4. **s-Plane Pole-Zero Map** (with stability boundary $\text{Re}(s)=0$).
- **Matplotlib Interactive Toolbar (`NavigationToolbar2QT`):** Zoom, pan, configure subplots, and export publication-ready SVG/PNG figures.
- **Time-Domain Step Response Metrics:**
  - Rise Time $T_r$ (10% to 90%)
  - Settling Time $T_s$ ($\pm 2\%$ band)
  - Peak Overshoot $\%OS$
  - Steady-State Error $e_{ss}$

### 6.2. Embedded ANSI C99 Code Generator (`Simulink Coder`)
Click **Export ANSI C** to compile the visual model into standalone ANSI C99 code:
- Generates `<model>.h` and `<model>.c`.
- Zero external dependencies beyond standard C `<stdint.h>` and `<math.h>`.
- Provides deterministic interfaces:
  ```c
  OctaLink_State st;
  OctaLink_Init(&st);
  while (1) {
      OctaLink_Step(&st, dt);
  }
  ```
- Ready for bare-metal microcontroller deployment (ARM Cortex-M, STM32, RP2040, ESP32, AVR, PIC) or hard real-time Linux loops.

### 6.3. Standalone GNU Octave Script Export (`.m`)
Click **Export .m** to generate a standalone GNU Octave script:
- Recreates the exact multi-phase topology.
- Integrates continuous states using Octave's native `ode45` solver.
- Correctly synchronizes discrete sample hits for ZOH and Unit Delays.
- Generates multi-channel comparison plots (`plot(T_log, Y_log, ...); grid on; legend(...);`).

---

## 7. GNU Octave Package (`pkg`) Installation

OctaLink complies with the official GNU Octave Package Manager structure:

```bash
# 1. Package the tarball (automatically synchronizes octalink_gui.py)
python pack_package.py

# 2. Inside GNU Octave, install and load the package:
octave --eval "pkg install octalink-1.0.0.tar.gz; pkg load octalink; octalink"
```

Once loaded, launch OctaLink directly from the Octave prompt:
```matlab
>> octalink
>> octalink("examples/hybrid_control_loop.json")
```

---

## 8. Verification & Self-Test Suite

OctaLink includes an automated 6-stage verification suite:
```bash
python run_tests.py
```
Or directly:
```bash
python octalink_gui.py --self-test
```

### Stages Verified:
1. **[1/6] Canvas, UX & Vector Icons:** Undo/Redo snapshot stack, selection grouping, block flipping (`Ctrl+I`), and vector SVG icon rendering.
2. **[2/6] Padé Delay Linearization:** Central finite-difference Jacobian perturbation with 6-state Padé augmentation, poles/zeros, Bode/Nyquist evaluation, Gain/Phase stability margins, and step metrics.
3. **[3/6] Embedded C99 Coder:** Code generation, GCC native compilation (`-std=c99 -O2 -Wall`), and binary execution verification.
4. **[4/6] Extended Block Set & Safe Regex:** Nonlinear math (`Product`, `Trig`), user-defined `Octave Function` (with word-boundary safe regex and `pow`), `State-Space` MIMO realization, `Mux`, and multi-port `Demux` output routing.
5. **[5/6] Switch, Relay & To CSV Sinks:** Discrete hysteresis relay switching, conditional signal routing, and multi-channel CSV time-series file writing.
6. **[6/6] Octave Exporter:** Generation and syntax verification of standalone `ode45` simulation script with multi-channel plotting and legend.
