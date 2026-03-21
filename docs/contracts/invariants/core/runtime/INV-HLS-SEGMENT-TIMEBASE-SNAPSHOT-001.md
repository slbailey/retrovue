# INV-HLS-SEGMENT-TIMEBASE-SNAPSHOT-001 — Segment timebase frozen at start

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CLOCK`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CLOCK` and `LAW-DERIVATION` by ensuring that a segment's editorial wallclock mapping cannot be corrupted by a BlockPlan timebase change that arrives mid-segment. Without this guarantee, `_compute_wall_clock_ms()` could mix a PCR from one editorial epoch with a timebase origin from another, producing a PROGRAM-DATE-TIME that corresponds to neither block.

## Guarantee

Each segment MUST capture and retain the editorial timebase (`timebase_start_utc_ms`, `timebase_pcr_origin`, and active block window) at segment start. All wallclock computations for that segment MUST use this snapshot exclusively.

## Preconditions

- A BlockPlan timebase has been set via `set_blockplan_timebase()` before the first PCR packet of the segment.

## Observability

`_compute_wall_clock_ms()` reads only from `_snap_*` fields. Any read of a mutable `_timebase_*` field during wallclock computation is a violation.

## Deterministic Testability

Set timebase A, feed packets to start a segment, call `set_blockplan_timebase()` with timebase B mid-segment, complete the segment. Assert the segment's `wall_clock_start_utc_ms` is derived from timebase A, not B.

## Failure Semantics

Runtime fault. A segment whose PROGRAM-DATE-TIME was derived from a timebase that changed after the segment began accumulation. Manifest consumers observe a timestamp discontinuity without a corresponding `EXT-X-DISCONTINUITY` marker.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_timebase_snapshot.py`

## Enforcement Evidence

TODO
