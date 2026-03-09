# INV-EPISODE-PROGRESSION-012 — Calendar-only computation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring that occurrence counting is a pure function of calendar dates and the placement bitmask. If occurrence counting depends on external state, the derivation chain becomes non-reproducible.

## Guarantee

`count_occurrences(anchor, target, mask)` MUST be a pure function. Same inputs MUST always produce the same output. The function MUST NOT access system time, mutable state, playlog records, as-run logs, resolution history, or external services.

The computation MUST use arithmetic (full weeks × bits-per-week plus partial-week remainder). The computation MUST be bounded regardless of the distance between anchor and target.

## Preconditions

None. This invariant applies to all invocations of the occurrence counting function.

## Observability

The occurrence count for a given (anchor, target, mask) triple changes between invocations. Or: computation time grows linearly with the distance between anchor and target.

## Deterministic Testability

Call `count_occurrences(anchor, target, mask)` twice with identical arguments. Assert identical results. Call with a 10-year range. Assert computation completes in bounded time and produces the correct count.

## Failure Semantics

**Planning fault.** Non-pure occurrence counting means episode selection is not deterministic.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
