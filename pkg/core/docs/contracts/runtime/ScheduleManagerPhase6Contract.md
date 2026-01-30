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
Phase3ScheduleService                  LoadPreview(asset, start_offset_ms)
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
- `Phase3ScheduleService.get_playout_plan_now()` calculates offset
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

**Statement:** Frames with PTS < target are decoded but not emitted.

**Rationale:** After seeking to a keyframe, the decoder produces frames from that
keyframe forward. Frames between the keyframe and target must be discarded to
achieve accurate positioning.

**Implementation:**
```cpp
// Video frame admission
if (base_pts_us < start_offset_us) {
    return true;  // Discard frame; continue decoding
}

// Audio frame admission
if (base_pts_us < start_offset_us) {
    continue;  // Discard audio frame
}
```

**Enforcement:**
- Frame admission check in `ProduceRealFrame()` for video
- Frame admission check in `ReceiveAudioFrames()` for audio
- Both must use same `start_offset_us` threshold

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

## Data Flow

### 1. Core Calculates Offset

```python
# In Phase3ScheduleService.get_playout_plan_now()
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

## Relationship to Other Phases

- **Phase 3:** Provides segment timing information
- **Phase 5:** Wires Phase 3 into runtime, passes offset to AIR
- **Phase 6:** Implements seek mechanics in AIR
- **Future:** Seamless segment transitions, pre-buffering next segment
