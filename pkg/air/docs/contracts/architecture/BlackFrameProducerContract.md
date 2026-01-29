# BlackFrameProducer Contract

_Related: [ProducerBus (Input Bus) Contract](ProducerBusContract.md) · [FileProducer Contract](FileProducerContract.md) · [Output Continuity](OutputContinuityContract.md) · [Playout Engine Contract](PlayoutEngineContract.md)_

**Status:** Design (pre-implementation)  
**Scope:** Air (C++) playout engine — fallback producer for continuous valid output  
**Audience:** Engine implementers, refactor tools (Cursor), future maintainers

---

## 1. Purpose

Define the observable guarantees for **BlackFrameProducer** — a fallback producer that outputs valid black video (program format) and no audio. It is used when the **live** bus’s content producer runs out of frames and Core has not yet supplied the next segment. Air switches to BlackFrameProducer **immediately** so the sink **always** receives valid output; no gaps, freezes, or invalid data. See [ProducerBusContract](ProducerBusContract.md) for the input path (preview + live buses) and the always-valid-output invariant.

**BlackFrameProducer is not content.** It is a continuity guarantee. Core does not send segments to it; Air selects it only when the live producer underruns.

---

## 2. Core Definitions (Normative)

### 2.1 BlackFrameProducer

**BlackFrameProducer** is an IProducer-compatible fallback that produces:

- **Video:** Valid black frames at the PlayoutInstance’s ProgramFormat (width, height, frame rate). Frames are decoder-legal and suitable for encoding/mux; PTS/DTS advance monotonically (see [OutputContinuityContract](OutputContinuityContract.md)).
- **Audio:** No audio (silence or no audio packets, as defined by program format and sink contract).

It does **not** take segment parameters from Core (asset_path, start_offset_ms, etc.). The engine invokes it only when switching to fallback; it runs until the engine switches back to the live bus.

### 2.2 When It Is Used

- The **live** bus’s producer (e.g. FileProducer) runs out of frames (EOF, buffer empty, or Core has not yet sent LoadPreview/UpdatePlan for the next segment).
- Air **immediately** switches the output path to BlackFrameProducer (or equivalent feed: black frames, no audio).
- The sink continues to receive valid video (black) and no audio until Core supplies new work and Air switches back to the live bus (with the new producer).

### 2.3 When It Is Not Used

- BlackFrameProducer is **not** used when the live producer has frames available.
- It is **not** loaded on the preview or live bus as a segment; it is a separate fallback path.
- It does **not** participate in LoadPreview or SwitchToLive as content; the engine switches to it internally on underrun.

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
- **Immediately** switch output to BlackFrameProducer when such an underrun occurs.
- Switch back from BlackFrameProducer to the live bus when Core has supplied new work (LoadPreview, SwitchToLive, UpdatePlan) and the live producer has frames ready.
- Ensure the sink never receives a gap, freeze, or invalid data; BlackFrameProducer is the guarantee when content is temporarily unavailable.

---

## 4. Invariants (Must Always Hold)

1. **BlackFrameProducer** is used only when the **live** producer has run out of frames and Core has not yet supplied the next segment.
2. Output from BlackFrameProducer is **valid black video** (program format) and **no audio**, with monotonic PTS/DTS.
3. The **sink always receives valid output**: either frames from the live producer, or frames from BlackFrameProducer. Never a gap, freeze, or invalid data (see [ProducerBusContract](ProducerBusContract.md) § Always-valid-output).

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
