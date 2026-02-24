# INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT

**Classification**: INVARIANT (Broadcast-Grade, Non-Negotiable)
**Owner**: MpegTSOutputSink / ProgramOutput
**Enforcement Phase**: From AttachStream success
**Priority**: Derived from INV-TICK-GUARANTEED-OUTPUT

## Definition

After `AttachStream` succeeds, AIR MUST emit decodable MPEG-TS within **500ms**, using fallback video/audio if real content is not yet available.

The output MUST be immediately decodable by standard players (VLC, ffplay, etc.):
- Video: IDR frame with SPS/PPS (black frame acceptable)
- Audio: Valid AAC frames (silence acceptable)
- PCR: Valid and advancing

## Rationale

**Output-first, not content-first.**

Professional playout systems emit the moment output is armed:
- Master control switchers output bars/tone until program is ready
- Satellite uplinks transmit carrier immediately
- Cable headends never show "no signal" to subscribers

The previous invariant (INV-AIR-CONTENT-BEFORE-PAD) had the philosophy backwards:
it gated output on content availability. This caused VLC to spin/reconnect
when content was slow to arrive.

The correct philosophy: **output is unconditional; content is best-effort**.

## Enforcement Mechanism

### Layer 1: ProgramOutput (Bounded Content Wait)
- Wait up to 500ms for first real content frame
- After window expires, emit pad frames (black video + silence audio)
- Continue emitting pad until real content arrives
- Log: `"Wait window expired, emitting pad frames before first real content"`

### Layer 2: MuxLoop (Bounded Pre-Timing Wait)
- Wait up to 500ms for first frame to initialize timing
- After window expires, initialize timing synthetically (ct_epoch_us = 0)
- Begin emitting black frames immediately
- Log: `"Pre-timing wait expired, initializing synthetic timing"`

### Combined Guarantee
With both layers having 500ms bounds, decodable TS is guaranteed within 500ms
of AttachStream, regardless of producer state.

## What This Replaces

| Old Invariant | Problem | New Behavior |
|---------------|---------|--------------|
| INV-AIR-CONTENT-BEFORE-PAD | Gated output on content | Output flows immediately; content joins when ready |

## Allowed Termination

Fallback output continues until one of:
1. Real content arrives (seamless transition)
2. Explicit StopChannel/DetachStream
3. Fatal error (socket, encoder)

Fallback output MUST NOT terminate due to:
- Producer EOF
- Empty queues
- Decode errors
- Timeout waiting for content

## Logging

Boot sequence start:
```
[MpegTSOutputSink] INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT: Output armed, deadline=500ms
```

Fallback activation:
```
[ProgramOutput] INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT: Emitting fallback (no real content after Xms)
```

Real content arrival:
```
[ProgramOutput] INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT: Real content arrived, transitioning from fallback
```

## Test Criteria

| Test | Pass Condition |
|------|----------------|
| Boot with no content | TS packets within 500ms of AttachStream |
| Boot with slow producer | TS packets within 500ms, then real content joins |
| Boot with fast producer | Real content within 500ms, no fallback needed |
| VLC smoke test | No spinning logo, immediate playback (black or content) |

## Related Contracts

- `INV-TICK-GUARANTEED-OUTPUT` — Parent invariant (every tick emits)
- `INV-SINK-NO-IMPLICIT-EOF` — Output continues until explicit stop
- `LAW-OUTPUT-LIVENESS` — TS must flow continuously

## Changelog

- 2025-01: Initial definition (replaces INV-AIR-CONTENT-BEFORE-PAD)
