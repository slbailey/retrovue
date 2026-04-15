## Overview

`ChannelActiveRevision` is the canonical pointer authority for selecting the
active `ScheduleRevision` for a `(channel_id, broadcast_day)`.
The pointer MUST always reference the canonical active revision for that same
channel and day so runtime authority loading can deterministically preload
timeline state at startup.

## Invariants

### 1) Canonical pointer target

For every `(channel_id, broadcast_day)`, `ChannelActiveRevision.schedule_revision_id`
MUST reference a `ScheduleRevision` that:

- exists
- has the same `channel_id`
- has the same `broadcast_day`
- has `status='active'`

### 2) No superseded pointer targets

`ChannelActiveRevision` MUST NOT point to revisions in non-canonical states,
including `superseded`, `draft`, or any state other than canonical active.

### 3) Pointer/status atomicity

When publishing a new canonical revision for a day, pointer update and revision
status transition MUST leave a consistent persisted final state.
There MUST be no durable state where the pointer remains on an old revision
that has already been superseded.

### 4) Prewarm-safe authority

A valid persisted schedule MUST remain preloadable at startup.
Prewarm MUST NOT fail solely because writer-side persistence left
`ChannelActiveRevision` pointing at a non-canonical target.

### 5) Single canonical day authority

For each `(channel_id, broadcast_day)`, there MUST be exactly one canonical
active revision selected by pointer authority.
Duplicate or ambiguous canonical states are invariant violations.

### 6) Restart-safe pointer integrity

After restart, runtime authority loading MUST resolve the canonical revision
through `ChannelActiveRevision` without repair-by-guessing or fallback
inference from non-pointer scans.

## Failure conditions

- `ChannelActiveRevision` points to a `superseded` revision.
- `ChannelActiveRevision` points to a revision with mismatched day or channel.
- Startup prewarm fails because pointer target is non-canonical.
- Writer publish flow leaves pointer stale after superseding previous revision.
- Runtime must infer canonical authority because pointer integrity is broken.

## Required tests

- `tests/contracts/test_channel_active_revision_integrity.py::test_pointer_targets_active_revision`
  - Invariants: Canonical pointer target.
- `tests/contracts/test_channel_active_revision_integrity.py::test_pointer_to_superseded_revision_is_rejected`
  - Invariants: No superseded pointer targets; Prewarm-safe authority.
- `tests/contracts/test_channel_active_revision_integrity.py::test_publish_transition_keeps_pointer_canonical`
  - Invariants: Pointer/status atomicity; Single canonical day authority.
- `tests/contracts/test_channel_active_revision_integrity.py::test_prewarm_succeeds_with_canonical_pointer`
  - Invariants: Canonical pointer target; Prewarm-safe authority.
- `tests/contracts/test_channel_active_revision_integrity.py::test_restart_preserves_canonical_pointer_resolution`
  - Invariants: Restart-safe pointer integrity.
- `tests/contracts/test_channel_active_revision_integrity.py::test_pointer_channel_or_day_mismatch_is_rejected`
  - Invariants: Canonical pointer target; No superseded pointer targets.
