# Timeline Compilation Strategy

> **Terminology note:** Per board feedback, this document uses **Timeline Compilation** (not "block hydration") as the canonical term for the process of transforming editorial placements into execution-ready segment sequences. See Glossary for full terminology alignment.

## Glossary of Terms

| Term                      | Definition                                                                                                                                                                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Timeline Compilation**  | The process of transforming a bare editorial placement ("Cheers at 8:00 PM") into a fully-timed, decorated segment sequence ready for playout — including all continuity elements, breaks, and padding. Replaces the informal term "hydration." |
| **Block**                 | A time-bounded segment of the schedule grid. Not a CRUD entity — it is a computed slice of a ScheduleRevision. A 30-minute episode occupies one grid block; a 2-hour movie spans four.                                                          |
| **Grid Slot**             | The smallest time unit on the channel's EPG grid (typically 30 minutes, set by `grid_minutes`). Blocks snap to grid boundaries.                                                                                                                 |
| **Primary Content**       | The editorial anchor of a block: the movie, episode, or event that the viewer tunes in for. Never cut or shifted. (Tier 0)                                                                                                                      |
| **Presentation**          | Mandatory continuity elements that accompany a specific program: intro sequence, rating card, "Feature Presentation" bumper. Resolved at compile time. (Tier 1). Replaces the informal term "decorations."                                      |
| **Continuity Elements**   | The collective term for all non-primary-content segments that create broadcast flow: presentation, obligations, optional presentation, bumpers, station IDs. Replaces the informal term "decorations."                                          |
| **Obligation**            | Clock- or daypart-triggered content: station ID at top of hour, legal ID, daypart transition intro. Triggered by time-of-day rules, not program identity. (Tier 2)                                                                              |
| **Optional Presentation** | Enrichment content: "coming up next" promo, channel ident, network branding. Compile-time decision, deterministic selection. (Tier 3)                                                                                                           |
| **Fill / Traffic**        | Interstitial content that fills remaining time: commercials, promos, trailers, PSAs. Selected at playlog plan time via traffic policy. (Tier 4)                                                                                                 |
| **Break**                 | A gap in primary content where fill is inserted. Detected by break detection, structured by BreakStructure, filled by TrafficManager.                                                                                                           |
| **Break Budget**          | The total time available for breaks in a block, calculated as: `scheduled_duration - content_duration - presentation_duration`. Breaks expand to consume this budget. Never a fixed value.                                                      |
| **Break Structure**       | The internal shape of a break: bumper → interstitial pool → station ID → bumper. Canonical ordering.                                                                                                                                            |
| **Bumper**                | Short transitional clip marking entry/exit from a commercial break ("We'll be right back" / "And now back to...").                                                                                                                              |
| **Station ID**            | Legal identification clip placed at a structural position within breaks. Not traffic inventory.                                                                                                                                                 |
| **Pad / Padding**         | Silent or filler frames that fill micro-gaps when interstitials don't perfectly exhaust the break budget.                                                                                                                                       |
| **Block Template**        | A named, reusable compilation recipe that defines break *behavior* (placement strategy, density heuristics, continuity elements) — not fixed durations or break counts. Templates adapt to content runtime.                                     |
| **Playout Plan**          | The final, execution-ready segment sequence stored as a PlaylistEvent. Write-once, consumed by ChannelManager → AIR.                                                                                                                            |

***

## Current State Assessment

### What Works Today

RetroVue already has a sophisticated multi-tier block assembly pipeline:

1. **Tier 0 (Primary Content)** — Fully implemented. Movies are atomic (`INV-MOVIE-PRIMARY-ATOMIC`). Episodes resolve from pools with sequential/random/shuffle modes.
2. **Tier 1 (Mandatory Presentation)** — Fully implemented. The `presentation` field on ProgramDefinition supports intro sequences, rating cards. Budget-deducted at compile time. Used by HBO channel for "Feature Presentation" intros.
3. **Tier 4 (Traffic Fill)** — Fully implemented. Break detection → BreakStructure → TrafficManager pipeline with cooldown, caps, rotation, and canonical slot ordering (bumper → interstitial → station\_id → bumper).
4. **Episode Progression** — ProgressionRun anchors with placement\_days and exhaustion\_policy.
5. **Segment Conservation** — `INV-BLOCK-SEGMENT-CONSERVATION-001` ensures no time is lost or created.
6. **Deterministic Compilation** — Seed-based determinism for reproducible schedules.
7. **Break Detection** — `INV-BREAK-001` through `INV-BREAK-012` with chapter marker priority, boundary seams, and algorithmic fallback.

### What's Missing (The Gaps)

1. **No block-level "recipe" abstraction.** Each content type (episodic TV, movie, event) is handled by different code paths, but there's no unified, operator-configurable template.
2. **Tier 2 (Clock/Daypart Obligations) is break-scoped, not clock-scoped.** Station IDs appear inside every commercial break, but there's no guarantee of a station ID at the top of each hour. No daypart transition intros.
3. **Tier 3 (Optional Presentation) does not exist.** No "coming up next," no channel ident between programs, no network branding segments.
4. **No chapter-marker-aware break placement in compilation.** Break detection supports chapter markers (INV-BREAK-002), but the prober doesn't yet extract them during ingest.
5. **No per-block traffic policy override.** Traffic policy is channel-global. Can't say "movie blocks get trailers; sitcom blocks get promos."
6. **No daypart-aware template selection.** Can't automatically change decoration style based on time of day.
7. **Break durations are not derived from a budget formula.** Break count and duration are not cleanly separated.

***

## Runtime Conformance and Adaptive Break Behavior

The following principles are **invariants**, not edge cases. Real broadcast content rarely aligns perfectly with grid slots. The compilation pipeline must handle runtime variance as a first-class concern.

### INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001: Templates Are Behavior, Not Duration

Templates define break *placement strategy* and *continuity element rules* — not fixed break counts or durations. A sitcom template applies identically whether the content is a 22-minute episode, a 44-minute double episode, or a 60-minute special. The template specifies:

* Break density heuristic (e.g., "one break every \~10-12 minutes of content")
* Placement strategy (chapter markers preferred → synthetic fallback)
* Continuity element types (intro, bumper, station ID)

The template does NOT specify:

* Exact break count
* Exact break durations
* Fixed positions (e.g., "break at 11:00")

This prevents template explosion (`sitcom_30`, `sitcom_60`, etc.) and ensures a single template handles runtime variance naturally.

### INV-CONFORMANCE-MANDATORY-001: Compiled Plan Must Match Scheduled Duration

The compiled playout plan must exactly match the scheduled block duration, within frame tolerance (40ms per `INV-BLOCK-SEGMENT-CONSERVATION-001`). This is not new — it strengthens the existing segment conservation guarantee by making it explicit at the compilation entry point:

```
sum(all_segment_durations) == scheduled_block_duration ± 40ms
```

Conformance is verified at every pipeline stage (existing enforcement points in `_expand_blocks_inner`, `fill_ad_blocks`, persistence, deserialization, and feed time).

### INV-BREAK-BUDGET-DERIVED-001: Break Budget Is Derived, Not Fixed

Break time is calculated as:

```
break_budget = scheduled_duration - content_duration - presentation_duration
```

Where:

* `scheduled_duration` \= grid slot allocation for this block
* `content_duration` \= Tier 0 primary content runtime
* `presentation_duration` \= sum of Tiers 1-3 continuity element durations

Breaks expand to consume the full break budget. This replaces any notion of "standard break length" with a derived value that adapts to actual content runtime.

### INV-BREAK-COUNT-DURATION-SEPARATED-001: Break Count and Break Duration Are Independent

The template defines **break density / placement strategy** (where to place breaks). The compiler determines **actual break durations** by distributing the derived break budget across the placed breaks. This separation means:

* Template says: "place breaks at chapter markers, or every \~10 minutes synthetically"
* Compiler says: "3 breaks detected; 8 minutes of break budget; each break gets \~2:40"

Break duration distribution follows `INV-BREAK-BUDGET-EQUAL-001` (equal by default) or weighted distribution when explicitly configured.

### INV-BREAK-DENSITY-SCALES-001: Break Density Scales With Content Runtime

Rather than fixed break counts per template, break density is expressed as a heuristic that scales:

| Content Runtime | Expected Breaks | Rationale                 |
| --------------- | --------------- | ------------------------- |
| \~22 min        | \~2             | Standard half-hour sitcom |
| \~42 min        | \~4             | Standard hour drama       |
| \~85 min        | 4-5             | 90-minute movie           |
| \~110 min       | 5-6             | 2-hour movie              |
| \~140 min       | 6-7             | Epic-length movie         |

The template expresses this as `target_segment_minutes` (e.g., 10-12 for TV, 18-20 for movies). The compiler derives break count from `content_duration / target_segment_minutes`, subject to chapter marker positions when available. This single parameter handles all runtimes without template proliferation.

### INV-BREAK-EXPAND-TO-FILL-001: Breaks Expand to Fill Budget

Breaks must not be fixed-length. After break positions are determined, the break budget is distributed across all breaks. If a block has 6 minutes of break budget and 2 breaks, each break gets 3 minutes — not a "standard" 2 minutes with leftover padding. This is critical for broadcast-style movies where content runtime varies significantly.

Residual micro-gaps (\< 1 segment) after traffic fill are handled by `INV-BREAK-PAD-DISTRIBUTED-001` (existing: leftover time distributed as black pad).

### INV-BREAK-PLACEMENT-PRIORITY-001: Break Placement Has Strict Priority

Break placement follows the existing priority model from `INV-BREAK-002`, formalized here:

1. **Chapter markers** (Priority 1) — If present in asset metadata AND template strategy is `chapter_markers_preferred`, use chapter boundaries as break positions.
2. **Asset boundaries** (Priority 2) — Content-to-content seams in accumulate-mode programs.
3. **Synthetic rules** (Priority 3) — Deterministic fallback using template's `target_segment_minutes`.

Chapter markers suppress algorithmic fallback per `INV-BREAK-PLACEMENT-FALLBACK-001`.

### INV-OVERCONSTRAINED-POLICY-001: Over/Under-Constrained Scenarios Are Defined

When content and schedule don't align, the compiler must follow explicit policy:

**Content longer than slot (overconstrained):**

* **Bleed mode** (existing, `INV-BLEED-NO-GAP-001`): content extends into adjacent slots. No breaks injected. Adjacent blocks shift.
* **Reject mode**: compilation fails with a clear error. Operator must resize the slot or choose different content.
* Mode is set per-template. Default: `bleed`.

**Content shorter than slot (underconstrained):**

* Break budget absorbs the difference (per INV-BREAK-BUDGET-DERIVED-001).
* If break budget exceeds maximum break density (e.g., more break time than content time), compiler inserts interstitials from Tier 3 (optional presentation) first, then expands breaks, then inserts pad.
* **Extreme underrun** (content \< 50% of slot): compiler emits a warning. Operator should review the slot allocation.

### INV-CLOCK-OBLIGATIONS-OVERRIDE-001: Clock-Based Obligations Override Block Structure

Top-of-hour station IDs, legal IDs, and daypart transitions are **timeline-level inserts** — they are not tied to any specific block or template. They are evaluated in the second compilation pass against absolute wall-clock time, not relative block position.

Rules:

* If a clock obligation falls within a break, it is inserted into the break (displacing Tier 4 fill per `INV-TIER-DISPLACEMENT-001`).
* If a clock obligation falls within primary content, the compiler inserts a micro-break at the nearest safe point (respecting `INV-BREAK-009` — no breaks in intro/outro, and `INV-BREAK-003` — protected zone).
* Clock obligations are channel-global configuration, not per-template. Templates can declare which obligation types they participate in, but cannot suppress mandatory obligations.

***

## Proposed Strategy: Block Templates as Compilation Recipes

### Core Concept

Introduce **Block Templates** — named, reusable compilation recipes defined in channel YAML that specify break *behavior* and continuity element *rules* for a given content type or daypart. Templates are NOT new code entities or CRUD objects. They are DSL-level configuration that the existing compilation pipeline interprets.

Templates encode behavior, not duration. A single `sitcom` template handles 22-minute, 44-minute, and 60-minute content identically — the compiler adapts break count and duration dynamically.

### Template Structure (Proposed DSL Syntax)

```yaml
templates:
  sitcom:
    description: "Standard sitcom block"
    continuity:
      presentation:
        - type: intro
          pool: channel_intros
          max_duration_sec: 15
      optional:
        - type: coming_up_next
          pool: coming_up_promos
          max_duration_sec: 30
          position: after_content
    breaks:
      strategy: chapter_markers_preferred
      fallback: synthetic
      target_segment_minutes: 11
      bumpers:
        to_break: { pool: to_break_bumpers, duration_sec: 5 }
        from_break: { pool: from_break_bumpers, duration_sec: 5 }
      station_id:
        pool: station_ids
        duration_sec: 10
      traffic_profile: default
    overconstrained: bleed
    underconstrained: expand_breaks

  movie_premium:
    description: "Premium movie block (HBO/Showtime style — no mid-content breaks)"
    continuity:
      presentation:
        - type: rating_card
          pool: rating_cards
          duration_sec: 10
        - type: feature_intro
          pool: feature_intros
          max_duration_sec: 45
      optional:
        - type: channel_ident
          pool: channel_idents
          duration_sec: 15
          position: after_content
    breaks:
      strategy: none
    trailing:
      - type: interstitial_block
        traffic_profile: movie_trailers

  movie_broadcast:
    description: "Broadcast movie block with commercial breaks"
    continuity:
      presentation:
        - type: rating_card
          pool: rating_cards
          duration_sec: 10
    breaks:
      strategy: synthetic
      target_segment_minutes: 20
      min_segment_minutes: 12
      bumpers:
        to_break: { pool: to_break_bumpers, duration_sec: 5 }
        from_break: { pool: from_break_bumpers, duration_sec: 5 }
      traffic_profile: broadcast_mix
    overconstrained: bleed
    underconstrained: expand_breaks

  creature_feature:
    description: "Late-night horror movie block with themed decoration"
    extends: movie_broadcast
    continuity:
      presentation:
        - type: host_intro
          pool: creature_host_intros
          max_duration_sec: 120
        - type: rating_card
          pool: rating_cards
          duration_sec: 10
      optional:
        - type: host_outro
          pool: creature_host_outros
          max_duration_sec: 90
          position: after_content

  daypart_transition:
    description: "Daypart boundary marker (e.g., Adult Swim transition)"
    content: none
    continuity:
      presentation:
        - type: daypart_intro
          pool: adult_swim_bumps
          max_duration_sec: 60
    breaks:
      strategy: fill_all
      traffic_profile: late_night
```

**Key design points:**

* No `grid_slots` or `break_count` fields — slot sizing is derived from content + continuity + break budget. Break count is derived from `target_segment_minutes` and content runtime.
* `extends` enables composition without duplication.
* `overconstrained` / `underconstrained` policy is explicit per template.
* Continuity elements replace "tiers" in the DSL surface (the tier model remains internal to the compiler).

### Template Resolution Flow (Two-Pass Compilation)

```
DSL YAML (channel config)
    |
Schedule Block references a template by name
    |
FIRST PASS (structural resolution):
  1. Resolve Tier 0 (content from pool)
  2. Resolve Tier 1 (presentation from template continuity)
  3. Calculate break budget: scheduled_duration - content - presentation
  4. Detect break positions (chapter markers → synthetic fallback)
  5. Resolve Tier 3 (optional presentation, next-block lookahead)
  6. Recalculate break budget after Tier 3
  7. Distribute break budget across break positions
    |
SECOND PASS (timeline obligations):
  8. Evaluate Tier 2 obligations against wall-clock time
  9. Insert clock obligations (top-of-hour station ID, legal ID, daypart)
  10. Adjust break budgets to accommodate obligation insertions
    |
compiled_segments (all structural segments resolved, INV-STRUCTURAL-RESOLUTION-001)
    |
EXPANSION (existing _expand_blocks_inner):
  11. Hydrate segments (asset_id → asset_uri)
  12. Sequence tiers in canonical order (INV-ASSEMBLY-SEQUENCE-001)
  13. Insert filler placeholders in breaks
    |
TRAFFIC FILL (existing fill_ad_blocks):
  14. Fill interstitial slots per template's traffic_profile
  15. Fill bumpers per template config
  16. Pad remaining gaps (INV-BREAK-PAD-DISTRIBUTED-001)
    |
CONFORMANCE CHECK:
  17. Verify sum(segments) == scheduled_duration ± 40ms
    |
PlaylistEvent (execution-ready playout plan)
```

### Chapter-Marker-Aware Break Placement

1. **During ingest enrichment**, the prober extracts chapter markers from media files. Store as `probed.chapter_markers` on Asset.
2. **During break detection**, if chapter markers are present AND the template says `strategy: chapter_markers_preferred`, use chapter boundaries as break positions. This leverages the existing `INV-BREAK-002` priority model.
3. **Fallback**: if no chapter markers exist, use the template's `target_segment_minutes` to place breaks at synthetic positions (non-uniform per `INV-BREAK-007`).
4. Backward-compatible: existing channels without templates keep current behavior.

### Break Budget Calculation Example

A 30-minute grid slot with a sitcom template:

```
scheduled_duration:      1800s (30:00)
content_duration:        1320s (22:00) — actual episode runtime
presentation_duration:     15s (intro)
optional_presentation:     30s (coming up next)
-----------------------------------------
break_budget:             435s (7:15)
target_segment_minutes:    11 → 2 breaks detected
break_duration_each:      ~217s (3:37) — budget / break_count
bumper_overhead_each:      10s (5s in + 5s out)
station_id_each:           10s
fill_per_break:           ~197s (3:17) — actual traffic fill
```

For a 44-minute double episode in the same template:

```
scheduled_duration:      3600s (60:00) — 2 grid slots
content_duration:        2640s (44:00)
presentation_duration:     15s
optional_presentation:     30s
-----------------------------------------
break_budget:             915s (15:15)
target_segment_minutes:    11 → 4 breaks
break_duration_each:      ~229s (3:49)
```

Same template. Different runtime. Different break count and duration. Correct behavior.

### Daypart Awareness

Templates can be applied conditionally by time of day:

```yaml
schedule:
  weekday:
    - block:
        start: "06:00"
        end: "22:00"
        title: "Daytime Programming"
        pool: all_episodes
        template: sitcom

    - block:
        start: "22:00"
        end: "22:01"
        template: daypart_transition

    - block:
        start: "22:00"
        end: "06:00"
        title: "Late Night Movies"
        pool: horror_movies
        template: creature_feature
```

***

## What Changes vs. What Stays

| Aspect                | Current                    | Proposed                                        | Change Type              |
| --------------------- | -------------------------- | ----------------------------------------------- | ------------------------ |
| Compilation concept   | Block hydration            | Timeline compilation                            | Terminology alignment    |
| Block assembly tiers  | Tiers 0-1, 4 implemented   | All tiers 0-4                                   | Extension (Tier 2-3 new) |
| Break budget          | Implicit                   | Derived formula (explicit invariant)            | Formalization            |
| Break count           | Partially hardcoded        | Derived from target\_segment\_minutes + runtime | Enhancement              |
| Break duration        | Mixed fixed/derived        | Always derived from budget ÷ count              | Enhancement              |
| Break placement       | Gap-based                  | Chapter-marker-preferred + synthetic fallback   | Enhancement              |
| Decoration config     | Hardcoded per content type | Template-driven from YAML                       | New abstraction          |
| Traffic profiles      | Channel-global             | Per-template override                           | Enhancement              |
| Daypart transitions   | Not supported              | Template-based transition blocks                | New feature              |
| Compilation passes    | Single-pass + expansion    | Two-pass compilation + expansion                | Extension                |
| Grid sizing           | Tier 0-1 only              | All structural tiers (0-3)                      | Extension                |
| DSL syntax            | Pools + schedule blocks    | + templates section                             | Extension                |
| Over/underconstrained | Bleed only                 | Explicit per-template policy                    | New invariant            |

***

## New Invariants Introduced

| ID                                       | Title                                    | Summary                                                                    |
| ---------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------- |
| `INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001` | Templates are behavior, not duration     | Templates adapt to any content runtime; no fixed break counts or durations |
| `INV-CONFORMANCE-MANDATORY-001`          | Compiled plan matches scheduled duration | Strengthens INV-BLOCK-SEGMENT-CONSERVATION-001 at compilation entry        |
| `INV-BREAK-BUDGET-DERIVED-001`           | Break budget is derived                  | `break_budget = scheduled - content - presentation`                        |
| `INV-BREAK-COUNT-DURATION-SEPARATED-001` | Break count and duration are independent | Template sets placement strategy; compiler derives durations               |
| `INV-BREAK-DENSITY-SCALES-001`           | Break density scales with runtime        | `target_segment_minutes` replaces fixed break counts                       |
| `INV-BREAK-EXPAND-TO-FILL-001`           | Breaks expand to fill budget             | No fixed-length breaks; budget distributed proportionally                  |
| `INV-BREAK-PLACEMENT-PRIORITY-001`       | Strict break placement priority          | Formalizes chapter > boundary > synthetic ordering                         |
| `INV-OVERCONSTRAINED-POLICY-001`         | Over/underconstrained policy defined     | Explicit bleed/reject/expand policy per template                           |
| `INV-CLOCK-OBLIGATIONS-OVERRIDE-001`     | Clock obligations override structure     | Timeline-level inserts independent of block/template                       |

***

## Implementation Phases

**Phase A — Foundation (Templates + Derived Break Budget)**

* Add `templates:` section to DSL schema
* Implement break budget derivation formula
* Template resolution in `compile_schedule()` first pass
* `target_segment_minutes` replaces hardcoded break counts
* Contract: `timeline_compilation_templates.md`
* Invariants: `INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001`, `INV-BREAK-BUDGET-DERIVED-001`, `INV-BREAK-COUNT-DURATION-SEPARATED-001`, `INV-BREAK-DENSITY-SCALES-001`, `INV-BREAK-EXPAND-TO-FILL-001`, `INV-CONFORMANCE-MANDATORY-001`

**Phase B — Chapter Markers**

* Extend prober to extract chapter markers during ingest
* Break detection honors chapter markers when template says so (existing `INV-BREAK-002` priority)
* Fallback to synthetic rules when markers absent
* Contract: `chapter_marker_break_placement.md`
* Invariant: `INV-BREAK-PLACEMENT-PRIORITY-001`

**Phase C — Tier 2 Clock Obligations**

* Clock-scoped obligation evaluation in second compilation pass
* Implement per `block_assembly_tiers.md` contract
* Invariants: `INV-TIER2-OBLIGATION-YAML-ONLY-001` (existing), `INV-CLOCK-OBLIGATIONS-OVERRIDE-001`

**Phase D — Tier 3 Optional Presentation**

* "Coming up next" with next-block lookahead in second compilation pass
* Implement per `block_assembly_tiers.md` contract
* Invariants: `INV-TIER3-COMPILE-RESOLUTION-001` (existing), `INV-TIER3-NEXT-BLOCK-IDENTITY-001` (existing)

**Phase E — Per-Template Traffic Profiles + Over/Underconstrained Policy**

* Thread template's `traffic_profile` reference through to TrafficManager
* Block-scoped traffic policy evaluation
* Implement explicit overconstrained/underconstrained handling
* Invariant: `INV-OVERCONSTRAINED-POLICY-001`

***

## Domain Boundary Compliance

All proposed changes live within the **scheduling domain**:

* Templates are DSL configuration (editorial intent)
* Template resolution is compilation (scheduling authority)
* Break rules are planning decisions (scheduling authority)
* Traffic profiles are planning-time configuration (scheduling authority)
* No changes to playout domain — ChannelManager continues to execute segments without tier awareness (`INV-CHANNEL-NO-COMPILE-001`)
* No changes to AIR — it sees BlockPlan segments regardless of how they were assembled
* No changes to ingest domain (except Phase B: chapter marker extraction, which is an ingest enrichment concern)

***

## What This Enables (Operator Experience)

After implementation, an operator can:

1. **Add a new sitcom**: point it at a pool, assign `template: sitcom`, and the system automatically adds intros, places breaks at conventional positions (scaling with runtime), fills with appropriate interstitials.
2. **Add a new movie channel**: assign `template: movie_premium` for HBO-style (no breaks, feature presentation intro, trailing promos) or `template: movie_broadcast` for network-style (commercial breaks every \~20 min).
3. **Handle any runtime**: a 22-min episode, 44-min double, or 60-min special all use the same `sitcom` template. Break count and duration adapt automatically.
4. **Create themed blocks**: extend a base template with themed continuity elements (creature feature host segments, Saturday morning cartoon bumpers).
5. **Handle daypart transitions**: insert transition blocks that mark format changes (Adult Swim style).
6. **Trust chapter markers**: when content has them, breaks land at natural story breaks instead of synthetic positions.
7. **Know what happens when content doesn't fit**: explicit overconstrained/underconstrained policy — no guessing.

All of this follows the same DSL → compile → expand → fill → playout pipeline. No new runtime concepts. No new authority domains. Templates are pure configuration that the existing compilation pipeline interprets.