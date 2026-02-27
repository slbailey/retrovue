# INV-ASRUN-TRACEABILITY-001 — Every AsRun entry must be traceable through the full derivation chain

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-DERIVATION`

## Purpose

Enforces `LAW-DERIVATION` at its terminus — the observed broadcast record. Without a complete chain from AsRun back to SchedulePlan, it is impossible to audit whether what aired was constitutionally authorized. A broken traceability chain means the system cannot distinguish a legal broadcast from a content injection outside the constitutional pipeline. This invariant makes `LAW-DERIVATION` verifiable after the fact.

## Guarantee

Every AsRun entry must satisfy all of the following:

1. References a PlaylogEvent (`playlog_event_id` is set).
2. That PlaylogEvent references a Playlist entry.
3. That Playlist entry references a ScheduleDay.
4. That ScheduleDay references a SchedulePlan (or carries `is_manual_override=true` with a superseded-record reference).

AsRun entries created by operator override are exempt from conditions 2–4 but must still reference the PlaylogEvent override record that authorized the broadcast.

## Preconditions

- Playback of an asset has completed and an AsRun record is being created.

## Observability

At AsRun record creation, the application layer must verify the PlaylogEvent reference is present and non-null. The full chain can be traversed via audit query:

```sql
SELECT a.id, p.id, pl.id, sd.id, sp.id
FROM asrun_log a
JOIN playlog_events p ON a.playlog_event_id = p.id
JOIN playlist_entries pl ON p.playlist_entry_id = pl.id
JOIN broadcast_schedule_days sd ON pl.schedule_day_id = sd.id
LEFT JOIN schedule_plans sp ON sd.plan_id = sp.id
WHERE sp.id IS NULL AND sd.is_manual_override = false
```

Any row returned is a violation.

## Deterministic Testability

Create an AsRun record without a `playlog_event_id`. Assert creation is rejected. Separately, create an AsRun record with a valid PlaylogEvent reference and trace the full chain; assert no link in the chain is null (unless manual override). No real-time waits required.

## Failure Semantics

**Runtime fault** if the AsRun service failed to record the PlaylogEvent reference. **Operator fault** if a manual database intervention broke the chain post-hoc. Either way the record is a violation.

## Required Tests

- `pkg/core/tests/contracts/test_inv_asrun_traceability.py`

## Enforcement Evidence

TODO
