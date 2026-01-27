# Phase 8.1.5 — VideoFileProducer Internal Decode Refactor (LIBAV)

**Purpose**  
Redesign `VideoFileProducer` so that all media demuxing, decoding, and frame emission are handled _entirely in-process_ via the libav* family of libraries (libavformat, libavcodec, libavutil)—**never** by spawning an ffmpeg executable. The public/observable behavior (single contiguous file playback, no asset switching) must remain unchanged from Phase 8.1, as seen by the pipeline and downstream code.

This refactor is specifically to unlock the frame-accurate segment boundaries and control needed for advanced broadcast playout, while improving reliability and testability.

---

## Core Requirements & Invariants

- **No ffmpeg processes or external decode.**
    - Absolutely _no_ fork/exec/spawn/piping to ffmpeg or other media tools.
- **No keyframe-based hacks.**
    - Frame emission must be _deterministic_ and truly sequential, not dependent on keyframes or seeking heuristics.
- **All decode is in-library.**
    - Use libavformat for container/demux, libavcodec for decode, libavutil for time/PTSmath.
    - The decode pipeline must be _wholly_ in C++ and resident in the Producer.
- **Precise frame and time bookkeeping.**
    - Track both container packet index, decoded frame index, and mapping of PTS to output frame.
- **Producer drives the timeline.**
    - Emission is under Producer’s control: output a frame only when told; stop at exact frame N; pause/resume; etc.

---

## Implementation Details

### Decode Pipeline

- **Resource Lifetime:**  
  - Asset file is opened and libav* contexts are initialized once per Producer lifetime (`start()`).
- **State Tracking:**  
  - Maintain:
    - Current packet index (from demux).
    - Current decoded frame index.
    - PTS-to-frame mapping.
    - Optional: buffer N decoded frames ahead.
- **Frame Granularity:**  
  - Output _frames_ (to ring buffer/downstream), _not_ bytes or codecs’ raw output.

### Frame Emission Semantics

- **Determinism:**  
  - Frames must always be delivered in decode/display order.
  - No skipped, repeated, or “glitch” frames.
- **Precise Control:**  
  - Emission is producer-driven and deterministic.
  - Frames are emitted in decode order under explicit producer control.
  - No wall-clock pacing or real-time synchronization is required in Phase 8.1.5.
  - Must be possible to issue `stop()` and guarantee _no more than N_ frames are output.
  - Must be possible to pause, then resume exactly at N+1.
- **Start/Stop:**  
  - On `start()`, first frame emitted _must_ be frame 0 (even if not a keyframe).
  - No seeking (that’s future work); always decode from start.
  - On `stop()`, all emission immediately halts; decoder is drained and closed; _no_ lingering threads.

### Audio (8.1.5 scope)

- Audio frames must be decoded and emitted in-order alongside video frames.
- No A/V synchronization guarantees are required in Phase 8.1.5.
- Audio frames may be tagged, buffered, or stubbed, but must not be silently dropped.
- Full A/V sync and continuity are deferred to later phases.

---

## Out of Scope (for 8.1.5)

- No segment switching
- No preview/live jumping
- No seek/start_offset/hard_stop logic
- No MPEG-TS muxing: Producer emits decoded frames; TS encapsulation is stubbed or handled by another component
- No HTTP streaming or fanout changes
- No effort to ensure/lossless PTS continuity for downstream
- VLC and TS packet validation are not test requirements

---

## Testing Requirements

### Automated tests (required)

- **Decode test:**  
  - Open a known MP4 file.
  - Decode _N_ frames.
  - _Assert:_
    - Number of frames output matches expectation
    - PTS values are monotonically increasing
    - No dropped/skipped frames

- **Stop test:**  
  - Start decoding a file.
  - Issue `stop()` after K frames.
  - _Assert:_
    - Exactly K frames were emitted, no more

- **Restart test:**  
  - Start → stop → destroy Producer → start again.
  - _Assert:_
    - No crashes, leaks, or thread zombies
    - All libav and internal contexts freed properly

#### Forbidden Test Patterns

- **Do NOT require:**  
  - VLC playback
  - HTTP streaming/serving
  - MPEG-TS encapsulation or packet counting
  - ffmpeg executable presence/availability

---

## Exit Criteria

- `VideoFileProducer` uses _only_ libav* code for all demux and decode
- Frame emission and advancing are 100% deterministically controlled by the producer
- Frame boundaries are enforced at the decoded-frame level, not at packet or keyframe boundaries
- _No subprocess launching or ffmpeg_ at any point in Air
- All automated tests pass _without ffmpeg installed anywhere on the system_
