# Phase 3 — Active Schedule Item Resolver

## Purpose

Resolve the **active conceptual item** using **plan + configured durations**. Given a SchedulePlan (Phase 2, duration-free), grid timing (Phase 1), and a **mock duration config**, resolve the single active ScheduleItem (samplecontent or filler). Conceptual only—no media paths or PTS.

## Mock duration config

Phase 3 depends on a fixed config (not part of the plan). Time units are **milliseconds (int64)** to match Phase 4; human-readable equivalents in prose.

- **sample_duration_ms** = 1_499_000 (24:59) — how long Item A (samplecontent) runs within each grid.
- **grid_duration_ms** = 1_800_000 (30:00) — grid block length; **must match Phase 1**.
- **filler_start_ms** = sample_duration_ms — elapsed time at which Item B (filler) starts; i.e. filler starts at 24:59 into the grid.

So: `elapsed_in_grid_ms < filler_start_ms` → samplecontent; `elapsed_in_grid_ms >= filler_start_ms` → filler.

**Grid consistency:** Resolver must **assert** `grid_duration_ms == Phase 1 grid_duration`; a mismatch is a **configuration error** (fail fast, do not silently drift if Phase 1 is changed later).

## Contract

**Given**:

- SchedulePlan (from Phase 2; duration-free)
- Grid timing: `grid_start`, `elapsed_in_grid_ms` (from Phase 1; elapsed in ms)
- Mock duration config: `sample_duration_ms`, `grid_duration_ms`, `filler_start_ms` (as above)

**Resolve**: the **active ScheduleItem** (conceptual: "samplecontent" or "filler") for the current moment.

**Inputs**: SchedulePlan, grid timing info, mock duration config.

**Outputs**: Active ScheduleItem (samplecontent or filler), as a value or identifier—no file paths or PTS.

## Execution (this phase)

- **No process required.** Resolver is pure logic: (plan, grid timing, mock duration config) → active item.
- **Dependencies**: Phase 1 grid math, Phase 2 mock plan (duration-free), mock duration config. In tests, use the config above and fixed elapsed_in_grid.

## Test scaffolding

- **Unit tests**: Use mock duration config in ms (sample_duration_ms = 1_499_000, grid_duration_ms = 1_800_000, filler_start_ms = 1_499_000). Call the resolver with fixed plan and:
  - elapsed_in_grid_ms = 420_000 (7:00) → expect samplecontent
  - elapsed_in_grid_ms = 1_560_000 (26:00) → expect filler
  - Exact boundary: elapsed_in_grid_ms = 1_498_000 (24:58) → samplecontent; **elapsed_in_grid_ms >= filler_start_ms** → filler.
- No media, no files, no ChannelManager; no tune-in.

## Tests

- elapsed_in_grid_ms = 420_000 (7:00) → samplecontent
- elapsed_in_grid_ms = 1_560_000 (26:00) → filler
- Exact boundary: elapsed_in_grid_ms < filler_start_ms → samplecontent; **elapsed_in_grid_ms >= filler_start_ms** → filler (avoids ambiguity about 25:00 vs 24:59; the rule is simply ≥ filler_start).

## Out of scope

- ❌ No media offsets
- ❌ No files
- ❌ No ChannelManager or Air

## Exit criteria

- Conceptual correctness only.
- Automated tests pass without human involvement.
- ✅ Exit criteria: conceptual correctness only; tests pass automatically.
