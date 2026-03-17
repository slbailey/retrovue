# Test Endpoint Contract

## Overview

The `/test/block/{block_id}.ts` endpoint provides deterministic, on-demand playback of a single
named block via MPEG-TS HTTP streaming.

## Invariants

### INV-TEST-BLOCK-001: Block re-timing
The content block retrieved from `PlaylistEvent` is re-timed to start at UTC=NOW (wall clock at
session start), with its original segment structure preserved verbatim.

### INV-TEST-BLOCK-002: Segment fidelity
All `asset_uri`, `asset_start_offset_ms`, `segment_duration_ms`, and transition fields from the
stored block are passed unchanged to AIR.

### INV-TEST-BLOCK-003: Pad block suffix
A trailing pad block of `_PAD_DURATION_MS` (10 seconds) is appended after the content block so
`BlockPlanProducer.start()` can seed 2 blocks (A=content, B=pad).

### INV-TEST-BLOCK-004: Lookahead exhausted
After the pad block ends, `get_block_at` returns None, causing `lookahead_exhausted` in
`BlockPlanProducer._feed_ahead()`. The session ends naturally.

### INV-TEST-BLOCK-005: Production code path
The test endpoint uses the **exact same** `BlockPlanProducer`, `PlayoutSession`, AIR binary, and
UDS socket transport as live channels. No separate playout code is introduced.

### INV-TEST-BLOCK-006: Ephemeral lifetime
The AIR subprocess and `ChannelStream` are torn down when:
- The HTTP client disconnects (ASGI receive returns `http.disconnect`)
- A `GeneratorExit` or `CancelledError` is raised in the stream generator
- The session ends naturally (lookahead_exhausted)

### INV-TEST-BLOCK-007: Session isolation
Each request creates a new `EphemeralTestSession` with a unique session_id (UUID4).
No state is shared between concurrent test requests.

### INV-TEST-BLOCK-008: Not-found semantics
If the block_id is not found in `PlaylistEvent`, the endpoint returns HTTP 404.

## Stubs (not yet implemented)

- `/test/segment/{asset_id}.ts` — returns 501
- `/test/channel/{channel_id}.ts?t=<timestamp>` — returns 501

## Data Flow

```
HTTP GET /test/block/{block_id}.ts
  → Load ScheduledBlock from PlaylistEvent (DB)
  → SingleBlockTestScheduleService (re-timed to NOW, + pad block)
  → EphemeralTestSession
      → BlockPlanProducer.start()  ← same as live channels
          → PlayoutSession.start() / seed(block_a, block_b)
              → AIR subprocess (retrovue_air binary)
                  → MPEG-TS via UDS socket
                      → ChannelStream (FanoutBuffer)
                          → StreamingResponse → HTTP client
  ← on disconnect → EphemeralTestSession.stop() → AIR teardown
```
