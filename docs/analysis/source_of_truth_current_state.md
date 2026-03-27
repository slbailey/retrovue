# Source of Truth — Current State Analysis

Diagnostic document. Describes what the system currently does in practice, not intended design.

---

## 1. Authoritative Data Sources

### 1.1 DSL YAML (Schedule Template)

| Property | Value |
|----------|-------|
| Storage | Filesystem: `config/channels/<channel>.yaml` |
| Read by | `DslScheduleService._compile_day` (line 1777), `_build_initial` (line 1015), `_maybe_extend_horizon` (line 891) |
| Authority | Editorial intent. Authoritative for schedule structure, program definitions, pools, traffic profiles, presentation, midroll config. |
| Derivation | Source — not derived from anything. |

The DSL is read fresh from disk on every compilation. It is never cached in the database. Changes to the YAML take effect on the next compilation (either triggered by horizon extension or by superseding the active revision and restarting).

### 1.2 ScheduleRevision + ScheduleItem (Compiled Schedule)

| Property | Value |
|----------|-------|
| Storage | Postgres: `schedule_revisions` + `schedule_items` tables |
| Read by | `_load_existing_timeline` (line 1227), `_get_cached_schedule` (line 1438), `load_segmented_blocks_from_active_revision` (schedule_items_reader.py:146), PlaylistBuilderDaemon |
| Written by | `write_active_revision_from_compiled_schedule` (schedule_revision_writer.py:155) |
| Authority | Treated as authoritative for what should play and when. INV-TIMELINE-SINGLE-AUTHORITY-001: runtime `_blocks` is populated FROM this, not independently computed. |
| Derivation | Derived from DSL + catalog at compile time. Persisted and reused across restarts. |

One active revision per (channel, broadcast_day). Partial unique index enforces this. Revisions flow: draft → active → superseded. Items carry `compiled_segments` in `metadata_` JSONB — the post-BBL structural representation of break-aware content acts, filler placeholders, transitions, and offsets.

### 1.3 compiled_segments (on ScheduleItem.metadata_)

| Property | Value |
|----------|-------|
| Storage | Postgres: JSONB field on `schedule_items.metadata_["compiled_segments"]` |
| Read by | `_load_existing_timeline` (line 1252), `_get_cached_schedule` (line 1462), `_hydrate_compiled_segments` (schedule_items_reader.py:94), `_expand_blocks_hydrate` (dsl_schedule_service.py:1951) |
| Authority | Canonical structural representation of a block's segments. Authoritative for content offsets, break positions, transitions, gain, primary flag. |
| Derivation | Derived from DSL + catalog + BlockBreakLayout at compile time. Persisted in ScheduleItem metadata. |

**Format:** Flat list of segment dicts, each with `segment_type`, `asset_id`, `duration_ms`, `asset_start_offset_ms`, `transition_in/out`, `gain_db`, `is_primary`.

### 1.4 segmented_blocks (serialized ScheduledBlock dicts)

| Property | Value |
|----------|-------|
| Storage | Transient: in-memory `schedule["segmented_blocks"]` dict during `_compile_day`. Also cached in `_hydrate_schedule` fast path. |
| Read by | `_hydrate_schedule` (line 1853) |
| Written by | `_compile_day` (line 1822): `_serialize_scheduled_block(b) for b in blocks` |
| Authority | Derived from compiled_segments hydration. NOT independently authoritative — always reconstructable from ScheduleItem data. |
| Derivation | Derived from `_expand_schedule_to_blocks` which hydrates `compiled_segments` into `ScheduledBlock` objects, then serialized. |

**Format:** List of block wrapper dicts, each with `block_id`, `start_utc_ms`, `end_utc_ms`, `segments[]`. Each segment uses `asset_uri` (resolved path), `segment_duration_ms`, `asset_start_offset_ms`, transition fields.

**Schema conflict:** `compiled_segments` and `segmented_blocks` are structurally different. Loader functions must detect which format they're processing. This was a source of bugs (see Section 6).

### 1.5 PlaylistEvent (Playlog Plan)

| Property | Value |
|----------|-------|
| Storage | Postgres: `playlist_events` table. Keyed by `block_id`. |
| Read by | `get_block_at` (line 438), `ChannelManager._resolve_plan_for_block`, `EvidenceServicer` |
| Written by | `PlaylistBuilderDaemon._write_to_txlog` (playlist_builder_daemon.py:669), `ensure_block_compiled` (dsl_schedule_service.py:569) |
| Authority | Authoritative for filled blocks (content + ad segments with resolved URIs). INV-PLAYOUT-AUTHORITY-001: blocks MUST NOT be aired without a persisted PlaylistEvent row. |
| Derivation | Derived from ScheduleRevision blocks + traffic fill. Write-once: `INSERT ... ON CONFLICT DO NOTHING`. |

PlaylistEvent carries the fully-filled segment array (ad URIs resolved, loudness applied, transitions set). It is the last persistent artifact before AIR execution.

### 1.6 Runtime _blocks (In-Memory Cache)

| Property | Value |
|----------|-------|
| Storage | In-memory: `DslScheduleService._blocks: list[ScheduledBlock]` |
| Read by | `_find_in_memory_block` (line 715), `get_block_at` (line 430), `_maybe_extend_horizon` (line 869) |
| Written by | `_build_initial` (line 1127), `_maybe_extend_horizon` (line 912) |
| Authority | NOT independently authoritative. Populated from DB (ScheduleRevision) at startup and extended from DSL compilation. Time-to-block resolution uses this exclusively (INV-TIER2-COMPILATION-CONSISTENCY-001). |
| Derivation | Derived from ScheduleRevision hydration or fresh DSL compilation. Lost on restart — rebuilt from DB. |

Thread-safe via `self._lock`. Sorted by `start_utc_ms`. Pruned (blocks >24h old removed). Extended on demand when horizon runs thin.

### 1.7 ProgressionRun (Episode Cursor Anchor)

| Property | Value |
|----------|-------|
| Storage | Postgres: `progression_runs` table |
| Read by | `_apply_sequential_progression` (program_assembly.py:682) via `run_store.load()` |
| Written by | `_apply_sequential_progression` (program_assembly.py:693) via `run_store.create()` |
| Authority | Authoritative for episode sequence anchor point. NOT a mutable cursor — episode index is computed from calendar math against the immutable anchor. |
| Derivation | Source for its own concern (anchor persistence). Created once per (channel, run_id), never modified. |

---

## 2. Startup Behavior

### 2.1 Entry Point

`DslScheduleService._build_initial` (dsl_schedule_service.py:992)

Called once during service startup (idempotency guard at line 1004: if `_blocks` non-empty, return).

### 2.2 Startup Sequence

```
_build_initial()
  │
  ├─ 1. Determine start_date from wall clock + timezone + day_start_hour
  │     (line 1010–1028)
  │
  ├─ 2. _load_existing_timeline(channel_id, start_date, horizon_days, tz_name)
  │     (line 1044)
  │     │
  │     ├─ Queries ScheduleItem JOIN ScheduleRevision WHERE status='active'
  │     │   across full time window (start_date → start_date + horizon_days)
  │     │
  │     ├─ For each item: reads metadata_["compiled_segments"]
  │     │   ├─ Detects format (segment-format vs block-format)
  │     │   ├─ Segment-format → _hydrate_compiled_segments() → ScheduledBlock
  │     │   └─ Block-format → _deserialize_scheduled_block() → ScheduledBlock
  │     │
  │     ├─ Deduplicates by block_id, sorts by start_utc_ms
  │     │
  │     └─ Returns (loaded_blocks, loaded_days, missing_days)
  │
  ├─ 3. For each missing_day (sorted):
  │     │
  │     ├─ Compute effective_day_open_ms using last_loaded_end_ms  ← BUG SOURCE
  │     │   (line 1062: _compute_effective_day_open_ms(day_str, ..., last_loaded_end_ms))
  │     │
  │     ├─ _compile_day(channel_id, day_str, effective_day_open_ms)
  │     │   │
  │     │   ├─ _get_cached_schedule() → check DB for existing active revision
  │     │   │   ├─ If found → _hydrate_schedule() → return blocks (no recompile)
  │     │   │   └─ If not found → fall through to compile
  │     │   │
  │     │   ├─ Read DSL from disk
  │     │   ├─ compile_schedule(dsl, resolver, seed, run_store, resolved_config)
  │     │   ├─ _apply_overlap_push_forward(schedule, effective_day_open_ms)
  │     │   ├─ _expand_schedule_to_blocks(schedule, resolver)
  │     │   ├─ _save_compiled_schedule() → write to DB
  │     │   └─ Return blocks (or [] if write refused)
  │     │
  │     ├─ If blocks == [] (write refused):
  │     │   └─ Fallback: load_segmented_blocks_from_active_revision()
  │     │       → _hydrate_compiled_segments() → ScheduledBlock list
  │     │
  │     └─ Extend loaded_blocks, update last_loaded_end_ms
  │
  ├─ 4. Sort all blocks by start_utc_ms
  │
  └─ 5. Store in self._blocks under lock
```

### 2.3 What Is Trusted vs Validated

| Data | Trusted | Validated |
|------|---------|-----------|
| ScheduleRevision status='active' | Yes — taken as authoritative | No validation beyond status field |
| ScheduleItem.metadata_.compiled_segments | Yes — used directly for hydration | Format detection only (segment-format vs block-format). No content validation. |
| compiled_segments field values (offsets, durations) | Yes — passed through to ScheduledSegment | INV-BLOCK-SEGMENT-CONSERVATION-001: sum(segment_duration_ms) checked against block duration (±40ms tolerance) during `_deserialize_scheduled_block` |
| ProgressionRun anchor | Yes — loaded from DB and used without re-validation | No validation of anchor_date against current schedule structure |

### 2.4 What Triggers Rebuild vs Reuse

| Condition | Behavior |
|-----------|----------|
| Active revision exists for day | Reuse: `_get_cached_schedule` returns cached, `_hydrate_schedule` deserializes |
| No active revision for day | Rebuild: `_compile_day` compiles from DSL, writes to DB |
| Active revision exists but `_compile_day` tries to write | Write refused by `write_active_revision_from_compiled_schedule` (INV-TIMELINE-BOUNDARY-IMMUTABLE-001). Returns `[]`. Fallback to `load_segmented_blocks_from_active_revision`. |
| Active revision superseded via CLI or code | Next startup or horizon extension triggers fresh compile |

### 2.5 Fallback Paths

1. **Primary:** `_load_existing_timeline` → hydrate from DB
2. **If day missing:** `_compile_day` → compile from DSL → write to DB → return blocks
3. **If compile write refused:** `load_segmented_blocks_from_active_revision` → hydrate from existing revision items
4. **If all fail:** Day has no blocks. `_find_in_memory_block` returns None. Viewer gets 503.

---

## 3. Sequencing Ownership

### 3.1 Where Episode Selection Happens

Episode selection occurs at **compile time** inside `_apply_sequential_progression` (program_assembly.py:628).

**NOT** at runtime, NOT at feed time, NOT in PlaylistBuilder.

### 3.2 How "Next Episode" Is Determined

Pure function of:
- `ProgressionRun.anchor_date` (immutable, from DB)
- `ProgressionRun.anchor_episode_index` (immutable, from DB)
- Target `broadcast_day` (compile parameter)
- `placement_days` bitmask (from schedule layer)
- `emissions_per_occurrence` (derived from schedule structure)
- `prior_same_day_emissions` (derived from schedule structure)
- Pool size (number of eligible episodes in catalog)

Formula (program_assembly.py:702–720):
```
raw_index = anchor_episode_index
          + (occurrences × emissions_per_occurrence)
          + prior_same_day_emissions
          + execution_index
```

Where `occurrences = count_occurrences(anchor_date, target_date, placement_days)` — pure arithmetic counting matching days between anchor and target.

### 3.3 Determinism and Persistence

| Property | Status |
|----------|--------|
| Deterministic | Yes. Same inputs always produce same episode index. INV-EPISODE-PROGRESSION-001. |
| Persisted | Anchor only (ProgressionRun). No cursor, no counter. |
| Restart-safe | Yes. INV-EPISODE-PROGRESSION-002: scheduler downtime does not alter selection. |
| Recompile-safe | Yes, if run_id unchanged. INV-EPISODE-PROGRESSION-010: schedule edit preserving run_id continues from existing anchor. |

### 3.4 Risk: Catalog Size Changes

Episode index is computed modulo pool size via exhaustion policy (wrap/hold_last/stop). If catalog changes between compiles (asset added/removed/retired), the same raw_index maps to a different episode. This is by design (pool is authoritative at compile time) but means episode ordering is not perfectly stable across catalog mutations.

---

## 4. Carry-In Computation

### 4.1 Code Paths

**Path 1: `_build_initial` startup loop** (dsl_schedule_service.py:1053–1122)

```python
last_loaded_end_ms = 0
if loaded_blocks:
    last_loaded_end_ms = loaded_blocks[-1].end_utc_ms    # ← GLOBAL HORIZON END
for day_str in sorted(missing_days):
    effective_day_open_ms = self._compute_effective_day_open_ms(
        day_str, ..., last_loaded_end_ms,                 # ← PASSED AS carry-in
    )
    blocks = self._compile_day(channel_id, day_str,
                               effective_day_open_ms=effective_day_open_ms)
    ...
    last_loaded_end_ms = max(last_loaded_end_ms, blocks[-1].end_utc_ms)
```

**Inputs used:** `loaded_blocks[-1].end_utc_ms` — the end time of the LAST block across ALL loaded days in the horizon. This is a **global** value, not per-day.

**Path 2: `_maybe_extend_horizon`** (dsl_schedule_service.py:862–941)

```python
last_end_ms = self._blocks[-1].end_utc_ms
effective_day_open_ms = self._compute_effective_day_open_ms(
    day_str, ..., last_end_ms,
)
```

**Inputs used:** `self._blocks[-1].end_utc_ms` — same pattern. Last block in the entire in-memory timeline.

**Path 3: `_compute_effective_day_open_ms`** (dsl_schedule_service.py:693–713)

```python
return max(broadcast_day_start_ms, prior_block_end_ms)
```

**Pure function.** Takes `prior_block_end_ms` and returns the later of broadcast day start or that value.

**Path 4: `_apply_overlap_push_forward`** (dsl_schedule_service.py:1911–1981)

Called inside `_compile_day` (line 1810). Uses `effective_day_open_ms` to:
- Drop blocks whose `end_ms <= effective_day_open_ms` (fully subsumed)
- Push forward blocks whose `start_ms < effective_day_open_ms`
- Cascade all subsequent blocks to maintain contiguity

### 4.2 Future Data Affecting Past Compilation

**YES — this occurs in Path 1.**

At startup, `_load_existing_timeline` loads blocks across the FULL horizon (e.g., Mar 26–29). The `loaded_blocks` list is sorted by `start_utc_ms`. If Mar 29 has a revision (loaded from DB), `loaded_blocks[-1].end_utc_ms` is the end of Mar 29's last block.

When the loop then compiles Mar 27 (a missing day), it uses `last_loaded_end_ms` = Mar 29's end time as `prior_block_end_ms`. `_compute_effective_day_open_ms` returns `max(Mar 27 start, Mar 29 end)` = Mar 29 end. `_apply_overlap_push_forward` then drops ALL of Mar 27's blocks as "subsumed."

**This is the active bug causing the cheers-24-7 channel to be down.**

The original code had `_load_prior_day_carry_in_end_ms` which queried only the PREVIOUS day's last item. This was replaced with a global `loaded_blocks[-1].end_utc_ms` that spans the entire horizon.

### 4.3 Carry-In Data Sources Summary

| Path | Source of carry-in value | Scope | Correct? |
|------|--------------------------|-------|----------|
| `_build_initial` startup | `loaded_blocks[-1].end_utc_ms` | Global horizon | **NO** — future days suppress past days |
| `_maybe_extend_horizon` | `self._blocks[-1].end_utc_ms` | Global in-memory | Correct for extending — always appending to the END of the timeline |
| `_load_prior_day_carry_in_end_ms` (DELETED) | Prior day's last ScheduleItem | Per-day | Was correct. No longer exists. |

---

## 5. Persistence vs Derivation

| Artifact | Persisted | Recomputed | Reused | Rebuilt When |
|----------|-----------|------------|--------|-------------|
| **DSL YAML** | Filesystem | Never (source of truth) | Always read from disk | Manual edit |
| **ScheduleRevision** | DB (schedule_revisions) | On compile | Across restarts | Superseded + recompile |
| **ScheduleItem** | DB (schedule_items) | On compile | Across restarts | Parent revision superseded |
| **compiled_segments** | DB (JSONB on ScheduleItem) | On compile | Across restarts | Parent revision superseded |
| **segmented_blocks** | Transient (in-memory during compile) | Every compile | Within single compile cycle | Every compile |
| **ProgressionRun** | DB (progression_runs) | Never after creation | Across restarts, recompiles | Only when run_id changes |
| **PlaylistEvent** | DB (playlist_events) | On first request or PlaylistBuilder fill | Across restarts | Deleted if stale (conservation check fails) |
| **_blocks (runtime)** | In-memory only | On startup, on horizon extend | Within single process | Every restart |

---

## 6. Boundary Violations

### 6.1 Future Data Influencing Past Compilation

**Location:** `_build_initial` (line 1057–1064)
**Violation:** `last_loaded_end_ms = loaded_blocks[-1].end_utc_ms` spans entire horizon. When missing days are compiled in sorted order (Mar 27 before Mar 28), the carry-in for Mar 27 uses the end time of Mar 29 (a future day that was already loaded from DB).
**Impact:** All blocks for Mar 27 and Mar 28 dropped as "subsumed." Empty revisions persisted. Channel returns 503.

### 6.2 Mixed Formats (compiled_segments vs segmented_blocks)

**Location:** `_load_existing_timeline` (line 1262), `_get_cached_schedule` (line 1472) — prior to this session's fix.
**Violation:** Functions treated compiled_segments entries (flat segment dicts) as segmented_blocks entries (block wrapper dicts). Checked for `block_id`, `start_utc_ms`, `end_utc_ms`, `segments` keys on segment dicts.
**Status:** Fixed in this session. Format detection now routes to appropriate hydration path.

### 6.3 Hydration Layer Dropping Fields

**Location:** `_hydrate_compiled_segments` (schedule_items_reader.py:118) — prior to this session's fix.
**Violation:** `asset_start_offset_ms` hardcoded to 0. Transition fields, `is_primary`, and `gain_db` fallback not propagated.
**Status:** Fixed in this session.

### 6.4 Multiple Sources of Truth for Block Lookup

**Current state:** Three paths can produce a ScheduledBlock for a given time:

1. `_find_in_memory_block(utc_ms)` → from `_blocks` (in-memory)
2. `_get_filled_block_by_id(block_id)` → from PlaylistEvent (DB)
3. `ensure_block_compiled(channel_id, block)` → fills and persists on demand

The in-memory `_blocks` determines WHICH block covers a time. PlaylistEvent determines the FILLED version. These are not independent sources of truth — PlaylistEvent is keyed by `block_id` from `_blocks`. But if `_blocks` is stale (restart with different compilation), a `block_id` from `_blocks` may not match any PlaylistEvent row, triggering synchronous re-fill.

### 6.5 Empty Revisions Persisted

**Location:** `_compile_day` (line 1831) → `_save_compiled_schedule` → `write_active_revision_from_compiled_schedule`
**Violation:** When `_apply_overlap_push_forward` drops all blocks (due to carry-in bug), the empty `program_blocks` list is persisted as a new active revision with 0 ScheduleItems. This creates a permanent empty revision that blocks future compilation (the revision exists, so the write guard refuses new writes for that day).
**Impact:** Channel permanently broken for that day until manual intervention (supersede via CLI).

### 6.6 PlaylistBuilder Reading from ScheduleRevision Directly

**Location:** PlaylistBuilderDaemon calls `load_segmented_blocks_from_active_revision` (schedule_items_reader.py:146)
**Observation:** PlaylistBuilder reads from the DB (ScheduleRevision) independently of the runtime `_blocks` cache. If the DB has a different revision than what `_blocks` was built from (e.g., a new revision was written after startup), PlaylistBuilder may fill blocks that `_blocks` doesn't know about. This is by design (PlaylistBuilder is authoritative for filling), but creates a consistency window where `_blocks` and PlaylistEvent are out of sync.

---

## 7. Consistency Risks

### 7.1 Skipped Blocks

**Trigger:** Carry-in bug drops all blocks for a day. Empty revision persisted.
**Code path:** `_build_initial` → `_compute_effective_day_open_ms(day, ..., future_day_end)` → `_apply_overlap_push_forward` drops everything.
**Result:** `_blocks` has no entries for the affected day. `_find_in_memory_block` returns None. Viewer gets 503.
**Observed:** Active. cheers-24-7 Mar 27 and Mar 28 have 0-item revisions.

### 7.2 Duplicated Playback

**Trigger:** `_hydrate_compiled_segments` previously hardcoded `asset_start_offset_ms=0`.
**Code path:** All content segments start at file offset 0 regardless of chapter marker position.
**Result:** Cold open replays after first break instead of continuing to act 1.
**Status:** Fixed in this session.

### 7.3 Empty Schedules

**Trigger:** Carry-in bug (7.1) OR write refusal from `write_active_revision_from_compiled_schedule` with no fallback blocks.
**Code path:** `_compile_day` returns `[]`. Fallback `load_segmented_blocks_from_active_revision` loads the empty revision. 0 blocks.
**Result:** Channel down. PlaylistBuilder reports `healthy=False`.

### 7.4 Non-Deterministic Rebuilds

**Trigger:** Catalog mutation between compiles (asset added/removed).
**Code path:** `compile_schedule` → `assemble_schedule_block` → pool query returns different set → different episode at same index.
**Result:** Re-compiling the same day with a changed catalog produces a different schedule. This is by design but means superseding and recompiling changes what airs.

### 7.5 Startup Failures

**Trigger:** No blocks loadable from DB AND no blocks compilable (e.g., all writes refused because empty revisions exist).
**Code path:** `_build_initial` → `_load_existing_timeline` returns 0 blocks → `_compile_day` returns `[]` for every day → `_blocks` remains empty.
**Result:** `_find_in_memory_block` always returns None. Every viewer request fails with "No block for channel at time." Channel permanently down until revisions are manually superseded.
**Observed:** Active. This is the current state of cheers-24-7.

### 7.6 Horizon Extension Race

**Trigger:** `_maybe_extend_horizon` computes `effective_day_open_ms` from `self._blocks[-1].end_utc_ms`, then compiles outside the lock.
**Code path:** If another thread modifies `_blocks` between the read (line 869) and the write (line 912), the effective_day_open_ms may be stale.
**Mitigation:** `_extending` flag prevents concurrent extensions. But the flag is not an atomic CAS — there's a TOCTOU window between the check (line 865) and the set (line 874), both under the same lock acquisition.
**Practical risk:** Low. The flag check and set are within the same `with self._lock` block, making them atomic.

### 7.7 PlaylistEvent / _blocks Divergence

**Trigger:** PlaylistBuilder fills blocks from a newer revision than what `_blocks` was built from.
**Code path:** `get_block_at` finds block B1 in `_blocks` → queries PlaylistEvent by B1.block_id → no match (PlaylistEvent has B2 from newer revision) → synchronous re-fill of B1 → PlaylistEvent now has both B1 and B2.
**Result:** No functional failure (B1 gets filled correctly). But PlaylistEvent accumulates stale rows from old compilations. Mitigated by PlaylistEvent retention policy.

---

## Appendix: Function Reference

| Function | File | Line | Role |
|----------|------|------|------|
| `_build_initial` | dsl_schedule_service.py | 992 | Startup: load timeline from DB, compile missing days |
| `_load_existing_timeline` | dsl_schedule_service.py | 1138 | Load ScheduledBlocks from active ScheduleRevisions |
| `_get_cached_schedule` | dsl_schedule_service.py | 1448 | Check for cached schedule for a single day |
| `_compile_day` | dsl_schedule_service.py | 1755 | Compile a single broadcast day |
| `_hydrate_schedule` | dsl_schedule_service.py | 1844 | Deserialize cached schedule into blocks |
| `_compute_effective_day_open_ms` | dsl_schedule_service.py | 693 | Compute first legal block start time |
| `_apply_overlap_push_forward` | dsl_schedule_service.py | 1911 | Drop/push blocks past carry-in boundary |
| `_expand_schedule_to_blocks` | dsl_schedule_service.py | 1983 | Hydrate compiled_segments into ScheduledBlocks |
| `_find_in_memory_block` | dsl_schedule_service.py | 715 | Time-range lookup in _blocks |
| `get_block_at` | dsl_schedule_service.py | 412 | Public entry: find + fill block at time |
| `ensure_block_compiled` | dsl_schedule_service.py | 446 | Fill and persist a single block |
| `_maybe_extend_horizon` | dsl_schedule_service.py | 862 | Extend _blocks when schedule runs thin |
| `compile_schedule` | schedule_compiler.py | 999 | Compile DSL into program_blocks |
| `_compile_program_block` | schedule_compiler.py | 577 | Compile a single schedule block |
| `_expand_to_compiled_segments` | schedule_compiler.py | 162 | BBL: build layout + expand to segments |
| `_resolve_presentation_ref` | schedule_compiler.py | 301 | Resolve preroll/postroll/midroll from DSL |
| `build_break_layout` | block_break_layout.py | 101 | Build BlockBreakLayout (all break decisions) |
| `expand_break_layout` | block_break_layout.py | 535 | Mechanical expansion of layout to segments |
| `_hydrate_compiled_segments` | schedule_items_reader.py | 74 | Hydrate compiled_segments → ScheduledBlock |
| `load_segmented_blocks_from_active_revision` | schedule_items_reader.py | 146 | Load blocks from active revision items |
| `write_active_revision_from_compiled_schedule` | schedule_revision_writer.py | 155 | Persist compiled schedule to DB |
| `_apply_sequential_progression` | program_assembly.py | 628 | Calendar-based episode selection |
| `PlaylistBuilderDaemon.evaluate_once` | playlist_builder_daemon.py | 136 | Fill playlog plan horizon |
| `ChannelManager._feed_ahead` | channel_manager.py | 2447 | Feed blocks to AIR via gRPC |
