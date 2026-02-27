# INV-PLAYLOG-CONTINUITY-SINGLE-AUTHORITY-AT-TIME-001 — At any UTC instant exactly one PlaylogEvent is authoritative for a channel

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`

## Purpose

Enforces the uniqueness of runtime authority across the full planning horizon, including at and around broadcast-day boundaries. `LAW-RUNTIME-AUTHORITY` designates the PlaylogEvent as the sole runtime authority for a channel at any given instant. If two PlaylogEvents both claim authority over the same instant — due to duplication, overlap, or boundary-triggered regeneration — the law's uniqueness requirement is violated and ChannelManager has no unambiguous execution instruction for that instant.

## Guarantee

At any given UTC instant within the planning horizon, exactly one PlaylogEvent MUST be authoritative for a given channel.

This guarantee MUST hold across broadcast-day boundaries. A boundary event MUST NOT cause two PlaylogEvents to share authority over any instant.

No UTC instant within the lookahead window MUST be covered by zero PlaylogEvents (gap) or by two or more PlaylogEvents (overlap) simultaneously.

## Preconditions

- The channel has an active planning horizon.
- The instant in question falls within the lookahead window.

## Observability

PlaylogService MUST validate single-authority coverage after each commit or extension operation. Any interval covered by two or more PlaylogEvents for the same channel is a violation. Any interval within the lookahead window covered by zero PlaylogEvents is a gap violation (see `INV-PLAYLOG-NO-GAPS-001`). Violation: log the channel ID, the overlapping or uncovered interval, and the IDs of all conflicting PlaylogEvents.

## Deterministic Testability

Create a PlaylogEvent for channel C covering [05:00, 07:00] spanning the 06:00 broadcast-day boundary. Query PlaylogService for each one-minute point in [05:00, 07:00] and assert exactly one PlaylogEvent is returned per query. Assert no second PlaylogEvent exists covering any sub-interval of [05:00, 07:00]. Assert that querying at 05:59 and 06:01 both return the same single PlaylogEvent record.

Invalid scenario: two PlaylogEvents for the same channel both cover 06:00–06:30 — this is a violation of this invariant.

## Failure Semantics

**Runtime fault.** PlaylogService permitted a duplicate or overlapping commit, most likely triggered by a broadcast-day boundary event or a concurrent extension operation that did not validate the existing coverage before writing.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_continuity_single_authority.py`

## Enforcement Evidence

TODO
