# INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001 — Enricher failures are visible, never silent

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that enricher failures produce observable evidence. Without this guarantee, assets reach `ready` state with missing metadata (e.g. `interstitial_type`) and no record of why the enricher did not execute, forcing trial-and-error debugging.

## Guarantee

If a processor_id is resolved for a job's target_type, the corresponding enricher MUST either execute successfully OR produce a failed `ProcessorRun` record with an error message. The enricher MUST NOT be silently skipped.

## Preconditions

- The processor_id is present in `CAPABILITY_REGISTRY` for the job's `target_type`.
- The enricher class is registered in `ENRICHERS`.

## Observability

- `enricher_construction_failed` structured log event with processor_id, target_id, collection, and reason.
- `ProcessorRun` row with `status=failed` and `error_message` naming the construction failure.

## Deterministic Testability

1. Configure a processor pipeline that includes `interstitial-type` with an invalid collection name.
2. Execute the job.
3. Assert that a `ProcessorRun` record with `status=failed` exists for `interstitial-type`.
4. Assert that the structured log contains `enricher_construction_failed`.
5. Assert that no silent skip occurred (the enricher is not simply absent from the run records).

## Failure Semantics

**Planning fault.** A silently-skipped enricher produces assets with missing metadata that are invisible to pool resolution.

## Required Tests

- `pkg/core/tests/contracts/test_inv_enricher_must_execute_or_fail.py`

## Enforcement Evidence

TODO
