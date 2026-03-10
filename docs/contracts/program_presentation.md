# Program Presentation Stack — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-ELIGIBILITY`, `LAW-DERIVATION`

---

## Overview

A presentation stack is an ordered sequence of 0..n non-primary segments that precede the primary content segment within an assembled program block. Presentation segments represent deterministic program-framing assets: rating cards, feature presentation bumpers, studio logos, and similar channel branding that introduce a specific program airing.

Presentation segments are editorial — they are declared in the ProgramDefinition and resolved at assembly time. They are not traffic inventory, not break structure elements, and not filler.

---

## Scope

This contract governs pre-program presentation segments only.

**In scope:**
- Rating cards
- Feature presentation bumpers (e.g., HBO "Feature Presentation")
- Studio logos
- Content advisory cards
- Any deterministic, asset-backed segment that frames a program airing

**Out of scope:**
- Commercial breaks, traffic selection, break structure, filler behavior (`traffic_manager.md`, `break_structure.md`)
- Continuity-layer bumpers that frame ad breaks (`break_structure.md`)
- Station IDs and network bumpers inserted by the traffic layer
- Inter-program transitions not tied to a specific program airing

---

## Segment Type

Presentation segments MUST use `segment_type="presentation"`.

Presentation segments MUST NOT be classified as `"content"`, `"filler"`, `"pad"`, `"bumper"`, `"intro"`, `"outro"`, or any other existing segment type. The `"presentation"` type is distinct and carries its own pipeline semantics.

---

## Invariants

### INV-PRESENTATION-SINGLE-PRIMARY-001 — Exactly one primary content segment

Each assembled program block MUST contain exactly one segment with `is_primary=True`. The primary segment is the editorial content — the movie, episode, or program that the block exists to air. Presentation segments MUST NOT be marked `is_primary=True`.

### INV-PRESENTATION-PRECEDES-PRIMARY-001 — Presentation precedes primary

All presentation segments MUST appear before the primary content segment in the block's segment list. The declared order of presentation segments MUST be preserved. No content, filler, or pad segment may appear between presentation segments and the primary segment.

### INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001 — Editorial identity from first content segment

Editorial identity resolution MUST use the first segment with `segment_type="content"` as the identity source. Presentation segments (`segment_type="presentation"`) MUST NOT be considered for editorial identity. The primary content segment MUST remain the first `segment_type="content"` segment in the block.

### INV-PRESENTATION-GRID-BUDGET-001 — Presentation durations deducted from grid budget

The total duration of all presentation segments MUST be deducted from the available grid budget before primary content selection. Content selection MUST be constrained by the sum of presentation durations plus content duration against the grid allocation. A presentation stack that exceeds the grid allocation without `bleed: true` MUST be rejected.

### INV-PRESENTATION-NOT-FILLER-001 — Presentation segments are not filler placeholders

Presentation segments MUST NOT have `segment_type="filler"` or `asset_uri=""`. A presentation segment is always asset-backed. The `_assert_no_filler_before_primary` guard MUST NOT be triggered by presentation segments because they are not filler placeholders.

### INV-PRESENTATION-BREAK-INVISIBLE-001 — Break detection ignores presentation boundaries

Break detection MUST NOT place break opportunities at presentation-to-content boundaries. Presentation segments are not `segment_type="content"` and therefore MUST be invisible to chapter-marker extraction, boundary-seam detection, and algorithmic break placement.

---

## Configuration Model

A ProgramDefinition MAY declare a `presentation` field containing an ordered list of 0..n entries. Each entry is either a direct asset reference (string) or a pool reference (`{pool: "<pool_name>"}`). Direct references resolve to a single asset. Pool references resolve to one randomly-selected asset from the named pool using the block's seeded RNG. The list defines the presentation stack in playback order.

Pool-based entries are resolved independently per program execution within a schedule block. Two executions of the same program MAY receive different pool selections.

A ProgramDefinition MUST NOT declare both `presentation` and `intro` simultaneously.

The presentation stack is a property of the ProgramDefinition, not the schedule block. Schedule blocks MUST NOT contain inline presentation declarations (`INV-PROGRAM-SEPARATION-001`).

---

## Assembly Sequence

Given a ProgramDefinition with presentation stack [P1, P2, ..., Pn] and primary content C:

1. Resolve all presentation entries. String entries resolve via asset lookup. Pool entries resolve via `resolve_pool()` followed by seeded random selection. Each resolved asset MUST satisfy `LAW-ELIGIBILITY` (state=ready, approved_for_broadcast=true).
2. Compute wrapper overhead: `presentation_ms = sum(Pi.duration_ms for all Pi)`.
3. Include wrapper overhead in grid budget calculation (alongside any outro duration).
4. Select primary content C from the pool, constrained by remaining grid budget.
5. Assemble segment list: `[P1, P2, ..., Pn, C, ...]` followed by filler placeholder for remaining slot time.

The final block segment ordering:

```
[presentation_1] [presentation_2] ... [presentation_n] [primary_content] [filler_placeholder]
```

---

## Relationship to Existing Contracts

| Contract | Relationship |
|----------|-------------|
| `program_definition.md` | Presentation stack extends the existing intro/outro model. `INV-PROGRAM-INTRO-OUTRO-001` generalizes to include presentation durations in runtime calculations. |
| `break_detection.md` | `INV-BREAK-009` already excludes intro-to-content seams. Presentation-to-content seams follow the same principle (`INV-PRESENTATION-BREAK-INVISIBLE-001`). |
| `traffic_manager.md` | `INV-MOVIE-PRIMARY-ATOMIC` is preserved. Presentation segments are not empty filler placeholders and do not trigger the guard. |
| `channel_dsl.md` | The `presentation` field on ProgramDefinition is the DSL surface for this contract. |

---

## Required Tests

- `pkg/core/tests/contracts/test_program_presentation.py`

### Test Scenarios

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_zero_presentation_segments` | INV-PRESENTATION-SINGLE-PRIMARY-001 | Program with empty presentation stack assembles with primary content only. |
| `test_single_presentation_segment` | INV-PRESENTATION-PRECEDES-PRIMARY-001 | Single presentation segment appears before primary content in segment list. |
| `test_multiple_presentation_segments_declared_order` | INV-PRESENTATION-PRECEDES-PRIMARY-001 | Multiple presentation segments appear in declared order before primary content. |
| `test_presentation_grid_budget_deduction` | INV-PRESENTATION-GRID-BUDGET-001 | Presentation durations reduce available grid budget for content selection. Content that would fit without presentation stack is rejected when presentation overhead causes grid overrun with `bleed: false`. |
| `test_presentation_does_not_break_identity_resolution` | INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001 | Schedule compiler extracts editorial identity from the primary content segment, not from presentation segments. |
| `test_presentation_does_not_trigger_filler_before_primary` | INV-PRESENTATION-NOT-FILLER-001 | A block with presentation segments before a primary segment passes `_assert_no_filler_before_primary` without error. |
| `test_presentation_invisible_to_break_detection` | INV-PRESENTATION-BREAK-INVISIBLE-001 | Break detection produces no opportunities at presentation-to-content boundaries. |
| `test_primary_segment_is_first_content_type` | INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001 | The primary content segment is the first segment with `segment_type="content"` in the block. No presentation segment has `segment_type="content"`. |
| `test_presentation_segments_are_not_primary` | INV-PRESENTATION-SINGLE-PRIMARY-001 | All presentation segments have `is_primary=False`. Exactly one segment has `is_primary=True`. |
| `test_presentation_and_intro_mutual_exclusion` | INV-PRESENTATION-PRECEDES-PRIMARY-001 | A ProgramDefinition with both `presentation` and `intro` is rejected at validation time. |
| `test_pool_entry_resolves_to_single_asset` | INV-PRESENTATION-PRECEDES-PRIMARY-001 | A `{pool: "..."}` entry resolves to exactly one asset from the named pool. |
| `test_pool_entry_selection_is_seeded` | INV-PRESENTATION-PRECEDES-PRIMARY-001 | Same seed produces same pool selection; different seeds produce different selections. |
| `test_mixed_asset_and_pool_entries` | INV-PRESENTATION-PRECEDES-PRIMARY-001 | A presentation stack mixing direct asset refs and pool refs resolves in declared order. |

---

## Enforcement Evidence

TODO
