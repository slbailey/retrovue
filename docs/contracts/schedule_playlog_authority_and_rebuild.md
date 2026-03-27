# Schedule, Playlog, and Rebuild — Authority Contract

Status: Contract
Version: v0.4
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-CLOCK`, `LAW-DERIVATION`
Grounding Document: `docs/analysis/source_of_truth_current_state.md`

---

## 1. Purpose

This contract defines the authority boundaries, dependency rules, and rebuild semantics for the scheduling and playout pipeline. It governs the relationship between editorial intent (DSL), compiled schedule (ScheduleRevision), execution plan (PlaylistEvent), runtime cache (`_blocks`), and sequence anchor (ProgressionRun).

This contract exists to prevent the following classes of failure:

- **Skipped blocks:** Blocks compiled but dropped before reaching the runtime timeline, leaving time gaps that produce viewer-facing 503 errors.
- **Missed blocks:** Time ranges with no blocks available because empty revisions were persisted and accepted as authoritative.
- **Schedule corruption:** Compiled schedule output influenced by data from a scope other than the target day and its immediate predecessor.
- **Non-deterministic rebuilds:** Schedule recompilation producing different output under unchanged inputs, or producing different output because of illegitimate cross-day influence.
- **Startup failures caused by poisoned persisted state:** Empty or malformed revisions in the database blocking the system from constructing a viable runtime timeline.
- **Runtime state leaking into scheduling:** Playlog, execution artifacts, or runtime cache influencing editorial schedule decisions or episode sequencing.

---

## 2. Authority Model

### 2.1 Editorial Authority — DSL YAML

The DSL YAML file (`config/channels/<channel>.yaml`) is the sole editorial input for schedule compilation. It defines schedule structure, program definitions, content pools, traffic profiles, presentation phases, and midroll configuration.

The DSL is NOT persisted in the database. It is read from the filesystem on every compilation. Editorial changes take effect at the next compilation boundary.

No other artifact may override, supplement, or contradict the editorial intent expressed in the DSL for a given compilation.

### 2.2 Schedule Authority — ScheduleRevision + ScheduleItem

The compiled schedule, persisted as a `ScheduleRevision` with ordered `ScheduleItem` rows, is the authoritative artifact for what content should air and when.

Schedule authority determines:

- Which episodes air on a given broadcast day.
- The start time and duration of each block.
- The structural segmentation of each block (content acts, filler placeholders, transitions, offsets).
- The ordering of blocks within a day.

At most one active `ScheduleRevision` may exist per (channel, broadcast_day). This is enforced by partial unique index.

Schedule authority is produced by compilation and persisted to the database. It survives service restarts. It is the source from which all downstream artifacts (playlog, runtime cache) are derived.

### 2.3 Structural Block Authority — compiled_segments

`compiled_segments`, stored as JSONB on `ScheduleItem.metadata_["compiled_segments"]`, is the canonical persisted structural representation of a block.

It is authoritative for:

- Content act boundaries (`asset_start_offset_ms`).
- Break positions and filler durations.
- Transition types and durations.
- Loudness gain values at compile time.
- Primary content flag (`is_primary`).

`compiled_segments` is the format that hydration consumers MUST read when reconstructing `ScheduledBlock` objects from the database. All fields present in the persisted dict MUST be propagated to the resulting `ScheduledSegment`. No field may be silently dropped or defaulted when a value exists.

### 2.4 Execution Authority — PlaylistEvent

`PlaylistEvent` is the persisted execution-ready artifact. It carries the fully-filled segment array — content with resolved file URIs, ad segments selected by traffic policy, loudness normalization applied, transitions finalized.

PlaylistEvent is authoritative for:

- The exact segments that AIR will execute for a given block.
- Ad fill decisions (which commercials, promos, bumpers fill each break).
- Resolved asset paths.

PlaylistEvent is NOT authoritative for:

- What should air and when (schedule authority).
- Episode sequencing (ProgressionRun authority).
- Block identity or time boundaries (schedule authority).

PlaylistEvent is keyed by `block_id`, which is derived from schedule authority. The relationship is: schedule determines block identity; PlaylistEvent fills that identity with execution-ready content.

PlaylistEvent is write-once per `block_id` (`INSERT ... ON CONFLICT DO NOTHING`). First writer wins.

### 2.5 Runtime Cache — `_blocks`

`DslScheduleService._blocks` is a derived, in-memory, disposable cache. It is populated from schedule authority (ScheduleRevision) at startup and extended from DSL compilation during horizon extension.

`_blocks` is NOT independently authoritative. It MUST NOT be treated as a source of truth after restart without persisted schedule backing. It is the sole mechanism for time-to-block resolution at runtime, but the data it contains is derived from — and must be consistent with — the persisted schedule.

`_blocks` may be discarded and rebuilt at any time from the database without loss of editorial or execution truth.

### 2.6 Sequence Authority — ProgressionRun

`ProgressionRun` is the authoritative anchor for deterministic episode progression. It persists:

- The calendar anchor date.
- The episode index at that anchor.
- The day-of-week placement pattern.
- The exhaustion policy.

Episode selection is a pure function of the ProgressionRun anchor, the target broadcast day, and the current catalog pool size. No mutable cursor, counter, or runtime state is involved.

ProgressionRun is owned by the schedule compilation layer. It is NOT owned by playlog, runtime, or execution. Playlog MUST NOT read, write, or influence ProgressionRun state.

### 2.7 Timeline Reconstruction Principle

No single persisted artifact represents the full authoritative timeline. The runtime timeline is **reconstructed**, not stored. It is assembled from:

- ScheduleRevision + ScheduleItem (schedule authority per broadcast day).
- ProgressionRun (sequence anchor for episode selection during compilation).
- MasterClock / wall-clock time (determines which blocks are current, past, future).

This principle means:

- `_blocks` is a reconstruction, not a copy of stored truth. It may be discarded and rebuilt.
- A partial horizon load (some days loaded, some missing) is an incomplete reconstruction, not an authoritative partial timeline.
- No cached schedule, segmented_blocks dict, or PlaylistEvent row is the timeline. Each is a fragment that contributes to reconstruction.
- The system MUST NOT trust any single fragment as representing the complete timeline state.

---

## 3. Schedule Contract

### 3.1 Editorial Ordering Authority

The schedule is the authoritative editorial ordering artifact. It determines what airs, in what order, at what times, for each broadcast day and channel. All downstream artifacts (playlog, runtime cache, AIR execution) derive from schedule authority.

### 3.2 Deterministic Rebuild

Schedule compilation for a given set of inputs MUST produce identical output. "Same inputs" is defined as:

- Same DSL YAML content.
- Same catalog state (eligible assets, durations, metadata, chapter markers).
- Same ProgressionRun anchor (channel_id, run_id, anchor_date, anchor_episode_index).
- Same compilation parameters (seed, broadcast_day, resolved_config).
- Same applicable prior-day boundary (the end time of the immediately preceding day's last block, if any).

These inputs collectively form the **compilation snapshot**. Deterministic rebuild is guaranteed only relative to a stable compilation snapshot. If any element of the snapshot changes between compilations, the output may legitimately differ.

In particular, catalog mutation (asset addition, removal, retirement, re-enrichment) between compiles may change which episode occupies a given index. This is by design: the catalog is authoritative at compile time, not at schedule-creation time. The system does not persist a catalog snapshot hash; determinism is therefore soft with respect to catalog. Exact rebuild equivalence is guaranteed only when the catalog state is unchanged.

### 3.3 Episode Progression Ownership

Episode sequencing MUST be owned by schedule compilation via ProgressionRun. The episode selected for a given block is determined by the ProgressionRun anchor, the target broadcast day, and the schedule structure (emissions_per_occurrence, prior_same_day_emissions). No other component may override, supplement, or alter this selection.

Episode selection MUST NOT depend on:

- PlaylistEvent content.
- Runtime `_blocks` state.
- As-run logs or execution history.
- PlaylistBuilderDaemon state.
- AIR execution feedback.

### 3.4 Compilation Input Boundaries

Schedule compilation for target day D MUST depend only on:

- The DSL YAML (editorial input).
- The catalog/resolver (asset eligibility, durations, chapter markers, loudness).
- The ProgressionRun anchor (sequence state).
- Compilation parameters (seed, resolved_config, broadcast_day, channel_type).
- The prior-day boundary: the end time of day D-1's last block, subject to the prior-day policy defined in Section 3.5.

Schedule compilation for target day D MUST NOT depend on:

- PlaylistEvent rows for any day.
- Runtime `_blocks` contents.
- The schedule or blocks of day D+1 or any later day.
- A global horizon-end value derived from blocks across multiple days.
- Any value derived from days D+2, D+3, ..., D+N in the horizon.

The prior-day boundary is scoped to the **immediately preceding broadcast day** only. It MUST NOT be derived from a global variable that accumulates across the entire horizon. It MUST NOT be derived from blocks loaded for days after D.

### 3.5 Carry-In Rule

#### 3.5.1 Carry-In Authority

The carry-in boundary for day D is the single value that determines which of D's blocks are dropped or pushed forward to prevent overlap with prior-day content. This value has exactly one legitimate source: the end time of the last block of day D-1's committed schedule.

The carry-in value for day D MUST be derived from day D-1's schedule only. Specifically: the `end_utc_ms` of the last `ScheduleItem` (by `start_time` order) in D-1's active `ScheduleRevision`. If D-1 has no active revision or no items, and D-1 is genuinely unprogrammed, the carry-in is zero (broadcast-day start, no overlap).

#### 3.5.2 Carry-In Application

When day D-1 has a committed schedule whose last block extends past day D's broadcast-day start time, the carry-in boundary for day D is the end time of day D-1's last block. Blocks in day D that would end before this boundary are dropped. Blocks that start before but end after this boundary are pushed forward.

#### 3.5.3 Carry-In Prohibitions

The carry-in value for day D MUST NOT be derived from:

- Day D+1 or any later day.
- A running accumulator that spans days D-2, D-1, D+1, D+2, etc.
- The last block in the entire loaded horizon (e.g., `loaded_blocks[-1].end_utc_ms` when `loaded_blocks` spans multiple days).
- `self._blocks[-1].end_utc_ms` when `_blocks` contains blocks from days beyond D-1.
- Runtime `_blocks` state from a previous compilation.
- Any block whose `start_utc_ms` falls on or after day D's broadcast-day start.

#### 3.5.4 Carry-In Isolation Verification

At the moment carry-in is computed for day D, it MUST be verifiable that the value originates from D-1. If the computation cannot prove D-1 provenance (e.g., the value came from a sorted list containing blocks from multiple days), the computation is invalid.

### 3.6 Missing Prior-Day Policy

When day D-1 has no committed schedule (no active ScheduleRevision with items), the system MUST follow the strict policy:

**Strict policy:** When compiling multiple broadcast days (startup, horizon extension, or batch recompile), compilation MUST proceed in strictly ascending chronological order. Later days MUST NOT be compiled before earlier missing days are resolved. Each day's compilation output provides the prior-day boundary for the next day. This rule applies regardless of which days are missing — the system MUST NOT compile day D before day D-1 is either loaded from DB or freshly compiled.

If day D-1 cannot be compiled (DSL has no schedule for that day, or compilation fails), the carry-in boundary for day D is zero (broadcast-day start). This is acceptable only because D-1 genuinely has no content extending into D.

The system MUST NOT silently assume zero carry-in when D-1 is merely unloaded or missing from the current horizon load. A missing D-1 in the database while the DSL defines programming for D-1 is an incomplete state, not an absence of carry-in. The system MUST compile D-1 first, or fail explicitly.

This prevents the scenario where:
- D-1 exists in the DB but was not loaded (partial horizon load).
- D is compiled with carry-in=0.
- D's blocks overlap D-1's carry-in content.
- Viewer sees duplicate or conflicting content at the day boundary.

### 3.7 Per-Day Compilation Isolation

Compilation of day D MUST be isolated from all days except D-1 (carry-in source only). No data from day D+1 or beyond may influence:

- Whether blocks are retained or dropped during overlap resolution.
- Whether blocks are pushed forward or left at their compiled start times.
- The `effective_day_open_ms` value used for subsumption and push-forward decisions.
- The carry-in boundary value passed to `_compute_effective_day_open_ms` or equivalent.

When the system loads blocks from the database across a multi-day horizon, blocks from days D+1, D+2, ..., D+N MUST NOT be included in any variable, accumulator, or list position that feeds into day D's carry-in or overlap computation.

### 3.8 Subsumption Safety Rule

A block may only be dropped as "subsumed" (fully covered by prior content) if the subsuming content originates from:

- The same broadcast day (an earlier block within day D), OR
- Day D-1's carry-in (the tail of D-1's last block extending into D).

Subsumption of a block on day D by content from day D+1 or any later day is INVALID. A subsumption decision that relies on an `effective_day_open_ms` value derived from a future day is a contract violation.

Specifically: if `_apply_overlap_push_forward` (or equivalent) receives an `effective_day_open_ms` that exceeds day D's broadcast-day end time, the value is provably derived from a future day and the entire subsumption pass is invalid. In this case, the system MUST NOT drop or push any blocks — it MUST either recompute with a correct carry-in or fail explicitly.

### 3.9 Startup Schedule Validation

On startup, after loading the timeline from persisted schedule authority and compiling any missing days, the system MUST validate that every programmed day in the horizon has at least one block in `_blocks`.

If any programmed day has zero blocks after the startup sequence:

- The system MUST detect this condition.
- The system MUST attempt to rebuild that day: supersede any existing (possibly poisoned) revision and recompile from DSL.
- If rebuild succeeds, the day's blocks are added to `_blocks`.
- If rebuild fails, the channel MUST fail fast for that day — refuse to serve content, return explicit error. It MUST NOT silently serve nothing or substitute adjacent-day content.

This validation MUST occur after all compilation and loading is complete, before the channel is marked as ready to serve viewers.

---

## 4. Playlog / Execution Contract

### 4.1 Derived Authority

PlaylistEvent is derived from schedule authority. It takes a scheduled block (identified by `block_id`, with structural segments from `compiled_segments`) and fills it with execution-ready content (ad URIs, loudness, transitions).

### 4.2 Not Editorial Authority

PlaylistEvent is an execution artifact. It MUST NOT be treated as the source of truth for what airs next, what episode plays, or when blocks start and end. These are schedule-layer decisions.

### 4.3 Forward-Only Rebuild

The playlog plan may be rebuilt from an arbitrary wall-clock timestamp T_now going forward. Rebuilding the playlog:

- MUST NOT alter schedule identity (block_id, start/end times).
- MUST NOT alter episode sequence (which episode is in which block).
- MUST NOT alter block structural segmentation (compiled_segments).
- MAY produce different ad fill decisions (different commercials selected) because traffic state changes over time.

### 4.4 Block Identity Linkage

PlaylistEvent rows are keyed by `block_id`. This identifier is derived from schedule authority (deterministic hash of asset_id + start_utc_ms). The relationship is immutable: a PlaylistEvent row corresponds to exactly one scheduled block. Changing the schedule (superseding a revision) invalidates the block_id; the old PlaylistEvent row becomes stale and may be pruned.

A PlaylistEvent MUST be considered valid only if it corresponds to the currently active ScheduleRevision. If the ScheduleRevision that produced the block_id has been superseded, any existing PlaylistEvent for that block_id is stale and MUST NOT be reused for the replacement block. The replacement block will have a different block_id (because the schedule changed), so a new PlaylistEvent is created. Stale PlaylistEvent rows with orphaned block_ids are eligible for pruning.

### 4.5 Execution Readiness

A block MUST NOT be fed to AIR without a persisted PlaylistEvent row. If no PlaylistEvent exists for a block at feed time, the block is filled synchronously and persisted before feeding. If persistence fails, the block MUST NOT be aired.

### 4.6 Segment Completeness

The PlaylistEvent segment array MUST include all fields required by AIR: segment_type, asset_uri, asset_start_offset_ms, segment_duration_ms, transition_in/out and durations, gain_db. No field may be omitted or defaulted to zero when the schedule authority (compiled_segments) carried a non-zero value.

---

## 5. Boundary Rules

### 5.1 Allowed Influence Directions

```
DSL YAML ──────────────────────→ compile_schedule()
                                       │
                                       ▼
catalog/resolver ──────────────→ compile_schedule()
                                       │
                                       ▼
ProgressionRun (anchor) ───────→ compile_schedule()
                                       │
                                       ▼
prior-day boundary (D-1 only) ─→ compile_schedule()
                                       │
                                       ▼
                              ScheduleRevision + ScheduleItem
                                       │
                          ┌────────────┴─────────────┐
                          ▼                          ▼
                    _blocks (cache)          PlaylistBuilderDaemon
                          │                          │
                          ▼                          ▼
                 time-to-block lookup          PlaylistEvent
                          │                          │
                          └──────────┬───────────────┘
                                     ▼
                              get_block_at()
                                     │
                                     ▼
                           ChannelManager._feed_ahead()
                                     │
                                     ▼
                              PlayoutSession → AIR
```

### 5.2 Prohibited Influence Directions

**MUST NOT occur:**

- PlaylistEvent → compile_schedule(). Playlog content MUST NOT influence what episodes are selected or how blocks are structured.
- PlaylistEvent → ProgressionRun. Execution history MUST NOT alter the sequence anchor.
- `_blocks` → compile_schedule(). Runtime cache MUST NOT influence editorial compilation. `_blocks` is consumed by runtime lookup only.
- Day D+1 schedule → Day D compilation. Future-loaded schedule data MUST NOT influence the carry-in, overlap push-forward, or block retention for an earlier day.
- Horizon-global accumulator → per-day compilation. A single value derived from blocks across the entire loaded horizon MUST NOT be used as carry-in for individual day compilation.
- AIR execution feedback → compile_schedule(). What AIR played, how it played, or whether it succeeded MUST NOT influence schedule compilation.
- `_blocks` → startup trust without DB backing. After restart, `_blocks` is rebuilt from the database. It MUST NOT be treated as authoritative from a previous process lifetime.

### 5.3 Empty Revision Prohibition

An active `ScheduleRevision` for a programmed (non-dark) broadcast day MUST NOT be persisted with zero `ScheduleItem` rows. A compilation that produces zero blocks for a day that has a non-empty DSL schedule definition is a compilation failure, not a valid outcome.

The persistence layer MUST enforce this:

- Before writing a new active revision, check whether the compiled `program_blocks` list is empty.
- If empty, and the DSL defines programming for that day, the write MUST be rejected. The persistence function MUST return failure (e.g., return `False`).
- The system MUST NOT fall through to persistence after overlap push-forward drops all blocks. The overlap result MUST be validated before persistence.
- If overlap push-forward produces zero surviving blocks for a programmed day, this is a carry-in computation error, not a valid schedule. The system MUST either recompute with corrected carry-in or fail explicitly.

If a compilation legitimately produces zero blocks (e.g., the DSL defines a dark day with no schedule), an active revision with zero items is acceptable only for that explicit editorial intent.

---

## 6. Rebuild Semantics

### 6.1 Schedule Rebuild

A schedule rebuild replaces the active `ScheduleRevision` for a (channel, broadcast_day) with a newly compiled version.

**When allowed:**

- The existing active revision is superseded (status changed to 'superseded').
- OR no active revision exists for the target day.
- The immutable-boundary guard (`INV-TIMELINE-BOUNDARY-IMMUTABLE-001`) may refuse the write if the existing revision has items that have already started airing (start_time < wall-clock boundary). In that case, the rebuild is refused and the existing revision persists.

**What authority it starts from:**

- DSL YAML (read fresh from disk).
- Catalog/resolver (current asset state).
- ProgressionRun (current anchor, loaded from DB).

**What must remain stable across rebuilds under unchanged inputs:**

- Episode selection for each block (same raw_index, same pool order → same episode).
- Block count and time boundaries (same DSL, same grid → same slot structure).
- Break positions (same chapter markers or DSL midroll → same midroll layout).

**What may legitimately differ if inputs changed:**

- Episode selection if catalog pool membership changed (asset added/removed/retired).
- Break positions if chapter markers changed (re-enrichment).
- Loudness gain values if re-measured.
- Traffic-related presentation segments if presentation pool membership changed.

### 6.2 Playlog Rebuild

A playlog rebuild regenerates PlaylistEvent rows from the current schedule authority.

**When allowed:**

- From any arbitrary wall-clock timestamp T_now going forward.
- Stale or corrupt PlaylistEvent rows may be deleted and regenerated.
- PlaylistBuilderDaemon performs this continuously as part of its fill-ahead loop.

**What it starts from:**

- Active ScheduleRevision for the relevant broadcast days.
- Current catalog state (for URI resolution and loudness).
- Current traffic state (for ad selection, cooldowns, rotation).

**What it MUST NOT change:**

- Schedule identity (block_id, start/end times, episode selection).
- ScheduleRevision content.
- ProgressionRun anchors.
- compiled_segments on any ScheduleItem.

**What may differ on playlog rebuild:**

- Which specific ads fill each break (traffic selection is stateful: cooldowns, rotation counters).
- Ad segment count and individual durations (different commercial inventory available).
- Loudness gain values (if re-measured since last fill).

### 6.3 Startup Rebuild Behavior

On service startup, the system loads the runtime timeline from persisted schedule authority (ScheduleRevision + ScheduleItem). The startup process:

**MUST:**

- Load active revisions from the database for the applicable horizon.
- Hydrate `compiled_segments` into `ScheduledBlock` objects, preserving all persisted fields.
- Populate `_blocks` from the hydrated data.
- Compile missing days from the DSL if no active revision exists for a day in the horizon.

**MUST NOT:**

- Trust `_blocks` from a previous process lifetime (in-memory cache does not survive restart).
- Blindly accept empty active revisions as representing valid schedule state for programmed days. An empty active revision on a programmed day is a poisoned artifact.
- Use future-loaded day data to compute carry-in for earlier-day compilation.
- Persist empty compilation output as a new active revision on a programmed day.

**MUST handle poisoned state deterministically:**

- If an active revision exists but contains zero items for a day that the DSL defines as programmed, the system MUST NOT treat it as authoritative. The system MUST immediately supersede the empty revision and attempt a deterministic rebuild from DSL. If the rebuild succeeds, the new revision replaces the empty one and the channel proceeds. If the rebuild fails (DSL missing, catalog empty, compilation error), the channel MUST fail fast for that day — not silently degrade or serve stale data. The failure MUST be logged at ERROR level with the channel, broadcast day, and reason. "Fail fast" means the channel MUST refuse to serve content for that broadcast day and return an explicit error to viewers. It MUST NOT substitute fallback, stale, or adjacent-day content. Other broadcast days on the same channel are unaffected.
- If `compiled_segments` on a ScheduleItem cannot be hydrated into a valid ScheduledBlock (missing required fields, conservation violation, format error), the system MUST log the failure and skip the item. It MUST NOT propagate invalid data into `_blocks`. If hydration failures result in zero valid blocks for a programmed day, the day MUST be treated as poisoned and the system MUST attempt rebuild for that day. If rebuild also fails, the day fails fast as defined above.
- The system MUST NOT require manual operator intervention (CLI supersede) to recover from an empty revision on a programmed day. Automatic recovery is mandatory. Manual intervention is a fallback for failures that automatic recovery cannot resolve.

---

## 7. Validity and Persistence Rules

### 7.1 Active Revision Non-Emptiness

An active `ScheduleRevision` for a channel+broadcast_day that has a non-empty DSL schedule definition MUST contain at least one `ScheduleItem`. Persisting an active revision with zero items on a programmed day is a contract violation.

### 7.2 Structural Coherence

Persisted `compiled_segments` on a `ScheduleItem` MUST be internally coherent:

- `sum(duration_ms)` across all segments MUST equal `slot_duration_sec * 1000` (within frame tolerance).
- Content segments MUST have non-zero `duration_ms`.
- Content segment `asset_start_offset_ms` values MUST be strictly non-negative and monotonically non-decreasing within a block.
- Segment types MUST be one of the recognized values: `content`, `filler`, `presentation`, `intro`, `outro`.

### 7.3 Execution Artifact Correspondence

A `PlaylistEvent` row MUST correspond to a `block_id` that exists (or existed) in schedule authority. Orphaned PlaylistEvent rows (block_id not traceable to any ScheduleItem) are stale and may be pruned.

### 7.4 Recovery from Poisoned State

Invalid or poisoned persisted artifacts MUST NOT permanently block the system from constructing a viable runtime timeline. Specifically:

- An empty active revision MUST NOT prevent recompilation of that day indefinitely. The system or operator MUST have a mechanism to supersede the empty revision and trigger a fresh compile.
- A malformed `compiled_segments` entry MUST NOT crash the hydration process. The item MUST be skipped with a logged warning, and the system MUST continue processing remaining items.
- A stale PlaylistEvent row (block_id from a superseded revision) MUST NOT prevent a new PlaylistEvent from being created for the replacement block_id.

### 7.5 Schedule Horizon Minimum

At runtime, schedule authority MUST cover at least the configured playlog horizon beyond the current MasterClock time. If schedule coverage falls below this threshold (no blocks available for the time range the playlog needs to fill), the system MUST trigger compilation for the missing days.

If compilation cannot extend coverage (DSL exhausted, compilation failure), the system MUST log the shortfall at WARN level. The channel continues serving content for the time range that IS covered. When coverage reaches zero (no blocks for the current time), the channel fails fast for the affected time range.

The playlog horizon (currently 2–3 hours) defines the minimum useful schedule depth. The schedule compilation horizon (currently multi-day) provides headroom. The invariant is: schedule coverage MUST always be >= playlog horizon depth when programming exists for that time range.

### 7.6 What Constitutes a Contract Violation

The following are contract violations that MUST be detected, logged, and either corrected or reported:

- An active revision with zero ScheduleItems on a programmed day.
- A persisted `compiled_segments` structure that cannot be hydrated into a valid `ScheduledBlock`.
- Schedule authority that cannot support runtime lookup for the time range it claims to cover (e.g., items exist but their compiled_segments are empty or malformed).
- A carry-in computation that uses data from day D+1 or later to suppress blocks on day D.
- A schedule compilation that depends on PlaylistEvent content, runtime `_blocks`, or execution history.
- A ProgressionRun anchor that was modified by a non-compilation component.

---

## 8. Failure Classification

### 8.1 Editorial Change

An editorial change is a legitimate alteration to compilation inputs that may produce a different schedule.

Examples:

- DSL YAML modification (program list, time slots, presentation config, traffic profiles).
- Schedule template restructuring (new schedule layers, changed start times).
- Explicit run_id change or sequence reset by operator.
- Catalog mutation (asset ingestion, retirement, re-enrichment).
- Configuration change (grid_minutes, channel_type, resolved_config).

**Response:** Schedule rebuild for affected broadcast days. Supersede existing active revisions. Recompile from DSL. Playlog rebuild follows automatically (PlaylistBuilder fills from new schedule). ProgressionRun anchor is preserved if run_id is unchanged; new anchor created if run_id changes.

### 8.2 Operational Failure

An operational failure is a system malfunction that produces incorrect artifacts without editorial intent.

Examples:

- Carry-in computation using future-day data to suppress current-day blocks.
- Empty active revision persisted on a programmed day.
- Corrupted runtime `_blocks` cache (stale, incomplete, or inconsistent with DB).
- Failed ad fill producing a PlaylistEvent with incomplete segments.
- Startup hydration failure (compiled_segments cannot be deserialized).
- Format mismatch in loader path (compiled_segments mistaken for segmented_blocks).
- Hydration layer dropping fields (asset_start_offset_ms defaulted to zero when a value exists).

**Response by category:**

| Failure | Response |
|---------|----------|
| Bad carry-in computation | Supersede affected revisions. Recompile with corrected carry-in. |
| Empty active revision on programmed day | Supersede the empty revision. Recompile from DSL. |
| Corrupted runtime cache | Restart service. `_blocks` is rebuilt from DB. No schedule or playlog change needed. |
| Bad PlaylistEvent (incomplete fill) | Delete the stale PlaylistEvent row. PlaylistBuilder or ensure_block_compiled regenerates on next access. |
| Hydration failure on startup | Log, skip affected item. Treat day as having missing blocks. Recompile from DSL for that day. |
| Format mismatch in loader | Fix loader to detect format correctly. Restart. No schedule change needed. |
| Hydration dropping fields | Fix hydration function. Restart. Existing compiled_segments in DB are correct; only the in-memory hydration was wrong. |

**Key distinction:** Operational failures MUST NOT trigger episode progression changes. The ProgressionRun anchor MUST remain unchanged. Recompiling a day after fixing an operational failure MUST produce the same episode sequence as the original (correct) compilation would have, assuming unchanged editorial inputs.

---

## 9. Invariant Seeds

The following candidate invariants are to be formalized in the next step. Each is directly testable.

**INV-AUTHORITY-SINGLE-EDITORIAL-001:** The DSL YAML is the sole editorial input to schedule compilation. No other artifact may override or supplement editorial intent during compilation.

**INV-AUTHORITY-SINGLE-SCHEDULE-001:** At most one active ScheduleRevision exists per (channel, broadcast_day). All downstream artifacts derive from this single authority.

**INV-AUTHORITY-SEQUENCE-OWNERSHIP-001:** Episode selection is determined solely by ProgressionRun anchor + calendar math + catalog pool at compile time. No playlog, runtime, or execution-layer component may read, write, or influence ProgressionRun state.

**INV-COMPILE-NO-FUTURE-INFLUENCE-001:** Schedule compilation for target day D MUST NOT depend on schedule data from day D+1 or any later day. The carry-in boundary for day D is derived from day D-1 only.

**INV-COMPILE-NO-HORIZON-GLOBAL-001:** The carry-in value for a target day MUST NOT be derived from a global variable that accumulates across the entire loaded horizon. It MUST be scoped to the immediately preceding broadcast day.

**INV-RUNTIME-CACHE-DERIVED-001:** `_blocks` is a derived in-memory cache. It MUST NOT be treated as authoritative after restart without persisted schedule backing. It MUST be reconstructable from ScheduleRevision data.

**INV-PLAYLOG-NO-SCHEDULE-MUTATION-001:** PlaylistEvent content MUST NOT influence schedule identity, block identity, episode sequence, or compiled_segments. Playlog is execution-layer only.

**INV-REVISION-NONEMPTY-PROGRAMMED-001:** An active ScheduleRevision for a non-dark programmed day MUST contain at least one ScheduleItem. Persisting a zero-item revision on a programmed day is a contract violation.

**INV-COMPILE-DETERMINISTIC-001:** Schedule compilation under an unchanged compilation snapshot (DSL, catalog, ProgressionRun, parameters, prior-day boundary) MUST produce identical output. Determinism is relative to the snapshot; catalog mutation breaks equivalence.

**INV-COMPILE-PRIOR-DAY-DEPENDENCY-001:** Compilation for day D MUST depend only on D's own inputs and D-1's boundary (if present). If D-1 is missing and the DSL defines programming for D-1, the system MUST compile D-1 first or fail explicitly. The system MUST NOT silently assume zero carry-in when D-1 is merely unloaded.

**INV-PLAYLOG-REBUILD-NO-SEQUENCE-MUTATION-001:** Rebuilding playlog from arbitrary T_now MUST NOT alter schedule identity, block identity, or episode sequence. Only ad fill decisions may differ.

**INV-HYDRATE-FIELD-PRESERVATION-001:** Hydration of compiled_segments into ScheduledSegment MUST propagate every field present in the persisted dict. No field may be silently dropped or defaulted when a value exists.

**INV-CARRY-IN-DAY-MINUS-ONE-ONLY-001:** The prior-day boundary used in carry-in computation for day D MUST be derived from day D-1's last block end time. If D-1 has no committed schedule, the boundary is zero only if D-1 is genuinely unprogrammed.

**INV-STARTUP-POISON-DETECTION-001:** On startup, an empty active revision on a programmed day MUST be detected as invalid. The system MUST automatically supersede it and attempt rebuild. If rebuild fails, the channel MUST fail fast — not silently degrade.

**INV-TIMELINE-RECONSTRUCTION-001:** No single persisted artifact represents the full authoritative timeline. The runtime timeline is reconstructed from ScheduleRevision + ProgressionRun + MasterClock. Partial loads MUST NOT be treated as complete timeline state.

**INV-COMPILE-CHRONOLOGICAL-ORDER-001:** When compiling multiple broadcast days, compilation MUST proceed in strictly ascending chronological order. Later days MUST NOT be compiled before earlier missing days are resolved. Each day's output provides the prior-day boundary for the next.

**INV-PLAYLIST-EVENT-REVISION-VALIDITY-001:** A PlaylistEvent is valid only if its block_id corresponds to the currently active ScheduleRevision. If the originating revision has been superseded, the PlaylistEvent is stale and MUST NOT be reused for the replacement block.

**INV-SCHEDULE-HORIZON-MINIMUM-001:** At runtime, schedule authority MUST cover at least the playlog horizon depth beyond the current MasterClock time. If coverage falls below this threshold, the system MUST trigger compilation for missing days. If compilation cannot extend coverage, the shortfall MUST be logged.

**INV-HYDRATE-DAY-COMPLETENESS-001:** If hydration failures result in zero valid blocks for a programmed day, the day MUST be treated as poisoned and rebuilt. If rebuild also fails, the day fails fast.

**INV-CARRY-IN-AUTHORITY-001:** The carry-in value for day D MUST originate exclusively from the end time of day D-1's last ScheduleItem. The computation MUST be able to prove D-1 provenance. If the value came from a data structure containing blocks from multiple days (e.g., a sorted list spanning the horizon), and the origin day cannot be verified as D-1, the value is invalid.

**INV-COMPILE-DAY-ISOLATION-001:** Compilation of day D MUST be isolated from all days except D-1 (carry-in only). No data from day D+1 or beyond may influence block dropping, push-forward, overlap resolution, or the effective_day_open_ms computation for day D.

**INV-SUBSUMPTION-SAFETY-001:** A block on day D may only be dropped as "subsumed" if the subsuming content originates from day D itself or from day D-1's carry-in. Subsumption by content from day D+1 or later is invalid. If the effective_day_open_ms used for subsumption exceeds day D's broadcast-day end time, the subsumption pass is provably invalid and MUST NOT proceed.

**INV-PERSISTENCE-GUARD-NONEMPTY-001:** The persistence layer MUST reject writes of active revisions with zero ScheduleItems when the DSL defines programming for that day. The check MUST occur before the write, not after. If overlap push-forward produces zero surviving blocks, the system MUST NOT persist the empty result — it MUST either recompute or fail.

**INV-STARTUP-DAY-COVERAGE-001:** After startup completes (timeline loaded + missing days compiled), every programmed day in the horizon MUST have at least one block in `_blocks`. If any programmed day has zero blocks, the system MUST attempt rebuild. If rebuild fails, the channel MUST fail fast for that day before being marked ready to serve.
