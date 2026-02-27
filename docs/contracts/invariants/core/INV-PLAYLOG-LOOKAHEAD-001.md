# INV-PLAYLOG-LOOKAHEAD-001 — Playlog must extend at least 3 hours ahead of current time

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-LIVENESS`

## Purpose

Ensures ChannelManager always has a populated execution window to present to AIR. `LAW-RUNTIME-AUTHORITY` requires PlaylogEvent to be the authoritative source for what plays now. If the Playlog falls behind real time, ChannelManager has no constitutionally-authorized content, forcing AIR to stall or produce unplanned filler — violating `LAW-LIVENESS`.

## Guarantee

At all times while a channel has at least one active viewer, the PlaylogEvent sequence must extend at least 3 hours ahead of the current MasterClock time, with no temporal gaps in that window.

## Preconditions

- Channel has at least one active viewer (a live playout session exists).
- MasterClock is established for the session.

## Observability

PlaylogService MUST continuously monitor the distance between current MasterClock time and the `end_utc` of the last PlaylogEvent entry. When this distance falls below 3 hours, the rolling window MUST be extended immediately. If extension fails (e.g., no ScheduleDay exists for the required window), a lookahead violation MUST be logged with the channel ID and the depth shortfall in minutes.

## Deterministic Testability

Using a deterministic clock: construct a Playlog extending to time T. Advance the clock to T minus 2h59m. Assert PlaylogService detects the lookahead shortfall and triggers extension. Assert that after extension the window again extends ≥3h. No real-time waits required.

## Failure Semantics

**Runtime fault.** The PlaylogService failed to extend the rolling window. This is a liveness failure of the scheduling runtime. Root cause may be upstream (`INV-SCHEDULEDAY-LEAD-TIME-001` violated) or a PlaylogService logic failure.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_lookahead.py`

## Enforcement Evidence

TODO
