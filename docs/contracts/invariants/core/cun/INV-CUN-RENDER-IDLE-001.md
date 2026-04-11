# INV-CUN-RENDER-IDLE-001 — CUN Renders During Idle Time

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects schedule compilation latency. CUN rendering is compute-intensive (ffmpeg). It MUST happen during idle processor time (the "think" phase), never inline during schedule compilation.

## Guarantee

CUN segments MUST be rendered during idle processor time. Rendering MUST NOT occur during schedule compilation.

## Preconditions

CUN feature is enabled for the channel.

## Observability

Schedule compilation blocks on CUN rendering, or CUN rendering is invoked from within the compilation call stack.

## Deterministic Testability

Verify that schedule compilation with an unresolved CUN segment completes without invoking the render worker. The CUN segment is left unresolved (pending) for the worker to pick up asynchronously.

## Failure Semantics

Runtime fault — compilation latency spike blocks schedule generation.

## Required Tests

- `server/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
