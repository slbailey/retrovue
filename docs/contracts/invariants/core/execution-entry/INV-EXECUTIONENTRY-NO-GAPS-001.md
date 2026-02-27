# INV-EXECUTIONENTRY-NO-GAPS-001 — ExecutionEntry sequence must have no temporal gaps within the lookahead window

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Purpose

Prevents temporal dead zones in the execution sequence. A gap in the ExecutionEntry sequence for an active channel represents a window of time for which no execution authority exists. During this window ChannelManager has no constitutionally-authorized content to present to AIR — the channel either stalls or produces filler without a plan mandate, violating `LAW-LIVENESS`.

## Guarantee

The ExecutionEntry sequence for an active channel must be temporally contiguous with no gaps within the lookahead window (current MasterClock time through current time + 3 hours).

A gap is defined as any interval within the lookahead window not covered by at least one ExecutionEntry.

## Preconditions

- Channel has at least one active viewer.
- The lookahead window has been populated (see `INV-EXECUTIONENTRY-LOOKAHEAD-001`).

## Observability

HorizonManager MUST validate continuity of the ExecutionEntry sequence after each rolling-window extension. Any gap is a violation. The gap interval (start, end) and channel ID MUST be logged. HorizonManager MUST attempt to fill the gap with declared filler; it MUST NOT emit a sequence with an unresolved gap.

## Deterministic Testability

Construct an ExecutionEntry sequence with a deliberate 10-minute gap at a known position. Trigger HorizonManager continuity validation. Assert the validation raises a gap fault identifying the precise gap interval. No real-time waits required.

## Failure Semantics

**Runtime fault** if the TransmissionLog-to-ExecutionEntry conversion introduced the gap. **Planning fault** if the gap propagated from an upstream `INV-SCHEDULEDAY-NO-GAPS-001` violation. Fault origin is identified by inspecting whether the upstream TransmissionLogEntry existed for the gap window.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py::TestInvExecutionentryNoGaps001`

## Enforcement Evidence

`validate_execution_entry_contiguity()` in `pkg/core/src/retrovue/runtime/execution_window_store.py` — standalone validation function. Sorts entries by `start_utc_ms`, checks each consecutive pair for `entries[i].end_utc_ms == entries[i+1].start_utc_ms`. Raises `ValueError` with tag `INV-EXECUTIONENTRY-NO-GAPS-001-VIOLATED` on gap detection, including gap boundaries and channel ID.
