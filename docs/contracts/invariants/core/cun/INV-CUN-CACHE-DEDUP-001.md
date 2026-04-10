# INV-CUN-CACHE-DEDUP-001 — Content-Addressed Cache Deduplication

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects storage efficiency and `LAW-DERIVATION` traceability. Identical CUN renders (same template + title) MUST produce the same content hash, enabling deduplication.

## Guarantee

Rendered CUN assets MUST be content-addressed by `hash(template_id, title)` for deduplication. Two requests with the same template and title MUST produce the same content hash.

## Preconditions

CUN template and title are available.

## Observability

Two CUN requests with identical template_id and title produce different content hashes, or identical hashes map to different rendered files.

## Deterministic Testability

Compute content hashes for two requests with the same (template_id, title). Verify they are equal. Compute for different titles. Verify they differ.

## Failure Semantics

Planning fault — duplicate renders waste storage and CPU.

## Required Tests

- `pkg/core/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
