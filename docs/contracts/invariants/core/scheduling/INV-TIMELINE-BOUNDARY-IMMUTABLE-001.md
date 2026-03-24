# INV-TIMELINE-BOUNDARY-IMMUTABLE-001 — Timeline boundary immutability

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-CONTENT-AUTHORITY`, `LAW-TIMELINE`

## Purpose

Protects `LAW-IMMUTABILITY` by defining a concrete boundary below which the timeline is frozen. Without a defined boundary, scheduling operations can unintentionally modify already-defined or in-flight portions of the timeline. This invariant gives "append-only" a precise meaning.

## Guarantee

At the moment a scheduling operation begins, a boundary time T₍boundary₎ MUST be established. No modification may occur to any time strictly before T₍boundary₎.

## Observability

Given a boundary time T₍boundary₎, all timeline entries with start times < T₍boundary₎ MUST remain unchanged after the operation.

## Deterministic Testability

Record the timeline for all times < T₍boundary₎ before a scheduling operation. Execute the operation. Assert that every timeline entry with start time < T₍boundary₎ is byte-identical to the pre-operation snapshot.

## Failure Semantics

**Planning fault.** Scheduling operations that modify time ranges before the boundary retroactively rewrite history, creating divergence between the as-run record and the current timeline.

## Required Tests

- `pkg/core/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

TODO
