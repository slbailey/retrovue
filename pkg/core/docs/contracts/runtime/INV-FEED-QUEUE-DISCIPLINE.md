# INV-FEED-QUEUE-DISCIPLINE: BlockPlan Feed Queue Discipline

**Component:** Core / BlockPlanProducer
**Enforcement:** Runtime (channel_manager.py)
**Contract Reference:** PlayoutAuthorityContract.md
**Created:** 2026-02-07

## Problem Statement

AIR's BlockPlan queue has a maximum depth of 2 (executing + pending).
When Core calls `feed()` before the currently-pending block has started
execution, AIR returns `QUEUE_FULL`.  Under the old design, `_generate_next_block()`
eagerly advanced the block cursor (`_block_index`, `_next_block_start_ms`)
**before** confirming that `feed()` succeeded.  A `QUEUE_FULL` rejection
therefore lost the block permanently — the cursor had already moved past it,
and `_on_block_complete()` generated a *new* block instead of retrying the
rejected one.

This manifested as content gaps (e.g., filler playing twice instead of the
second episode) because the rejected block was never delivered to AIR.

## Invariants

### INV-FEED-QUEUE-001: Cursor Advances Only on Successful Feed

> `_block_index` and `_next_block_start_ms` MUST NOT advance until
> `feed()` returns `True`.  Generation and cursor advancement are
> separate operations.

**Rationale:** If the cursor advances before confirmation, a QUEUE_FULL
rejection permanently skips a block.

### INV-FEED-QUEUE-002: Pending Block Slot

> When `feed()` returns `False` (QUEUE_FULL), the rejected block MUST be
> stored in `_pending_block`.  No new block is generated while
> `_pending_block` is occupied.

**Rationale:** The pending slot preserves the rejected block for retry
without re-generating it (which would produce a different block_id and
potentially different content).

### INV-FEED-QUEUE-003: Retry Before Generate

> On `BLOCK_COMPLETE`, if `_pending_block` is not None, Core MUST retry
> feeding `_pending_block` before generating any new block.

**Rationale:** BLOCK_COMPLETE is the only signal that AIR has consumed a
queue slot.  The pending block has priority over new generation because it
was already committed to the playout sequence.

### INV-FEED-QUEUE-004: Sequence Integrity

> The block sequence delivered to AIR MUST be gap-free and monotonically
> increasing in `block_index`.  No block index is ever skipped.

**Rationale:** A gap in the block sequence causes content to be skipped,
leading to visible playout errors (wrong content, repeated filler).

### INV-FEED-QUEUE-005: Event-Driven Retry Only

> Retry of a pending block MUST occur only in response to a
> `BLOCK_COMPLETE` event.  No timers, sleeps, or polling loops are
> permitted for retry.

**Rationale:** The system is event-driven.  BLOCK_COMPLETE is the only
signal that a queue slot has been freed.

## State Machine

```
                    generate_block()
                          |
                          v
              +---[block ready]---+
              |                   |
         feed() ok           feed() QUEUE_FULL
              |                   |
              v                   v
      [advance cursor]    [store in _pending_block]
              |                   |
              v                   v
          (done)          [wait for BLOCK_COMPLETE]
                                  |
                                  v
                          [retry feed(_pending_block)]
                                  |
                          +-------+-------+
                          |               |
                     feed() ok      feed() QUEUE_FULL
                          |               |
                          v               v
                  [advance cursor]  [keep in _pending_block]
                  [_pending = None]  [wait again]
```

## Affected Methods

| Method | Change |
|--------|--------|
| `__init__` | Add `_pending_block = None` |
| `_generate_next_block` | No longer advances cursor |
| `_advance_cursor` | New: advances `_block_index` and `_next_block_start_ms` |
| `_try_feed_block` | New: feeds, stores to pending on failure, advances on success |
| `_on_block_complete` | Retry pending before generating new |
| `start` | Handle QUEUE_FULL on initial 3rd block feed |
| `_cleanup` | Reset `_pending_block = None` |

## Verification

Contract test: `TestQueueFullRetry` in `test_blockplan_feeding_contracts.py`

The test forces QUEUE_FULL on the first feed attempt, then emits
BLOCK_COMPLETE and verifies:
1. The rejected block is retried (same block_id)
2. No block index is skipped
3. The retry is event-driven (triggered by BLOCK_COMPLETE only)
