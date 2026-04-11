# INV-CUN-SCHEDULE-SCOPED-001 — CUN render queue is schedule-scoped

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

The "Coming Up Next" (CUN) render pipeline requires a dedicated job queue
scoped to schedule segments. Reusing the generic `ProcessorJob` queue would
conflate ingest-time asset processing with schedule-time presentation rendering,
violating the separation between ingest and playout enrichment domains.

## Guarantee

CUN render requests MUST be stored in a dedicated `cun_render_requests` table,
not in the `processor_jobs` table.

Each request MUST be uniquely scoped to a (channel, segment start time) pair.

## Preconditions

- The `channels` table exists with a UUID primary key.
- The migration is applied before any CUN rendering code executes.

## Observability

- The `cun_render_requests` table exists as a separate relation from `processor_jobs`.
- A UNIQUE constraint on `(channel_id, segment_start_utc)` prevents duplicate render requests per segment.
- Partial indexes support SKIP LOCKED claim patterns without scanning completed rows.

## Deterministic Testability

Inspect the database schema: `cun_render_requests` MUST exist as its own table
with the required columns, constraints, and indexes. No column in `processor_jobs`
references CUN rendering.

## Failure Semantics

Planning fault. If CUN render requests are stored in `processor_jobs`, the ingest
worker may claim and misprocess them, or CUN workers may claim ingest jobs.

## Required Tests

- `server/tests/contracts/test_cun_render_requests_schema.py`

## Enforcement Evidence

TODO
