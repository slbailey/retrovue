# INV-PLAYLIST-EVENT-SEGMENT-ORDER-003

## Behavioral Guarantee

Segments within a PlaylistEvent must be contiguous — each segment's logical end equals the next segment's logical start with no gaps. Segments are ordered by their position in the list; the implicit start of each segment is the cumulative duration of all preceding segments added to the block's `start_utc_ms`.

## Authority Model

Block expansion owns segment ordering and contiguity. Segments are emitted in playout order. The segment list itself IS the ordering — no separate ordering field exists.

## Boundary / Constraint

Given a PlaylistEvent `PE` starting at `start_utc_ms` with segments `[S_0, S_1, ..., S_n]`:

Define the implicit timeline position of each segment:

```
S_0.implicit_start = PE.start_utc_ms
S_i.implicit_end   = S_i.implicit_start + S_i.segment_duration_ms
S_{i+1}.implicit_start = S_i.implicit_end
```

For every adjacent pair `(S_i, S_{i+1})`:

```
S_i.implicit_end == S_{i+1}.implicit_start
```

This is satisfied by construction when segments are stored as an ordered list with positive durations (guaranteed by INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002). The invariant additionally requires:

- Segments are in strictly ascending timeline order (no reordering).
- No gap exists between the logical end of one segment and the logical start of the next.
- The first segment starts at `PE.start_utc_ms`.
- The last segment ends at `PE.end_utc_ms`.

## Violation

Any of the following:

- A segment's implicit start does not equal the previous segment's implicit end (gap or overlap between segments).
- The first segment does not start at `PE.start_utc_ms`.
- The last segment does not end at `PE.end_utc_ms`.

MUST be logged as a planning fault with fields: `block_id`, `segment_index`, `expected_start_ms`, `actual_start_ms`.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_event_segments.py::test_segments_contiguous` — no gaps between adjacent segments.
- `pkg/core/tests/contracts/playout/test_playlist_event_segments.py::test_segments_ordered` — segments tile from block start to block end.

## Enforcement Evidence

- **Guard location:** Block expansion pipeline — segment list is constructed in order with durations that tile the block.
- **Error tag:** `INV-PLAYLIST-EVENT-SEGMENT-ORDER-003-VIOLATED`
