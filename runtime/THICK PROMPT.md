You are working on AIR.

AIR is a C++ runtime playout engine in the Retro IPTV Simulation Project.
AIR is responsible only for real-time execution correctness of a single active channel playout session.
AIR is not an editorial system and does not own scheduling, EPG, or multi-channel orchestration.

AIR enforces timing, buffering, producer switching, encoding, and output correctness.
All business intent and long-horizon truth live outside AIR.

────────────────────────
NON-GOALS (HARD BOUNDARIES)
────────────────────────
AIR does NOT:
- Build or interpret schedules or EPG data
- Decide what content should play
- Manage multiple channels concurrently
- Persist historical truth or as-run logs
- Own channel definitions or editorial rules
- Provide DVR, rewind, or catch-up semantics

Those concerns belong to Core (Python control plane).
AIR executes a plan that has already been decided elsewhere.

────────────────────────
MENTAL MODEL
────────────────────────
AIR runs at most one active PlayoutInstance at a time.

High-level signal flow:

Producer
 → InputBus / ProducerBus (LIVE or PREVIEW)
 → FrameRingBuffer
 → ProgramOutput
 → OutputBus
 → OutputSink (e.g., MPEG-TS)

Time is governed by a single MasterClock and a TimingLoop.
All execution is driven by real-time constraints, not persisted state.

────────────────────────
FIRST-CLASS COMPONENTS
(Use these names. Do not invent parallel abstractions.)
────────────────────────

ROOT / CONTROL
- PlayoutEngine
  - Root runtime object
  - Owns exactly one active PlayoutInstance
  - Enforces lifecycle invariants

- PlayoutControl
  - Explicit state machine governing runtime transitions
  - Valid phases include (canonical):
    Idle → Buffering → Ready → Playing → Paused → Stopping → Error
  - Owns all sequencing rules (attach/detach, start/stop, switch safety)

- PlayoutInterface
  - Thin adapter between gRPC surface and PlayoutEngine
  - Contains no business logic

SESSION MODEL
- PlayoutInstance
  - Represents one active runtime session
  - Identified by:
    - channel_id (external correlation only)
    - plan_handle
    - ProgramFormat
  - Owns:
    - Producers
    - InputBus / ProducerBus
    - FrameRingBuffer
    - ProgramOutput
    - OutputBus
    - TimingLoop
    - OutputSinks

IMPORTANT:
- AIR enforces at most ONE active PlayoutInstance.
- channel_id is supplied by Core and is used only for correlation, routing, and metrics.
- AIR does not own channel identity or channel persistence.

PRODUCERS
- IProducer
  - Minimal lifecycle interface (start, stop, readiness)

- FileProducer
  - FFmpeg-backed decode of local media
  - Supports segment parameters:
    - start_offset_ms
    - hard_stop_time_ms

- ProgrammaticProducer
  - Synthetic frame generator
  - Used for tests, harnesses, and diagnostics
  - No FFmpeg dependency

INPUT PATH (FIRST-CLASS)
- InputBus (also referred to in docs/code as ProducerBus)
  - Routed producer input path
  - Supports at least two logical busses:
    - LIVE
    - PREVIEW
  - NOT a buffer or store
  - Atomic switching is controlled exclusively by PlayoutControl
  - Feeds downstream buffering stages

BUFFERING / OUTPUT PATH
- FrameRingBuffer
  - Lock-free circular buffer
  - Holds decoded audio/video frames
  - Enforces backpressure and pacing

- ProgramOutput
  - Consumes frames from FrameRingBuffer
  - Routes frames into OutputBus
  - Headless (no transport concerns)

- OutputBus
  - Signal path between ProgramOutput and attached OutputSink(s)
  - OutputSinks may be attached/detached at runtime
  - Attachment sequencing is governed by PlayoutControl

OUTPUT SINKS
- IOutputSink
  - Interface for encoding/muxing/transport

- MpegTSOutputSink
  - Primary production sink
  - Encodes H.264
  - Muxes MPEG-TS
  - Streams over UDS or TCP
  - Owns encoder and mux pipelines

TIMING / CLOCK
- MasterClock
  - Single authoritative time source
  - Provides monotonic ↔ UTC mapping
  - Owns drift correction and wait semantics
  - No component calls system time directly

- TimingLoop
  - Drives frame pacing and scheduling
  - Coordinates with MasterClock
  - Enforces real-time constraints

TELEMETRY
- MetricsExporter
- MetricsHTTPServer
  - Prometheus-compatible /metrics endpoint
  - Exposes runtime state, timing, and health
  - Observability only; no control authority

────────────────────────
gRPC INTERFACE (CANONICAL)
────────────────────────
Source of truth: protos/playout.proto

Service: PlayoutControl (API v1.x)

RPCs (do not rename or invent):
- StartChannel
  - Activates the single playout session
  - Parameters include:
    - channel_id
    - plan_handle
    - program_format_json
    - output parameters
  - A second distinct channel_id while active returns error

- StopChannel
  - Graceful shutdown of the active session

- UpdatePlan
  - Swaps the active plan without stopping the session

- LoadPreview
  - Loads a producer into PREVIEW bus

- SwitchToLive
  - Atomically promotes PREVIEW to LIVE
  - Must preserve PTS continuity

- AttachStream
  - Attaches an OutputSink to OutputBus

- DetachStream
  - Detaches OutputSink from OutputBus

- GetVersion
  - Returns API version

gRPC is INTERNAL ONLY.
AIR never exposes gRPC directly to viewers.

────────────────────────
PROGRAM FORMAT (SESSION INVARIANT)
────────────────────────
- ProgramFormat is supplied as JSON at session start
- Defines canonical signal format:
  - video: width, height, frame_rate
  - audio: sample_rate, channels
- ProgramFormat is FIXED for the lifetime of the PlayoutInstance
- Producers and sinks must conform or fail fast

────────────────────────
KEY INVARIANTS
────────────────────────
- One active PlayoutInstance at a time
- channel_id is correlation only
- ProgramFormat immutable per session
- InputBus switching is atomic and controlled
- Output attachment follows PlayoutControl state rules
- PTS continuity is preserved across preview → live
- AIR enforces correctness; it does not invent intent

────────────────────────
HOW TO THINK ABOUT CHANGES
────────────────────────
When asked “add X to AIR”:

1) Verify X belongs to runtime execution (timing, buffering, producer behavior, output, telemetry, or gRPC surface).
2) Identify which first-class component(s) are affected.
3) Preserve all stated invariants unless explicitly redefining them.
4) Update documentation/contracts first if behavior changes.
5) Do NOT introduce Core/editorial concepts (schedules, EPG, zones, policies) into AIR unless the docs explicitly define them.

If X does not fit cleanly, it must be proposed as a new first-class component with explicit contracts.

────────────────────────
ACKNOWLEDGEMENT
────────────────────────
Confirm understanding of AIR as a single-session, C++ runtime playout engine with explicit buses, strict timing control, gRPC-defined surface, and hard separation from editorial control plane responsibilities.
Do not proceed until this model is accepted.
