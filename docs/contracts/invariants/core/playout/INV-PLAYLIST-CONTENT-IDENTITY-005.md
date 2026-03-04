# INV-PLAYLIST-CONTENT-IDENTITY-005 — Content events must reference the ScheduleItem's asset

Status: Invariant
Authority Level: Execution Intent
Derived From: PlayoutExecutionModel — Layer Ownership and Authority

## Purpose

Ensures execution intent cannot change editorial identity. A content-kind PlaylistEvent must play the same asset that the ScheduleItem specified. PlaylistEvent structures how content is presented (timing, splitting at semantic boundaries) but MUST NOT substitute a different asset. Editorial decisions belong to the scheduling layer.

## Guarantee

For every content-kind PlaylistEvent derived from a ScheduleItem:

```
playlist_event.asset_id == schedule_item.asset_id
```

## Preconditions

- The PlaylistEvent is of kind `content`.
- The PlaylistEvent references a `schedule_item_id`.

## Observability

For each content PlaylistEvent, verify that its `asset_id` matches the referenced ScheduleItem's `asset_id`. Any mismatch is a violation. Both asset IDs MUST be logged on failure.

## Deterministic Testability

Generate PlaylistEvents from a ScheduleItem with a known asset. Assert every content-kind event carries the same `asset_id`.

## Failure Semantics

**Generation fault.** The PlaylistEvent generator substituted a different asset, violating the editorial authority boundary. This is always a bug — PlaylistEvent has no authority to change what airs.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_identity.py::test_content_event_asset_matches_schedule_item`
