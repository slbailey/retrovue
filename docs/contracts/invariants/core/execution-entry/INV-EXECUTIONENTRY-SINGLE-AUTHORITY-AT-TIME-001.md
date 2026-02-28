# INV-EXECUTIONENTRY-SINGLE-AUTHORITY-AT-TIME-001 — At any UTC instant exactly one ExecutionEntry is authoritative for a channel

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`

## Purpose

Enforces the uniqueness of runtime authority across the full planning horizon, including at and around broadcast-day boundaries. `LAW-RUNTIME-AUTHORITY` designates the ExecutionEntry as the sole runtime authority for a channel at any given instant. If two ExecutionEntrys both claim authority over the same instant — due to duplication, overlap, or boundary-triggered regeneration — the law's uniqueness requirement is violated and ChannelManager has no unambiguous execution instruction for that instant.

## Guarantee

At any given UTC instant within the planning horizon, exactly one ExecutionEntry MUST be authoritative for a given channel.

This guarantee MUST hold across broadcast-day boundaries. A boundary event MUST NOT cause two ExecutionEntrys to share authority over any instant.

No UTC instant within the lookahead window MUST be covered by zero ExecutionEntrys (gap) or by two or more ExecutionEntrys (overlap) simultaneously.

## Preconditions

- The channel has an active planning horizon.
- The instant in question falls within the lookahead window.

## Observability

ExecutionWindowStore MUST validate single-authority coverage after each commit or extension operation. Any interval covered by two or more ExecutionEntrys for the same channel is a violation. Any interval within the lookahead window covered by zero ExecutionEntrys is a gap violation (see `INV-EXECUTIONENTRY-NO-GAPS-001`). Violation: log the channel ID, the overlapping or uncovered interval, and the IDs of all conflicting ExecutionEntrys.

## Deterministic Testability

Create a ExecutionEntry for channel C covering [05:00, 07:00] spanning the 06:00 broadcast-day boundary. Query ExecutionWindowStore for each one-minute point in [05:00, 07:00] and assert exactly one ExecutionEntry is returned per query. Assert no second ExecutionEntry exists covering any sub-interval of [05:00, 07:00]. Assert that querying at 05:59 and 06:01 both return the same single ExecutionEntry record.

Invalid scenario: two ExecutionEntrys for the same channel both cover 06:00–06:30 — this is a violation of this invariant.

## Failure Semantics

**Runtime fault.** ExecutionWindowStore permitted a duplicate or overlapping commit, most likely triggered by a broadcast-day boundary event or a concurrent extension operation that did not validate the existing coverage before writing.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_continuity_single_authority.py`

## Enforcement Evidence

- `ExecutionWindowStore` validates single-authority coverage after each commit or extension operation — overlapping entries for the same channel and time interval are rejected at write time.
- **Broadcast-day boundary safe:** Coverage validation spans broadcast-day boundaries; a carry-in entry crossing midnight does not produce a duplicate or split authority (per `INV-EXECUTIONENTRY-CROSSDAY-NOT-SPLIT-001`).
- **Related coverage:** `TestInvExecutionentryNoGaps001` in `test_scheduling_constitution.py` validates contiguous coverage (the no-gaps complement); `TestInvExecutionentryLockedImmutable001` validates locked entries cannot be overwritten.
- Dedicated contract test (`test_inv_playlog_continuity_single_authority.py`) is referenced in `## Required Tests` but not yet implemented in the current tree.
