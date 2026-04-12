# INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001 — Interstitial type survives the full enrichment pipeline

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` and `LAW-CONTENT-AUTHORITY` by ensuring that `interstitial_type`, once stamped by the `InterstitialTypeEnricher`, is never silently lost during subsequent persistence or enrichment steps. Without this guarantee, interstitial assets reach `ready` state with a missing type, causing pool resolution to exclude them — a silent scheduling failure that requires manual SQL intervention.

## Guarantee

If an asset belongs to a container whose name is a key in `COLLECTION_TYPE_MAP`, then after all enrichment jobs complete and the asset reaches `ready` state, `AssetEditorial.payload["interstitial_type"]` MUST contain the canonical type from the mapping. The value MUST NOT be silently overwritten, dropped, or nulled by any subsequent persistence call, state transition, or enricher execution.

## Preconditions

- The asset's container name is a key in `COLLECTION_TYPE_MAP`.
- The `InterstitialTypeEnricher` is registered in `ENRICHERS` and `CAPABILITY_REGISTRY`.
- The asset's `AssetEditorial` row exists in the database.

## Observability

Query `AssetEditorial.payload->>'interstitial_type'` for assets in interstitial containers. Any `NULL` result for a `ready`-state asset is a violation.

## Deterministic Testability

1. Create an asset with a container name matching `COLLECTION_TYPE_MAP`.
2. Run the enricher via `execute_job()` or direct `enrich()` call.
3. Assert `AssetEditorial.payload["interstitial_type"]` equals the expected canonical type.
4. Run a subsequent enricher (e.g., ffprobe) that produces only probed metadata.
5. Assert `interstitial_type` is still present and unchanged.
6. Verify `persist_asset_metadata` with editorial does not silently drop existing fields.

## Failure Semantics

**Planning fault.** Assets that reach `ready` without `interstitial_type` are invisible to pool resolution, causing empty pools and missing presentation segments.

## Required Tests

- `server/tests/contracts/test_inv_interstitial_type_persisted.py`

## Enforcement Evidence

TODO
