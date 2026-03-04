# INV-PLAYLIST-TIME-ANCHOR-006 — First PlaylistEvent must start at ScheduleItem start

Status: Invariant
Authority Level: Execution Intent
Derived From: PlayoutExecutionModel — Timeline Alignment

## Purpose

Ensures that execution intent is anchored to the editorial schedule. The first PlaylistEvent derived from a ScheduleItem must begin exactly at the ScheduleItem's start time. Any drift means the execution timeline has detached from the editorial timeline — content starts early (bleeding into the previous slot) or late (creating a gap).

## Guarantee

For the first PlaylistEvent derived from a ScheduleItem (ordered by `start_utc_ms`):

```
first_event.start_utc_ms == schedule_item.start_at_utc_ms
```

## Preconditions

- At least one PlaylistEvent has been generated for the ScheduleItem.
- `start_at_utc_ms` is derived from the ScheduleItem's `start_at` timestamp.

## Observability

After PlaylistEvent generation, compare the earliest event's `start_utc_ms` with the ScheduleItem's start time. Any delta is a violation. Both timestamps MUST be logged on failure.

## Deterministic Testability

Generate PlaylistEvents from a ScheduleItem with a known start time. Assert the first event's `start_utc_ms` matches exactly.

## Failure Semantics

**Generation fault.** The PlaylistEvent generator anchored execution intent to the wrong time, detaching from the editorial schedule.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_timeline_continuity.py::test_first_event_anchored_to_schedule_item_start`
