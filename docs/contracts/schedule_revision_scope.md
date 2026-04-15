# Schedule Revision Scope Contract

Authority Domain: Scheduling
Owner: Core scheduling runtime (`DslScheduleService` + revision writer)
Derived From: `LAW-IMMUTABILITY`, `LAW-CLOCK`, `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Overview

`ScheduleRevision` is the authoritative planned schedule for a specific broadcast day.
Active revisions define the schedule state consumed by runtime systems (`ChannelManager`, playlog horizon workers, and EPG readers).
Restart behavior MUST preserve existing schedule authority and only extend missing future schedule.

---

## Invariants

### 1) Per-day revision scope

Active schedule revisions are scoped to `(channel_id, broadcast_day)`.
A channel MAY hold multiple active revisions at once, with at most one active revision per broadcast day.
Publishing or writing a revision for one broadcast day MUST NOT alter active revision state for other broadcast days.

### 2) Past immutability

No schedule entry with `start_time < now` may be modified, regenerated, replaced, or superseded by runtime or restart flows.
Past schedule is sealed editorial history.

### 3) Forward-only generation

Schedule compilation and revision write flows may generate only time ranges where `time >= now`.
Historical ranges (`time < now`) MUST NOT be recompiled except in explicit recovery mode (out of scope for this contract).

### 4) Restart idempotency

Restart MUST NOT rebuild existing schedule days or alter existing schedule entries.
Restart may only:
- load canonical persisted schedule
- generate missing future schedule gaps

### 5) Revision replacement scope

When writing a new revision:
- only the existing active revision for the same `(channel_id, broadcast_day)` may be superseded
- active revisions for other broadcast days MUST remain unchanged

---

## Failure Conditions

The system is in violation if any of the following occur:

- Full-day recomputation of previously persisted broadcast days during normal startup/restart.
- Loss of active revisions for unrelated broadcast days when writing one broadcast day.
- Any mutation or replacement of entries where `start_time < now`.
- Restart-triggered schedule churn (new revisions for already persisted active days without explicit operator action).

---

## Required Tests

- `tests/contracts/test_schedule_revision_scope.py`

## Enforcement Evidence
TODO
