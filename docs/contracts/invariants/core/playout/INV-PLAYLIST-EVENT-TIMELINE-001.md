# INV-PLAYLIST-EVENT-TIMELINE-001

## Behavioral Guarantee

A PlaylistEvent's wall-clock boundaries must exactly match the ScheduleItem it was expanded from. The ScheduleItem defines the editorial time slot; the PlaylistEvent occupies that slot without shifting, truncating, or extending it.

## Authority Model

PlaylistEvent generation (block expansion) is responsible for preserving timeline alignment. ScheduleItem owns editorial timing; PlaylistEvent inherits it without modification.

## Boundary / Constraint

Given a ScheduleItem `S` and its derived PlaylistEvent `PE`:

- `S.start_at` (converted to epoch ms) == `PE.start_utc_ms` (integer equality)
- `S.end_at` (converted to epoch ms) == `PE.end_utc_ms` (integer equality)
- `PE.end_utc_ms - PE.start_utc_ms` == `S.slot_duration_sec * 1000` (duration consistency)

All comparisons are integer equality — no tolerance.

## Violation

Any of the following:

- `PE.start_utc_ms` != `S.start_at` as epoch ms (shifted start).
- `PE.end_utc_ms` != `S.end_at` as epoch ms (shifted end).
- `PE.end_utc_ms - PE.start_utc_ms` != `S.slot_duration_sec * 1000` (duration mismatch).

MUST be logged as a planning fault with fields: `block_id`, `schedule_item_id`, `expected_start_utc_ms`, `actual_start_utc_ms`, `expected_end_utc_ms`, `actual_end_utc_ms`.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_event_timeline.py::test_event_matches_schedule_item` — PE start/end equal SI start/end.
- `pkg/core/tests/contracts/playout/test_playlist_event_timeline.py::test_event_duration_equals_slot` — PE duration equals SI slot_duration_sec * 1000.

## Enforcement Evidence

- **Guard location:** Block expansion pipeline — the function that converts a ScheduleItem into a PlaylistEvent MUST propagate `start_at`/`end_at` without modification.
- **Error tag:** `INV-PLAYLIST-EVENT-TIMELINE-001-VIOLATED`
