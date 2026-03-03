# Program Template Assembly — v1.0

**Status:** Foundational Contract
**Version:** 1.0

**Classification:** Domain (Content Assembly)
**Authority Level:** Planning (Tier 2 Resolution)
**Governs:** Template definition, segment composition, template resolution lifecycle, duration enforcement, selection rule evaluation
**Out of Scope:** Schedule slot assignment, frame timing, ad decisioning, runtime execution

---

## Domain — Program Template Assembly

### Purpose

Program Template Assembly is a declarative content assembly model. It defines the segment composition system applied at Tier 2 (Playlog horizon) to construct ordered playout segments from structural definitions.

Templates are not a scheduling authority. They do not assign time windows or influence grid geometry. Schedule Manager owns slot boundaries and schedulable entry assignment. Templates operate strictly within those boundaries.

Program Template Assembly is responsible for:

- Declaring the internal structure of a program event as an ordered list of segments.
- Resolving that list into concrete, ordered playout segments during Tier 2 materialization.
- Enforcing duration constraints against the schedule-assigned time window.
- Surfacing resolution failures explicitly to the operator.

---

### Tier model

Two tiers govern the lifecycle of a scheduled program event. Templates interact with both but are resolved only at Tier 2.

#### Tier 1 — Schedule horizon

- Commits time windows to the broadcast grid.
- Commits the schedulable entry type for each scheduled event (template, pool, or asset reference).
- May commit an EPG title for the event via the `epg_title` property of the schedule entry. If no `epg_title` is declared, EPG identity is deferred to Tier 2 derivation from the resolved primary content asset.
- Does not resolve template internals. Segment definitions, selection rules, and asset references are opaque at Tier 1.
- Immutable after build. Tier 1 commitments are not modified unless the operator explicitly triggers a rebuild of the affected schedule window.

#### Tier 2 — Playlog horizon

- Resolves the referenced schedulable entry into concrete, ordered playout segments.
- Applies selection rules within each template segment in declared segment order.
- Resolves each segment to a concrete asset reference.
- Derives EPG identity from the resolved primary content asset when no EPG title is committed at Tier 1.
- May re-randomize content selections on each Tier 2 build until the playout window becomes active. Non-determinism is permitted only before activation.
- Becomes immutable once the playout window enters the active execution window. No further re-resolution occurs after activation.

The boundary between Tier 1 and Tier 2 is a resolution boundary. Tier 1 stores what will air and when. Tier 2 resolves how the airing is internally structured.

---

### Template definition model

Templates live in channel configuration. The `templates` key in channel configuration is a mapping (dictionary) keyed by template ID. Each entry in the mapping is a complete template definition. Template IDs are unique within a channel and serve as the reference identifier for schedule assignments.

Templates are structural definitions. A template describes the internal composition of a program event as an ordered list of segments. Templates do not contain asset bytes, playback instructions, or execution-level detail.

Templates consist of an ordered list of segments. Each segment resolves to exactly one asset. Segments are processed in declared order. There is no tree structure, no nesting, no template inclusion, and no recursion. The segment list is the complete definition of the template's internal structure.

Templates are declarative. They describe structure, not procedure. Resolution processes segments sequentially and produces a flat, ordered sequence of concrete asset references. The segment list is the definition; the asset sequence is the output.

---

### Segment definition model

Templates consist of an ordered list of segments. Each segment is a declarative resolution unit that resolves to exactly one asset.

Each segment consists of:

- **source** — The content source from which the segment resolves an asset. The source specifies:
  - `type`: One of `collection` or `pool`. No other source types are permitted. The `primary_content` source type is retired and MUST NOT be used.
  - `name`: The identifier of the collection or pool.
- **primary** (optional) — Boolean. When `true`, marks this segment as the primary content segment for the template. At most one segment per template MAY be marked `primary: true`. See "Primary content definition" for the full detection rules.
- **selection** (optional) — An ordered list of selection rules applied to filter the source's candidate asset set before the mode strategy is applied. Rules operate on asset metadata. All rules MUST be valid metadata expressions against the declared source. An invalid or unresolvable selection rule is a hard resolution failure.
- **mode** — The selection strategy applied after filtering. `random` selects uniformly at random from the filtered candidate set. The mode determines which single asset is emitted.

---

### Primary content definition

Primary content is the segment that resolves to the main content asset of the program event.

Templates MUST resolve exactly one primary content segment per iteration. The primary content segment is the segment whose resolved asset constitutes the program event as a viewing unit — the feature film, episode, or primary editorial asset. Exactly one primary segment is required. It is used for EPG identity derivation when Tier 1 `epg_title` is `None`.

Failure to resolve the primary content segment is a hard resolution failure. There is no fallback and no partial resolution.

The primary content segment is identified as follows (see `INV-TEMPLATE-PRIMARY-SEGMENT-001`):

1. **Explicit flag.** If exactly one segment has `primary: true`, that segment is the primary content segment. If more than one segment has `primary: true`, the template is invalid (compile error).
2. **Convention.** If no segment has `primary: true` and exactly one segment has `source.type == "pool"`, that pool segment is the primary content segment by convention.
3. **Ambiguous.** If no segment has `primary: true` and the template has zero pool segments or multiple pool segments, the template is invalid (compile error). The operator must disambiguate by setting `primary: true` on exactly one segment.

---

### Duration invariants

Duration validation applies to scheduled slot entries — schedule entries of type `template`, `pool`, or `asset` that occupy a fixed, pre-allocated time window. For such entries, template resolution MUST NOT produce a total segment duration that exceeds the assigned slot duration. Overrun is a hard failure condition. A resolved template whose total duration exceeds the slot boundary MUST be rejected. The failure is surfaced to the operator as a resolution error.

Underfill is permitted. A resolved template whose total duration is less than the scheduled time window is valid. The difference between resolved duration and slot duration is handled externally. The template does not pad, stretch, or otherwise compensate for underfill.

Duration validation occurs at resolution time (Tier 2). Tier 1 stores only the schedulable entry reference and the slot duration; it does not validate internal segment duration at build time.

Iterative window entries — schedule entries whose time window accommodates multiple sequential iterations of the same schedulable entry — are not subject to per-iteration slot validation by the template layer. Capacity gating and bleed semantics for iterative windows are governed exclusively by `INV-SCHED-WINDOW-ITERATION-001` at the scheduling layer. Template resolution does not inspect window boundaries, iteration counts, or bleed configuration.

---

### Selection rule evaluation

Segments within a template may declare selection rules. Selection rules filter the candidate asset set produced by the segment's source before the mode strategy is applied.

Selection rules may inspect:

- **Asset metadata.** Tag membership, content type, era, rating, and format properties of candidate assets.
- **Source-level constraints.** Pool or collection constraints (e.g., `max_duration_sec`) are applied by the source before selection rules are evaluated.

Selection rules are evaluated independently per segment. Rules from one segment do not propagate to other segments.

Multiple rules on a single segment are evaluated conjunctively. There is no else branch, no multi-way dispatch, and no fallback selection in v1.

The architecture MUST support future additive rule stacking and compound boolean evaluation. The v1 model does not implement these but MUST NOT preclude them.

---

### Resolution lifecycle

Resolution occurs during Tier 2 materialization. When the Playlog horizon extends and a new playout window is generated, each scheduled event's template reference is resolved into concrete, ordered segments.

Resolution MUST NOT mutate template definitions. Templates are read-only inputs to the resolution process. Any state produced during resolution (concrete asset references, selection evaluation results) is output state, not modification of the source template.

Resolution processes segments sequentially:

1. For each segment, in declared order:
   - Apply source-level constraints to the candidate set.
   - Apply declared selection rules to filter the candidate set.
   - Apply the mode strategy to select one asset from the filtered candidate set.
   - Emit the resolved asset reference.
   - Accumulate the resolved asset's duration.
2. Validate total accumulated duration against the slot duration, when the template is resolved against a fixed scheduled slot entry.
3. Derive EPG identity from the resolved primary content asset if no EPG title is committed at Tier 1.

Resolution is deterministic within a single Tier 2 build session. Given identical inputs (template definition, available assets, channel context), resolution produces identical output. Randomized selection uses a session-scoped seed. The seed MUST be stable for a given scheduled event within a single Tier 2 horizon build. A horizon build is one invocation of the Playlog horizon extension for a specific channel and time window. Daemon restarts or system restarts that trigger a new horizon build produce a new session and a new seed.

Once the playout window becomes active (enters the locked execution window), the resolved output is frozen. No re-resolution, re-randomization, or re-evaluation occurs after activation.

---

### Failure behavior

Templates may fail resolution. Failure conditions include:

- A segment cannot resolve to a valid asset (no eligible content after filtering, resolver miss, asset not approved).
- The primary content segment fails to resolve.
- A selection rule references an invalid or unavailable metadata property.
- Resolved total duration exceeds the scheduled time window for fixed-slot entries.

Failure is explicit. A template that fails resolution produces no output. There is no partial resolution, no silent substitution, and no fallback to a default template.

Failures are comparable to compile-time validation errors. The template definition is the source; resolution is compilation; a failure means the source is invalid for the given context. The system does not emit a best-effort result.

Failures MUST surface to the operator. The resolution failure, its cause, the affected template ID, the affected channel, and the affected time window are reported through operator-visible channels. Silent failure is prohibited.

---

### Scheduling authority

Schedule entries are the authoritative scheduling unit. All schedule entries conform to a single canonical schema. There is no distinct entry type for iterative or block scheduling; iteration behavior is governed by scheduling-layer policy applied uniformly to all entry types.

#### Canonical entry schema

Every schedule entry contains the following fields:

- **type** — Required. One of `template`, `pool`, or `asset`. Determines how the entry resolves content.
- **name** — Required when `type` is `template` or `pool`. The identifier of the referenced template or pool. Not present for `type: asset`.
- **id** — Required when `type` is `asset`. The asset identifier. Not present for `type: template` or `type: pool`.
- **start** — Required. The start boundary of the scheduled time window in `HH:MM` format.
- **end** — Required. The end boundary of the scheduled time window in `HH:MM` format. An end value earlier than or equal to start denotes a window that crosses midnight.
- **epg_title** — Optional. If declared, this string is committed as the EPG identity for the event at Tier 1 and is authoritative. If absent, EPG identity is derived from the resolved primary content asset at Tier 2.
- **allow_bleed** — Optional. Boolean. Defaults to `false`. Governs whether the final program event begun within the window may complete past the window's end boundary. Evaluated exclusively by the scheduling layer. The template layer has no visibility into this field.
- **mode** — Optional. Valid only for `type: pool` entries. Declares the asset selection strategy applied to the pool candidate set. MUST NOT appear on `type: template` or `type: asset` entries.

No other fields are permitted on schedule entries. Injecting selectors, pool references, asset filters, or mode values into a `type: template` entry is prohibited.

#### Schedulable entry types

- **type: template** — References a named template by `name: <template_id>`, resolved against the channel's `templates` registry. The template owns its internal segment definitions and selection rules. The schedule entry does NOT inject selectors, mode values, pool references, or asset filters into the template.
- **type: pool** — References a named pool directly by `name: <pool_id>`. The pool definition governs the candidate asset set. The `mode` field on the schedule entry declares the selection strategy.
- **type: asset** — References a specific asset by `id`. No selection occurs. The referenced asset is the direct output of resolution.

Templates are self-contained. Segment composition, selection rules, and mode strategies are properties of the template definition. The schedule entry commits the template reference; it does not override or augment the template's internal resolution logic.

Templates do not influence slot duration. The schedule layer assigns time windows. Templates operate within those windows. A template cannot request a longer or shorter slot.

The schedule layer owns time boundaries. Slot start time, slot end time, and slot duration are schedule-layer commitments made at Tier 1. Templates have read-only visibility into slot duration for the purpose of duration validation. They have no write access to schedule state.

Templates MUST conform to schedule constraints. A template that cannot produce valid output within the assigned slot duration is a resolution failure, not a schedule modification request.

#### Iteration and bleed semantics

The scheduling layer governs whether a schedule entry is applied once (fixed-slot) or iteratively (repeating within the window). This distinction is not expressed in the entry schema; it is determined by the scheduling layer's window iteration policy based on the entry's time window and the durations of resolved content.

A fixed-slot entry occupies its entire assigned window with a single resolved event. An iterative entry's window accommodates multiple sequential iterations of the same schedulable entry, each resolving independently.

The `allow_bleed` field governs the boundary behavior of the final iteration:

- `allow_bleed: true` — The scheduling layer permits the final program event begun within the window to run to its natural end, even if that end time exceeds the window's declared boundary.
- `allow_bleed: false` (default) — No program event may begin within the window if its natural duration would extend past the window boundary. The scheduling layer does not start an iteration that cannot complete within the remaining window time.

Bleed evaluation occurs before each candidate iteration begins. The template layer has no visibility into bleed configuration, window capacity, or iteration count. Underfill — remaining time after the last complete event and before the window end — is handled by the filler system declared at channel level.

---

### EPG identity model

EPG identity is determined at the schedule entry level using the following precedence:

1. If the schedule entry declares an `epg_title` property, that value is used as the EPG identity for the event. The declared value is authoritative and is committed at Tier 1.
2. If no `epg_title` is declared, EPG identity is derived from the primary content asset resolved by the entry at Tier 2. The resolved asset's title becomes the EPG identity string for the event.

Templates do not declare static EPG identity in v1. EPG identity is a schedule-entry or asset-derived property, not a template property.

Single-primary-content templates derive EPG identity from the selected primary content asset. The asset's title, as resolved at Tier 2, is the EPG string committed for that event.

---

### Operator workflows

Operators define templates in channel configuration. Templates are authored as part of the channel's programming definition and are available for scheduling once defined.

Schedule entries reference templates by ID. When an operator assigns a program event to a schedule slot as `type: template`, the assignment includes a template ID via the `name` field. The template ID links the schedule commitment (Tier 1) to the structural definition resolved at Tier 2.

Tier 1 builds the schedule horizon. The schedule compiler produces grid-aligned program blocks with schedulable entry references and, where declared, EPG title strings. These are editorial commitments.

Tier 2 resolves structure. When the Playlog horizon extends into a scheduled window, the referenced template is resolved into concrete segments. Resolution applies selection rules and produces the ordered playout sequence.

Manual rebuild is required to change Tier 1 commitments. Once a schedule window is built at Tier 1, the entry reference and any declared EPG title are locked. Changing the template assignment for a locked window requires an explicit operator-initiated rebuild of the affected schedule window.

---

### Naming rules

Template IDs MUST be unique per channel. No two templates within a single channel's configuration may share the same identifier.

Templates should follow stable naming conventions. Template IDs are channel-scoped identifiers referenced by schedule assignments. Renaming a template ID invalidates all schedule references to that ID. Naming conventions are operator-managed; the system enforces uniqueness but does not enforce a naming scheme.

---

## Example — HBO Feature With Intro

The following example uses the `hbo-classics` channel configuration to illustrate template resolution behavior within a scheduled window.

**Configuration:**

```yaml
channel: hbo-classics
channel_number: 6
name: "HBO"
channel_type: movie
timezone: America/New_York

format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

filler: !include _defaults.yaml:filler

pools:
  hbo_movies:
    match:
      type: movie
    max_duration_sec: 10800

templates:
  hbo_feature_with_intro:
    segments:
      - source:
          type: collection
          name: Intros
        selection:
          - type: tags
            values: [hbo]
        mode: random
      - source:
          type: pool
          name: hbo_movies
        mode: random

schedule:
  all_day:
    - type: template
      name: hbo_feature_with_intro
      start: "06:00"
      end: "14:00"
      epg_title: "HBO Feature Presentation"
      allow_bleed: true
    - type: template
      name: hbo_feature_with_intro
      start: "14:00"
      end: "22:00"
      epg_title: "HBO Prime"
      allow_bleed: true
    - type: template
      name: hbo_feature_with_intro
      start: "22:00"
      end: "06:00"
      epg_title: "HBO Late Night"
      allow_bleed: true

traffic:
  allowed_types: [promo]
  default_cooldown_seconds: 7200
  max_plays_per_day: 3
```

#### Window: 06:00–14:00

The `type: template` schedule entry occupying 06:00–14:00 defines an eight-hour playout window with `allow_bleed: true`. The entry references the `hbo_feature_with_intro` template by name via the `name` field. The template is applied iteratively within this window. Each iteration resolves one complete movie event. Iterations continue until remaining window time is insufficient to accommodate another event, subject to the bleed policy on the final iteration.

#### Segment resolution per iteration

For each movie event within the window, the `hbo_feature_with_intro` template is resolved in declared segment order:

1. **Segment 1 — Intro.** Source type is `collection`, name `Intros`. The selection rule filters the collection to assets tagged `hbo`. Mode is `random`. One asset is selected uniformly at random from the filtered candidate set. The resolved asset is emitted as the first playout segment of this event.

2. **Segment 2 — Movie.** Source type is `pool`, name `hbo_movies`. The pool constrains candidates to assets of `type: movie` with duration not exceeding 10800 seconds. No additional selection rules are declared on this segment. Mode is `random`. One asset is selected uniformly at random from the constrained candidate set. The resolved asset is emitted as the second playout segment and constitutes the primary content of this event.

Both segments are emitted in declared order: intro, then movie. Segment order is invariant. Resolution does not reorder segments based on selection outcome.

#### Multiple iterations within the window

The window duration (480 minutes) exceeds the duration of any single movie event. After each event resolves, if remaining time permits another iteration, resolution begins again from segment 1 of the template. Accumulation against the window boundary is performed by the scheduling layer. Template resolution is stateless per iteration. Each iteration performs independent selection. The intro asset and the movie asset are re-selected for each iteration. Prior selections within the same window do not constrain subsequent selections unless the pool or collection definition enforces deduplication.

#### EPG identity

The schedule entry declares `epg_title: "HBO Feature Presentation"`. This string is committed at Tier 1 as the window-level EPG identity. For each individual movie event resolved within the window, the `hbo_feature_with_intro` template declares no static EPG title. EPG identity for each individual event is therefore derived from the primary content asset resolved at segment 2. The resolved movie asset's title is the EPG string committed for that event. The window-level `epg_title` and the per-event asset-derived title are distinct EPG entries.

#### Duration validation

This is an iterative window entry. There is no pre-allocated slot per iteration. Template resolution does not validate each iteration's duration against a slot boundary; it has no visibility into remaining window capacity, iteration index, or bleed configuration.

Duration management for this window is governed entirely by `INV-SCHED-WINDOW-ITERATION-001` at the scheduling layer. The `allow_bleed: true` declaration is evaluated by the window iteration policy before each iteration begins, not by the template resolution step. Underfill within a completed iteration is handled by the filler system declared at channel level.

---

**Document version:** 1.0
**Related:** [Program Event Scheduling Model (v1.0)](ProgramEventSchedulingModel_v1.0.md) · [Schedule Manager Planning Authority (v1.0)](ScheduleManagerPlanningAuthority_v1.0.md) · [Two-Tier Horizon Architecture](../architecture/two-tier-horizon.md) · [Programming DSL & Schedule Compiler](../contracts/core/programming_dsl.md)
**Governs:** Template definition, segment composition, template resolution lifecycle, duration enforcement, selection rule evaluation
