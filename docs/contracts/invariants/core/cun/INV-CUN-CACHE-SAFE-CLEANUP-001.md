# INV-CUN-CACHE-SAFE-CLEANUP-001 — Safe Cache Cleanup Rule

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-LIVENESS` under content-addressed deduplication. A cached file may be shared across multiple CUN requests (different channels or time slots). Premature deletion breaks all referencing requests.

## Guarantee

A cached CUN file MUST NOT be deleted until ALL `cun_render_requests` referencing its `content_hash` have `segment_start_utc` in the past.

## Preconditions

A cached file is referenced by multiple CUN render requests with different `segment_start_utc` values.

## Observability

A cached file is deleted while at least one referencing request has a future `segment_start_utc`.

## Deterministic Testability

Create two completed requests with the same content hash but different `segment_start_utc` values (one past, one future). Run cleanup. Verify the file is retained. Advance both past. Run cleanup. Verify the file is now eligible.

## Failure Semantics

Runtime fault — shared CUN asset deleted prematurely; downstream segment skipped.

## Required Tests

- `pkg/core/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
