# INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 — ScheduleDay seam at carry-in boundary must not overlap or duplicate content

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

## Purpose

Governs the seam between consecutive ScheduleDays when a slot from the preceding day carries past the broadcast-day boundary. Without this invariant, the ScheduleDay generation service could schedule new content for the start of the next broadcast day while the carry-in slot is still occupying that interval — producing overlapping authorities over the same time window. Overlapping content authorities violate `LAW-GRID` (which requires non-overlapping, aligned slot boundaries) and `LAW-DERIVATION` (which requires each derived artifact to trace to a single upstream source, not to two competing slot origins).

## Guarantee

If a ScheduleDay contains a slot whose `end_utc` extends past the nominal broadcast-day boundary, then the next ScheduleDay MUST NOT schedule any slot whose `start_utc` is earlier than that carry-in slot's `end_utc`.

The effective scheduling window start for the next ScheduleDay MUST equal the `end_utc` of the carry-in slot.

Content MUST NOT be duplicated across the seam. The carry-in slot MUST appear in exactly one ScheduleDay and MUST NOT be re-created, re-attributed, or shadowed in the next.

## Preconditions

- Two consecutive ScheduleDays exist for the same channel.
- The earlier ScheduleDay contains at least one slot whose `end_utc` exceeds the broadcast-day start of the later ScheduleDay.

## Observability

The ScheduleDay generation service MUST read the preceding ScheduleDay's terminal slot boundary before opening the next day's scheduling window. A violation is any committed slot in the later ScheduleDay whose `start_utc` is less than the `end_utc` of the carry-in slot. Violation: log both ScheduleDay IDs, the carry-in slot ID and its `end_utc`, and the conflicting new slot ID and its `start_utc`.

## Deterministic Testability

Create a ScheduleDay for Monday with a final slot covering [05:00, 07:00] (60 minutes past the 06:00 broadcast-day boundary). Trigger generation of Tuesday's ScheduleDay. Assert Tuesday's first slot has `start_utc = 07:00`. Assert no Tuesday slot has `start_utc < 07:00`. Assert the carry-in slot ID appears only in Monday's ScheduleDay and is not referenced or duplicated in Tuesday's.

Invalid scenario: Tuesday schedules new content starting at 06:00 while the Monday carry-in runs until 07:00 — this is a violation of this invariant.

## Failure Semantics

**Planning fault.** The ScheduleDay generation service failed to read or honor the carry-in boundary when opening the next day's scheduling window.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvScheduledaySeamNoOverlap001`

## Enforcement Evidence

- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `validate_scheduleday_seam()` computes preceding day's last slot absolute end, compares against new day's first slot start, raises `ValueError` with `INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001-VIOLATED` tag if overlap detected
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.store()` calls `validate_scheduleday_seam()` inside lock when `programming_day_start_hour` is configured
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.force_replace()` calls `validate_scheduleday_seam()` inside lock when `programming_day_start_hour` is configured
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `_compute_effective_start()` computes carry-in adjusted start for contiguity validation, ensuring `validate_scheduleday_contiguity()` accepts days with carry-in from the preceding day
- Error tag: `INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001-VIOLATED`
