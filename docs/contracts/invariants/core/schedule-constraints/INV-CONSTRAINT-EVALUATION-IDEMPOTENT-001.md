# INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001 — Constraint evaluation idempotency

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Guarantees that constraint evaluation is a pure function. Non-deterministic constraint evaluation would produce different violation sets on repeated runs, making it impossible to reliably validate or reconcile schedules. Violation risks `LAW-DERIVATION` by breaking the deterministic derivation chain from plan to compiled schedule.

## Guarantee

Constraint evaluation MUST be a pure function: given identical inputs (zones, constraints, compiled blocks), evaluation MUST produce an identical violation set. Constraint functions MUST have no side effects and MUST NOT depend on external state, wall-clock time, or random values.

## Preconditions

None. This invariant applies unconditionally to all constraint evaluation functions.

## Observability

Invoke any constraint evaluation function twice with identical inputs. The returned violation sets MUST be equal (same items in same order).

## Deterministic Testability

Call each constraint check function (blackout, adjacency, content restriction) twice with the same inputs. Assert that the returned violation lists are identical. No real-time waits required.

## Failure Semantics

**Planning fault.** Non-deterministic constraint evaluation indicates a defect in the constraint implementation.

## Required Tests

- `server/tests/contracts/scheduling/test_schedule_constraints.py::TestInvConstraintEvaluationIdempotent001`

## Enforcement Evidence

- All functions in `server/src/retrovue/scheduling/schedule_constraints.py` are pure functions: frozen dataclass inputs, no side effects, no external state dependencies
