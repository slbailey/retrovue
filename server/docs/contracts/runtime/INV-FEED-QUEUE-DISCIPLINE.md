# INV-FEED-QUEUE-DISCIPLINE: BlockPlan Feed Queue Discipline

**Component:** Core / BlockPlanProducer
**Enforcement:** Runtime (channel_manager.py)
**Contract Reference:** PlayoutAuthorityContract.md
**Created:** 2026-02-07
**Updated:** 2026-02-12 (configurable queue depth, BlockStarted credit signal)

## Problem Statement

AIR's BlockPlan queue has a configurable maximum depth (default 3, minimum 2).
When Core calls `feed()` before a queue slot is available, AIR returns
`QUEUE_FULL`.  Under the old design, `_generate_next_block()` eagerly advanced
the block cursor (`_block_index`, `_next_block_start_ms`) **before** confirming
that `feed()` succeeded.  A `QUEUE_FULL` rejection therefore lost the block
permanently — the cursor had already moved past it, and `_on_block_complete()`
generated a *new* block instead of retrying the rejected one.

This manifested as content gaps (e.g., filler playing twice instead of the
second episode) because the rejected block was never delivered to AIR.

The runway controller now uses `BlockStarted` events (preferred) as the credit
signal: a queue pop means a slot was consumed, so Core can immediately feed the
next block without waiting for BlockCompleted.

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

> On credit availability, if `_pending_block` is not None, Core MUST retry
> feeding `_pending_block` before generating any new block.

**Rationale:** The pending block has priority over new generation because it
was already committed to the playout sequence.

### INV-FEED-QUEUE-004: Sequence Integrity

> The block sequence delivered to AIR MUST be gap-free and monotonically
> increasing in `block_index`.  No block index is ever skipped.

**Rationale:** A gap in the block sequence causes content to be skipped,
leading to visible playout errors (wrong content, repeated filler).

### INV-FEED-QUEUE-005: Event-Driven Credit Signals

> Credit increments occur in response to `BlockStarted` events (preferred)
> or `BlockCompleted` events (backward compatibility).  No timers or
> polling loops for retry.

**Rationale:** The system is event-driven.  `BlockStarted` fires when AIR
pops a block from its queue (slot consumed); `BlockCompleted` fires when a
block finishes execution.  BlockStarted provides earlier notification,
allowing Core to maintain deeper runway.

### INV-FEED-QUEUE-006: Proactive Fill After Seed

> After seed, Core MUST initialize credits to `queue_depth - 2` and
> proactively fill remaining slots on the next tick or BlockStarted event.

**Rationale:** With queue_depth > 2, the seed fills 2 slots.  The remaining
slots should be filled immediately to maximize runway, not deferred until
the first BlockCompleted.

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
          (done)          [wait for BlockStarted/BlockCompleted]
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

Queue depth = 3 (default):
  seed(A, B) → credits = 1
  BlockStarted(A) → credits = 2 → feed(C), feed(D)
  BlockCompleted(A) → (no credit if BlockStarted supported)
  BlockStarted(B) → credits += 1 → feed(E)
  ...
```

## Affected Methods

| Method | Change |
|--------|--------|
| `__init__` | Add `_pending_block = None`, `_queue_depth`, `_block_started_supported` |
| `_generate_next_block` | No longer advances cursor |
| `_advance_cursor` | Advances `_block_index` and `_next_block_start_ms` |
| `_try_feed_block` | Feeds, stores to pending on failure, advances on success |
| `_on_block_started` | Credit increment, SEEDED→RUNNING, proactive feed |
| `_on_block_complete` | Backward-compat credit, SEEDED→RUNNING fallback |
| `_feed_ahead` | Proactive fill-to-depth when credits > 0 |
| `start` | Initializes credits to `queue_depth - 2` after seed |
| `_cleanup` | Reset `_pending_block = None`, `_block_started_supported = False` |

## Verification

Contract tests in `test_blockplan_feeding_contracts.py`:

- `TestQueueFullRetry`: Forces QUEUE_FULL, verifies retry on BlockCompleted
- `TestProactiveFillAfterSeed`: With queue_depth=3, block_c fed before any BlockCompleted
- `TestBlockStartedCredits`: BlockStarted increments credit and triggers feed
- `TestBackwardCompatBlockCompleted`: Without BlockStarted, BlockCompleted still works
