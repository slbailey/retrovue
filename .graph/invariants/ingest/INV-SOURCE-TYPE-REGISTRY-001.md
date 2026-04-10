# INV-SOURCE-TYPE-REGISTRY-001

**Domain:** ingest

## Plain-language rule

All source type dispatch MUST route through a single `SOURCE_TYPE_REGISTRY` that maps type identifiers to importer implementations. No CLI command, API handler, or workflow may contain inline type-dispatch logic outside the registry.

## Why it exists

Without a single registry, source type handling scatters across CLI commands, API handlers, and workflows, creating undocumented type-specific branches that diverge silently when new source types are added.

## What it constrains

- **Service:** `source-ingest-workflow` — must use registry lookup, not inline dispatch.
- **Entity:** `source` — `source_type` field is validated against the registry.

## Failure mode if violated

Adding a new source type requires changes in multiple scattered locations. Missing one location causes silent failures for that source type.
