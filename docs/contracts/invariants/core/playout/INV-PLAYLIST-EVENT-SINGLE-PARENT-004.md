# INV-PLAYLIST-EVENT-SINGLE-PARENT-004

## Behavioral Guarantee

Every PlaylistEvent must reference exactly one ScheduleItem. A PlaylistEvent without a parent ScheduleItem is an orphan with no editorial authority — it has no constitutionally-authorized reason to exist in the playout timeline.

## Authority Model

ScheduleItem is the editorial anchor. PlaylistEvent is a derived execution artifact. The derivation chain MUST be traceable: every PlaylistEvent was expanded from exactly one ScheduleItem, and that relationship MUST be recorded.

## Boundary / Constraint

Given a PlaylistEvent `PE`:

- `PE.schedule_item_id` MUST NOT be null.
- `PE.schedule_item_id` MUST reference a valid ScheduleItem.
- The relationship is many-to-one: each PlaylistEvent references exactly one ScheduleItem. Each ScheduleItem produces exactly one PlaylistEvent (1:1 in practice, enforced by deterministic block identity).

## Violation

Any of the following:

- `PE.schedule_item_id` is null (orphaned PlaylistEvent).
- `PE.schedule_item_id` references a non-existent ScheduleItem (dangling reference).

MUST be logged as a planning fault with fields: `block_id`, `schedule_item_id` (or `null`).

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_event_parent.py::test_playlist_event_has_schedule_item` — every PE has a non-null schedule_item_id.

## Enforcement Evidence

- **Guard location:** Block expansion pipeline — `schedule_item_id` MUST be set during PlaylistEvent creation.
- **Database constraint:** `schedule_item_id` column NOT NULL with FK to `schedule_items.id`.
- **Error tag:** `INV-PLAYLIST-EVENT-SINGLE-PARENT-004-VIOLATED`
