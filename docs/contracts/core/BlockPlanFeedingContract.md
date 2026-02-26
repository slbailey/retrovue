# BlockPlan Feeding Policy Contract

**Status:** Canonical  
**Scope:** Core — BlockPlanProducer feeding policy, streaming teardown safety, ChannelManager integration  
**Authority:** Core owns feeding and session lifecycle; AIR owns execution and subscriber attachment

This contract defines the production-grade feeding and teardown invariants for perpetual playout. Core feeds blocks to AIR in response to BlockCompleted events; teardown and viewer lifecycle must complete in bounded time without deadlock.

---

## 1. Part 1 — Feeding Policy Contracts

**Owner:** Core (BlockPlanProducer / ChannelManager feed loop)

### INV-FEED-EXACTLY-ONCE

**N BlockCompleted events → exactly N feeds.**

For each distinct BlockCompleted event, Core MUST call FeedBlockPlan (or equivalent feed) at most once for the corresponding block. Duplicate completions for the same block_id MUST be ignored; the implementation MUST track fed blocks and MUST NOT feed the same block twice.

**Violation:** Feeding twice for the same BlockCompleted; not tracking fed blocks.

---

### INV-FEED-NO-MID-BLOCK

**FeedBlockPlan never called before BlockCompleted.**

Core MUST NOT call FeedBlockPlan for a block until AIR has emitted a BlockCompleted event for the previous block (or the session has not yet completed any block). Feeds MUST be driven solely by BlockCompleted events; no speculative or time-based feed before completion.

**Violation:** Any FeedBlockPlan call occurring before the first BlockCompleted, or any feed for block N+1 before BlockCompleted for block N.

---

### INV-FEED-TWO-BLOCK-WINDOW

**Window size never exceeds 2 blocks.**

The number of blocks Core has sent to AIR but not yet completed (the “in-flight” or “window” size) MUST NOT exceed 2. Equivalently: the block queue or feed-ahead depth MUST be at most 2. This preserves bounded memory and deterministic handoff.

**Violation:** More than two blocks in flight (e.g. feeding a third block before any BlockCompleted); queue depth > 2.

---

### INV-FEED-NO-FEED-AFTER-END

**No feeds after SessionEnded.**

After AIR has emitted SessionEnded (or Core has transitioned to session-ended state), Core MUST NOT call FeedBlockPlan. FeedBlockPlan MUST return an error (e.g. ERROR) if invoked after session end. Internal feed state MUST guard against feeding after end.

**Violation:** Any feed after SessionEnded; not setting feed_state on end; FeedBlockPlan succeeding after session end.

---

### INV-FEED-SESSION-END-REASON

**Correct reason codes.**

When SessionEnded is processed, Core MUST log the session end reason (e.g. lookahead_exhausted, stopped, error) and MUST set feed state so that no further feeding occurs. The reason MUST be recorded and used for diagnostics and contract verification.

**Violation:** Not logging the reason; not setting feed_state so further feeding is impossible.

---

## 2. Part 2 — Streaming Teardown Safety

**Owner:** Core (stop path); AIR (subscriber cleanup)

### INV-TEARDOWN-IMMEDIATE

**stop() completes within bounded time.**

When Core (or the test harness) calls stop() on the channel/session, the stop MUST complete within a bounded time (e.g. 5 seconds). The call MUST NOT block indefinitely waiting on AIR or internal queues.

**Violation:** stop() blocking beyond the bound; hang on teardown.

---

### INV-TEARDOWN-NO-DEADLOCK

**stop() during various states succeeds.**

stop() MUST succeed regardless of the current state (e.g. mid-feed, waiting on BlockCompleted, idle). No state combination may cause stop() to deadlock or never return.

**Violation:** stop() deadlocking when called during feed loop, event processing, or other states.

---

### INV-TEARDOWN-SUBSCRIBER-CLEANUP

**AIR removes disconnected subscribers.**

When a viewer disconnects (or Core detaches), AIR MUST remove that subscriber from the session and MUST NOT retain references or resources for the disconnected subscriber. Cleanup MUST occur as part of teardown or detach.

**Violation:** AIR retaining subscriber state after disconnect; leak of per-subscriber resources.

---

## 3. Part 3 — ChannelManager Integration

**Owner:** Core (ChannelManager)

### INV-CM-SINGLE-SUBSCRIPTION

**One subscription per session.**

At any time there MUST be at most one active subscription (one playout session) per channel session. No duplicate subscriptions or multiple concurrent sessions for the same logical channel session.

**Violation:** Multiple subscriptions for the same session; duplicate session handles.

---

### INV-CM-VIEWER-LIFECYCLE

**Correct start/stop on viewer transitions.**

When the first viewer tunes in, Core MUST start the channel/session (and feeding) as required. When the last viewer leaves, Core MUST stop the channel/session and teardown. Start and stop MUST be invoked correctly on viewer join/leave transitions.

**Violation:** Not starting when first viewer joins; not stopping when last viewer leaves; incorrect lifecycle transitions.

---

### INV-CM-RESTART-SAFETY

**New session on restart.**

After a stop (or failure), a subsequent start MUST use a clean session state. Pending block, feed cursor, and session flags MUST be reset so that no state from the previous run is reused. Restart MUST behave as a fresh session.

**Violation:** Reusing stale state across restart; _pending_block or feed cursor not cleared; session flags from previous run affecting new session.

---

## 4. Required test

**Contract test:** `pkg/core/tests/contracts/test_blockplan_feeding_contracts.py` — existing tests enforce the invariants above (Part 1: feeding policy; Part 2: teardown; Part 3: ChannelManager integration).
