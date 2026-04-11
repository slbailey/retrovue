# INV-HLS-PDT-MONOTONIC-001 — Non-decreasing PROGRAM-DATE-TIME

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CLOCK`

## Purpose

Protects `LAW-CLOCK` by ensuring that PROGRAM-DATE-TIME values across consecutive HLS segments never jump backward. A backward jump causes HLS clients to miscompute live-edge position and may trigger seek-to-live failures or infinite rebuffering.

## Guarantee

PROGRAM-DATE-TIME values across consecutive HLS segments MUST be strictly non-decreasing. For consecutive segments i and i+1, `segment[i+1].wall_clock_start_utc_ms` MUST be >= `segment[i].wall_clock_start_utc_ms`.

## Preconditions

- Segments are produced in index order by a single `HlsSegmenter` instance.
- BlockPlan timebases advance forward in time (block N+1 starts at or after block N ends).

## Observability

A manifest where a segment's PROGRAM-DATE-TIME is earlier than the preceding segment's PROGRAM-DATE-TIME.

## Deterministic Testability

Build 3+ segments across a block transition. Assert each segment's `wall_clock_start_utc_ms` is >= the previous segment's value.

## Failure Semantics

Runtime fault. No backward timestamp jumps. A violation indicates either a timebase snapshot failure or a BlockPlan with non-monotonic editorial times.

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_segment_timebase_snapshot.py`

## Enforcement Evidence

TODO
