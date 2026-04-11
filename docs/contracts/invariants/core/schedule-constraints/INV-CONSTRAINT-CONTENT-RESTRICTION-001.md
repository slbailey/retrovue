# INV-CONSTRAINT-CONTENT-RESTRICTION-001 — Content time-window restrictions

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Enforces time-of-day restrictions on classified content (e.g. watershed rules restricting mature content to late-night hours). Content restriction constraints prevent operator scheduling errors where age-gated or classified material appears outside its permitted broadcast window. Violation risks `LAW-CONTENT-AUTHORITY` by producing a schedule that breaches declared content policy.

## Guarantee

Content matching a restricted classification MUST NOT appear in the schedule outside its allowed time window. An allowed window is defined by start time, end time, and optional day-of-week filters, all in broadcast-day-relative coordinates.

## Preconditions

- At least one content restriction constraint is defined for the channel or plan.
- The scheduled content has a classification matching the constraint.
- The constraint's day-of-week filter (if any) includes the day being validated.

## Observability

At plan-edit or compilation time, each scheduled block with classified content is checked against all active content restriction constraints. Any block whose start time falls outside the allowed window produces a structured violation identifying the block, its classification, the allowed window, and the constraint reason.

## Deterministic Testability

Construct a plan with a zone at 14:00-16:00 containing an asset classified "mature". Define a content restriction allowing "mature" only between 21:00-06:00. Assert that validation raises a content restriction violation. Verify that the same asset scheduled within the allowed window passes. No real-time waits required.

## Failure Semantics

**Planning fault.** The operator scheduled restricted content outside its allowed broadcast window. System MUST reject the conflicting schedule configuration.

## Required Tests

- `server/tests/contracts/scheduling/test_schedule_constraints.py::TestInvConstraintContentRestriction001`

## Enforcement Evidence

- `server/src/retrovue/scheduling/schedule_constraints.py` — `check_content_restriction_constraints()`
- Error tag: `INV-CONSTRAINT-CONTENT-RESTRICTION-001-VIOLATED`
