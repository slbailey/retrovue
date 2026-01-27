# Phase 6A — Air Execution Contracts (Overview)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase6A-0 Control Surface](Phase6A-0-ControlSurface.md) · [Phase6A-1 ExecutionProducer](Phase6A-1-ExecutionProducer.md) · [Phase6A-2 FileBackedProducer](Phase6A-2-FileBackedProducer.md) · [Phase6A-3 ProgrammaticProducer](Phase6A-3-ProgrammaticProducer.md)_

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

## Purpose

Treat **Air** (the internal C++ playout engine) as a **contained sub-project** with its own phases. Each sub-phase has clear contracts and exit criteria. Execution is validated in order: control surface → producer interface → minimal file-backed producer → programmatic producer. **Only after** these contracts pass do we address MPEG-TS serving, Renderer placement, or performance.

## Scope and deferrals

- **In scope (6A.0–6A.3):** gRPC control surface, producer lifecycle/interface, minimal FileBackedProducer (ffmpeg, fixed output), ProgrammaticProducer (test pattern). All without relying on real TS serving or Renderer placement.
- **Explicitly deferred until after 6A:**
  - MPEG-TS serving
  - Renderer placement / frame-to-TS path
  - Performance tuning and latency targets

## Cross-phase invariants

These apply across all Phase 6A sub-contracts:

- **No schedule or plan logic in Air:** Air must not interpret schedules or plans. Segment-based control is canonical: Air receives exact execution instructions (asset_path, start_offset_ms, hard_stop_time_ms) via LoadPreview; SwitchToLive is control-only. Plan handles (e.g. in StartChannel) are accepted only for proto compatibility and must not drive behavior in 6A.
- **Segment-based control:** Media execution is driven by **LoadPreview** (segment payload) then **SwitchToLive** (at boundary). StartChannel initializes channel state but does not imply media playback.
- **Clock authority:** MasterClock lives in the Python runtime. Air enforces deadlines (e.g. hard_stop_time_ms) but does not compute schedule time.
- **Hard stop authoritative:** hard_stop_time_ms is authoritative; Air may stop at or before this time but must never play past it.
- **Heterogeneous producers:** The engine supports both file-backed producers and programmatic (synthetic) producers; both use the same ExecutionProducer lifecycle and preview/live slot model.

## Phase summary

| Phase   | Focus                         | Media / ffmpeg      | Exit criterion                          |
|---------|-------------------------------|---------------------|----------------------------------------|
| 6A.0    | gRPC control surface          | No                  | Server compiles; 4 RPCs accept & return |
| 6A.1    | ExecutionProducer + slots     | No                  | Lifecycle & stop semantics tested       |
| 6A.2    | FileBackedProducer (minimal)  | Yes (ffmpeg, fix out) | start_offset_ms & hard_stop_time_ms honored |
| 6A.3    | ProgrammaticProducer          | No decode           | Heterogeneous producers work            |

All phases are **automated** (tests pass without human involvement). Defer MPEG-TS, Renderer, and performance until 6A is complete.

## After Phase 6A (deferred)

Only after **6A.0–6A.3** pass:

- **MPEG-TS serving:** Real TS output, tune-in, byte-level checks (e.g. Phase 7).
- **Renderer placement:** Where frames become TS (inside Air vs separate Renderer); see [ArchitectureOverview](../architecture/ArchitectureOverview.md).
- **Performance:** Latency targets, buffer depth, throughput (see [PlayoutEngineContract](PlayoutEngineContract.md), [VideoFileProducerDomainContract](VideoFileProducerDomainContract.md)).
