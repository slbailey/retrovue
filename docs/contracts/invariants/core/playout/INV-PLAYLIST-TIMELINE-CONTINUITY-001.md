# INV-PLAYLIST-TIMELINE-CONTINUITY-001 — PlaylistEvents must form a continuous timeline

Status: Invariant
Authority Level: Execution Intent
Derived From: PlayoutExecutionModel — Timeline Alignment

## Purpose

Ensures a channel's playout timeline has no undefined intervals. PlaylistEvents tile the timeline without gaps or overlaps. A gap means AIR has no execution intent for that interval — the channel falls silent. An overlap means two conflicting instructions occupy the same wall-clock time — the channel enters an undefined state.

## Guarantee

For any channel within the active playout horizon, the sequence of PlaylistEvents sorted by `start_utc_ms` must satisfy:

```
event[i].start_utc_ms + event[i].duration_ms == event[i+1].start_utc_ms
```

for all adjacent pairs. No gaps. No overlaps.

## Preconditions

- PlaylistEvents have been generated for the channel's active playout horizon.
- The sequence is ordered by `start_utc_ms`.

## Observability

After PlaylistEvent generation for a horizon window, compute adjacency for all consecutive pairs. Any pair where `event[i].end != event[i+1].start` is a violation. The gap or overlap interval (start, end, delta_ms) MUST be logged. Generation MUST NOT emit a horizon window with discontinuities.

## Deterministic Testability

Generate PlaylistEvents from a known ScheduleItem sequence. Assert that every adjacent pair satisfies the continuity equation. Test both the no-gap and no-overlap conditions independently.

## Failure Semantics

**Generation fault.** The PlaylistEvent generator produced a timeline with discontinuities. This is always a bug in the generation logic — never a valid state.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_timeline_continuity.py::test_playlist_events_have_no_gaps`
- `pkg/core/tests/contracts/playout/test_playlist_timeline_continuity.py::test_playlist_events_have_no_overlaps`
