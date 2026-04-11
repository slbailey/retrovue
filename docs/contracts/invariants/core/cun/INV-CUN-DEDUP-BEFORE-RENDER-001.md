# INV-CUN-DEDUP-BEFORE-RENDER-001 — Pre-Render Deduplication Check

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects CPU efficiency. Before starting a render, the system MUST check for an existing completed render with the same content hash and reuse it immediately.

## Guarantee

Before enqueueing or starting a CUN render, the system MUST check for an existing completed render with the same `content_hash`. If found, the request MUST be marked completed immediately with the existing file path. No duplicate ffmpeg invocation MUST occur.

## Preconditions

A completed CUN render with a given content hash exists in the cache.

## Observability

An ffmpeg render is invoked when a completed render with the same content hash already exists.

## Deterministic Testability

Insert a completed render request with content hash H. Enqueue a new request with the same content hash H. Verify the new request is marked completed without invoking the render function.

## Failure Semantics

Runtime fault — wasted CPU on redundant render.

## Required Tests

- `server/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
