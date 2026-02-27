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

- `pkg/core/tests/contracts/test_inv_scheduleday_derivation_traceable.py`

## Enforcement Evidence

TODO
