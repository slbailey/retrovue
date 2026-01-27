# Phase 2 — Mock SchedulePlan Contract

## Purpose

Describe intent only: a static, declarative plan for the mock channel. **Duration-free**: no clock math, no offsets, no durations, no playout—just the structure of “what runs in each grid” (item identity and order).

## Contract

**SchedulePlan** for the mock channel expresses:

- For **every** grid segment (30-minute block):
  - **Item A**: samplecontent (e.g. `samplecontent` or asset id)
  - **Item B**: filler (e.g. `filler` or asset id)
- **Order only**; **no durations, no offsets, no timing** in the plan itself. Phase 3 introduces a separate “mock duration config” to resolve which item is active; the plan stays purely structural.

**Inputs**: none (static plan).

**Outputs**: SchedulePlan, ScheduleDay, and a **ScheduleItem** list per grid (exactly two items, A then B). No duration or timing fields.

## Execution (this phase)

- **No process required.** Build the plan data structure and optionally a loader or accessor that returns “plan for any given day.”
- **Dependency**: May use Phase 1 grid boundaries to define “per grid” only if needed for structure; no elapsed/remaining math here.

## Test scaffolding

- **Unit tests**: Construct or load the mock SchedulePlan; for a given day (or any day), assert:
  - Plan exists.
  - Each grid has exactly two items in order: A (samplecontent), B (filler).
- No duration math in the plan; no clock, no tune-in.

## Tests

- Plan exists for any given day.
- Each grid has exactly two items in order (samplecontent, filler).
- Plan is duration-free: no duration or timing fields in the plan.

## Out of scope

- ❌ No clock math
- ❌ No offsets
- ❌ No playout
- ❌ No ChannelManager or Air

## Exit criteria

- Plan is declarative and boring.
- Automated tests pass without human involvement.
- ✅ Exit criteria: plan is declarative and boring; tests pass automatically.
