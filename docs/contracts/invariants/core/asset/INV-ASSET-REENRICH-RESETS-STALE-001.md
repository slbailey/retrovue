# INV-ASSET-REENRICH-RESETS-STALE-001 — Re-enrichment resets stale metadata

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

## Purpose

When an asset is re-enriched — whether due to an explicit reprobe or because the enricher pipeline configuration changed — previously extracted technical metadata becomes stale. Scheduling decisions based on outdated duration, codec, or chapter data produce invalid block plans. Stale approval status may allow an asset to remain schedulable when its technical profile has changed.

## Guarantee

Re-enrichment of an existing asset MUST follow the same lifecycle as reprobe:

1. Clear technical metadata: `duration_ms`, `video_codec`, `audio_codec`, `container` set to `NULL`
2. Delete the `AssetProbed` row
3. Delete all markers with `kind = CHAPTER`
4. Preserve all markers with `kind != CHAPTER`
5. Reset `approved_for_broadcast` to `FALSE`
6. Transition through `enriching` state via `validate_state_transition()`
7. Promote to `ready` only if `duration_ms > 0` after enrichment
8. MUST NOT set `approved_for_broadcast = TRUE`

## Preconditions

The asset MUST exist and MUST have a resolvable file path (`canonical_uri` or `uri`).

## Observability

Enforced in `asset_enrich.enrich_asset()`. After re-enrichment, the asset is in `ready` (with `approved_for_broadcast = FALSE`) or `new` state. The `last_enricher_checksum` field reflects the current pipeline identity.

## Deterministic Testability

Create an asset stub with `state='ready'`, `approved_for_broadcast=True`, populated technical fields, CHAPTER markers, and non-CHAPTER markers. Call `enrich_asset()` with a mock enricher pipeline. Assert all eight guarantees hold. No real database or media files required.

## Failure Semantics

**Stale data fault.** Re-enrichment failed to clear stale metadata before running the new pipeline. Downstream consumers may use outdated duration or codec information for scheduling decisions, or an asset may remain approved despite changed technical properties.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetReenrichResetsStale001`
- `pkg/core/tests/usecases/test_asset_enrich.py`

## Enforcement Evidence

- `pkg/core/src/retrovue/usecases/asset_enrich.py` — `enrich_asset()` implements the unified lifecycle
- Error tag: `INV-ASSET-REENRICH-RESETS-STALE-001-VIOLATED`
