# DiscoveredItem

**Domain:** ingest  
**Slug:** `discovered-item`

## What it represents

A **pre-catalog sighting** of content from an importer: candidate for becoming an Asset after processing.

## Lifecycle phase

**Transient to persisted**: discovery → ingest jobs → Asset.

## Owning domain

ingest

## What depends on it

Importer deduplication, asset creation, enrichment targets.

## What produces it

Importer scans against Source/Container.

## What must NOT be assumed

- That every discovered item becomes schedulable immediately (gates apply).
- That discovery order implies broadcast order.
