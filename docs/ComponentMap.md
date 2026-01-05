_Metadata: Status=Canonical • Scope=System overview_

# RetroVue component map

## Purpose

Provide a single, cross-repo list of RetroVue’s major components (Core + Air), what they do, and where their
interfaces/docs live.

## How to use this document

- If you’re trying to understand **“what are the moving parts?”**, start here.
- If you’re trying to change behavior safely, jump from a component to its **contracts** and **runtime docs**.

## Mental model (one channel, one viewer)

```mermaid
flowchart LR
  Viewer[Viewer joins stream] --> CoreCM[Core: ChannelManager]
  CoreCM -->|asks "what should air now?"| CoreSched[Core: ScheduleService]
  CoreCM -->|uses authoritative time| CoreClock[Core: MasterClock]
  CoreCM -->|gRPC StartChannel/UpdatePlan| AirCtl[Air: PlayoutEngine control plane]
  AirCtl --> AirPipe[Air: Decode → buffer → renderer → MPEG-TS sink]
  CoreCM -->|record "what actually aired"| CoreAsRun[Core: AsRunLogger]
  CorePD[Core: ProgramDirector] -->|global mode/policy| CoreCM
```

## Component inventory

> **Note:** Some names you may remember (“ScheduleManager”, “MediaManager”) map to today’s names/layers:
> - “ScheduleManager” ≈ **ScheduleService** (+ scheduling domain models)
> - “MediaManager” ≈ **Sources/Collections/Assets** (+ ingest + metadata enrichment)

### Core (Python) — orchestration, scheduling, state, operator surfaces

| Component | Owns | Primary interfaces | Where to start (docs) | Where to start (code) |
| --- | --- | --- | --- | --- |
| **MasterClock** | One authoritative time source used across scheduling + playout | In-process protocol (time reads); used by ScheduleService/ChannelManager/ProgramDirector | `docs/core/domain/MasterClock.md` | `pkg/core/src/retrovue/runtime/clock.py` |
| **ScheduleService** (“ScheduleManager”) | Interprets schedules; answers “what should be airing now?”; broadcast-day alignment | In-process protocol; read-only to runtime; produces playout horizon/segments | `docs/core/runtime/schedule_service.md` • `docs/core/domain/Scheduling.md` | `pkg/core/src/retrovue/runtime/schedule_service.py` (and related runtime modules) |
| **ChannelManager** | Per-channel runtime orchestration; decides when to start/stop/swap Producers; calls Air via gRPC | gRPC client to Air (`StartChannel`, `UpdatePlan`, etc.); optional HTTP surface for status/ops | `docs/core/runtime/channel_manager.md` • `docs/core/runtime/ProducerLifecycle.md` | `pkg/core/src/retrovue/runtime/channel_manager_daemon.py` |
| **ProgramDirector** (“Program Manager”) | System-wide coordination and policy (normal/emergency/guide modes); not a scheduler | In-process policy surface consumed by ChannelManager; future UI/dashboard consumer | `docs/core/runtime/program_director.md` | `pkg/core/src/retrovue/runtime/program_director.py` |
| **AsRunLogger** | Records “what actually aired” (compliance/reporting feed) | In-process logger; depends on ScheduleService for broadcast-day labeling | `docs/core/runtime/asrun_logger.md` | `pkg/core/src/retrovue/runtime/asrun_logger.py` |
| **Domain model: Channel/Source/Collection/Asset/Enricher** (“Media Manager”) | Operator-configured entities + invariants | CLI + usecases; DB-backed | `docs/core/domain/` (start: `Channel.md`, `Source.md`, `Asset.md`) | `pkg/core/src/retrovue/domain/` + `pkg/core/src/retrovue/usecases/` |
| **CLI (test harness)** | Contract-first operator/dev harness; JSON is the canonical contract surface | Typer commands; calls usecases | `docs/core/contracts/resources/README.md` | `pkg/core/src/retrovue/cli/` |
| **Web/API surfaces (experimental / legacy)** | HTTP entrypoints used for dev demos and daemon surfaces | FastAPI apps (varies) | `docs/core/architecture/ArchitectureOverview.md` (context) | `pkg/core/src/retrovue/web/server.py` and `pkg/core/src/retrovue/runtime/channel_manager_daemon.py` (`FastAPI(...)`) |

### Air (C++) — real-time playout engine

| Component | Owns | Primary interfaces | Where to start (docs) | Where to start (code) |
| --- | --- | --- | --- | --- |
| **PlayoutEngine (control plane + engine)** | Channel lifecycle: start/stop/update plan; coordinates internal pipeline | gRPC service surface; Prometheus metrics | `docs/air/contracts/PlayoutEngineContract.md` • `docs/air/domain/PlayoutEngineDomain.md` | `pkg/air/src/runtime/PlayoutEngine.cpp` • `pkg/air/src/runtime/PlayoutController.cpp` |
| **Producers (decode/input)** | Turning assets into frames (FFmpeg/libav boundary) | Internal C++ interfaces | `docs/air/domain/VideoFileProducerDomain.md` | `pkg/air/src/producers/` |
| **Buffering** | Frame bus / ring buffer / staging between decode and render | Internal C++ interfaces | (see architecture/runtime docs) | `pkg/air/src/buffer/` |
| **Renderer** | Converts staged frames into renderable output; optional preview | Internal C++ interface; telemetry | `docs/air/domain/RendererDomain.md` • `docs/air/contracts/RendererContract.md` | `pkg/air/src/renderer/FrameRenderer.cpp` |
| **MPEG-TS sinks** | Emit continuous MPEG-TS stream; handle pacing/backpressure | TCP/UDS output + telemetry | `docs/air/domain/MpegTSPlayoutSinkDomain.md` • contracts under `docs/air/air/contracts/` | `pkg/air/src/sinks/mpegts/` and `pkg/air/src/playout_sinks/mpegts/` |
| **Proto / versioning boundary** | The Core ↔ Air contract surface | Protobuf + gRPC metadata/versioning | `docs/air/infra/Integration.md` | `protos/playout.proto` |

## See also

- [Core docs index](core/README.md)
- [Air docs index](air/README.md)
- [Documentation standards](standards/documentation-standards.md)

