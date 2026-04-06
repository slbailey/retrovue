# INV-GRPC-FEED-BACKPRESSURE-001

**Domain:** playout (Core↔AIR coordination)

## Plain-language rule

When AIR's block queue is full, `FeedBlockPlan` returns `QUEUE_FULL` (a capacity signal, not an error). Core waits for a boundary event before retrying.

## Why it exists

Prevents Core from overwhelming AIR's bounded block queue. Ensures block feeding is event-driven, not polling-driven.

## What it constrains

- **Services:** `playout-session` / `channel-manager` (Core feed logic), `air-playout-engine` (queue depth owner).
- Core MUST NOT treat `QUEUE_FULL` as a failure.
- Core MUST NOT poll `FeedBlockPlan` in a loop; must wait for `BlockStarted`/`BlockCompleted`.

## Failure mode if violated

Core floods AIR with redundant feed attempts; queue overflow or busy-wait CPU burn; block ordering corruption.
