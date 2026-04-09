# INV-WATCH-DEBOUNCE-001 — File changes debounced before re-ingest

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION` by ensuring that rapid filesystem changes (e.g. bulk file copy, editor autosave) do not trigger redundant ingest runs. Without debounce, a single file operation that produces dozens of events would spawn dozens of overlapping ingests, corrupting catalog state and wasting compute.

## Guarantee

File change events detected by watch mode MUST be aggregated over a configurable debounce window before triggering re-ingest. A re-ingest MUST NOT be triggered for every individual file event. The debounce timer MUST reset on each new event within the window. When the timer expires without further events, exactly one `SourceIngestService.ingest_source()` call MUST be made.

## Preconditions

- Watch mode is active and monitoring filesystem paths.
- Debounce interval is ≥ 1 second.

## Observability

- Each raw file event emits a `file_change_detected` structured log at DEBUG level.
- Each debounce expiry emits a `reingest_triggered` structured log with the count of aggregated events.
- If N file events occur within the debounce window, exactly one `reingest_triggered` event is emitted.

## Deterministic Testability

1. Simulate 10 file events within a 1-second window with debounce set to 2 seconds. Assert exactly one `ingest_source()` call after the 2-second timer expires.
2. Simulate a file event, wait 1 second (less than debounce), simulate another event. Assert the timer resets and `ingest_source()` is called once, 2 seconds after the last event.
3. Simulate two file events separated by more than the debounce interval. Assert two separate `ingest_source()` calls.

## Failure Semantics

**Planning fault.** Missing debounce causes redundant ingests that may produce inconsistent catalog state when overlapping transactions compete.

## Required Tests

- `pkg/core/tests/contracts/ingest/test_inv_watch_debounce.py`

## Enforcement Evidence

TODO
