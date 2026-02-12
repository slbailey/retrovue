# ⚠️ RETIRED — Superseded by BlockPlan Architecture

**See:** [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)

This document describes legacy playlist/Phase8 execution and is no longer active.

---

# Phase 8.9 — Audio and Video Streams from Single FileProducer

_Related: [Phase Model](../PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-6 Real MPEG-TS E2E](Phase8-6-RealMpegTsE2E.md) · [Phase8-7 Immediate Teardown](Phase8-7-ImmediateTeardown.md) · [Phase8-8 Frame Lifecycle and Playout Completion](Phase8-8-FrameLifecycleAndPlayoutCompletion.md)_

**Principle:** A single FileProducer per asset decodes and emits both audio and video frames. EncoderPipeline owns video encoder, audio encoder, and TS mux. Switching swaps producers atomically; audio never influences switching or lifecycle decisions. One producer = one AV source.

---

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)).

---

## Problem Statement

The current architecture may separate audio and video decoding into distinct abstractions (e.g., separate AudioProducer and FrameProducer). This creates complexity in lifecycle management, switching coordination, and PTS synchronization. The system needs a unified model where:

- **One producer = one AV source:** Each FileProducer handles both audio and video decoding from a single asset file.
- **EncoderPipeline owns encoding:** Video encoder, audio encoder, and TS mux are all owned by EncoderPipeline, ensuring proper synchronization and PTS continuity.
- **Switching is producer-based:** SwitchToLive swaps entire producers, not individual audio/video streams. This simplifies lifecycle and ensures atomic transitions.
- **Audio is secondary:** Audio PTS is producer-relative and rescaled by EncoderPipeline, but audio never influences switching decisions or lifecycle management.

This phase defines the behavioral contract for unified audio/video producers and producer-based switching. It does **not** introduce separate AudioProducer or FrameProducer abstractions.

---

## Terminology

| Term | Definition |
|------|------------|
| **FileProducer** | A producer that decodes both video frames and audio frames from a single asset file. Outputs decoded video frames with PTS and decoded audio frames with PTS. |
| **Video frame** | A decoded video frame with PTS (producer-relative, in microseconds). |
| **Audio frame** | A decoded audio frame with PTS (producer-relative, in microseconds). |
| **EncoderPipeline** | Owns video encoder, audio encoder, and TS mux. Receives video frames and audio frames from producers, encodes them, and muxes into MPEG-TS. Responsible for PTS rescaling and synchronization. |
| **Producer-relative PTS** | PTS values emitted by FileProducer are relative to the start of that producer's asset. EncoderPipeline rescales these to the broadcast timeline. |
| **SwitchToLive** | Stops the old live FileProducer, swaps the preview FileProducer to live, and does NOT coordinate audio/video separately. The switch is atomic at the producer level. |

---

## Architecture Model

### FileProducer Responsibilities

1. **Decode video frames with PTS**  
   FileProducer reads the asset file, demuxes video packets, decodes them to raw video frames, and emits video frames with producer-relative PTS (in microseconds).

2. **Decode audio frames with PTS**  
   FileProducer reads the asset file, demuxes audio packets, decodes them to raw audio frames, and emits audio frames with producer-relative PTS (in microseconds).

3. **Unified output**  
   FileProducer outputs both video frames and audio frames. Both frame types include PTS metadata. The producer does not distinguish between audio and video for lifecycle purposes; it decodes both until EOF or stop is requested.

### EncoderPipeline Responsibilities

1. **Own video encoder**  
   EncoderPipeline creates and manages the video encoder (e.g., libx264). Receives decoded video frames from producers and encodes them.

2. **Own audio encoder**  
   EncoderPipeline creates and manages the audio encoder (e.g., libfdk_aac or aac). Receives decoded audio frames from producers and encodes them.

3. **Own TS mux**  
   EncoderPipeline creates and manages the MPEG-TS muxer (AVFormatContext). Muxes encoded video and audio packets into MPEG-TS output.

4. **PTS rescaling**  
   EncoderPipeline receives producer-relative PTS values (in microseconds) and rescales them to the broadcast timeline (90kHz for MPEG-TS). EncoderPipeline maintains PTS continuity across producer switches.

5. **Synchronization**  
   EncoderPipeline synchronizes video and audio encoding and muxing. Audio and video are muxed together into the same TS stream with proper timing.

6. **Silent padding (optional)**  
   EncoderPipeline MAY emit silence frames if audio ends early (before video) to preserve A/V continuity. This prevents audio EOF from influencing producer lifecycle.

### SwitchToLive Behavior

1. **Stop old FileProducer**  
   SwitchToLive stops the current live FileProducer (signals stop, waits for producer thread to exit, releases resources).

2. **Swap preview to live**  
   SwitchToLive atomically swaps the preview FileProducer to become the live producer. The preview producer (which was created by LoadPreview but not started) is now started and becomes the active source.

3. **No separate audio/video coordination**  
   SwitchToLive does NOT coordinate audio and video separately. It swaps the entire producer. Both audio and video from the new producer begin flowing to EncoderPipeline immediately after the swap.

4. **EncoderPipeline persists**  
   EncoderPipeline (video encoder, audio encoder, TS mux) persists across switches. It is created once per channel start and closed only on channel teardown. PTS continuity is maintained by EncoderPipeline's rescaling logic.

---

## Contract Rules

### FileProducer must decode both audio and video

1. **FileProducer MUST decode video frames with PTS.** Each video frame emitted by FileProducer MUST include a PTS value (producer-relative, in microseconds).

2. **FileProducer MUST decode audio frames with PTS.** Each audio frame emitted by FileProducer MUST include a PTS value (producer-relative, in microseconds).

3. **FileProducer MUST NOT introduce separate AudioProducer or FrameProducer abstractions.** There is no separate AudioProducer class or FrameProducer class. FileProducer handles both audio and video decoding internally.

4. **FileProducer outputs both frame types.** FileProducer emits both video frames and audio frames. The output mechanism (e.g., ring buffer, callback) accepts both types with PTS metadata.

### EncoderPipeline owns all encoding

5. **EncoderPipeline MUST own the video encoder.** EncoderPipeline creates, configures, and manages the video encoder. No other component owns or directly accesses the video encoder.

6. **EncoderPipeline MUST own the audio encoder.** EncoderPipeline creates, configures, and manages the audio encoder. No other component owns or directly accesses the audio encoder.

7. **EncoderPipeline MUST own the TS mux.** EncoderPipeline creates, configures, and manages the MPEG-TS muxer (AVFormatContext). No other component owns or directly accesses the TS mux.

8. **EncoderPipeline MUST rescale PTS.** EncoderPipeline receives producer-relative PTS values (in microseconds) from FileProducer and rescales them to the broadcast timeline (90kHz for MPEG-TS). PTS continuity across producer switches is maintained by EncoderPipeline.

### Audio never influences switching or lifecycle

9. **Audio MUST NOT influence switching decisions.** SwitchToLive decisions are based on schedule time (Core authority); video timing is an execution detail. Audio PTS, audio buffer state, or audio EOF MUST NOT trigger or delay switching.

10. **Audio MUST NOT influence lifecycle management.** Producer lifecycle (start, stop, teardown) is determined by schedule boundaries and viewer count. Audio state (EOF, buffer empty, PTS) MUST NOT influence producer lifecycle.

11. **Audio PTS is producer-relative.** Audio frames emitted by FileProducer have PTS values that are relative to the start of that producer's asset. EncoderPipeline rescales audio PTS to the broadcast timeline, independent of video PTS rescaling (though both use the same timeline).

### SwitchToLive swaps producers, not streams

12. **SwitchToLive MUST stop the old FileProducer.** When SwitchToLive is called, the current live FileProducer MUST be stopped (stop signal, thread join, resource cleanup).

13. **SwitchToLive MUST swap preview FileProducer to live.** The preview FileProducer (created by LoadPreview but not started) MUST be started and atomically swapped to become the live producer.

14. **SwitchToLive MUST NOT coordinate audio/video separately.** SwitchToLive operates at the producer level. It does NOT separately stop audio streams and video streams, or separately start new audio streams and video streams. The entire producer is swapped atomically.

15. **One producer = one AV source.** Each FileProducer instance represents one complete AV source (one asset file with both audio and video). Switching swaps from one complete AV source to another complete AV source.

### EncoderPipeline persistence

16. **EncoderPipeline persists across switches.** EncoderPipeline (video encoder, audio encoder, TS mux) is created once per channel start and persists across all producer switches. It is closed only when the channel is torn down (viewer count 0 or playout completion).

17. **PTS continuity is maintained by EncoderPipeline.** EncoderPipeline maintains PTS continuity across producer switches by rescaling producer-relative PTS values to a continuous broadcast timeline. No PTS reset, no discontinuity flags, no PAT/PMT reset.

---

## State Transitions

### Producer lifecycle

- **Idle** — FileProducer created but not started (e.g., preview producer after LoadPreview).
- **Producing** — FileProducer is decoding and emitting both video frames and audio frames.
- **Exhausted** — FileProducer has reached EOF for both audio and video; no more frames will be produced.
- **Stopped** — FileProducer has been stopped (e.g., by SwitchToLive); decode thread has exited, resources released.

### SwitchToLive sequence

1. **LoadPreview** creates preview FileProducer in Idle state (does not start it).
2. **SwitchToLive** is called at segment boundary.
3. **Stop old live producer:** Live FileProducer transitions Producing → Stopped.
4. **Start preview producer:** Preview FileProducer transitions Idle → Producing.
5. **Swap:** Preview FileProducer becomes the new live producer.
6. **EncoderPipeline continues:** EncoderPipeline receives frames from the new producer and maintains PTS continuity.

---

## Tests

### Unit tests

- **FileProducer emits both video and audio:** Create FileProducer with asset containing both audio and video. Assert that both video frames and audio frames are emitted, each with PTS metadata.
- **FileProducer handles audio-only or video-only assets:** Create FileProducer with asset containing only video (no audio) or only audio (no video). Assert that FileProducer handles missing streams gracefully (emits available frames, does not crash).
- **EncoderPipeline owns all encoders:** Create EncoderPipeline and assert that it creates video encoder, audio encoder, and TS mux. Assert that no other component has direct access to these encoders.
- **EncoderPipeline rescales PTS:** Feed EncoderPipeline frames with producer-relative PTS (microseconds). Assert that encoded packets have PTS in 90kHz units, and that PTS values are continuous across producer switches (simulated).

### Integration tests

- **SwitchToLive swaps producers:** Run LoadPreview → SwitchToLive sequence. Assert that old producer stops, preview producer starts, and both audio and video frames flow from new producer to EncoderPipeline.
- **EncoderPipeline persists across switches:** Perform multiple SwitchToLive operations. Assert that EncoderPipeline (video encoder, audio encoder, TS mux) is not closed/reopened. Assert PTS continuity in encoded output.
- **Audio does not influence switching:** Simulate audio EOF or audio buffer empty conditions. Assert that SwitchToLive is not triggered or delayed by audio state. Assert that switching occurs based on schedule time (Core authority) only.
- **Producer-relative PTS rescaling:** Feed frames from two different producers (different assets) with overlapping producer-relative PTS ranges. Assert that EncoderPipeline rescales both to continuous broadcast timeline (no PTS collision, no reset).

### E2E test expectations

- **VLC plays audio and video:** E2E test with VLC: StartChannel → LoadPreview → AttachStream → SwitchToLive. VLC plays both video and audio from the stream. Audio and video are synchronized.
- **Switching maintains audio/video sync:** E2E test with multiple segments: Loop SampleA (10s) → SampleB (10s) → SampleA. VLC shows: no audio dropouts, no video glitches, audio and video remain synchronized across switches.
- **Phase 8.6–8.8 expectations still hold:** All Phase 8.6 (real MPEG-TS E2E), Phase 8.7 (immediate teardown), and Phase 8.8 (frame lifecycle) expectations continue to pass. Audio addition does not regress existing behavior.

---

## Non-Goals

- **No separate AudioProducer or FrameProducer abstractions.** This contract does not require or define separate AudioProducer or FrameProducer classes. FileProducer handles both audio and video internally.
- **No audio-driven switching.** Audio state (EOF, buffer empty, PTS) does not trigger or delay switching. Switching is driven by schedule time (Core authority).
- **No audio lifecycle management.** Audio does not have separate lifecycle from video. Producer lifecycle (start, stop, teardown) is determined by schedule boundaries and viewer count.
- **No performance tuning.** Throughput, latency, or buffer sizing optimizations for audio are out of scope.
- **No audio format conversion beyond encoding.** FileProducer decodes audio to a standard format (e.g., PCM); EncoderPipeline encodes to target format (e.g., AAC). No additional format conversion or resampling beyond what is necessary for encoding.

---

## Exit Criteria

1. **FileProducer decodes both audio and video.** FileProducer emits both video frames with PTS and audio frames with PTS from a single asset file.
2. **EncoderPipeline owns all encoding.** EncoderPipeline creates and manages video encoder, audio encoder, and TS mux. No other component has direct access to these encoders.
3. **SwitchToLive swaps producers atomically.** SwitchToLive stops old FileProducer and swaps preview FileProducer to live. It does NOT coordinate audio/video separately.
4. **Audio never influences switching or lifecycle.** Audio PTS, audio buffer state, or audio EOF does not trigger or delay switching. Producer lifecycle is determined by schedule boundaries and viewer count.
5. **PTS rescaling works correctly.** EncoderPipeline rescales producer-relative PTS (microseconds) to broadcast timeline (90kHz). PTS continuity is maintained across producer switches.
6. **E2E with audio and video.** VLC plays both audio and video from the stream. Audio and video are synchronized. Switching maintains audio/video sync.
7. **Phase 8.6–8.8 tests still pass.** All existing Phase 8.6, 8.7, and 8.8 tests continue to pass. Audio addition does not regress existing behavior.
8. **Unit, integration, and E2E tests** for FileProducer audio/video decoding, EncoderPipeline encoder ownership, SwitchToLive producer swapping, and audio non-influence on switching/lifecycle pass as specified above.

---

## Constraints

- **DO NOT** introduce separate AudioProducer or FrameProducer abstractions. FileProducer handles both audio and video internally.
- **DO NOT** allow audio to influence switching decisions or lifecycle management. Audio is secondary to video for these purposes.
- **DO NOT** coordinate audio and video separately in SwitchToLive. SwitchToLive operates at the producer level.
- **DO NOT** close/reopen EncoderPipeline during SwitchToLive. EncoderPipeline persists across switches and is closed only on channel teardown.

This document is intended to block incorrect future changes: any change that introduces separate AudioProducer or FrameProducer abstractions, that allows audio to influence switching or lifecycle, that coordinates audio/video separately in SwitchToLive, or that closes/reopens EncoderPipeline during switches violates this contract.
