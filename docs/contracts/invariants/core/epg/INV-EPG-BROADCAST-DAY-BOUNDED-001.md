# INV-EPG-BROADCAST-DAY-BOUNDED-001 — EPG events contained within broadcast day

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

## Purpose

Every EPG event declares a `programming_day_date`. The event's time span MUST fall within that broadcast day's window. An event that extends beyond its declared broadcast day misrepresents when the program airs, breaking the grid alignment guarantee (`LAW-GRID`) and the derivation chain (`LAW-DERIVATION`).

## Guarantee

For every `EPGEvent`, the `start_time` and `end_time` MUST fall within the broadcast day window defined by `programming_day_date`. The broadcast day window runs from `programming_day_start_hour` on `programming_day_date` to `programming_day_start_hour` on `programming_day_date + 1 day`.

## Preconditions

- `programming_day_start_hour` is configured (default: 06:00).
- The source `ResolvedScheduleDay` has been materialized.

## Observability

For each EPG event, compute the broadcast day window from `programming_day_date` and `programming_day_start_hour`. Assert `window_start <= event.start_time` and `event.end_time <= window_end`. Violations are detectable by offline audit.

## Deterministic Testability

Build `ResolvedScheduleDay` entries with slots at various times including late-night (after midnight). Derive EPG events and assert each event's time span is contained within its declared broadcast day window. No real-time waits required.

## Failure Semantics

**Planning fault.** An event outside its broadcast day window indicates incorrect `programming_day_date` assignment or incorrect time calculation in the derivation logic.

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgBroadcastDayBounded001`

## Enforcement Evidence

TODO
