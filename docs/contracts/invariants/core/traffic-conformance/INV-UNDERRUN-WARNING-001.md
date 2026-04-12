# INV-UNDERRUN-WARNING-001 — Extreme underrun emits structured warning

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

## Purpose

When content occupies less than 50% of the grid slot, the schedule is likely misconfigured. The compiler MUST warn the operator without halting compilation, preserving `LAW-GRID` (grid-aligned output) while surfacing the anomaly.

## Guarantee

When `content_duration < 0.5 * scheduled_duration`, the compiler MUST emit a structured warning containing block identifier, template name, content duration, slot duration, and utilization percentage. The warning MUST NOT halt compilation.

## Preconditions

- Content duration and scheduled slot duration are known at compile time.
- The block is underconstrained (positive break budget).

## Observability

- Structured warning event with fields: `block_id`, `template`, `content_duration_sec`, `slot_duration_sec`, `utilization_pct`.
- Warning is emitted at compile time, not at traffic fill time.

## Deterministic Testability

Construct a block where content is 40% of the slot. Verify a warning is emitted with correct utilization percentage. Construct a block at 60% and verify no warning. Verify the warned block still compiles successfully.

## Failure Semantics

No fault. Warning only. The block compiles and the budget absorption cascade runs normally.

## Required Tests

- `server/tests/contracts/test_traffic_profiles_conformance.py`

## Enforcement Evidence

TODO
