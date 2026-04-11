# INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001 — Carry-in from prior day must be loaded from DB on cold start

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that a long-running program (e.g. a 6-hour documentary) that carries over from the prior broadcast day's last slot into the current day's time window is not trampled when the schedule is recompiled after a process restart. Without this guarantee, a cold start erases the carry-in movie from the EPG and replaces it with a freshly-compiled schedule that starts at the day boundary, violating "longform is never cut" and "carry-in across day boundary is allowed."

## Guarantee

When `_build_initial()` compiles the schedule starting from broadcast day D, and day D-1 is NOT in the compilation window, the system MUST load the prior day's last block end time from the active `ScheduleRevision` for day D-1 and use it as `active_carry_in_end_ms` for day D's compilation. Day D's first block MUST NOT start before the carry-in end time.

## Preconditions

- An active `ScheduleRevision` exists for day D-1.
- Day D-1's last `ScheduleItem` extends past the day D broadcast day start (carry-in scenario).
- The process is cold-starting (no in-memory blocks).

## Observability

Compare the active revision's first block start time against the prior day's last block end time. If `first_block_start < prior_last_block_end`, the carry-in window was violated.

## Deterministic Testability

1. Create a schedule for day D-1 whose last slot is a 6-hour movie starting at 09:30, ending at ~15:30.
2. Persist as active `ScheduleRevision` for D-1.
3. Cold-start `_build_initial()` with `start_date = D`.
4. Assert that day D's first compiled block starts at or after 15:30 (the carry-in end).
5. Assert that the EPG does not show a different movie in the 09:30–15:30 window.

## Failure Semantics

**Planning fault.** The viewer sees a different movie than what was scheduled. The EPG retroactively rewrites history. The as-run log and EPG become inconsistent.

## Incident Evidence

2026-03-24: "In Search of Darkness Part III" (342 min) scheduled as last slot of March 23 broadcast day (09:30–15:30 UTC March 24). Process restarted at 13:54 UTC. `_build_initial` compiled March 24 starting at 10:00 UTC with `active_carry_in_end_ms=0`, superseding the carry-in window. EPG replaced the movie with "Hell Night" at 10:00 and "Lilo & Stitch" at 13:30. Viewer reconnected and got Lilo & Stitch instead of the documentary that was still supposed to be playing.

## Required Tests

- `server/tests/contracts/test_inv_carry_in_survives_restart.py`

## Enforcement Evidence

TODO
