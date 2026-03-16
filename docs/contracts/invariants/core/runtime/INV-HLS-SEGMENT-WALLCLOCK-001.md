# INV-HLS-SEGMENT-WALLCLOCK-001

## Behavioral Guarantee

Each HLS segment carries a wall-clock start timestamp derived from the channel's BlockPlan schedule (MasterClock origin). The timestamp represents the editorial broadcast time of the segment's first frame.

## Authority Model

HLSSegmenter owns timestamp assignment. BlockPlan `start_utc_ms` is the upstream authority. MasterClock is the ultimate time source.

## Boundary / Constraint

- Segment wall-clock timestamp MUST be derived from BlockPlan timing, not from system clock at the moment of segmentation.
- The timestamp MUST fall within the time range of a BlockPlan block that was active during that segment's production.
- Segments MUST NOT carry timestamps derived from `datetime.now()`, `time.time()`, or any non-MasterClock source.

## Violation

Segment timestamp derived from system clock rather than BlockPlan; timestamp outside the active block's time range; timestamp diverging from MasterClock-derived editorial truth.

## Derives From

`LAW-CLOCK`, `LAW-DERIVATION`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_segment_production.py`

## Enforcement Evidence

TODO
