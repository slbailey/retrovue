# INV-VALIDATOR-RESULT-PERSISTENCE-001 — Validator results persisted in canonical shape

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring validator results are persisted in the same canonical shape defined by `INV-VALIDATOR-OUTPUT-SHAPE-001`. Without persistence, validation outcomes are ephemeral — operators cannot audit why an asset was accepted or rejected, and re-validation cannot compare against prior runs.

## Guarantee

Every validator result that gates an asset state transition MUST be persisted. The persisted record MUST conform to the canonical shape defined by `INV-VALIDATOR-OUTPUT-SHAPE-001` without transformation or lossy compression. The persisted record MUST include the asset identifier, the timestamp of the validation run, and the full structured result. Retrieval of a persisted result MUST return the identical shape that was produced at validation time.

## Preconditions

- The validator has produced a result conforming to `INV-VALIDATOR-OUTPUT-SHAPE-001`.
- The persistence layer is available.

## Observability

- A validator result that is produced but not persisted is a violation. Detection occurs when a state transition has no corresponding persisted validation record.
- A persisted result that does not round-trip to the canonical shape is a violation.

## Deterministic Testability

1. Run a validator that produces a valid result. Assert a persisted record exists with the correct asset id, timestamp, and full result shape.
2. Run a validator that produces a failure result. Assert the failure is persisted with errors and per-validator statuses intact.
3. Retrieve a persisted result. Assert it round-trips to the identical canonical shape (no field loss, no type coercion).
4. Simulate a state transition without a persisted validation record. Assert the transition is rejected.
5. Assert persisted results include warnings, not just errors (no lossy compression of the warning list).

## Failure Semantics

**Planning fault.** Unpersisted validation results make asset acceptance decisions unauditable. Operators cannot determine why an asset reached `ready` state or diagnose validation regressions.

## Required Tests

- `server/tests/contracts/ingest/test_inv_validator_result_persistence.py`

## Enforcement Evidence

TODO
