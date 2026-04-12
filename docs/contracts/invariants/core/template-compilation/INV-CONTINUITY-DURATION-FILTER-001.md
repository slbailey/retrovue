# INV-CONTINUITY-DURATION-FILTER-001 — max_duration_sec is pool selection filter, not truncation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring continuity elements play at their authored duration. Truncation would silently alter editorial content. Filtering ensures only appropriately-sized assets are selected.

## Guarantee

`max_duration_sec` on a continuity element MUST be a pool selection filter. Assets with duration > `max_duration_sec` are excluded from the candidate set. Selected assets play at their full native duration. No asset is truncated to fit the `max_duration_sec` constraint.

## Observability

Pool resolution logs the filter criteria and the number of excluded assets. Selected asset duration is logged and verified to be ≤ `max_duration_sec`. No asset duration in the compiled block differs from its catalog duration.

## Deterministic Testability

Define a pool with assets of 10s, 20s, and 30s. Set `max_duration_sec: 15`. Verify only the 10s asset is selected. Verify its segment duration in the compiled block equals 10s (not 15s).

## Failure Semantics

**Planning fault.** Truncation alters content duration, causing incorrect break budget derivation and potential `INV-BLOCK-SEGMENT-CONSERVATION-001` violations.

## Required Tests

- `server/tests/contracts/test_timeline_compilation_templates.py`

## Enforcement Evidence

TODO
