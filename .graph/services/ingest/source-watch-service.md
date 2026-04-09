# Source Watch Service

**Domain:** ingest  
**Slug:** `source-watch-service`

## Responsibility

**Monitor** a source's filesystem paths for changes and trigger re-ingest after a debounce window expires. Owns the observer lifecycle, debounce timer, and re-ingest orchestration.

## Owns vs reads

- **Owns:** filesystem observer lifecycle, debounce timer, re-ingest dispatch.
- **Reads:** source entity (for path resolution), `SourceIngestService` (delegates actual ingest).

## Upstream inputs

CLI command or API route handler (presentation layer). Receives resolved `Source` entity and debounce configuration.

## Downstream outputs

Structured log events: `watch_started`, `file_change_detected`, `reingest_triggered`, `reingest_completed`, `reingest_failed`, `watch_stopped`.

## Must NOT do

- Contain presentation logic (IO, HTTP response formatting).
- Duplicate `SourceIngestService` ingest logic — must delegate via `ingest_source()`.
- Run without debounce (minimum interval ≥ 1 second).
- Be instantiated from the CLI command module (CLI calls `run_watch()` entry point only).

## Source location

`pkg/core/src/retrovue/workflows/source_watch.py`
