# Container Ingest Workflow

**Domain:** ingest  
**Slug:** `container-ingest-workflow`

## Responsibility

**Orchestrate** ingest for a single container: discover locators, determine reconciliation outcomes, persist new/updated assets, enqueue processor jobs for enrichment.

## Owns vs reads

- **Owns:** single-container ingest orchestration, reconciliation logic, enrichment job queuing.
- **Reads:** container entity, importer output, asset state machine rules.

## Upstream inputs

`source-ingest-workflow` (when invoked per-container) or CLI/API directly (single-container ingest).

## Downstream outputs

`ContainerIngestResult` — per-container statistics, errors, reconciliation outcomes.

## Must NOT do

- Contain presentation logic (IO, HTTP response formatting).
- Encode scheduling or playout decisions.
- Bypass asset state machine (`INV-ASSET-STATE-MACHINE-001`).
- Call other workflows — it is a leaf workflow (`INV-WORKFLOW-FLAT-NESTING-001`).

## Source location

`server/src/retrovue/workflows/container_ingest.py`
