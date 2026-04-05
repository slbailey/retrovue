# Asset

**Domain:** ingest  
**Slug:** `asset`

## What it represents

A **persisted catalog record** for a piece of media (or synthetic stand-in) with metadata, lifecycle state, and eligibility gates scheduling depends on.

## Lifecycle phase

**Persisted**; transitions through probe/enrich/approve per state machine contracts.

## Owning domain

ingest

## What depends on it

Scheduling pools, eligibility, traffic fill, execution plans **after** resolution to concrete paths.

## What produces it

Importer pipeline from discovered items + enrichment jobs.

## What must NOT be assumed

- That `approved` means “will air” (scheduling still places it).
- That enrichers may silently skip; failures must be visible (`INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001`).
