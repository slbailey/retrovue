# INV-PLAYLIST-DURATION-COVERAGE-004 — PlaylistEvents must cover the full slot duration

Status: Invariant
Authority Level: Execution Intent
Derived From: PlayoutExecutionModel — Timeline Alignment

## Purpose

Ensures that the total wall-clock time of all PlaylistEvents derived from a ScheduleItem exactly equals the ScheduleItem's slot duration. Under-coverage leaves a gap in the timeline (violating INV-PLAYLIST-TIMELINE-CONTINUITY-001). Over-coverage means events bleed into a neighboring ScheduleItem's time.

## Guarantee

For all PlaylistEvents derived from a single ScheduleItem:

```
sum(event.duration_ms for event in events) == schedule_item.slot_duration_ms
```

This sum includes all event kinds: content, ad, promo, pad, and override.

## Preconditions

- PlaylistEvents have been generated for the ScheduleItem.
- `slot_duration_ms` is known from the ScheduleItem (derived from `slot_duration_sec * 1000`).

## Observability

After PlaylistEvent generation for a ScheduleItem, sum all event durations. Any delta from the slot duration is a violation. The expected and actual totals MUST be logged on failure.

## Deterministic Testability

Generate PlaylistEvents from a ScheduleItem with a known slot duration (e.g., 30 minutes = 1,800,000 ms). Assert that the sum of all generated event durations equals 1,800,000 ms exactly.

## Failure Semantics

**Generation fault.** The PlaylistEvent generator produced events that do not fill the slot. Either content duration was miscalculated, padding was omitted, or ad/promo durations were incorrect.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_duration_coverage.py::test_playlist_events_cover_schedule_item_duration`
