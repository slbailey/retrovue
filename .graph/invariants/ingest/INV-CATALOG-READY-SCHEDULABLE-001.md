# INV-CATALOG-READY-SCHEDULABLE-001

**Domain:** ingest (cross-domain: scheduling boundary)

## Plain-language rule

If an asset is in state `ready`, scheduling MAY place it in any matching pool slot without further validation. Scheduling MUST NOT re-validate or probe assets — `ready` is the trust boundary between ingest and scheduling.

## Why it exists

Without this guarantee, scheduling must re-validate or probe assets before placement, creating runtime dependencies on ingest infrastructure during schedule compilation. The `ready` state is the contract between ingest and scheduling.

## What it constrains

- **Entity:** `asset` — state `ready` = fully schedulable, no enrichment gating.
- **Service:** schedule compiler — must not query ingest infrastructure at compile time.

## Failure mode if violated

Schedule compilation becomes coupled to ingest availability. An ingest outage blocks schedule compilation, violating separation of concerns.
