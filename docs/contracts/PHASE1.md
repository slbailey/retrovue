# Phase 1 – Prevent Black/Silence

**Document Type:** Architectural Contract  
**Status:** Complete (2026-02-01)  
**Laws:** LAW-OUTPUT-LIVENESS, LAW-VIDEO-DECODABILITY, LAW-AUDIO-FORMAT  
**Prerequisites:** None (foundation phase)  
**Referenced by:** Phase 8 (Timeline Semantics), Phase 11 (Broadcast-Grade Timing), Phase 12 (Live Session Authority)

---

## 1. Purpose

### 1.1 Why Phase 1 Exists

Phase 1 defines and enforces the rules that **prevent viewer-visible black or silence**. It establishes:

- **Output liveness:** The output path never blocks indefinitely; if there is no content, the system emits deterministic pad (black video + silence) within a bounded time.
- **Content-before-pad:** Pad frames are only emitted *after* the first real decoded content frame has been routed to output. This prevents a pad-only loop with no escape.
- **Video decodability:** Every segment starts with an IDR (keyframe); AIR does not emit video packets until an IDR is produced; the gate resets on segment switch so tune-in always sees a decodable stream.
- **Audio and format discipline:** House audio format is enforced at the encoder; non-house format is rejected. No B-frames in encoder output to avoid decoder stalls on missing references.
- **Bootstrap and emission liveness:** When a sink is attached, decodable TS is emitted within a bounded time (e.g. 500ms). Audio is queued within a bounded time of video epoch so the mux can emit TS. Zero-frame segments bypass the content gate so the system does not deadlock waiting for an impossible frame.

Phase 1 is the foundation: without it, viewers see black screens, silence, garbage frames on tune-in, or indefinite freezes. Later phases (8, 11, 12) build on this by adding timeline semantics, authority hierarchy, and lifecycle authority.

### 1.2 What Class of Failures This Prevents

Without Phase 1 discipline, you get:

- **Black screen:** Output blocks; no pad when buffer is empty; viewer sees nothing.
- **Pad loop with no escape:** Pad emitted before any real content; content-before-pad gate never opens; deadlock.
- **Garbage on tune-in:** Video packets emitted before IDR; decoder cannot decode until next keyframe.
- **Indefinite freeze:** Buffer starvation not handled; no bounded-time pad; crash or hang.
- **Frames lost before sink:** Frames consumed when no sink attached; viewer sees gap when they connect.
- **Zero-frame deadlock:** Segment with frame_count=0; system waits for a frame that never comes; CONTENT-BEFORE-PAD gate never opens without INV-P8-ZERO-FRAME-BOOTSTRAP.
- **Encoder/audio failure:** Non-house audio format accepted; B-frames in output; decoder or encoder failure.
- **Viewer waits 5+ seconds:** No TS bytes within 500ms of PCR-PACE init; bootstrap liveness violated.
- **Mux blocked:** Audio not queued within 100ms of video epoch; mux cannot emit TS; no bytes flow.

Phase 1 eliminates these through LAW-OUTPUT-LIVENESS, INV-AIR-CONTENT-BEFORE-PAD, INV-AIR-IDR-BEFORE-OUTPUT, LAW-VIDEO-DECODABILITY, INV-STARVATION-FAILSAFE-001, INV-P10-SINK-GATE, INV-P8-ZERO-FRAME-BOOTSTRAP, INV-P9-TS-EMISSION-LIVENESS, INV-P10-AUDIO-VIDEO-GATE, LAW-AUDIO-FORMAT, INV-AUDIO-HOUSE-FORMAT-001, and INV-ENCODER-NO-B-FRAMES-001.

---

## 2. Terminology

**Pad:**  
Synthetic black video and/or silence emitted when there is no real content to output. Used to satisfy LAW-OUTPUT-LIVENESS (never block). Must only be emitted *after* the first real content frame (INV-AIR-CONTENT-BEFORE-PAD).

**Content-before-pad:**  
The rule that pad frames are only allowed after the first decoded content frame has been routed to output. Prevents a pad-only loop. INV-AIR-CONTENT-BEFORE-PAD. Bypassed for zero-frame segments (INV-P8-ZERO-FRAME-BOOTSTRAP).

**IDR (Instantaneous Decoder Refresh):**  
Keyframe that allows a decoder to start decoding without reference to prior frames. INV-AIR-IDR-BEFORE-OUTPUT: no video packets until IDR produced; gate resets on segment switch. LAW-VIDEO-DECODABILITY: every segment starts with IDR; TS valid (e.g. 0x47 sync, 188-byte packets).

**House format:**  
The single audio format (e.g. sample rate, channels) that the encoder accepts. LAW-AUDIO-FORMAT; INV-AUDIO-HOUSE-FORMAT-001: reject non-house audio at encoder.

**Sink gate:**  
No frame is consumed from the output buffer when no sink is attached. INV-P10-SINK-GATE. Prevents frames from being lost before a viewer connects.

**Starvation failsafe:**  
When the buffer is empty (starvation detected), pad must be emitted within a bounded time (e.g. 100ms). INV-STARVATION-FAILSAFE-001. Prevents indefinite freeze.

**Bootstrap liveness:**  
When a sink is newly attached, decodable TS must be emitted within a bounded time. INV-P9-BOOT-LIVENESS, INV-P9-TS-EMISSION-LIVENESS (e.g. first TS within 500ms of PCR-PACE init). INV-P9-BOOTSTRAP-READY: readiness = commit + ≥1 video frame.

**Zero-frame bootstrap:**  
When a segment has frame_count=0 (or no_content_segment=true), the content-before-pad gate is bypassed so the system does not deadlock waiting for a frame that will never come. INV-P8-ZERO-FRAME-BOOTSTRAP.

**Audio-video gate:**  
The mux needs both video and audio to emit valid TS. INV-P10-AUDIO-VIDEO-GATE: the first audio frame must be queued within a bounded time (e.g. 100ms) of VIDEO_EPOCH_SET so the mux is not blocked.

---

## 3. Scope (Subsystems)

Phase 1 rules are enforced across AIR subsystems:

| Subsystem           | Phase 1 focus |
|---------------------|----------------|
| **ProgramOutput**   | LAW-OUTPUT-LIVENESS; INV-AIR-CONTENT-BEFORE-PAD; INV-STARVATION-FAILSAFE-001; INV-P10-SINK-GATE |
| **EncoderPipeline** | LAW-AUDIO-FORMAT; INV-AUDIO-HOUSE-FORMAT-001; INV-ENCODER-NO-B-FRAMES-001; INV-AIR-IDR-BEFORE-OUTPUT |
| **MpegTSOutputSink**| INV-P9-BOOT-LIVENESS; INV-P9-AUDIO-LIVENESS; LAW-VIDEO-DECODABILITY; INV-P9-TS-EMISSION-LIVENESS |
| **PlayoutEngine**   | INV-P8-ZERO-FRAME-BOOTSTRAP; INV-P9-BOOTSTRAP-READY |
| **FileProducer**    | INV-P10-AUDIO-VIDEO-GATE (first audio within 100ms of VIDEO_EPOCH_SET) |

Canonical definitions and enforcement status are in **CANONICAL_RULE_LEDGER**. Task-level implementation is in **PHASE1_TASKS.md** and **PHASE1_EXECUTION_PLAN.md**.

---

## 4. Invariants Summary (Phase 1)

### 4.1 Output Liveness (ProgramOutput)

| Rule ID | One-Line Definition |
|---------|----------------------|
| LAW-OUTPUT-LIVENESS | ProgramOutput never blocks; if no content → deterministic pad (black + silence) |
| INV-AIR-CONTENT-BEFORE-PAD | Pad frames only after first real decoded content frame routed to output |
| INV-STARVATION-FAILSAFE-001 | Pad emitted within bounded time (e.g. 100ms) of buffer starvation detection |
| INV-P10-SINK-GATE | Frame not consumed when no sink attached; no consumption before sink attached |

### 4.2 Video Decodability (EncoderPipeline, MpegTSOutputSink)

| Rule ID | One-Line Definition |
|---------|----------------------|
| LAW-VIDEO-DECODABILITY | Every segment starts with IDR; real content gates pad; AIR owns keyframes; TS valid (0x47 sync, 188-byte packets) |
| INV-AIR-IDR-BEFORE-OUTPUT | AIR must not emit video packets until IDR produced; gate resets on switch |

### 4.3 Audio and Encoder Format (EncoderPipeline)

| Rule ID | One-Line Definition |
|---------|----------------------|
| LAW-AUDIO-FORMAT | House audio format enforced at encoder |
| INV-AUDIO-HOUSE-FORMAT-001 | Reject non-house audio (e.g. sample_rate != house_sample_rate) |
| INV-ENCODER-NO-B-FRAMES-001 | No B-frames in encoder output; decoder must not see missing reference frames |

### 4.4 Bootstrap and Emission Liveness (MpegTSOutputSink, PlayoutEngine)

| Rule ID | One-Line Definition |
|---------|----------------------|
| INV-P9-BOOT-LIVENESS | First decodable TS emitted when sink attached; observable latency |
| INV-P9-AUDIO-LIVENESS | Audio stream liveness (first_audio_pts, header write time) |
| INV-P9-TS-EMISSION-LIVENESS | First TS bytes within bounded time (e.g. 500ms) of PCR-PACE init |
| INV-P9-BOOTSTRAP-READY | Readiness = commit + ≥1 video frame |
| INV-P8-ZERO-FRAME-BOOTSTRAP | When no_content_segment=true (or frame_count=0), bypass CONTENT-BEFORE-PAD gate |

### 4.5 Audio-Video Gate (FileProducer)

| Rule ID | One-Line Definition |
|---------|----------------------|
| INV-P10-AUDIO-VIDEO-GATE | First audio frame queued within bounded time (e.g. 100ms) of VIDEO_EPOCH_SET so mux can emit TS |

---

## 5. Relationship to Later Phases

- **Phase 8 (Timeline Semantics):**  
  Builds on Phase 1 liveness and content-before-pad. Phase 8 defines CT, write barriers, legacy preload RPC/legacy switch RPC, and segment commit. Phase 1 ensures that when Phase 8 runs, output never goes black or silent and tune-in is always decodable.

- **Phase 11 (Broadcast-Grade Timing & Authority Hierarchy):**  
  Cites Phase 1 as prerequisite. Phase 11 adds clock authority, boundary lifecycle, and deadline enforcement; Phase 1 remains the guarantee that output is always liveness- and decodability-compliant.

- **Phase 12 (Live Session Authority & Teardown):**  
  Cites Phase 1 as independent prerequisite. Phase 12 defines who may tear down a channel and when; Phase 1 defines what viewers must never see (black/silence) regardless of lifecycle state.

Phase 1 does not define timeline, boundary state, or teardown; those are Phase 8, 11F, and 12. Code and docs that say “Phase 1” in the context of prevent black/silence, content-before-pad, IDR, house format, or bootstrap liveness refer to this contract.

---

## 6. Document References

| Document | Relationship |
|----------|--------------|
| **CANONICAL_RULE_LEDGER.md** | Authoritative list of all Phase 1 laws and invariants; enforcement and test status |
| **PHASE1_TASKS.md** | Phase 1 atomic task list and checklists (P1-PO-*, P1-EP-*, P1-MS-*, P1-PE-*, P1-FP-*) |
| **PHASE1_EXECUTION_PLAN.md** | Phase 1 execution plan; tests and logs added; completion criteria |
| **ENFORCEMENT_ROADMAP.md** | Phase 1 justification (“Prevent Black/Silence”) and rule list |
| **PHASE8.md** | Timeline semantics; builds on Phase 1 liveness and content-before-pad |
| **PHASE11.md** | Broadcast-grade timing; prerequisite Phase 1 |
| **PHASE12.md** | Live session authority; prerequisite Phase 1 |
