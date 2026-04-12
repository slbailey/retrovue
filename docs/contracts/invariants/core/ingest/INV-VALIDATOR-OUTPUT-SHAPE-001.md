# INV-VALIDATOR-OUTPUT-SHAPE-001 — Validator outputs are structured and deterministic

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring validator results are traceable, machine-readable, and stable across versions. Without a canonical output shape, downstream consumers (persistence, diagnostics, operator CLI) must each parse ad-hoc formats, creating silent breakage when validators change.

## Guarantee

Every validator run MUST produce a structured result object with a canonical shape containing: a top-level `status` field (`validated` or `failed`), an `errors` list, a `warnings` list, and a `validators` map keyed by validator name with per-validator status (`pass`, `fail`, or `warn`). Each error and warning entry MUST include a machine-readable `code`, the originating `validator` name, and a human-readable `message`.

## Preconditions

- The validator is registered and invoked through the validator pipeline.

## Observability

Validator results conform to the canonical shape at construction time. A result object that omits required fields or uses non-canonical status values MUST raise `ValueError` with tag `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED`.

## Deterministic Testability

1. Construct a validator result with all required fields populated. Assert it is accepted.
2. Construct a result missing the `status` field. Assert `ValueError` with the invariant tag.
3. Construct a result with an invalid status value (e.g. `"partial"`). Assert rejection.
4. Construct an error entry missing the `code` field. Assert rejection.
5. Construct an error entry missing the `validator` field. Assert rejection.
6. Assert the shape is additive-only: adding extra fields to a valid result MUST NOT cause rejection.

## Failure Semantics

**Planning fault.** A malformed validator result produces uninterpretable output that breaks persistence, diagnostics, and operator visibility into validation failures.

## Required Tests

- `server/tests/contracts/ingest/test_inv_validator_output_shape.py`

## Enforcement Evidence

TODO
