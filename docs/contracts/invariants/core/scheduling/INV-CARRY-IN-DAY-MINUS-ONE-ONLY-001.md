# INV-CARRY-IN-DAY-MINUS-ONE-ONLY-001 — Carry-in from D-1 only

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by constraining the carry-in computation to a strict D-1 → D relationship. The prior-day boundary used for carry-in MUST come from the immediately preceding day's last block end time. Deriving carry-in from any other source (D-2, a global accumulator, or a default) when D-1 has a committed schedule would silently corrupt block boundaries.

## Guarantee

The prior-day boundary used in carry-in computation for day D MUST be derived from day D-1's last block end time. If D-1 has no committed schedule, the boundary is zero only if D-1 is genuinely unprogrammed.

## Preconditions

- Day D is being compiled with programming assigned.
- Day D-1 may or may not have a committed schedule.

## Observability

If carry-in is derived from a source other than D-1, block boundaries for day D will differ from what D-1's output would produce — detectable by comparing D's first block start against D-1's last block end.

## Deterministic Testability

Compile day D-1. Record its last block end time. Compile day D. Verify D's carry-in matches D-1's last block end time. Also verify that loading additional days does not alter the carry-in value for D.

## Failure Semantics

**Planning fault.** Incorrect carry-in derivation produces wrong block boundaries for day D and all subsequent days in the chain, creating gaps or overlaps in the timeline.

## Required Tests

- `pkg/core/tests/contracts/integration/test_integration_scheduling_authority.py`

## Enforcement Evidence

- `TestHorizonGlobalCarryIn::test_d_minus_1_and_future_day_do_not_cross_contaminate` — carry-in for D is derived from D-1 only, not cross-contaminated by other loaded days
