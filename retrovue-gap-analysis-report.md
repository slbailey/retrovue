# RetroVue Scheduling System — Architectural Extraction Report

**Purpose:** Structured report for gap analysis between DSL contract (`docs/contracts/channel_dsl.md`) and current implementation.

**Date:** 2026-03-07
**Branch:** `feature/template-v2-graft`

---

## SECTION 1 — DSL CONTRACT SUMMARY

### 1.1 DSL Entity Model

```
Channel
  ├─ format.grid_minutes          # Time grid (e.g. 30 min)
  ├─ pools                        # Named asset sources (match rules only)
  │    └─ match: { type, series_title, genre, ... }
  ├─ programs                     # Reusable content assembly recipes
  │    ├─ pool                    # Which pool to draw from
  │    ├─ grid_blocks             # Target slot count (integer)
  │    ├─ fill_mode               # "single" or "accumulate"
  │    ├─ bleed                   # true/false — overrun allowed?
  │    ├─ intro (optional)        # Prepend segment
  │    └─ outro (optional)        # Append segment
  ├─ schedule                     # Layered override schedule
  │    ├─ all_day                 # Default layer (lowest priority)
  │    ├─ weekday / weekend       # Group layer
  │    ├─ <day_name>              # Specific DOW layer
  │    └─ dates: { "MM-DD": [...] }  # Exact date layer (highest priority)
  │         └─ blocks[]
  │              ├─ start          # Grid-aligned start time
  │              ├─ slots / duration / end_time  # Exactly one duration spec
  │              ├─ program        # Reference to a named program
  │              ├─ progression    # sequential / random / shuffle
  │              └─ cooldown_hours # Per-block cooldown
  ├─ templates (optional)         # Multi-segment wrappers (intros, bumpers)
  │    └─ segments[]
  │         ├─ source             # Collection/pool reference
  │         └─ primary: true      # Marks the main content segment
  └─ traffic                      # Commercial/promo fill rules
       ├─ allowed_types
       ├─ cooldowns
       └─ max_plays_per_day
```

### 1.2 Scheduling Model (Contract)

The contract defines a **six-stage pipeline**:

1. **Schedule Resolution** — Layered override merge (dates > DOW > group > all_day)
2. **Program Block Plan** — Grid-aligned program assignments
3. **Program Resolution** — Pool + progression mode → asset selection
4. **Program Assembly** — Fill mode (single/accumulate), intro/outro, bleed
5. **Break Detection** — Chapter markers > asset boundaries > algorithmic placement
6. **Traffic Fill** — Commercials/promos fill break budget; pad to exact grid fit

### 1.3 Required Invariants (Contract)

| # | Invariant |
|---|-----------|
| C1 | Program starts always align to grid |
| C2 | Schedule blocks resolve to integer grid units |
| C3 | Programs are reusable named objects defining content assembly, not timing |
| C4 | Pools are asset sources only — no progression/cooldown logic |
| C5 | Progression mode, cooldowns, cursor persistence are schedule-block concerns |
| C6 | Sequential progression maintains persistent cursor per schedule-block identity |
| C7 | Bleed is explicitly controlled by program definition |
| C8 | Continuity is optional/best-effort |
| C9 | Break opportunities determined during playlog construction, not schedule compilation |
| C10 | Break priority: chapter markers > asset boundaries > algorithmic |
| C11 | Traffic fills all breaks; remaining budget padded to exact grid fit |
| C12 | Actual playout may exceed grid if program bleeds |
| C13 | Slot count must be exact multiple of program's grid_blocks |
| C14 | Schedule block identity = (channel_id, layer, start_time, program_ref) |
| C15 | First ~20% of program runtime is a protected zone for algorithmic breaks |
| C16 | Break spacing is non-uniform — intervals widen toward end |
| C17 | Cold opens respected — no break before first chapter marker |
| C18 | All randomness flows from a single RNG stream (determinism) |

### 1.4 Required Outputs

| Output | Description |
|--------|-------------|
| Program Schedule | Grid-aligned program blocks (Tier 1) |
| Playlog | Fully segmented timeline with breaks and traffic (Tier 2) |
| EPG | Viewer-facing program guide derived from resolved schedule |
| Playout Plan | Frame-accurate segments for AIR execution |

---

## SECTION 2 — CURRENT SCHEDULER ARCHITECTURE

### 2.1 Main Modules

| Module | Purpose |
|--------|---------|
| `schedule_compiler.py` | Pure-function compiler: YAML DSL → ProgramBlockOutput list |
| `dsl_schedule_service.py` | Rolling horizon service: compiles days, serves ScheduledBlocks |
| `playout_log_expander.py` | Expands a program block into segmented ScheduledBlock (content + filler placeholders) |
| `traffic_manager.py` | Fills filler placeholders with real interstitials or static filler |
| `schedule_revision_writer.py` | Persists compiled schedule to relational tables (ScheduleRevision + ScheduleItem) |
| `schedule_items_reader.py` | Reads Tier-1 relational rows → serialized block dicts for Tier-2 |
| `playlist_builder_daemon.py` | Background daemon maintaining 2-3h rolling Tier-2 horizon |
| `channel_manager.py` | Per-channel runtime: serves MPEG-TS, consumes ScheduledBlocks |
| `schedule_types.py` | Canonical data structures (ScheduledBlock, ScheduledSegment, etc.) |
| `schedule_manager.py` | Phase 1-3 ScheduleManager (legacy, being superseded by DSL pipeline) |

### 2.2 Core Classes

```
DslScheduleService
  ├─ load_schedule(channel_id)          # Initial multi-day compile
  ├─ get_block_at(channel_id, utc_ms)   # Serve block for wall-clock time
  ├─ get_playout_plan_now(channel_id, at_station_time)  # Segments for current block
  ├─ ensure_block_compiled(channel_id, block)  # Synchronous Tier-2 fill
  ├─ _build_initial(channel_id)         # Compile HORIZON_DAYS days
  ├─ _compile_day(channel_id, day_str)  # Single broadcast day
  └─ _maybe_extend_horizon(...)         # Rolling horizon extension
```

```
schedule_compiler (pure functions)
  ├─ parse_dsl(yaml_text) → dict
  ├─ compile_schedule(dsl, resolver, ...) → dict  # Main entry point
  ├─ resolve_day_schedule(dsl, target_date) → list[dict]  # Layer merge
  ├─ expand_templates(dsl) → dict
  ├─ _compile_episode_block(...)   # Episode/rerun blocks
  ├─ _compile_movie_block(...)     # Single movie blocks
  ├─ _compile_movie_marathon(...)  # Back-to-back movie windows
  ├─ _compile_template_entry(...)  # Template-based blocks
  ├─ _compile_sitcom_block(...)    # Slot-based sitcom blocks (legacy)
  ├─ select_episode(...)           # Episode selection (sequential/random/serial)
  └─ select_movie(...)             # Movie selection with filters
```

### 2.3 Data Flow

```
YAML DSL File (config/dsl/*.yaml)
       │
       ▼  parse_dsl()
   Raw dict
       │
       ▼  compile_schedule()
   Program Schedule dict
   { program_blocks: [ProgramBlockOutput...] }
       │
       ├──▶  _save_compiled_schedule()
       │     → write_active_revision_from_compiled_schedule()
       │     → ScheduleRevision + ScheduleItem rows (Postgres)
       │
       ▼  DslScheduleService._compile_day()
   list[ScheduledBlock]   ← expand_program_block() per block
   (in-memory, content + filler placeholders)
       │
       ├──▶  Tier 1: In-memory blocks (DslScheduleService._blocks)
       │
       ▼  fill_ad_blocks() / PlaylistBuilderDaemon
   ScheduledBlock with real interstitials
       │
       ├──▶  Tier 2: PlaylistEvent rows (Postgres)
       │
       ▼  ChannelManager.get_block_at()
   ScheduledBlock → BlockPlan → PlayoutSession → AIR → MPEG-TS
```

### 2.4 How Dayparts Are Resolved

The `resolve_day_schedule()` function in `schedule_compiler.py` implements layered merge:

1. Start with `all_day` blocks (indexed by start time)
2. Overlay `weekdays`/`weekends` group blocks (by start time)
3. Overlay specific DOW blocks (by start time)

Higher layers **replace** lower-layer blocks at the same start time. Blocks at non-overlapping start times from lower layers pass through.

**Current limitation:** The `dates:` layer from the contract (exact date overrides with highest priority) is **not implemented**.

### 2.5 How Content Is Selected

| Block Type | Selection Logic |
|-----------|----------------|
| Episode block (`_compile_episode_block`) | `select_episode()` — sequential counter per pool, random seed, or shuffle round-robin across pools |
| Movie block (`_compile_movie_block`) | `select_movie()` — random from filtered pool with rating/duration constraints |
| Movie marathon (`_compile_movie_marathon`) | Same as movie block but iterates until time window filled, with dedup via `used_movie_ids` |
| Template entry (`_compile_template_entry`) | Primary segment from pool (like movie), non-primary resolved from collection/pool |
| Sitcom block (`_compile_sitcom_block`) | Legacy slot-based: explicit slot list with per-slot episode_selector |

### 2.6 How Filler/Ads Are Inserted

**Two-stage process:**

1. **`expand_program_block()`** (playout_log_expander.py):
   - Creates content segments + empty filler placeholders (`segment_type="filler"`, `asset_uri=""`)
   - For "network" channel_type: mid-content breaks at chapter markers or computed intervals
   - For "movie" channel_type: single post-content filler block

2. **`fill_ad_blocks()`** (traffic_manager.py):
   - Replaces empty filler placeholders with real interstitial assets from DatabaseAssetLibrary
   - Falls back to static filler file if no interstitials available
   - Distributes leftover time as evenly-spaced black pads between spots

### 2.7 How Current Playback Is Determined

`ChannelManager` calls `DslScheduleService.get_block_at(channel_id, utc_ms)`:

1. Check if horizon needs extending (`_maybe_extend_horizon`)
2. In-memory time-range lookup (`_find_in_memory_block`) — linear scan
3. Check Tier-2 (PlaylistEvent) for pre-filled version by block_id
4. If Tier-2 miss: synchronous compile via `ensure_block_compiled()`
5. Result: fully-filled `ScheduledBlock` → converted to `BlockPlan` → fed to `PlayoutSession`

Join-in-progress (JIP): `get_playout_plan_now()` walks segments, computes elapsed offset, adjusts `asset_start_offset_ms` for mid-segment join.

---

## SECTION 3 — DATA MODELS

### 3.1 Compile-Time Models

#### `ProgramBlockOutput` (schedule_compiler.py)
```
title: str                          # Block title for EPG
asset_id: str                       # Selected asset identifier
start_at: datetime                  # Grid-aligned start time (UTC)
slot_duration_sec: int              # Grid slot duration
episode_duration_sec: int           # Actual content runtime
collection: str | None              # Source pool/collection
selector: dict | None               # Selection metadata
window_uuid: str | None             # Shared UUID for marathon windows
template_id: str | None             # Template name if template-derived
epg_title: str | None               # Override EPG title
compiled_segments: list[dict] | None # Pre-compiled template segments
```
- **Created by:** `schedule_compiler._compile_*()` functions
- **Consumed by:** `compile_schedule()` → serialized to dict → `DslScheduleService._compile_day()`

### 3.2 Runtime Models

#### `ScheduledSegment` (schedule_types.py, frozen)
```
segment_type: str                    # "content", "filler", "padding", "episode", "pad"
asset_uri: str                       # File path
asset_start_offset_ms: int           # Seek offset (INV-TIME-TYPE-001: must be int)
segment_duration_ms: int             # Duration (INV-TIME-TYPE-001: must be int)
transition_in: str                   # "TRANSITION_NONE" | "TRANSITION_FADE"
transition_in_duration_ms: int
transition_out: str
transition_out_duration_ms: int
gain_db: float                       # Loudness normalization gain
is_primary: bool                     # INV-MOVIE-PRIMARY-ATOMIC
```
- **Created by:** `expand_program_block()`, `_hydrate_compiled_segments()`, `fill_ad_blocks()`
- **Consumed by:** `ChannelManager`, `PlayoutSession`, serialized to PlaylistEvent

#### `ScheduledBlock` (schedule_types.py, frozen)
```
block_id: str                        # Deterministic hash: sha256(asset_id:start_utc_ms)
start_utc_ms: int                    # Grid boundary start (INV-TIME-TYPE-001)
end_utc_ms: int                      # Grid boundary end (INV-TIME-TYPE-001)
segments: tuple[ScheduledSegment, ...] # Immutable segment list
```
- **Created by:** `expand_program_block()`, `_hydrate_compiled_segments()`, deserialized from DB
- **Consumed by:** `DslScheduleService`, `ChannelManager`, `PlaylistBuilderDaemon`

### 3.3 Persistence Models

#### `ScheduleRevision` (Postgres)
- One row per (channel, broadcast_day) compilation
- Fields: `channel_id`, `broadcast_day`, `status` (active/superseded), `activated_at`, `metadata_`
- Represents a complete day's program schedule

#### `ScheduleItem` (Postgres)
- One row per program block within a revision
- Fields: `schedule_revision_id`, `start_time`, `duration_sec`, `asset_id`, `collection_id`, `content_type`, `slot_index`, `metadata_`, `window_uuid`
- `metadata_` contains: title, asset_id_raw, collection_raw, selector, compiled_segments

#### `ChannelActiveRevision` (Postgres)
- Pointer: (channel_id, broadcast_day) → schedule_revision_id
- One active revision per channel per day

#### `PlaylistEvent` (Postgres)
- Tier-2: fully-filled block with real interstitial URIs
- Fields: `block_id`, `channel_slug`, `broadcast_day`, `start_utc_ms`, `end_utc_ms`, `segments` (JSON)

### 3.4 Legacy Models (schedule_types.py, partially active)

| Model | Purpose | Status |
|-------|---------|--------|
| `ProgramBlock` | Phase 0 grid-bounded playout unit | Legacy — superseded by ScheduledBlock |
| `PlayoutSegment` | Frame-indexed segment with datetime boundaries | Legacy — superseded by ScheduledSegment |
| `SimpleGridConfig` | Phase 0 single-show config | Legacy |
| `DailyScheduleConfig` | Phase 1 multi-program config | Legacy |
| `ScheduleSlot` / `ResolvedSlot` | Phase 3 resolved schedule day | Legacy |
| `ResolvedScheduleDay` | Phase 3 immutable daily truth | Legacy |
| `EPGEvent` | Phase 3 EPG entry | Active for EPG queries |
| `ProgramEvent` | Canonical editorial unit (frozen) | Used in ResolvedScheduleDay |

---

## SECTION 4 — SCHEDULING PIPELINE

### 4.1 Full Pipeline: Template → Playback

```
YAML DSL File (config/dsl/trek-tv.yaml)
  │
  ▼ [1] parse_dsl()
Raw Python dict (channel, pools, schedule, templates, timezone)
  │
  ▼ [2] compile_schedule()
  │   ├─ expand_templates() — resolve legacy template aliases
  │   ├─ resolve_day_schedule() — merge layered schedule for target date
  │   ├─ _compile_*_block() — per-block compilation
  │   │     ├─ select_episode() / select_movie() — asset selection
  │   │     └─ ProgramBlockOutput per grid slot
  │   ├─ Sort, UTC normalize, grid alignment validation
  │   ├─ Compact (resolve bleed overlaps)
  │   └─ Emit: { version, channel_id, broadcast_day, program_blocks[] }
  │
  ▼ [3] DslScheduleService._compile_day()
  │   ├─ For each ProgramBlockOutput:
  │   │     ├─ Resolve asset URI via CatalogAssetResolver
  │   │     ├─ expand_program_block() OR _hydrate_compiled_segments()
  │   │     └─ ScheduledBlock (content + empty filler placeholders)
  │   └─ write_active_revision_from_compiled_schedule() → Postgres
  │
  ▼ [4] PlaylistBuilderDaemon.evaluate_once()  [background, rolling]
  │   ├─ load_segmented_blocks_from_active_revision() — read Tier-1
  │   ├─ expand_editorial_block() — deserialize + fill_ad_blocks()
  │   └─ Write to PlaylistEvent table (Tier-2)
  │
  ▼ [5] ChannelManager (at viewer tune-in)
  │   ├─ DslScheduleService.get_block_at(utc_ms)
  │   │     ├─ In-memory time lookup
  │   │     ├─ Tier-2 PlaylistEvent lookup by block_id
  │   │     └─ Synchronous fallback: ensure_block_compiled()
  │   ├─ JIP offset calculation
  │   └─ ScheduledBlock → BlockPlan → PlayoutSession
  │
  ▼ [6] PlayoutSession → AIR (gRPC)
  │   ├─ StartBlockPlanSession
  │   ├─ FeedBlockPlan (rolling feed-ahead)
  │   └─ AIR → MPEG-TS bytes → HTTP → Viewer
```

### 4.2 Step Ownership

| Step | Component | Artifact |
|------|-----------|----------|
| 1. Parse DSL | schedule_compiler | Raw dict |
| 2. Compile schedule | schedule_compiler | Program Schedule (ProgramBlockOutput list) |
| 3. Segment expansion | DslScheduleService + playout_log_expander | ScheduledBlock (Tier-1 in-memory) |
| 4. Traffic fill | PlaylistBuilderDaemon + traffic_manager | PlaylistEvent (Tier-2 Postgres) |
| 5. Block serving | ChannelManager + DslScheduleService | ScheduledBlock for playout |
| 6. Playout | PlayoutSession + AIR | MPEG-TS stream |

---

## SECTION 5 — CURRENT INVARIANTS

### 5.1 Enforced in Code

| Invariant | Enforcement |
|-----------|-------------|
| **Grid alignment** | `_validate_grid_alignment()` in schedule_compiler.py — validates start times and slot durations are multiples of grid slot. Runs pre- and post-compaction. |
| **INV-TIME-TYPE-001** (int ms) | `__post_init__` on ScheduledSegment, ScheduledBlock; boundary checks in `expand_program_block()`, `fill_ad_blocks()` |
| **INV-MOVIE-PRIMARY-ATOMIC** | `_assert_no_filler_before_primary()` in traffic_manager.py — no filler before primary segment |
| **INV-BREAK-PAD-DISTRIBUTED-001** | `_fill_break_with_interstitials()` — even pad distribution; assert total == break_duration |
| **INV-BLEED-NO-GAP-001** | Compaction pass in `compile_schedule()` — pushes blocks forward to resolve overlaps |
| **INV-SCHEDULE-SEED-DETERMINISTIC-001** | `channel_seed()` uses SHA-256, not Python `hash()` |
| **INV-SCHEDULE-SEED-DAY-VARIANCE-001** | `compilation_seed()` mixes broadcast_day; `_window_seed()` mixes start time |
| **INV-CHANNEL-TYPE-BREAK-PLACEMENT** | `expand_program_block()` dispatches to `_expand_movie` or `_expand_network` based on channel_type |
| **INV-TRANSITION-001** | `_expand_network()` applies TRANSITION_FADE only to second-class (computed) breakpoints |
| **INV-LOUDNESS-NORMALIZED-001** | `gain_db` on ScheduledSegment; background measurement via LoudnessEnricher |
| **INV-TEMPLATE-BLOCKS-COMPILE-TO-EXPLICIT-SEGMENTS** | `_resolve_template_segments()` + `_hydrate_compiled_segments()` — template segments resolved at compile time, not reconstructed at runtime |
| **INV-SCHEDULE-RETENTION-001** | Tier-1 purge (ProgramLogDay rows > 1 day old); hourly throttle |
| **INV-TIER2-AUTHORITY-001** | `ensure_block_compiled()` — synchronous, idempotent Tier-2 compilation |
| **INV-CHANNEL-NO-COMPILE-001** | ChannelManager reads Tier-2 only; compilation is service/daemon concern |
| **INV-PLAYLOG-HORIZON-001** | PlaylistBuilderDaemon maintains >= min_hours (default 3h) Tier-2 coverage |

### 5.2 Implicit Assumptions (Not Formally Enforced)

| Assumption | Where |
|-----------|-------|
| Schedule built per broadcast day (06:00–06:00 local) | `_build_initial()`, `_compile_day()` |
| Horizon of 3 days ahead on initial load | `HORIZON_DAYS = 3` |
| Recompile threshold: 6 hours remaining | `RECOMPILE_THRESHOLD_HOURS = 6` |
| Sequential counter persistence per compilation session only | `sequential_counters` dict lives in compile call scope |
| Grid minutes determined by channel template ("network"=30, "premium_movie"=15) | `get_grid_minutes()` |
| Broadcast day starts at hour 6 local time | `BROADCAST_DAY_START_HOUR = 6` |
| Blocks pruned when >24h in the past | `_prune_old_blocks()` |
| Block dedup via deterministic `block_id = sha256(asset_id:start_utc_ms)` | `_make_block_id()` |

---

## SECTION 6 — LIMITATIONS / IMPLICIT ASSUMPTIONS

### 6.1 Missing Contract Features

| Contract Feature | Status | Notes |
|-----------------|--------|-------|
| **`programs` as first-class named objects** | NOT IMPLEMENTED | No `programs:` section in DSL. Content assembly is embedded in block compilation functions (`_compile_episode_block`, `_compile_movie_block`, etc.). Programs are not reusable named entities. |
| **`fill_mode: accumulate`** | PARTIAL | Episode blocks accumulate to fill a time window, but this is implicit in `_compile_episode_block()`, not driven by a named program's `fill_mode` property. |
| **`fill_mode: single`** | PARTIAL | Movie blocks select a single asset, but this is embedded in `_compile_movie_block()`, not a program attribute. |
| **`program.grid_blocks`** | NOT IMPLEMENTED | Programs don't define their own grid span. Slot duration is computed dynamically from asset duration: `_grid_slot_duration(grid_minutes, episode_duration_sec)`. |
| **`program.bleed`** | NOT IMPLEMENTED as program property | Bleed is a property of block types (`allow_bleed` on movie_marathon), not a named program attribute. |
| **`program.intro` / `program.outro`** | NOT IMPLEMENTED on programs | Only available via `templates.segments[]`. |
| **`schedule.slots` as multiple of program.grid_blocks** | NOT IMPLEMENTED | No validation that slot count is a multiple of program grid_blocks (programs don't have grid_blocks). |
| **`dates:` override layer** | NOT IMPLEMENTED | `resolve_day_schedule()` only handles `all_day`, `weekdays`/`weekends`, and specific DOW names. No exact-date override support. |
| **Progression as schedule-block property** | PARTIAL | `mode:` is set on blocks in the DSL, but it's processed inline during compilation, not as a formal schedule-block attribute. |
| **Persistent sequential cursor per schedule-block identity** | NOT IMPLEMENTED | Sequential counters (`sequential_counters` dict) are per-compilation-session. They reset on restart/recompile. The contract requires persistence across days via schedule-block identity tuple. |
| **Cooldown rules** | NOT IMPLEMENTED | No `cooldown_hours` support on schedule blocks. |
| **Schedule block identity tuple** | NOT IMPLEMENTED | Contract requires `(channel_id, schedule_layer, start_time, program_ref)`. Current system has no formal block identity for cursor persistence. |
| **Break priority: chapter > boundary > algorithmic** | PARTIAL | `_expand_network()` uses chapter markers if present, else computed breakpoints. But `accumulate`-mode asset boundary breaks don't exist as a distinct tier. |
| **Protected zone (first 20%)** | NOT IMPLEMENTED | Computed breakpoints in `_expand_network()` use uniform interval division: `interval = episode_duration_ms / (num_breaks + 1)`. No protected zone. |
| **Non-uniform break spacing** | NOT IMPLEMENTED | Break spacing is uniform (equal intervals). Contract requires widening intervals and increasing break durations toward program end. |
| **Cold open protection** | NOT IMPLEMENTED | No logic to prevent breaks before first chapter marker. |
| **Continuity layer** | NOT IMPLEMENTED | No station IDs, network bumpers, or branding insertion. |
| **Traffic policy per channel** | MINIMAL | `fill_ad_blocks()` takes `asset_library` but has no per-channel `allowed_types`, `cooldowns`, or `max_plays_per_day` policy. |
| **Single RNG stream** | NOT IMPLEMENTED | Multiple independent `random.Random(seed)` instances created across different functions. |
| **`shuffle` progression** | PARTIAL | Multi-pool shuffle via round-robin in `_compile_episode_block()`. Not a true shuffle-then-consume-sequentially as described in contract. |

### 6.2 Structural Divergences

| Area | Contract Model | Current Implementation |
|------|---------------|----------------------|
| **Content assembly** | Named `programs` define assembly rules; schedule blocks reference programs | Block compilation functions (`_compile_episode_block`, `_compile_movie_block`, etc.) embed selection + assembly logic inline. No program objects exist. |
| **DSL structure** | `pools` + `programs` + `schedule` | `pools` + `schedule` (programs section absent). Block types are inferred from DSL shape (presence of `block:`, `movie_marathon:`, `movie_block:`, `type: template`). |
| **Duration specification** | `slots`, `duration`, or `end_time` on schedule blocks | `start`/`end` on block defs, `duration` on some blocks. `slots` is an explicit list of per-slot configs in sitcom blocks (not a count). |
| **Grid occupancy** | `slots × grid_minutes` = deterministic | Dynamic: `_grid_slot_duration()` computes from actual asset duration. Grid occupancy varies per episode. |
| **Break detection** | During playlog construction from assembled program | During `expand_program_block()` — operates on a single asset, not an assembled multi-asset program. |

### 6.3 Database Dependencies

- Schedule compilation requires `CatalogAssetResolver` which reads from Postgres (`Asset`, `Collection` tables)
- Compiled schedules persisted to `ScheduleRevision` + `ScheduleItem` (relational Tier-1)
- Filled blocks persisted to `PlaylistEvent` (Tier-2)
- Legacy `ProgramLogDay` table still exists but deprecated
- Sequential counters are NOT persisted — lost on restart

### 6.4 Fixed/Implicit Structures

- Grid is always 30 min (network) or 15 min (premium) — no per-channel override from DSL `grid_minutes` field
- Broadcast day always starts at 06:00 local
- Channel type ("network" vs "movie") drives break placement but is set at DslScheduleService construction, not in DSL
- Block types determined by DSL shape heuristics, not explicit `type:` field (except template entries)

---

## SECTION 7 — RELEVANT CODE FILES

### 7.1 Scheduling Pipeline

| File | Description |
|------|-------------|
| `pkg/core/src/retrovue/runtime/schedule_compiler.py` (~1420 lines) | Pure-function DSL compiler. Parses YAML, resolves day schedule layers, compiles block types (episode, movie, marathon, template, sitcom), validates grid alignment, compacts bleed overlaps. |
| `pkg/core/src/retrovue/runtime/dsl_schedule_service.py` (~900 lines) | Stateful schedule service. Rolling horizon compilation, Tier-1/Tier-2 block serving, asset URI resolution, loudness measurement, DB persistence. Main runtime entry point for scheduling. |
| `pkg/core/src/retrovue/runtime/playout_log_expander.py` (~242 lines) | Expands ProgramBlockOutput into ScheduledBlock with content + filler segments. Break placement logic (network vs movie channel types). |
| `pkg/core/src/retrovue/runtime/traffic_manager.py` (~201 lines) | Fills filler placeholders with real interstitials from DatabaseAssetLibrary. Pad distribution. Primary segment protection. |
| `pkg/core/src/retrovue/runtime/schedule_types.py` (~683 lines) | Canonical data structures: ScheduledBlock, ScheduledSegment, ProgramBlock (legacy), EPGEvent, ResolvedScheduleDay, protocols (ScheduleQueryService, etc.). |

### 7.2 Persistence / Reader-Writer

| File | Description |
|------|-------------|
| `pkg/core/src/retrovue/runtime/schedule_revision_writer.py` (~150+ lines) | Writes ScheduleRevision + ScheduleItem rows from compiled schedule output. Content type inference. |
| `pkg/core/src/retrovue/runtime/schedule_items_reader.py` (~200+ lines) | Reads Tier-1 rows, converts to serialized block dicts. Handles compiled_segments hydration for template blocks. |
| `pkg/core/src/retrovue/runtime/playlist_builder_daemon.py` (~300+ lines) | Background daemon: reads Tier-1, fills ads, writes Tier-2 PlaylistEvent. Rolling horizon maintenance. |

### 7.3 Runtime Consumption

| File | Description |
|------|-------------|
| `pkg/core/src/retrovue/runtime/channel_manager.py` (~large) | Per-channel runtime. HTTP serving, ScheduledBlock → BlockPlan conversion, JIP, PlayoutSession management. |
| `pkg/core/src/retrovue/runtime/playout_session.py` | Python wrapper for AIR subprocess. BlockPlan feed-ahead via gRPC. |

### 7.4 Asset Resolution

| File | Description |
|------|-------------|
| `pkg/core/src/retrovue/runtime/catalog_resolver.py` | CatalogAssetResolver — reads Asset/Collection from Postgres, provides lookup/query for schedule compiler. |
| `pkg/core/src/retrovue/runtime/asset_resolver.py` | AssetResolver protocol + AssetMetadata dataclass. |

### 7.5 DSL Configuration Files

| File | Description |
|------|-------------|
| `config/dsl/trek-tv.yaml` | All Star Trek — 4 pools, 4 episode blocks, all sequential |
| `config/dsl/galactica-command.yaml` | BSG classic + reimagined — 2 pools, 2 episode blocks |
| `config/dsl/the-precinct.yaml` | Crime procedurals — 4 pools, 4 episode blocks, all sequential |
| `config/dsl/saturday-supercade.yaml` | Saturday cartoons — 6 pools, 1 block with multi-pool shuffle |

### 7.6 Legacy / Transitional

| File | Description |
|------|-------------|
| `pkg/core/src/retrovue/runtime/schedule_manager.py` | Phase 1-3 ScheduleManager — older scheduling path |
| `pkg/core/src/retrovue/runtime/schedule_manager_service.py` | Service wrapper for legacy ScheduleManager |
| `pkg/core/src/retrovue/runtime/playlist_backed_schedule_service.py` | Older schedule service backed by playlist |
| `pkg/core/src/retrovue/runtime/scheduler_tier1.py` | Tier-1 scheduling helpers |
| `pkg/core/src/retrovue/runtime/mock_schedule.py` | Test schedule mock |

---

## SUMMARY: Key Gaps for Architect Review

The most significant architectural divergences between contract and implementation:

1. **No `programs` abstraction** — The contract's central concept (named, reusable program objects with `fill_mode`, `grid_blocks`, `bleed`, `intro`/`outro`) does not exist. Content assembly is scattered across per-block-type compilation functions.

2. **No persistent progression cursors** — Sequential/shuffle state is session-scoped, not persisted per schedule-block identity as required.

3. **No `dates:` override layer** — The highest-priority scheduling layer is missing.

4. **Simplified break model** — Uniform interval spacing instead of non-uniform widening. No protected zone. No cold open protection. No accumulate-mode asset boundary breaks.

5. **No formal traffic policy** — No per-channel allowed types, cooldowns, or daily caps.

6. **Dynamic grid occupancy** — Slot duration computed from asset runtime, not from program.grid_blocks. This means grid occupancy is data-dependent, not editorially declared.

7. **DSL shape divergence** — Current DSL uses `block:`, `movie_marathon:`, `movie_block:`, `type: template` — structurally different from the contract's `programs` + `schedule` with `program:` references.
