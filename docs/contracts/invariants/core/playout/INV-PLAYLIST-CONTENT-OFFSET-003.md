# INV-PLAYLIST-CONTENT-OFFSET-003 — Content events must preserve content order

Status: Invariant
Authority Level: Execution Intent
Derived From: PlayoutExecutionModel — Layer Ownership and Authority

## Purpose

Ensures movie and episode continuity across content PlaylistEvents derived from the same ScheduleItem. When a program is split by semantic boundaries (e.g., ad breaks), the content events must resume exactly where the previous content event left off. No rewinds. No skips. The viewer sees the program in order.

## Guarantee

For content-kind PlaylistEvents derived from the same ScheduleItem, ordered by `start_utc_ms`:

```
offset_ms[n+1] == offset_ms[n] + duration_ms[n]
```

The first content event starts at `offset_ms = 0` (or at the ScheduleItem's specified entry offset for join-in-progress scenarios). Each subsequent content event resumes exactly where the previous one ended.

## Preconditions

- Multiple content-kind PlaylistEvents exist for a single ScheduleItem (i.e., semantic splits occurred).
- Events are ordered by `start_utc_ms`.

## Observability

For each ScheduleItem with multiple content events, verify the offset chain. Any discontinuity (gap or overlap in offset space) is a violation. The expected and actual offset values MUST be logged on failure.

## Deterministic Testability

Generate PlaylistEvents from a ScheduleItem with known ad break markers at specific offsets. Assert the content events form a contiguous offset chain covering the full program duration.

## Failure Semantics

**Generation fault.** The PlaylistEvent generator miscalculated content offsets, producing a rewind or skip in the program timeline.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_content_offsets.py::test_content_offsets_increase_monotonically`
- `pkg/core/tests/contracts/playout/test_playlist_content_offsets.py::test_content_events_cover_asset_in_order`
