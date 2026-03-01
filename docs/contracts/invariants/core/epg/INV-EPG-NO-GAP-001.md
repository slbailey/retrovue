# INV-EPG-NO-GAP-001 — No temporal gaps in EPG coverage

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-LIVENESS`

## Purpose

A broadcast day with gap-free scheduling (`INV-SCHEDULEDAY-NO-GAPS-001`) MUST produce gap-free EPG coverage. A gap in the EPG means viewers see no listing for a time window where content is actually airing — violating `LAW-LIVENESS` at the presentation layer. Since EPG is derived from a contiguous grid (`LAW-GRID`), gaps indicate a derivation fault.

## Guarantee

EPG events derived from a fully-resolved broadcast day MUST provide continuous coverage from the first event's `start_time` to the last event's `end_time`. For consecutive events sorted by `start_time`: `events[i].end_time == events[i+1].start_time`.

## Preconditions

- The source `ResolvedScheduleDay` has been materialized with full coverage.
- The query range falls within a resolved broadcast day.

## Observability

Sort EPG events by `start_time`. For each consecutive pair, assert `events[i].end_time == events[i+1].start_time`. Any gap is detectable by offline audit.

## Deterministic Testability

Build a `ResolvedScheduleDay` with contiguous slots covering the full broadcast day. Derive EPG events. Assert consecutive events are temporally adjacent with no gaps. No real-time waits required.

## Failure Semantics

**Planning fault.** A gap in derived EPG events indicates the derivation logic dropped or miscalculated an event's time span.

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgNoGap001`

## Enforcement Evidence

TODO
