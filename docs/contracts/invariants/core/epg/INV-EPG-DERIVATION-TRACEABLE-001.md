# INV-EPG-DERIVATION-TRACEABLE-001 — Traceable to ResolvedScheduleDay

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

## Purpose

`LAW-DERIVATION` requires every downstream artifact to be traceable to its source. EPG events are derived from `ResolvedScheduleDay` via `ProgramEvent` and `ResolvedSlot` data. Every `EPGEvent` MUST trace back to a specific `ResolvedScheduleDay` and its constituent `ProgramEvent`, ensuring the EPG is accountable to the editorial chain.

## Guarantee

Every `EPGEvent` MUST carry a `programming_day_date` that corresponds to an existing `ResolvedScheduleDay`. The event's `resolved_asset`, `title`, `episode_id`, and `episode_title` MUST match the source `ProgramEvent` or `ResolvedSlot` from which the event was derived.

## Observability

For each EPG event, look up the `ResolvedScheduleDay` by `programming_day_date`. Verify that a `ProgramEvent` or `ResolvedSlot` exists whose resolved asset matches the event's `resolved_asset`. Any unmatched event is a violation.

## Deterministic Testability

Build a `ResolvedScheduleDay` with known `ProgramEvent` entries. Derive EPG events. For each event, verify `programming_day_date` matches the source day and asset fields match the source `ProgramEvent`. No real-time waits required.

## Failure Semantics

**Planning fault.** An untraceable EPG event indicates the derivation logic fabricated data not present in the source `ResolvedScheduleDay`.

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgDerivationTraceable001`

## Enforcement Evidence

TODO
