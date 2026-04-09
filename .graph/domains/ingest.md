# Domain: ingest

## Purpose

Bring **media and metadata** into the catalog: discovery, enrichment jobs, persistence, and **eligibility gates** that scheduling and execution rely on—but without deciding the broadcast grid or operating playout.

## Responsibilities

- Discover items from external sources (importers) and persist **Assets**.
- Run enrichers/processors so metadata required for scheduling eligibility is **real or visibly failed**—never silently missing.
- Maintain asset lifecycle (e.g. probe, approval, readiness) as contracted.
- Provide **per-enricher observability**: queryable execution records with enricher name, status, version, and timestamps per asset.

## What this domain owns

- Catalog truth: sources, containers (subdivision for discovery), discovered items, assets, provider references.
- Ingest and enrichment **pipelines** and their persistence (ProcessorRun, etc., per contracts).

## What this domain does NOT own (critical)

- SchedulePlan, ScheduleDay, zones, or EPG (**scheduling**).
- Playlists, execution windows, or AIR control (**playout**).
- Wall-clock playout or HLS/TS delivery (**playout**).

## Boundaries vs other domains

| Adjacent domain | Boundary |
|-----------------|----------|
| **scheduling** | Consumes **eligible** assets; does not mutate editorial schedule. |
| **playout** | Consumes **resolved material** already bound into plans; does not query the library ad hoc at runtime for playback decisions. |
| **systems** | Engineering boundaries (production vs test code) apply to ingest modules like any other. |

## Key entities (slugs)

`source`, `container`, `discovered-item`, `asset`, `enricher-run`

## Key services (slugs)

`importer`, `source-ingest-workflow`, `container-ingest-workflow`, `source-watch-service`

## Key invariants (IDs)

`INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001`, `INV-ENRICHER-OBSERVABILITY-001`, `INV-ENRICHER-RESULT-VERSIONED-001`, `INV-CLI-NO-BUSINESS-LOGIC-001`, `INV-WORKFLOW-FLAT-NESTING-001`, `INV-TAG-CANONICAL-FORM-001`, `INV-TAG-MIGRATION-IDEMPOTENT-001`, `INV-WATCH-DELEGATES-001`, `INV-WATCH-DEBOUNCE-001`

See RetroVue `docs/contracts/INVARIANTS.md` for asset eligibility, probe authority, and ingest-related entries.
