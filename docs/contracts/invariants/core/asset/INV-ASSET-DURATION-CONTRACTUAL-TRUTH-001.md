# INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001 — Duration is measured once and consumed as contractual truth

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

## Purpose

Asset duration is the foundational input to the scheduling grid. If duration were re-derived, re-probed, or independently calculated during planning or execution, different pipeline stages could disagree on content length, causing block boundary misalignment, schedule gaps, or overruns.

## Guarantee

Asset duration MUST be measured exactly once at ingest by ffprobe and stored as `duration_ms` on the Asset entity. The planning pipeline MUST consume `duration_ms` as contractual truth via the Asset Library. Duration MUST NOT be re-derived, re-probed, or independently calculated during planning or execution.

## Preconditions

The asset MUST have completed enrichment and have a valid `duration_ms > 0`.

## Observability

Enforced by architectural boundary: the Asset Library `get_duration_ms()` method returns the stored `duration_ms` value. No re-calculation is performed.

## Deterministic Testability

Set `duration_ms` on an asset stub during simulated enrichment. Query via a mock Asset Library. Assert the returned value matches the stored value exactly. No real database or media files required.

## Failure Semantics

**Architectural violation.** A pipeline stage attempted to derive duration independently of the stored value. This indicates a bypass of the Asset Library contract.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetDurationContractualTruth001`

## Enforcement Evidence

- `pkg/core/src/retrovue/catalog/db_asset_library.py` — `get_duration_ms()` returns stored value
- `pkg/core/src/retrovue/usecases/ingest_orchestrator.py` — sets `duration_ms` from probe data
- Error tag: `INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001-VIOLATED`
