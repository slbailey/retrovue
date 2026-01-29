<!-- ⚠️ Historical document. Superseded by: [PlayoutEngineContract](../../contracts/architecture/PlayoutEngineContract.md) and [PlayoutControlDomainContract](../../contracts/architecture/PlayoutControlDomainContract.md) -->

# Phase 6A.1 — ExecutionProducer Interface

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 6A Overview](Phase6A-Overview.md) · [Phase6A-0 Control Surface](Phase6A-0-ControlSurface.md)_

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

Shared invariants are defined in the [Overview](Phase6A-Overview.md). This phase does not introduce file decode or ffmpeg; interface and state machine only.

## Purpose

Define an **abstract producer lifecycle** and **preview vs live slots** with clear **stop semantics**. No ffmpeg, no real decode; interface and state machine only.

## Contract

**Engine vs producer responsibility:** The **engine (Air)** owns preview/live slot state and switch timing; **producers are passive** and only respond to Start/Stop. Producers must not “self-switch” or manage switch timing internally.

**ExecutionProducer (abstract interface / contract):**

- **Lifecycle:** Start, (running), Stop. Optional: Pause/Resume if part of the intended API; otherwise start/stop is sufficient for 6A.
- **Slots:** Engine maintains **preview** and **live** slots. LoadPreview binds a producer (or segment config) to the **preview** slot; SwitchToLive promotes preview → live and clears or recycles the previous live producer.
- **Stop semantics:**
  - On **StopChannel:** All producers for that channel must stop; resources released; no frames after stop.
  - On **segment boundary (hard_stop_time_ms):** Producer for that segment must stop **at or before** `hard_stop_time_ms`; engine must never play past it. (Behavior may be stubbed in 6A.1; enforcement is required by 6A.2 for file-backed.)
- **Observable:** Tests must be able to assert that “preview loaded”, “switched to live”, “stopped” occur in the correct order and that a producer is not run past its hard stop.

**Execution (6A.1):**

- Implement or mock the **interface** (e.g. `IProducer` / `ExecutionProducer`) with:
  - Start(segment params: asset_path, start_offset_ms, hard_stop_time_ms)
  - Stop()
  - Optional: IsReady(), GetState()
- Engine (or test harness) holds preview and live slot references; LoadPreview installs into preview; SwitchToLive swaps preview ↔ live and stops old live. No actual frames required; stubbed producers that only track start/stop and segment params are enough.

## Tests

- LoadPreview installs segment into preview slot; live unchanged until SwitchToLive.
- SwitchToLive promotes preview to live; old live is stopped (or recycled); preview slot is cleared or ready for next LoadPreview.
- StopChannel stops all producers for the channel; no further Start without a new StartChannel.
- Segment with `hard_stop_time_ms` is not played past that time (stub may simply record the param and assert in test that engine called stop by that time).

## Out of scope (6A.1)

- No ffmpeg or real file decode.
- No real frame output (null sink, file, or TS).
- No buffer depth or latency targets.

## Exit criteria

- Abstract producer lifecycle and preview/live slot semantics are defined and implemented (or mocked).
- Stop semantics (channel stop and hard_stop_time_ms) are contractually clear and tested.
- Automated tests pass.
