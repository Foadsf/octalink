# OctaLink completion plan

Scope: finish the requested first MVP on the existing Qt editor. Preserve its curved/orthogonal per-diagram preference and current model corpus. Connect actual GNU Octave execution, qualify C/.m generation against the corrected solver, make linear analysis selectable and interpretable, verify reference cases and package the source. Full proprietary Simulink product parity is beyond the first-MVP scope.

| Component | Selected approach | Alternative | Reason |
| --- | --- | --- | --- |
| Octave execution | Local CLI process per job | oct2py live bridge | Explicit process ownership, cancellation and no extra dependency |
| Editor | Extend existing native Qt application | Replace editor | Preserve functional work and familiar gestures |
| Verification | Analytical solutions + adaptive ode45 + independently compiled C | Generated artifact structure only | Measures results and catches defects |

These choices are compatible: the worker exchanges plain model/result records with either process engine; the editor stays responsive. A live shared workspace would add session/state ownership constraints and is deferred.

Backward dependency chain: delivered packages <- identity verification and native exercise <- GUI/CLI integration <- native engines, qualified exporters, analysis <- existing compiled graph contract. Engine/export/analysis work proceeds in parallel; editor integration and final checks join those tracks.

Must: real Octave Run/Stop, original examples load, saved backend/style settings, analytical/native comparisons, correctly described analysis and reproducible release. Should: qualify generated C and standalone Octave functions for the supported block set. Could: more example models and small UX refinements. Out of scope: Stateflow/Simscape/SLX/hardware deployment and claiming untested OS support.

Planning estimates in minutes, not promised completion times:

| Track | Optimistic | Likely | Pessimistic | PERT expected |
| --- | ---: | ---: | ---: | ---: |
| Native Octave backend | 15 | 30 | 60 | 32.5 |
| C export qualification | 15 | 30 | 60 | 32.5 |
| Linear analysis qualification | 10 | 20 | 45 | 22.5 |
| GUI/CLI integration | 10 | 15 | 30 | 16.7 |
| Final verification/package | 5 | 15 | 30 | 15.8 |

The likely critical path is native-engine/export readiness -> final integration -> verification/package. Most editor work overlaps with engine work. Estimates are a planning aid; completion depends on acceptance evidence.
