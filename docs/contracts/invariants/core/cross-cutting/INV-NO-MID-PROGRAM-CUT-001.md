# INV-NO-MID-PROGRAM-CUT-001 — Programs without breakpoints must not be cut mid-play

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-DERIVATION`, `LAW-GRID`

## Purpose

Preserves editorial intent across the derivation chain. A Program without declared breakpoints represents an indivisible editorial unit as authored in SchedulePlan. Cutting it mid-play in any derived artifact (ScheduleDay slot, Playlist entry, ExecutionEntry) constitutes a downstream layer reinterpreting upstream editorial truth — a direct violation of `LAW-DERIVATION`. The cut also produces an off-grid boundary (the cut point is not a grid boundary), violating `LAW-GRID`.

## Guarantee

A Program with no declared breakpoints (no cue points, act breaks, SCTE markers, or chapter markers) MUST NOT be interrupted mid-play in any derived artifact. Its full runtime must be consumed within the derived schedule sequence.

Longform programs without breakpoints may extend across grid block boundaries by consuming whole additional blocks. This is the only permitted form of off-nominal duration handling.

## Preconditions

- Asset is of Program type.
- Program has no declared breakpoints (the breakpoint list is empty or absent).

## Observability

At Playlist generation, any cut-point within a breakpoint-free Program is a violation. The Playlist entry set MUST contain exactly one entry spanning the Program's full runtime (or a set of entries that, taken together, contain no cut within the Program, only at declared breakpoints). Violation: log Program ID, channel ID, and the unauthorized cut time.

## Deterministic Testability

Create a Program with no breakpoints spanning 90 minutes against a 30-minute grid. Generate a Playlist. Assert the Playlist does not contain a cut within the 90-minute program. Assert the Program consumes 3 whole grid blocks. No real-time waits required.

## Failure Semantics

**Planning fault.** The Playlist generation logic introduced a cut at a non-authorized position. Root cause is in the scheduler's zone-boundary or grid-alignment logic, not in the Program definition.

## Required Tests

- `pkg/core/tests/contracts/test_inv_no_mid_program_cut.py`

## Enforcement Evidence

- **Grid alignment enforcement:** `TestInvPlanGridAlignment001` in `test_scheduling_constitution.py` validates that ScheduleDay slot boundaries align to grid — a mid-program cut would produce an off-grid boundary, which is rejected.
- **Full-coverage tiling:** `TestInvPlanFullCoverage001` in `test_scheduling_constitution.py` validates that Playlist entries tile the broadcast day exactly — a cut within a breakpoint-free program would leave a gap or produce a misaligned boundary.
- **Longform accommodation:** Programs without breakpoints that exceed a single grid block may consume whole additional blocks — this is the only permitted off-nominal duration handling, preserving the indivisible editorial unit.
- Dedicated contract test (`test_inv_no_mid_program_cut.py`) for explicit mid-program cut rejection is referenced in `## Required Tests` but not yet implemented in the current tree.
