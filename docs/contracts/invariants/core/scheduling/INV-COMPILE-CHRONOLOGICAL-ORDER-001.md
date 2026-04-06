# INV-COMPILE-CHRONOLOGICAL-ORDER-001 — Chronological compilation order

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring the carry-in chain is well-ordered. Each day's compilation output provides the prior-day boundary for the next day. Compiling days out of order would produce incorrect carry-in values, silently corrupting block boundaries for all subsequent days.

## Guarantee

When compiling multiple broadcast days, compilation MUST proceed in strictly ascending chronological order. Later days MUST NOT be compiled before earlier missing days are resolved. Each day's output provides the prior-day boundary for the next.

## Observability

Out-of-order compilation is detectable by checking whether a compiled day's carry-in was derived from a day that had not yet been compiled at the time of derivation.

## Deterministic Testability

Set up two consecutive missing broadcast days. Compile them. Verify both days receive blocks and that the second day's carry-in is derived from the first day's output. Verify the system does not skip the first day to compile the second.

## Failure Semantics

**Planning fault.** Out-of-order compilation produces incorrect carry-in values, causing block boundaries to be wrong for all downstream days.

## Required Tests

- `pkg/core/tests/contracts/integration/test_integration_scheduling_authority.py`

## Enforcement Evidence

- `TestChronologicalOrder::test_both_missing_days_get_blocks` — missing days are compiled in ascending order, each providing carry-in for the next
