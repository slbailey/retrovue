# INV-BREAK-PLACEMENT-PRIORITY-001 — Strict break placement priority order

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring editorial metadata (chapter markers) is the authoritative source of break positions when present. Protects `LAW-DERIVATION` by ensuring break placement is a faithful derivation of content structure, not an algorithmic invention when editorial markers exist. Without this invariant, the compiler may ignore chapter markers and place synthetic breaks that contradict the content creator's intended act structure.

## Guarantee

Break placement MUST follow a strict 3-tier priority: chapter markers (Tier 1) > asset boundaries (Tier 2) > synthetic/algorithmic rules (Tier 3). When chapter markers are present on an asset, they MUST be the sole source of within-asset break positions. Algorithmic placement MUST NOT generate break opportunities for an asset that has chapter markers. Boundary opportunities between different assets are independent of chapter marker presence on individual assets.

## Preconditions

1. The content asset has been probed and `probed.chapter_markers` is populated (or absent/null).
2. Chapter markers are delivered to break detection via `AssemblySegment.chapter_markers_ms`.
3. Template `strategy` is `chapter_markers_preferred` or no template is configured (default priority model applies).

## Observability

A violation is observable as a BreakPlan containing both `source: "chapter"` and `source: "algorithmic"` opportunities for the same content asset. Alternatively, a BreakPlan that uses synthetic placement when valid chapter markers exist and the active strategy is `chapter_markers_preferred`.

## Deterministic Testability

Construct an AssemblyResult with one content segment carrying chapter markers at known positions. Call break detection with `chapter_markers_preferred` strategy. Assert the resulting BreakPlan contains only `source: "chapter"` opportunities at the marker positions. Repeat with chapter markers absent and assert fallback to algorithmic placement using `target_segment_minutes`.

## Failure Semantics

**Planning fault.** Chapter markers are ignored, producing synthetic break positions that contradict the content's act structure. Viewers see breaks at algorithmically chosen positions instead of at editorial act boundaries.

## Required Tests

- `server/tests/contracts/test_chapter_marker_break_placement.py`

## Enforcement Evidence

TODO
