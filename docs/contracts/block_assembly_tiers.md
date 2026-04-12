# Block Assembly Tiers — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Purpose

Block assembly converts a compiled program block into a fully-timed segment sequence. Multiple categories of content compete for time within a single block: primary content, mandatory presentation, clock-triggered obligations, optional presentation, and traffic fill.

This contract defines the priority ordering, displacement rules, and assembly sequence that govern how these categories share block time. It formalizes behavior that is partially implemented and extends it to cover obligation and optional presentation tiers that do not yet exist.

---

## Existing Enforced Invariants

The following invariants already govern parts of the assembly pipeline. This contract references them; it does not redefine them.

| Invariant | What it governs | Status |
|---|---|---|
| `INV-MOVIE-PRIMARY-ATOMIC` | Primary content MUST NOT be split by filler or breaks | Enforced: `playout_log_expander.py`, `traffic_manager.py` |
| `INV-PRESENTATION-PRECEDES-PRIMARY-001` | Presentation segments MUST appear before primary content | Enforced: `program_definition.py:291`, `dsl_schedule_service.py:1561` |
| `INV-PRESENTATION-GRID-BUDGET-001` | Presentation duration MUST be deducted from grid slot budget | Enforced: `program_definition.py:267`, `dsl_schedule_service.py:1544` |
| `INV-PRESENTATION-NOT-FILLER-001` | Presentation segments MUST NOT be treated as filler | Enforced: `program_definition.py` |
| `INV-PRESENTATION-BREAK-INVISIBLE-001` | Break detection MUST NOT see presentation segments as break opportunities | Enforced: `break_detection.py` |
| `INV-BLOCK-SEGMENT-CONSERVATION-001` | Sum of segment durations MUST equal block duration at every pipeline stage | Enforced: `dsl_schedule_service.py:1576`, `traffic_manager.py:148` |
| `INV-BREAKSTRUCTURE-ORDERED-001` | Break slots MUST follow canonical order: bumper, interstitial, station_id, bumper | Enforced: `break_structure.py:52` |
| `INV-BREAKSTRUCTURE-BUDGET-EXACT-001` | Break slot durations MUST sum to allocated budget | Enforced: `break_structure.py:52` |
| `INV-CHANNEL-NO-COMPILE-001` | ChannelManager MUST NOT compile schedules or fill ads | Enforced: `channel_manager.py` |
| `INV-TIME-TYPE-001` | All ms fields MUST be int | Enforced: `schedule_types.py:608` |

---

## Tier Definitions

### Tier 0 — Primary Content

The program itself: movie, episode, event.

**Rules:**
- Primary content MUST NOT be cut, shifted, or truncated by any other tier.
- Primary content defines the block's editorial anchor.
- `INV-MOVIE-PRIMARY-ATOMIC` is the existing enforcement.

**Existing implementation:** `is_primary=True` on `ScheduledSegment`. `_expand_movie()` produces a single uninterrupted content segment. `_assert_no_filler_before_primary()` rejects filler before primary content.

**Delta from current code:** None. Fully implemented.

### Tier 1 — Mandatory Program Presentation

Content that MUST accompany a specific program: rating card, program intro.

**Rules:**
- Tier 1 segments MUST appear before Tier 0 content within the same block.
- Tier 1 duration MUST be known at compile time.
- Tier 1 duration MUST be deducted from the grid slot budget before break detection runs.
- Tier 1 asset selection occurs at compile time via `assemble_program()`, not at traffic fill time.

**Existing implementation:** `presentation` field on `ProgramDefinition`. `_resolve_presentation_entries()` resolves pool references at compile time. `compiled_segments` carries presentation entries through `ProgramBlockOutput` to `_expand_blocks_inner()`, where they are hydrated and prepended. Budget deduction at `dsl_schedule_service.py:1544`. HBO channel config uses this for intros and rating cards.

**Existing invariants:** `INV-PRESENTATION-PRECEDES-PRIMARY-001`, `INV-PRESENTATION-GRID-BUDGET-001`, `INV-PRESENTATION-NOT-FILLER-001`, `INV-PRESENTATION-BREAK-INVISIBLE-001`.

**Delta from current code:** None. Fully implemented.

### Tier 2 — Clock/Daypart Obligations

Content triggered by time-of-day rules rather than program identity: station ID at top of hour, daypart intro at boundary, legal ID.

**Rules:**
- Tier 2 obligations are derived from channel YAML configuration (`obligations:` section).
- Tier 2 obligations MUST be evaluated in a **second compilation pass** against absolute wall-clock time, after all first-pass structural segments (Tiers 0–1) are resolved and break positions are determined.
- When an obligation's trigger time falls within a block's time range, the obligation MUST be honored in that block.
- Tier 2 duration is structural and is included in grid sizing. It displaces fill time, never primary content.
- Multiple obligations MAY stack within a single block.
- Obligation evaluation MUST be deterministic: same (config + block boundaries) produces same obligations.
- No persisted state is required. See `INV-TIER2-OBLIGATION-YAML-ONLY-001`.
- Clock obligations are channel-global configuration, not per-template. Templates MAY declare which obligation types they participate in but MUST NOT suppress mandatory obligations.

#### Obligation Types

| Type | Trigger | Example |
|------|---------|---------|
| `station_id` | Fixed interval (e.g., every 60 minutes) | FCC station identification at top of each hour |
| `legal_id` | Fixed interval or specific times | Legal identification requirements |
| `daypart_transition` | Specific wall-clock times | Adult Swim transition bump at 22:00 |

#### Obligation YAML Schema

```yaml
obligations:
  - type: station_id
    interval_minutes: 60        # Trigger every N minutes from midnight
    pool: station_ids            # Asset pool for obligation content
    duration_sec: 10             # Obligation segment duration
    mandatory: true              # Cannot be suppressed by templates
  - type: daypart_transition
    trigger_times: ["06:00", "22:00"]  # Specific wall-clock trigger times
    pool: daypart_intros
    max_duration_sec: 60
    mandatory: true
  - type: legal_id
    interval_minutes: 180
    pool: legal_ids
    duration_sec: 15
    mandatory: true
```

#### Obligation Placement Rules (`INV-CLOCK-OBLIGATIONS-OVERRIDE-001`)

Placement depends on where the trigger time falls relative to the block's segment structure:

1. **Trigger within a break:** The obligation MUST be inserted into that break, displacing Tier 4 fill per `INV-TIER-DISPLACEMENT-001`. The break's fill budget is reduced by the obligation's duration.

2. **Trigger within primary content:** The compiler MUST defer the obligation to the nearest eligible placement point. Eligible points, in priority order:
   - (a) The next existing break within the same block
   - (b) The block boundary (appended after the last segment)
   - If no eligible point exists within the block, the obligation attaches to the next block boundary.
   - The compiler MUST NOT insert a micro-break or split primary content to place an obligation (`INV-MOVIE-PRIMARY-ATOMIC`).

3. **Trigger at block boundary:** The obligation MUST appear at the head of the block's segment sequence, before Tier 1 presentation.

4. **Multiple obligations at same trigger time:** Stacked in declaration order from the YAML config.

#### Second Compilation Pass

The second pass operates on the output of the first pass:

```
Input:  compiled blocks with resolved T0, T1 segments and break positions
Config: channel-level obligations[] from YAML

For each block in broadcast day:
  For each obligation in config:
    If obligation triggers within block's [start_utc, end_utc):
      Determine insertion point (break, deferred eligible point, or block head)
      Insert obligation segment into compiled_segments
      Adjust fill budget if inserting into a break

Output: compiled blocks with T0, T1, T2 segments and adjusted break budgets
```

The second pass MUST NOT modify Tier 0 content identity, duration, or ordering. It MUST NOT modify Tier 1 presentation segments. It MAY adjust Tier 4 fill budgets within breaks to accommodate inserted obligations.

**Existing implementation:** Partial. Station ID is already a structural element within breaks via `BreakConfig.station_id_ms` and `_select_station_id()`. However, station ID placement is currently break-scoped (appears inside each commercial break), not clock-scoped (guaranteed per hour regardless of break placement). No daypart intro or legal ID mechanism exists.

**Delta from current code:**
- New: clock-scoped obligation evaluation at compile time (second pass in `compile_schedule()`).
- New: obligation injection into `compiled_segments` with placement-aware insertion logic.
- New: `obligations` section in channel YAML with typed obligation entries.
- New: deferral logic for obligations that trigger within primary content (defers to next break or block boundary).
- Existing break-scoped station ID via `BreakConfig` is unaffected; Tier 2 clock obligations are a separate, additive mechanism.

### Tier 3 — Optional Presentation

Content that enriches the viewing experience: "coming up next" promo, channel ident, network branding.

**Rules:**
- Tier 3 inclusion is a compile-time decision, made BEFORE grid sizing.
- Tier 3 duration is part of the structural total that drives grid block allocation. If Tier 3 causes the structural total to exceed the current grid slot, the grid grows — Tier 3 is NOT dropped to fit.
- Once included, Tier 3 segments are structural — they MUST NOT be added, removed, or modified during expansion. See `INV-TIER3-COMPILE-RESOLUTION-001`.
- Tier 3 asset selection MUST use deterministic selection rules (longest-fitting from pool, seed-based, no uncontrolled RNG). See `INV-TIER3-POOL-DETERMINISTIC-001`.
- "Coming up next" requires next-block program identity, available only after all blocks in a broadcast day are compiled.
- Tier 3 segments MUST NOT displace Tier 0, Tier 1, or Tier 2 content.
- Tier 3 duration is deducted from the break budget BEFORE Tier 4 traffic fill runs. The break budget formula is: `break_budget = scheduled_duration - content_duration - presentation_duration`, where `presentation_duration` includes Tiers 1–3. See `INV-TIER3-BUDGET-BEFORE-FILL-001`.
- Tier 3 elements MUST be declared in a template's `continuity.optional` section. No Tier 3 element may be injected ad-hoc outside of template configuration. See `INV-TIER3-TEMPLATE-DECLARED-001`.

#### Optional Presentation Sub-Types

##### "Coming Up Next" Promo

A promo referencing the next program in the broadcast day. Requires next-block lookahead.

| Property | Value |
|----------|-------|
| `segment_type` | `coming_up_next` |
| Position | After primary content (Tier 0), last among Tier 3 elements |
| Lookahead | Resolved during second compilation pass over `all_blocks[i+1]` |
| Pool | Template-declared promo pool |
| Duration | Selected asset's native duration (pool-filtered by `max_duration_sec`) |
| Last block | Omitted — last block of a broadcast day has no next-block identity. No error. |

**Semantics:**
- The "coming up next" segment MUST reference the next block's program identity as resolved by `compile_schedule()`, after all blocks are compiled and compacted. See `INV-TIER3-NEXT-BLOCK-IDENTITY-001`.
- Asset selection from the promo pool MUST be deterministic: same (pool contents + block seed) produces the same asset. The compiler selects the longest-fitting asset whose duration ≤ `max_duration_sec`.
- Cross-day boundary: the last block of a broadcast day MUST NOT produce a "coming up next" segment. This is not an error; the element is silently omitted.
- The next-block identity is the `title` (or `program_title`) field of the adjacent compiled block. The promo asset carries this identity as metadata, not as part of the asset content.

##### Channel Ident

A short branding segment identifying the channel. Placed at block boundaries.

| Property | Value |
|----------|-------|
| `segment_type` | `channel_ident` |
| Position | After primary content, first among Tier 3 elements |
| Pool | Template-declared ident pool |
| Duration | Selected asset's native duration (pool-filtered by `max_duration_sec`) |

**Placement rules:**
- Channel idents MUST appear between programs — at block boundaries, not mid-content.
- When a block declares a channel ident via its template, the ident segment is placed after Tier 0 content and any interleaved breaks, before any other Tier 3 elements.
- Channel idents MUST NOT be inserted within primary content or within breaks.
- A block MAY declare at most one channel ident.

##### Network Branding

A short network-level branding segment (e.g., network promo, seasonal bumper).

| Property | Value |
|----------|-------|
| `segment_type` | `network_branding` |
| Position | After channel ident (if present), before "coming up next" (if present) |
| Pool | Template-declared branding pool |
| Duration | Selected asset's native duration (pool-filtered by `max_duration_sec`) |

**Placement rules:**
- Network branding MUST appear at block boundaries, not mid-content.
- A block MAY declare at most one network branding segment.
- Network branding is optional — a template MAY omit it entirely.

#### Tier 3 Ordering Within Block

When multiple Tier 3 sub-types are present, they MUST appear in this order after Tier 0 content:

```
[Tier 0 content ± breaks] → [channel_ident] → [network_branding] → [coming_up_next]
```

This ordering is enforced by `INV-ASSEMBLY-SEQUENCE-001`.

#### Compile-Time Resolution (Deterministic Pool Selection)

All Tier 3 asset selection occurs at compile time using deterministic rules. See `INV-TIER3-POOL-DETERMINISTIC-001`.

Selection algorithm:
1. Filter pool assets by `max_duration_sec` (exclude assets longer than the filter value).
2. From the filtered set, select using a deterministic seed derived from `(channel_id, broadcast_day, block_index, element_type)`.
3. The seed computation MUST use the same hashlib-based approach as `INV-SCHEDULE-SEED-DETERMINISTIC-001`.
4. Same inputs MUST produce the same selected asset across compilations.

No uncontrolled RNG (`random.random()`, `random.choice()`) is permitted. Pool selection is a pure function of its inputs.

#### Budget Interaction

Tier 3 optional presentation is structural. Its duration participates in the break budget derivation:

```
break_budget = scheduled_duration - content_duration - tier1_duration - tier2_duration - tier3_duration
```

Tier 3 is deducted BEFORE Tier 4 traffic fill runs. This means:
- Adding a Tier 3 element reduces the available break budget.
- If the structural total (T0 + T1 + T2 + T3) exceeds the current grid slot, the grid grows per `INV-GRID-SIZING-STRUCTURAL-001`. The break budget is then recomputed against the enlarged slot.
- Tier 3 elements are NEVER dropped to preserve break budget. Grid growth is the resolution mechanism.

This is consistent with `INV-TIER-DISPLACEMENT-001`: higher-numbered tiers do not displace lower-numbered tiers, and structural tiers (0–3) all participate in grid sizing.

#### Relationship to Phase C Second Compilation Pass

Tier 3 optional presentation shares the second compilation pass with Tier 2 clock obligations. The pass sequence within `compile_schedule()` is:

```
First pass:  Resolve T0 content, T1 presentation, break positions
Second pass: Evaluate T2 clock obligations (INV-CLOCK-OBLIGATIONS-OVERRIDE-001)
             Then resolve T3 optional presentation (this section)
Grid sizing: Compute slot duration from total structural runtime
```

Tier 3 resolution runs AFTER Tier 2 obligations because:
- "Coming up next" requires all blocks to be compiled and compacted (including any obligation-induced adjustments).
- Channel ident and network branding placement depends on final block boundaries (post-obligation insertion).

Tier 3 MUST NOT modify, reorder, or remove Tier 2 obligation segments. The second pass is ordered: T2 first, then T3. Both are structural and immutable once placed.

#### Template Participation

Tier 3 elements are declared in a template's `continuity.optional` section (see `timeline_compilation_templates.md`):

```yaml
templates:
  sitcom:
    continuity:
      optional:
        - type: channel_ident
          pool: channel_idents
          max_duration_sec: 10
          position: after_content
        - type: coming_up_next
          pool: coming_up_promos
          max_duration_sec: 30
          position: after_content
        - type: network_branding
          pool: network_bumpers
          max_duration_sec: 15
          position: after_content
```

Rules:
- Only templates may declare Tier 3 elements. There is no channel-global Tier 3 mechanism (unlike Tier 2 obligations, which are channel-global).
- A template MAY declare zero, one, or multiple Tier 3 element types.
- The `position` field MUST be `after_content` for all Tier 3 sub-types. Tier 3 elements MUST NOT appear before primary content (that is Tier 1's domain).
- Template inheritance via `extends` applies: a child template inherits the parent's `continuity.optional` unless overridden. List replacement, not merge (per `timeline_compilation_templates.md` composition rules).
- Blocks that reference no template have no Tier 3 elements.

**Existing implementation:** None. No concept of optional presentation exists.

**Delta from current code:**
- New: compile-time conditional segment injection with deterministic asset selection.
- New: next-block lookahead for "coming up next" via second pass in `compile_schedule()`.
- New: Tier 3 segment types (`segment_type="coming_up_next"`, `segment_type="channel_ident"`, `segment_type="network_branding"`).
- New: Tier 3 ordering enforcement within the assembly sequence.
- New: Template `continuity.optional` integration with existing template compilation.
- New: Tier 3 budget deduction before traffic fill.

### Tier 4 — Fill (Traffic Domain)

Promos, commercials, and other interstitial content that fills remaining time.

**Rules:**
- Tier 4 fills time remaining after Tiers 0–3 are placed.
- Tier 4 MUST NOT add time, remove time, or reorder segments placed by higher tiers.
- Tier 4 asset identity is resolved at playlog plan generation time (PlaylistBuilderDaemon), not at compile time.
- `INV-BLOCK-SEGMENT-CONSERVATION-001` governs conservation after fill.

**Existing implementation:** `traffic_manager.fill_ad_blocks()` replaces empty filler placeholders with real assets. `break_structure.build_break_structure()` produces typed slots. `traffic_policy.evaluate_candidates()` enforces allowed types, cooldowns, daily caps, rotation.

**Existing invariants:** `INV-BREAKSTRUCTURE-ORDERED-001`, `INV-BREAKSTRUCTURE-BUDGET-EXACT-001`, `INV-BREAKSTRUCTURE-TRAFFIC-SCOPE-001`.

**Delta from current code:** None. Fully implemented.

---

## Displacement Rule

### INV-TIER-DISPLACEMENT-001

Higher-numbered tiers MUST NOT displace lower-numbered tiers. Tiers 0–3 are all structural and are resolved before grid sizing. Grid block allocation accommodates the total structural runtime.

1. Tier 0 (primary content) is never cut or shifted.
2. Tier 1 (mandatory presentation) is never dropped.
3. Tier 2 (obligations) is never dropped. If the structural total exceeds grid capacity, grid blocks increase.
4. Tier 3 (optional presentation), once included at compile time, is structural. Grid grows to fit.
5. Tier 4 (fill) occupies remaining time after all structural tiers are placed. Fill budget is a consequence of grid sizing, not an input to it.

This rule is partially enforced today: `INV-PRESENTATION-GRID-BUDGET-001` deducts Tier 1 from the slot budget before break detection, which means Tier 1 displaces Tier 4 fill. `INV-MOVIE-PRIMARY-ATOMIC` prevents Tier 4 from splitting Tier 0.

**Delta:** Formalized as a cross-tier rule. Tiers 2–3 as structural (grid-sizing inputs, not fill-budget consumers) is new.

---

## Assembly Sequence

Block assembly produces a segment sequence. The default ordering when obligation trigger times align with block boundaries is:

```
[Tier 2: obligations]  [Tier 1: presentation]  [Tier 0: content ± breaks(Tier 4)]  [Tier 3: optional]
```

When a Tier 2 obligation triggers mid-block (within primary content or a break), it is placed at the trigger point rather than the block head. Obligations that trigger within a break displace Tier 4 fill in that break. Obligations that trigger within primary content are deferred to the nearest eligible placement point (next break or block boundary) per `INV-CLOCK-OBLIGATIONS-OVERRIDE-001`.

The assembly sequence is split across two stages with a strict boundary:

### Stage 1: Compilation (`compile_schedule()`) — resolves structural segments

`INV-STRUCTURAL-RESOLUTION-001`: All T0–T3 segments fully resolved here.

| Step | What | Status |
|---|---|---|
| 1. Resolve Tier 0 content | Episode/movie selection via assembly (first pass) | Implemented |
| 2. Resolve Tier 1 presentation | Intro, rating card from program definition (first pass) | Implemented |
| 3. Resolve Tier 2 obligations | Clock-triggered segments from config (second pass). Evaluates `obligations:` config against block wall-clock boundaries. Determines insertion point per `INV-CLOCK-OBLIGATIONS-OVERRIDE-001`. | **Not implemented** |
| 4. Resolve Tier 3 candidates | "Coming up next" from adjacent block (second pass) | **Not implemented** |
| 5. Size grid allocation | Based on total T0–T3 structural runtime (`INV-GRID-SIZING-STRUCTURAL-001`) | Partial (T0–T1 only) |

Grid sizing is the LAST step of compilation. All structural tiers (T0–T3) MUST be resolved before grid block count is computed. T2/T3 durations that push the structural total past a grid boundary cause additional grid blocks — they are never dropped to fit.

Output: `ProgramBlockOutput` with `compiled_segments` containing all structural segments, `slot_duration_sec` sized to fit them.

### Stage 2: Expansion (`_expand_blocks_inner()`) — sequences and fills

`INV-EXPANSION-NON-MUTATION-001`: Structural segments are read-only. Expansion adds fill only.

| Step | What | Status |
|---|---|---|
| 7. Hydrate structural segments | Resolve `asset_id` to `asset_uri` (file path) | Implemented (Tier 1 only) |
| 8. Compute fill budget | `slot_ms - structural_ms` | Partial (Tier 1 only) |
| 9. Expand Tier 0 with breaks | Content + empty filler placeholders | Implemented |
| 10. Sequence all tiers | Tier-ordered assembly into `ScheduledBlock` | Partial (Tier 1 + 0 only) |
| 11. Fill Tier 4 | Replace empty filler with traffic assets | Implemented |

### Compilation/expansion boundary

- `compile_schedule()` owns WHAT airs and HOW LONG each segment is (editorial authority).
- `_expand_blocks_inner()` owns WHERE segments go in the sequence and WHAT FILLS the remaining time (sequencing + traffic).
- Expansion MUST NOT change asset identity, segment type, or duration of any T0–T3 segment.
- Expansion MAY hydrate `asset_id` to `asset_uri` (path resolution is not editorial).

---

## Component Responsibility Mapping

| Component | Tier 0 | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---|---|---|---|---|
| `schedule_compiler.py` | Selects content via assembly | Delegates to `assemble_program()` | **New:** evaluates obligations | **New:** injects optional segments via second pass | — |
| `program_assembly.py` | Progression, fill_mode | Resolves presentation assets | — | — | — |
| `program_definition.py` | Content assembly | Orders presentation before content | — | — | — |
| `dsl_schedule_service.py` | Expands content + breaks | Hydrates and prepends presentation | **New:** hydrates obligation segments | **New:** hydrates optional segments | Delegates to `fill_ad_blocks()` |
| `playout_log_expander.py` | Break placement within content | — | — | — | Produces empty filler placeholders |
| `traffic_manager.py` | — | — | — | — | Fills placeholders with real assets |
| `break_structure.py` | — | — | — | — | Organizes break internal structure |
| `channel_manager.py` | Executes segments | Executes segments | Executes segments | Executes segments | Executes segments |

ChannelManager executes all tiers identically. It has no tier awareness. `INV-CHANNEL-NO-COMPILE-001`.

---

## Open Implementation Delta

### Already implemented (no work required)

| Capability | Where |
|---|---|
| Tier 0 primary content protection | `INV-MOVIE-PRIMARY-ATOMIC`, `_expand_movie()`, `_assert_no_filler_before_primary()` |
| Tier 1 mandatory presentation | `presentation` on ProgramDefinition, `compiled_segments`, budget deduction |
| Tier 4 traffic fill | `fill_ad_blocks()`, `build_break_structure()`, traffic policy engine |
| Displacement: Tier 1 over Tier 4 | Budget deduction at `dsl_schedule_service.py:1544` |
| Displacement: Tier 0 over Tier 4 | `INV-MOVIE-PRIMARY-ATOMIC` |
| Conservation invariant | `INV-BLOCK-SEGMENT-CONSERVATION-001` at Tier 1 and Tier 2 stages |
| ChannelManager as pure executor | `INV-CHANNEL-NO-COMPILE-001` |
| Deterministic compilation | `INV-SCHEDULE-SEED-DETERMINISTIC-001`, hashlib-based seeds |

### Requires implementation

| Capability | Proposed location | Rationale |
|---|---|---|
| Tier 2 obligation evaluation | Second pass in `compile_schedule()` after compaction, before serialization (`schedule_compiler.py:858–871`) | All block boundaries and program identities are known. Obligation config from channel YAML. Pure function, deterministic. |
| Tier 2 `obligations` YAML schema | Channel YAML `obligations:` section | Follows `traffic.break_config` pattern: frozen dataclass from YAML, consumed by pure functions. |
| Tier 2 obligation hydration | `_expand_blocks_inner()` alongside existing presentation hydration | Obligation segments in `compiled_segments` are hydrated (asset_id → asset_uri path resolution only, per `INV-EXPANSION-NON-MUTATION-001`). Budget deduction extends the existing pattern at line 1544. |
| Tier 3 "coming up next" injection | Second pass in `compile_schedule()`, accessing `all_blocks[i+1]` | Next-block program identity is only available after all blocks are compiled and compacted. Cannot be done in the first pass. |
| Tier 3 compile-time resolution | Second pass in `compile_schedule()` | Tier 3 resolved before grid sizing. Asset selected deterministically from pool. Grid grows to fit. |
| Tier 3 hydration and placement | `_expand_blocks_inner()` | Optional segments in `compiled_segments` are hydrated (path resolution only, per `INV-EXPANSION-NON-MUTATION-001`) and placed after content, before trailing filler. |
| Cross-day "coming up next" | `_build_initial()` post-merge pass or omission for day-boundary blocks | Last block of a broadcast day cannot see next day's first block during single-day compilation. Three options: omit, post-merge pass, or query next day's cached ProgramLogDay. |

---

## New Invariants

### INV-TIER-DISPLACEMENT-001 — Higher tiers displace lower tiers

Defined in the Displacement Rule section above.

### INV-CLOCK-OBLIGATIONS-OVERRIDE-001 — Clock obligations override block structure

Clock obligations MUST be evaluated in a second compilation pass against absolute wall-clock time. When an obligation's trigger time falls within a block, it MUST be honored: inserted into a break (displacing Tier 4 fill), deferred to the nearest eligible placement point if within primary content (next break or block boundary), or prepended at the block head. Clock obligations are channel-global configuration; templates MUST NOT suppress mandatory obligations. See `docs/contracts/invariants/core/block-assembly-tiers/INV-CLOCK-OBLIGATIONS-OVERRIDE-001.md`.

### INV-TIER2-OBLIGATION-YAML-ONLY-001 — Obligations require no persisted state

Obligation evaluation MUST be deterministic from (channel YAML config + block boundaries). No database state, no fulfillment tracking, no cross-compilation memory is required. The compiler recomputes obligations identically on every compilation of the same broadcast day.

### INV-STRUCTURAL-RESOLUTION-001 — Structural segments fully resolved at compilation

All non-fill segments (Tiers 0–3) MUST be fully resolved during `compile_schedule()`, including asset selection and final duration. `compiled_segments` on each `ProgramBlockOutput` MUST contain the complete, ordered set of structural segments with resolved `asset_id` and `duration_ms` values. Supersedes `INV-TIER2-OBLIGATION-COMPILE-TIME-001`.

### INV-GRID-SIZING-STRUCTURAL-001 — Grid allocation based on total structural runtime

Grid block allocation MUST be based on the total runtime of all structural segments (Tiers 0–3). The grid slot duration MUST satisfy: `slot_duration_ms >= sum(segment.duration_ms for segment in compiled_segments)`. Generalizes `INV-PRESENTATION-GRID-BUDGET-001` to all structural tiers.

### INV-EXPANSION-NON-MUTATION-001 — Expansion must not modify structural segments

Expansion MUST NOT modify, re-resolve, reorder, or remove structural segments (Tiers 0–3) produced by `compile_schedule()`. Expansion MAY: hydrate `asset_id` to `asset_uri` (file path resolution), insert fill segments (Tier 4), and sequence structural segments into tier-ordered positions. Expansion MUST NOT change `segment_type`, `asset_id`, or `duration_ms` of any structural segment.

### INV-TIER3-COMPILE-RESOLUTION-001 — Tier 3 segments resolved at compilation

Tier 3 segments, when enabled, MUST be resolved during `compile_schedule()`, including asset selection and duration, using deterministic selection rules. Tier 3 inclusion is decided BEFORE grid sizing — Tier 3 duration is part of the structural total that drives grid block allocation. Once included in `compiled_segments`, Tier 3 segments MUST be treated as structural and MUST NOT be added, removed, or modified during expansion.

### INV-TIER3-NEXT-BLOCK-IDENTITY-001 — "Coming up next" uses compiled block identity

"Coming up next" MUST reference the next block's program identity as determined by the compiled, compacted block sequence. The identity MUST be resolved during a second pass over `all_blocks` in `compile_schedule()`, after all blocks are compiled and compacted.

### INV-STRUCTURAL-TIER-UNIFICATION-001 — All structural tiers follow the same compilation model

All structural tiers (T0–T3) MUST follow the same compilation model: asset selection occurs during `compile_schedule()`, durations are known at compile time, and segments are immutable during expansion. No structural tier receives special treatment. The distinction between tiers governs ordering and editorial intent, not the compilation/expansion boundary.

### INV-TIER3-POOL-DETERMINISTIC-001 — Tier 3 asset selection is deterministic

Tier 3 asset selection from pools MUST be deterministic. The selection seed MUST be derived from `(channel_id, broadcast_day, block_index, element_type)` using the same hashlib-based approach as `INV-SCHEDULE-SEED-DETERMINISTIC-001`. Same inputs MUST produce the same selected asset across compilations. No uncontrolled RNG (`random.random()`, `random.choice()`) is permitted. Pool filtering by `max_duration_sec` occurs before seed-based selection.

### INV-TIER3-BUDGET-BEFORE-FILL-001 — Tier 3 duration deducted before traffic fill

Tier 3 optional presentation duration MUST be deducted from the break budget BEFORE Tier 4 traffic fill runs. The break budget formula is: `break_budget = scheduled_duration - content_duration - tier1_duration - tier2_duration - tier3_duration`. If adding Tier 3 elements causes the structural total to exceed the grid slot, the grid grows per `INV-GRID-SIZING-STRUCTURAL-001`; Tier 3 elements are NEVER dropped to preserve break budget.

### INV-TIER3-TEMPLATE-DECLARED-001 — Tier 3 elements declared in templates only

Tier 3 optional presentation elements MUST be declared in a template's `continuity.optional` section. No Tier 3 element may be injected ad-hoc outside of template configuration. Blocks that reference no template MUST NOT have Tier 3 elements. This ensures all optional presentation is editorially intentional and auditable.

### INV-TIER3-SUBTYPE-ORDER-001 — Tier 3 sub-types follow fixed ordering

When multiple Tier 3 sub-types are present within a block, they MUST appear in this order: `channel_ident`, `network_branding`, `coming_up_next`. This ordering is deterministic and MUST NOT vary based on template declaration order.

### INV-ASSEMBLY-SEQUENCE-001 — Segment ordering follows tier precedence

Within a block's segment sequence, segments MUST appear in this order: Tier 2 obligations, Tier 1 presentation, Tier 0 content (with Tier 4 breaks interleaved), Tier 3 optional presentation (in sub-type order per `INV-TIER3-SUBTYPE-ORDER-001`). Tier 4 fill occupies break slots within and after Tier 0 content.

---

## Required Tests

`server/tests/contracts/test_block_assembly_tiers.py`

| Test | Invariant | Scenario |
|---|---|---|
| `test_tier0_never_cut_by_presentation` | `INV-MOVIE-PRIMARY-ATOMIC` | Primary content duration unchanged when Tier 1 presentation is added. |
| `test_tier1_precedes_content` | `INV-PRESENTATION-PRECEDES-PRIMARY-001` | Presentation segments appear before first content segment. |
| `test_tier1_deducted_from_budget` | `INV-PRESENTATION-GRID-BUDGET-001` | Fill budget is slot_ms minus presentation_ms minus content_ms. |
| `test_structural_tiers_grow_grid` | `INV-TIER-DISPLACEMENT-001` | Adding T2/T3 segments increases grid block count when structural total exceeds slot. |
| `test_fill_is_residual` | `INV-TIER-DISPLACEMENT-001` | Tier 4 fill budget is `slot_ms - structural_ms` — a consequence of grid sizing, not an input to it. |
| `test_structural_tiers_never_dropped` | `INV-TIER-DISPLACEMENT-001` | T0–T3 segments are all present after compilation regardless of fill budget. |
| `test_clock_obligation_in_break_displaces_fill` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Obligation trigger within a break inserts into break and reduces fill budget. |
| `test_clock_obligation_in_content_defers_to_break` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Obligation trigger within primary content defers to nearest eligible break. |
| `test_clock_obligation_in_content_defers_to_boundary` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Obligation trigger within primary content with no subsequent break defers to block boundary. |
| `test_clock_obligation_in_content_deferred_appears_in_output` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Deferred obligation still appears in compiled output (not silently dropped). |
| `test_clock_obligation_at_block_boundary` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Obligation trigger at block start prepends before Tier 1 presentation. |
| `test_clock_obligation_mandatory_not_suppressible` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Mandatory obligation cannot be suppressed by template configuration. |
| `test_clock_obligation_multiple_stack` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Multiple obligations at same trigger time stack in YAML declaration order. |
| `test_clock_obligation_does_not_cut_content` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Obligation insertion never cuts, truncates, or shifts primary content. |
| `test_clock_obligation_second_pass_deterministic` | `INV-CLOCK-OBLIGATIONS-OVERRIDE-001` | Same config + block boundaries produce identical obligation placements across compilations. |
| `test_obligation_yaml_only_deterministic` | `INV-TIER2-OBLIGATION-YAML-ONLY-001` | Same config + same block boundaries produce identical obligations across compilations. |
| `test_obligation_no_db_state` | `INV-TIER2-OBLIGATION-YAML-ONLY-001` | Obligation evaluation does not query database or require prior compilation output. |
| `test_all_structural_segments_resolved_at_compile` | `INV-STRUCTURAL-RESOLUTION-001` | All T0–T3 segments in `compiled_segments` have non-empty `asset_id` and `duration_ms > 0` after `compile_schedule()`. |
| `test_no_structural_placeholder_survives_compile` | `INV-STRUCTURAL-RESOLUTION-001` | No `compiled_segments` entry has empty `asset_id` or zero `duration_ms`. |
| `test_grid_sized_for_structural_total` | `INV-GRID-SIZING-STRUCTURAL-001` | `slot_duration_sec * 1000 >= sum(cs["duration_ms"])` for all structural segments. |
| `test_grid_boundary_push_from_structural` | `INV-GRID-SIZING-STRUCTURAL-001` | T1–T3 durations that push total across grid boundary cause extra grid block allocation. |
| `test_expansion_preserves_structural_identity` | `INV-EXPANSION-NON-MUTATION-001` | After expansion, every structural segment in `ScheduledBlock` matches its `compiled_segments` source in type, asset, and duration. |
| `test_expansion_does_not_add_structural` | `INV-EXPANSION-NON-MUTATION-001` | No structural segment appears in expanded block that was not in `compiled_segments`. |
| `test_expansion_does_not_drop_structural` | `INV-EXPANSION-NON-MUTATION-001` | Every structural segment in `compiled_segments` appears in the expanded block. |
| `test_tier3_resolved_at_compile_time` | `INV-TIER3-COMPILE-RESOLUTION-001` | Tier 3 segments have resolved `asset_id` and `duration_ms > 0` in `compiled_segments` after `compile_schedule()`. |
| `test_tier3_included_in_grid_sizing` | `INV-TIER3-COMPILE-RESOLUTION-001` | Tier 3 duration is part of structural total used for grid block allocation. |
| `test_tier3_immutable_during_expansion` | `INV-TIER3-COMPILE-RESOLUTION-001` | Tier 3 segments in expanded `ScheduledBlock` match source `compiled_segments` exactly. |
| `test_structural_unification_all_tiers` | `INV-STRUCTURAL-TIER-UNIFICATION-001` | T0–T3 all follow same model: asset selected at compile, duration known, immutable in expansion. |
| `test_coming_up_next_uses_next_block_title` | `INV-TIER3-NEXT-BLOCK-IDENTITY-001` | "Coming up next" segment references `all_blocks[i+1].title`. |
| `test_coming_up_next_last_block_no_error` | `INV-TIER3-NEXT-BLOCK-IDENTITY-001` | Last block of broadcast day has no "coming up next" segment, no error. |
| `test_tier3_pool_selection_deterministic` | `INV-TIER3-POOL-DETERMINISTIC-001` | Same pool + seed inputs produce identical Tier 3 asset selection across compilations. |
| `test_tier3_pool_no_uncontrolled_rng` | `INV-TIER3-POOL-DETERMINISTIC-001` | Tier 3 selection does not use `random.random()` or `random.choice()`. |
| `test_tier3_pool_max_duration_filter` | `INV-TIER3-POOL-DETERMINISTIC-001` | Assets exceeding `max_duration_sec` are excluded from selection. |
| `test_tier3_budget_deducted_before_fill` | `INV-TIER3-BUDGET-BEFORE-FILL-001` | Break budget equals `slot - T0 - T1 - T2 - T3` when Tier 3 elements are present. |
| `test_tier3_budget_grid_grows_not_dropped` | `INV-TIER3-BUDGET-BEFORE-FILL-001` | Tier 3 elements cause grid growth rather than being dropped when structural total exceeds slot. |
| `test_tier3_template_declared_only` | `INV-TIER3-TEMPLATE-DECLARED-001` | Block without template has no Tier 3 elements in compiled_segments. |
| `test_tier3_no_adhoc_injection` | `INV-TIER3-TEMPLATE-DECLARED-001` | Tier 3 segments only appear when template `continuity.optional` declares them. |
| `test_tier3_subtype_order_ident_branding_next` | `INV-TIER3-SUBTYPE-ORDER-001` | Tier 3 sub-types appear in order: channel_ident, network_branding, coming_up_next. |
| `test_tier3_subtype_order_partial` | `INV-TIER3-SUBTYPE-ORDER-001` | With only ident + next (no branding), order is still ident then next. |
| `test_channel_ident_after_content_not_mid` | `INV-TIER3-SUBTYPE-ORDER-001`, `INV-ASSEMBLY-SEQUENCE-001` | Channel ident appears after Tier 0 content, not within breaks or mid-content. |
| `test_network_branding_max_one_per_block` | `INV-TIER3-SUBTYPE-ORDER-001` | At most one network branding segment per block. |
| `test_coming_up_next_omitted_last_block` | `INV-TIER3-NEXT-BLOCK-IDENTITY-001` | Last block of broadcast day omits "coming up next" without error. |
| `test_tier3_does_not_modify_tier2` | `INV-EXPANSION-NON-MUTATION-001` | Tier 3 resolution in second pass does not alter existing Tier 2 obligation segments. |
| `test_segment_order_tiers` | `INV-ASSEMBLY-SEQUENCE-001` | Segment sequence is: obligation, presentation, content, optional. |
| `test_conservation_with_all_tiers` | `INV-BLOCK-SEGMENT-CONSERVATION-001` | Sum of all tier segment durations equals block duration. |

---

## Enforcement Evidence

TODO
