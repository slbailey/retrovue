_Related: [Architecture overview](../architecture/ArchitectureOverview.md) • [RetroVue runtime - ChannelManager](../../../retrovue_core/docs/runtime/ChannelManager.md)_

# Playout runtime

## Purpose

Explain the execution model, threading, timing rules, and operational safeguards enforced by the playout engine at runtime.

## Channel lifecycle

- **Segment-based (canonical):** ChannelManager computes PlayoutSegments and sends execution instructions via `LoadPreview` (asset_path, start_offset_ms, hard_stop_time_ms) and `SwitchToLive` (control-only). Air does not understand schedules or plans.
- **Start:** ChannelManager may call `StartChannel` with initial plan and TCP port allocation where used.
- **Update:** `UpdatePlan` may hot-swap the active plan without interrupting output where plan-based control is used.
- **Stop:** Planned maintenance or fatal errors invoke `StopChannel`, draining buffers before releasing resources.

## Threading model

- **Producers:** Heterogeneous — file-backed producers may use demux/decode threads (e.g. libav/ffmpeg); programmatic producers (Prevue, weather, community, test patterns) have their own threading. All produce decoded frames meeting the common output contract.
- **Staging:** Frames are packaged with PTS/DTS, asset IDs, and duration before enqueuing to the Renderer ring buffer (or direct TS path).
- **Telemetry loop:** Emits metrics and structured logs without blocking the producer/output path.

## Timing guarantees

- MasterClock lives in the Python runtime. Air enforces deadlines (e.g. `hard_stop_time_ms`) but does not compute schedule time. Timing decisions that need wall-clock reference use the MasterClock delivered over the control/runtime boundary.
- Minimum frame lead time: 150 ms. Soft maximum: 500 ms. Exceeding the ceiling triggers buffer trimming.
- Slate insertion occurs when available frames drop below 30, preventing Renderer starvation.
- Renderer consumption is intentionally decoupled from decode timing, keeping output aligned with the MasterClock.

## Timing telemetry flow

- MasterClock publishes monotonic UTC deadlines and correction signals that gate Renderer pacing.
- Renderer compares in-flight frames against MasterClock deadlines before packaging transport stream output.
- Metrics exporter samples both MasterClock state and Renderer gap measurements to expose Prometheus gauges.

```mermaid
flowchart LR
    MC[MasterClock\n(now, drift_ppm, corrections)]
    R(Renderer\nframe pacing & buffering)
    M[Metrics Exporter\nPrometheus scrape]

    MC --> R
    R --> M
    MC --> M
```

## Resource management

- Every channel owns a memory budget for frame staging (default 90 frames is approximately 3 s at 30 fps).
- Libav contexts are pooled per codec to reduce reinitialization costs between plan updates.
- Backpressure from the Renderer ring buffer dynamically slows decode throughput to stay within the soft maximum.

## Health monitoring

- Metrics exported at `/metrics` (Prometheus format):
  - `retrovue_playout_channel_state{channel="N"}`: `ready`, `buffering`, or `error`.
  - `retrovue_playout_frame_gap_seconds{channel="N"}`: deviation from scheduled timestamps.
  - `retrovue_playout_restart_total{channel="N"}`: count of automatic decoder restarts.
- Structured logs include channel id, asset id, and timing drift for simplified correlation with RetroVue core logs.

## Failure handling

- Decoder crashes trigger automatic restart with exponential backoff (max five attempts per minute).
- Persistent failures transition the channel to `error` and notify ChannelManager via gRPC status.
- Slate playback remains active until ChannelManager delivers new playable content or disables the channel.

## Operator guidance

- Use the `--log-level trace` flag when tracing frame flow and timing adjustments.
- Collect a metrics snapshot before and after plan updates to verify buffer stability.
- When diagnosing timing issues, compare `retrovue_playout_frame_gap_seconds` against ChannelManager scheduler logs.

## See also

- [Architecture overview](../architecture/ArchitectureOverview.md)
- [Deployment integration](../infra/Integration.md)
- [RetroVue renderer runtime](../../../retrovue_core/docs/runtime/Renderer.md)
