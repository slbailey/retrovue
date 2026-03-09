# Break Detection — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Overview

Break detection is a dedicated pipeline stage that runs after program assembly and before traffic fill. It consumes an assembled program result and produces an ordered set of break opportunities with a break budget. Traffic fill consumes the break plan — it MUST NOT invent break locations.

The schedule compiler produces grid-aligned program blocks. Program assembly produces ordered content segments with total runtime. Break detection identifies where breaks may occur within or around those segments, classifies each opportunity by source, and computes the budget available for traffic to fill.

Break detection produces a BreakPlan describing where breaks occur and the break budget available. Break detection does not select traffic assets. Traffic fill is performed by the traffic manager using policies defined in `traffic_policy.md` and configured via `traffic_dsl.md`.

Break detection does not modify content segments. Break detection does not alter timing. It produces a plan that downstream consumers execute.

---

## Domain Objects

### AssemblyResult (upstream input)

Break detection receives an `AssemblyResult` from program assembly. The relevant fields are:

| Field | Type | Description |
|-------|------|-------------|
| `segments` | ordered list of AssemblySegment | Content segments in playout order. |
| `total_runtime_ms` | non-negative integer | Sum of all segment durations. |

Each `AssemblySegment` carries:

| Field | Type | Description |
|-------|------|-------------|
| `asset_id` | string | Asset identifier. |
| `duration_ms` | positive integer | Segment duration in milliseconds. |
| `segment_type` | string | `"content"`, `"intro"`, or `"outro"`. |
| `chapter_markers_ms` | tuple of int or null | Chapter marker positions relative to segment start. Null when absent. |

Break detection MUST NOT access raw asset metadata. All information it needs MUST be present in the AssemblyResult.

### BreakOpportunity

A single identified point where a break may be inserted.

| Field | Type | Description |
|-------|------|-------------|
| `position_ms` | non-negative integer | Position in the program timeline where the break occurs. |
| `source` | `"chapter"` \| `"boundary"` \| `"algorithmic"` | How this break was identified. |
| `weight` | positive float | Relative share of the break budget this opportunity receives. Higher weight = longer break. |

`source` classification:
- `"chapter"` — derived from a chapter marker embedded in asset metadata. Authoritative.
- `"boundary"` — derived from the seam between consecutive accumulated assets. Natural.
- `"algorithmic"` — derived from heuristic placement. Lowest priority.

### BreakPlan

The complete output of break detection for one program execution.

| Field | Type | Description |
|-------|------|-------------|
| `opportunities` | ordered list of BreakOpportunity | Break points in timeline order. May be empty. |
| `break_budget_ms` | non-negative integer | Total time available for breaks. |
| `program_runtime_ms` | positive integer | Assembled program runtime (from AssemblyResult). |
| `grid_duration_ms` | positive integer | Grid-allocated duration for this program. |

The break budget is:

```
break_budget_ms = grid_duration_ms − program_runtime_ms
```

When `break_budget_ms` is zero, `opportunities` MUST be empty. Traffic has no time to fill.

When `break_budget_ms` is negative (bleed programs), `opportunities` MUST be empty. The program overruns the grid and there is no break time.

---

## Break Priority Model

Break opportunities are identified in strict priority order. Higher-priority sources are authoritative — lower-priority sources MUST NOT override, relocate, or suppress them.

### Priority 1 — Chapter Markers

Chapter markers embedded in asset metadata are the authoritative break points. When chapter markers are present on any content segment, the markers define where breaks occur within that segment.

- Chapter marker positions are relative to their owning segment's start. Break detection converts them to program-timeline positions.
- All valid chapter markers (position > 0 and position < segment duration) are emitted as `source: "chapter"` opportunities.
- Chapter markers at position 0 or at the segment boundary are ignored (they coincide with the segment edge, not an internal break).

### Priority 2 — Asset Boundaries

In `accumulate`-mode programs, the seam between consecutive content segments is a natural break opportunity.

- Each seam between two adjacent `segment_type: "content"` segments produces one `source: "boundary"` opportunity.
- The seam position is the cumulative runtime up to the end of the preceding segment.
- Intro-to-content and content-to-outro seams are NOT break opportunities. Only content-to-content seams qualify.
- Boundary opportunities are emitted regardless of whether chapter markers also exist. A program may have both chapter breaks within segments and boundary breaks between them.

### Priority 3 — Algorithmic Placement

When the identified chapter and boundary opportunities are insufficient, algorithmic placement generates additional break points.

Algorithmic placement is subject to constraints:
- MUST NOT place a break within the protected zone (first 20% of program runtime).
- MUST NOT place a break at a position already occupied by a chapter or boundary opportunity.
- MUST NOT place a break within an intro or outro segment.
- MUST use non-uniform spacing: intervals between algorithmic breaks MUST widen toward the end of the program.

Algorithmic placement is suppressed entirely when chapter markers or boundary opportunities already provide sufficient break points. "Sufficient" means at least one opportunity exists and the break budget can be distributed across existing opportunities without any single break exceeding a reasonable upper bound.

---

## Break Rules

### Protected Zone

The first 20% of program runtime is a protected zone. No `source: "algorithmic"` break MUST fall within this zone.

Chapter markers and boundary opportunities are exempt from the protected zone — they represent editorial or structural intent and are always respected.

Protected zone boundary:

```
protected_end_ms = floor(program_runtime_ms * 0.20)
```

### Cold Open Protection

When a content segment has chapter markers, no algorithmic break MUST be placed before the first chapter marker within that segment. The content before the first marker is a cold open and MUST play uninterrupted.

This rule applies per-segment. If the first content segment has a chapter marker at 180000ms (3 minutes), no algorithmic break may appear before 180000ms in that segment's contribution to the program timeline.

### Non-Uniform Spacing

Algorithmic break spacing MUST widen toward the end of the program, matching real broadcast cadence where early acts are longer and later acts are shorter.

The spacing ratio between the last algorithmic interval and the first algorithmic interval MUST be greater than 1.0. Equal spacing is prohibited for programs with two or more algorithmic breaks.

### Non-Uniform Duration Weighting

Break opportunities closer to the end of the program receive a larger share of the break budget. The `weight` field on each BreakOpportunity controls budget distribution.

For algorithmic breaks, weights MUST increase monotonically from the first to the last opportunity. For chapter and boundary breaks, weights default to position-proportional values (later breaks receive more).

Budget distribution per opportunity:

```
opportunity_budget_ms = floor(break_budget_ms * (opportunity.weight / sum_of_all_weights))
```

Rounding remainder is added to the last opportunity.

### Accumulate-Mode Seams

When the assembled program contains multiple content segments (accumulate mode), every content-to-content seam MUST be emitted as a `source: "boundary"` break opportunity. Omitting a seam is a violation.

### Single-Asset Programs

Programs with a single content segment and no chapter markers rely entirely on algorithmic placement for break opportunities. The protected zone and non-uniform spacing rules apply.

Programs with a single content segment and chapter markers use those markers exclusively. No algorithmic breaks are added when chapter markers are present on the sole content segment.

### Intro and Outro Segments

Intro and outro segments are never broken. No break opportunity of any source MUST fall within an intro or outro segment.

Intro-to-content and content-to-outro transitions are NOT break opportunities.

---

## Pipeline Boundary

### Upstream — Program Assembly

Program assembly produces:
- Ordered content segments (with asset_id, duration_ms, segment_type, chapter_markers_ms)
- Total assembled runtime

Program assembly does NOT:
- Place breaks
- Compute break budgets
- Access grid duration

### This Stage — Break Detection

Break detection produces:
- Ordered break opportunities with source classification and weight
- Break budget computed from grid duration and assembled runtime

Break detection does NOT:
- Select traffic assets
- Modify content segment order or duration
- Create filler or padding segments

### Downstream — Traffic Fill

Traffic fill receives a BreakPlan and fills each opportunity with traffic assets (commercials, promos, PSAs) according to channel policy.

Traffic fill MUST NOT:
- Invent new break locations not present in the BreakPlan
- Reorder break opportunities
- Exceed the break budget
- Place traffic within content, intro, or outro segments

Any remaining budget after traffic fill is converted to padding to satisfy exact grid fit.

---

## Edge Cases

### Break Budget Zero or Negative

When `grid_duration_ms <= program_runtime_ms`, the break budget is zero or negative. Break detection MUST return an empty `opportunities` list. No breaks are inserted. For bleed programs, this is expected — the content fills or exceeds the grid.

### No Markers and No Valid Algorithmic Placement

When a program has no chapter markers, no asset boundaries, and the protected zone eliminates all algorithmic candidates (e.g., very short programs), break detection MUST return an empty `opportunities` list. The entire break budget becomes post-content padding.

### Clustered Chapter Markers

When chapter markers are clustered very closely (multiple markers within 30 seconds of each other), break detection MUST emit all of them as opportunities. Budget distribution via weights ensures that closely-spaced breaks receive proportionally small durations. Break detection does not merge or deduplicate markers.

### Programs with bleed=true

Bleed programs may have `program_runtime_ms > grid_duration_ms`. The break budget is negative. Break detection MUST return an empty `opportunities` list regardless of available chapter markers or boundaries. A bleeding program has no break time by definition.

### Intro/Outro Boundary

If an intro segment is present, the intro-to-content transition is NOT a break opportunity. If an outro is present, the content-to-outro transition is NOT a break opportunity. These transitions are editorial structure, not ad insertion points.

---

## Invariants

### INV-BREAK-001 — Break detection must consume assembled program output

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Break detection MUST receive an AssemblyResult as input. It MUST NOT access raw asset durations, raw metadata, or any source outside the assembled output. The assembled program is the sole input authority.

**Violation:** A break detection function that accepts raw asset_id + duration_ms instead of an AssemblyResult, or that queries an asset resolver directly.

---

### INV-BREAK-002 — Break priority order must be chapter > boundary > algorithmic

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** When chapter markers are present, they MUST be emitted as break opportunities. When asset boundaries exist, they MUST be emitted as break opportunities. Algorithmic breaks MUST NOT override, relocate, or suppress chapter or boundary breaks. All three sources may coexist in a single BreakPlan.

**Violation:** An algorithmic break that replaces a chapter marker position; a boundary opportunity that is suppressed because chapter markers exist on adjacent segments; a BreakPlan that contains only algorithmic breaks when chapter markers or boundaries are available.

---

### INV-BREAK-003 — Algorithmic breaks must not fall in protected zone

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

**Guarantee:** No `source: "algorithmic"` break opportunity MUST have `position_ms < floor(program_runtime_ms * 0.20)`. Chapter and boundary breaks are exempt from this constraint.

**Violation:** An algorithmic break opportunity whose position falls within the first 20% of program runtime.

---

### INV-BREAK-004 — Accumulate boundaries must be emitted as break opportunities

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** When the assembled program contains N content segments (N > 1), break detection MUST emit exactly N-1 `source: "boundary"` opportunities at the seam positions between consecutive content segments. No seam may be omitted.

**Violation:** An accumulate-mode program with 3 content segments that produces fewer than 2 boundary opportunities; a BreakPlan that omits any content-to-content seam.

---

### INV-BREAK-005 — Break budget must be derived from assembled runtime

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

**Guarantee:** `break_budget_ms` MUST equal `grid_duration_ms - AssemblyResult.total_runtime_ms`. The budget MUST NOT be derived from raw asset duration, from a single segment's duration, or from any source other than the total assembled runtime.

**Violation:** A break budget computed from `slot_duration_ms - episode_duration_ms` when the program includes intro, outro, or multiple accumulated segments whose total differs from a single asset's duration.

---

### INV-BREAK-006 — Traffic fill must consume break plan, not invent break points

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** The traffic fill stage MUST consume a BreakPlan produced by break detection. Traffic fill MUST NOT create break opportunities, insert breaks at positions not present in the BreakPlan, or modify break positions. The BreakPlan is the sole authority for where breaks occur.

**Violation:** A traffic fill function that computes its own break points from episode duration and slot duration; a traffic fill that inserts a filler segment at a position not listed in the BreakPlan's opportunities.

---

### INV-BREAK-007 — Algorithmic break spacing must be non-uniform

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** When two or more algorithmic breaks are placed, the interval between the last two algorithmic breaks MUST be shorter than the interval between the first two algorithmic breaks. Equal spacing is prohibited. Spacing MUST widen toward the end of the program (intervals decrease, meaning acts get shorter toward the end).

**Violation:** Two or more algorithmic breaks with equal spacing; a BreakPlan where the first algorithmic interval is shorter than the last.

---

### INV-BREAK-008 — Break detection must be a dedicated stage

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

**Guarantee:** Break detection MUST be implemented as a callable function that accepts an AssemblyResult and grid_duration_ms and returns a BreakPlan. It MUST NOT be fused into the playout log expander, the schedule compiler, or the traffic manager. It is a distinct pipeline stage with defined inputs and outputs.

**Violation:** Break opportunity identification that occurs inside `expand_program_block()` or inside a traffic fill function; break logic that cannot be invoked independently of segment expansion.

---

### INV-BREAK-009 — No break within intro or outro segments

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** No break opportunity of any source MUST fall at a position within an intro or outro segment. Intro and outro segments play uninterrupted. Intro-to-content and content-to-outro transitions are NOT break opportunities.

**Violation:** A BreakOpportunity whose `position_ms` falls within the timeline range occupied by an intro or outro segment; a boundary break emitted at an intro-to-content or content-to-outro seam.

---

### INV-BREAK-010 — Cold open must be respected

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** When a content segment has chapter markers, no `source: "algorithmic"` break MUST be placed before the first chapter marker's program-timeline position within that segment. Content before the first chapter marker is a cold open.

**Violation:** An algorithmic break placed before the first chapter marker of a segment that has chapter markers.

---

### INV-BREAK-011 — Bleed programs produce empty break plans

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** When `program_runtime_ms > grid_duration_ms` (the program bleeds past its grid allocation), break detection MUST return a BreakPlan with an empty `opportunities` list and `break_budget_ms <= 0`.

**Violation:** A BreakPlan with non-empty opportunities for a program whose assembled runtime exceeds the grid duration.

---

### INV-BREAK-012 — No break opportunity within primary content

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** When the assembled program contains a segment marked `is_primary`, break detection MUST NOT place any break opportunity at a position within that segment's timeline range. Primary content plays without interruption. Break opportunities MUST appear only outside primary segment boundaries.

**Violation:** A BreakOpportunity whose `position_ms` falls within the timeline range occupied by a primary segment; an algorithmic or boundary break placed inside primary content.

---

## Required Tests

All tests live under:

```
pkg/core/tests/contracts/test_break_detection.py
```

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_detect_breaks_from_assembly_result` | INV-BREAK-001 | Break detection accepts AssemblyResult, returns BreakPlan. |
| `test_rejects_raw_asset_duration` | INV-BREAK-001 | Break detection function signature requires AssemblyResult, not raw duration. |
| `test_chapter_markers_emit_chapter_breaks` | INV-BREAK-002 | Single-asset program with 3 chapter markers produces 3 chapter opportunities. |
| `test_boundary_breaks_coexist_with_chapter_breaks` | INV-BREAK-002 | Accumulate program with chapter markers on one segment produces both chapter and boundary breaks. |
| `test_algorithmic_does_not_override_chapter` | INV-BREAK-002 | Chapter markers present — no algorithmic break at a chapter position. |
| `test_algorithmic_not_in_protected_zone` | INV-BREAK-003 | Algorithmic breaks all have position_ms >= 20% of runtime. |
| `test_chapter_breaks_allowed_in_protected_zone` | INV-BREAK-003 | Chapter marker at 5% of runtime is emitted — protected zone does not apply to chapters. |
| `test_accumulate_boundaries_emitted` | INV-BREAK-004 | 3-segment accumulate program produces exactly 2 boundary opportunities. |
| `test_single_segment_no_boundary_breaks` | INV-BREAK-004 | Single-segment program produces 0 boundary opportunities. |
| `test_budget_from_assembled_runtime` | INV-BREAK-005 | Budget = grid_duration - total_runtime (with intro+outro included in runtime). |
| `test_budget_not_from_single_asset` | INV-BREAK-005 | Accumulate program: budget uses sum of segments, not first segment alone. |
| `test_break_plan_is_sole_authority` | INV-BREAK-006 | BreakPlan output contains all information needed by traffic fill — no resolver access. |
| `test_algorithmic_spacing_non_uniform` | INV-BREAK-007 | 3+ algorithmic breaks: first interval > last interval. |
| `test_two_algorithmic_breaks_not_equal` | INV-BREAK-007 | 2 algorithmic breaks: intervals differ. |
| `test_detect_breaks_callable_independently` | INV-BREAK-008 | Break detection function is importable and callable without playout_log_expander. |
| `test_no_break_in_intro` | INV-BREAK-009 | Program with intro segment — no break falls within intro timeline range. |
| `test_no_break_in_outro` | INV-BREAK-009 | Program with outro segment — no break falls within outro timeline range. |
| `test_no_break_at_intro_content_seam` | INV-BREAK-009 | Intro-to-content transition is not a boundary break. |
| `test_cold_open_respected` | INV-BREAK-010 | Chapter marker at 180s — no algorithmic break before 180s. |
| `test_bleed_program_empty_plan` | INV-BREAK-011 | Program runtime > grid duration — empty opportunities, budget <= 0. |
| `test_zero_budget_empty_plan` | INV-BREAK-011 | Program runtime == grid duration — empty opportunities, budget == 0. |
| `test_weight_increases_toward_end` | INV-BREAK-007 | Algorithmic break weights increase monotonically from first to last. |
| `test_no_break_in_primary_segment` | INV-BREAK-012 | Primary segment present — no opportunity falls within its timeline range. |
| `test_breaks_only_after_primary` | INV-BREAK-012 | All opportunities have position_ms outside the primary segment range. |
