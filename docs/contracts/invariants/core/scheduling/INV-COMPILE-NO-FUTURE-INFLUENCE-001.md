# INV-COMPILE-NO-FUTURE-INFLUENCE-001 — No future-day influence on compilation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring the compilation of day D is a pure function of D's own inputs and D-1's boundary. If future-day data (D+1 or later) could influence D's compilation, then changing a future day would retroactively alter an already-compiled day, violating `LAW-IMMUTABILITY`.

## Guarantee

Schedule compilation for target day D MUST NOT depend on schedule data from day D+1 or any later day. The carry-in boundary for day D is derived from day D-1 only.

## Observability

If a future-loaded revision suppresses or alters the compilation of an earlier day, the resulting block timeline for the earlier day will differ from what it would produce in isolation — detectable by comparing outputs with and without future data loaded.

## Deterministic Testability

Compile day D with no future-day data loaded. Then compile day D again with day D+1 loaded. Both compilations MUST produce identical block timelines for day D. A future revision MUST NOT suppress or alter the target day's output.

## Failure Semantics

**Planning fault.** The compiler allowed future-day data to influence an earlier day's output, creating a hidden dependency that breaks immutability guarantees.

## Required Tests

- `pkg/core/tests/contracts/integration/test_integration_scheduling_authority.py`

## Enforcement Evidence

- `TestFutureContamination::test_future_revision_does_not_suppress_target_day` — future-loaded schedule data does not suppress compilation of earlier days
