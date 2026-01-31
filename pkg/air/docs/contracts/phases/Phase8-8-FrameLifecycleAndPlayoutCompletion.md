# Phase 8.8 — Frame Lifecycle and Playout Completion

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-5 Fan-out & Teardown](Phase8-5-FanoutTeardown.md) · [Phase8-6 Real MPEG-TS E2E](Phase8-6-RealMpegTsE2E.md) · [Phase8-7 Immediate Teardown](Phase8-7-ImmediateTeardown.md)_

**Principle:** Producer exhaustion (EOF) MUST NOT imply playout completion. Teardown MUST NOT occur until all scheduled frames have been rendered at their wall-clock time. The renderer / clock owns playout completion; EOF from the demuxer does not. **Clock-driven segment switching** (LoadPreview → SwitchToLive at scheduled boundaries) is the primary mechanism; EOF is a secondary condition that does not drive teardown.

---

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md)).

---

## Problem Statement

File-based content is demuxed faster than real time. The demuxer reaches end-of-file (EOF) before all decoded frames have been presented to the viewer at the intended frame rate. Treating producer EOF as “playout done” causes:

- **Premature teardown:** The pipeline shuts down while frames remain in the buffer, not yet rendered.
- **Reconnect loops:** The system interprets EOF as failure or end-of-stream and may attempt restarts or reconnects.
- **Stream instability:** Viewers see abrupt stops, restarts, or gaps instead of smooth playback to the last frame.

The **correct** behavior: EOF from the demuxer only means “no more frames will be produced.” Playout is complete only when the **last frame has been presented** at its scheduled wall-clock time. Teardown is allowed only after that completion signal from the time-governed rendering path.

This phase defines the behavioral contract for that lifecycle. It does **not** refactor code, rename components, or introduce new abstractions.

---

## Terminology (Explicit, Temporary)

The following terms are used in this contract. Terminology is **provisional** and may be formalized in later phases.

| Term | Definition |
|------|------------|
| **Producer** | The frame source (e.g. file demuxer, decoder). Produces decoded frames into a buffer. May run faster than real time. |
| **Renderer** | The component that presents frames at wall-clock time according to a master clock / frame rate. Owns “when” each frame is shown. |
| **Producer EOF** | The condition where the producer has no more frames to emit (e.g. end of file for file-based content). Does **not** mean all frames have been presented. |
| **Playout completion** | The condition where the last scheduled frame has been presented at its scheduled wall-clock time. Only the renderer/clock path may declare this. |
| **Frame production** | The activity of the producer emitting frames into the buffer. |
| **Frame buffering** | Frames held between production and presentation (e.g. ring buffer). |
| **Frame presentation** | The act of outputting a frame at its scheduled time (e.g. writing to mux/stream at the correct PTS). |
| **Clock-driven switching** | Segment switching based on scheduled time boundaries (not EOF). `LoadPreview` prepares next asset; `SwitchToLive` activates it at the segment boundary. |
| **Teardown eligibility** | The condition under which the channel may be torn down: either (a) viewer count has dropped to zero (Phase 8.7), or (b) playout has completed and viewer count is still ≥ 1 (this phase). |

---

## Lifecycle Model

### Step-by-step description

1. **Clock-driven segment switching**  
   Segment boundaries are determined by scheduled time, not EOF. Before the segment boundary (preload deadline), `LoadPreview` is called to prepare the next asset: it creates a preview producer but **does not start it**. At the scheduled segment boundary, `SwitchToLive` is called: it starts the preview producer, stops the old live producer, and atomically swaps preview → live. The encoder and TS mux persist across switches (created once per channel start, never closed/reopened).

2. **File demux**  
   The live producer (e.g. file demuxer) reads the container and emits decoded frames. Demuxing may run **faster than real time**. EOF occurs when the file has been fully read; at that moment, frames may still be in the buffer and not yet presented. **EOF does not trigger switching**; clock-driven `SwitchToLive` at the segment boundary handles transitions.

3. **Frame buffering**  
   Frames produced by the live producer are placed into a buffer (e.g. frame ring buffer) between the producer and the renderer. The buffer decouples production rate from presentation rate. The same buffer is used across segment switches; only the producer feeding it changes.

4. **Timed rendering**  
   The renderer (or equivalent time-governed path) consumes frames from the buffer and presents each at its scheduled wall-clock time, according to the master clock and frame rate. This is the only path that determines "all frames have been shown." The encoder/mux continues encoding frames from the buffer without interruption across switches.

5. **Completion signaling**  
   Playout completion is signaled **only** when the last frame has been presented—i.e. when the renderer has finished outputting the final frame at its scheduled time. No component may infer completion from EOF or from "buffer empty" alone. Playout completion MUST be signaled by the time-governed rendering path (or a component directly driven by the master clock), not by the producer or buffer.

6. **Teardown eligibility**  
   The renderer (or equivalent time-governed path) consumes frames from the buffer and presents each at its scheduled wall-clock time, according to the master clock and frame rate. This is the only path that determines “all frames have been shown.”

4. **Completion signaling**  
   Playout completion is signaled **only** when the last frame has been presented—i.e. when the renderer has finished outputting the final frame at its scheduled time. No component may infer completion from EOF or from “buffer empty” alone. Playout completion MUST be signaled by the time-governed rendering path (or a component directly driven by the master clock), not by the producer or buffer.

6. **Teardown eligibility**  
   - If **viewer count = 0:** Teardown is **immediate** (Phase 8.7). Phase 8.8 does not apply.
   - If **viewer count ≥ 1:** Teardown is allowed **only after** playout completion (last frame presented). Until then, the stream MUST continue; EOF from the producer MUST NOT trigger teardown, stop writing, or channel shutdown.

---

## State Transitions

### Valid states (logical)

- **Producing** — Producer is emitting frames; buffer may be filling.
- **Exhausted** — Producer has reached EOF; no more frames will be produced; buffer may still hold frames.
- **RenderingRemaining** — All production is done (Exhausted); frames may be pending either in the buffer or already scheduled but not yet presented (e.g. last frame dequeued, still waiting for its scheduled presentation time).
- **Completed** — Last frame has been presented at its scheduled time; playout completion has been signaled.
- **TornDown** — Channel runtime has been torn down (either due to viewer count 0 or after Completed with viewer count ≥ 1).

### Valid transitions

- Producing → Exhausted (on producer EOF).
- Exhausted → RenderingRemaining (always, when buffer or render path still has frames).
- RenderingRemaining → Completed (when last frame is presented).
- Completed → TornDown (when teardown is executed after completion).
- *Any state* → TornDown (when viewer count goes to zero; Phase 8.7 immediate teardown).

### Forbidden transitions

- **EOF → Teardown** — MUST NOT tear down solely because the producer reported EOF.
- **Exhausted → TornDown** — MUST NOT tear down while frames remain to be rendered (RenderingRemaining).
- **BufferEmpty → Teardown** — MUST NOT infer teardown from “buffer is empty” alone; completion is only when the renderer has presented the last frame.
- **ProducerEOF → StopWriting** — MUST NOT stop writing to the stream solely because the producer reached EOF; writing continues until the last frame is rendered.

No component may infer teardown or “stream over” based solely on EOF or empty buffers. Completion MUST be an explicit signal from the time-governed rendering path.

---

## Contract Rules

### Producer exhaustion ≠ playout completion

1. **Producer EOF only means no more frames will be produced.** It does NOT mean that all frames have been presented. Implementations MUST NOT treat producer EOF as playout completion.

2. **EOF from a file demuxer MUST NOT trigger teardown, stop writing, or channel shutdown by itself.** When viewer count ≥ 1, the pipeline MUST continue to render and write all buffered frames until playout completion.

3. **Renderer / clock owns playout completion.** Playout is complete only when the last frame has been presented at its scheduled wall-clock time. Playout completion MUST be signaled by the time-governed rendering path (or a component directly driven by the master clock), not by the producer or buffer.

4. **Teardown MAY occur only after rendering completion (when viewer count ≥ 1), not after producer EOF.** Teardown may also occur immediately when viewer count drops to zero (Phase 8.7).

### No implicit EOF-driven teardown

5. **No component MAY infer teardown based solely on EOF or empty buffers.** Completion MUST be an explicit signal from the time-governed rendering path.

6. **No component MAY stop writing to the stream or shut down the channel solely because the producer has reached EOF.** Writing and channel activity MUST continue until either (a) playout completion, or (b) viewer count reaches zero (Phase 8.7).

### Immediate teardown (Phase 8.7) unchanged

7. **Phase 8.7 rules still apply.** If viewer count drops to zero, teardown is immediate. Phase 8.8 applies only while viewer count ≥ 1. When viewer count = 0, the pipeline MUST tear down without waiting for playout completion or producer EOF.

### Clock-driven switching (LoadPreview / SwitchToLive)

8. **LoadPreview prepares but does not activate.** `LoadPreview` creates the preview producer but **MUST NOT** start it. The preview producer remains idle until `SwitchToLive` is called. This ensures LoadPreview only prepares the next asset; clock-driven SwitchToLive triggers the actual switch.

9. **SwitchToLive activates and swaps.** `SwitchToLive` starts the preview producer (if not already started), stops the old live producer, and atomically swaps preview → live. The encoder and TS mux MUST remain alive across switches (created once per channel start, never closed/reopened during SwitchToLive). PTS continuity is maintained; no PAT/PMT reset, no discontinuity flags.

10. **Encoder/mux persistence.** The encoder pipeline (EncoderPipeline) and TS mux (AVFormatContext, AVIO) are created once per channel start and persist across all segment switches. They are closed only when the channel is torn down (viewer count 0 or playout completion). This ensures broadcast-grade continuity: no pause, no time reset, no mid-stream jump.

### Explicit lifecycle

11. **The contract distinguishes clearly between:** frame production, frame buffering, frame presentation, playout completion, and teardown eligibility. Implementations MUST maintain observable behavior consistent with these distinctions: no EOF-driven teardown, clock-driven switching, and teardown only when eligible (viewer count 0 or playout completed).

---

## Tests

### Unit tests

- **LoadPreview does not start preview producer:** Call `LoadPreview` and assert that the preview producer is created but not started (no frames written to buffer). Assert that `SwitchToLive` starts the preview producer before swapping to live.
- **SwitchToLive starts preview before swap:** Call `LoadPreview` then `SwitchToLive` and assert that the preview producer is started before it becomes the live producer. Assert atomic swap (preview → live, preview cleared).
- **Encoder persists across switches:** Perform multiple LoadPreview/SwitchToLive cycles and assert that the encoder pipeline is not closed/reopened between switches. Assert PTS continuity (monotonic increase, no reset).
- **EOF before render complete:** Simulate producer EOF while the buffer still contains frames (or the render path has not yet presented the last frame). Assert that teardown is NOT triggered, that writing continues, and that playout completion is only signaled after the last frame is presented. Assert that no “stream over” or “channel stop” is inferred from EOF alone.
- **Completion only after last frame:** With a known frame count and simulated real-time render clock, assert that playout completion is signaled only when the last frame has been presented at its scheduled time, not when the producer reports EOF.

### Integration tests

- **Clock-driven switching:** Run a schedule with multiple segments (e.g. SampleA 10s → SampleB 10s → SampleA). Assert that `LoadPreview` is called before each segment boundary (preload deadline) and that `SwitchToLive` is called exactly at each segment boundary. Assert that the preview producer is not started until `SwitchToLive`.
- **Encoder persistence across switches:** Perform multiple segment switches and assert that the encoder pipeline (EncoderPipeline) is not closed/reopened. Assert that AVFormatContext, AVIO, and PTS counters persist across switches. Assert no PAT/PMT injection, no discontinuity flags, same PCR timeline.
- **Producer finishes early, stream continues:** Run a file-based producer that reaches EOF quickly (demux faster than real time). Assert that the TS stream continues until the last frame has been rendered and written; assert no premature stop, no reconnect attempts, and no restarts. Assert that teardown occurs only after the completion signal from the render path (or after viewer count → 0).
- **Buffer drains at real-time rate:** With producer EOF and frames remaining in the buffer, assert that output (e.g. MPEG-TS bytes) continues at the expected real-time rate until the last frame is output; assert no burst then stop, and no EOF-based teardown.

### E2E test expectations

- **Broadcast-grade switching:** Loop SampleA (10s) → SampleB (10s) → SampleA → SampleB. Observe in VLC: no pause, no time reset, no mid-stream jump, audio continuous. Encoder and TS mux stay alive across switches.
- **No reconnects:** Playing a single file to completion (one viewer) MUST NOT produce “attempting reconnect” or equivalent; the stream MUST continue smoothly until the last frame.
- **No restarts:** The producer/encoder MUST NOT be restarted or re-created solely because of EOF; one logical playout from start to completion. The encoder pipeline MUST NOT be closed/reopened during SwitchToLive.
- **Smooth playback:** VLC (or equivalent) plays from start to last frame without visible truncation, restart, or discontinuity attributable to EOF-based teardown.
- **Phase 8.6 VLC playback remains correct:** All Phase 8.6 E2E expectations (real MPEG-TS, VLC-playable) still hold.
- **Phase 8.7 teardown semantics still hold:** Last viewer disconnect still causes immediate teardown; no background activity after teardown; baseline resource invariants hold.

---

## Non-Goals

- **No renaming of components.** This contract does not require or define renames of Producer, Renderer, EncoderPipeline, or any other class or module.
- **No performance tuning.** Throughput, latency, or buffer sizing optimizations are out of scope.
- **No refactors beyond lifecycle correctness.** Structural refactors (new abstractions, new interfaces) are out of scope; only behavior that affects frame lifecycle and teardown eligibility is in scope.
- **Audio frame exhaustion follows the same rules as video frame exhaustion.** Audio EOF does not imply playout completion. This phase is audio-agnostic; Phase 8.9 enforces audio-specific lifecycle rules that align with this contract.

---

## Exit Criteria

1. **Clock-driven switching works correctly.** `LoadPreview` creates preview producer but does not start it. `SwitchToLive` starts preview producer before swapping to live. Switching occurs at scheduled segment boundaries, not EOF.
2. **Encoder/mux persistence.** Encoder pipeline (EncoderPipeline) and TS mux (AVFormatContext, AVIO) are created once per channel start and persist across all segment switches. They are closed only on channel teardown. PTS continuity is maintained (monotonic increase, no reset).
3. **EOF does not cause teardown.** When viewer count ≥ 1, producer EOF alone MUST NOT cause teardown, stop writing, or channel shutdown.
4. **Stream remains stable until last frame is rendered.** The TS stream MUST continue until the last scheduled frame has been presented; no premature stop, reconnect loops, or restarts due to EOF.
5. **Broadcast-grade switching.** E2E test: Loop SampleA (10s) → SampleB (10s) → SampleA → SampleB. VLC shows: no pause, no time reset, no mid-stream jump, audio continuous.
6. **Phase 8.6 VLC playback remains correct.** E2E with VLC and real MPEG-TS still passes; no regression.
7. **Phase 8.7 teardown semantics still hold.** Immediate teardown on viewer count 1 → 0; no background activity after teardown; no UDS reconnect attempts; baseline resource invariants.
8. **Unit, integration, and E2E tests** for LoadPreview/SwitchToLive lifecycle, encoder persistence, EOF-before-render-complete, and producer-finishes-early scenarios pass as specified above.

---

## Runtime integration note (Python / ffmpeg fallback)

When the runtime uses the **ffmpeg fallback** (e.g. Phase 0), the playout process is the ffmpeg CLI: it runs the file to EOF and then exits. The UDS write side then closes and the TS reader sees EOF. That behaviour is **expected** for the ffmpeg fallback; Phase 8.8 does not require the fallback to stay up. **Phase 8.8 behaviour (no EOF-driven stop, stream until last frame rendered) applies when the Air playout engine (C++) is used:** the producer stays running after EOF and the sink drains the buffer. Log messages in Core that mention “TS source EOF” or “ffmpeg process exited” should clarify that with the ffmpeg fallback this is expected when the file ends, and that using the Air playout engine is required for Phase 8.8.

---

## Constraints

- **DO NOT** rename classes or files as part of this phase.
- **DO NOT** modify implementation in this phase; this document is a **behavioral contract only**.
- **DO NOT** introduce new abstractions or APIs; define only correct behavior for the existing pipeline.

This document is intended to block incorrect future changes: any change that allows EOF to trigger teardown, or that ties teardown to producer exhaustion instead of renderer completion (when viewers ≥ 1), violates this contract. Additionally, any change that starts the preview producer in `LoadPreview` (instead of waiting for `SwitchToLive`), or that closes/reopens the encoder pipeline during `SwitchToLive` (instead of keeping it alive across switches), violates this contract.
