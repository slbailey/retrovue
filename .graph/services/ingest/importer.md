# Importer

**Domain:** ingest  
**Slug:** `importer`

## Responsibility

**Discover** external content and drive creation/update of catalog records (`discovered-item` → `asset`) within configured sources/containers.

## Owns vs reads

- **Owns:** importer-specific connection, discovery, and mapping to Core catalog writes.
- **Reads:** source/container configuration, capability registry for processor jobs.

## Upstream inputs

External libraries/APIs, operator config.

## Downstream outputs

Persisted assets, processor jobs, discovery logs.

## Must NOT do

- Encode scheduling or playout decisions.
- Hide enricher failures: pipeline must execute or fail visibly (`INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001`).
