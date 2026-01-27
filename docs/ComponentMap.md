_Metadata: Status=Canonical • Scope=System overview_

# RetroVue component map

## Purpose

Provide a single, cross-repo list of RetroVue's major components, what they do, and where their
interfaces/docs live.

## How to use this document

- If you're trying to understand **"what are the moving parts?"**, start here.
- If you're trying to change behavior safely, jump from a component to its **contracts** and **runtime docs**.

## Phase 0 invariant

Channels exist in time even when not streaming.
Internal playout engine pipelines only run when at least one viewer is present.

## Mental model (one channel, one viewer)

```mermaid
flowchart LR
  Viewer -->|HTTP| PM[Core: ProgramDirector (Web + Control Plane)]
  PM -->|tune_in/tune_out| CM[Core: ChannelManager]
  CM -->|asks "what should air now?"| Sched[Core: ScheduleService]
  CM -->|uses authoritative time| Clock[Core: MasterClock]
  CM -->|gRPC Start/Update/Stop| AirCtl[Internal: PlayoutEngine (control plane)]
  AirCtl --> AirPipe[Internal: Decode → buffer → renderer → MPEG-TS sink]
  AirPipe -->|MPEG-TS bytes| PM
  CM -->|as-run events| AsRun[Core: AsRunLogger]
  PM -->|global policy/overrides| CM
```

**PM never generates A/V. CM never forwards A/V bytes. The internal playout engine never knows about viewers.**

## Component inventory

> **Note:** Some names you may remember ("ScheduleManager", "MediaManager") map to today's names/layers:
> - "ScheduleManager" ≈ **ScheduleService** (+ scheduling domain models)
> - "MediaManager" ≈ **Sources/Collections/Assets** (+ ingest + metadata enrichment)

### Core (Python) — orchestration, scheduling, state, operator surfaces

| Component | Owns | Primary interfaces | Where to start (docs) | Where to start (code) |
| --- | --- | --- | --- | --- |
| **MasterClock** | One authoritative time source used across scheduling + playout | In-process protocol (time reads); used by ScheduleService/ChannelManager/ProgramDirector | `docs/core/domain/MasterClock.md` | `pkg/core/src/retrovue/runtime/clock.py` |
| **ScheduleService** ("ScheduleManager") | Interprets schedules; answers "what should be airing now?"; broadcast-day alignment | In-process protocol; read-only to runtime; produces playout horizon/segments | `docs/core/runtime/schedule_service.md` • `docs/core/domain/Scheduling.md` | `pkg/core/src/retrovue/runtime/schedule_service.py` (and related runtime modules) |
| **ChannelManager (CM)** | Per-channel runtime orchestration; decides when to start/stop/swap Producers; calls the internal playout engine via gRPC; viewer_count, join-in-progress offsets, plan authority. Never internet-facing. Never forwards MPEG-TS bytes. Only orchestrates plans and lifecycle. | gRPC client to internal playout engine (`StartChannel`, `UpdatePlan`, etc.); in-process status surface (not internet-facing) | `docs/core/runtime/channel_manager.md` • `docs/core/runtime/ProducerLifecycle.md` | `pkg/core/src/retrovue/runtime/channel_manager_daemon.py` |
| **ProgramDirector (PM)** | The control plane inside RetroVue. Control plane + routing + operator surfaces. Owns all web servers, viewer routing, fanout buffers, global overrides (emergency/guide/maintenance), and operator dashboards. Does not perform scheduling or playout. | HTTP (viewer + operator UI), in-process commands to CMs | `docs/core/runtime/program_director.md` | `pkg/core/src/retrovue/runtime/program_director.py` |
| **AsRunLogger** | Records "what actually aired" (compliance/reporting feed) | In-process logger; depends on ScheduleService for broadcast-day labeling | `docs/core/runtime/asrun_logger.md` | `pkg/core/src/retrovue/runtime/asrun_logger.py` |
| **FanoutBuffer (runtime)** | One-to-many distribution of live channel bytes. Receives a single MPEG-TS stream from the internal playout engine and multiplexes it to N viewers. Ensures only one playout engine pipeline runs per channel regardless of viewer count. | In-process async stream API | `docs/core/runtime/fanout_buffer.md` | `pkg/core/src/retrovue/runtime/fanout.py` |
| **Domain model: Channel/Source/Collection/Asset/Enricher** ("Media Manager") | Operator-configured entities + invariants | CLI + usecases; DB-backed | `docs/core/domain/` (start: `Channel.md`, `Source.md`, `Asset.md`) | `pkg/core/src/retrovue/domain/` + `pkg/core/src/retrovue/usecases/` |
| **CLI (test harness)** | Contract-first operator/dev harness; JSON is the canonical contract surface | Typer commands; calls usecases | `docs/core/contracts/resources/README.md` | `pkg/core/src/retrovue/cli/` |
| **Web/API surfaces (experimental / legacy)** | HTTP entrypoints used for dev demos and runtime surfaces | FastAPI apps (varies) | `docs/core/architecture/ArchitectureOverview.md` (context) | `pkg/core/src/retrovue/web/server.py` and `pkg/core/src/retrovue/runtime/channel_manager_daemon.py` (`FastAPI(...)`) |

### Internal playout engine (C++) — real-time playout engine

| Component | Owns | Primary interfaces | Where to start (docs) | Where to start (code) |
| --- | --- | --- | --- | --- |
| **PlayoutEngine (control plane + engine)** | Channel lifecycle: start/stop/update plan; coordinates internal pipeline. Does not persist, segment, or store output; emits live bytes only. | gRPC service surface; Prometheus metrics | `docs/air/contracts/PlayoutEngineContract.md` • `docs/air/domain/PlayoutEngineDomain.md` | `pkg/air/src/runtime/PlayoutEngine.cpp` • `pkg/air/src/runtime/PlayoutController.cpp` |
| **Producers (decode/input)** | Turning assets into frames (FFmpeg/libav boundary) | Internal C++ interfaces | `docs/air/domain/VideoFileProducerDomain.md` | `pkg/air/src/producers/` |
| **Buffering** | Frame bus / ring buffer / staging between decode and render | Internal C++ interfaces | (see architecture/runtime docs) | `pkg/air/src/buffer/` |
| **Renderer** | Converts staged frames into renderable output; optional preview | Internal C++ interface; telemetry | `docs/air/domain/RendererDomain.md` • `docs/air/contracts/RendererContract.md` | `pkg/air/src/renderer/FrameRenderer.cpp` |
| **MPEG-TS sinks** | Emit continuous MPEG-TS stream; handle pacing/backpressure | TCP/UDS output + telemetry | `docs/air/domain/MpegTSPlayoutSinkDomain.md` • contracts under `docs/air/air/contracts/` | `pkg/air/src/sinks/mpegts/` and `pkg/air/src/playout_sinks/mpegts/` |
| **Proto / versioning boundary** | The Core ↔ internal playout engine contract surface | Protobuf + gRPC metadata/versioning | `docs/air/infra/Integration.md` | `protos/playout.proto` |

## Control plane vs Data plane

**Control plane**
- ProgramDirector → ChannelManager → internal playout engine
- Commands, plans, policies, overrides

**Data plane**
- internal playout engine → ProgramDirector → Viewers
- Continuous MPEG-TS bytes
- No files, no history, no rewind

## See also

- [Core docs index](core/README.md)
- [Internal playout engine docs index](air/README.md)
- [Documentation standards](standards/documentation-standards.md)
