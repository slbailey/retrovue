# INV-SCHEDULEREVISION-IMMUTABLE-001 — ScheduleItems within an active ScheduleRevision must not be mutated

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

## Purpose

Protects the derivation chain from post-hoc corruption. PlaylistEvents are derived from ScheduleItems within the active ScheduleRevision. If those ScheduleItems could be mutated after activation, downstream PlaylistEvents and ExecutionSegments would silently diverge from the editorial truth they were derived from — directly violating `LAW-DERIVATION`. The active revision is the editorial ground truth for a channel's broadcast_day; its integrity is the foundation of every downstream artifact.

## Guarantee

Once a ScheduleRevision transitions to `active`, its ScheduleItems MUST NOT be mutated. Specifically:

**Disallowed operations on ScheduleItems within an active revision:**
- Updating `start_time` (time reassignment)
- Changing asset assignments (`asset_id` / `asset_uri` / resolved material reference)
- Deleting a ScheduleItem from the revision
- Adding a new ScheduleItem to an already-active revision

**Allowed operations:**
- Creating a **new** ScheduleRevision in `draft` state with different ScheduleItems.
- **Activating** the new revision, which atomically supersedes the current active revision.

Schedule changes are expressed as new revisions, never as mutations to active revisions.

## Preconditions

- A ScheduleRevision exists with `state=active` for a given channel and broadcast_day.
- The ScheduleRevision contains one or more ScheduleItems.

## Observability

Application-layer enforcement at the store level. Any attempt to update or delete a ScheduleItem whose parent ScheduleRevision has `state=active` MUST be rejected with tag `INV-SCHEDULEREVISION-IMMUTABLE-001-VIOLATED`, including the ScheduleItem ID, the revision ID, and the attempted operation. Silent mutation is unconditionally prohibited.

## Deterministic Testability

1. Create a ScheduleRevision with ScheduleItems. Activate the revision.
2. Attempt to update a ScheduleItem's `start_time` — assert rejected with `INV-SCHEDULEREVISION-IMMUTABLE-001-VIOLATED`.
3. Attempt to update a ScheduleItem's `asset_id` — assert rejected.
4. Attempt to delete a ScheduleItem from the active revision — assert rejected.
5. Create a new revision with different ScheduleItems. Activate it. Assert the original revision transitions to `superseded` and its ScheduleItems remain unchanged.

No real-time waits required.

## Failure Semantics

**Planning fault** if the system mutated ScheduleItems within an active revision without creating a new revision. Indicates a logic error in the scheduler or a missing enforcement guard in the store layer. **Operator fault** if a direct database edit bypassed application-layer enforcement.

## Required Tests

- `tests/contracts/schedule_revision/test_schedule_revision_immutable.py`

## Enforcement Evidence

TODO
