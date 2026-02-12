# ⚠️ RETIRED — Superseded by BlockPlan Architecture

**See:** [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)

This document describes legacy playlist/Phase8 execution and is no longer active.

---

# ScheduleManager Phase 6 Contract: Mid-Segment Join

**Status:** Draft
**Version:** 1.0
**Dependencies:** Phase 5

## Overview

Phase 6 implements mid-segment join (seek) functionality. When a viewer tunes in
mid-program, playback starts at the correct position within the episode rather
than from the beginning.

**Goal:** Viewer tuning in at 18:22 during an episode that started at 18:00
sees playback at the 22-minute mark, not at 0:00.

**Illusion Guarantee:** From the viewer's perspective, playback MUST appear as
if the channel has been playing continuously since segment start, regardless of
join time.

## Problem Statement

Linear TV simulation requires that:
1. Content plays according to a fixed schedule (wall-clock driven)
2. Viewers joining mid-program see the correct point in the content
3. All viewers of a channel see synchronized content

Without mid-segment join, a viewer tuning in mid-episode would see the episode
start from the beginning, breaking the illusion of live linear TV.

## Scope

Phase 6 applies to any scheduled segment with seekable media (programs, bumpers,
promos), but excludes ad pods unless explicitly enabled in future phases.

Phase 6 covers:
- Core: Calculating correct seek offset based on schedule and current time
- AIR: Implementing container seek + frame admission for accurate positioning
- Verification: Ensuring seek accuracy within acceptable tolerance

Phase 6 does NOT cover:
- DVR or rewind functionality
- Viewer-controlled seeking
- Ad break insertion during seek
- Catch-up TV features

## Terminology

| Term | Definition |
|------|------------|
| `target_pts` | Desired playback position in media time (microseconds) |
| `start_offset_ms` | Core-calculated seek offset passed to AIR (milliseconds) |
| `first_emitted_pts` | PTS of first frame output after seek |
| `keyframe` | I-frame; decode-independent frame required to start decoding |
| `GOP` | Group of Pictures; distance between keyframes |
| `frame admission` | Logic that discards frames with PTS below threshold |

## Architecture

```
Core (Python)                          AIR (C++)
─────────────────────────────────────────────────────────────────

ProgramDirector                        PlayoutEngine
    │                                      │
    ▼                                      ▼
ScheduleManagerBackedScheduleService                  LoadPreview(asset, start_offset_ms)
    │                                      │
    ├─► get_playout_plan_now()             ▼
    │       │                          FileProducer
    │       ├─► Calculate elapsed      ┌───────────────────────┐
    │       │   since segment start    │ 1. Container seek     │
    │       │                          │    (av_seek_frame)    │
    │       └─► Return start_pts_ms    │                       │
    │                                  │ 2. Frame admission    │
    ▼                                  │    (discard until     │
ChannelManager                         │     PTS >= target)    │
    │                                  │                       │
    └─► load_preview(start_offset_ms)  │ 3. First emitted      │
                                       │    frame at target    │
                                       └───────────────────────┘
```

## Invariants

### INV-P6-001: Seek Offset Calculation

**Statement:** Core calculates `start_offset_ms` as elapsed time from segment start.

**Formula:**
```
if now < segment.start_utc:
    start_offset_ms = 0
else:
    start_offset_ms = (now - segment.start_utc).total_seconds() * 1000
                    + segment.seek_offset_seconds * 1000
```

**Rationale:** The seek offset must account for:
- Time elapsed since the segment began airing
- Any pre-existing seek offset (for multi-part segments)
- Clock skew or schedule drift (clamp to 0, never negative)

**Enforcement:**
- `ScheduleManagerBackedScheduleService.get_playout_plan_now()` calculates offset
- Offset passed in playout plan as `start_pts` field
- If `now < segment.start_utc`, offset MUST be 0

### INV-P6-002: Container Seek to Keyframe

**Statement:** AIR seeks to the nearest keyframe at or before the target PTS.

**Rationale:** Video codecs require starting from a keyframe (I-frame) to decode
correctly. Seeking to an arbitrary position produces corrupted output.

**Implementation:**
```cpp
av_seek_frame(format_ctx_, video_stream_index_, target_ts, AVSEEK_FLAG_BACKWARD);
```

**Enforcement:**
- FileProducer calls `av_seek_frame` in `InitializeDecoder()`
- AVSEEK_FLAG_BACKWARD ensures keyframe at or before target
- Decoder buffers flushed after seek

### INV-P6-003: Single Seek Per Join

**Statement:** A mid-segment join MUST perform at most one seek per viewer join event.

**Rationale:** Prevents:
- Retry loops that increase latency unpredictably
- "Keep seeking until exact PTS" anti-patterns
- Resource exhaustion from repeated seek attempts

**Enforcement:**
- `FileProducer::InitializeDecoder()` performs seek once during initialization
- No seek retry logic; if seek fails, fall back to decode-from-start
- Frame admission handles fine-grained positioning after single seek

### INV-P6-004: Frame Admission Gate

**Statement:** Frames with PTS < effective_seek_target are decoded but not emitted.
All streams MUST use the same effective seek target for admission.

**Rationale:** After seeking to a keyframe, the decoder produces frames from that
keyframe forward. Frames between the keyframe and target must be discarded to
achieve accurate positioning.

**Critical:** The admission threshold MUST be the effective seek target in media
time, NOT the raw schedule offset. For looping content where schedule_offset >
media_duration, the effective target is `schedule_offset % media_duration`.

**Effective Seek Target Calculation:**
```cpp
int64_t raw_target_us = start_offset_ms * 1000;
int64_t effective_seek_target_us = raw_target_us;

if (media_duration_us > 0 && raw_target_us >= media_duration_us) {
    effective_seek_target_us = raw_target_us % media_duration_us;
}
```

**Implementation:**
```cpp
// Video frame admission (uses effective_seek_target_us_, NOT start_offset_ms)
if (base_pts_us < effective_seek_target_us_) {
    return true;  // Discard frame; continue decoding
}

// Audio frame admission (MUST use same threshold as video)
if (base_pts_us < effective_seek_target_us_) {
    continue;  // Discard audio frame
}
```

**Enforcement:**
- Frame admission check in `ProduceRealFrame()` for video
- Frame admission check in `ReceiveAudioFrames()` for audio
- Both MUST use same `effective_seek_target_us_` threshold
- NEVER use raw `start_offset_ms * 1000` directly for admission

### INV-P6-005: First Emitted Frame Accuracy

**Statement:** First emitted frame has PTS within tolerance of target.

**Tolerance:** ≤ 1 GOP (Group of Pictures) duration, typically ≤ 2 seconds for
broadcast content, ≤ 10 seconds for streaming content.

**Rationale:** Due to keyframe spacing, exact positioning is not always possible.
The first emitted frame will be the first frame at or after the target PTS.

**Verification:**
```
first_emitted_pts >= target_pts
first_emitted_pts <= target_pts + max_gop_duration
```

### INV-P6-006: Audio-Video Sync After Seek

**Statement:** Audio and video remain synchronized after seek.

**Rationale:** Audio and video streams have different keyframe structures. Both
must be seeked and admitted consistently to maintain lip sync.

**Implementation:**
- Both streams seek to same target time
- Both streams flush decoder buffers after seek
- Both streams use same frame admission threshold
- PTS offset applied consistently to both

### INV-P6-007: Seek Latency Bound

**Statement:** Seek-to-first-output latency is bounded.

**Target:** First output within 5 seconds of seek request for typical broadcast
content (GOP ≤ 2 seconds, 30fps).

**Rationale:** Excessive seek latency creates poor user experience when tuning in.

**Factors affecting latency:**
- Keyframe spacing (GOP size)
- Decode speed
- Buffer sizes
- Network latency (if remote asset)

### INV-P6-008: Clock-Gated Emission

**Statement:** After `SwitchToLive` completes, frames MUST be emitted at wall-clock
pace. A frame with media PTS `P` MUST NOT be emitted before wall-clock time `T₀ + P`,
where `T₀` is the epoch when the first frame was emitted.

**Formal Definition:**

Let:
- `T₀` = wall-clock time when first frame is emitted (epoch)
- `P₀` = media PTS of first emitted frame
- `Pₙ` = media PTS of frame N
- `Tₙ` = wall-clock time when frame N is emitted
- `ε` = tolerance (default: 10ms)

**Invariant:**
```
For all frames N after the first:
    Tₙ ≥ T₀ + (Pₙ - P₀) - ε
```

In prose: Frame N must not be emitted earlier than `(Pₙ - P₀)` microseconds after
the epoch, minus a small tolerance for scheduling jitter.

**Corollary (Rate Bound):**
```
For any window of K consecutive frames:
    (T_{n+K} - Tₙ) ≈ (P_{n+K} - Pₙ) ± Kε
```

In prose: The wall-clock duration to emit K frames must approximately equal the
media duration of those K frames.

**Rationale:** Without clock gating, a producer decoding faster than wall-clock
floods output buffers. The invariant ensures production rate equals consumption
rate (1× real-time).

**Applies To:**
- Video frames (ProduceRealFrame)
- Audio frames (ReceiveAudioFrames)
- Both streams use the same epoch `T₀`

**Implementation Sketch:**
```cpp
// Before emitting any frame:
int64_t frame_offset_us = frame_pts_us - first_frame_pts_us_;
int64_t target_utc_us = playback_start_utc_us_ + frame_offset_us;
int64_t now_us = master_clock_->now_utc_us();
if (now_us < target_utc_us) {
    sleep_until(target_utc_us);
}
// Now emit
```

**Verification:** See P6-T021 through P6-T025 for test specifications.

### INV-P6-009: Backpressure on Buffer Full

**Statement:** When output buffer is full, producer MUST block until space is
available. Producer MUST NOT spin, flood, or silently drop frames.

**Rationale:** "Buffer full" is a flow-control signal, not an error condition.
A producer that ignores backpressure will overwhelm downstream consumers and
cause cascading failures.

**Rules:**
- When `Push()` returns false (buffer full), producer MUST:
  - Block (sleep/yield) for a bounded interval
  - Retry until push succeeds or stop is requested
- Producer MUST NOT:
  - Log and continue without retry
  - Drop frames silently
  - Spin without backing off
- Video and audio MUST obey the same backpressure rules

**Bounded backoff:** 10ms default, configurable per-producer.

### INV-P6-010: Audio-Video Emission Parity

**Statement:** Audio MUST NOT emit until the video epoch is established. After
epoch establishment, audio MUST NOT outrun video by more than the warm-up window.

**Rationale:** Audio decodes faster than video. Without emission parity, audio
fills its buffer while video starves, causing desync and buffer overflow.

**Rules:**
1. Video establishes epoch: first video frame sets `first_frame_pts_us_` and
   `playback_start_utc_us_`
2. Audio MUST block until `first_frame_pts_us_ > 0` before emitting any frame
3. After epoch, both streams emit at wall-clock pace using the same `T₀`
4. Audio MUST NOT push frames while `first_frame_pts_us_ == 0`

**Implementation:**
```cpp
// In ReceiveAudioFrames(), before emitting:
while (first_frame_pts_us_ == 0 && !stop_requested_) {
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
}
// Now safe to clock-gate and emit
```

**Violation:** If audio pushes any frames before video epoch is set, or if audio
pushes hundreds of frames without video, the invariant is violated.

### INV-P6-011: Warm-Up Window

**Statement:** Producers MAY decode up to N milliseconds ahead of wall-clock
time, but MUST NOT emit ahead.

**Default warm-up window:** 500ms

**Rationale:** A small decode-ahead window prevents startup starvation by
pre-filling buffers. However, emit timing is still clock-gated to prevent
runaway production.

**Rules:**
- Decode-ahead is permitted (private queue)
- Emit is clock-gated (shared buffer)
- If buffer has space AND clock permits → emit
- If buffer has space BUT clock forbids → wait
- If buffer full AND clock permits → wait for space (INV-P6-009)

**Note:** This warm-up window is for initial fill. Once steady-state is reached,
production and consumption rates converge to wall-clock pace.

### INV-P6-012: Clock Epoch Must Account for Seek Offset

**Statement:** When playback starts after a mid-segment seek, the MasterClock epoch
MUST be set to `playback_start_utc - first_frame_pts`, not just `playback_start_utc`.

**Rationale:** The epoch is used by `scheduled_to_utc_us(pts)` to map frame PTS to
wall-clock deadlines. Without accounting for the seek offset:

```
scheduled_to_utc_us(first_frame_pts) = epoch + first_frame_pts
                                     = playback_start + first_frame_pts
                                     = (e.g.) now + 23 minutes  ← WRONG!
```

With the correct epoch calculation:

```
epoch = playback_start - first_frame_pts
scheduled_to_utc_us(first_frame_pts) = epoch + first_frame_pts
                                     = (playback_start - first_frame_pts) + first_frame_pts
                                     = playback_start  ← CORRECT!
```

**Failure Signature:** ProgramOutput appears stuck after seek. Video frames are pushed
to buffer but never rendered. The log shows:
```
[FileProducer] Video frame pushed #1, pts=1407030622
[FileProducer] Video frame pushed #2, pts=1407072333
... (no ProgramOutput consumption logs)
```

The frames have PTS values in the millions (media time after seek), and ProgramOutput
is waiting for deadlines far in the future.

**Implementation:**
```cpp
// In FileProducer, when setting epoch after first frame:
int64_t epoch_utc_us = playback_start_utc_us_ - first_frame_pts_us_;
master_clock_->set_epoch_utc_us(epoch_utc_us);
```

**Test Specification (P6-T027):** After mid-segment seek to time T, the first frame
MUST be rendered within 1 second of wall-clock time (not T seconds later).

### INV-P6-013: Audio Frame Processing Rate Limit

**Statement:** The audio frame receiver MUST process at most ONE audio frame
per call, returning control to the video decode loop after each frame.

**Rationale:** After a seek, the FFmpeg decoder may buffer multiple audio frames
before they are requested via `avcodec_receive_frame()`. If the audio receiver
processes ALL buffered frames in a single call (via a while loop), several
problems occur:

1. **Burst Emission:** All buffered audio frames have PTS values clustered near
   the seek target. When video epoch is set, these frames calculate their clock-
   gate sleep times as nearly zero (since `frame_offset_us ≈ 0`), causing all
   frames to emit immediately without proper pacing.

2. **Buffer Overflow:** Audio frames burst into the buffer faster than the
   consumer can drain them, triggering "buffer full" backpressure retries.

3. **Video Starvation:** While audio is bursting, video decode is blocked
   waiting for `ReceiveAudioFrames()` to return, preventing video from
   establishing or maintaining its pacing.

**Failure Signature:**
```
[FileProducer] VIDEO_EPOCH_SET first_video_pts_us=60033333
[FileProducer] Pushed audio frame #7, base_pts_us=60023220
[FileProducer] Pushed audio frame #8, base_pts_us=60046453
...
[FileProducer] Pushed audio frame #50, base_pts_us=61000000  ← 50 frames in <100ms!
[FileProducer] Audio buffer full, backing off (retry #1)
[FileProducer] Audio buffer full, backing off (retry #100)
[FileProducer] Audio buffer full, backing off (retry #1000)
```

**Root Cause:** Audio frames at PTS 60023220 through 61000000 (~1 second of media)
all have clock-gate targets within milliseconds of each other after epoch is set,
so none of them sleep.

**Fix:** Change the audio receive loop from:
```cpp
// BAD: Processes all frames in one call
while (!stop_requested) {
    avcodec_receive_frame(audio_codec_ctx_, audio_frame_);
    // ... clock gate and emit ...
}
```

To:
```cpp
// GOOD: Processes one frame per call, interleaves with video
bool processed_one = false;
while (!stop_requested && !processed_one) {
    avcodec_receive_frame(audio_codec_ctx_, audio_frame_);
    // ... clock gate and emit ...
    processed_one = true;  // Exit after this frame
}
```

**Effect:** By processing one audio frame per call, control returns to the video
decode loop after each audio frame. This naturally interleaves audio and video
production, and the video decode loop's inherent pacing (via clock gating on
video frames) spreads out the audio frame production over time.

**Enforcement:**
- `ReceiveAudioFrames()` MUST set a "processed one" flag and break after
  successfully emitting one frame
- `ReceiveAudioFrames()` is called frequently (after each video packet
  dispatch), so audio frames are still processed promptly

**Test Specification (P6-T026):** After mid-segment seek, audio buffer MUST NOT
receive more than 5 frames before video emits its first frame. Audio frame rate
MUST NOT exceed 2× wall-clock rate for more than 100ms after epoch.

### INV-P6-014: Segment End Time From Schedule, Not Duration

**Statement:** ChannelManager MUST extract segment end time directly from
`end_time_utc` in the playout plan, NOT calculate it from `station_time + duration_seconds`.

**Rationale:** For mid-segment joins, `duration_seconds` represents the FULL segment
duration (from segment start to segment end), but the viewer joined mid-segment.
Calculating end time from duration produces incorrect transitions:

```
# Wrong calculation (mid-segment join):
segment.duration_seconds = 1500  # 25 minutes (full segment)
station_time = 18:15:00  # viewer joins here
_segment_end_time_utc = 18:15:00 + 25min = 18:40:00  ← WRONG!

# Correct: use schedule's end_time_utc
segment.end_time_utc = 18:25:00  # segment ends at grid boundary
_segment_end_time_utc = 18:25:00  ← CORRECT!
```

**Failure Signature:**
- Segment transitions occur late by the amount of time elapsed since segment start
- Example: If viewer joins 10 minutes into segment, transition is 10 minutes late
- Program → filler transitions may never occur if duration exceeds grid boundary

**Implementation:**
```python
# In ChannelManager._segment_end_time_from_plan()
def _segment_end_time_from_plan(self, segment: dict, fallback_start: datetime) -> datetime | None:
    # Prefer explicit end_time_utc from schedule (Phase 6 correct behavior)
    end_time_str = segment.get("end_time_utc")
    if end_time_str:
        return datetime.fromisoformat(end_time_str)

    # Legacy fallback: calculate from duration (only works at segment start)
    duration_s = self._segment_duration_seconds(segment)
    if duration_s > 0:
        return fallback_start + timedelta(seconds=duration_s)
    return None
```

**Enforcement:**
- `ChannelManager` MUST call `_segment_end_time_from_plan()` instead of calculating
  from duration
- Playout plan MUST include `end_time_utc` field (provided by ScheduleManagerBackedScheduleService)
- Unit tests verify transition timing matches grid boundary, not join_time + duration

**Test Specification (P6-T028):** Mid-segment join at time T with segment ending
at grid boundary B MUST trigger transition at time B, regardless of segment duration.
Specifically: `_segment_end_time_utc == B`, not `T + segment.duration_seconds`.

## Data Flow

### 1. Core Calculates Offset

```python
# In ScheduleManagerBackedScheduleService.get_playout_plan_now()
now = datetime.now(timezone.utc)
elapsed = (now - segment.start_utc).total_seconds()
total_seek = segment.seek_offset_seconds + elapsed
start_pts_ms = int(total_seek * 1000)
```

### 2. Offset Passed to AIR

```python
# In ChannelManager
producer.load_preview(asset_path, start_offset_ms=start_pts_ms)
```

### 3. AIR Performs Seek

```cpp
// In PlayoutEngine::LoadPreview()
preview_config.start_offset_ms = start_offset_ms;

// In FileProducer::InitializeDecoder()
if (config_.start_offset_ms > 0) {
    int64_t target_ts = av_rescale_q(
        config_.start_offset_ms * 1000,
        AV_TIME_BASE_Q,
        format_ctx_->streams[video_stream_index_]->time_base);
    av_seek_frame(format_ctx_, video_stream_index_, target_ts, AVSEEK_FLAG_BACKWARD);
    avcodec_flush_buffers(codec_ctx_);
    avcodec_flush_buffers(audio_codec_ctx_);
}
```

### 4. Frame Admission Filters Output

```cpp
// In FileProducer::ProduceRealFrame()
const int64_t start_offset_us = config_.start_offset_ms * 1000;
if (base_pts_us < start_offset_us) {
    return true;  // Discard, continue decoding
}
// Frame passes admission, emit to buffer
```

## Test Specifications

| ID | Test | Description |
|----|------|-------------|
| P6-T001 | Offset calculation | Elapsed time correctly calculated |
| P6-T002 | Offset at segment start | Offset is 0 at segment start time |
| P6-T003 | Offset mid-segment | Offset equals elapsed seconds * 1000 |
| P6-T004 | Container seek called | av_seek_frame invoked with correct params |
| P6-T005 | Decoder buffers flushed | avcodec_flush_buffers called after seek |
| P6-T006 | Video frame admission | Frames before target discarded |
| P6-T007 | Audio frame admission | Audio before target discarded |
| P6-T008 | First frame accuracy | First emitted PTS ≥ target |
| P6-T009 | A/V sync after seek | Audio and video remain synchronized |
| P6-T010 | Seek latency | First output within 5 seconds |
| P6-T011 | Zero offset (no seek) | start_offset_ms=0 skips seek logic |
| P6-T012 | Near-EOF seek | Seek near end of file handles gracefully |
| P6-T013 | Clock gating video | Video frames emit at wall-clock pace |
| P6-T014 | Clock gating audio | Audio frames emit at wall-clock pace |
| P6-T015 | Backpressure video | Video blocks on buffer full |
| P6-T016 | Backpressure audio | Audio blocks on buffer full |
| P6-T017 | Audio-video parity | Audio doesn't outrun video after join |
| P6-T018 | No buffer overflow | No BUFFER FULL errors after warm-up |
| P6-T019 | Warm-up window | Initial buffer fill within 500ms |
| P6-T020 | Steady-state rate | Production rate matches wall-clock |
| P6-T021 | Video rate invariant | 30 video frames in ~1000ms wall-clock |
| P6-T022 | Audio rate invariant | 1 second of audio in ~1000ms wall-clock |
| P6-T023 | No early emission | Frame Tₙ ≥ T₀ + (Pₙ - P₀) - ε |
| P6-T024 | Post-seek rate | Rate invariant holds immediately after seek |
| P6-T025 | Sustained rate | Rate invariant holds for 30+ seconds |
| P6-T026 | Audio burst prevention | Audio MUST NOT burst >5 frames before video epoch |
| P6-T027 | Epoch accounts for seek | First frame renders within 1s after seek, not T seconds |
| P6-T028 | Segment end from schedule | Mid-join transition occurs at grid boundary, not join_time + duration |

### Clock-Gated Emission Tests (INV-P6-008)

These tests verify that frames are emitted at wall-clock pace, not decode pace.

#### P6-T021: Video Rate Invariant

**Setup:** Start producer with mid-segment seek. Record wall-clock time and PTS
for each emitted video frame.

**Measurement:** For 30fps content, measure wall-clock duration to emit 30 frames.

**Pass Criteria:**
```
wall_clock_duration_for_30_frames ∈ [950ms, 1050ms]
```

**Failure Mode:** If duration < 900ms, producer is free-running (not clock-gated).

#### P6-T022: Audio Rate Invariant

**Setup:** Start producer with mid-segment seek. Record wall-clock time and PTS
for each emitted audio frame.

**Measurement:** Measure wall-clock duration to emit 1 second of audio samples
(e.g., 48000 samples at 48kHz).

**Pass Criteria:**
```
wall_clock_duration_for_1s_audio ∈ [950ms, 1050ms]
```

**Failure Mode:** If duration < 900ms, audio is free-running ahead of clock.

#### P6-T023: No Early Emission

**Setup:** Instrument producer to log `(wall_clock_time, frame_pts)` for each emit.

**Measurement:** For each frame N, compute:
```
early_by = (T₀ + (Pₙ - P₀)) - Tₙ
```

**Pass Criteria:**
```
For all N: early_by ≤ 10ms (tolerance ε)
```

**Failure Mode:** If any frame has `early_by > 10ms`, clock gating failed.

#### P6-T024: Post-Seek Rate (Immediate)

**Setup:** Seek to 5 minutes into content. Measure rate for first 3 seconds after
first frame emit.

**Pass Criteria:**
```
frames_emitted_in_3s ∈ [87, 93] for 30fps video
audio_duration_emitted_in_3s ∈ [2.85s, 3.15s]
```

**Rationale:** Verifies clock gating activates immediately after seek, not after
a warm-up period.

#### P6-T025: Sustained Rate (30+ seconds)

**Setup:** Run producer for 30 seconds after seek. Sample frame rate every 5 seconds.

**Pass Criteria:**
```
For each 5-second window:
    video_frames ∈ [148, 152] for 30fps
    audio_duration ∈ [4.9s, 5.1s]
```

**Rationale:** Verifies clock gating is sustained, not just initial.

### Test Implementation (AIR C++)

```cpp
// In contracts_playoutengine_tests or deterministic_harness_tests

TEST(Phase6ClockGating, VideoRateInvariant) {
    // Setup: Create producer with FakeClock
    auto clock = std::make_shared<FakeMasterClock>();
    ProducerConfig config;
    config.start_offset_ms = 300000; // Seek to 5 minutes
    config.target_fps = 30.0;

    FrameRingBuffer buffer(60);
    FileProducer producer(config, buffer, clock);

    // Record emit times
    std::vector<std::pair<int64_t, int64_t>> emits; // (wall_time, pts)

    producer.start();

    // Advance fake clock and collect 30 frames
    for (int i = 0; i < 30; i++) {
        clock->advance_us(33333); // ~30fps
        // Wait for frame to be emitted
        auto frame = buffer.Pop();
        emits.push_back({clock->now_utc_us(), frame.metadata.pts});
    }

    producer.stop();

    // Verify: 30 frames should take ~1000ms of wall-clock
    int64_t wall_duration = emits.back().first - emits.front().first;
    EXPECT_GE(wall_duration, 950000); // >= 950ms
    EXPECT_LE(wall_duration, 1050000); // <= 1050ms
}

TEST(Phase6ClockGating, NoEarlyEmission) {
    // Similar setup...

    int64_t T0 = emits[0].first;
    int64_t P0 = emits[0].second;

    for (size_t i = 1; i < emits.size(); i++) {
        int64_t Tn = emits[i].first;
        int64_t Pn = emits[i].second;
        int64_t expected_time = T0 + (Pn - P0);
        int64_t early_by = expected_time - Tn;

        EXPECT_LE(early_by, 10000) // <= 10ms tolerance
            << "Frame " << i << " emitted " << (early_by/1000) << "ms early";
    }
}
```

## Failure Analysis: Clock Gating

When clock gating fails, the symptom is buffer overflow. This section describes
how to diagnose and identify the root cause.

### Symptom: BUFFER FULL Errors

```
[FileProducer] ===== FAILED TO PUSH AUDIO FRAME ===== (BUFFER FULL)
```

If you see hundreds of these in rapid succession immediately after `SwitchToLive`,
the producer is **free-running** (not clock-gated).

### Diagnostic: Compare PTS vs Wall-Clock

Add instrumentation to log emit times:
```cpp
std::cout << "[EMIT] wall_us=" << master_clock_->now_utc_us()
          << " pts_us=" << frame_pts_us
          << " delta=" << (master_clock_->now_utc_us() - playback_start_utc_us_)
          << " expected_delta=" << (frame_pts_us - first_frame_pts_us_)
          << std::endl;
```

**Healthy output (clock-gated):**
```
[EMIT] wall_us=1000000 pts_us=0      delta=0      expected_delta=0
[EMIT] wall_us=1033333 pts_us=33333  delta=33333  expected_delta=33333
[EMIT] wall_us=1066666 pts_us=66666  delta=66666  expected_delta=66666
```

**Unhealthy output (free-running):**
```
[EMIT] wall_us=1000000 pts_us=0      delta=0      expected_delta=0
[EMIT] wall_us=1000050 pts_us=33333  delta=50     expected_delta=33333  ← 33ms early!
[EMIT] wall_us=1000100 pts_us=66666  delta=100    expected_delta=66666  ← 66ms early!
```

### Root Causes

| Cause | Fix |
|-------|-----|
| Clock gating code missing | Add sleep/wait before emit |
| Clock gating only on video, not audio | Apply same logic to audio path |
| `first_frame_pts_us_` not set before audio emits | Audio must wait for video epoch |
| Backpressure returns instead of blocks | Change to retry loop with sleep |
| Using wrong clock (local vs MasterClock) | Use `master_clock_->now_utc_us()` |

### Quick Validation

After fixing, run for 10 seconds and count frames:

```bash
# Expected: ~300 video frames, ~10 seconds of audio
grep "Video frame pushed" /opt/retrovue/pkg/air/logs/*.log | wc -l
grep "Pushed audio frame" /opt/retrovue/pkg/air/logs/*.log | wc -l
```

If counts are 10× higher than expected, clock gating is still broken.

### Failure Pattern: Audio Burst Emission After Seek

**Symptom:** After mid-segment seek, audio floods the buffer with hundreds of
frames in milliseconds while video produces only a handful of frames.

```
[FileProducer] VIDEO_EPOCH_SET first_video_pts_us=60033333
[FileProducer] Video frame pushed #1, pts=60033333
[FileProducer] Pushed audio frame #7, base_pts_us=60023220
[FileProducer] Pushed audio frame #8, base_pts_us=60046453
... (audio frames 9-50 in rapid succession)
[FileProducer] Audio buffer full, backing off (retry #1)
[FileProducer] Audio buffer full, backing off (retry #1000)
[FileProducer] Video frame pushed #2, pts=60066666
```

**Root Cause:** `ReceiveAudioFrames()` processes all buffered audio frames in
a while loop. After seek, FFmpeg has many audio frames queued. When video epoch
is set, these frames all have `frame_offset_us` values near zero, so their
clock-gate sleep times are zero or negative, causing burst emission.

**Example Calculation (why all frames emit immediately):**
```
first_frame_pts_us = 60,033,333  (video epoch)
playback_start_utc_us = 1000000000  (wall clock at epoch)

Audio frame 1: pts = 60,023,220
  frame_offset_us = 60,023,220 - 60,033,333 = -10,113 (negative!)
  target_utc_us = 1000000000 + (-10,113) = 999,989,887 (IN THE PAST)
  now >= target → emit immediately

Audio frame 2: pts = 60,046,453
  frame_offset_us = 60,046,453 - 60,033,333 = 13,120
  target_utc_us = 1000000000 + 13,120 = 1,000,013,120
  If now ≈ 1,000,000,050 → only 13ms sleep, effectively immediate

... All 50 buffered frames emit in <100ms wall-clock time
```

**The Fix:** Process ONE audio frame per call to `ReceiveAudioFrames()`. This
returns control to the video decode loop, which has its own clock gating. The
video loop's pacing naturally spreads out audio frame production over time.

**Verification:** After fix, logs should show interleaved audio/video:
```
[FileProducer] VIDEO_EPOCH_SET first_video_pts_us=60033333
[FileProducer] Video frame pushed #1, pts=60033333
[FileProducer] Pushed audio frame #7, base_pts_us=60023220
[FileProducer] Video frame pushed #2, pts=60066666
[FileProducer] Pushed audio frame #8, base_pts_us=60046453
[FileProducer] Video frame pushed #3, pts=60099999
[FileProducer] Pushed audio frame #9, base_pts_us=60069686
... (interleaved, roughly 1 audio per video)
```

## Verification Procedure

```bash
# 1. Run contract tests
source pkg/core/.venv/bin/activate
pytest pkg/core/tests/contracts/test_schedule_manager_phase6_contract.py -v

# 2. Start server
retrovue start

# 3. Note current time and block schedule
# Example: Block started at 18:00, now is 18:15

# 4. Tune in and verify seek
vlc http://localhost:8000/channel/cheers-24-7.ts

# 5. Verify in VLC:
# - Playback starts mid-episode (not from beginning)
# - Seek position approximately matches elapsed time
# - Audio and video are synchronized
# - No visual corruption from bad keyframe handling
```

## Litmus Test

1. Schedule shows episode starting at 14:00:00
2. Tune in at 14:12:30
3. Verify:
   - Playback position is approximately 12:30 into episode
   - Audio and video are in sync
   - No green frames or visual artifacts
   - Playback is smooth after initial seek

## Edge Cases

### Near Segment Boundary
When `now` is within 5 seconds of segment end:
- Core may return next segment instead
- Seek offset should be minimal (0-5 seconds)

### Seek Beyond EOF
When calculated offset exceeds file duration:
- FileProducer should handle gracefully
- May trigger immediate EOF
- Core should detect and switch to next segment

### Keyframe-Only Content
Some content (screen recordings) may be all keyframes:
- Seek is effectively frame-accurate
- Frame admission may discard very few frames

### Very Large GOP
Live recordings may have 10+ second GOPs:
- Seek latency may exceed 5 second target
- Frame admission discards more frames
- First output may be several seconds after target

## Observability

Seek operations SHOULD emit a structured log containing:
- `target_pts` — requested seek position
- `first_emitted_pts` — actual first frame PTS
- `seek_latency_ms` — time from seek request to first output

Example log format:
```
[FileProducer] Seek complete: target_pts=1362163000us, first_emitted_pts=1362194166us, seek_latency_ms=127
```

## Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| seek_latency_ms | Time from seek to first output | ≤ 5000ms |
| seek_accuracy_ms | |first_emitted_pts - target_pts| | ≤ 2000ms |
| frames_discarded | Frames discarded by admission | varies |
| keyframe_distance_ms | Distance from keyframe to target | varies |
| clock_gate_sleeps | Number of clock-gate sleep events | normal |
| backpressure_waits | Number of buffer-full wait events | 0 steady-state |
| audio_video_drift_ms | Audio/video emit time difference | ≤ 40ms |
| warmup_duration_ms | Time to reach steady-state | ≤ 500ms |

## Relationship to Other Phases

- **Phase 3:** Provides segment timing information
- **Phase 5:** Wires Phase 3 into runtime, passes offset to AIR
- **Phase 6:** Implements seek mechanics in AIR
- **Future:** Seamless segment transitions, pre-buffering next segment

## Future Work (Phase 7+)

### Timezone-Aware Scheduling

**Priority:** High

**Problem:** Currently, schedule blocks use UTC time codes. This makes it difficult
for operators to reason about schedules in their local timezone and creates
confusion when programming content for specific local air times.

**Proposed Solution:** Store all times internally in UTC (current behavior is correct),
but display/communicate times to operators in their configured local timezone.

**Requirements:**
- Channel-level timezone configuration (e.g., `"timezone": "America/New_York"`)
- CLI output shows times in local timezone
- Schedule input accepts local time, converts to UTC for storage
- EPG output in local timezone
- Logs show local timezone for operator readability
- Internal runtime continues using UTC (no change to execution logic)
- Handle DST transitions correctly in display/input conversion

### AIR Log Verbosity Reduction

**Priority:** Medium

**Problem:** AIR logs are extremely verbose during normal operation, logging every
frame push, audio frame, PTS value, and scale diagnostic. This makes it difficult
to spot actual issues and generates excessive log volume.

**Proposed Solution:** Implement log levels in AIR with sensible defaults:

**Requirements:**
- Add log level configuration (ERROR, WARN, INFO, DEBUG, TRACE)
- Default to INFO level for production
- Move per-frame logging (VIDEO_PTS, audio frame push, SCALE_DIAG) to DEBUG/TRACE
- Keep important events at INFO: startup, seek, switch, errors, periodic stats
- Add command-line flag or config option to set log level
- Consider periodic summary logs instead of per-frame (e.g., "Produced 100 frames in 3.3s")

### FIXED: Audio Frame Counter Not Resetting on Producer Switch

**Status:** Fixed (2026-01-30)

**Problem:** When switching producers (e.g., episode → filler), the `frames_since_start`
audio counter did not reset. This caused cumulative counting across producer switches
(e.g., audio at 80,000+ while video at 1,700), leading to A/V desync.

**Observed Symptoms:**
- Audio and video stuttering after producer switch
- A/V desync that worsens over time
- Audio frame counter shows cumulative count across sessions

**Root Cause:** Multiple counters in `FileProducer.cpp` were declared as `static` instead
of instance members, causing them to persist across FileProducer instances.

**Fix Applied:** Converted all static counters to instance member variables in
`FileProducer.h` and `FileProducer.cpp`:
- `video_frame_count_`, `video_discard_count_` - video frame counters
- `audio_frame_count_`, `frames_since_producer_start_` - audio frame counters
- `audio_skip_count_`, `audio_drop_count_`, `audio_ungated_logged_` - audio state
- `scale_diag_count_` - diagnostic counter

Each new FileProducer instance now gets fresh counters.

### FIXED: Sample Rate and Channel Mismatch on Producer Switch

**Status:** Fixed (2026-01-30)

**Problem:** When switching from content with one audio format (e.g., 48kHz stereo) to
content with a different format (e.g., 44.1kHz or mono), the encoder pipeline failed
with "Error muxing audio packet: Operation not permitted". Audio stopped completely.

**Root Cause:** Two issues were identified:
1. The EncoderPipeline used the encoder's channel count (`audio_codec_ctx_->ch_layout.nb_channels`)
   instead of the input's channel count, causing data corruption when channels differed.
2. The audio resampler was only configured to handle sample rate conversion, not channel
   conversion. When input channels differed from encoder channels (stereo), the resampler
   produced incorrect output.

**Fix Applied:**
1. Added input validation to skip invalid audio frames (prevents crashes)
2. Added `last_input_channels_` tracking to detect channel count changes
3. Updated `needs_resampling` to trigger when sample rate OR channels differ from encoder
4. Fixed resampler setup to use correct source channel layout based on input channels
5. Added `audio_format_changed` check that triggers buffer flush on either sample rate
   or channel changes

**Files Modified:**
- `pkg/air/include/retrovue/playout_sinks/mpegts/EncoderPipeline.hpp` - added `last_input_channels_`
- `pkg/air/src/playout_sinks/mpegts/EncoderPipeline.cpp` - fixed channel handling and resampler setup
