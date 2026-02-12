# Air Architecture Reference Contract

**Purpose:** Canonical reference for the Air (C++) playout engine: first-class components, boundaries, gRPC surface, ownership, and directory layout. This document is the **reference contract** for architecture—the codebase is the source of truth; this doc defines the intended first-class citizens and invariants. Use for onboarding, design review, and contract alignment.

**Status:** Reference (canonical). Not an audit or findings document.

---

## Table of Contents

1. [Explicit Non-Goals of Air](#explicit-non-goals-of-air)
2. [Architecture Overview](#architecture-overview)
3. [gRPC Interfaces](#grpc-interfaces)
4. [First-Class Components](#first-class-components)
5. [Component Relationships](#component-relationships)
6. [Directory Structure](#directory-structure)
7. [Key Documentation](#key-documentation)
8. [Build and Test](#build-and-test)

---

## Explicit Non-Goals of Air

**THINK vs ACT:** Core performs THINK (authoritative timeline, what plays next, when transitions occur); Air performs ACT (executes explicit commands). Air does **not** make scheduling, timing, or sequencing decisions.

Air intentionally does NOT:

- Manage multiple channels internally
- Persist playout history
- Interpret schedules or EPG data
- Make business or editorial decisions
- Coordinate redundancy or failover
- **Detect producer endings or initiate transitions** (no duration tracking, no EOF-triggered switching, no "what comes next"—transitions occur only via explicit Core commands or dead-man failsafe; see [BlackFrameProducerContract](../architecture/BlackFrameProducerContract.md))

These concerns are owned by Core.  
Air enforces only runtime execution correctness.

**Core → Air boundary:** Core passes asset identity (GUID), resolved playout-ready descriptors (producer type, offsets, constraints), and explicit control commands (legacy preload RPC, legacy switch RPC, UpdatePlan). Core does **not** pass file paths or execution instructions; Air maps descriptors to concrete producer implementations and owns *how* media is materialized, not *what* or *when*.

---

## Architecture Overview

**Mental model:** Air is a **single-channel playout engine**. It runs one playout session at a time. Channel identity and multi-channel coordination live in Core (Python). Air owns only runtime execution state and enforces execution correctness (timing, buffer, encoder invariants).

What Air does:

- Receives playout control via gRPC (`channel_id` is an external identifier for correlation, not internal ownership)
- Decodes video/audio via FFmpeg (FileProducer) or synthetic frames (ProgrammaticProducer)
- Stages frames in a lock-free ring buffer
- Delivers program output (headless or preview) and routes through OutputBus to OutputSink
- OutputSink encodes, muxes, and streams MPEG-TS over UDS/TCP when attached

### High-Level Flow

```
Core ChannelManager (owns channel lifecycle, schedules)
         │
         ▼ gRPC (channel_id for correlation only)
PlayoutControlImpl → PlayoutInterface → PlayoutEngine
         │
         ▼ one active instance
┌─────────────────────────────────────────────────────────┐
│  PlayoutInstance (internal: one per active “channel”)    │
│  ┌───────────────────────────────────────────────────┐  │
│  │ INPUT PATH (ProducerBus):                          │  │
│  │   ProducerBus (preview) + ProducerBus (live)       │  │
│  │   → IProducer on live bus (e.g. FileProducer)      │  │
│  │         ▼                                          │  │
│  │ FrameRingBuffer (lock-free circular buffer)        │  │
│  │         ▼                                          │  │
│  │ ProgramOutput (headless; routes to OutputBus)       │  │
│  │         ▼                                          │  │
│  │ OUTPUT PATH: OutputBus → OutputSink (encode, mux)   │  │
│  │   OutputBus (signal path; routes to attached sink)  │  │
│  │         ▼                                          │  │
│  │ OutputSink (MpegTSOutputSink: encode, mux, stream) │  │
│  └───────────────────────────────────────────────────┘  │
│  PlayoutControl (preview + live buses; RuntimePhase)    │  │
│  TimingLoop (timing, backpressure)                       │  │
└─────────────────────────────────────────────────────────┘
```

**Input bus:** PlayoutControl owns two ProducerBuses (preview, live). legacy preload RPC loads the preview bus; legacy switch RPC promotes preview → live. The live bus’s producer feeds FrameRingBuffer. See [ProducerBusContract](../architecture/ProducerBusContract.md).

---

## gRPC Interfaces

**Source:** `protos/playout.proto` (canonical; repo root).  
**Generated C++:** `pkg/air/build/playout.pb.h`, `playout.grpc.pb.h` (CMake generates from same proto).

**Service:** `PlayoutControl` (API version 1.0.0).

| RPC | Request | Response | Purpose |
|-----|---------|----------|---------|
| StartChannel | StartChannelRequest | StartChannelResponse | Activate playout session (plan_handle, port, program_format_json). One session at a time; second distinct channel_id returns error. ProgramFormat (JSON) defines canonical per-channel signal format (video: width, height, frame_rate; audio: sample_rate, channels). Fixed for lifetime of PlayoutInstance. |
| StopChannel | StopChannelRequest | StopChannelResponse | Graceful shutdown of active session. |
| UpdatePlan | UpdatePlanRequest | UpdatePlanResponse | Swap active plan for session without stopping. |
| GetVersion | ApiVersionRequest | ApiVersion | API version string. |
| legacy preload RPC | legacy preload RPCRequest | legacy preload RPCResponse | Load asset into preview bus; shadow decode. |
| legacy switch RPC | legacy switch RPCRequest | legacy switch RPCResponse | Promote preview bus to live atomically; PTS continuity. |
| AttachStream | AttachStreamRequest | AttachStreamResponse | Attach OutputSink (e.g. MpegTSOutputSink) to OutputBus for byte output. |
| DetachStream | DetachStreamRequest | DetachStreamResponse | Detach OutputSink from OutputBus. |

**Convention:** All request messages carry `channel_id` (int32). This is an **external correlation ID** supplied by Core. Air does not own channel identity or lifecycle; it uses `channel_id` for routing and metrics only.

---

## First-Class Components

### Runtime (control and session)

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **PlayoutEngine** | `runtime/PlayoutEngine.h` | Root execution unit. Single playout session at a time. Owns runtime graph (producer → buffer → ProgramOutput → OutputBus → OutputSink), clock, and engine-level state. Provides AttachOutputSink/DetachOutputSink, ConnectRendererToOutputBus methods. Does *not* own channel lifecycle or schedules. |
| **PlayoutInterface** | `runtime/PlayoutInterface.h` | Thin adapter: gRPC layer → PlayoutEngine. Delegates all ops to engine. Provides AttachOutputSink/DetachOutputSink, GetOutputBus, ConnectRendererToOutputBus wrappers. |
| **PlayoutControl** | `runtime/PlayoutControl.h` | Enforces valid sequencing of runtime ops (PTS, buffer priming, decode/render order). Uses **RuntimePhase** (kIdle, kBuffering, kReady, kPlaying, kPaused, kStopping, kError). Governs OutputBus attach/detach transitions via CanAttachSink/CanDetachSink. Tracks sink attachment state. Does *not* represent channel lifecycle or scheduling. |
| **ProducerBus** | `runtime/ProducerBus.h` | Input path: two buses (preview, live). Each bus holds an IProducer (e.g. FileProducer). Live bus’s producer feeds FrameRingBuffer. Core directs legacy preload RPC (preview bus) and legacy switch RPC (promote preview → live). See [ProducerBusContract](../architecture/ProducerBusContract.md). BlackFrameProducer fallback when live runs out: [BlackFrameProducerContract](../architecture/BlackFrameProducerContract.md). |
| **TimingLoop** | `runtime/TimingLoop.h` | Tick loop, backpressure events, timing/coordination with MasterClock. |

**PlayoutInstance** (internal struct in `PlayoutEngine.cpp`): Holds one instance's runtime: `channel_id` (external), `plan_handle`, `program_format` (ProgramFormat struct parsed from JSON), ring_buffer, live_producer, preview_producer, program_output, timing_loop, PlayoutControl (control), OutputBus. One instance per active “channel” slot; Air enforces at most one active instance. ProgramFormat defines canonical program signal (video: width, height, frame_rate; audio: sample_rate, channels); fixed for lifetime of instance; independent of encoding/transport. See [PlayoutInstanceAndProgramFormatContract](PlayoutInstanceAndProgramFormatContract.md).

### Producers

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **IProducer** | `producers/IProducer.h` | Minimal interface: start(), stop(), isRunning(). |
| **FileProducer** | `producers/file/FileProducer.h` | Decodes local video/audio (FFmpeg), produces frames/audio into FrameRingBuffer. Segment params: start_offset_ms, hard_stop_time_ms. |
| **ProgrammaticProducer** | `producers/programmatic/ProgrammaticProducer.h` | **Scaffolding / test-only.** Synthetic frames; no FFmpeg. Same IProducer lifecycle; will be replaced by domain producers. |
| **BlackFrameProducer** | (design) | **Internal failsafe (dead-man fallback).** Produces valid black video (program format) and no audio. When the **live** producer runs out of frames (EOF, underrun) and Core has not yet issued the next control command, Air **immediately** switches output to BlackFrameProducer so the sink **always** receives valid output. Not content, not scheduled; exists solely to guarantee always-valid output until Core reasserts control. See [BlackFrameProducerContract](../architecture/BlackFrameProducerContract.md). |

### Buffer and program output

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **FrameRingBuffer** | `buffer/FrameRingBuffer.h` | Lock-free circular buffer for Frame/AudioFrame. Producer pushes; ProgramOutput consumes. |
| **ProgramOutput** | `renderer/ProgramOutput.h` | Consumes buffer; headless or preview. Routes frames to OutputBus when connected, else uses legacy callbacks. |

### Output (bus and sink)

| Component | Header | Responsibility |
|-----------|--------|----------------|
| **OutputBus** | `output/OutputBus.h` | Signal path for program output. Routes frames to currently attached OutputSink. Governed by PlayoutControl. Does not own transport, threads, or encoding. Validates attach/detach via PlayoutControl. |
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
| **PlayoutControlImpl** | `playout_service.h` | Implements PlayoutControl service. Delegates to PlayoutInterface. Manages AttachStream/DetachStream (creates/destroys OutputSink, attaches/detaches from OutputBus). |

---

## Component Relationships

- **PlayoutControlImpl** → **PlayoutInterface** → **PlayoutEngine**.  
  PlayoutEngine owns **PlayoutInstance** (or instances map, one active); each instance owns:
  - **ProgramFormat** (canonical signal format: video width/height/frame_rate, audio sample_rate/channels; fixed for instance lifetime)
  - **FrameRingBuffer**
  - **PlayoutControl** (control), **ProducerBus**es (preview, live)
  - **FileProducer** (live, optional preview), **ProgramOutput**
  - **OutputBus** (signal path; routes frames to attached OutputSink)
  - **TimingLoop** (if used)
- **PlayoutControl** owns preview/live **ProducerBus**es; loads/switches producers via factory and **activatePreviewAsLive**. Governs OutputBus attach/detach transitions.
- **FileProducer** / **ProgrammaticProducer** implement **IProducer**; push into **FrameRingBuffer**.
- **ProgramOutput** reads **FrameRingBuffer**; routes frames to **OutputBus** when connected (via `SetOutputBus()`), else uses legacy side_sink_ callbacks. Supports both modes during transition.
- **OutputBus** routes frames to currently attached **OutputSink** (e.g. MpegTSOutputSink). Frames are in **ProgramFormat** (established at StartChannel). Attachment/detachment validated by PlayoutControl. OutputBus does not own transport, threads, or encoding.
- **MpegTSOutputSink** implements **IOutputSink**; consumes frames from OutputBus via ConsumeVideo/ConsumeAudio (frames in ProgramFormat); adapts ProgramFormat to encoding (must fail fast if format unsupported); enqueues to internal queues; MuxLoop thread drains queues and encodes via EncoderPipeline; writes TS packets to file descriptor (UDS/TCP). Created by PlayoutControlImpl on legacy switch RPC when stream attached.
- **MasterClock** and **MetricsExporter** are shared into PlayoutEngine and passed into session components.
- **One-session rule:** `PlayoutEngine::StartChannel` returns error if a session already exists for a *different* channel_id; idempotent for same channel_id.
- **OutputBus invariant:** At most one OutputSink attached per OutputBus (enforced by PlayoutControl). OutputBus does not perform attach/detach autonomously; all operations validated by PlayoutControl.
- **PlayoutControlImpl** creates MpegTSOutputSink on legacy switch RPC (if AttachStream was called); attaches to OutputBus via PlayoutInterface; connects program output to OutputBus to start frame flow.

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
│   ├── renderer/        ProgramOutput.h
│   ├── runtime/         PlayoutEngine, PlayoutInterface, PlayoutControl, ProducerBus, TimingLoop, ProgramFormat, AspectPolicy
│   ├── sinks/           Legacy IPlayoutSink.h, mpegts/* (legacy MpegTSPlayoutSink - being phased out)
│   ├── telemetry/       MetricsExporter, MetricsHTTPServer
│   └── timing/          MasterClock.h
├── src/
│   ├── buffer/          FrameRingBuffer.cpp
│   ├── decode/          FFmpegDecoder, FrameProducer
│   ├── output/          OutputBus.cpp, MpegTSOutputSink.cpp
│   ├── playout_sinks/   mpegts/* (EncoderPipeline, TSMuxer, MpegTSEncoder, TsOutputSink - used by MpegTSOutputSink)
│   ├── producers/       file/FileProducer, programmatic/ProgrammaticProducer
│   ├── renderer/        ProgramOutput.cpp
│   ├── runtime/         PlayoutEngine, PlayoutInterface, PlayoutControl, ProducerBus, TimingLoop, ProgramFormat
│   ├── playout_service.cpp, playout_service.h   PlayoutControlImpl
│   ├── main.cpp
│   ├── telemetry/       MetricsExporter, MetricsHTTPServer
│   └── timing/          SystemMasterClock, TestMasterClock
├── docs/                Documentation (this doc under docs/architecture/)
├── tests/               Contract tests, fixtures (ChannelManagerStub, etc.)
├── core_test_harness/   Python harness (file_decoder, frame_ring_buffer, etc.)
└── CMakeLists.txt       Proto generation, retrovue_air_core, retrovue_air, contracts_playoutengine_tests
```

**Proto:** Single source `protos/playout.proto` at repo root. Generate with `scripts/air/generate_proto.sh` (Python stubs for Core); C++ generated by Air’s CMake.

---

## Key Documentation

| Area | Location |
|------|----------|
| Docs index | [docs/README.md](../../README.md) |
| **This reference** | [AirArchitectureReference](AirArchitectureReference.md) |
| Architecture overview | [ArchitectureOverview](../../overview/ArchitectureOverview.md) |
| Domain models | [docs/archive/domain/](../../archive/domain/) |
| **Architecture contracts** | [docs/contracts/architecture/](../architecture/) — PlayoutEngine, OutputBus, ProgramFormat, Renderer, FileProducer, etc. |
| **Development phase contracts** | [contracts/phases/](../phases/) — Phase 6A, Phase 8 (milestone-specific) |
| PlayoutInstance / ProgramFormat | [PlayoutInstanceAndProgramFormatContract](PlayoutInstanceAndProgramFormatContract.md) |
| OutputBus / OutputSink | [OutputBusAndOutputSinkContract](../architecture/OutputBusAndOutputSinkContract.md) |
| Build | [docs/build.md](../build.md); CLAUDE.md in repo root |

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
