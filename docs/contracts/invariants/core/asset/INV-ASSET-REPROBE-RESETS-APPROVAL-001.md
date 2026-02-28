# INV-ASSET-REPROBE-RESETS-APPROVAL-001 — Reprobe resets approval and technical metadata

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

## Purpose

Reprobing re-extracts technical metadata from the media file. The old probe data, approval status, and derived markers (CHAPTER) become stale and MUST be cleared to prevent scheduling decisions based on outdated metadata. Non-CHAPTER markers (operator-placed) represent editorial intent and MUST survive reprobe.

## Guarantee

Reprobing an asset MUST:

1. Reset `approved_for_broadcast` to `FALSE`
2. Clear technical metadata: `duration_ms`, `video_codec`, `audio_codec`, `container` set to `NULL`
3. Delete the `AssetProbed` row
4. Delete all markers with `kind = CHAPTER`
5. Preserve all markers with `kind != CHAPTER`

## Preconditions

The asset MUST exist and MUST have a collection with configured enrichers.

## Observability

Enforced in `asset_reprobe.reprobe_asset()`. After reprobe, the asset is in `new` state with all technical fields cleared and CHAPTER markers removed.

## Deterministic Testability

Create an asset stub with `state='ready'`, `approved_for_broadcast=True`, populated technical fields, CHAPTER markers, and non-CHAPTER markers. Simulate reprobe reset. Assert all five guarantees hold. No real database or media files required.

## Failure Semantics

**Stale data fault.** Reprobe failed to clear stale metadata before re-enrichment. Downstream consumers may use outdated duration or codec information for scheduling decisions.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetReprobeResetsApproval001`

## Enforcement Evidence

- `pkg/core/src/retrovue/usecases/asset_reprobe.py` — `reprobe_asset()` lines 53-73 clear all stale data
- Error tag: `INV-ASSET-REPROBE-RESETS-APPROVAL-001-VIOLATED`
