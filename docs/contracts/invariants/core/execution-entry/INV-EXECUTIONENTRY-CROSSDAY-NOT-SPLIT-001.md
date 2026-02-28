# INV-EXECUTIONENTRY-CROSSDAY-NOT-SPLIT-001 — ExecutionEntry spanning a broadcast-day boundary must not be split

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-IMMUTABILITY`

## Purpose

Protects the runtime authority of the ExecutionEntry record against corruption by accounting mechanics. When a program straddles a broadcast-day boundary, the system may determine that it intersects two accounting windows. Without this invariant, that determination could trigger segmentation, duplication, or regeneration of the runtime artifact — each of which violates `LAW-RUNTIME-AUTHORITY` by producing competing authorities for the same channel interval, and violates `LAW-IMMUTABILITY` by retroactively mutating or splitting a committed execution record.

## Guarantee

A ExecutionEntry (and its corresponding AsRun record) whose scheduled interval crosses a broadcast-day boundary MUST remain a single, continuous, unmodified runtime authority record.

The broadcast-day boundary MUST NOT cause automatic segmentation, duplication, truncation, regeneration, or synthetic splitting of the ExecutionEntry or AsRun record.

Broadcast-day accounting is a projection operation applied over committed runtime artifacts. It MUST NOT mutate, replace, or re-create those artifacts.

## Preconditions

- A ExecutionEntry exists whose `start_utc` precedes a broadcast-day boundary and whose `end_utc` follows that boundary.
- The ExecutionEntry is in the locked (committed) state.

## Observability

ExecutionWindowStore MUST NOT produce more than one ExecutionEntry for a single continuous content block, regardless of how many broadcast-day boundaries that block spans. The AsRun persistence layer MUST NOT create more than one AsRun record for a single ExecutionEntry. Any ExecutionEntry or AsRun record whose boundary exactly coincides with a broadcast-day start timestamp — and whose corresponding content block was not independently scheduled to start at that moment — is a violation. Violation: log the ExecutionEntry ID, the broadcast-day boundary timestamp, and the operation that triggered the split.

## Deterministic Testability

Create a ExecutionEntry with `start_utc = DAY_BOUNDARY - 1h` and `end_utc = DAY_BOUNDARY + 1h` (e.g., 05:00–07:00 UTC when `programming_day_start = 06:00`). Commit the record. Trigger ExecutionWindowStore extension and AsRun persistence. Assert exactly one ExecutionEntry exists covering [05:00, 07:00]. Assert exactly one AsRun record exists referencing that ExecutionEntry. Assert no record exists with `start_utc` or `end_utc` equal to `DAY_BOUNDARY` unless independently committed prior to this operation.

Invalid scenario: system produces two ExecutionEntrys covering [05:00, 06:00] and [06:00, 07:00] — this is a violation of this invariant.

## Failure Semantics

**Runtime fault** if ExecutionWindowStore performed the split during lookahead extension or lock commitment. **Operator fault** if an operator-initiated workflow (e.g., day-close export, reporting trigger) caused the runtime artifact to be mutated or replaced.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_crossday_not_split.py`

## Enforcement Evidence

- `ExecutionWindowStore` preserves entries that cross broadcast-day boundaries as single, continuous records — no automatic segmentation, truncation, or splitting at the day boundary.
- **Carry-in logic:** `TestInvScheduledaySeamNoOverlap001` in `test_scheduling_constitution.py` validates carry-in entries are honored across day boundaries without producing overlap or duplication.
- **Broadcast-day accounting is a projection:** Reporting layers project over committed runtime artifacts by interval intersection (per `INV-BROADCASTDAY-PROJECTION-TRACEABLE-001`); they do not mutate or re-create the underlying `ExecutionEntry`.
- Dedicated contract test (`test_inv_playlog_crossday_not_split.py`) is referenced in `## Required Tests` but not yet implemented in the current tree.
