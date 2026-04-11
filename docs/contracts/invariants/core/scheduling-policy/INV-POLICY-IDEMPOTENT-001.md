# INV-POLICY-IDEMPOTENT-001 — Same inputs produce same violations

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION` by ensuring policy evaluation is deterministic. Non-deterministic evaluation would break derivation traceability — the same schedule inputs could produce different compilation results across runs.

## Guarantee

Given identical `candidate_assets`, `policy`, and `context`, `evaluate_scheduling_policies` MUST return identical eligible assets and identical violations. Evaluation MUST NOT depend on call order, global state, random sources, or wall-clock time not passed via `context`.

## Preconditions

None. This invariant holds unconditionally for all valid inputs.

## Observability

Call `evaluate_scheduling_policies` twice with the same inputs and compare outputs. Any divergence is a violation.

## Deterministic Testability

Invoke `evaluate_scheduling_policies` N times (N >= 3) with identical frozen inputs. Assert that all N results are equal. Vary candidate list ordering between invocations and assert that eligible assets and violations are identical regardless of input order.

## Failure Semantics

Planning fault. Non-deterministic policy evaluation means schedule compilation is non-reproducible, breaking `LAW-DERIVATION` traceability guarantees.

## Required Tests

- `server/tests/contracts/test_scheduling_policies.py`

## Enforcement Evidence

TODO
