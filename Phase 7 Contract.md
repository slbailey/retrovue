# Phase 7 — End-to-End Mock Channel Acceptance

## Purpose

Prove the system works as a **linear channel**: a viewer can “tune in” at any time and see the correct asset + offset; boundaries are respected; no drift over time. All assertions are automated (simulate tune-in, no human in the loop).

**Phase 7 is the only HTTP- and real-playout–dependent phase.** Phases 0–6 are testable via the **direct ProgramDirector API** (e.g. `start_channel(channel_id, now)` or `ensure_channel_running(channel_id)`); HTTP is not required there. Phase 7 is where **HTTP tune-in** is required: a “viewer” is simulated by issuing `GET /channels/{channel_id}.ts` against ProgramDirector. Phase 7 also uses real ffmpeg and long-running behaviour.

Phase 7 does not introduce new scheduling logic, timing rules, or playout semantics.
It only verifies that existing Phases 0–6 compose correctly when exercised through HTTP tune-in.

## Contract

- **Startup**: Retrovue is started (e.g. `retrovue program-director start` with Phase 0 options); ProgramDirector and ChannelManagerDaemon run; mock channel is available (e.g. `mock` or `retro1`).
- **Tune-in (Phase 7 only)**: A “viewer” is simulated by **HTTP** `GET /channels/{channel_id}.ts` (or equivalent) against ProgramDirector. Optionally read some bytes or only assert HTTP 200 and headers. (For Phases 0–6, use the direct ProgramDirector API instead.)
- **Correctness**: For a given tune-in time (or clock controlled by test), the **content** (or stream metadata / side effects) matches the **expected asset + offset** from the Phase 4 pipeline and Phase 3 resolver.
- **Boundaries**: Grid boundaries (:00, :30) are respected forever (no early/late switch, no gap).
- **Stability**: No drift after hours (run with accelerated or stepped clock if needed; assert consistency over multiple boundaries).

## Execution

1. Start RetroVue with Phase 0 (or current) options:
   - Example: `retrovue program-director start --phase0 --phase0-program-asset /path/to/samplecontent.mp4 --phase0-program-duration 1200 --phase0-filler-asset /path/to/filler.mp4 --phase0-filler-duration 3600 --port 8000`
2. Use a **test script or pytest** to simulate tune-in (no browser, no human):
   - HTTP client: `GET http://localhost:8000/channels/mock.ts` (or chosen channel id).
   - Assert: status 200, `Content-Type: video/mp2t` (or equivalent), and optionally read a bounded number of bytes to ensure stream starts.
3. For **time-sensitive assertions** (e.g. “at :02 we see samplecontent, at :17 samplecontent, at :29 filler”):
   - Use **stepped or accelerated clock** and control “now” in test, then simulate tune-in and assert expected asset/offset (e.g. from response metadata, or from a test-only probe endpoint that returns “current PlayoutRequest” or “current asset”).
   - Or run short real-time tests at known wall-clock times (e.g. run test at :02 past the hour and assert; less deterministic).

## Test scaffolding

- **E2E test (automated)**:
  - Start ProgramDirector + ChannelManagerDaemon in process or subprocess (e.g. pytest fixture with free port).
  - Simulate tune-in: `requests.get(http://localhost:{port}/channels/{channel_id}.ts, stream=True)` (or httpx); read first N bytes or only headers; then close.
  - Assert 200 and expected headers; optionally assert no exception and some bytes received.
- **Time-based content assertion** (recommended):
  - If possible, inject a **stepped clock** into the test run so that “now” is fixed (e.g. 10:02, 10:17, 10:29). After tune-in, query a test-only endpoint or internal state: “current asset” / “current offset” and assert samplecontent vs filler and offset. This avoids relying on wall clock.
- **Boundary and drift**:
  - Run with stepped clock; advance across several grid boundaries; after each boundary, assert “current” asset/offset matches Phase 3/4 expectations. Optionally run a long-running test (many boundaries) and assert no drift (e.g. hard stop times remain aligned to grid).

## Tests

- Tune in at **:02** → content (or metadata) matches expected asset + offset (samplecontent near start).
- Tune in at **:17** → content matches expected asset + offset (samplecontent, ~17 min offset).
- Tune in at **:29** → content matches expected asset + offset (filler segment).
- Boundaries respected forever (multiple boundaries, no gap, correct switch).
- No drift after many boundaries (e.g. N × 30 minutes; offsets and hard stops still correct).

## Exit criteria

- All E2E tests pass with **no human involvement** (automated tune-in simulation and assertions).
- Content (or observable behaviour) matches expected asset + offset at each tune-in time.
- Boundaries respected; no drift.
- ✅ Exit criteria: E2E mock channel acceptance passes automatically; system is ready for real Air or production scheduling when desired.
