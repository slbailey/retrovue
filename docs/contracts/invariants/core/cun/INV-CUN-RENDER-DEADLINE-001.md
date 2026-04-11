# INV-CUN-RENDER-DEADLINE-001 — CUN Render Deadline Enforcement

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-CLOCK`

## Purpose

Protects `LAW-CLOCK` by ensuring renders that cannot complete before airtime are not started. A late render wastes CPU and its output MUST NOT be used.

## Guarantee

CUN renders MUST complete before `segment_start_utc` minus a configurable safety margin (`render_deadline_margin_ms`). Late renders MUST be marked SKIPPED and MUST NOT be used for playout.

## Preconditions

CUN render request exists with a `segment_start_utc` and the channel config specifies `render_deadline_margin_ms`.

## Observability

A CUN render request is started after its deadline has passed, or a completed render whose completion timestamp exceeds the deadline is used in playout.

## Deterministic Testability

Create a render request whose `segment_start_utc - render_deadline_margin_ms` is in the past relative to the test clock. Verify the worker marks it SKIPPED without rendering.

## Failure Semantics

Runtime fault — wasted CPU on late render; potential playout of stale content.

## Required Tests

- `server/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
