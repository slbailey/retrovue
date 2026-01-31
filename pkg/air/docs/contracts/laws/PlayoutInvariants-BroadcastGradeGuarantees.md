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

## 6. Summary Table

| Invariant | Law |
|-----------|-----|
| **Clock** | MasterClock is the only source of "now"; CT never resets once established. |
| **Timeline** | TimelineController owns CT mapping; producers are time-blind after lock. |
| **Output Liveness** | ProgramOutput never blocks; if no content → deterministic pad (black + silence). |
| **Audio Format** | Channel defines house audio format; all audio normalized before OutputBus; EncoderPipeline never negotiates format. Contract test: INV-AUDIO-HOUSE-FORMAT-001. |
| **Switching** | No gaps, no PTS regression, no silence during switches. |

---

## 7. Relationship to Other Contracts

- **Phase 8 (INV-P8-XXX):** Timeline, CT/MT, segment mapping, write barrier, and output liveness are detailed in [Phase8-Invariants-Compiled](../phases/Phase8-Invariants-Compiled.md) and [ScheduleManagerPhase8Contract](../../../../core/docs/contracts/runtime/ScheduleManagerPhase8Contract.md). This document states the broadcast-grade laws; Phase 8 contracts refine and test them.
- **Phase 9 / 10:** Bootstrap and pipeline flow control (INV-P10, etc.) must preserve these invariants. See [Phase9-OutputBootstrap](../phases/Phase9-OutputBootstrap.md) and [INV-P10-PIPELINE-FLOW-CONTROL](../phase10/INV-P10-PIPELINE-FLOW-CONTROL.md).
- **Architecture contracts:** [MasterClockContract](../architecture/MasterClockContract.md), [OutputContinuityContract](../architecture/OutputContinuityContract.md), [ProducerBusContract](../architecture/ProducerBusContract.md), [BlackFrameProducerContract](../architecture/BlackFrameProducerContract.md), and [OutputBusAndOutputSinkContract](../architecture/OutputBusAndOutputSinkContract.md) specify component-level behavior that satisfies these laws.

Implementations that violate any of these invariants are non-compliant. When in doubt, the invariant wins.
