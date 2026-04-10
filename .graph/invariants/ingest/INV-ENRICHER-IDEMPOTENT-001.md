# INV-ENRICHER-IDEMPOTENT-001

**Domain:** ingest

## Plain-language rule

Re-running an enricher at the same version on the same asset MUST be idempotent — producing the same result without side effects. Every `EnrichmentResult` MUST include a `version` field.

## Why it exists

Without idempotency, re-enrichment after failures or retries can corrupt asset metadata or create duplicate records. Version tracking enables stale-result detection without bulk reprocessing.

## What it constrains

- **Service:** all enrichers via `DomainEnricher` base class — `enrich()` must be side-effect-free for repeated calls.
- **Entity:** `enricher-run` — same version + same asset = same result.

## Failure mode if violated

Retry logic produces inconsistent metadata. Enricher upgrades require expensive bulk reprocessing with no targeted re-enrichment path.
