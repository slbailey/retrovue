# INV-PLAYLOG-NO-GAPS-001 — PlaylogEvent sequence must have no temporal gaps within the lookahead window

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-RUNTIME-AUTHORITY`

## Purpose

Prevents temporal dead zones in the execution sequence. A gap in the PlaylogEvent sequence for an active channel represents a window of time for which no execution authority exists. During this window ChannelManager has no constitutionally-authorized content to present to AIR — the channel either stalls or produces filler without a plan mandate, violating `LAW-LIVENESS`.

## Guarantee

The PlaylogEvent sequence for an active channel must be temporally contiguous with no gaps within the lookahead window (current MasterClock time through current time + 3 hours).

A gap is defined as any interval within the lookahead window not covered by at least one PlaylogEvent entry.

## Preconditions

- Channel has at least one active viewer.
- The lookahead window has been populated (see `INV-PLAYLOG-LOOKAHEAD-001`).

## Observability

PlaylogService MUST validate continuity of the PlaylogEvent sequence after each rolling-window extension. Any gap is a violation. The gap interval (start, end) and channel ID MUST be logged. The service MUST attempt to fill the gap with declared filler; it MUST NOT emit a sequence with an unresolved gap.

## Deterministic Testability

Construct a PlaylogEvent sequence with a deliberate 10-minute gap at a known position. Trigger PlaylogService continuity validation. Assert the validation raises a gap fault identifying the precise gap interval. No real-time waits required.

## Failure Semantics

**Runtime fault** if the Playlist-to-Playlog conversion introduced the gap. **Planning fault** if the gap propagated from an upstream `INV-SCHEDULEDAY-NO-GAPS-001` violation. Fault origin is identified by inspecting whether the upstream Playlist entry existed for the gap window.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_no_gaps.py`

## Enforcement Evidence

TODO
