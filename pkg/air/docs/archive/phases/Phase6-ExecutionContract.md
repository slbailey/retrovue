# Phase 6 — Air Execution Contract (Mocked First)

## Purpose

Validate **control-plane → data-plane handoff** via gRPC. Air (or a mock) responds to `LoadPreview` and `SwitchToLive`; Phase 6 tests **observable control-plane outcomes only**—no inspection of MPEG-TS bytes. That keeps Phase 6 deterministic and automatable. Real Air and byte-level checks belong in Phase 7.

## Contract

**Air** (playout engine, or gRPC mock):

- Accepts **PlayoutRequest** intents via gRPC: `StartChannel`, `LoadPreview`, `SwitchToLive`, `UpdatePlan`, `StopChannel` (see Phase 4 mapping).
- On `LoadPreview`: loads asset into preview slot; shadow decode may start; does **not** go live.
- On `SwitchToLive`: promotes preview to live **exactly** when commanded (at boundary); seamless, no gap.

## Execution (this phase)

- **Mock Air**: gRPC test double that implements `PlayoutControl` and records/returns the response fields below. ChannelManager (or test harness) drives LoadPreview then SwitchToLive; assert on **gRPC response fields**, not TS bytes.
- **Real Air (later)**: Same gRPC contract; Phase 7 adds HTTP tune-in and real ffmpeg.

## Test scaffolding — control-plane outcomes only

Phase 6 tests **must not** inspect MPEG-TS bytes. Test observable gRPC outcomes instead:

- **LoadPreview**: Assert `LoadPreviewResponse.shadow_decode_started == true` (or equivalent from mock).
- **SwitchToLive**: Assert `SwitchToLiveResponse.pts_contiguous == true` (when implemented); and that the switch occurs when commanded.
- **Channel lifecycle**: Channel remains active across switches; no `StopChannel` unless explicitly commanded (e.g. last viewer disconnects).
- **Order**: LoadPreview for next segment before boundary; SwitchToLive at boundary; no gap, no double-switch.

This keeps Phase 6 deterministic and automatable without depending on real media or TS parsing.

## Tests (Phase 6 — gRPC / control-plane only)

- After `LoadPreview`: `LoadPreviewResponse.shadow_decode_started == true` (or mock equivalent).
- After `SwitchToLive`: `SwitchToLiveResponse.pts_contiguous == true` (when available); switch at commanded time.
- Channel remains active across multiple switches; no spurious `StopChannel`.
- Receives LoadPreview for next segment before current segment ends; receives SwitchToLive at boundary.

## Tests (real Air / byte-level — Phase 7)

- Join mid-segment (correct offset), no gap at boundaries, no looping artifacts: tested in Phase 7 with HTTP tune-in and real ffmpeg.

## Exit criteria

- Control-plane → data-plane handoff validated via gRPC response assertions; no MPEG-TS inspection in Phase 6.
- Automated tests pass without human involvement.
- ✅ Exit criteria: gRPC behaviour correct and tested; byte-level behaviour covered in Phase 7.
