# INV-WATCH-DELEGATES-001 — Watch CLI delegates to workflow

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring watch mode business logic (observer lifecycle, debounce, re-ingest orchestration) lives in the workflow layer, not in the CLI command. Without this, watch mode becomes a second ingest authority that cannot be triggered by API consumers or tested without CLI harness.

## Guarantee

The `retrovue source watch` CLI command MUST delegate all business logic to a `SourceWatchService` in the workflow layer. The CLI command MUST be limited to argument parsing, source selector resolution, IO output, and signal handling. Observer creation, debounce timer management, and `SourceIngestService` invocation MUST NOT appear in the CLI command module.

## Preconditions

- `SourceWatchService` exists in `workflows/` and accepts a resolved `Source` entity and debounce configuration.
- `INV-CLI-NO-BUSINESS-LOGIC-001` is enforced.

## Observability

Static analysis of the `source watch` CLI command module: no `watchdog` imports, no `SourceIngestService` imports, no timer or threading logic.

## Deterministic Testability

1. Assert the `source.py` CLI module does not import `watchdog`, `SourceIngestService`, or `threading`/`asyncio` timer primitives.
2. Assert the CLI command calls `SourceWatchService` (or equivalent workflow entry point) with the resolved source and debounce configuration.
3. Assert `SourceWatchService` is located in `workflows/` or `usecases/`.

## Failure Semantics

**Planning fault.** Business logic in the watch CLI command creates a capability gap — watch mode becomes untriggerable outside the CLI, violating `INV-CLI-NO-BUSINESS-LOGIC-001`.

## Required Tests

- `server/tests/contracts/ingest/test_inv_watch_delegates.py`

## Enforcement Evidence

TODO
