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

## ChannelManager lifecycle (post-collapse)

**ProgramDirector is the sole authority for ChannelManager lifecycle.** There is no separate “daemon” runtime concept; PD owns the active registry of ChannelManagers.

- **Creation** — PD creates a ChannelManager on demand (e.g. first tune to a channel) and adds it to the registry.
- **Health ticking** — PD runs the health-check loop and calls `check_health()` / `tick()` on each registered manager.
- **Fanout attachment** — PD creates and attaches ChannelStream (fanout) to a manager’s producer.
- **Teardown** — PD removes a manager from the registry and tears it down (e.g. on last viewer disconnect); ChannelManagers do not self-terminate.

**Invariant:** ChannelManagers have no autonomous lifecycle; they exist only while referenced by ProgramDirector’s active registry. ChannelManagers must never self-terminate or assume daemon semantics.

See: ProgramDirector is the sole lifecycle owner (ChannelManagerDaemon was collapsed into PD).

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
> - "MediaManager" ≈ **Sources/Containers/Assets** (+ ingest + metadata enrichment)

### Core (Python) — orchestration, scheduling, state, operator surfaces

| Component | Owns | Primary interfaces | Where to start (docs) | Where to start (code) |
| --- | --- | --- | --- | --- |
| **MasterClock** | One authoritative time source used across scheduling + playout | In-process protocol (time reads); used by ScheduleService/ChannelManager/ProgramDirector | `server/docs/data/domain/MasterClock.md` | `server/src/retrovue/runtime/clock.py` |
| **ScheduleService** ("ScheduleManager") | Interprets schedules; answers "what should be airing now?"; broadcast-day alignment | In-process protocol; read-only to runtime; produces playout horizon/segments | `server/docs/runtime/schedule_service.md` • `server/docs/data/domain/Scheduling.md` | `server/src/retrovue/runtime/schedule_service.py` (and related runtime modules) |
| **ChannelManager (CM)** | Per-channel runtime orchestration; decides when to start/stop/swap Producers; calls the internal playout engine via gRPC; viewer_count, join-in-progress offsets, plan authority. Never internet-facing. Never forwards MPEG-TS bytes. No autonomous lifecycle—exists only while in ProgramDirector’s active registry. | gRPC client to internal playout engine (`StartChannel`, `UpdatePlan`, etc.); in-process status surface (not internet-facing) | `server/docs/runtime/channel_manager.md` • `server/docs/runtime/ProducerLifecycle.md` | `server/src/retrovue/runtime/channel_manager.py` |
| **ProgramDirector (PM)** | The control plane inside RetroVue. **Sole owner of ChannelManager lifecycle** (creation, health ticking, fanout attachment, teardown). Owns all web servers, viewer routing, fanout buffers, global overrides (emergency/guide/maintenance), and operator dashboards. Does not perform scheduling or playout. | HTTP (viewer + operator UI), in-process commands to CMs | `server/docs/runtime/program_director.md` | `server/src/retrovue/runtime/program_director.py` |
| **AsRunLogger** | Records "what actually aired" (compliance/reporting feed) | In-process logger; depends on ScheduleService for broadcast-day labeling | `server/docs/runtime/asrun_logger.md` | `server/src/retrovue/runtime/asrun_logger.py` |
| **FanoutBuffer (runtime)** | One-to-many distribution of live channel bytes. Receives a single MPEG-TS stream from the internal playout engine and multiplexes it to N viewers. Ensures only one playout engine pipeline runs per channel regardless of viewer count. | In-process async stream API | *(see code)* | `server/src/retrovue/runtime/fanout.py` |
| **Domain model: Channel/Source/Container/Asset/Enricher** ("Media Manager") | Operator-configured entities + invariants | CLI + usecases; DB-backed | `server/docs/data/domain/` (start: `Channel.md`, `Source.md`, `Asset.md`) | `server/src/retrovue/domain/` + `server/src/retrovue/usecases/` |
| **CLI (test harness)** | Contract-first operator/dev harness; JSON is the canonical contract surface | Typer commands; calls usecases | `server/docs/contracts/cli/` | `server/src/retrovue/cli/` |
| **Web/API surfaces (experimental / legacy)** | HTTP entrypoints used for dev demos and runtime surfaces | FastAPI apps (varies) | `server/docs/architecture/ArchitectureOverview.md` (context) | `server/src/retrovue/runtime/program_director.py` (embedded FastAPI server). **Note:** ChannelManagerDaemon’s HTTP has been collapsed into ProgramDirector; there is no separate daemon. IPTV playlist generation lives in `server/src/retrovue/web/iptv.py`. |

### Internal playout engine (C++) — real-time playout engine

| Component | Owns | Primary interfaces | Where to start (docs) | Where to start (code) |
| --- | --- | --- | --- | --- |
| **PlayoutEngine (control plane + engine)** | Channel lifecycle: start/stop/update plan; coordinates internal pipeline. Does not persist, segment, or store output; emits live bytes only. | gRPC service surface; Prometheus metrics | `runtime/docs/contracts/semantics/PlayoutEngineContract.md` | `runtime/src/runtime/PlayoutEngine.cpp` • `runtime/src/runtime/PlayoutInterface.cpp` |
| **Producers (decode/input)** | Turning assets into frames (FFmpeg/libav boundary) | Internal C++ interfaces | `runtime/docs/contracts/architecture/FileProducerContract.md` | `runtime/src/producers/` |
| **Buffering** | Frame bus / ring buffer / staging between decode and render | Internal C++ interfaces | (see architecture/runtime docs) | `runtime/src/buffer/` |
| **Renderer** | Converts staged frames into renderable output; optional preview | Internal C++ interface; telemetry | `runtime/docs/contracts/semantics/RendererContract.md` | `runtime/src/renderer/ProgramOutput.cpp` |
| **MPEG-TS sinks** | Emit continuous MPEG-TS stream; handle pacing/backpressure | TCP/UDS output + telemetry | `docs/legacy/air/domain/MpegTSPlayoutSinkDomain.md` • contracts under `docs/legacy/air/air/contracts/` | `runtime/src/sinks/mpegts/` and `runtime/src/playout_sinks/mpegts/` |
| **Proto / versioning boundary** | The Core ↔ internal playout engine contract surface | Protobuf + gRPC metadata/versioning | `runtime/docs/operations/Integration.md` | `protos/playout.proto` |

## Control plane vs Data plane

**Control plane**
- ProgramDirector → ChannelManager → internal playout engine
- Commands, plans, policies, overrides

**Data plane**
- internal playout engine → ProgramDirector → Viewers
- Continuous MPEG-TS bytes
- No files, no history, no rewind

## See also

- [Core docs index](../server/docs/README.md)
- [Internal playout engine docs index](../runtime/docs/)
- [Documentation standards](standards/documentation-standards.md)
