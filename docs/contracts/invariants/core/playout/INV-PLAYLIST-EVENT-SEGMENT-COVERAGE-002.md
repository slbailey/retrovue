# INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002

## Behavioral Guarantee

The segments within a PlaylistEvent must exactly cover the block's total duration. No time is unaccounted for — the sum of all segment durations equals the block duration with zero remainder.

## Authority Model

Block expansion (PlaylistEvent generation) owns segment duration allocation. Each segment's `segment_duration_ms` is assigned during expansion. The invariant ensures no time is lost or invented during the process.

## Boundary / Constraint

Given a PlaylistEvent `PE` with segments `[S_0, S_1, ..., S_n]`:

```
sum(S_i.segment_duration_ms for i in 0..n) == PE.end_utc_ms - PE.start_utc_ms
```

Integer equality. No tolerance.

Additionally:

- Every segment MUST have `segment_duration_ms > 0` (positive duration).
- The segment list MUST NOT be empty.

## Violation

Any of the following:

- `sum(segment_duration_ms)` < `block_duration_ms` (uncovered time — gap).
- `sum(segment_duration_ms)` > `block_duration_ms` (excess time — overflow).
- Any segment has `segment_duration_ms <= 0` (zero or negative duration).
- Segment list is empty.

MUST be logged as a planning fault with fields: `block_id`, `block_duration_ms`, `segment_sum_ms`, `delta_ms = segment_sum_ms - block_duration_ms`.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_event_segments.py::test_segments_cover_block` — sum of segment durations equals block duration.

## Enforcement Evidence

- **Guard location:** Block expansion pipeline and any PlaylistEvent validation path.
- **Error tag:** `INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002-VIOLATED`
