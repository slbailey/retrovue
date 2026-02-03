# 📺 Canonical Runtime Dataflow

**Status:** _Canonical_  
**Scope:** AIR runtime only (channel execution path)  
**Goal:** Describe the minimal professional broadcast dataflow that preserves the [Broadcast Constitution](./BROADCAST_CONSTITUTION.MD):

- **Clock authority**
- **Continuous emission**
- **Pad-first operation**
- **Sink-attachment independence**

>This document describes _what happens at runtime_, not implementation details.

---

## 1. 🛤️ The Broadcast Line

A channel is a continuous conveyor belt:

```
MasterClock → TimelineController → FrameSelection → OutputBus → Sinks → Transport
```
**Key Property:**  
Time advances _even if content does not_.  
The pipeline must _always have something to emit_.

---

## 2. 🪄 Canonical Streams and Formats

A channel has a fixed, declared **house format**:
- **Video:** width, height, fps, pixel format _(implicitly)_
- **Audio:** sample rate, channels, sample format
- **Mux/transport:** MPEG-TS / HLS / etc. _(sink-dependent)_

**Every frame** that enters the OutputBus is already in house format.  
_No downstream component negotiates format._

---

## 3. 🎭 Roles in the Dataflow

### 3.1 ⏰ MasterClock (_Time Source_)

- **Inputs:** system time
- **Outputs:** monotonic “now”, epoch establishment

**Responsibilities:**
- Establishes an **epoch** once per channel session
- Provides stable **now** to all timing logic
- Never resets during a session
- No other component defines “now”

---

### 3.2 🕰️ TimelineController (_Schedule Interpreter_)

- **Inputs:**
  - Session epoch
  - Planned segments/boundaries from control plane
  - Producer “first frame” event _(for mapping lock only)_
- **Outputs:**
  - Continuous, monotonic CT mapping (“channel time”)
  - Segment state: current segment, next boundary time, mapping locked flag

**Responsibilities:**
- Declares what the channel _must_ air at each instant
- Locks mapping on first admitted frame of a segment _(video anchor)_
- Advances CT based on clock, **not** frame availability
- Treats decoder EOF as an _event_, not an authority

**Never waits for:**
- Buffer depth
- Sink presence
- Producer readiness

---

### 3.3 🎛️ Producers (_Frame Sources_)

There are **two canonical producer classes**:
- **Pad Producer** _(first-class)_
- **Content Producer** (file/live/etc.)

**Both produce:**
- video frames  
- audio frames  

**Both are:**
- time-blind
- non-blocking
- format-normalized on output

#### Pad Producer
- Conceptually always running
- Produces deterministic black video & silence audio at house format

#### Content Producer
- Produces decoded real frames _opportunistically_
- May **stall, seek, EOF, or fail** — none of which halts the channel

---

### 3.4 🔀 FrameSelection (_ProgramOutput role_)

_This is the “broadcast switcher” inside AIR._

- **Inputs:**
  - TimelineController segment state & boundary schedule
  - Pad frames _(always available)_
  - Real content frames _(if available)_
- **Outputs:**
  - Exactly **one video frame per frame period**
  - Continuous audio sample stream

**Responsibilities:**
- Chooses what to emit at each instant:  
  - **real** _if eligible_  
  - otherwise, **pad**
- Guarantees cadence
- Guarantees continuity & monotonic PTS/CT semantics
- Applies switching rules at boundary instants
- Never generates frames itself—the switcher only selects  
  - FrameSelection is not a producer, but a router with pacing.

---

### 3.5 🚏 OutputBus (_Routing Plane_)

- **Inputs:** house-format frames from FrameSelection
- **Outputs:** same frames delivered to all attached sinks

**Responsibilities:**
- Delivers frames to sinks if present, drop if not (or optionally meter for diagnostics)
- Sink-agnostic and timing-agnostic
- Never blocks upstream
- Must never be required for liveness (no mandatory prebuffer or readiness gate)
- If prebuffer exists, it must be bounded, shallow, and avoid creating readiness semantics

---

### 3.6 🧑‍💻 Sinks (_Encoding/Muxing_)

A sink is a downstream consumer that converts frames into bytes (e.g., MPEG-TS encoder/muxer).

- **Inputs:** video frames, audio frames
- **Outputs:** decodable byte stream

**Responsibilities:**
- Encodes/muxes without blocking upstream
- Emits decodable output as soon as attached (header, then IDR and audio)
- Maintains output cadence rules (e.g., PCR pacing)
- Accepts pad frames if no real content is available
- May internally pace emission, but must **never** apply backpressure upstream that causes audio drops

---

## 4. 🏃 Runtime Dataflow Timeline (Step-by-Step)

### 4.1 ▶️ Channel Session Start

- Control plane requests channel start with house format
- MasterClock establishes epoch
- TimelineController enters segment 1 “mapping pending”
- Pad Producer becomes available immediately (conceptually “always on”)
- FrameSelection emits pad frames at real-time cadence

The channel is already _broadcast-valid_ immediately, even without any sinks.

---

### 4.2 🔌 Sink Attachment (Any Time)

When a sink attaches:
- Must receive a hot stream immediately
- Must become decodable within bounded time (header + IDR + audio)
- **Attachment does NOT affect** timeline, producers, or FrameSelection

Attachment is orthogonal to runtime or emission.

---

### 4.3 🎬 Content Prefeed (Preview) & Mapping Lock

- Content Producer begins decoding (may seek/preroll)
- On first eligible video frame:
  - TimelineController locks mapping (CT_start ↔ MT_start)
  - FrameSelection prefers real frames as they arrive; pad always available
  - **No waiting permitted**  
  - If real content is late, **pad continues uninterrupted**

---

### 4.4 ▶️ Steady State Playout
- Each video frame period:
  - MasterClock provides “now”
  - TimelineController provides segment mapping & current CT
  - FrameSelection outputs:
    - `1 video frame` (real or pad)
    - corresponding audio samples for period
  - OutputBus forwards to sinks
  - Sinks emit bytes

- If real frames missing, _pad_ for that interval

**Steady State:**
- Bounded buffer depth equilibrium
- No drops of audio samples
- Monotonic CT/PTS
- Continuous TS emission

---

### 4.5 ⏩ Boundary Switching (Schedule-Driven)
- At scheduled boundary time:
  - Switch occurs because **clock says so** (not “ready” or “successor emission” or “buffer depth” or “EOF”)
  - If successor isn’t ready: **pad fills until it is**
- **Switching:**
  - TimelineController declares boundary and segment ownership transitions
  - FrameSelection enforces cut rules & pacing

---

### 4.6 ⛔ EOF Inside a Segment (Content Deficit)
- **EOF ≠ segment end**
- If Content Producer EOFs before boundary:
  - FrameSelection immediately falls back to pad
  - Timeline continues advancing
  - Output continues emitting
  - At boundary, switching proceeds as normal

---

## 5. 🏅 The Three "Always-On" Guarantees

### 5.1 🎞️ Video Cadence Guarantee
- **Every frame period:** one video frame emitted (real _or_ pad)

### 5.2 🔊 Audio Continuity Guarantee
- Audio is **continuous and monotonic**
- _No sample drops due to queue fullness_
- Overflow must throttle producer, **not** discard samples

### 5.3 🟩 Decodability Guarantee
- Once a sink attaches, output becomes and remains decodable:
  - header written immediately
  - IDR produced _before_ video emission
  - audio always present _(pad silence if needed)_

---

## 6. 🚫 Where Your Stack Might Be "Not Broadcast"

Common architectural smells this dataflow _forbids_:

- "ProgramOutput" **generating** frames instead of _selecting_
- Using sink attachment as a **readiness gate**
- Deep pre-sink buffers to prevent mux starvation
- Mux loop waiting on queues (not time-driven)
- Audio drops under backpressure
- EOF triggers teardown / viewer disconnect logic

_If any of those exist, they must be eliminated or demoted to diagnostics only._

---

## 7. 📑 Canonical Interfaces (Conceptual)

_These are not code APIs — they define the **contract boundary**:_

**Producers → FrameSelection**
- `VideoFrame { pts, data, metadata }`
- `AudioFrame { pts, samples, metadata }`

**FrameSelection → OutputBus**
- Same frames, already house-normalized

**OutputBus → Sink**
- `ConsumeVideo(frame)`
- `ConsumeAudio(frame)`

_No producer speaks to a sink.  
No sink speaks to a producer.  
Only FrameSelection decides “real vs pad”._

---