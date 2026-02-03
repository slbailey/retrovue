# Phase 9 Task Specs

This directory contains individual task specifications for Phase 9: Steady-State Playout Correctness.

## Task Index

### Core Implementation (P9-CORE-*)

| Task ID | Purpose | Invariant | Status |
|---------|---------|-----------|--------|
| P9-CORE-001 | Steady-state entry detection | INV-P9-STEADY-001 | Pending |
| P9-CORE-002 | PCR-paced mux loop | INV-P9-STEADY-001 | Pending |
| P9-CORE-003 | Disable silence injection | INV-P9-STEADY-008 | Pending |
| P9-CORE-004 | Remove local CT counters | INV-P9-STEADY-007 | Pending |
| P9-CORE-005 | Slot-based decode gating | INV-P9-STEADY-002 | Pending |
| P9-CORE-006 | Symmetric A/V backpressure | INV-P9-STEADY-003 | Pending |
| P9-CORE-007 | Pad-while-depth-high violation | INV-P9-STEADY-004 | Pending |
| P9-CORE-008 | Equilibrium monitoring | INV-P9-STEADY-005 | Pending |

### Contract Tests (P9-TEST-*)

| Task ID | Purpose | Invariant | Status |
|---------|---------|-----------|--------|
| P9-TEST-001 | Mux waits for CT | INV-P9-STEADY-001 | Pending |
| P9-TEST-002 | No burst consumption | INV-P9-STEADY-001 | Pending |
| P9-TEST-003 | Slot-based blocking | INV-P9-STEADY-002 | Pending |
| P9-TEST-004 | No hysteresis | INV-P9-STEADY-002 | Pending |
| P9-TEST-005 | Symmetric backpressure | INV-P9-STEADY-003 | Pending |
| P9-TEST-006 | Coordinated stall | INV-P9-STEADY-003 | Pending |
| P9-TEST-007 | Pad violation detection | INV-P9-STEADY-004 | Pending |
| P9-TEST-008 | Buffer equilibrium 60s | INV-P9-STEADY-005 | Pending |
| P9-TEST-009 | Frame rate accuracy | INV-P9-STEADY-006 | Pending |
| P9-TEST-010 | PTS bounded to clock | INV-P9-STEADY-006 | Pending |
| P9-TEST-011 | No CT reset on attach | INV-P9-STEADY-007 | Pending |
| P9-TEST-012 | Silence disabled | INV-P9-STEADY-008 | Pending |

### Optional Tasks (P9-OPT-*)

| Task ID | Purpose | Status |
|---------|---------|--------|
| P9-OPT-001 | Equilibrium warning log | Pending |
| P9-OPT-002 | Steady-state metrics | Pending |
| P9-OPT-003 | Steady-state entry log | Pending |

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/PHASE9_STEADY_STATE_CORRECTNESS.md` | Architectural contract |
| `docs/contracts/PHASE9_EXECUTION_PLAN.md` | Execution plan |
| `docs/contracts/PHASE9_TASKS.md` | Task checklist |
