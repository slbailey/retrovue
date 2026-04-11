# INV-BREAK-EXPAND-TO-FILL-001 — Breaks expand to fill budget

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-GRID` by ensuring all break budget time is consumed by breaks. Fixed-length breaks leave unallocated time that violates grid conservation. Expanding breaks to fill the budget ensures the block duration equation holds.

## Guarantee

Breaks MUST NOT be fixed-length. After break positions are determined, the break budget MUST be distributed across all breaks. The sum of all break durations MUST equal the break budget. Residual micro-gaps (< 1 segment) after traffic fill are handled by `INV-BREAK-PAD-DISTRIBUTED-001`.

## Observability

Per-break durations are logged during compilation. Sum of break durations equals the break budget. Different content runtimes in the same grid slot produce different per-break durations.

## Deterministic Testability

Compile two blocks with the same template and break count but different content durations (different break budgets). Verify that per-break durations differ and that each block's break durations sum to its respective break budget.

## Failure Semantics

**Planning fault.** Fixed-length breaks leave unallocated time, causing `INV-BLOCK-SEGMENT-CONSERVATION-001` violations.

## Required Tests

- `server/tests/contracts/test_timeline_compilation_templates.py`

## Enforcement Evidence

TODO
