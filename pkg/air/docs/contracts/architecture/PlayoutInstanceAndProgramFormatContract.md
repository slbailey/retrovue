# PlayoutInstance & ProgramFormat Contract

**Status:** LOCKED (pre-implementation)  
**Scope:** Air (C++) playout engine  
**Audience:** Engine, Core (Python), gRPC boundary, refactor tooling  
**Related:** [PlayoutEngineContract.md](PlayoutEngineContract.md), [OutputBusAndOutputSinkContract.md](OutputBusAndOutputSinkContract.md)

## 1. Purpose

This contract defines how program signal format is established, owned, and enforced for a playout session in Air.

It explicitly separates:

- **Program signal definition** (what the channel is)
- **Output encoding / transport** (how the signal is delivered)

This contract exists to prevent format ambiguity, mid-stream renegotiation, and transport leakage into playout control.

## 2. Core Definitions (Normative)

### 2.1 PlayoutInstance

A **PlayoutInstance** represents a single active channel execution inside Air.

- One PlayoutInstance exists per active channel
- Air enforces at most one active PlayoutInstance

A PlayoutInstance owns:

- ProgramFormat
- ProducerBus(es)
- FrameRingBuffer
- ProgramOutput
- OutputBus
- TimingLoop
- PlayoutControl

**PlayoutInstance lifetime:**

StartChannel → Active → StopChannel → Destroyed

### 2.2 ProgramFormat (Per-Channel Signal Format)

**ProgramFormat** defines the canonical program signal produced by a channel.

It is:

- Per-channel
- Fixed for the lifetime of a PlayoutInstance
- Independent of encoding, muxing, or transport

**ProgramFormat includes (minimum):**

- Video width
- Video height
- Frame rate (timebase)
- Audio sample rate
- Audio channel count

**ProgramFormat explicitly does NOT include:**

- Codec (H.264, H.265, etc.)
- Bitrate
- GOP structure
- Container or transport (MPEG-TS, TCP, UDS)

## 3. Ownership & Invariants (Normative)

### 3.1 Ownership

| Concept | Owner |
|---------|-------|
| Channel identity | Core |
| ProgramFormat | Core (declares), Air (enforces) |
| PlayoutInstance | Air |
| Output encoding | OutputSink |

### 3.2 Invariants (Must Always Hold)

- ProgramFormat is established before playout begins
- ProgramFormat does not change during a PlayoutInstance
- All producers, buffers, renderers, and buses operate in ProgramFormat
- OutputSinks adapt ProgramFormat → delivery format
- StartChannel never specifies encoding or transport parameters

**Violation of any invariant is a contract breach.**

## 4. gRPC StartChannel Changes (Normative)

### 4.1 Motivation

Air must know what signal it is producing, but not how it is delivered.

Therefore, StartChannel must accept ProgramFormat.

### 4.2 gRPC Shape (Authoritative)

To preserve flexibility and avoid proto churn, ProgramFormat is passed as JSON.

```proto
message StartChannelRequest {
  int32 channel_id = 1;
  string plan_handle = 2;

  // Canonical per-channel program signal format.
  // JSON object; schema defined by this contract.
  string program_format_json = 10;
}
```

## 5. ProgramFormat JSON Schema (Normative)

### 5.1 Required Fields

```json
{
  "video": {
    "width": 1920,
    "height": 1080,
    "frame_rate": "30000/1001"
  },
  "audio": {
    "sample_rate": 48000,
    "channels": 2
  }
}
```

### 5.2 Rules

- `frame_rate` MUST be a rational string ("30000/1001", "25/1")
- All numeric values MUST be integers
- Unknown fields MUST be ignored (forward compatibility)
- Missing required fields MUST cause StartChannel to fail

## 6. Parsing & Validation (Normative)

- ProgramFormat JSON is parsed by PlayoutEngine during StartChannel
- Validation occurs before any producers or threads are started
- On validation failure:
  - StartChannel returns error
  - No partial PlayoutInstance may exist
- ProgramFormat is stored in PlayoutInstance as a strongly typed struct after parsing.

## 7. Relationship to Output (Normative)

- OutputBus emits frames in ProgramFormat
- OutputSink MUST adapt ProgramFormat to its encoding
- OutputSink MUST fail fast if it cannot support ProgramFormat

**Example:**

- 720p ProgramFormat + sink configured for 1080p → error
- 48kHz PCM + sink expecting 44.1kHz → error or resample (sink choice)

PlayoutEngine never performs format conversion.

## 8. Non-Goals (Explicit)

This contract does NOT define:

- Multiple ProgramFormats per channel
- Mid-stream format changes
- Dynamic resolution switching
- OutputSink negotiation protocols

Those may be added later under separate contracts.

## 9. Change Control

Any future change that:

- Allows ProgramFormat mutation during playback
- Pushes encoding parameters into StartChannel
- Allows OutputSink to dictate ProgramFormat

**violates this contract** and requires explicit architectural review.

## 10. Summary (Authoritative)

- Channels define what signal exists
- Air renders that signal
- Output sinks decide how it leaves the system

This contract locks that separation permanently.
