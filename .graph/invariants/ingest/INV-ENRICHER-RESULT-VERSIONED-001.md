# INV-ENRICHER-RESULT-VERSIONED-001

**Domain:** ingest

## Plain-language rule

Every persisted enricher result MUST include the version of the enricher that produced it. Stale results are detected by version comparison, not bulk reprocessing.

## Why it exists

Without version tracking, enricher upgrades silently invalidate prior results with no detection path. Targeted re-enrichment requires knowing which results were produced by outdated enricher versions.

## What it constrains

- **Entity:** `enricher-run` — `enricher_version` column on every execution record.
- **Service:** `container-ingest-workflow` — persists version on every enricher-run.

## Failure mode if violated

Enricher upgrades require expensive bulk reprocessing with no way to identify which assets have stale results.
