# INV-EPISODE-PROGRESSION-003 — Monotonic ordered advancement

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that viewers see episodes in catalog order. A serial strip that skips or reorders episodes violates the broadcast simulation contract.

## Guarantee

For each broadcast day where the placement pattern matches, episodes MUST advance by exactly `emissions_per_occurrence` positions. The Nth matching day after the anchor MUST select base episode at `anchor_episode_index + (N × emissions_per_occurrence)` (subject to exhaustion policy). For single-emission runs (`emissions_per_occurrence=1`), this reduces to advancing by exactly one position per matching day.

## Preconditions

- A Progression Run record exists with a valid anchor and placement pattern.
- The target broadcast day matches the placement pattern.

## Observability

An episode is skipped, repeated (except under `hold_last` after catalog exhaustion), or selected out of catalog order on a matching broadcast day.

## Deterministic Testability

Create a daily Progression Run anchored on Monday at E0 with `emissions_per_occurrence=1`. Resolve Monday through Sunday. Assert indices 0, 1, 2, 3, 4, 5, 6. Resolve the second Monday. Assert index 7. No day is skipped; no day repeats. For a run with `emissions_per_occurrence=3`, day 1 base is 0, day 2 base is 3, day 3 base is 6.

## Failure Semantics

**Planning fault.** Non-monotonic advancement means the episode catalog is not being consumed in order.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
