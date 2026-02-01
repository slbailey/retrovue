# Playout Invariants (Broadcast-Grade Guarantees)

**Status:** Canonical  
**Scope:** AIR playout engine — non-negotiable laws  
**Audience:** Implementers, contract authors, reviewers

These invariants are **laws**, not implementation notes. They define the broadcast-grade guarantees that the playout system must uphold. Violations are design faults; implementations must conform.

_Related: [Phase 8 Invariants Compiled](../phases/Phase8-Invariants-Compiled.md) · [Air Architecture Reference](../AirArchitectureReference.md) · [ProducerBus Contract](../architecture/ProducerBusContract.md) · [Output Continuity](../architecture/OutputContinuityContract.md) · [BlackFrameProducer](../architecture/BlackFrameProducerContract.md)_

---

## 1. Clock Invariant

**MasterClock is the only source of "now".**

- No component other than MasterClock may define or supply wall-clock "now" for playout decisions.
- Pacing, scheduling, and deadline checks use MasterClock (or values derived from it). No ad-hoc `std::chrono` or system clock for timeline authority.
- Epoch is established once per session and is immutable (INV-P8-005).

**CT never resets once established.**

- Channel time (CT) advances monotonically for the lifetime of the session.
- CT does not wrap, jump backward, or reset on segment switch. Segment mapping assigns CT from a continuous timeline (CT_cursor + mapping).
- Underrun may pause CT advancement; when frames resume, CT continues from the last assigned value. No reset.

---

## 2. Timeline Invariant

**TimelineController owns CT mapping.**

- Only TimelineController assigns CT to frames. Producers emit media time (MT) only; CT appears only after admission (INV-P8-001).
- Segment boundaries (BeginSegmentFromPreview, BeginSegmentAbsolute) are defined by TimelineController. First admitted frame in a segment locks both CT_start and MT_start for that segment (INV-P8-SWITCH-002).
- No other component may write, compute, or influence CT. No producer, buffer, or sink may assign or modify CT.

**Producers are time-blind after lock.**

- Once TimelineController is active and segment mapping is locked, producers do not make timing or sequencing decisions. They do not compare MT to target_pts for suppression, delay emission for alignment, or gate audio on video PTS (INV-P8-TIME-BLINDNESS).
- All timeline-based admission decisions belong to TimelineController's admission window. Producers decode and submit frames; they do not own "when" something airs.

---

## 3. Output Liveness Invariant

**ProgramOutput never blocks.**

- The output path from buffer to OutputBus/OutputSink must not deadlock. ProgramOutput consumes the active buffer and delivers frames (or deterministic pad) to the sink. Blocking the output thread is forbidden.
- Backpressure is handled at the producer (decode) side or at the buffer boundary, not by blocking ProgramOutput indefinitely.

**If no content → deterministic pad video + silence.**

- When the live producer has no frames (EOF, underrun, or Core has not yet commanded the next action), the sink must still receive valid output. Air switches to a deterministic fallback: black video (program format) and silence (no audio)—BlackFrameProducer or equivalent (dead-man failsafe).
- Silence is emitted in the channel's house audio format (sample rate, channel count, sample format), exactly matching normal program audio timing.
- No gaps, no freezes, no invalid data. The fallback is not content and not scheduled; it is a continuity guarantee until Core reasserts control.
- "No content" does not mean "no output." Output liveness is non-negotiable (INV-P8-OUTPUT-001).

---

## 4. Audio Format Invariant

**Channel defines house audio format.**

- The channel's program format (sample rate, channel layout, sample format) is the single source of truth for audio. It is established at session start (e.g. StartChannel / ProgramFormat) and does not change for the lifetime of the session.
- All audio delivered to the output path conforms to this house format.

**All audio is normalized before OutputBus.**

- Any producer or upstream stage that emits audio must output in the house format (or a stage before OutputBus must normalize to it). OutputBus and downstream components assume normalized input; they do not resample or reformat per-stream.
- Normalization (if needed) is a defined step before frames reach OutputBus. EncoderPipeline and the muxer receive only house-format audio.
- Normalization is conceptually part of the Air playout path, not the encoder. Whether implemented in producers, a dedicated AudioNormalizer stage, or ProgramOutput is an implementation choice, but the invariant is that OutputBus only ever sees house-format audio.

**EncoderPipeline never negotiates format.**

- EncoderPipeline does not discover, negotiate, or adapt to arbitrary input formats. It encodes the program format it is configured with. If input does not match that format, the failure is explicit (e.g. reject or error), not silent adaptation.
- Format authority stays with the channel/session; the encoder is a consumer of a fixed contract.

**Contract test: INV-AUDIO-HOUSE-FORMAT-001**

- All audio reaching EncoderPipeline (including pad/silence) must be in house format. The contract test **INV-AUDIO-HOUSE-FORMAT-001** verifies that the pipeline rejects or fails loudly on non–house-format input and that pad audio uses the same path, CT, sample cadence, and format as program audio. (Test may be stubbed initially.)

---

## 5. Switching Invariant

**No gaps, no PTS regression, no silence during switches.**

- **No gaps:** The output stream has no missing frames or packets at the switch boundary. Continuity counters and PTS/DTS advance without discontinuity (or any discontinuity is explicit and spec-compliant).
- **No PTS regression:** PTS/DTS never decrease across the switch. The segment mapping (INV-P8-SWITCH-002) ensures the first preview frame locks CT and MT together; subsequent frames continue from that point. TimelineController guarantees monotonic CT (INV-P8-002).
- **No silence during switches:** The switch is seamless at the frame boundary. Preview is primed (shadow decode, then buffer fill) before promotion; the first frame from the new segment follows the last frame from the old segment without inserting silence or black beyond at most one acceptable frame if specified.
- Switching is Core-commanded (SwitchToLive). Air does not switch autonomously except dead-man fallback (live underrun → BlackFrameProducer). Write barrier applies only to the producer being phased out; the producer required for switch readiness must be allowed to write until readiness is achieved.

---

## 6. Video Decodability Invariant

**Every segment starts with a decodable keyframe (IDR).**

- AIR is responsible for media decodability: keyframes, SPS/PPS, IDR presence.
- CORE is NOT responsible for keyframes. Keyframe enforcement is an AIR concern.
- Safety rails (pad/black frames) are NOT a continuity mechanism for decodability.

**INV-AIR-IDR-BEFORE-OUTPUT: IDR gate at segment start.**

- AIR must not emit any video packets for a segment until an IDR frame has been produced by the encoder for that segment.
- The gate blocks all video output until `avcodec_receive_packet()` returns a packet with `AV_PKT_FLAG_KEY` set.
- The gate resets on segment switch (via `ResetOutputTiming()`).
- Audio may be buffered but is not muxed until the video IDR gate opens.

**Why this is required:**

- Segments may start and end quickly (1-2 frames).
- Even with `pict_type = AV_PICTURE_TYPE_I` (requesting I-frame), the encoder may buffer frames.
- Without the gate, non-IDR packets could be emitted before the first keyframe.
- VLC and other players cannot decode until they receive an IDR frame with SPS/PPS.

**Enforcement:**

- EncoderPipeline tracks `first_keyframe_emitted_` per segment.
- On `avcodec_receive_packet()` success, if `first_keyframe_emitted_ == false`:
  - If `packet_->flags & AV_PKT_FLAG_KEY`: set `first_keyframe_emitted_ = true`, proceed.
  - Else: log violation, discard packet, continue.
- On segment switch (`ResetOutputTiming()`): reset `first_keyframe_emitted_ = false`.

**Violation log (only on block):**

```
[AIR] INV-AIR-IDR-BEFORE-OUTPUT: BLOCKING output (waiting_for_idr=true)
```

**INV-AIR-CONTENT-BEFORE-PAD: Real content gates pad emission.**

- Pad frames may ONLY be emitted AFTER at least one real decoded content frame
  has been successfully routed to output.
- This ensures VLC receives decodable content (with IDR/SPS/PPS) FIRST, before
  any pad frames which may lack keyframe treatment.
- ProgramOutput tracks `first_real_frame_emitted_` flag:
  - If false: skip pad emission, wait for real content
  - If true: pad frames allowed (normal safety rail behavior)

**Evidence that justified this invariant:**

```
[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad frame #1 at PTS=0us reason=BUFFER_TRULY_EMPTY
```

This log appeared BEFORE any real content frames, causing VLC to display nothing.
The pad frames lacked proper decoder initialization (IDR/SPS/PPS), and VLC
could not recover once the stream started with non-decodable frames.

**Enforcement:**

- ProgramOutput: If `Pop(frame)` fails AND `!first_real_frame_emitted_`:
  - Do NOT emit pad frame
  - Brief yield (1ms) and continue loop
  - Log waiting status periodically
- ProgramOutput: After routing first real frame:
  - Set `first_real_frame_emitted_ = true`
  - Log that pad frames are now allowed

**Relationship to INV-AIR-IDR-BEFORE-OUTPUT:**

These two invariants work together:
1. **INV-AIR-CONTENT-BEFORE-PAD**: Ensures first frame to encoder is real content (not pad)
2. **INV-AIR-IDR-BEFORE-OUTPUT**: Ensures first encoded packet is IDR (not P/B frame)

Together they guarantee VLC receives a decodable stream from the start.

---

## 7. Frame Execution Invariant

**Frame index is execution authority; CT is time authority.**

Playout execution is frame-addressed. Segments are bounded by frame counts, not durations. CT is derived from frame index, never the inverse. This enables frame-accurate editorial cuts and deterministic padding.

**INV-FRAME-001: Segment boundaries are frame-indexed.**

- Segments are defined by `start_frame` and `frame_count`, not start/end times.
- Duration is derived: `duration = frame_count / fps`
- Time-to-frame conversion happens once, at schedule generation (Core), not at execution (Air).

**INV-FRAME-002: Padding is expressed in frames.**

- Padding quantity is a frame count, never a duration.
- Core computes: `padding_frames = grid_frames - content_frames`
- Air executes: exactly `padding_frames` black frames.
- No rounding, estimation, or adaptive adjustment at execution time.

**INV-FRAME-003: CT derives from frame index.**

- Given epoch CT and frame index, CT is computed:
  ```
  ct_us = epoch_ct_us + (frame_index * 1_000_000 * fps.denominator) / fps.numerator
  ```
- Frame index is the execution cursor; CT is the timestamp assigned to that cursor position.
- Air never reads CT and converts to frame index. The direction is always: frame → CT → PTS.

**Relationship to Clock Invariant:**

CT remains the sole time authority (Section 1). Frame index is not a competing time source—it is the discrete execution cursor from which CT is derived. MasterClock owns epoch and "now"; TimelineController maps frame index to CT.

**Structural padding vs failsafe padding:**

- **Structural padding:** Core-planned frame count for grid reconciliation. Bounded, deterministic, part of the playout plan.
- **Failsafe padding:** Air-initiated when producer underruns (BlackFrameProducer). Unbounded, defensive, not part of the plan.

Both emit black + silence. The distinction is control: structural padding is Core intent executed by Air; failsafe is Air's protective continuity behavior.

---

## 8. Summary Table

| Invariant | Law |
|-----------|-----|
| **Clock** | MasterClock is the only source of "now"; CT never resets once established. |
| **Timeline** | TimelineController owns CT mapping; producers are time-blind after lock. |
| **Output Liveness** | ProgramOutput never blocks; if no content → deterministic pad (black + silence). |
| **Audio Format** | Channel defines house audio format; all audio normalized before OutputBus; EncoderPipeline never negotiates format. Contract test: INV-AUDIO-HOUSE-FORMAT-001. |
| **Switching** | No gaps, no PTS regression, no silence during switches. |
| **Video Decodability** | Every segment starts with IDR; AIR gates output until keyframe emitted; real content must precede pad frames. Contract tests: INV-AIR-IDR-BEFORE-OUTPUT, INV-AIR-CONTENT-BEFORE-PAD. |
| **Frame Execution** | Frame index is execution authority; CT derives from frame index (INV-FRAME-001/002/003). |

---

## 9. Relationship to Other Contracts

- **Phase 8 (INV-P8-XXX):** Timeline, CT/MT, segment mapping, write barrier, and output liveness are detailed in [Phase8-Invariants-Compiled](../phases/Phase8-Invariants-Compiled.md) and [ScheduleManagerPhase8Contract](../../../../core/docs/contracts/runtime/ScheduleManagerPhase8Contract.md). This document states the broadcast-grade laws; Phase 8 contracts refine and test them.
- **Phase 9 / 10:** Bootstrap and pipeline flow control (INV-P10, etc.) must preserve these invariants. See [Phase9-OutputBootstrap](../phases/Phase9-OutputBootstrap.md) and [INV-P10-PIPELINE-FLOW-CONTROL](../phase10/INV-P10-PIPELINE-FLOW-CONTROL.md).
- **Architecture contracts:** [MasterClockContract](../architecture/MasterClockContract.md), [OutputContinuityContract](../architecture/OutputContinuityContract.md), [ProducerBusContract](../architecture/ProducerBusContract.md), [BlackFrameProducerContract](../architecture/BlackFrameProducerContract.md), and [OutputBusAndOutputSinkContract](../architecture/OutputBusAndOutputSinkContract.md) specify component-level behavior that satisfies these laws.

Implementations that violate any of these invariants are non-compliant. When in doubt, the invariant wins.
