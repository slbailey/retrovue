# INV-COMPILE-NO-HORIZON-GLOBAL-001 — No horizon-global carry-in

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring carry-in is scoped to the immediately preceding broadcast day, not accumulated from a global variable spanning the loaded horizon. A global accumulator creates hidden dependencies between non-adjacent days, making compilation results sensitive to which days happen to be loaded.

## Guarantee

The carry-in value for a target day MUST NOT be derived from a global variable that accumulates across the entire loaded horizon. It MUST be scoped to the immediately preceding broadcast day.

## Observability

If carry-in is derived from a global accumulator, loading different subsets of the horizon will produce different carry-in values for the same target day — detectable by comparing outputs across different load sets.

## Deterministic Testability

Compile day D with D-1 loaded and a future day also loaded. Verify that the carry-in for day D is derived solely from D-1 and that the future day's data does not cross-contaminate D's carry-in value.

## Failure Semantics

**Planning fault.** A horizon-global carry-in accumulator makes compilation results depend on the set of loaded days rather than the strict D-1 → D chain, producing non-deterministic output.

## Required Tests

- `server/tests/contracts/integration/test_integration_scheduling_authority.py`

## Enforcement Evidence

- `TestHorizonGlobalCarryIn::test_d_minus_1_and_future_day_do_not_cross_contaminate` — carry-in is derived from D-1 only, not from a global horizon accumulator
