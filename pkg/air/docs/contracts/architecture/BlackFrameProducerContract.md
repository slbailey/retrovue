# BlackFrameProducer Contract

_Related: [ProducerBus (Input Bus) Contract](ProducerBusContract.md) · [FileProducer Contract](FileProducerContract.md) · [Output Continuity](OutputContinuityContract.md) · [Playout Engine Contract](PlayoutEngineContract.md)_

**Status:** Implemented
**Scope:** Air (C++) playout engine — fallback producer for continuous valid output
**Audience:** Engine implementers, refactor tools (Cursor), future maintainers

**Authoritative definition of the output liveness law** (ProgramOutput never blocks; if no content → deterministic pad black + silence) **lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md).**

---

## 1. Purpose

Define the observable guarantees for **BlackFrameProducer** — an **internal failsafe** producer that outputs valid black video (program format) and no audio. It is used when the **live** bus’s content producer runs out of frames and Core has not yet issued the next control command. Air switches output to BlackFrameProducer **immediately** so the sink **always** receives valid output; no gaps, freezes, or invalid data. See [ProducerBusContract](ProducerBusContract.md) for the input path (preview + live buses) and the always-valid-output invariant.

**BlackFrameProducer is not content and not scheduled.** It is a **dead-man fallback** for output continuity. Core does not send segments to it, schedule it, or control it; Air selects it only when the live producer underruns. Air remains in this state indefinitely until Core explicitly reasserts control (e.g. LoadPreview + SwitchToLive). Entry into BlackFrameProducer may occur without any gRPC interaction and does not imply an error condition; it is a protective continuity state.

---

## 2. Core Definitions (Normative)

### 2.1 BlackFrameProducer

**BlackFrameProducer** is an IProducer-compatible fallback that produces:

- **Video:** Valid black frames at the PlayoutInstance’s ProgramFormat (width, height, frame rate). Frames are decoder-legal and suitable for encoding/mux; PTS/DTS advance monotonically (see [OutputContinuityContract](OutputContinuityContract.md)).
- **Audio:** No audio (silence or no audio packets, as defined by program format and sink contract).

It does **not** take segment parameters from Core (asset_path, start_offset_ms, etc.). The engine invokes it only when switching to fallback; it runs until the engine switches back to the live bus.

### 2.2 When It Is Used (dead-man failsafe)

- The **live** bus’s producer (e.g. FileProducer) runs out of frames (EOF, buffer empty, or Core has not yet issued the next control command).
- Air **immediately** enters **failsafe mode** and switches the output path to BlackFrameProducer (black frames, no audio).
- This is **dead-man behavior**: Air protects output continuity; it does **not** make a scheduling or "what comes next" decision.
- The sink continues to receive valid video (black) and no audio until Core explicitly reasserts control (e.g. LoadPreview + SwitchToLive). Air remains in failsafe indefinitely until then.

### 2.3 When It Is Not Used

- BlackFrameProducer is **not** used when the live producer has frames available.
- It is **not** loaded on the preview or live bus as a segment; it is an **internal** fallback path, not a scheduled asset.
- It does **not** participate in LoadPreview or SwitchToLive as content; the engine switches to it internally on underrun only.

---

## 3. Responsibilities (Normative)

### 3.1 BlackFrameProducer MUST

- Produce video frames that are decoder-legal (black, correct dimensions and frame rate per ProgramFormat).
- Produce no audio (or silence as required by program format and sink).
- Respect the PlayoutInstance’s ProgramFormat (width, height, frame rate).
- Advance PTS/DTS monotonically within its output (see [OutputContinuityContract](OutputContinuityContract.md)).
- Support the same lifecycle interface as other producers (start/stop or equivalent) so the engine can switch to and from it.

### 3.2 BlackFrameProducer MUST NOT

- Take direction from Core for content (no asset_path, start_offset_ms, or segment params).
- Produce anything other than black video and no audio.
- Be placed on the preview or live bus as a “segment”; it is a fallback feed, not bus content.

### 3.3 Air (Engine) MUST

- Detect when the live producer has run out of frames (no more frames available for the current segment).
- **Immediately** switch output to BlackFrameProducer when such an underrun occurs (dead-man failsafe).
- Switch back from BlackFrameProducer to the live bus **only** when Core has explicitly reasserted control (e.g. LoadPreview, SwitchToLive, UpdatePlan) and the live producer has frames ready.
- Ensure the sink never receives a gap, freeze, or invalid data; BlackFrameProducer is the **failsafe** guarantee when content is temporarily unavailable—not a scheduling or sequencing decision.

---

## 4. Invariants (Must Always Hold)

1. **BlackFrameProducer** is an **internal failsafe**, not a scheduled asset. It is used only when the **live** producer has run out of frames and Core has not yet issued the next control command.
2. Output from BlackFrameProducer is **valid black video** (program format) and **no audio**, with monotonic PTS/DTS.
3. The **sink always receives valid output**: either frames from the live producer, or frames from BlackFrameProducer (dead-man fallback). Never a gap, freeze, or invalid data. This reflects **dead-man behavior**, not scheduling logic (see [ProducerBusContract](ProducerBusContract.md) § Always-valid-output).

---

## 5. Non-Goals (Explicit)

This contract does NOT define:

- How the engine detects underrun (implementation detail).
- Exact implementation (synthetic frames vs. pre-encoded black; single instance vs. created on demand).
- Recovery or retry policy if Core never supplies new work (operational concern).
- Multi-channel or multi-instance behavior (single PlayoutInstance per channel).

---

## 6. See Also

- [ProducerBusContract](ProducerBusContract.md) — Input path (preview + live), always-valid-output invariant, fallback reference.
- [FileProducerContract](FileProducerContract.md) — Content producer contract (segment params, lifecycle).
- [OutputContinuityContract](OutputContinuityContract.md) — PTS/DTS monotonicity for all output, including black.
- [OutputBusAndOutputSinkContract](OutputBusAndOutputSinkContract.md) — Output path to sink.
