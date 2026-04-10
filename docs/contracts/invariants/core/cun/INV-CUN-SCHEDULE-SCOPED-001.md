# INV-CUN-SCHEDULE-SCOPED-001 — CUN Is Schedule-Scoped Synthesis

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects domain model integrity. CUN synthesis operates on schedule segments (channel + time + next program), not on existing assets. It MUST NOT be implemented as an ingest enricher or use the ProcessorJob queue, which are asset-scoped.

## Guarantee

CUN synthesis MUST use its own schedule-scoped pipeline (`cun_render_requests`). It MUST NOT be implemented as an ingest enricher or use the `ProcessorJob` queue.

## Preconditions

None.

## Observability

A CUN render request exists in the `processor_jobs` table, or a CUN enricher appears in the enricher registry.

## Deterministic Testability

Verify that the CUN render request model does not inherit from or reference `ProcessorJob`. Verify no enricher with CUN responsibility exists in the enricher registry.

## Failure Semantics

Planning fault — domain model violation; asset-scoped pipeline used for schedule-scoped work.

## Required Tests

- `pkg/core/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
