# INV-HLS-SEGMENT-EDITORIAL-CONSISTENCY-001 — No cross-timebase contamination

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CLOCK`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CLOCK` and `LAW-DERIVATION` by ensuring that all fields used in a single wallclock computation belong to the same editorial epoch. A segment that mixes a PCR origin from block A with a `timebase_start_utc_ms` from block B produces a timestamp that is internally inconsistent and belongs to neither block's editorial timeline.

## Guarantee

A segment's PROGRAM-DATE-TIME MUST be derived from a single, internally consistent timebase. All fields used in wallclock computation (`timebase_start_utc_ms`, `timebase_pcr_origin`, `seg_start_pcr`) MUST belong to the same editorial epoch. Mixing timebase state across block transitions is prohibited.

## Preconditions

- At least one `set_blockplan_timebase()` call has been made before the segment begins.

## Observability

Consecutive segments spanning a block transition produce wallclocks derived from different timebases. Each segment's wallclock is self-consistent with the timebase that was active when it started.

## Deterministic Testability

Set timebase A, start and complete segment 1 across a mid-segment timebase change to B. Then start and complete segment 2 under timebase B. Assert segment 1 wallclock derives from A, segment 2 wallclock derives from B, and the two wallclocks differ.

## Failure Semantics

Runtime fault. A segment whose wallclock was computed using a PCR origin from one block and a `timebase_start_utc_ms` from a different block.

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_segment_timebase_snapshot.py`

## Enforcement Evidence

TODO
