# Container

**Domain:** ingest  
**Slug:** `container`

## What it represents

A **subdivision of a Source for discovery**—the canonical RetroVue term for “where importers look,” not a scheduling zone.

## Lifecycle phase

**Persisted** / configured as part of ingest topology.

## Owning domain

ingest

## What depends on it

Discovered items and importer targeting.

## What produces it

Operator / ingest configuration.

## What must NOT be assumed

- **Critical naming:** do not confuse with a **scheduling Zone** (see `ambiguities/collection-vs-container.md` and scheduling `zone` entity).
- That “container” implies Docker or runtime isolation (here: **catalog subdivision**).
