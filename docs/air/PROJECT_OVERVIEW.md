# RetroVue Playout Engine – Developer Overview

_Related: [Architecture overview](architecture/ArchitectureOverview.md) • [Runtime model](runtime/PlayoutRuntime.md) • [Proto schema](../proto/retrovue/playout.proto)_

---

## Purpose

The **RetroVue Playout Engine** implements a native C++ backend that executes segment-based playout instructions from the ChannelManager. It does not understand schedules or plans; ChannelManager computes PlayoutSegments and sends exact execution instructions via gRPC. Air hosts heterogeneous producers (file-backed and programmatic such as Prevue, weather, community, test patterns) that share a common output contract (decoded frames).

- **Control interface:** gRPC (`proto/retrovue/playout.proto`). Segment-based control is canonical: `LoadPreview` (asset_path, start_offset_ms, hard_stop_time_ms), `SwitchToLive` (control-only, no payload). Optional: `StartChannel` / `UpdatePlan` with plan handles.
- **Output:** Either Air outputs MPEG-TS directly, or Air outputs frames to a Renderer that muxes MPEG-TS — an intentional design boundary; deployments fix one path.
- **Timing:** MasterClock lives in the Python runtime. Air enforces deadlines (e.g. `hard_stop_time_ms`) but does not compute schedule time.

---

## Component Overview

| Component             | Language        | Responsibility                                |
| --------------------- | --------------- | --------------------------------------------- |
| **RetroVue Core**     | Python          | Scheduling, PlayoutSegment computation, channel management |
| **RetroVue Renderer** | Python or C++   | MPEG-TS encoding & transport (or Air outputs TS directly)  |
| **Playout Engine**    | C++             | Producers (file-backed + programmatic), buffer, output     |

Each component communicates over a documented API surface. The C++ playout engine **does not** implement scheduling or plan logic — ChannelManager computes segments and sends execution instructions; Air executes them.

---

## Contracts & Interfaces

| Type    | Path/Location                  | Description                                      |
| ------- | ------------------------------ | ------------------------------------------------ |
| gRPC    | `proto/retrovue/playout.proto` | Control API: ChannelManager ↔ Playout (required) |
| Metrics | Prometheus `/metrics` endpoint | Channel state, frame gap telemetry               |
| Build   | `CMakeLists.txt`               | Defines `retrovue_playout` and dependencies      |

**Workflow:**  
_New features start by updating the contract_ (proto, metrics, etc.) in `docs/contracts/` and `proto/`, **before** implementing new functionality.

---

## Building & Running

**Build (Release)**

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
```

**Run**

```bash
./build/retrovue_playout --channel 1 --port 8090
```

---

## Communication Model

- **Control API (gRPC):** Receives segment-based instructions from the ChannelManager: `LoadPreview` (asset_path, start_offset_ms, hard_stop_time_ms), `SwitchToLive` (control-only), plus optional `StartChannel` / `UpdatePlan` / `StopChannel`.
- **Frame Bus:** Producers feed decoded frames into a per-channel ring buffer; Renderer (or direct TS path) consumes them.
- **Telemetry:** Publishes health and state metrics at the Prometheus `/metrics` endpoint.

---

## Development Status

### Phase 1: gRPC Skeleton ✅ Complete

- ✅ gRPC service definition and implementation
- ✅ `StartChannel`, `UpdatePlan`, `StopChannel` RPCs
- ✅ CMake build system with vcpkg integration
- ✅ Python test client

### Phase 2: Frame Buffer & Stub Decode ✅ Complete

- ✅ Lock-free circular frame buffer (FrameRingBuffer)
- ✅ Frame producer with stub decode (synthetic frames)
- ✅ Dedicated decode thread per channel
- ✅ Prometheus metrics schema
- ✅ Unit tests and integration tests

### Phase 3: Real Decode + Renderer + Metrics ✅ Complete

- ✅ File-backed producers with real decode (e.g. libav/ffmpeg or equivalent — implementation detail per producer)
- ✅ Multi-codec support (H.264, HEVC, VP9, AV1)
- ✅ FrameRenderer (headless + preview modes)
- ✅ MetricsHTTPServer with native HTTP/1.1 implementation
- ✅ Complete producer → buffer → render → metrics pipeline
- ✅ Production-grade performance (<10ms decode latency @ 1080p30)

### Phase 4: Production Hardening 📋 Planned

- [ ] MasterClock integration for frame-accurate timing
- [ ] Multi-channel stress testing (10+ simultaneous channels)
- [ ] Error recovery and slate frame fallback
- [ ] Hardware decode acceleration (NVDEC, QSV, VideoToolbox)
- [ ] Operational tooling (Grafana dashboards, Prometheus alerts)

**See:** [Roadmap](milestones/Roadmap.md) for detailed plans

---

## Notes & House Rules

- This repository is **not** the owner of scheduling or plan logic. ChannelManager (Python) computes PlayoutSegments and sends exact execution instructions; Air executes them and enforces deadlines (e.g. `hard_stop_time_ms`) but does not compute schedule time. MasterClock lives in the Python runtime.
- Always treat Python → C++ interactions as client → server.
- Keep all timing and output strictly deterministic; Air aligns to MasterClock for output pacing.
- All API and integration changes **must** follow the `docs/contracts/` workflow (contract first, then implementation).

---

_For further details, see:_

- [docs/README.md](README.md)
- [runtime/PlayoutRuntime.md](runtime/PlayoutRuntime.md)
- [developer/BuildAndDebug.md](developer/BuildAndDebug.md)
