# Phase 8 — Python–Air Stream & TS Pipeline (Overview)

_Related: [Phase Model](../PHASE_MODEL.md) · [Phase 6A Overview](../../archive/phases/Phase6A-Overview.md) · [Phase8-0 Transport](Phase8-0-Transport.md) · [Phase8-1 Air Owns MPEG-TS](Phase8-1-AirOwnsMpegTs.md) · [Phase8-2 Segment Control](Phase8-2-SegmentControl.md) · [Phase8-3 Preview/SwitchToLive](Phase8-3-PreviewSwitchToLive.md) · [Phase8-4 Persistent MPEG-TS Mux](Phase8-4-PersistentMpegTsMux.md) · [Phase8-5 Fan-out & Teardown](Phase8-5-FanoutTeardown.md) · [Phase8-6 Real MPEG-TS E2E](Phase8-6-RealMpegTsE2E.md) · [Phase8-7 Immediate Teardown](Phase8-7-ImmediateTeardown.md) · [Phase8-8 Frame Lifecycle and Playout Completion](Phase8-8-FrameLifecycleAndPlayoutCompletion.md) · [Phase8-9 Audio and Video Unified Producer](Phase8-9-AudioVideoUnifiedProducer.md)_

**Principle:** Prove the pipeline from Air byte output to HTTP viewer—first as raw plumbing, then with real MPEG-TS, then with segment control and switching. No media assumptions until 8.1; no switching until 8.3.

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

Phase 8 connects **Air** (C++ playout engine) to **Python** (ProgramDirector / HTTP) via a **stream transport**. Each sub-phase adds one layer: transport only → real TS from ffmpeg → segment control (seek/stop) → preview/live switch with TS continuity → fan-out and teardown. Phases 3–6 pay off in 8.2–8.3.

## Scope and dependencies

- **Requires:** Phase 6A (control surface, producers, segment params, preview/live slots) and Phase 7 (E2E tune-in, probe, boundaries) where applicable.
- **In scope (8.0–8.9):** Stream FD handoff, opaque bytes over HTTP (8.0); Air-owned ffmpeg TS output (8.1); start_offset_ms / hard_stop_time_ms driving ffmpeg (8.2); seamless SwitchToLive in the TS path (8.3); persistent TS mux (8.4); multiple readers and last-viewer teardown (8.5); real MPEG-TS only on stream, E2E VLC-playable (8.6); immediate teardown on viewer count 0 (8.7); frame lifecycle and playout completion (8.8); unified audio/video producer (8.9).
- **Explicitly out of scope until after 8.5:** Performance tuning, multi-channel scale, metrics on the stream path.

## Cross-phase invariants

- **Python does not run ffmpeg:** Air (or a subprocess owned by Air) is the only place that runs ffmpeg for channel output. Python only reads bytes and serves HTTP.
- **One logical stream per channel:** One write side (Air) and one or more read sides (HTTP viewers). Fan-out is in Python (8.5).
- **Clean shutdown:** When the last viewer disconnects, Air stops writing; no leaked FDs, no zombie ffmpeg (8.5).
- **Segment authority:** start_offset_ms and hard_stop_time_ms are defined by Python/Phase 4; Air enforces them (8.2).

## Proto (Phase 8)

The exact RPC shape is in **`protos/playout.proto`**: **AttachStream** and **DetachStream** with `StreamTransport` (UDS recommended), `AttachStreamRequest/Response`, `DetachStreamRequest/Response`. Ordering and idempotency rules are in [Phase8-0 Transport](Phase8-0-Transport.md). Transport uses **UDS by default** (Python server, Air client); no FD passing.

## Phase summary

| Phase   | Focus                          | Media / ffmpeg   | Exit criterion                                  |
|---------|--------------------------------|------------------|-------------------------------------------------|
| 8.0     | Transport contract (no media)  | No               | Raw bytes Air → Python → HTTP 200; clean shut   |
| 8.1     | Air owns MPEG-TS               | Yes (one file)   | Valid TS to HTTP; VLC plays                     |
| 8.2     | Segment control → ffmpeg       | Yes (seek/stop)  | Join-in-progress; hard stops; no drift (1 block)|
| 8.3     | Preview / SwitchToLive (TS)    | Yes (switch)     | No discontinuity / PID reset / timestamp jump   |
| 8.4     | Persistent MPEG-TS mux (single producer) | Yes              | One mux per channel; stable PIDs/continuity/PTS; no restarts |
| 8.5     | Fan-out & teardown             | Yes              | N viewers; last disconnect → Air stops; no leak |
| 8.6     | Real MPEG-TS E2E (no fake mux) | Yes              | Stream = real TS only; VLC plays E2E            |
| 8.7     | Immediate teardown             | Yes              | Viewer count 1→0 → immediate teardown; no background activity |
| 8.8     | Frame lifecycle & completion   | Yes              | EOF ≠ completion; stream until last frame rendered |
| 8.9     | Unified audio/video producer   | Yes              | One FileProducer = AV source; EncoderPipeline owns all encoding |

All phases are **automated** where possible; 8.1 and 8.6 allow a manual VLC check as a documented exit step.

## Relation to Phase 7

Phase 7 (E2E mock channel acceptance) can use stub or fake TS for automation. Once Phase 8.1+ is in place, the same Phase 7 tests (tune-in, probe, boundaries, drift) can run against **real** TS from Air over the 8.x transport.

## After Phase 8

- Full E2E with real assets and schedule (Phase 7 style over real TS).
- Performance and latency targets on the stream path.
- Multi-channel and operational hardening.
