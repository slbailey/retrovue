You are working on AIR.

AIR is a C++ runtime playout engine for the Retro IPTV Simulation Project.
AIR enforces real-time execution correctness for a single active channel playout session.
AIR does not own schedules, EPG, channels, or editorial intent — those belong to Core.

────────────────────────
BOUNDARIES
────────────────────────
AIR IS responsible for:
- Runtime execution correctness
- Timing, buffering, and pacing
- Producer switching (preview ↔ live)
- Encoding, muxing, and output
- gRPC control surface
- Telemetry and metrics

AIR is NOT responsible for:
- Scheduling or EPG
- Multi-channel orchestration
- Editorial decisions
- Persistence of business truth
- As-run logging

────────────────────────
MENTAL MODEL
────────────────────────
One active PlayoutInstance at a time.

Signal flow:
Producer
 → InputBus / ProducerBus (LIVE or PREVIEW)
 → FrameRingBuffer
 → ProgramOutput
 → OutputBus
 → OutputSink (MPEG-TS)

Execution is driven by MasterClock + TimingLoop.

────────────────────────
FIRST-CLASS COMPONENTS
────────────────────────
Root:
- PlayoutEngine (owns one active session)
- PlayoutControl (explicit state machine)
- PlayoutInterface (gRPC adapter)

Session:
- PlayoutInstance
  - channel_id (external correlation only)
  - plan_handle
  - ProgramFormat (immutable per session)

Producers:
- IProducer
- FileProducer (FFmpeg decode, segment offsets)
- ProgrammaticProducer (synthetic/test)

Input:
- InputBus / ProducerBus
  - LIVE + PREVIEW
  - Atomic switching via PlayoutControl
  - Not a buffer

Buffer / Output:
- FrameRingBuffer
- ProgramOutput
- OutputBus
- IOutputSink
- MpegTSOutputSink

Timing:
- MasterClock (single time authority)
- TimingLoop (pacing + scheduling)

Telemetry:
- MetricsExporter
- MetricsHTTPServer (/metrics)

────────────────────────
gRPC SURFACE (CANONICAL)
────────────────────────
Source of truth: protos/playout.proto

Service: PlayoutControl

RPCs:
- StartChannel
- StopChannel
- UpdatePlan
- LoadPreview
- SwitchToLive
- AttachStream
- DetachStream
- GetVersion

gRPC is internal only.

────────────────────────
SESSION INVARIANTS
────────────────────────
- At most one active PlayoutInstance
- channel_id is correlation only
- ProgramFormat fixed for session lifetime
- InputBus switching is atomic
- PTS continuity preserved across preview → live
- Output attachment obeys PlayoutControl states

────────────────────────
CHANGE DISCIPLINE
────────────────────────
When asked “add X to AIR”:
1) Confirm X belongs to runtime execution.
2) Identify affected first-class components.
3) Preserve all invariants.
4) Update contracts/docs before behavior changes.
5) Do NOT introduce Core concepts.

ACKNOWLEDGEMENT:
Confirm understanding of AIR as a single-session C++ playout engine with explicit buses, strict timing control, and gRPC-defined boundaries.
Do not proceed until accepted.
