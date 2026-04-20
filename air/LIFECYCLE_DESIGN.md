# AIR vNext — Session Lifecycle Design

**Status:** design note for the next implementation slice (BootstrapContentGate + lifecycle state machine).
**Author:** drafted 2026-04-20, end of gRPC slice.
**Scope:** semantic state machine for a single AirSession from `OpenAir()` to termination. Does NOT cover retune, seams, or admission pacing — those are later slices.

## Purpose

Make the session's lifecycle state explicit and observable. Today, `AirSession` has a binary "on-air or not" state implied by `encode_thread_.joinable()`. That's enough for the demo but loses two distinctions that matter:

1. **Warming vs. on-air** — per `project_retrovue_air_lifecycle_model`, first bytes on wire must be content, not pad. Today the encoder emits the moment the thread starts; we need an explicit gate.
2. **Failed start vs. on-air loss** — today a decode failure during startup is indistinguishable from end-of-stream. Core can't tell "AIR never got on air" from "AIR finished the content."

## State table

| State | Entry condition | Exit to | Exit condition |
|---|---|---|---|
| **WARMING** | `OpenAir()` returns successfully | READY | All bootstrap readiness conditions satisfied for ≥1 tick |
| | | FAILED_START | Any irrecoverable startup error (decode open fail, source missing, canonical mismatch, etc.) |
| **READY** | Bootstrap readiness conditions met | ON_AIR | Next tick-boundary commit from BootstrapContentGate |
| | | WARMING | Conditions regress (e.g. buffer drained below floor) — sticky/non-regressing NOT guaranteed during READY, only once ON_AIR fires |
| | | FAILED_START | Extended inability to maintain readiness (configurable timeout) |
| **ON_AIR** | BootstrapContentGate fires; first content byte emitted | STOPPING | `Close()` called by gRPC handler or internal failure |
| **STOPPING** | `Close()` called from any prior state | (terminal) | Encode thread joined; encoder flushed + closed; fd closed |
| **FAILED_START** | Irrecoverable pre-ON_AIR error | (terminal) | Session must be destroyed; StartChannel response carries `ok=false` with reason class |

**Terminal states:** STOPPING (after completion) and FAILED_START. No restart from these; a new session must be constructed.

**Sticky once ON_AIR:** the system does NOT regress from ON_AIR back to WARMING. On-air continuity is broken only by STOPPING. Pad substitution (runtime fault recovery) happens WITHIN ON_AIR and does not change the state.

## Transition diagram

```
                    OpenAir()
                       |
                       v
                  +---------+
                  | WARMING | <--- (regress: conditions lost)
                  +---------+
                   |       |
           (conds  |       | (startup fail)
            met)   v       v
              +-------+  +--------------+
              | READY |  | FAILED_START |  (terminal)
              +-------+  +--------------+
                   |
           (next   |
            tick)  v
              +--------+
              | ON_AIR | <--- (pad substitution happens WITHIN this state;
              +--------+       does NOT regress to WARMING)
                   |
            Close()|
                   v
              +----------+
              | STOPPING |  (terminal after thread joined + fd closed)
              +----------+
```

## Bootstrap readiness conditions (WARMING → READY)

All MUST be true for READY (aggregate, not depth alone — per execution discipline memory):

- Video buffer depth ≥ floor (configurable; e.g. `≥ 500ms` of content)
- Audio buffer depth ≥ floor
- First video frame in buffer is decodable (AVFrame not null, PTS set)
- First audio sample present (nb_samples > 0)
- Monotonic PTS (no regressions across last N frames)
- V/A fronts aligned within `≤ 1 channel frame period`
- Minimum runway duration achieved (time-based, not frame-count; floor * fps would undercount at low fps)
- No decoder fault state

Any one failing → stays in WARMING. All satisfied for ≥1 tick → READY.

## Failure reason classes (for FAILED_START)

Structured enum; carries through to `StartChannelResponse.message` and observability:

- `SOURCE_OPEN_FAILED` — FileSourceProducer::Prepare() or Activate() returned false. Missing file, unsupported format, etc.
- `CANONICAL_MISMATCH` — source pixel format or other hard constraint incompatible with requested channel canonical (today: FileSourceProducer rejects non-YUV420P at Prepare).
- `ENCODER_OPEN_FAILED` — MpegTsEncoder::Open() returned false. Usually a libav configuration issue.
- `UDS_CONNECT_FAILED` — AttachOutput failed at the fd level. Core's UDS path doesn't exist or isn't accepting.
- `WARMUP_TIMEOUT` — WARMING exceeded a deadline (e.g. 30 seconds) without reaching READY. Indicates a slow or stuck decoder.
- `WARMUP_HEALTH_FAILURE` — decoder emitted a fault signal during warmup.

Reason class is a stable string suitable for metrics labels.

## Entry / exit actions per state

- **WARMING enter:** record `warming_entered_mono_us`. Emit structured event. Encode thread started (already happens today in OpenAir).
- **WARMING exit → READY:** record `warming_duration_us = now - warming_entered_mono_us`. Emit structured event with duration.
- **READY enter:** record `ready_entered_mono_us`. Emit event. (Byte path still closed — emission has NOT started.)
- **READY → ON_AIR:** BootstrapContentGate arms the commit. Record `bootstrap_total_duration_us = now - warming_entered_mono_us`. Open the byte path (permit emission). Emit kickoff event with first content frame's channel PTS.
- **ON_AIR enter:** first emission tick fires. `time_on_air_started` recorded. Diagnostics counters begin advancing.
- **STOPPING enter:** `stopping_entered_mono_us` recorded. Emit event. Signal encode thread via `stopping_.store(true)`.
- **STOPPING exit (terminal):** encoder flushed + closed, thread joined, fd closed. Emit final event with totals.
- **FAILED_START enter (terminal):** reason class set, structured event emitted. Session disposable.

## Telemetry

Counters / gauges exposed via diagnostic accessors on `AirSession`:

| Metric | Type | Meaning |
|---|---|---|
| `state_current` | enum | Current state, one of {WARMING, READY, ON_AIR, STOPPING, FAILED_START} |
| `warming_duration_us` | gauge | Duration of WARMING (set on exit) |
| `bootstrap_total_duration_us` | gauge | Duration from OpenAir to first ON_AIR tick (`bootstrap_delay_ms` in as-run) |
| `on_air_duration_us` | counter | Total time in ON_AIR so far |
| `failed_start_reason` | string | Reason class if FAILED_START reached |
| `ready_regressions_total` | counter | Count of READY → WARMING regressions within this session |
| `readiness_signals` | struct | Current snapshot of individual readiness inputs (depth, alignment, etc.) |
| `frames_encoded` | counter | Already exists; unchanged |
| `bytes_written` | counter | Already exists; unchanged |
| `pacer_total_sleep_ms` | counter | Already exists; unchanged |

Structured events (for log aggregation / as-run):

- `state_transition{from, to, reason_class, mono_us}`
- `kickoff_fired{first_content_pts_us, warming_duration_us, bootstrap_total_duration_us}` (on READY → ON_AIR)
- `failed_start{reason_class, detail_message, mono_us}`

## What this is NOT

- **Not retune.** Retune (device-centric) is a separate transition class per `project_retrovue_air_separation_of_concerns`. The five states above apply to a single bootstrap→on-air→stop cycle.
- **Not seam / scheduled transitions.** SeamController owns those, within the ON_AIR state. A seam does not change the lifecycle state; it's an intra-state event.
- **Not failure recovery within ON_AIR.** Pad substitution, source faults mid-block, slow successors — all handled by AIR_Lifecycle's failure transition class WITHIN ON_AIR. The lifecycle state stays ON_AIR throughout.
- **Not multi-block / BlockPlan sessions.** BlockPlan adds a pre-WARMING phase for Core to feed blocks; out of scope here.

## Wiring plan (for implementer)

1. Add `enum class SessionState` to `air_session.hpp` with the five values.
2. Add `std::atomic<SessionState> state_{WARMING}` (initialized by OpenAir) and the timestamp fields.
3. Build `BootstrapContentGate` as a small standalone class (`include/bootstrap_content_gate.hpp` / `.cpp`): takes a `ReadinessSignals` snapshot per tick, returns `{NotReady, Pending, Ready}` verdict, emits kickoff once.
4. Build `ReadinessController` or fold its logic into the gate for this slice (keep minimal — one class is fine for first cut; split later if complexity warrants).
5. Modify `EncodeLoop` to:
   - Pull video/audio as today, but do NOT hand to encoder until the gate has fired.
   - Evaluate readiness each tick; update state transitions.
   - On gate fire: state → ON_AIR, first frame goes to encoder, emission begins.
6. Modify `Close()` to transition to STOPPING before joining.
7. Wire telemetry accessors so gRPC status responses or a separate diagnostics RPC can read them later.

## Risks / open questions

- **Where does "byte path closed" live?** Option A: the encoder simply isn't called with frames (cleanest; no bytes to drop). Option B: bytes are produced but the SocketEmitter is gated. Recommend A — symmetric with the lifecycle memory ("first bytes are content").
- **Warmup timeout value.** 30 seconds is defensible for bootstrap; shorter is aggressive. Start with 30s configurable.
- **READY regression policy.** If conditions regress after READY but before the commit tick, do we go back to WARMING or stay in READY expecting to cut at the next tick? Recommendation: regress to WARMING; don't cut to air on stale signals. But only regress READY → WARMING; never regress ON_AIR back.
- **Gate fires sticky or re-armable?** Per org-chart memory, the bootstrap gate is sticky — fires exactly once per session. Re-arming would be for retune (different transition class).

## Related memory

- `project_retrovue_air_lifecycle_model` — bootstrap vs on-air philosophy. First byte is content.
- `project_retrovue_air_execution_discipline` — aggregate readiness, arm/commit at tick boundary, fence is sacred.
- `project_retrovue_air_org_chart` — three transition classes (scheduled / bootstrap / failure). This doc is the bootstrap class's state machine.
- `project_retrovue_air_separation_of_concerns` — the three-phase startup. Lifecycle states live on top of that structure.
