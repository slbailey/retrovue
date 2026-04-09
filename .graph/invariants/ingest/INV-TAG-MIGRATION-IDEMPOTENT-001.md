# INV-TAG-MIGRATION-IDEMPOTENT-001

**Domain:** ingest

## Plain-language rule

The tag canonicalization function must be idempotent: applying it twice produces the same result as applying it once.

## Why it exists

Without idempotency, re-running migration on already-canonical tags corrupts them (e.g. `tag.hbo` → `tag.tag.hbo`). Safe re-run is essential for data repair and operational confidence.

## What it constrains

- **Service:** `canonicalize_tag()` in `tag_normalization.py`.
- **Entity:** `asset` tag storage — migration Alembic script relies on idempotency for safe re-execution.

## Failure mode if violated

Tag corruption on re-run: canonical tags get double-prefixed, breaking all downstream queries. Data loss that is difficult to recover without backups.
