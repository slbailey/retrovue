# INV-WATCH-DEBOUNCE-001

**Domain:** ingest

## Plain-language rule

File change events must be aggregated over a configurable debounce window before triggering re-ingest. The timer resets on each new event; exactly one ingest runs per expiry.

## Why it exists

Without debounce, a single file operation producing dozens of filesystem events spawns dozens of overlapping ingests, corrupting catalog state and wasting compute.

## What it constrains

- **Service:** `source-watch-service` — debounce timer management and event aggregation.
- **Entity:** `asset` — protects catalog consistency by preventing concurrent competing ingests.

## Failure mode if violated

Redundant overlapping ingests with competing transactions produce inconsistent catalog state. Silent data corruption that may not surface until scheduling attempts to resolve affected assets.
