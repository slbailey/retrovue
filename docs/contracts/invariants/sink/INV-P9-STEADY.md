# INV-P9-STEADY

This document defines steady-state mode.

Steady-state is governed by the following invariants:

- INV-P10-PCR-PACED-MUX
- RULE-P10-DECODE-GATE
- INV-P10-PRODUCER-THROTTLE
- INV-P10-BACKPRESSURE-SYMMETRIC
- INV-P10-BUFFER-EQUILIBRIUM
- INV-P10-NO-SILENCE-INJECTION
- INV-P9-NO-DEADLOCK

Bootstrap, liveness, and segment boundaries are governed by:

- INV-TS-EMISSION-LIVENESS
- INV-BOOTSTRAP-AV-CONTINUITY
- INV-TIME-AUTHORITY-SINGLE-SOURCE
- INV-CONTENT-DEFICIT-FILL
- INV-CONTROL-PLANE-CADENCE

Switch timing (core): INV-P8-SWITCH-BOUNDARY-TIMING.

This file MUST NOT introduce new behavioral guarantees.
