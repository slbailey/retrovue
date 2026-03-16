# INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001

## Behavioral Guarantee

Every completed segment's wall-clock timestamp is audited against the active BlockPlan block's time range. A segment whose timestamp falls outside the active block's `[start_utc_ms, end_utc_ms)` range is a timeline violation.

## Authority Model

HLSSegmenter owns the audit check at segment completion time. BlockPlan `start_utc_ms` and `end_utc_ms` are the authoritative boundaries.

## Boundary / Constraint

- At segment completion, the segmenter MUST verify `block.start_utc_ms <= segment.wall_clock_start_utc_ms < block.end_utc_ms`.
- If the check fails, the segmenter MUST log at WARNING level with invariant ID, the segment timestamp, and the block time range.
- The segment MUST NOT be dropped on audit failure — it represents real playout output and MUST still be pushed to the ring. The warning enables operator diagnosis.
- Wall-clock timestamps MUST be computed from BlockPlan offsets, not from `time.time()` or `datetime.now()`.

## Violation

Segment timestamp outside active block range; timestamp derived from system clock; audit check omitted at segment completion.

## Derives From

`INV-HLS-SEGMENT-WALLCLOCK-001`, `LAW-CLOCK`, `LAW-DERIVATION`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_timeline.py`

## Enforcement Evidence

TODO
