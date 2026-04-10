# Chapter Marker Break Placement — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Overview

Chapter markers are editorial metadata extracted at ingest and stored on the Asset as `probed.chapter_markers`. When present, chapter markers are the authoritative source of break positions within a content segment. This contract defines the strict priority model for break placement, the data shape scheduling expects from ingest, and how template configuration activates chapter-marker-preferred placement.

This contract bridges the ingest boundary (chapter marker extraction and persistence) and the scheduling boundary (break detection using markers). Scheduling defines what data shape it expects; ingest owns how that data is produced.

### Authority Boundary

This contract owns:
- Break placement priority model (chapter markers > asset boundaries > synthetic rules)
- Chapter marker data shape expected by break detection
- Template `strategy: chapter_markers_preferred` semantics and fallback behavior
- Interaction between chapter marker placement and `target_segment_minutes`

This contract does NOT own:
- Chapter marker extraction from media files (ingest)
- Chapter marker persistence to the catalog (ingest)
- BreakPlan object construction (`break_plan.md`)
- Break structure internals (`break_structure.md`)
- Traffic asset selection (`traffic_policy.md`)
- Algorithmic break spacing rules (`break_detection.md`)

---

## Chapter Marker Data Model

### Ingest-Side Shape (Catalog)

Chapter markers are stored on Asset metadata at `probed.chapter_markers`:

```
probed.chapter_markers: list[int] | null
```

Each entry is a position in milliseconds relative to the content start. Markers at position 0 or at the content boundary are invalid for break placement and MUST be filtered by break detection.

When `probed.chapter_markers` is `null` or absent, the asset has no chapter markers. Fallback placement applies.

### Scheduling-Side Input Shape

Break detection receives chapter markers via `AssemblySegment.chapter_markers_ms`:

```
chapter_markers_ms: tuple[int, ...] | None
```

This field is populated by the `CatalogAssetResolver` during program assembly. Break detection MUST NOT access `probed.chapter_markers` directly. The AssemblyResult is the sole input authority per `INV-BREAK-001`.

---

## Break Placement Priority

Break placement follows a strict 3-tier priority. This priority model is the central guarantee of this contract.

### Tier 1 — Chapter Markers (Authoritative)

When chapter markers are present on a content segment, they define where breaks occur within that segment. Chapter markers are editorial metadata and represent the content creator's intended act structure.

- All valid markers (position > 0 and position < segment duration) are emitted as `source: "chapter"` opportunities.
- Chapter markers are exempt from the protected zone (first 20% of runtime).
- Chapter markers suppress algorithmic placement for the same asset per `INV-BREAK-PLACEMENT-FALLBACK-001`.
- Chapter markers coexist with boundary opportunities between different segments per `INV-BREAK-002`.

### Tier 2 — Asset Boundaries (Structural)

In accumulate-mode programs, the seam between consecutive content segments is a natural break opportunity.

- Each content-to-content seam produces one `source: "boundary"` opportunity per `INV-BREAK-004`.
- Boundary opportunities are independent of chapter markers — a program may have both chapter breaks within segments and boundary breaks between them.

### Tier 3 — Synthetic (Algorithmic)

When neither chapter markers nor sufficient boundary opportunities exist, algorithmic placement generates break points.

- Algorithmic placement is subject to protected zone, cold open, and non-uniform spacing rules per `INV-BREAK-003`, `INV-BREAK-010`, `INV-BREAK-007`.
- Algorithmic breaks are suppressed entirely when chapter markers exist for the same asset per `INV-BREAK-PLACEMENT-FALLBACK-001`.

---

## Template Integration

### `strategy: chapter_markers_preferred`

Templates activate chapter-marker-preferred placement via the `breaks.strategy` field:

```yaml
templates:
  sitcom:
    breaks:
      strategy: chapter_markers_preferred
      fallback: synthetic
      target_segment_minutes: 11
```

Semantics:
1. If the content asset has `probed.chapter_markers`, use chapter markers for break positions.
2. If the content asset has no chapter markers, fall through to the `fallback` strategy (default: `synthetic`), using `target_segment_minutes` for break count derivation per `INV-BREAK-DENSITY-SCALES-001`.

The `fallback` field is only meaningful when `strategy` is `chapter_markers_preferred`. For other strategies (`synthetic`, `none`, `fill_all`), `fallback` is ignored.

### `strategy: synthetic`

When `strategy` is `synthetic`, chapter markers are ignored even if present on the asset. Break positions are derived entirely from `target_segment_minutes` and algorithmic placement rules.

### Backward Compatibility

Channels without a `templates:` section continue to use the existing break detection pipeline unchanged. The existing `INV-BREAK-002` priority model (chapter > boundary > algorithmic) applies as before. Templates do not change the priority model — they provide a DSL entry point to configure it.

---

## Fallback Semantics

When `strategy: chapter_markers_preferred` is active and chapter markers are absent:

1. Break detection checks `chapter_markers_ms` on the AssemblySegment.
2. If `null` or empty after filtering invalid positions, chapter source is skipped.
3. Fallback strategy activates: `synthetic` uses `target_segment_minutes` to derive break count via `floor(content_duration_minutes / target_segment_minutes)`.
4. All existing algorithmic placement rules apply (protected zone, non-uniform spacing, cold open protection).

The fallback is not a degraded mode — it is the intended behavior for content without chapter markers. The template encodes the operator's intent: "prefer chapter markers when available, use synthetic placement otherwise."

---

## Invariants

### INV-BREAK-PLACEMENT-PRIORITY-001 — Strict break placement priority order

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Break placement MUST follow a strict 3-tier priority: chapter markers (Tier 1) > asset boundaries (Tier 2) > synthetic/algorithmic rules (Tier 3). When chapter markers are present on an asset, they MUST be the sole source of within-asset break positions. Algorithmic placement MUST NOT generate break opportunities for an asset that has chapter markers. Boundary opportunities between different assets are independent of chapter marker presence on individual assets.

**Violation:** An asset with chapter markers that also has `source: "algorithmic"` break opportunities; a BreakPlan that uses synthetic placement when valid chapter markers exist and strategy is `chapter_markers_preferred`; boundary opportunities suppressed because chapter markers exist on an adjacent segment.

### Relationship to Existing Invariants

| Invariant | Relationship |
|-----------|-------------|
| `INV-BREAK-002` | This contract formalizes and strengthens the priority model already defined in `INV-BREAK-002`. `INV-BREAK-PLACEMENT-PRIORITY-001` adds the template strategy dimension. No conflict — same priority order, additional configuration surface. |
| `INV-BREAK-PLACEMENT-FALLBACK-001` | Complementary. That invariant defines chapter-marker suppression of algorithmic placement at the per-asset level. This contract defines the template-level activation of chapter-preferred strategy. |
| `INV-BREAK-BUDGET-DERIVED-001` | No conflict. Break budget derivation is independent of break placement source. Budget = `scheduled_duration - content_duration - presentation_duration` regardless of whether breaks are chapter-derived or synthetic. |
| `INV-BREAK-DENSITY-SCALES-001` | Complementary. `target_segment_minutes` drives break count when chapter markers are absent (fallback mode). When chapter markers are present, marker positions determine break count directly — `target_segment_minutes` is not used for count derivation. |
| `INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001` | No conflict. Templates define strategy, not fixed counts. Chapter marker presence determines actual break positions; the template only declares the preference. |
| `INV-BREAK-V2-SINGLE-CHAPTER-001` | Complementary. That invariant ensures V2 compiled_segments blocks with single content segments route through chapter-aware break detection. This contract provides the priority model that detection applies. |

---

## Required Tests

All tests live under:

```
pkg/core/tests/contracts/test_chapter_marker_break_placement.py
```

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_chapter_markers_take_priority_over_algorithmic` | INV-BREAK-PLACEMENT-PRIORITY-001 | Asset with chapter markers produces only `source: "chapter"` opportunities, no algorithmic. |
| `test_chapter_markers_coexist_with_boundary` | INV-BREAK-PLACEMENT-PRIORITY-001 | Accumulate program: chapter breaks within segments + boundary breaks between segments. |
| `test_no_chapter_markers_falls_to_synthetic` | INV-BREAK-PLACEMENT-PRIORITY-001 | Asset without chapter markers with `chapter_markers_preferred` strategy produces algorithmic breaks. |
| `test_chapter_markers_preferred_strategy_uses_markers` | INV-BREAK-PLACEMENT-PRIORITY-001 | Template with `strategy: chapter_markers_preferred` and asset with markers uses chapter positions. |
| `test_synthetic_strategy_ignores_chapter_markers` | INV-BREAK-PLACEMENT-PRIORITY-001 | Template with `strategy: synthetic` ignores chapter markers even when present. |
| `test_fallback_uses_target_segment_minutes` | INV-BREAK-PLACEMENT-PRIORITY-001, INV-BREAK-DENSITY-SCALES-001 | Fallback from `chapter_markers_preferred` to synthetic uses `target_segment_minutes` for break count. |
| `test_chapter_marker_data_shape_from_assembly` | INV-BREAK-001 | Break detection receives chapter markers via `chapter_markers_ms` on AssemblySegment, not raw catalog. |
| `test_invalid_markers_filtered` | INV-BREAK-PLACEMENT-PRIORITY-001 | Markers at position 0 and at segment boundary are excluded. |
| `test_backward_compat_no_template` | INV-BREAK-PLACEMENT-PRIORITY-001 | Channel without `templates:` section uses existing priority model unchanged. |

---

## Enforcement Evidence

TODO
