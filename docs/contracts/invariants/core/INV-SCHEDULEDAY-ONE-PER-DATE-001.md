# INV-SCHEDULEDAY-ONE-PER-DATE-001 — Exactly one ScheduleDay per channel per broadcast date

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

## Purpose

Prevents multiple conflicting authoritative schedules for the same channel-date. Two ScheduleDays for the same `(channel_id, programming_day_date)` create an ambiguous derivation root: downstream artifacts (ExecutionEntry, AsRun) cannot determine which is the canonical upstream record, violating `LAW-DERIVATION`.

## Guarantee

At any point in time, at most one ResolvedScheduleDay MUST exist for a given `(channel_id, programming_day_date)` pair. Duplicate insertion MUST be rejected. Replacement MUST be atomic via `force_replace()` — the old record is removed and the new record is installed in a single critical section.

## Preconditions

- None. This invariant holds unconditionally — including during force-regeneration and manual override workflows.

## Observability

Enforced at the `ResolvedScheduleStore.store()` boundary. Any insert for a `(channel_id, programming_day_date)` that already has a record MUST raise `ValueError` with tag `INV-SCHEDULEDAY-ONE-PER-DATE-001-VIOLATED`. Force-regeneration uses `force_replace()` which atomically swaps the record under lock.

## Deterministic Testability

Materialize a ResolvedScheduleDay for (channel=C, date=D). Attempt to store a second ResolvedScheduleDay for the same (C, D). Assert the store raises ValueError with the invariant tag. Then verify `force_replace()` atomically swaps the record. No real-time waits required.

## Failure Semantics

**Planning fault.** The generation service attempted to create a duplicate ScheduleDay without first checking `exists()`. This indicates a logic error in the generation or regeneration workflow.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvScheduledayOnePerDate001`

## Enforcement Evidence

- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.store()` rejects duplicates, `force_replace()` atomically swaps
- `pkg/core/src/retrovue/runtime/schedule_types.py` — `ResolvedScheduleStore` protocol defines `store()`, `force_replace()`
- `pkg/core/src/retrovue/runtime/schedule_manager.py` — `resolve_schedule_day()` guards with `exists()` check before calling `store()`
- Error tag: `INV-SCHEDULEDAY-ONE-PER-DATE-001-VIOLATED`
