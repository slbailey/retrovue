# INV-SWITCH-BOUNDARY-TIMING

## Behavioral Guarantee
A producer/source switch MUST complete no later than one frame duration after the declared schedule boundary.

## Authority Model
- Core declares the authoritative boundary timestamp.
- AIR executes the switch relative to that boundary.

## Boundary / Constraint
Switch completion time is measured against the declared boundary timestamp.
Frame duration is defined by the active output FPS.

## Violation
If switch completion time exceeds boundary + one frame duration, a violation MUST be logged.

## Required Tests
- `pkg/core/tests/contracts/test_inv_switch_boundary_timing.py` (Core declares boundary in protocol)
- `pkg/air/tests/contracts/DeadlineSwitchTests.cpp` (AIR executes switch within one frame of boundary)

## Enforcement Evidence

**Core (protocol boundary):**
- `pkg/core/tests/contracts/test_inv_switch_boundary_timing.py` — Verifies `SwitchToLiveRequest` includes `target_boundary_time_ms` and `issued_at_time_ms` fields, and that the boundary timestamp is >= issuance timestamp.

**AIR (execution boundary):**
- `pkg/air/tests/contracts/DeadlineSwitchTests.cpp` — Verifies switch completes within one frame duration (33 ms at 30 fps) of the declared boundary.
- `pkg/air/src/runtime/PlayoutEngine.cpp` (lines 834–968) — Runtime enforcement:
  - Line 834: `INV-BOUNDARY-DECLARED-001` — Logs receipt of `target_boundary_time_ms`.
  - Lines 855–868: `INV-BOUNDARY-TOLERANCE-001` — Measures switch completion delta against 33 ms tolerance; logs violation and records metric if exceeded (control-surface path).
  - Lines 889–903: `INV-BOUNDARY-TOLERANCE-001` — Same tolerance check for auto-completed switch path.
  - Lines 913–968: `INV-SWITCH-DEADLINE-AUTHORITATIVE-001` — Deadline-aware wait: evaluates lead time from `issued_at_time_ms`, waits until `target_boundary_time_ms`, then executes switch at deadline.
