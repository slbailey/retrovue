_Related: [Runtime model](../runtime/PlayoutRuntime.md) • [RetroVue architecture overview](../../../retrovue_core/docs/architecture/ArchitectureOverview.md)_

# Architecture overview

## Purpose

Describe how the native C++ playout engine fits into the RetroVue architecture and how it collaborates with the Python runtime, Renderer, and surrounding infrastructure.

## System context

- The ChannelManager computes PlayoutSegments (what to play and when) and sends exact execution instructions to the playout engine via gRPC. Air does not understand schedules or plans; it receives segment-based directives only.
- The playout engine hosts heterogeneous execution producers: file-backed producers (which may use ffmpeg subprocesses or libav) and programmatic producers (Prevue, weather, community, test patterns). Producers share a common output contract (decoded frames) but may differ internally.
- Output may be produced in one of two ways: either Air outputs MPEG-TS directly, or Air outputs frames to a Renderer that muxes MPEG-TS. This boundary is an intentional design choice documented here; specific deployments fix one path.
- Prometheus scrapes health metrics exposed by the playout engine to confirm channel readiness and timing accuracy.

## Core subsystems

- **Control plane:** gRPC service defined in `proto/retrovue/playout.proto` that receives channel lifecycle and segment instructions (e.g. `LoadPreview`, `SwitchToLive`). Segment-based control is canonical: `LoadPreview` carries asset path, `start_offset_ms`, and `hard_stop_time_ms`; `SwitchToLive` is control-only with no payload.
- **Producers:** Execution units that produce decoded frames. File-backed producers may use demux/decode threads (e.g. libav/ffmpeg); programmatic producers generate frames without file decode. All feed a common frame contract into staging.
- **Frame staging:** Lock-free ring buffers that guarantee minimum and maximum buffer depths for each channel.
- **Telemetry:** Metrics and structured logs emitted for monitoring, debugging, and operator visibility.

## Data and timing flow

1. ChannelManager computes PlayoutSegments and sends execution instructions via `LoadPreview` (asset_path, start_offset_ms, hard_stop_time_ms) and, at switch time, `SwitchToLive`. Optional: `StartChannel` / `UpdatePlan` with plan handles may also be used depending on deployment.
2. The playout engine executes segment instructions: file-backed producers seek by offset and stop at or before `hard_stop_time_ms`; Air enforces deadlines but does not compute schedule time. Clock authority lives in the Python runtime (MasterClock).
3. Frames are staged with timing metadata and asset provenance before the Renderer (or direct TS path) consumes them.
4. The Renderer—or the engine’s direct TS path—delivers output aligned with the MasterClock maintained by the Python runtime.

## Deployment topology

- Local development runs the playout engine and Python runtime in the same host using in-process gRPC channels.
- Production deployments run the playout engine as a dedicated service communicating via Unix domain sockets.
- Multiple channel workers can run inside a single engine process; horizontal scaling is achieved by starting more engine instances.

## Failure domains

- **Producer/decode failures:** Surface channel `error` state, trigger retries, and fall back to slate content. Decoding is an implementation detail of file-backed producers (e.g. ffmpeg/libav); programmatic producers have their own failure modes.
- **Control plane disconnects:** ChannelManager retries gRPC connection with exponential backoff.
- **Renderer starvation:** Detected via buffer depth metrics and mitigated by slate injection until recovery.

## Evolution notes

- API versioning is governed by the `PLAYOUT_API_VERSION` constant. Any breaking change must bump the constant and coordinate releases between `retrovue-core` and `retrovue-air`.
- Future extensions (e.g., adaptive bitrate ladders or remote hardware decoders) must maintain the same control plane contract or introduce versioned endpoints.

## See also

- [Runtime model](../runtime/PlayoutRuntime.md)
- [Deployment integration](../infra/Integration.md)
- [RetroVue core architecture](../../../retrovue_core/docs/architecture/ArchitectureOverview.md)

