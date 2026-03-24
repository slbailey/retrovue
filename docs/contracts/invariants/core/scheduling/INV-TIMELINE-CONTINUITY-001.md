# INV-TIMELINE-CONTINUITY-001 — No gaps, no overlaps

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-LIVENESS`, `LAW-TIMELINE`

## Purpose

Protects `LAW-GRID` and `LAW-LIVENESS` by ensuring the timeline forms a contiguous, non-overlapping sequence. Gaps mean no content airs. Overlaps mean two programs claim the same time and the system must arbitrarily discard one.

## Guarantee

The timeline MUST form a continuous, non-overlapping sequence of blocks. No time within the defined timeline may be unassigned or multiply assigned.

## Observability

For any adjacent blocks A and B, A.end MUST equal B.start.

## Deterministic Testability

Compile a multi-day timeline. For every pair of adjacent blocks (ordered by start time), assert that the first block's end time equals the second block's start time exactly. Assert that no time between the first block's start and the last block's end is uncovered.

## Failure Semantics

**Planning fault.** Gaps cause playback errors (no content to play). Overlaps cause ambiguous block selection (two blocks cover the same time).

## Required Tests

- `pkg/core/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

TODO
