# INV-TAG-CANONICAL-FORM-001

**Domain:** ingest

## Plain-language rule

Every persisted tag must use the canonical form `namespace.value` — no plain strings, no colon-prefixed forms, no mixed formats.

## Why it exists

Mixed tag formats cause pool DSL filters to silently miss matching assets. A tag stored as `hbo` and another as `tag.hbo` look like different tags to queries, breaking scheduling pool resolution.

## What it constrains

- **Service:** all tag write paths (CLI, ingest workflow, studio API) must route through `canonicalize_tag()`.
- **Entity:** `asset` tag storage in `asset_tags.tag` column.

## Failure mode if violated

Pool resolution produces incorrect membership — assets appear to be missing from pools they should match, or match pools they should not. Silent planning fault.
