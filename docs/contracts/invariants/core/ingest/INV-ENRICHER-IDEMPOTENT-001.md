# INV-ENRICHER-IDEMPOTENT-001 — Enrichers are idempotent and version-tolerant

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring enricher re-execution does not corrupt asset metadata or produce divergent results. Without idempotency, retries after partial failure, version upgrades, or operator-triggered re-enrichment create assets with inconsistent or duplicated metadata.

## Guarantee

Running an enricher twice on the same asset with the same input MUST produce the same result. Enrichers MUST NOT leave side effects that break on re-execution. Enricher results MUST include a version field. Upgrading an enricher MUST NOT require re-processing all previously enriched assets.

## Preconditions

- The enricher is registered and invoked through the enricher pipeline.
- The asset exists and is in a state that permits enrichment.

## Observability

Idempotency violations are detectable by running the same enricher twice on the same asset and comparing results. Any divergence in output fields (excluding timestamps) constitutes a violation.

## Deterministic Testability

1. Run an enricher on a test asset. Record the result.
2. Run the same enricher on the same asset again. Assert the result is identical (excluding execution timestamps).
3. Simulate a partial failure mid-enrichment, then re-run. Assert no duplicate side effects (e.g. duplicated metadata rows, double-counted values).
4. Assert the result object contains a `version` field.

## Failure Semantics

**Planning fault.** A non-idempotent enricher produces divergent metadata on retry, causing assets to have inconsistent quality depending on execution history.

## Required Tests

- `pkg/core/tests/contracts/ingest/test_inv_enricher_idempotent.py`

## Enforcement Evidence

TODO
