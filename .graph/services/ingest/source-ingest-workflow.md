# Source Ingest Workflow

**Domain:** ingest  
**Slug:** `source-ingest-workflow`

## Responsibility

**Orchestrate** ingest across all eligible containers for a source. Resolves the source, filters containers by `sync_enabled` and `ingestible`, delegates each to `container-ingest-workflow`, and aggregates results.

## Owns vs reads

- **Owns:** cross-container orchestration, result aggregation, source-level error collection.
- **Reads:** source entity, container eligibility flags, importer factory.

## Upstream inputs

CLI command or API route handler (presentation layer). Receives source selector and options (dry_run).

## Downstream outputs

`SourceIngestResult` — aggregated statistics and per-container results.

## Must NOT do

- Contain presentation logic (IO, HTTP response formatting).
- Call workflows deeper than one level (`INV-WORKFLOW-FLAT-NESTING-001`).
- Encode scheduling or playout decisions.
- Be called from another workflow (it is a top-level entry point).

## Source location

`server/src/retrovue/workflows/source_ingest.py`
