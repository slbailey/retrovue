# Phase 0 — Clock Contract

> **Historical:** This doc described the pre–PD/CM collapse flow (ChannelManagerDaemon as provider). Current architecture: ProgramDirector owns the ChannelManager registry; single HTTP server; stream path is **GET /channel/{channel_id}.ts**. See `docs/core/ProgramDirector-ChannelManagerDaemon-Collapse.md`.

## Purpose

Establish a single, testable time authority. All downstream logic (grid math, schedule resolution, ChannelManager timing) must consume time only through this interface.

## Startup flow (Phases 0–7)

The following flow applies once the system is runnable:

1. **Start RetroVue**: `retrovue program-director start [options]` (or equivalent) starts the control plane.
2. **ProgramDirector** starts and binds its HTTP server; it holds (or embeds) the ChannelManager registry (post-collapse: no separate daemon).
3. ChannelManagers are created on first use by ProgramDirector (no pre-spawn for every channel).
4. **Simulated tune-in**: For Phases 0–6, tune-in is simulated via a **direct ProgramDirector API** (no HTTP). For Phase 7, tune-in uses HTTP (e.g. `GET /channel/{channel_id}.ts`). In both cases, ProgramDirector creates or returns a ChannelManager for that `channel_id`; that ChannelManager may start a Producer/Air process (and in Phase 7 serve the stream over HTTP).

**Testability**: All phases must be testable via a **direct ProgramDirector API**. HTTP is only required in the final end-to-end phase (Phase 7). Make the path explicit, for example:
- `ProgramDirector.start_channel(channel_id, now)` or  
- `ProgramDirector.ensure_channel_running(channel_id)`

Tests call this API (or the equivalent in-process path) and assert on responses, stream metadata, or side effects—**no manual interaction required**. No need for a separate "TuneInSimulator" abstraction; the direct API is the contract.

### Phase scope: HTTP and real playout only in Phase 7

- **Phases 0–6**: Use the **direct ProgramDirector API** (e.g. `start_channel` / `ensure_channel_running`) + ChannelManager + **gRPC** (or in-process mocks). No HTTP tune-in, no real ffmpeg. Tests drive the control plane via this API and assert on clock, grid, plan, PlayoutRequest, and gRPC calls/responses.
- **Phase 7**: **Only** phase that uses **HTTP tune-in**, **real ffmpeg**, and **long-running** behaviour. Keeps early phases decoupled from transport and media.

---

## Contract

- **MasterClock** (or equivalent) is the single time authority.
- `MasterClock.now()` (or `now_utc()` / protocol as implemented) returns wall-clock time.
- All downstream logic consumes time **only** via this interface.
- No component calls `datetime.now()` or `time.time()` directly for scheduling/playout decisions.

## Execution (this phase)

- **No process required for Phase 0.** Implement and test the clock in isolation.
- Provide a **real** implementation (e.g. `RealTimeMasterClock`) and a **test** implementation (e.g. `SteppedMasterClock` or injectable `now` callback) so tests can control time.

## Test scaffolding

- **Unit tests**: Instantiate the test clock (e.g. SteppedMasterClock); advance time; assert `now()` / `now_utc()` values and that elapsed/time-since logic is correct.
- **Determinism under test**: With an injectable or stepped clock, test behaviour must be deterministic (no reliance on real wall clock inside the test).
- **Guard against raw time**: (Optional) Search or static check: no direct `datetime.now()` / `datetime.utcnow()` in scheduling, grid, or playout code paths.

## Tests

- Clock returns deterministic value under test (injected/stepped clock).
- No component calls `datetime.now()` (or equivalent) directly for authority time.

## Out of scope

- Grid math, schedule, ChannelManager, Air, or any other component logic.

## Exit criteria

- Time is injectable and mockable.
- Automated tests pass with no human involvement.
- ✅ Exit criteria: time is injectable and mockable; tests pass automatically.
