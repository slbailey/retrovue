# INV-CUN-PRIORITY-PLAYOUT-001 — Playout-Time Priority Ordering

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-CLOCK`

## Purpose

Protects `LAW-CLOCK` by ensuring the most urgent CUN renders (soonest airtime) are processed first. Without priority ordering, a far-future render could starve an imminent one.

## Guarantee

CUN render priority MUST be ordered by playout time. Soonest-airing segments MUST render first.

## Preconditions

Multiple pending CUN render requests exist.

## Observability

A render request with a later `segment_start_utc` is claimed before one with an earlier `segment_start_utc`.

## Deterministic Testability

Enqueue two render requests with different `segment_start_utc` values. Verify the worker claims the earlier one first.

## Failure Semantics

Runtime fault — imminent CUN segment misses deadline while far-future segment renders.

## Required Tests

- `pkg/core/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
