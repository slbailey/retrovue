# INV-REVISION-NONEMPTY-PROGRAMMED-001 — Revision non-empty guard

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that an active ScheduleRevision for a non-dark programmed day always contains editorial content. A zero-item revision on a programmed day is a contract violation — the schedule compiler MUST produce at least one ScheduleItem for any day with programming.

## Guarantee

An active ScheduleRevision for a non-dark programmed day MUST contain at least one ScheduleItem. Persisting a zero-item revision on a programmed day is a contract violation.

## Observability

Compilation output is validated before persistence. A zero-item revision triggers a guard error with the channel, broadcast day, and revision context.

## Deterministic Testability

Compile a programmed day through the normal scheduling pipeline. Verify the resulting revision contains at least one ScheduleItem. Attempt to construct a zero-item revision for a programmed day and verify the guard rejects it.

## Failure Semantics

**Planning fault.** The schedule compiler produced an empty result for a day that should have content, indicating a bug in compilation logic or DSL interpretation.

## Required Tests

- `pkg/core/tests/contracts/integration/test_integration_scheduling_authority.py`

## Enforcement Evidence

- `TestRevisionNonemptyGuard::test_normal_compile_produces_nonempty_revision` — baseline: compiling a programmed day produces a non-empty revision
