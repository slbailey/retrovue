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
- Tier 2 obligations are derived from channel YAML configuration.
- Tier 2 obligations MUST be evaluated at compile time against block boundaries.
- When an obligation's trigger time falls within a block's time range, the obligation MUST be honored in that block.
- Tier 2 duration MUST be deducted from fill budget (Tier 4), never from primary content (Tier 0).
- Tier 2 segments MUST appear before Tier 0 content in the block's segment sequence.
- Multiple obligations MAY stack within a single block.
- Obligation evaluation MUST be deterministic: same (config + block boundaries) produces same obligations.
- No persisted state is required. See `INV-TIER2-OBLIGATION-YAML-ONLY-001`.

**Existing implementation:** Partial. Station ID is already a structural element within breaks via `BreakConfig.station_id_ms` and `_select_station_id()`. However, station ID placement is currently break-scoped (appears inside each commercial break), not clock-scoped (guaranteed per hour regardless of break placement). No daypart intro or legal ID mechanism exists.

**Delta from current code:**
- New: clock-scoped obligation evaluation at compile time.
- New: obligation injection into `compiled_segments` via a second pass in `compile_schedule()`.
- New: `obligations` section in channel YAML.
- Existing break-scoped station ID via `BreakConfig` is unaffected; Tier 2 obligations are a separate mechanism.

### Tier 3 — Optional Presentation

Content included when budget allows: "coming up next" promo, channel ident, network branding.

**Rules:**
- Tier 3 segments are included only when remaining fill budget after Tiers 0–2 is sufficient.
- Tier 3 segments MAY be dropped without violating any invariant.
- Tier 3 asset selection occurs at compile time.
- "Coming up next" requires next-block program identity, available only after all blocks in a broadcast day are compiled.
- Tier 3 segments MUST NOT displace Tier 0, Tier 1, or Tier 2 content.

**Existing implementation:** None. No concept of optional or budget-conditional presentation exists.

**Delta from current code:**
- New: budget-conditional segment injection.
- New: next-block lookahead for "coming up next" via second pass in `compile_schedule()`.
- New: Tier 3 segment types (e.g., `segment_type="coming_up_next"`, `segment_type="channel_ident"`).

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

Higher-numbered tiers MUST NOT displace lower-numbered tiers. When block time is insufficient for all tiers, displacement occurs bottom-up:

1. Tier 4 (fill) budget is reduced first.
2. Tier 3 (optional presentation) is dropped next.
3. Tier 2 (obligations) is never dropped. If an obligation cannot fit after Tier 0 and Tier 1 are placed, this is a planning fault.
4. Tier 1 (mandatory presentation) is never dropped.
5. Tier 0 (primary content) is never cut or shifted.

This rule is partially enforced today: `INV-PRESENTATION-GRID-BUDGET-001` deducts Tier 1 from the slot budget before break detection, which means Tier 1 displaces Tier 4 fill. `INV-MOVIE-PRIMARY-ATOMIC` prevents Tier 4 from splitting Tier 0.

**Delta:** Formalized as a cross-tier rule. Tiers 2 and 3 displacement behavior is new.

---

## Assembly Sequence

Block assembly produces a segment sequence in this order:

```
[Tier 2: obligations]  [Tier 1: presentation]  [Tier 0: content ± breaks(Tier 4)]  [Tier 3: optional]
```

The assembly sequence maps to the current pipeline as follows:

| Step | What | Current owner | Status |
|---|---|---|---|
| 1. Resolve Tier 1 assets | Intro, rating card from program definition | `assemble_program()` in `program_definition.py` | Implemented |
| 2. Resolve Tier 2 obligations | Clock-triggered segments from config | — | **Not implemented** |
| 3. Resolve Tier 3 candidates | "Coming up next" from adjacent block identity | — | **Not implemented** |
| 4. Compute fill budget | `slot_ms - tier0_ms - tier1_ms - tier2_ms - tier3_ms` | `dsl_schedule_service.py:1544` (Tier 1 only) | Partial |
| 5. Expand Tier 0 with breaks | Content + empty filler placeholders | `expand_program_block()` | Implemented |
| 6. Prepend Tier 1 + Tier 2 | Presentation and obligation segments before content | `dsl_schedule_service.py:1561` (Tier 1 only) | Partial |
| 7. Append Tier 3 | Optional segments after content, before trailing filler | — | **Not implemented** |
| 8. Fill Tier 4 | Replace empty filler with traffic assets | `fill_ad_blocks()` | Implemented |

### Where each step executes

- Steps 1, 5: Inside `_compile_program_block()` via `assemble_schedule_block()` → `expand_program_block()`. Single-block scope.
- Steps 2, 3: Requires a second pass in `compile_schedule()` after all blocks are compiled and compacted. `all_blocks: list[ProgramBlockOutput]` is available at `schedule_compiler.py:856` with full program identity (`title`, `selector["program"]`, `asset_id`) on each block. Next-block identity for "coming up next" is `all_blocks[i+1]`.
- Steps 4, 6, 7: During expansion in `_expand_blocks_inner()`. `schedule["program_blocks"]` is the full day's block list. `block_def["compiled_segments"]` carries Tier 1–3 segments from the compiler.
- Step 8: At playlog plan generation time via `PlaylistBuilderDaemon` or synchronous `ensure_block_compiled()`.

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
| Tier 2 obligation hydration | `_expand_blocks_inner()` alongside existing presentation hydration | Obligation segments in `compiled_segments` are hydrated identically to presentation segments. Budget deduction extends the existing pattern at line 1544. |
| Tier 3 "coming up next" injection | Second pass in `compile_schedule()`, accessing `all_blocks[i+1]` | Next-block program identity is only available after all blocks are compiled and compacted. Cannot be done in the first pass. |
| Tier 3 budget-conditional inclusion | Second pass in `compile_schedule()` | Must compute remaining budget after Tiers 0–2 to decide whether Tier 3 fits. |
| Tier 3 hydration and placement | `_expand_blocks_inner()` | Optional segments in `compiled_segments` are hydrated and placed after content, before trailing filler. |
| Cross-day "coming up next" | `_build_initial()` post-merge pass or omission for day-boundary blocks | Last block of a broadcast day cannot see next day's first block during single-day compilation. Three options: omit, post-merge pass, or query next day's cached ProgramLogDay. |

---

## New Invariants

### INV-TIER-DISPLACEMENT-001 — Higher tiers displace lower tiers

Defined in the Displacement Rule section above.

### INV-TIER2-OBLIGATION-YAML-ONLY-001 — Obligations require no persisted state

Obligation evaluation MUST be deterministic from (channel YAML config + block boundaries). No database state, no fulfillment tracking, no cross-compilation memory is required. The compiler recomputes obligations identically on every compilation of the same broadcast day.

### INV-TIER2-OBLIGATION-COMPILE-TIME-001 — Obligations resolved at compile time

Tier 2 obligation segments MUST be resolved during schedule compilation and stored in `compiled_segments`. Obligation resolution MUST NOT occur at playlog plan generation time, feed time, or runtime.

### INV-TIER3-BUDGET-CONDITIONAL-001 — Optional presentation is budget-conditional

Tier 3 segments MUST be included only when fill budget remaining after Tiers 0–2 exceeds the segment's duration. When budget is insufficient, the segment MUST be omitted without error.

### INV-TIER3-NEXT-BLOCK-IDENTITY-001 — "Coming up next" uses compiled block identity

"Coming up next" MUST reference the next block's program identity as determined by the compiled, compacted block sequence. The identity MUST be resolved during a second pass over `all_blocks` in `compile_schedule()`, after all blocks are compiled and compacted.

### INV-ASSEMBLY-SEQUENCE-001 — Segment ordering follows tier precedence

Within a block's segment sequence, segments MUST appear in this order: Tier 2 obligations, Tier 1 presentation, Tier 0 content (with Tier 4 breaks interleaved), Tier 3 optional presentation. Tier 4 fill occupies break slots within and after Tier 0 content.

---

## Required Tests

`pkg/core/tests/contracts/test_block_assembly_tiers.py`

| Test | Invariant | Scenario |
|---|---|---|
| `test_tier0_never_cut_by_presentation` | `INV-MOVIE-PRIMARY-ATOMIC` | Primary content duration unchanged when Tier 1 presentation is added. |
| `test_tier1_precedes_content` | `INV-PRESENTATION-PRECEDES-PRIMARY-001` | Presentation segments appear before first content segment. |
| `test_tier1_deducted_from_budget` | `INV-PRESENTATION-GRID-BUDGET-001` | Fill budget is slot_ms minus presentation_ms minus content_ms. |
| `test_displacement_tier4_reduced_first` | `INV-TIER-DISPLACEMENT-001` | Adding Tier 2 obligation reduces fill budget, not content duration. |
| `test_displacement_tier3_dropped_before_tier2` | `INV-TIER-DISPLACEMENT-001` | When budget insufficient for both Tier 2 and Tier 3, Tier 3 is omitted and Tier 2 is retained. |
| `test_displacement_tier2_never_dropped` | `INV-TIER-DISPLACEMENT-001` | Tier 2 obligation always present when trigger condition is met, regardless of fill budget. |
| `test_obligation_yaml_only_deterministic` | `INV-TIER2-OBLIGATION-YAML-ONLY-001` | Same config + same block boundaries produce identical obligations across compilations. |
| `test_obligation_no_db_state` | `INV-TIER2-OBLIGATION-YAML-ONLY-001` | Obligation evaluation does not query database or require prior compilation output. |
| `test_obligation_resolved_at_compile_time` | `INV-TIER2-OBLIGATION-COMPILE-TIME-001` | Obligation segments appear in `compiled_segments` after `compile_schedule()` returns. |
| `test_tier3_included_when_budget_sufficient` | `INV-TIER3-BUDGET-CONDITIONAL-001` | "Coming up next" segment present when fill budget exceeds its duration. |
| `test_tier3_omitted_when_budget_insufficient` | `INV-TIER3-BUDGET-CONDITIONAL-001` | "Coming up next" segment absent when fill budget is too small, no error raised. |
| `test_coming_up_next_uses_next_block_title` | `INV-TIER3-NEXT-BLOCK-IDENTITY-001` | "Coming up next" segment references `all_blocks[i+1].title`. |
| `test_coming_up_next_last_block_no_error` | `INV-TIER3-NEXT-BLOCK-IDENTITY-001` | Last block of broadcast day has no "coming up next" segment, no error. |
| `test_segment_order_tiers` | `INV-ASSEMBLY-SEQUENCE-001` | Segment sequence is: obligation, presentation, content, optional. |
| `test_conservation_with_all_tiers` | `INV-BLOCK-SEGMENT-CONSERVATION-001` | Sum of all tier segment durations equals block duration. |

---

## Enforcement Evidence

TODO
