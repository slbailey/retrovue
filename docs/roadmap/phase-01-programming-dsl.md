# Phase 01 – Programming DSL & Two-Tier Schedule Architecture

**Status:** In Progress

## Objective
Provide a human-friendly YAML DSL for describing channel programming grids, compiled into a **Program Schedule** (Tier 1). A separate **Playout Log Expander** (Tier 2) breaks program blocks into acts + ad slots for Air.

## Architecture

### Tier 1: Program Schedule (DSL Compiler)
- Input: YAML DSL with templates, selectors, grid assignments
- Output: Grid-aligned program blocks (no breaks, no commercials)
- Rolling horizon: 3–4 calendar days
- This is what an EPG would display

### Tier 2: Playout Log (Expander)
- Input: Program block + asset metadata (chapter markers)
- Output: Acts interleaved with empty ad block slots
- Rolling horizon: 3–4 program blocks ahead of "now"
- Consumed by Channel Manager → Air

### Traffic Manager v1
- Fills empty ad blocks by looping filler.mp4
- Pads remainder with black frames

## Deliverables
1. **Contract doc** – `docs/contracts/core/programming_dsl.md` (two-tier model)
2. **JSON Schema** – `docs/contracts/core/programming_dsl.schema.json` (program schedule output)
3. **Schedule compiler** – `pkg/core/src/retrovue/runtime/schedule_compiler.py`
4. **Playout log expander** – `pkg/core/src/retrovue/runtime/playout_log_expander.py`
5. **Traffic manager v1** – `pkg/core/src/retrovue/runtime/traffic_manager.py`
6. **CLI commands** – `programming compile`, `programming validate`, `programming expand`
7. **Tests** – `test_schedule_compiler.py`, `test_playout_log_expander.py`, `test_traffic_manager.py`

## Key Concepts
- **Program Block** = one complete content piece (episode/movie) regardless of grid slots consumed
- **Grid Alignment** = episodes MUST start on grid boundaries (:00/:30 network, :00/:15 premium)
- **Chapter Markers** = `chapter_markers_sec` on AssetMetadata for act-break determination
- **Ad Block** = empty slot in playout log, filled by Traffic Manager

## Test Plan
- Program schedule: grid alignment, episode selection, template expansion, no breaks in output
- Playout log: chapter markers, approximation, act splitting, ad block durations
- Traffic manager: filler looping, black frame padding, duration math

## Implementation Status
- [x] Contract doc (v2 two-tier model)
- [x] JSON schema (program-schedule.v2)
- [x] Schedule compiler (program blocks only)
- [x] Playout log expander
- [x] Traffic manager v1
- [x] CLI commands (compile, validate, expand)
- [x] Tests
- [ ] Integration with ScheduleService
- [ ] Review with Steve
