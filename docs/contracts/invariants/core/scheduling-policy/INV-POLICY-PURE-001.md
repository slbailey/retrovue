# INV-POLICY-PURE-001 — Policy evaluation is pure

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-ELIGIBILITY` and `LAW-CONTENT-AUTHORITY` by ensuring scheduling policy evaluation has no hidden side effects that could corrupt scheduling state or introduce non-deterministic eligibility decisions.

## Guarantee

`evaluate_scheduling_policies` and all per-rule evaluation functions MUST NOT mutate any input. They MUST NOT perform I/O, database queries, or filesystem access. All state needed for evaluation MUST be passed as arguments.

## Preconditions

Policy evaluation functions exist and are callable with the contracted argument signatures.

## Observability

Static analysis or AST inspection confirms no I/O imports or mutation calls within the policy evaluation module. Runtime: wrapping inputs in frozen containers before evaluation and asserting equality after evaluation detects mutation.

## Deterministic Testability

Freeze all inputs before calling `evaluate_scheduling_policies`. Assert that inputs are byte-identical after the call returns. Verify that the module contains no imports of `os`, `io`, `pathlib`, `socket`, `requests`, `sqlalchemy`, or any database driver.

## Failure Semantics

Planning fault. A policy function that mutates state or performs I/O produces unreliable eligibility decisions that may silently corrupt downstream scheduling artifacts.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_policies.py`

## Enforcement Evidence

TODO
