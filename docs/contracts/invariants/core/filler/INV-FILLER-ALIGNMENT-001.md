# INV-FILLER-ALIGNMENT-001 — Filler offset computation matches declared alignment mode

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

## Purpose

Filler segments fill time gaps in scheduled blocks. The alignment mode (`"start"` or `"end"`) determines where within the filler asset playback begins. An incorrect offset computation causes the wrong portion of the filler to air, and in `"end"` mode, prevents the filler from terminating at the block seam. This protects `LAW-GRID` (exact duration accounting) and `LAW-CONTENT-AUTHORITY` (operator-declared alignment intent is honored).

## Guarantee

When `alignment` is `"start"`, the first filler segment in a gap MUST have `asset_start_offset_ms` equal to the current wrapping offset. When `alignment` is `"end"` and `gap_ms <= filler_duration_ms`, the filler segment MUST have `asset_start_offset_ms = filler_duration_ms - gap_ms`. When `alignment` is `"end"` and `gap_ms > filler_duration_ms`, the partial segment MUST have `asset_start_offset_ms = filler_duration_ms - (gap_ms % filler_duration_ms)` and MUST precede any full-loop segments.

In all cases, `sum(segment_duration_ms) == gap_ms`.

## Preconditions

- `filler_duration_ms > 0`
- `gap_ms > 0`
- `alignment` is `"start"` or `"end"`

## Observability

Inspect filler segments in the playlog. For each filler segment, verify `asset_start_offset_ms + segment_duration_ms <= filler_duration_ms`. For end-aligned gaps, verify the final segment ends at `asset_start_offset_ms + segment_duration_ms == filler_duration_ms`.

## Deterministic Testability

Construct gaps of varying sizes relative to filler duration. For each alignment mode, verify the offset and duration of every produced segment against the formulae in `filler_alignment.md`. No real-time waits required.

## Failure Semantics

**Planning fault.** Incorrect offset computation is a defect in the filler construction logic.

## Required Tests

- `server/tests/contracts/test_filler_alignment.py`

## Enforcement Evidence

TODO
