# INV-EPG-NO-OVERLAP-001 — No temporal overlap in EPG events

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

## Purpose

EPG events are derived from `ResolvedScheduleDay` whose slots snap to grid boundaries (`LAW-GRID`). Two overlapping EPG entries for the same channel would present contradictory information to viewers — two programs claiming to air at the same time. Since EPG is a pure derivation (`LAW-DERIVATION`) from a gap-free, non-overlapping grid, the derived events MUST inherit that non-overlap property.

## Guarantee

No two `EPGEvent` entries for the same `channel_id` within a single `programming_day_date` MUST have overlapping time spans. For any pair of events A and B: `A.end_time <= B.start_time` or `B.end_time <= A.start_time`.

## Preconditions

- The source `ResolvedScheduleDay` has been materialized and its slots satisfy `INV-SCHEDULEDAY-NO-GAPS-001`.
- EPG derivation has completed for the queried broadcast day.

## Observability

Sort EPG events by `start_time`. For each consecutive pair, assert `events[i].end_time <= events[i+1].start_time`. Any violation is a derivation logic fault detectable by offline audit.

## Deterministic Testability

Build a `ResolvedScheduleDay` with multiple `ProgramEvent` entries on grid boundaries. Derive EPG events via `ScheduleManager.get_epg_events()`. Sort by `start_time` and assert no consecutive pair overlaps. No real-time waits required.

## Failure Semantics

**Planning fault.** Overlap in EPG events indicates a defect in the derivation logic that maps `ProgramEvent` and `ResolvedSlot` data to `EPGEvent` time spans.

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgNoOverlap001`

## Enforcement Evidence

TODO
