# INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 — Every ScheduleDay must trace to its generating SchedulePlan

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Enforces `LAW-DERIVATION` at the ScheduleDay layer. A ScheduleDay that cannot be traced to an active SchedulePlan is constitutionally unanchored — it represents content introduced outside the editorial authority chain, violating `LAW-CONTENT-AUTHORITY`. Without this link, audit and cross-layer traceability (AsRun → ... → SchedulePlan) is broken.

## Guarantee

Every ScheduleDay must satisfy one of these two conditions:

1. `plan_id` references an active SchedulePlan that was used to generate it, **or**
2. `is_manual_override = true` and the record contains a reference to the ScheduleDay it supersedes.

A ScheduleDay with `plan_id = NULL` and `is_manual_override = false` MUST NOT exist.

## Preconditions

- ScheduleDay has been persisted.

## Observability

Audit query: `SELECT * FROM broadcast_schedule_days WHERE plan_id IS NULL AND is_manual_override = false`. Any result is a violation. MUST be checked at generation time (application layer enforcement) before commit.

## Deterministic Testability

Attempt to insert a ScheduleDay with `plan_id = NULL` and `is_manual_override = false` via the application layer. Assert insertion is rejected. Separately, insert with `is_manual_override = true` (and a superseded record reference); assert insertion is accepted. No real-time waits required.

## Failure Semantics

**Planning fault.** The ScheduleDay generation service produced an artifact outside the constitutional derivation chain. Indicates a logic error in the generation workflow.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvScheduledayDerivationTraceable001`

## Enforcement Evidence

- `pkg/core/src/retrovue/runtime/schedule_types.py` — `ResolvedScheduleDay.plan_id: str | None = None` field added to frozen dataclass
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `_enforce_derivation_traceability()` checks `plan_id is None and not is_manual_override` and raises `ValueError` with `INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001-VIOLATED` tag
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.store()` calls `_enforce_derivation_traceability()` before commit when `enforce_derivation_traceability=True`
- `pkg/core/src/retrovue/runtime/schedule_manager_service.py` — `InMemoryResolvedStore.force_replace()` calls `_enforce_derivation_traceability()` before commit when `enforce_derivation_traceability=True`
- Error tag: `INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001-VIOLATED`
