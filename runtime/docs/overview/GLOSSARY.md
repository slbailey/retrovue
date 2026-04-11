_Metadata: Status=Canonical; Scope=Terminology; Owner=@runtime-platform_

# Glossary

## Purpose

Record canonical terms used across RetroVue playout documentation so teams share the same vocabulary.

## Terms

**Channel**  
Logical playout worker responsible for decoding and rendering a single broadcast stream. Identified by `channel_id`.

**ChannelManager**  
Python service in RetroVue Core that computes PlayoutSegments and sends exact execution instructions to Air via gRPC. Orchestrates channels through the gRPC control plane. Air does not understand schedules or plans.

**Execution producer**  
Component that produces decoded frames into `FrameRingBuffer`. Heterogeneous: file-backed producers (may use ffmpeg/libav or equivalent) and programmatic producers (Prevue, weather, community, test patterns). Common output contract; internal implementation may differ.

**FrameProducer**  
Legacy/alternate term for a producer that decodes media assets (e.g. file-backed with libav/ffmpeg or stub) and supplies frames into the staging path.

**FrameRingBuffer**  
Lock-free circular buffer staging decoded frames for Renderer consumption while enforcing depth invariants.

**ProgramOutput**  
Consumer that retrieves frames from the buffer and delivers them to output targets (headless, preview, or downstream pipeline). Broadcast-native term for the program signal output path.

**MetricsExporter**  
Telemetry layer responsible for aggregating channel metrics and exposing Prometheus-compatible output.

**MetricsHTTPServer**  
Lightweight HTTP endpoint (`/metrics`) serving telemetry data to Prometheus/Grafana.

**MasterClock**  
Authoritative timing source; lives in the Python runtime. Ensures channels remain synchronized. Air enforces deadlines (e.g. `hard_stop_time_ms`) but does not compute schedule time.

**PlayoutControl**  
gRPC service defined in `protos/playout.proto` for channel lifecycle and segment-based execution. Canonical calls: `legacy preload RPC` (asset_path, start_offset_ms, hard_stop_time_ms), `legacy switch RPC` (control-only, no payload).

**PlayoutSegment**  
Executable instruction computed by ChannelManager: asset_path, start_offset_ms (media-relative), hard_stop_time_ms (wall-clock, authoritative). Sent to Air via `legacy preload RPC`; Air does not understand schedules or plans.

**Playout plan**  
Opaque handle (optional path) referencing scheduled media; may be supplied by ChannelManager via `StartChannel`/`UpdatePlan`. Segment-based control is canonical.

**ProducerBus (input bus)**  
Input path in Air: two buses, **preview** and **live**. Each holds an IProducer (e.g. FileProducer). The **live** bus’s producer feeds the FrameRingBuffer → ProgramOutput → OutputBus → OutputSink. Core directs legacy preload RPC (load next segment on preview bus) and legacy switch RPC (promote preview → live). See [ProducerBusContract](../contracts/architecture/ProducerBusContract.md).

**BlackFrameProducer**  
Fallback producer that outputs valid black video (program format) and no audio. When the active content producer runs out of frames and Core has not yet supplied the next segment, Air immediately switches to BlackFrameProducer so the sink always receives valid output. See [BlackFrameProducerContract](../contracts/architecture/BlackFrameProducerContract.md).

## See also

- `../standards/documentation-standards.md`
- `docs/contracts/PlayoutEngineContract.md`
