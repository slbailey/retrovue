# INV-CROSS-DAY-CARRY-IN-001 — Cross-day carry-in resolution

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`, `LAW-LIVENESS`

## Primary Invariant

The compiled schedule MUST form a strictly contiguous timeline:

    block[i].end_utc_ms == block[i+1].start_utc_ms

Carry-in resolution is one mechanism that protects this invariant at broadcast day boundaries.

## Purpose

Protects `LAW-LIVENESS` and `LAW-GRID` by ensuring that a program which crosses a broadcast day boundary does not create overlapping or unreachable blocks in the subsequent day. Broadcast days are accounting constructs — the schedule is a continuous linked list where each block starts where the previous one ended. When a carry-in program extends past the day boundary, subsequent blocks MUST be pushed forward to maintain contiguity rather than trimmed or dropped.

## Guarantee

When a program from broadcast day N extends past the broadcast day N+1 boundary, the carry-in resolution stage MUST push program blocks forward so that:

1. Blocks whose entire slot falls before the carry-in end are dropped (fully subsumed).
2. The first surviving block starts at the carry-in end time.
3. All subsequent blocks cascade forward to maintain strict contiguity.
4. No block is trimmed — content duration is preserved; only start times shift.

Carry-in resolution MUST occur before block expansion so that blocks are born with correct start times.

## Preconditions

- `effective_day_open_ms` is computed as `max(broadcast_day_start_ms, active_carry_in_end_ms)`.
- `active_carry_in_end_ms` propagates forward across empty days (days where all blocks are subsumed).
- The carry-in end time is derived from the previous day's last block `end_utc_ms`.

## Observability

A merge-time guardrail detects any residual overlaps after carry-in resolution. If the guardrail fires, it logs `WARNING` with `INV-CROSS-DAY-CARRY-IN-001 GUARDRAIL` — this indicates the carry-in resolution stage missed a case.

Block contiguity violations surface as playout session seeding rejecting non-contiguous blocks.

## Deterministic Testability

Construct a two-day scenario where day N's last program extends 30 minutes past the day N+1 boundary. Compile day N+1 with `effective_day_open_ms` set to the carry-in end. Verify: (1) blocks ending before the carry-in end are dropped, (2) the first surviving block starts at the carry-in end, (3) subsequent blocks are contiguous, (4) the guardrail produces no warnings.

## Failure Semantics

**Planning fault.** A carry-in overlap that reaches the merge-time guardrail indicates a defect in the carry-in resolution stage. A carry-in overlap that reaches playout session seeding indicates both carry-in resolution and the guardrail failed.

## Required Tests

- `pkg/core/tests/contracts/scheduling/test_inv_cross_day_carry_in.py`

## Enforcement Evidence

TODO
