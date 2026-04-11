# INV-GRPC-FEED-BACKPRESSURE-001

## Behavioral Guarantee

When AIR's block queue is full, `FeedBlockPlan` returns `QUEUE_FULL` as a capacity signal, not an error. Core distinguishes capacity exhaustion from transport failure and waits for a boundary event before retrying.

## Authority Model

AIR owns queue depth and backpressure signaling. Core owns the feed scheduling policy.

## Boundary / Constraint

- `FeedBlockPlan` MUST return `QUEUE_FULL` result code when the block queue is at capacity.
- Core MUST map `QUEUE_FULL` to `FeedResult.QUEUE_FULL`, not `FeedResult.ERROR`.
- Core MUST NOT poll `FeedBlockPlan` in a loop after receiving `QUEUE_FULL`.
- Core MUST wait for a `BlockStarted` or `BlockCompleted` event before retrying feed after `QUEUE_FULL`.

## Violation

Core treats `QUEUE_FULL` as an error. Core retries `FeedBlockPlan` without waiting for a boundary event.

## Derives From

`LAW-LIVENESS`

## Required Tests

- `server/tests/contracts/grpc/test_grpc_feed_backpressure.py`

## Enforcement Evidence
TODO
