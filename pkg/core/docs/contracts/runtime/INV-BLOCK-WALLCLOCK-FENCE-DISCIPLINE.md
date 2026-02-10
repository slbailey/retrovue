# INV-BLOCK-WALLCLOCK-FENCE-DISCIPLINE: Core-Side Wall-Clock Fence Guards

**Classification:** INVARIANT (Coordination)
**Owner:** BlockPlanProducer / ChannelManager
**Enforcement Phase:** Session start and every BlockCompleted event
**Depends on:** INV-BLOCK-WALLCLOCK-FENCE-001 (AIR-side), INV-JIP-BP-005/006
**Created:** 2026-02-07

---

## Problem Statement

AIR enforces wall-clock authoritative block boundaries by comparing
`FedBlock::end_utc_ms` against the session's UTC epoch to compute an
absolute fence frame index.  If Core sends `start_utc_ms` / `end_utc_ms`
as session-relative offsets (starting from 0) instead of real UTC epoch
milliseconds, every block's `end_utc_ms` is billions of milliseconds in
the past relative to the session epoch.  AIR computes `fence_frame = 0`
for every block, causing a catastrophic cascade: all blocks complete
instantly, Core feeds new blocks as fast as callbacks arrive, and the
entire session burns through its playout plan in under a second.

---

## Definition

Core MUST anchor block schedule timestamps (`start_utc_ms`, `end_utc_ms`)
to real UTC epoch milliseconds so that AIR's wall-clock fence fires at the
correct absolute time.  Core MUST also enforce defensive guards against
completion cascades.

---

## Invariants

### INV-WALLCLOCK-FENCE-001: Immutable Scheduled Window

> Each block has an immutable scheduled window:
>
>     scheduled_start_ts = start_utc_ms  (UTC epoch milliseconds)
>     scheduled_end_ts   = end_utc_ms    (UTC epoch milliseconds)
>
> derived from the session's UTC anchor and block duration.
>
>     end_utc_ms = start_utc_ms + block_duration_ms
>
> These values MUST be real UTC epoch milliseconds (milliseconds since
> 1970-01-01T00:00:00Z), NOT session-relative offsets.

**Why:** AIR's wall-clock fence subtracts `session_epoch_utc_ms` (a real
UTC epoch value) from `end_utc_ms`.  If `end_utc_ms` is a relative offset
(e.g., 30000), the subtraction produces a hugely negative delta, the fence
frame computes to 0, and the block completes on the first tick.

---

### INV-WALLCLOCK-FENCE-002: Only Active Blocks May Complete

> Core MUST NOT process a BlockCompleted event for a block unless Core
> has previously recorded that block as ACTIVE.
>
> A block is ACTIVE if it was seeded (as block A or B) or fed to AIR
> and has not yet had its BlockCompleted event processed.
>
> BlockCompleted events for unknown or already-completed block IDs
> MUST be silently discarded with a warning log.

**Why:** During a completion cascade, AIR may emit completions for blocks
that were fed in rapid succession.  Without this guard, Core would process
completions for blocks it hasn't tracked, generating and feeding even more
blocks in an unbounded loop.

---

### INV-WALLCLOCK-FENCE-003: No Completion Before Scheduled Start

> Core MUST NOT process a BlockCompleted event for any block where the
> current time is before that block's `start_utc_ms`.
>
> If `now_utc_ms < block.start_utc_ms`, the completion is invalid and
> MUST be discarded.

**Why:** A block that hasn't started yet cannot have completed.  This
catches timestamp miscalculation bugs where blocks have future start
times but past end times (which is impossible for correctly-computed
timestamps but possible for stale or corrupted state).

---

### INV-WALLCLOCK-FENCE-004: At Most One Completion Per Event

> Each invocation of the BlockCompleted callback MUST process at most
> ONE block completion.  There MUST NOT be a loop that processes
> multiple completions in a single callback invocation.
>
> No `while now >= end_ts: emit completion` patterns are permitted.

**Why:** Even if multiple blocks are technically past-due, processing
them in a tight loop creates unbounded CPU usage and floods AIR with
feed requests.  The event-driven architecture (one completion triggers
one feed) is the natural rate limiter.

---

### INV-WALLCLOCK-FENCE-005: Session Anchor From Grid-Aligned Real UTC

> When a session starts (including JIP), Core MUST establish the
> correct `start_utc_ms` for block A by anchoring `_next_block_start_ms`
> to the wall-clock grid boundary at or before the tune-in instant:
>
>     _next_block_start_ms = floor(join_utc_ms / block_duration_ms) * block_duration_ms
>
> where `join_utc_ms = int(start_at_station_time.timestamp() * 1000)`.
>
> The anchor MUST be a real UTC epoch value (milliseconds since
> 1970-01-01T00:00:00Z) and MUST be aligned to a `block_duration_ms`
> boundary.  It MUST NOT be set to a non-UTC value or to a value that
> is not grid-aligned.
>
> JIP (`jip_offset_ms > 0`) affects only the first block's segment:
> `asset_start_offset_ms` is increased and `segment_duration_ms` is
> decreased by `block_offset_ms`.  JIP MUST NOT alter
> `_next_block_start_ms` or the block's own `start_utc_ms`,
> `end_utc_ms`, or `block_duration_ms`.
>
> The resulting block timestamps are:
>
> - Block A: `start_utc_ms = _next_block_start_ms` (grid-aligned),
>   `end_utc_ms = start_utc_ms + block_duration_ms` (full duration)
> - Block B: `start_utc_ms = block_a.end_utc_ms`,
>   `end_utc_ms = block_a.end_utc_ms + block_duration_ms`
> - Subsequent blocks chain from the previous block's `end_utc_ms`.
>
> All blocks have identical duration (`block_duration_ms`).  The first
> block is not shortened; the JIP offset is carried entirely within
> the segment.

**Why:** The anchor MUST be real UTC so that `end_utc_ms` values sent
to AIR are always in the near future relative to AIR's
`session_epoch_utc_ms`.  A relative anchor (starting from 0) produces
timestamps billions of milliseconds in the past, causing instant fence
completion in AIR.  Grid alignment ensures that block boundaries are
deterministic and reproducible: any viewer joining within the same
`block_duration_ms` window receives a block with the same
`start_utc_ms` and `end_utc_ms`, differing only in JIP segment offset.

---

### INV-WALLCLOCK-FENCE-006: Stale Anchor Recovery

> If Core detects that `now_utc_ms` is already past the `end_utc_ms`
> of the current ACTIVE block at session start (e.g., due to stale
> anchors from a previous session), Core MUST recompute the anchor
> from the current wall clock.  It MUST NOT "fast-forward complete"
> multiple blocks.
>
> Recovery: set `_next_block_start_ms = floor(now_utc_ms / block_duration_ms) * block_duration_ms`
> and regenerate the block with fresh grid-aligned timestamps.

**Why:** If a session is torn down and restarted without clearing
`_next_block_start_ms`, the old anchor value persists.  Since blocks
chain from the anchor, all new blocks inherit stale timestamps.
Recomputing from the current wall clock ensures fresh timestamps.

---

## Constraints

### C1: No AIR Changes

These invariants are enforced entirely in Core.  AIR's wall-clock fence
logic is unchanged.

### C2: No Polling or Timers

Block completion is event-driven (BlockCompleted from AIR).  Core does
not poll for completion.

### C3: Minimal State

Per-session state additions:
- `_in_flight_block_ids: set[str]` — blocks seeded/fed but not completed
- Existing `_next_block_start_ms` reused (anchored to UTC instead of 0)

---

## Required Tests

**File:** `pkg/core/tests/contracts/runtime/test_wallclock_fence_discipline.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_block_timestamps_are_utc_epoch` | 001, 005 | Blocks generated after UTC anchor have start/end in real UTC range |
| `test_no_completion_before_start` | 003 | BlockCompleted rejected when now < block.start_utc_ms |
| `test_no_past_due_cascade_on_session_start` | 005, 006 | Stale anchor recomputed; no cascade of completions |
| `test_only_active_blocks_can_complete` | 002 | Completion rejected for unknown/prior-session block IDs |
| `test_one_completion_per_tick` | 004 | Even with time far past end, only one completion per callback |
| `test_jip_does_not_shift_schedule_timing` | 005 | JIP offset changes segment offset only; block start remains grid-aligned, block duration unchanged |
| `test_blocks_chain_correctly_from_anchor` | 001, 005 | Sequential blocks have contiguous UTC timestamps |

---

## Related Contracts

| Contract | Relationship |
|----------|-------------|
| INV-BLOCK-WALLCLOCK-FENCE-001 (AIR) | Consumer: AIR uses `end_utc_ms` for fence computation |
| INV-FEED-EXACTLY-ONCE | Sibling: prevents duplicate feeds; this contract prevents invalid completions |
| INV-FEED-NO-FEED-AFTER-END | Sibling: prevents feeds after session end |
| INV-JIP-BP-005/006 | Upstream: JIP offset rules for first block |
