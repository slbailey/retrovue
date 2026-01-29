# Phase 1 — Grid Math Contract

## Purpose

Define grid boundaries once, centrally. All schedule and playout timing later uses these same boundaries (Phase 0 startup flow applies when the full stack runs; this phase is logic-only).

## Contract

Given `now` (from MasterClock or passed in as parameter):

- `grid_start(now)` → datetime (start of current 30-minute block)
- `grid_end(now)` → datetime (end of current 30-minute block)
- Grid size = **30 minutes**
- Boundaries at **:00** and **:30**

**Inputs**: wall-clock time (datetime or seconds, as per implementation).

**Outputs**: `grid_start`, `grid_end`, `elapsed_in_grid`, `remaining_in_grid`.

## Execution (this phase)

- **No process required.** Grid math is pure functions or a small service; no ProgramDirector or ChannelManager needs to be running.
- **Dependency**: Time input must be obtained via Phase 0 clock in production; in tests, use fixed `now` or injectable clock.

## Test scaffolding

- **Unit tests only**: Call `grid_start(now)`, `grid_end(now)`, and any helpers for `elapsed_in_grid` / `remaining_in_grid` with fixed datetimes. No HTTP, no tune-in.
- **Simulate "now"**: Pass explicit `now` (e.g. 10:00, 10:07, 10:29:59, 10:30) and assert on returned values.

## Tests

- `10:00` → start=10:00, end=10:30
- `10:07` → elapsed=7:00
- `10:29:59` → remaining=0:01
- `10:30` → new grid (start=10:30, end=11:00)

## Out of scope

- ❌ No schedule logic
- ❌ No assets
- ❌ No ChannelManager
- ❌ No tune-in or HTTP

## Exit criteria

- Grid math is correct and isolated.
- All tests are automated; no human involvement.
- ✅ Exit criteria: grid math is correct and isolated; tests pass automatically.
