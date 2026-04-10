# INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001

**Domain:** ingest

## Plain-language rule

Interstitial type classification (bumper, ident, promo, filler, etc.) MUST be persisted as a first-class field on the asset, not inferred at scheduling time.

## Why it exists

Scheduling uses interstitial type for break assembly and filler selection. If the type is computed at scheduling time, it creates a runtime dependency on the classification enricher and breaks the ingest/scheduling trust boundary.

## What it constrains

- **Entity:** `asset` — interstitial type stored as a queryable field.
- **Service:** interstitial classification enricher — must persist type during enrichment.

## Failure mode if violated

Break assembly cannot distinguish bumpers from filler without re-running classification at schedule compile time.
