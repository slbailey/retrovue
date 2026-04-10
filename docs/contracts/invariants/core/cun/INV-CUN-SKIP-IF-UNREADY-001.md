# INV-CUN-SKIP-IF-UNREADY-001 — Skip Unready CUN Segments

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-LIVENESS`. A missing or incomplete CUN render MUST NOT block playout or introduce a generic bumper fallback. The segment is simply omitted.

## Guarantee

If a CUN render is incomplete at playout time, the system MUST skip the segment entirely. It MUST NOT block, wait, or fall back to a generic bumper.

## Preconditions

CUN segment exists in the schedule with no completed render.

## Observability

Playout blocks waiting for a CUN render, or a generic bumper is substituted for an unrendered CUN segment.

## Deterministic Testability

Expand a CUN segment in the playlist builder where the render request is pending/failed/missing. Verify the segment is omitted from the resolved playlist.

## Failure Semantics

Runtime fault — playout stall or unauthorized content substitution.

## Required Tests

- `pkg/core/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
