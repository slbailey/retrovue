# Placement DSL — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Purpose

The Placement DSL defines how midroll break positions are determined within a content asset. Placement is a property of a segment definition within a presentation's `midroll` list. It governs WHERE breaks are inserted, not WHAT fills them.

Placement uses a primary/fallback model:
- **Primary:** Chapter markers embedded in the asset are the authoritative break positions.
- **Fallback:** When chapter markers are absent, an explicit fallback strategy generates synthetic break positions.

This contract owns the `placement` field on segment definitions and the strategies available within `placement.fallback`. It does not own break budget allocation (→ `break_detection.md`), traffic fill (→ `traffic_dsl.md`), or segment ordering (→ `block_assembly_tiers.md`).

---

## DSL Structure

### Segment with Placement

```yaml
midroll:
  - type: traffic
    profile: sitcom_standard
    fill: remaining
    placement:
      fallback:
        strategy: weighted_positions
        positions: [0.30, 0.72]
        weights: [1, 1]
```

The `placement` field is optional on any segment definition. When absent, break positions are derived from chapter markers only — if no markers exist, no midroll breaks are placed.

### Placement Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `placement.fallback` | dict | No | Fallback strategy used when chapter markers are absent. |
| `placement.fallback.strategy` | string | Yes (if fallback present) | Strategy name: `weighted_positions` or `equal_split`. |

Additional fields are strategy-specific.

---

## Placement Rules

### Rule 1: Chapter Markers Are Primary

If the content asset has `chapter_markers_sec` (non-empty):
- Break positions MUST be derived from chapter markers.
- `placement.fallback` MUST NOT be used.
- The fallback definition is ignored, not an error.

### Rule 2: Fallback Activates on Missing Markers

If `chapter_markers_sec` is missing or empty:
- `placement.fallback` MUST be used to generate synthetic break positions.
- If no `placement` is declared and no chapter markers exist, no midroll breaks are placed.

### Rule 3: No Mixing

No asset may receive both chapter-derived and fallback-derived break positions. The two sources are mutually exclusive per `INV-BREAK-PLACEMENT-FALLBACK-001`.

---

## Strategies

### weighted_positions

Defines explicit relative positions within the content duration, with proportional budget weights.

```yaml
fallback:
  strategy: weighted_positions
  positions: [0.30, 0.72]
  weights: [1, 1]
```

| Field | Type | Required | Description |
|---|---|---|---|
| `positions` | list[float] | Yes | Relative positions within content (0.0–1.0, exclusive). |
| `weights` | list[number] | Yes | Proportional budget allocation per break. Same length as `positions`. |

**Behavior:**
- Each position `p` maps to an absolute offset: `content_duration_ms * p`.
- Weights determine how the total fill budget is distributed across breaks.
- Equal weights produce equal break durations.

**Constraints:**
- All positions MUST be strictly within (0.0, 1.0). Values at 0.0 or 1.0 are rejected.
- `weights` MUST have the same length as `positions`.
- All weights MUST be positive numbers.

### equal_split

Divides content into N equal segments with breaks between them.

```yaml
fallback:
  strategy: equal_split
  count: 3
```

| Field | Type | Required | Description |
|---|---|---|---|
| `count` | int | Yes | Number of breaks to insert. Must be > 0. |

**Behavior:**
- Content is divided into `count + 1` equal segments.
- Breaks are placed at the boundaries between segments.
- All breaks receive equal budget allocation.

---

## Compiler Integration

The schedule compiler processes placement during break detection (compile time):

1. For each content segment with a midroll placement definition:
   - If `chapter_markers_sec` exists and is non-empty → use chapter markers (ignore fallback).
   - Else if `placement.fallback` exists → generate positions from fallback strategy.
   - Else → no midroll breaks for this content.

2. Generated break positions are converted to `BreakOpportunity` objects with `source: "fallback"`.

3. Break budget is allocated across opportunities per `INV-BREAK-BUDGET-EQUAL-001` (equal by default, or per declared weights).

4. The compiler produces filler placeholder segments at each break position. Traffic fill resolves actual assets later.

---

## Invariants

### INV-PLACEMENT-FALLBACK-001

If chapter markers exist for an asset, fallback placement MUST NOT be used. Defined in `break_detection.md`.

### INV-PLACEMENT-STRUCTURE-001

Placement expansion MUST NOT alter total content duration. The sum of all content act durations after break insertion MUST equal the original content duration before insertion.

### INV-PLACEMENT-COUNT-001

The number of generated break positions MUST match the strategy definition. For `weighted_positions`: number of breaks equals `len(positions)`. For `equal_split`: number of breaks equals `count`.

### INV-PLACEMENT-BOUNDS-001

All placement positions MUST be strictly within (0.0, 1.0), not including endpoints. A position at 0.0 would create a pre-content break (use preroll). A position at 1.0 would create a post-content break (use postroll).

---

## Required Tests

- `pkg/core/tests/contracts/dsl/test_placement_strategies.py`

| Test | Invariant | Scenario |
|---|---|---|
| `test_chapter_markers_override_fallback` | INV-PLACEMENT-FALLBACK-001 | Asset with chapter markers: fallback strategy ignored, chapters used. |
| `test_fallback_used_when_no_chapters` | INV-PLACEMENT-FALLBACK-001 | Asset without chapters: fallback strategy produces breaks. |
| `test_no_placement_no_chapters_no_breaks` | INV-PLACEMENT-FALLBACK-001 | No placement declared, no chapters: zero midroll breaks. |
| `test_weighted_positions_count` | INV-PLACEMENT-COUNT-001 | `positions: [0.3, 0.7]` produces exactly 2 break positions. |
| `test_equal_split_count` | INV-PLACEMENT-COUNT-001 | `count: 3` produces exactly 3 break positions. |
| `test_content_duration_preserved` | INV-PLACEMENT-STRUCTURE-001 | Sum of content acts after expansion equals original content duration. |
| `test_position_at_zero_rejected` | INV-PLACEMENT-BOUNDS-001 | `positions: [0.0, 0.5]` is rejected. |
| `test_position_at_one_rejected` | INV-PLACEMENT-BOUNDS-001 | `positions: [0.5, 1.0]` is rejected. |
| `test_weights_length_mismatch_rejected` | INV-PLACEMENT-COUNT-001 | `positions` and `weights` with different lengths rejected. |
| `test_total_duration_preserved_after_expansion` | INV-PLACEMENT-STRUCTURE-001 | Block duration unchanged after placement expansion. |

---

## Enforcement Evidence

TODO
