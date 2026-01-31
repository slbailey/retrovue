# Output Switching Contract

_Related: [ProducerBus Contract](ProducerBusContract.md) · [OutputBus & OutputSink](OutputBusAndOutputSinkContract.md) · [BlackFrameProducer Contract](BlackFrameProducerContract.md)_

**Status:** Normative
**Scope:** Air (C++) playout engine — bus switching behavior
**Audience:** Engine implementers, future maintainers

---

## 1. Purpose

This contract defines the invariants for switching between Live and Preview buses in AIR. The goal is seamless, gapless transitions between content segments with no stalls, glitches, or decoder startup delays at switch time.

---

## 2. System Components

### 2.1 Given

| Component | Description |
|-----------|-------------|
| **Live Bus** | The currently active producer bus, emitting decoded frames to output. |
| **Preview Bus** | The next producer bus, pre-decoding frames in preparation for switch. |
| **Output Bus** | Consumes decoded frames from one upstream bus and routes to encoding/muxing. |

Each bus is capable of producing decoded frames independently.

---

## 3. Invariants (Normative)

### 3.1 Single-Source Output

The Output Bus consumes frames from **exactly one** upstream bus at any instant.

- There is never a moment where Output reads from both Live and Preview.
- There is never a moment where Output reads from neither (except dead-man failsafe).

### 3.2 Hot-Switch Continuity

When a switch is issued:

- The Output Bus changes its source **immediately**.
- The frame stream emitted by Output remains **continuous** across the switch.
- No gap, stall, or frame discontinuity is introduced by the switch itself.

### 3.3 Pre-Decoded Readiness

Any bus eligible to become the Output source **must already have decoded frames available** at switch time.

- Preview Bus must be running and have frames buffered before `SwitchToLive` is called.
- Decoder initialization, seeking, and initial decode happen **before** the switch, not during.
- The switch is instantaneous because frames are already waiting.

### 3.4 No Implicit Draining

A switch **does not wait** for the previously active bus to drain.

- Frames remaining in the previous bus are **not emitted** after the switch.
- The old bus is stopped; its remaining frames are discarded.
- Output immediately begins consuming from the new source.

### 3.5 Pre-Encoding Boundary

Switching occurs on **decoded frames**, not encoded streams.

- The switch point is between producer buses and Output Bus.
- Encoding consumes frames only from Output Bus.
- Encoding is **never** a switch boundary — the encoder sees a continuous frame stream.

### 3.6 Isolation

Live and Preview buses **do not share**:

- Decoders (each has its own decode context)
- Frame buffers (each writes to its own ring buffer)
- State (each producer is fully independent)

This isolation enables true parallel operation and prevents interleaving.

---

## 4. Failure Conditions

The following are **contract violations** and must not occur:

| Failure | Description |
|---------|-------------|
| **Output stalls during switch** | Output Bus stops emitting frames while switching sources. |
| **Output restarts during switch** | Output Bus or downstream encoding pipeline is reinitialized. |
| **Duplicate frames emitted** | Same frame emitted twice due to switch logic. |
| **Decoder initialization at switch time** | Any decoder setup occurs as a result of `SwitchToLive`. |
| **Encoded stream switching** | Switching occurs at the TS/mux level rather than decoded frame level. |
| **Buffer interleaving** | Frames from Live and Preview appear interleaved in Output. |

---

## 5. Reference Implementation Semantics (Non-Normative)

_This section describes one compliant implementation. Alternate implementations are permitted provided all invariants in Sections 3 and 4 are satisfied._

### 5.1 LoadPreview

When Core calls `LoadPreview`:

1. Create Preview Bus with its own dedicated ring buffer.
2. Create and start Preview producer (decoder begins filling buffer).
3. Preview runs in parallel with Live — no interference.

### 5.2 SwitchToLive

When Core calls `SwitchToLive`:

1. Stop or detach Live producer from Output (implementation-defined lifecycle).
2. Redirect Output Bus to consume from Preview's buffer.
3. Preview producer (already running) becomes the new Live producer.
4. Old Live buffer is discarded (not drained).

The switch is instantaneous because:
- Preview already has frames buffered.
- No decoder initialization occurs.
- No waiting for anything.

### 5.3 Buffer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ┌──────────────┐     ┌──────────────────┐                  │
│  │ Live Producer│────▶│ Live Ring Buffer │──┐               │
│  └──────────────┘     └──────────────────┘  │               │
│                                             │  ┌──────────┐ │
│                                             ├─▶│Output Bus│─┼──▶ Encoder
│                                             │  └──────────┘ │
│  ┌─────────────────┐  ┌─────────────────────┐│              │
│  │ Preview Producer│─▶│ Preview Ring Buffer │┘              │
│  └─────────────────┘  └─────────────────────┘               │
│                                                             │
└─────────────────────────────────────────────────────────────┘

On SwitchToLive: Output Bus redirects from Live Buffer to Preview Buffer.
Preview Buffer becomes the new Live Buffer.
```

---

## 6. Rationale

### Why Pre-Decoded Readiness?

Decoder initialization (opening file, parsing headers, seeking, decoding first frames) takes 100-500ms. If this happens at switch time, Output stalls. By requiring Preview to be pre-decoded, the switch is a simple pointer redirect.

### Why No Draining?

Draining the old buffer before switching introduces a gap. During drain:
- Old producer is stopped (no new frames)
- Buffer empties at playback rate
- New producer hasn't started yet
- Gap occurs

By not draining, we eliminate this gap. Old frames are simply discarded.

### Why Isolation?

If Live and Preview shared a buffer, we'd get A/B/A/B interleaving. Separate buffers ensure clean separation. The switch is atomic — one moment we read from buffer A, next moment from buffer B.

---

## 7. See Also

- [ProducerBus Contract](ProducerBusContract.md) — Live/Preview bus definitions
- [OutputBus & OutputSink Contract](OutputBusAndOutputSinkContract.md) — Output path
- [BlackFrameProducer Contract](BlackFrameProducerContract.md) — Fallback when no frames available
