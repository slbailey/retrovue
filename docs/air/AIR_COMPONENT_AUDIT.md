# Air Component Audit

**Date:** January 28, 2026  
**Purpose:** Authoritative snapshot of the Air (C++) playout engine: first-class objects, relationships, gRPC interfaces, and architectural boundaries. Use this document for onboarding, refactoring, and contract alignment.

---

## Table of Contents

1. [Explicit Non-Goals of Air](#explicit-non-goals-of-air)
2. [Architecture Overview](#architecture-overview)
3. [gRPC Interfaces](#grpc-interfaces)
4. [First-Class Objects](#first-class-objects)
5. [Component Relationships](#component-relationships)
6. [Directory Structure](#directory-structure)
7. [Key Documentation](#key-documentation)
8. [Build and Test](#build-and-test)

---

## Explicit Non-Goals of Air

Air intentionally does NOT:

- Manage multiple channels internally
- Persist playout history
- Interpret schedules or EPG data
- Make business or editorial decisions
- Coordinate redundancy or failover

These concerns are owned by Core.  
Air enforces only runtime execution correctness.

---

## Architecture Overview

**Mental model:** Air is a **single-channel playout engine**. It runs one playout session at a time. Channel identity and multi-channel coordination live in Core (Python). Air owns only runtime execution state and enforces execution correctness (timing, buffer, encoder invariants).

What Air does:

- Receives playout control via gRPC (`channel_id` is an external identifier for correlation, not internal ownership)
- Decodes video/audio via FFmpeg (FileProducer) or synthetic frames (ProgrammaticProducer)
- Stages frames in a lock-free ring buffer
- Renders frames (headless or preview) and routes through OutputBus to OutputSink
- OutputSink encodes, muxes, and streams MPEG-TS over UDS/TCP when attached

### High-Level Flow

```
Core ChannelManager (owns channel lifecycle, schedules)
         │
         ▼ gRPC (channel_id for correlation only)
PlayoutControlImpl → PlayoutController → PlayoutEngine
         │
         ▼ one active session
┌─────────────────────────────────────────────────────────┐
│  PlayoutSession (internal: one per active “channel”)    │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Producer (FileProducer / ProgrammaticProducer)     │  │
│  │         ▼                                          │  │
│  │ FrameRingBuffer (lock-free circular buffer)        │  │
│  │         ▼                                          │  │
│  │ FrameRenderer (headless; routes to OutputBus)      │  │
│  │         ▼                                          │  │
│  │ OutputBus (signal path; routes to attached sink)  │  │
│  │         ▼                                          │  │
│  │ OutputSink (MpegTSOutputSink: encode, mux, stream) │  │
│  └───────────────────────────────────────────────────┘  │
│  EngineStateMachine (RuntimePhase, bus switching)       │  │
│  OrchestrationLoop (timing, backpressure)               │  │
└─────────────────────────────────────────────────────────┘
```

---

## gRPC Interfaces

**Source:** `protos/playout.proto` (canonical; repo root).  
**Generated C++:** `pkg/air/build/playout.pb.h`, `playout.grpc.pb.h` (CMake generates from same proto).

**Service:** `PlayoutControl` (API version 1.0.0).

| RPC | Request | Response | Purpose |
|-----|---------|----------|---------|
| StartChannel | StartChannelRequest | StartChannelResponse | Activate playout session (plan_handle, port). One session at a time; second distinct channel_id returns error. |
| StopChannel | StopChannelRequest | StopChannelResponse | Graceful shutdown of active session. |
| UpdatePlan | UpdatePlanRequest | UpdatePlanResponse | Swap active plan for session without stopping. |
| GetVersion | ApiVersionRequest | ApiVersion | API version string. |
| LoadPreview | LoadPreviewRequest | LoadPreviewResponse | Load asset into preview bus; shadow decode. |
| SwitchToLive | SwitchToLiveRequest | SwitchToLiveResponse | Promote preview bus to live atomically; PTS continuity. |
| AttachStream | AttachStreamRequest | AttachStreamResponse | Attach OutputSink (e.g. MpegTSOutputSink) to OutputBus for byte output. |
| DetachStream | DetachStreamRequest | DetachStreamResponse | Detach OutputSink from OutputBus. |

**Convention:** All request messages carry `channel_id` (int32). This is an **external correlation ID** supplied by Core. Air does not own channel identity or lifecycle; it uses `channel_id` for routing and metrics only.

---

## First-Class Objects

### Runtime (control and session)

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **PlayoutEngine** | `runtime/PlayoutEngine.h` | Root execution unit. Single playout session at a time. Owns runtime graph (producer → buffer → renderer → OutputBus → OutputSink), clock, and engine-level state. Provides AttachOutputSink/DetachOutputSink, ConnectRendererToOutputBus methods. Does *not* own channel lifecycle or schedules. |
| **PlayoutController** | `runtime/PlayoutController.h` | Thin adapter: gRPC layer → PlayoutEngine. Delegates all ops to engine. Provides AttachOutputSink/DetachOutputSink, GetOutputBus, ConnectRendererToOutputBus wrappers. |
| **EngineStateMachine** | `runtime/EngineStateMachine.h` | Enforces valid sequencing of runtime ops (PTS, buffer priming, decode/render order). Uses **RuntimePhase** (kIdle, kBuffering, kReady, kPlaying, kPaused, kStopping, kError). Governs OutputBus attach/detach transitions via CanAttachSink/CanDetachSink. Tracks sink attachment state. Does *not* represent channel lifecycle or scheduling. |
| **ProducerBus** | `runtime/ProducerBus.h` | Routed producer input path (LIVE or PREVIEW). Not storage; may be empty, primed, or active. Switched atomically by EngineStateMachine. |
| **OrchestrationLoop** | `runtime/OrchestrationLoop.h` | Tick loop, backpressure events, timing/coordination with MasterClock. |

**PlayoutSession** (internal struct in `PlayoutEngine.cpp`): Holds one session’s runtime: `channel_id` (external), `plan_handle`, ring_buffer, live_producer, preview_producer, renderer, orchestration_loop, EngineStateMachine (control), OutputBus. One session per active “channel” slot; Air enforces at most one active session.

### Producers

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **IProducer** | `producers/IProducer.h` | Minimal interface: start(), stop(), isRunning(). |
| **FileProducer** | `producers/file/FileProducer.h` | Decodes local video/audio (FFmpeg), produces frames/audio into FrameRingBuffer. Segment params: start_offset_ms, hard_stop_time_ms. |
| **ProgrammaticProducer** | `producers/programmatic/ProgrammaticProducer.h` | **Scaffolding / test-only.** Synthetic frames; no FFmpeg. Same IProducer lifecycle; will be replaced by domain producers. |

### Buffer and renderer

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **FrameRingBuffer** | `buffer/FrameRingBuffer.h` | Lock-free circular buffer for Frame/AudioFrame. Producer pushes, renderer consumes. |
| **FrameRenderer** | `renderer/FrameRenderer.h` | Consumes buffer; headless or preview. Routes frames to OutputBus when connected, else uses legacy callbacks. |

### Output (bus and sink)

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **OutputBus** | `output/OutputBus.h` | Signal path for program output. Routes frames to currently attached OutputSink. Governed by EngineStateMachine. Does not own transport, threads, or encoding. Validates attach/detach via EngineStateMachine. |
| **IOutputSink** | `output/IOutputSink.h` | Interface for output sinks. Consumes frames from OutputBus; performs encoding, muxing, and transport. Defines Start(), Stop(), ConsumeVideo(), ConsumeAudio(), status reporting. |
| **MpegTSOutputSink** | `output/MpegTSOutputSink.h` | Concrete OutputSink implementation. Encodes to H.264, muxes to MPEG-TS, streams over UDS/TCP. Owns EncoderPipeline, frame queues, and MuxLoop worker thread. Uses playout_sinks::mpegts::EncoderPipeline internally. |

**Note:** Legacy `MpegTSPlayoutSink` (in `playout_sinks/mpegts/` and `sinks/mpegts/`) still exists but is being phased out in favor of OutputBus/OutputSink architecture. New code should use MpegTSOutputSink.

### Timing and telemetry

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **MasterClock** | `timing/MasterClock.h` | now_utc_us(), now_monotonic_s(), scheduled_to_utc_us(), drift_ppm(), WaitUntilUtcUs(). Single time authority. |
| **MetricsExporter** | `telemetry/MetricsExporter.h` | Prometheus /metrics; ChannelState (STOPPED, BUFFERING, READY, ERROR_STATE); per-channel metrics. |


### gRPC service

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **PlayoutControlImpl** | `playout_service.h` | Implements PlayoutControl service. Delegates to PlayoutController. Manages AttachStream/DetachStream (creates/destroys OutputSink, attaches/detaches from OutputBus). |

---

## Component Relationships

- **PlayoutControlImpl** → **PlayoutController** → **PlayoutEngine**.  
  PlayoutEngine owns **PlayoutSession** (or sessions map, one active); each session owns:
  - **FrameRingBuffer**
  - **EngineStateMachine** (control), **ProducerBus**es (preview, live)
  - **FileProducer** (live, optional preview), **FrameRenderer**
  - **OutputBus** (signal path; routes frames to attached OutputSink)
  - **OrchestrationLoop** (if used)
- **EngineStateMachine** owns preview/live **ProducerBus**es; loads/switches producers via factory and **activatePreviewAsLive**. Governs OutputBus attach/detach transitions.
- **FileProducer** / **ProgrammaticProducer** implement **IProducer**; push into **FrameRingBuffer**.
- **FrameRenderer** reads **FrameRingBuffer**; routes frames to **OutputBus** when connected (via `SetOutputBus()`), else uses legacy side_sink_ callbacks. Supports both modes during transition.
- **OutputBus** routes frames to currently attached **OutputSink** (e.g. MpegTSOutputSink). Attachment/detachment validated by EngineStateMachine. OutputBus does not own transport, threads, or encoding.
- **MpegTSOutputSink** implements **IOutputSink**; consumes frames from OutputBus via ConsumeVideo/ConsumeAudio; enqueues to internal queues; MuxLoop thread drains queues and encodes via EncoderPipeline; writes TS packets to file descriptor (UDS/TCP). Created by PlayoutControlImpl on SwitchToLive when stream attached.
- **MasterClock** and **MetricsExporter** are shared into PlayoutEngine and passed into session components.
- **One-session rule:** `PlayoutEngine::StartChannel` returns error if a session already exists for a *different* channel_id; idempotent for same channel_id.
- **OutputBus invariant:** At most one OutputSink attached per OutputBus (enforced by EngineStateMachine). OutputBus does not perform attach/detach autonomously; all operations validated by EngineStateMachine.
- **PlayoutControlImpl** creates MpegTSOutputSink on SwitchToLive (if AttachStream was called); attaches to OutputBus via PlayoutController; connects renderer to OutputBus to start frame flow.

---

## Directory Structure

```
pkg/air/
├── include/retrovue/
│   ├── buffer/          FrameRingBuffer.h
│   ├── decode/          FFmpegDecoder.h, FrameProducer.h (legacy/decode layer)
│   ├── output/          OutputBus.h, IOutputSink.h, MpegTSOutputSink.h
│   ├── playout_sinks/   IPlayoutSink.h, mpegts/* (legacy MpegTSPlayoutSink, EncoderPipeline, TSMuxer, TsOutputSink - used by MpegTSOutputSink)
│   ├── producers/       IProducer.h, file/FileProducer.h, programmatic/ProgrammaticProducer.h
│   ├── renderer/        FrameRenderer.h
│   ├── runtime/         PlayoutEngine, PlayoutController, EngineStateMachine, ProducerBus, OrchestrationLoop
│   ├── sinks/           Legacy IPlayoutSink.h, mpegts/* (legacy MpegTSPlayoutSink - being phased out)
│   ├── telemetry/       MetricsExporter, MetricsHTTPServer
│   └── timing/          MasterClock.h
├── src/
│   ├── buffer/          FrameRingBuffer.cpp
│   ├── decode/          FFmpegDecoder, FrameProducer
│   ├── output/           OutputBus.cpp, MpegTSOutputSink.cpp
│   ├── playout_sinks/   mpegts/* (EncoderPipeline, TSMuxer, MpegTSEncoder, TsOutputSink - used by MpegTSOutputSink)
│   ├── producers/       file/FileProducer, programmatic/ProgrammaticProducer
│   ├── renderer/        FrameRenderer.cpp
│   ├── runtime/         PlayoutEngine, PlayoutController, EngineStateMachine, ProducerBus, OrchestrationLoop
│   ├── playout_service.cpp, playout_service.h   PlayoutControlImpl
│   ├── main.cpp
│   ├── telemetry/       MetricsExporter, MetricsHTTPServer
│   └── timing/          SystemMasterClock, TestMasterClock
├── tests/               Contract tests, fixtures (ChannelManagerStub, etc.)
├── core_test_harness/   Python harness (file_decoder, frame_ring_buffer, etc.)
└── CMakeLists.txt       Proto generation, retrovue_air_core, retrovue_air, contracts_playoutengine_tests
```

**Proto:** Single source `protos/playout.proto` at repo root. Generate with `scripts/air/generate_proto.sh` (Python stubs for Core); C++ generated by Air’s CMake.

---

## Key Documentation

| Area | Location |
|------|----------|
| Air docs index | `docs/air/README.md` |
| Architecture | `docs/air/architecture/ArchitectureOverview.md` |
| Domain / contracts | `docs/air/domain/*.md`, `docs/air/contracts/*.md` |
| Phase 6A (control surface, producer) | `docs/air/contracts/Phase6A-*.md` |
| Phase 8 (transport, TS mux, segment) | `docs/air/contracts/Phase8-*.md` |
| PlayoutEngine / PlayoutControl | `docs/air/domain/PlayoutEngineDomain.md`, `PlayoutControlDomain.md`; contract `PlayoutEngineContract.md` |
| OutputBus / OutputSink | `docs/air/contracts/OutputBusAndOutputSinkContract.md` |
| FileProducer | `docs/air/domain/FileProducerDomain.md`, `FileProducerDomainContract.md` |
| Build | `docs/air/build.md`; CLAUDE.md in repo root |

---

## Build and Test

- **Configure (from repo root):**  
  `cmake -S pkg/air -B pkg/air/build -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" -DCMAKE_BUILD_TYPE=RelWithDebInfo`
- **Build:**  
  `cmake --build pkg/air/build -j$(nproc)`
- **Tests:**  
  `ctest --test-dir pkg/air/build --output-on-failure`
- **Proto (Python stubs for Core):**  
  `sh scripts/air/generate_proto.sh`

Build output must live under **pkg/air/build** (see CLAUDE.md).
