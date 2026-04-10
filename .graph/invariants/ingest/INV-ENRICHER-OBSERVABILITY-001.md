# INV-ENRICHER-OBSERVABILITY-001

**Domain:** ingest

## Plain-language rule

Every enricher execution MUST produce a queryable record containing enricher name, asset ID, execution status, enricher version, and timestamps (started_at, completed_at).

## Why it exists

Without per-enricher granularity, ProcessorJob is monolithic — operators cannot determine which enricher succeeded, which failed, and which is still pending for a given asset. Per-enricher records enable targeted re-enrichment and operator diagnostics.

## What it constrains

- **Entity:** `enricher-run` — each execution creates one record per enricher per asset.
- **Service:** `container-ingest-workflow` — creates enricher-run records during enricher dispatch.

## Failure mode if violated

Operators cannot diagnose partial enrichment failures. "Enrichment failed" becomes unactionable without knowing *which* enricher failed.
