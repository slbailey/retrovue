# INV-WATCH-DELEGATES-001

**Domain:** ingest

## Plain-language rule

The `source watch` CLI command must delegate all business logic to `SourceWatchService` in the workflow layer. The CLI command is limited to argument parsing, source resolution, IO, and signal handling.

## Why it exists

Business logic in the CLI creates a capability gap — watch mode becomes untriggerable outside the CLI, violating `INV-CLI-NO-BUSINESS-LOGIC-001`. The workflow layer must own observer lifecycle, debounce, and re-ingest orchestration.

## What it constrains

- **Service:** `source-watch-service` (workflow layer) — owns all watch business logic.
- **Service:** CLI `source watch` command — must not import `watchdog`, `SourceIngestService`, or timer primitives.

## Failure mode if violated

Watch mode becomes CLI-only, untestable without CLI harness, and inaccessible to API consumers. Violates single-authority principle for ingest orchestration.
