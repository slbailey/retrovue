# Phase 5 — ChannelManager Timing & Prefeed Contract

## Purpose

Prove **ChannelManager owns time orchestration**, not playback. CM watches MasterClock, knows when the current **PlayoutSegment** expires (hard_stop_time), invokes PlayoutPipeline **early**, and uses gRPC to prefeed and switch: **LoadPreview** carries the next segment; **SwitchToLive** stays exactly as-is. No media or ffmpeg required to verify behaviour.

## Prefeed window (explicit contract)

CM **must** issue **LoadPreview** for the next segment **no later than**:

`hard_stop_time_ms − prefeed_window_ms`

- **prefeed_window_ms** is a **config** (e.g. ChannelManager or system config; may be mocked in tests). The concrete value can be chosen later; the rule is what's contractual.
- **Why:** Prevents implementations that prefeed at T−1 ms; makes "early" objectively testable; gives Air a predictable buffer window.
- **Tests:** Assert **ordering** (LoadPreview before boundary, SwitchToLive at boundary), not absolute wall-clock values—unless the test injects a fixed prefeed_window_ms and then asserts the call happens within the window.

## Contract

**ChannelManager**:

- Watches **MasterClock** (or receives current time from it).
- Knows when the **current** segment expires via **hard_stop_time_ms** (PlayoutSegment / PlayoutRequest).
- Invokes **PlayoutPipeline** early (before expiry) to produce the next **PlayoutSegment** (and thus PlayoutRequest).
- **Issues `LoadPreview`** with the next segment (asset_path, start_offset_ms, hard_stop_time_ms, channel id) **by** `hard_stop_time_ms − prefeed_window_ms` at latest (see rule above).
- **Issues `SwitchToLive`** at the boundary exactly as defined in the proto (unchanged; no segment fields).
- **Immutability:** Once issued to Air, a **PlayoutSegment is immutable**; any change requires a **new** segment and a **new** LoadPreview. CM does not mutate an existing segment/request.
- Does **not** wait for Air to "ask" for the next segment; CM drives the timeline.
- **Re-evaluation:** CM may re-evaluate multiple times before the boundary (e.g. periodic tick, event loop, or scheduler), but **must not** issue duplicate **LoadPreview** calls for the **same** next segment (idempotent prefeed per segment).

**Inputs**: MasterClock, current PlayoutSegment/PlayoutRequest, **prefeed_window_ms** (config), and schedule/plan as needed to call PlayoutPipeline.

**Outputs**: next PlayoutSegment/PlayoutRequest (created early); gRPC `LoadPreview`(segment fields) by the prefeed deadline; then `SwitchToLive` at boundary. See Phase 4 for PlayoutSegment and gRPC mapping.

## Execution (this phase)

- **With or without full process.** Option A: run ProgramDirector (owns ChannelManager registry); simulate tune-in via **direct ProgramDirector API** (e.g. `ensure_channel_running(channel_id)`)—no HTTP. Advance time or wait until near boundary and assert that CM has issued LoadPreview (by prefeed deadline) and then SwitchToLive at the boundary. Option B: unit-test CM in isolation with a **stepped clock**: advance clock to just before boundary, **trigger CM evaluation** (tick/update), assert LoadPreview was sent before boundary and SwitchToLive at boundary.
- **CM drive model:** CM may be driven by a **periodic tick**, **event loop**, or **scheduler**; the contract does not prescribe push vs pull. Tests may **explicitly trigger evaluation** (e.g. `cm.tick(now)` or advance clock and run one loop).
- **Test scaffolding (recommended)**: Use a **gRPC mock** that records `LoadPreview` and `SwitchToLive` calls. Start CM with stepped clock; advance to T+1s, T+prefeed window, T+boundary; assert **ordering**: LoadPreview occurs by `hard_stop_time_ms − prefeed_window_ms`, SwitchToLive at boundary. Tests assert ordering (and optionally, with fixed prefeed_window_ms, that LoadPreview is within the window); no requirement to assert a specific millisecond value.

## Tests

- CM issues LoadPreview **no later than** `hard_stop_time_ms − prefeed_window_ms` (ordering, or with fixed config assert within window).
- CM issues SwitchToLive at the boundary (after LoadPreview for that segment).
- CM never mutates an existing segment once issued; changes require a new segment and new LoadPreview.
- CM never waits for Air to "ask" for the next segment; CM drives the timeline.
- CM does **not** issue duplicate LoadPreview for the same next segment when re-evaluating multiple times before the boundary.

## Out of scope

- ❌ No real media
- ❌ No ffmpeg (gRPC mock / test double only for this phase)

## Exit criteria

- CM stays ahead of the clock.
- Automated tests pass without human involvement (stepped clock + gRPC mock or recorded LoadPreview/SwitchToLive calls).
- ✅ Exit criteria: CM stays ahead of the clock; tests pass automatically.
