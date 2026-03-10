# INV-PRESENTATION-NOT-FILLER-001 — Presentation segments are not filler placeholders

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring presentation segments are never mistaken for empty filler placeholders. The traffic manager's `_assert_no_filler_before_primary` guard rejects blocks with empty filler before primary content. Presentation segments MUST NOT trigger this guard.

## Guarantee

Presentation segments MUST NOT have `segment_type="filler"` or `asset_uri=""`. Every presentation segment MUST reference a resolved, asset-backed file. The `_assert_no_filler_before_primary` guard MUST NOT be triggered by presentation segments.

## Preconditions

- The presentation asset satisfies `LAW-ELIGIBILITY` (state=ready, approved_for_broadcast=true).

## Observability

A presentation segment has `segment_type="filler"`, or `asset_uri=""`, or triggers the `INV-MOVIE-PRIMARY-ATOMIC` filler guard.

## Deterministic Testability

Construct a block with 2 presentation segments (asset-backed) followed by a primary content segment with `is_primary=True`. Pass the block to `fill_ad_blocks()`. Assert no ValueError is raised by `_assert_no_filler_before_primary`.

## Failure Semantics

**Planning fault.** A presentation segment with empty URI or filler type crashes `fill_ad_blocks()` for blocks with primary content.

## Required Tests

- `pkg/core/tests/contracts/test_program_presentation.py`

## Enforcement Evidence

TODO
