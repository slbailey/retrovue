# Source Watch Mode Contract

## Overview

Source watch mode is a long-running CLI command that monitors a source's filesystem paths for changes and triggers re-ingest through the existing `SourceIngestService` workflow pipeline. Watch mode adds a trigger mechanism; it does not alter core ingest logic.

## CLI Interface

```
retrovue source watch <source> [--debounce-sec 5]
```

- `<source>` — source selector (UUID, external ID, or case-insensitive name), resolved via `resolve_source_selector()`.
- `--debounce-sec` — seconds to aggregate rapid file changes before triggering re-ingest. Default: 5. MUST be ≥ 1.

## Watch Lifecycle

### States

1. **Starting** — resolve source, validate it exists, determine watch paths from source config, initialize filesystem observer.
2. **Watching** — observer is running; file change events are received and debounced.
3. **Debouncing** — a file change was detected; timer is running. Further changes reset the timer. When the timer expires, re-ingest is triggered.
4. **Re-ingesting** — `SourceIngestService.ingest_source()` is executing. New file changes during re-ingest are queued and debounced normally.
5. **Stopped** — observer is shut down. Exit code 0.

### Startup

1. Resolve source selector to a `Source` entity.
2. Determine watch paths from the source's container filesystem roots.
3. Start a `watchdog` `Observer` on those paths (recursive).
4. Emit `watch_started` structured log event.
5. Block on the observer thread until shutdown signal.

### Change Detection

File system events (created, modified, deleted, moved) are captured by the `watchdog` event handler.

Events MUST be debounced: when a file change is detected, a debounce timer of `--debounce-sec` seconds starts. Subsequent changes reset the timer. When the timer expires without further changes, a single re-ingest is triggered.

### Re-ingest Trigger

When the debounce timer expires:

1. Emit `reingest_triggered` structured log event with the source ID and the count of aggregated file events.
2. Call `SourceIngestService.ingest_source(source)` within a database session.
3. Log the ingest result summary.
4. Return to **Watching** state.

### Shutdown

On SIGINT or SIGTERM:

1. Stop the debounce timer (discard pending re-ingest).
2. Stop the `watchdog` observer.
3. Emit `watch_stopped` structured log event.
4. Exit with code 0.

## Structured Log Events

All events use structured fields (key=value), not free-form strings.

| Event | Fields | When |
|-------|--------|------|
| `watch_started` | `source_id`, `source_name`, `watch_paths`, `debounce_sec` | Observer begins monitoring |
| `file_change_detected` | `source_id`, `event_type`, `path` | Each raw filesystem event (DEBUG level) |
| `reingest_triggered` | `source_id`, `aggregated_events` | Debounce timer expires, re-ingest begins |
| `reingest_completed` | `source_id`, `status`, `assets_ingested`, `assets_updated`, `errors` | Re-ingest finishes |
| `reingest_failed` | `source_id`, `error` | Re-ingest raises an exception |
| `watch_stopped` | `source_id`, `reason` | Observer shuts down |

## Error Recovery

- If `SourceIngestService.ingest_source()` raises an exception, emit `reingest_failed` and return to **Watching** state. Watch mode MUST NOT crash on ingest failure.
- If the `watchdog` observer itself fails (e.g. inotify limit exhausted), emit a structured error log and exit with code 1.

## Delegation Rule

The watch CLI command MUST contain no business logic per `INV-CLI-NO-BUSINESS-LOGIC-001`. The command:

1. Parses arguments.
2. Resolves the source selector.
3. Delegates to a workflow-layer `SourceWatchService` that owns the observer lifecycle, debounce logic, and re-ingest orchestration.
4. Handles IO (progress output, shutdown signal).

## Dependencies

- `watchdog` — cross-platform filesystem monitoring library.
- `SourceIngestService` — existing ingest workflow (no changes required).
- `resolve_source_selector()` — existing source resolution (no changes required).

## Invariants

| ID | Guarantee |
|----|-----------|
| `INV-WATCH-DELEGATES-001` | Watch CLI delegates all business logic to `SourceWatchService` workflow |
| `INV-WATCH-DEBOUNCE-001` | File change events MUST be debounced before triggering re-ingest |

## Non-goals

- Watch mode does not perform incremental/differential ingest. Each trigger runs a full `ingest_source()`.
- Watch mode does not monitor remote sources (e.g. Plex API). Only local filesystem paths.
- Watch mode does not run as a daemon or background service. It is a foreground CLI process.
