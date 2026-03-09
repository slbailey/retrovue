# INV-EPISODE-PROGRESSION-005 — Day-pattern fidelity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that a weekday-only strip does not consume episodes on weekends. Days outside the placement pattern are not occurrences and MUST NOT advance the episode index.

## Guarantee

Occurrence counting MUST be computed from the calendar and the `placement_days` bitmask only. Days outside the placement pattern MUST NOT advance the episode index.

The computation MUST NOT depend on:

- How many times the scheduler has compiled
- Whether previous days were compiled
- The order in which days are compiled
- Playlog or as-run records

## Preconditions

- A Progression Run exists with a `placement_days` bitmask that excludes one or more days of the week.

## Observability

A weekday-only placement produces different episode indices for Monday depending on whether Saturday and Sunday were compiled. Or: a weekend day advances a weekday-only strip's episode index.

## Deterministic Testability

Create a weekday-only run (mask=31) anchored on Monday at E0. Resolve Friday: assert E4. Resolve the following Monday: assert E5 (not E7). The two weekend days between Friday and Monday MUST NOT contribute to the occurrence count.

## Failure Semantics

**Planning fault.** Day-pattern violation means the episode sequence drifts from the intended broadcast cadence.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
