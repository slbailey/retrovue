# INV-HLS-SEGMENT-BLOCK-ALIGNMENT-001 — Audit uses snapshot block window

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CLOCK`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CLOCK` by ensuring that a seam-straddling segment is audited against the block window from its start time, not the post-transition block window. Without this guarantee, every segment that starts in block N and completes after block N+1 activates would fire a spurious audit warning, because its wallclock falls within block N's window, not block N+1's window.

## Guarantee

A segment's wallclock audit MUST validate against the block window from the segment's start-time snapshot, not the currently active block at completion time.

## Preconditions

- A BlockPlan timebase with non-zero block window has been set before the segment begins.

## Observability

A segment that straddles a block transition completes without an `INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001` warning when its wallclock falls within the snapshot block window.

## Deterministic Testability

Set old block timebase with window `[1000000, 2000000)`. Start a segment (wallclock ~1000000). Set new block timebase with window `[2000000, 3000000)` mid-segment. Complete the segment. Assert wallclock is in `[1000000, 2000000)` and no audit warning is logged.

## Failure Semantics

Runtime fault. An audit that fires because a seam-straddling segment was validated against the post-transition block window instead of the snapshot window.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_timebase_snapshot.py`

## Enforcement Evidence

TODO
