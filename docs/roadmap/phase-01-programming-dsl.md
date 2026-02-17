# Phase 01 – Programming DSL & Two-Tier Schedule Architecture

**Status:** ✅ Implemented (Reviewed with Steve — Feb 17, 2026)

## Objective
Provide a human-friendly YAML DSL for describing channel programming grids, compiled into a **Program Schedule** (Tier 1). A separate **Playout Log Expander** (Tier 2) breaks program blocks into acts + ad slots for Air.

## Architecture

### Tier 1: Program Schedule (DSL Compiler)
- Input: YAML DSL with templates, selectors, grid assignments
- Output: Grid-aligned program blocks (no breaks, no commercials)
- Rolling horizon: 3–4 calendar days
- This is what the EPG displays

### Tier 2: Playout Log (Expander)
- Input: Program block + asset metadata (chapter markers)
- Output: Acts interleaved with empty ad block slots
- Rolling horizon: 3–4 program blocks ahead of "now"
- Consumed by Channel Manager → Air

### Traffic Manager v1
- Fills empty ad blocks by playing filler.mp4 from offset 0
- No looping, no state tracking — every break starts from the beginning

## Deliverables
1. **Contract doc** – `docs/contracts/core/programming_dsl.md` ✅
2. **JSON Schema** – `docs/contracts/core/programming_dsl.schema.json` ✅
3. **Schedule compiler** – `pkg/core/src/retrovue/runtime/schedule_compiler.py` ✅ (1035 lines)
4. **Playout log expander** – `pkg/core/src/retrovue/runtime/playout_log_expander.py` ✅
5. **Traffic manager v1** – `pkg/core/src/retrovue/runtime/traffic_manager.py` ✅
6. **DSL schedule service** – `pkg/core/src/retrovue/runtime/dsl_schedule_service.py` ✅ (500 lines)
7. **Tests** – `test_schedule_compiler.py`, `test_playout_log_expander.py`, `test_traffic_manager.py` ✅

## Key Concepts
- **Program Block** = one complete content piece (episode/movie) regardless of grid slots consumed
- **Grid Alignment** = episodes MUST start on grid boundaries (:00/:30 network, :00/:15 premium)
- **Chapter Markers** = `chapter_markers_sec` on AssetMetadata for act-break determination
- **Ad Block** = empty slot in playout log, filled by Traffic Manager
- **Pool** = named collection of assets matched by metadata (series_title, genre, type)
- **Multi-Pool Rotation** = `pool: [a, b, c]` with sequential/shuffle/random modes

## DSL Features Implemented
- Single-pool blocks (`pool: cheers`, `mode: sequential`)
- Multi-pool round-robin (`pool: [med, fire, pd]`, `mode: sequential`)
- Shuffle mode across pools
- Random mode with seeded RNG
- Movie marathon blocks (`movie_selector` with `max_duration_sec`, `allow_bleed`)
- 24h continuous scheduling (`start: "06:00"`, `duration: "24h"`)
- Time-slotted dayparts (`start: "06:00"`, `end: "09:00"`)
- Overnight wrap (`start: "22:00"`, `end: "06:00"`)
- Configurable grid minutes (default 30)
- Broadcast day timezone support

## Production Channels (as of Feb 2026)
| Channel | Type | Description |
| --- | --- | --- |
| cheers-24-7 | Single-pool sequential | Cheers episodes 24/7 |
| nightmare-theater | Multi-pool + movie marathon | Freddy's Nightmares, Tales from the Crypt, horror movies |
| retro-prime | Multi-pool | Mixed retro programming |
| chicago-3 | Multi-pool sequential rotation | Chicago Med/Fire/PD rotating 24/7 |

## Implementation Status
- [x] Contract doc (v2 two-tier model)
- [x] JSON schema (program-schedule.v2)
- [x] Schedule compiler (program blocks only)
- [x] Playout log expander (chapter markers + computed breaks)
- [x] Traffic manager v1 (filler filling)
- [x] DSL schedule service (bridges DSL compiler → runtime)
- [x] CLI commands (compile, validate, expand)
- [x] Tests
- [x] Integration with ScheduleService
- [x] Catalog asset resolver (12,364 assets, 24,375 aliases from Plex)
- [x] Review with Steve ✅ (Feb 17, 2026)
