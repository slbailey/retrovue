# INV-BREAK-BUDGET-DERIVED-001 — Break budget is derived, not fixed

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

## Purpose

Protects `LAW-GRID` by ensuring break time is the arithmetic residual of the grid slot after content and presentation are accounted for. A fixed break budget would either waste grid time or overflow it, violating grid conservation.

## Guarantee

Break budget MUST equal `scheduled_duration - content_duration - presentation_duration`. The budget MUST NOT be set independently of these three values.

## Preconditions

Content duration and presentation duration are resolved before break budget calculation. Grid slot allocation is known from the schedule.

## Observability

The compiler logs the derived break budget alongside its three input values. Any mismatch between the logged budget and the arithmetic difference is a violation.

## Deterministic Testability

Construct a block with known `scheduled_duration`, `content_duration`, and `presentation_duration`. Verify `break_budget == scheduled_duration - content_duration - presentation_duration` exactly.

## Failure Semantics

**Planning fault.** An incorrectly derived break budget causes either time underflow (gaps in the block) or time overflow (segment conservation violation).

## Required Tests

- `pkg/core/tests/contracts/test_timeline_compilation_templates.py`

## Enforcement Evidence

TODO
