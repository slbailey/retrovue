# INV-PATH-MAPPING-SOURCE-SCOPED-001

**Domain:** ingest

## Plain-language rule

Path mappings are declared at the source level (`source_path` / `retrovue_path`) and inherited by containers automatically. Per-container overrides are optional. Field names MUST be generic, not provider-specific (no `plex_path` or `local_path`).

## Why it exists

Without source-scoped inheritance, each container requires manual path configuration, creating operator burden and silent ingest failures when new containers are discovered from a source.

## What it constrains

- **Entity:** `source` — owns path mapping declarations.
- **Service:** `container-ingest-workflow` — resolves effective mappings (source + container overrides) at import time.

## Failure mode if violated

Assets ingested from new containers have broken paths. Operator must manually configure path mappings per container instead of once per source.
