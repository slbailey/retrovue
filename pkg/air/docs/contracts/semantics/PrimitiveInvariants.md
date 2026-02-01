# Primitive Invariants

**Document Role:** Behavioral Contract (Authoritative)

**Purpose:** Defines the three foundational invariants from which all other flow-control and pacing invariants derive. These are the root assumptions that, when violated, cause cascade failures across multiple derived invariants.

**Rule:** If code disagrees with these invariants, the code is wrong. Fix the code or explicitly amend this contract.

---

## Overview

Through log analysis of frame-based rendering failures, three **primitive assumptions** were identified. All other pacing, buffering, and coordination invariants derive from these three:

| Primitive | Owner | Layer |
|-----------|-------|-------|
| INV-PACING-001 | `ProgramOutput` | Semantic |
| INV-DECODE-RATE-001 | `FileProducer` | Semantic |
| INV-SEGMENT-CONTENT-001 | `Core` (external) | Semantic |

### Derivation Hierarchy

```
INV-PACING-001 (A)              INV-DECODE-RATE-001 (H)
     │                                   │
     ├─→ Pad emission rate               ├─→ Buffer depth sustainability
     ├─→ PTS advancement rate            ├─→ CATCH-UP completion timing
     ├─→ Gap metric correctness          ├─→ Shadow decode readiness
     │                                   ├─→ Switch readiness timing
     │                                   │
     └──────────┬────────────────────────┘
                │
                v
         Audio consumption coupling

INV-SEGMENT-CONTENT-001 (G)
     │
     └─→ First segment depth
         (independent, but symptoms overlap)
```

---

## INV-PACING-001: Render Loop Pacing

**Owner:** `ProgramOutput`

**Type:** Semantic

### Definition

The render loop emits frames at a rate governed by program frame rate, not by CPU availability. Each iteration of the loop corresponds to one frame period (e.g., 33.33ms at 30fps). Wall-clock time between consecutive frame emissions equals the reciprocal of the configured frame rate, within tolerance.

**Formal statement:**
```
Let T(n) = wall-clock time when frame n is emitted
Let Δ = 1 / target_fps (frame period)

∀n: |T(n+1) - T(n) - Δ| < ε

where ε is an acceptable jitter tolerance (e.g., ±1ms)
```

### Violation Consequences

When INV-PACING-001 is violated:

- Frames emit at CPU speed (thousands per second instead of 30)
- PTS values advance faster than wall-clock time
- Buffer drains instantly regardless of producer decode rate
- Downstream muxer receives burst traffic instead of steady stream
- Encoded output is temporally compressed (hours of content in seconds)
- Viewers see frozen frame or no video (decoder cannot process burst)

**Cascade effects:**

- INV-DECODE-RATE-001 appears violated (buffer empty) even when producer is healthy
- CATCH-UP mode completes but steady-state never achieved
- All derived pacing invariants fail simultaneously

### Violation Detection

| Observation Point | Symptom |
|-------------------|---------|
| `RenderStats::current_render_fps` | Reports 0 or extremely high value |
| `RenderStats::frame_gap_ms` | Negative or near-zero values |
| Log: frames rendered per second | Count >> target_fps in any 1-second window |
| PTS delta between consecutive frames | << frame_duration_us (e.g., 200µs instead of 33,333µs) |
| Pad frame emission rate | Hundreds of pad frames in milliseconds of wall time |
| `MpegTSOutputSink` queue depth | Spikes to max then oscillates (bursty input) |

**Canonical violation signature:**
```
[ProgramOutput] Rendered 100 frames, avg render time: 0.2ms, fps: 0, gap: -0.21ms
```

When `gap` is negative and `fps` reports 0 (measurement overflow), pacing is absent.

### Non-Owners

| Subsystem | Why NOT owner | Constraint |
|-----------|---------------|------------|
| `FileProducer` | Upstream of render loop; no visibility into output timing | Must not assume downstream pacing exists |
| `TimelineController` | Provides CT values; does not control emission cadence | Must not conflate CT advancement with frame emission rate |
| `MpegTSOutputSink` | Downstream consumer; cannot throttle upstream | Must not assume frames arrive at real-time rate |
| `MasterClock` | Provides time reference; does not enforce timing loops | May be queried for pacing decisions; does not initiate them |
| `FrameRingBuffer` | Passive data structure; no timing semantics | Must not block or pace based on time |

---

## INV-DECODE-RATE-001: Producer Decode Rate Floor

**Owner:** `FileProducer`

**Type:** Semantic

### Definition

The producer decodes frames at a rate sufficient to prevent buffer starvation during steady-state operation. The producer may decode faster than real-time (burst) when buffer has capacity, but must never fall behind for long enough to drain the buffer below a low-watermark threshold.

**Formal statement:**
```
Let B(t) = buffer depth at time t
Let B_low = low-watermark threshold (e.g., 5 frames)
Let target_fps = configured program frame rate

In steady state (not in seek/startup, not at EOF):
  1. Average decode rate over any 1-second window ≥ target_fps
  2. B(t) ≥ B_low for all t (buffer never drains to starvation)

Burst decode is explicitly allowed:
  - Producer MAY decode at 2×, 3×, or higher rates when buffer has room
  - Producer MUST throttle (backpressure) when buffer is full
  - Producer MUST NOT fall behind real-time for sustained periods

When INV-PACING-001 holds:
  R_consume = target_fps (steady consumption rate)
  Therefore: sustained R_decode ≥ R_consume
```

**Dependency:** This invariant assumes INV-PACING-001 holds. If consumption runs at CPU speed, no decode rate can satisfy this invariant.

### Violation Consequences

When INV-DECODE-RATE-001 is violated:

- Buffer depth trends toward zero during playback
- Pad frames emitted despite producer being active
- Output contains gaps or black frames interleaved with content
- Seek operations cause extended pad frame sequences
- Shadow decode never reaches readiness before buffer exhaustion
- Switch operations stall or complete with degraded output

**Cascade effects:**

- INV-P10-BUFFER-EQUILIBRIUM fails
- Audio/video sync degrades (audio consumed, video starved or vice versa)
- Metrics show high pad frame count despite healthy asset

### Violation Detection

| Observation Point | Symptom |
|-------------------|---------|
| `FrameRingBuffer::Size()` | Monotonically decreasing during playback |
| Pad frame counter | Non-zero during active decode (not seek, not segment boundary) |
| `FileProducer::GetFramesProduced()` | Increment rate < target_fps |
| Log: decode loop timing | Decode time per frame > frame_duration |
| Buffer full count | Zero (producer never catches up to backpressure point) |
| Shadow decode ready latency | Exceeds buffer sustainability window |

**Canonical violation signature:**
```
[FileProducer] Decode loop started
[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad frame #1
[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad frame #2
...
[FileProducer] Produced frame #1
```

When pad frames emit while decode loop is active and not in seek phase, decode rate is insufficient.

**Distinguishing from INV-PACING-001 violation:**

- If pad frames emit at real-time rate (one per 33ms) → INV-DECODE-RATE-001
- If pad frames emit at CPU speed (hundreds per second) → INV-PACING-001

### Non-Owners

| Subsystem | Why NOT owner | Constraint |
|-----------|---------------|------------|
| `ProgramOutput` | Sets consumption rate; cannot control production | Must not assume buffer is always populated |
| `TimelineController` | Assigns CT to frames; does not control decode rate | Must not gate or throttle producer decode loop |
| `FrameRingBuffer` | Mediates transfer; has no rate knowledge | Must provide capacity signal (full/empty) but not timing |
| `PlayoutEngine` | Orchestrates lifecycle; does not control frame-level timing | Must not issue decode rate instructions mid-segment |
| `MpegTSOutputSink` | Terminal consumer; no upstream influence | Must not assume sustained input rate |

---

## INV-SEGMENT-CONTENT-001: Segment Content Depth

**Owner:** `Core` (external to AIR)

**Type:** Semantic (input assumption)

### Definition

Each playout plan provided to AIR must cover its scheduled slot without gaps. Core achieves this by one of two methods:

1. **Content-complete segment:** The segment's `frame_count` equals the frames required for the slot duration at target frame rate.

2. **Content + filler plan:** The segment's `frame_count` covers the primary content, and Core provides an explicit filler plan (avails, commercials, interstitials) that AIR will play to cover the remainder of the slot.

AIR does not distinguish between "content" and "filler" — both are segments with frame counts. The invariant applies to the *aggregate* of all segments within a slot.

**Formal statement:**
```
Let slot_duration = scheduled end time - scheduled start time
Let segments[] = all segments in the playout plan for this slot
Let target_fps = configured program frame rate

Sum(segment.frame_count for segment in segments[]) ≥ slot_duration × target_fps

Exception: frame_count = 0 is valid for explicit zero-frame segments
(handled by INV-P8-ZERO-FRAME-READY / INV-P8-ZERO-FRAME-BOOTSTRAP)
```

**Clarification on slot vs. content duration:**

- **Grid block:** A scheduled time slot (e.g., 30 minutes)
- **Episode runtime:** The actual content duration (e.g., 22 minutes)
- **Filler:** Avails, commercials, interstitials that fill the gap (e.g., 8 minutes)

Core must provide segments (content + filler) whose aggregate frame count covers the grid block. AIR receives these as a sequence of segments and plays them in order.

**Boundary condition:** This invariant governs the *input* to AIR. AIR does not enforce it; AIR trusts Core to provide valid plans.

### Violation Consequences

When INV-SEGMENT-CONTENT-001 is violated:

- Segment exhausts content before its scheduled end time
- Pad frames fill remainder of segment duration
- If first segment is shallow, initial buffer never builds depth
- Preview segment may complete seek but have minimal content for switch
- Viewer sees black frames during scheduled content time
- No successor segment available to continue playback

**Cascade effects:**

- INV-DECODE-RATE-001 appears violated (buffer empties) due to insufficient input
- Switch readiness delayed (preview has no frames to cache)
- CATCH-UP ends with empty buffer (nothing to catch up with)

**Note:** Zero-frame segments are explicitly supported. Violation occurs when:
- A segment has `frame_count > 0` but `frame_count < segment_duration × fps`, OR
- The aggregate of all segments in a slot has insufficient frames to cover the slot

### Violation Detection

| Observation Point | Symptom |
|-------------------|---------|
| `FileProducer::IsEOF()` | Returns true before segment end time |
| Pad frame emission | Begins before scheduled segment boundary |
| Log: segment frame count | `frame_count` < `duration × fps` |
| First segment behavior | Only 1-2 frames consumed before pad emission |
| Preview readiness | Shadow caches frame but switch finds shallow buffer |

**Canonical violation signature:**
```
[StartChannel] segment frame_count=10, segment_duration=10s, fps=30
[FileProducer] EOF reached after frame #10
[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad frame #1
... (290 pad frames to fill remaining 9.67s)
[PlayoutEngine] No successor segment available
```

When EOF is reached, pad frames fill remaining duration, and no successor segment is queued, the plan was incomplete. Core should have either:
1. Provided a segment with `frame_count=300` (10s × 30fps), or
2. Provided the 10-frame segment followed by a filler segment covering the remainder

**Distinguishing from other violations:**

- If EOF not reached but buffer empty → INV-DECODE-RATE-001 or INV-PACING-001
- If EOF reached at segment boundary → correct behavior
- If EOF reached before segment boundary → INV-SEGMENT-CONTENT-001

### Non-Owners

| Subsystem | Why NOT owner | Constraint |
|-----------|---------------|------------|
| `PlayoutEngine` | Receives plan; does not generate it | Must not synthesize or modify segment parameters |
| `FileProducer` | Executes segment spec; does not validate content depth | Must not assume frame_count > 0; must handle zero-frame segments per INV-P8-ZERO-FRAME-READY |
| `ProgramOutput` | Consumes frames; no segment awareness | Must not assume frames will arrive; must handle empty buffer per INV-P10.5-OUTPUT-SAFETY-RAIL |
| `TimelineController` | Maps CT; no segment content knowledge | Must not assume segment provides frames for CT locking |

---

## Violation Discrimination Matrix

When pad frames are observed, use this matrix to identify the violated primitive:

| Pad emission rate | Decode loop active | EOF reached | Violated Invariant |
|-------------------|-------------------|-------------|-------------------|
| >> real-time (CPU speed) | Yes | No | **INV-PACING-001** |
| = real-time (30/sec) | Yes | No | **INV-DECODE-RATE-001** |
| = real-time (30/sec) | No (EOF) | Yes | **INV-SEGMENT-CONTENT-001** |
| >> real-time | No (EOF) | Yes | **INV-PACING-001** + **INV-SEGMENT-CONTENT-001** |

---

## Test Requirements

| Invariant | Required Contract Test |
|-----------|----------------------|
| INV-PACING-001 | `TEST_INV_PACING_001_FrameEmissionRate` — Verify frame emission matches target_fps ±ε |
| INV-DECODE-RATE-001 | `TEST_INV_DECODE_RATE_001_ProducerSustainsRealtime` — Verify decode rate ≥ target_fps when buffer has capacity |
| INV-SEGMENT-CONTENT-001 | (Core contract) — Verify segment frame_count ≥ duration × fps |

---

## Cross-Reference

These primitives derive other invariants documented elsewhere:

| Derived From | Derived Invariants |
|--------------|-------------------|
| INV-PACING-001 | INV-P10-REALTIME-THROUGHPUT, gap metric correctness, PTS advancement rate |
| INV-DECODE-RATE-001 | INV-P10-BUFFER-EQUILIBRIUM, shadow readiness timing, switch readiness |
| INV-SEGMENT-CONTENT-001 | First segment depth, CATCH-UP completion conditions |
