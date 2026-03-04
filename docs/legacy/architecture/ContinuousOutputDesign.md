# Broadcast-Correct Continuous Output Design

## Executive Summary

This document addresses the NON-NEGOTIABLE requirements for broadcast-correct streaming:

| Requirement | Current State | Root Cause | Fix |
|-------------|---------------|------------|-----|
| R1: Fast tune-in (<250ms) | ~2-5s delay | Encoder priming, no pad frames | Emit pad frames immediately |
| R2: Continuous output | Gaps between blocks | Serial block execution | Continuous output loop with source switching |
| R3: Encoder never stops | Encoder persists (fixed) | Was resetting per-block | Session-long encoder (done) |
| R4: Seamless block transition | ~22s gap | No source preloading, serial execution | A/B source switch with preloading |
| R5: Determinism | Stable frame count | CT-based execution | Already frame-deterministic |

---

## Section A: Ranked Hypotheses + Instrumentation

### Hypothesis 1: Serial Block Execution (CONFIRMED - Highest Likelihood)

**Observation**: Block A execution completes → loop returns → Block B execution starts.
During the transition, NO frames are emitted.

**Evidence from code** (`playout_service.cpp:247-358`):
```cpp
while (!state->stop_requested) {
    // Wait for block (line 262) - UP TO 100ms delay
    state->queue_cv.wait_for(lock, std::chrono::milliseconds(100));

    // Block B starts here - probe assets, validate, create executor
    // ALL OF THIS HAPPENS WHILE NO FRAMES EMIT

    auto result = executor.Execute(validated, join_result.params);
    // Block A completes HERE

    EmitBlockCompleted(state, current_block, result.final_ct_ms);
    // Loop back to top - gap starts
}
```

**Time spent in transition** (no frames emitting):
- `queue_cv.wait_for`: 0-100ms
- `assets.ProbeAsset()` for each segment: ~50-200ms per asset
- `validator.Validate()`: <1ms
- `JoinComputer::ComputeJoinParameters()`: <1ms
- `RealTimeBlockExecutor` constructor: <1ms
- `executor.Execute()` startup (sink open, clock setup): ~5-10ms

**Total estimated gap: 100-400ms** per block transition.

**But we're seeing 22s gaps!** This suggests something else...

**Instrumentation Points**:
```cpp
// Add to BlockPlanExecutionThread, line 267:
auto block_fetch_start = std::chrono::steady_clock::now();
current_block = state->block_queue.front();
auto block_fetch_end = std::chrono::steady_clock::now();
std::cout << "[METRIC] block_fetch_time_ms="
          << duration_cast<milliseconds>(block_fetch_end - block_fetch_start).count() << std::endl;

// Add after EmitBlockCompleted (line 333):
auto boundary_end = std::chrono::steady_clock::now();
std::cout << "[METRIC] boundary_to_next_block_start_ms=" << ... << std::endl;

// Add in RealTimeBlockExecutor::Execute, at first frame emission:
static auto first_frame_time = steady_clock::now();
if (sink_->FrameCount() == 1) {
    std::cout << "[METRIC] first_frame_since_block_start_ms="
              << duration_cast<ms>(now - block_enter_time).count() << std::endl;
}
```

### Hypothesis 2: Asset Probe Blocking (High Likelihood)

**Observation**: `RealAssetSource::ProbeAsset()` calls `avformat_open_input` + `avformat_find_stream_info` synchronously on the execution thread.

**Evidence** (`RealTimeExecution.cpp:72-108`):
```cpp
bool RealAssetSource::ProbeAsset(const std::string& uri) {
    if (avformat_open_input(&fmt_ctx, uri.c_str(), nullptr, nullptr) < 0) {
        // BLOCKING FILE I/O
    }
    if (avformat_find_stream_info(fmt_ctx, nullptr) < 0) {
        // BLOCKING - CAN TAKE 1-5 SECONDS FOR SOME FILES
    }
}
```

**FFmpeg's `avformat_find_stream_info`** is notorious for:
- Reading several seconds of file to detect codec parameters
- Scanning for keyframes
- Can take **10-30 seconds** for poorly-muxed files

**Instrumentation**:
```cpp
// Add timing around ProbeAsset:
auto probe_start = std::chrono::steady_clock::now();
bool result = assets_.ProbeAsset(seg.asset_uri);
auto probe_end = std::chrono::steady_clock::now();
std::cout << "[METRIC] asset_probe_ms=" << duration_cast<ms>(probe_end - probe_start).count()
          << " uri=" << seg.asset_uri << std::endl;
```

### Hypothesis 3: Decoder Open/Seek at Block Start (Medium Likelihood)

**Observation**: `RealTimeEncoderSink::EmitFrame()` opens a new decoder when asset URI changes.

**Evidence** (`RealTimeExecution.cpp:278-296`):
```cpp
if (!decoder_ || current_asset_uri_ != frame.asset_uri) {
    decoder_.reset();
    decoder_ = std::make_unique<decode::FFmpegDecoder>(dec_config);
    if (!decoder_->Open()) {  // BLOCKING - FILE I/O
        // ...
    }
}
```

**This happens on the FIRST frame of each block** if the asset is "new" (even if it's the same asset as previous block, since `current_asset_uri_` is reset per-sink instance).

**Instrumentation**:
```cpp
// Add timing:
auto decoder_open_start = steady_clock::now();
if (!decoder_->Open()) { ... }
auto decoder_open_end = steady_clock::now();
std::cout << "[METRIC] decoder_open_ms=" << duration_cast<ms>(...).count() << std::endl;
```

### Hypothesis 4: Encoder Priming Delay at Session Start (High for Startup)

**Observation**: x264/NVENC encoders buffer frames before producing output (B-frame lookahead, rate control warmup).

**Evidence**:
- x264 default: 16-frame lookahead
- At 30fps: 16 × 33ms = **528ms** before first encoded frame
- NVENC default: 0 lookahead (better), but still has priming

**Instrumentation**:
```cpp
// In EncoderPipeline::encodeFrame, measure time to first output:
if (!first_frame_encoded_) {
    auto encode_start = steady_clock::now();
    // ... encode ...
    auto encode_end = steady_clock::now();
    std::cout << "[METRIC] first_encode_latency_ms=" << ... << std::endl;
    first_frame_encoded_ = true;
}
```

### Hypothesis 5: No PAT/PMT Until First Keyframe (Medium for Tune-in)

**Observation**: VLC/ffplay may wait for PAT/PMT before displaying.

**Evidence**: PAT/PMT are written in `avformat_write_header()`, which happens in `EncoderPipeline::open()`. This is correct. BUT if the first video packet is not a keyframe, decoders wait.

**Instrumentation**:
```cpp
// Log keyframe timing:
if ((packet_->flags & AV_PKT_FLAG_KEY) && !first_keyframe_emitted_) {
    std::cout << "[METRIC] first_keyframe_emitted_at_pts=" << packet_->pts
              << " frame_count=" << video_frame_count_ << std::endl;
    first_keyframe_emitted_ = true;
}
```

---

## Section B: Continuous Output Design + Invariants

### Core Invariant

```
INV-OUTPUT-CONTINUOUS: Once streaming starts, the TS writer outputs at frame cadence
until teardown. If content isn't available, emit pad A/V. Never stall.
```

### Current Architecture (BROKEN)

```
                    ┌─────────────────────────────────────────┐
                    │         BlockPlanExecutionThread        │
                    │                                         │
                    │  ┌──────────┐   GAP   ┌──────────┐     │
                    │  │ Block A  │ ======> │ Block B  │     │
                    │  │ Execute  │  NO     │ Execute  │     │
                    │  │          │ OUTPUT  │          │     │
                    │  └──────────┘         └──────────┘     │
                    │        │                    │          │
                    └────────┼────────────────────┼──────────┘
                             │                    │
                             v                    v
                    ┌─────────────────────────────────────────┐
                    │            EncoderPipeline              │
                    │         (frames only when              │
                    │          executor is running)           │
                    └─────────────────────────────────────────┘
```

### Target Architecture (CONTINUOUS)

```
┌───────────────────────────────────────────────────────────────────┐
│                    ContinuousOutputController                      │
│                                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │              OUTPUT CLOCK TICK (33ms cadence)              │   │
│  │                                                            │   │
│  │   for each tick:                                           │   │
│  │     1. Check if content available from ActiveSource        │   │
│  │     2. If yes: encode real frame                           │   │
│  │     3. If no:  encode pad frame (black+silence)            │   │
│  │     4. Never skip a tick                                   │   │
│  │                                                            │   │
│  └────────────────────────────────────────────────────────────┘   │
│                              │                                     │
│                              v                                     │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                     SOURCE ABSTRACTION                      │   │
│  │                                                             │   │
│  │   ActiveSource ◄────────────────────► NextSource            │   │
│  │   (current block)         PRELOAD    (next block)           │   │
│  │                             │                               │   │
│  │   At fence: swap ActiveSource ← NextSource                  │   │
│  │             NextSource ← fetch from queue                   │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              v                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │               SESSION-LONG ENCODER PIPELINE                   │  │
│  │                                                               │  │
│  │   - Never closed during session                               │  │
│  │   - Continuity counters maintained                            │  │
│  │   - PTS monotonically increasing                              │  │
│  │   - PAT/PMT at session start + periodic refresh               │  │
│  │                                                               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              v                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                        UDS WRITER                             │  │
│  │                                                               │  │
│  │   - Write at every tick (real or pad)                         │  │
│  │   - No blocking on content availability                       │  │
│  │                                                               │  │
│  └───────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. OutputClock (33ms tick)

```cpp
class OutputClock {
public:
    // Blocks until next frame deadline
    void WaitForNextTick();

    // Get current session time (monotonic, never resets)
    int64_t SessionTimeMs() const;

    // Get frame count since session start
    int64_t FrameCount() const;

private:
    std::chrono::steady_clock::time_point session_start_;
    std::chrono::steady_clock::time_point next_tick_;
    int64_t frame_count_ = 0;
    static constexpr int64_t kTickIntervalMs = 33;
};
```

#### 2. BlockSource (preloadable content source)

```cpp
class BlockSource {
public:
    enum class State {
        kEmpty,       // No block assigned
        kLoading,     // Probing assets, opening decoders
        kReady,       // Can produce frames
        kExhausted    // Reached fence
    };

    // Assign a block (starts background preload)
    void AssignBlock(const BlockPlan& block);

    // Get next frame (or nullptr if not ready/exhausted)
    std::unique_ptr<FrameData> GetNextFrame();

    // Check state
    State GetState() const;

    // CT position in current block
    int64_t CurrentCt() const;

    // Has reached block fence?
    bool AtFence() const;

private:
    std::atomic<State> state_{State::kEmpty};
    BlockPlan current_block_;
    RealAssetSource assets_;        // Preloaded
    FFmpegDecoder decoder_;         // Preloaded and positioned
    int64_t ct_ms_ = 0;
    std::mutex mutex_;
    std::thread preload_thread_;
};
```

#### 3. ContinuousOutputController (main loop)

```cpp
class ContinuousOutputController {
public:
    void Run() {
        // Session-long encoder already open

        while (!stop_requested_) {
            output_clock_.WaitForNextTick();

            int64_t session_pts_90k = output_clock_.FrameCount() * 33 * 90;

            // Try to get frame from active source
            std::unique_ptr<FrameData> frame = nullptr;

            if (active_source_.GetState() == BlockSource::State::kReady) {
                frame = active_source_.GetNextFrame();

                // Check for fence transition
                if (active_source_.AtFence()) {
                    // Swap sources
                    SwapSources();
                }
            }

            if (frame) {
                // Encode real content
                encoder_->encodeFrame(*frame, session_pts_90k);
            } else {
                // Encode pad frame (black+silence)
                encoder_->encodePadFrame(session_pts_90k);
            }

            // Ensure output at every tick - INV-OUTPUT-CONTINUOUS
        }
    }

private:
    void SwapSources() {
        // Active exhausted → promote next to active
        active_source_ = std::move(next_source_);

        // Fetch next block from queue and start preloading
        auto next_block = FetchNextBlock();
        if (next_block) {
            next_source_.AssignBlock(*next_block);
        } else {
            // Lookahead exhausted - will emit pad frames
            // until session termination
        }
    }

    OutputClock output_clock_;
    BlockSource active_source_;
    BlockSource next_source_;
    EncoderPipeline* encoder_;  // Session-long, not owned
};
```

### Invariant Enforcement

| Invariant | Enforcement Point |
|-----------|-------------------|
| INV-OUTPUT-CONTINUOUS | `ContinuousOutputController::Run()` - every tick produces output |
| INV-NO-CONTENT-STALL | `GetNextFrame()` returns nullptr, NOT blocks; caller emits pad |
| INV-SOURCE-PRELOAD | `BlockSource::AssignBlock()` starts background preload |
| INV-SEAMLESS-SWAP | `SwapSources()` is atomic; no tick skipped |
| INV-ENCODER-PERSISTENT | `EncoderPipeline` opened once at session start |
| INV-PTS-MONOTONIC | `session_pts_90k` computed from `output_clock_.FrameCount()` |

---

## Section C: Boundary Switch Algorithm (A/B)

### Timeline

```
Time:     T-5000ms      T-100ms       T=0 (fence)      T+33ms
          |             |             |                |
Block A:  [...frames...][...frames...]|                |
                        |             |                |
Block B:  |<--PRELOAD-->|<---READY--->|<--EXECUTING--->
          (background)   (decoder at  (first frame
                         start pos)   emitted)
```

### Preload Strategy

1. **When block A is 50% complete** (or earlier if short block):
   - Check if next_source_ is empty
   - Fetch Block B from queue
   - Call `next_source_.AssignBlock(block_b)`

2. **AssignBlock does background work**:
   - Probe all assets (avformat_open_input + find_stream_info)
   - Open decoder for first segment
   - Seek to segment start offset
   - Set state to `kReady`

3. **At fence (CT >= block_duration)**:
   - `SwapSources()` called
   - active_source_ now points to preloaded Block B
   - `GetNextFrame()` immediately returns Block B frame 0
   - No gap

### Swap Pseudocode

```cpp
void ContinuousOutputController::SwapSources() {
    std::lock_guard<std::mutex> lock(swap_mutex_);

    // Emit BlockCompleted event for old active source
    EmitBlockCompleted(active_source_.BlockId(), active_source_.FinalCt());

    // Check next source is ready
    if (next_source_.GetState() != BlockSource::State::kReady) {
        // NOT ready - this is a preload failure
        // Log warning but continue - will emit pad frames
        std::cerr << "[WARN] Source swap but next not ready - will pad" << std::endl;
    }

    // Atomic swap
    active_source_ = std::move(next_source_);

    // Start preloading the one after
    auto next_block = FetchNextBlockFromQueue();
    if (next_block) {
        next_source_.AssignBlock(*next_block);
    } else {
        // Lookahead exhausted - session will terminate after current block
        lookahead_exhausted_ = true;
    }
}
```

### PTS Model at Boundary

```
Block A (5000ms):
  Frame 0:   session_pts = 0
  Frame 151: session_pts = 151 * 33 * 90 = 448,470 (4983ms)
  [FENCE at CT=5016ms, but we output at 33ms cadence so last frame is CT=4983]

Block B (5000ms):
  Frame 152: session_pts = 152 * 33 * 90 = 451,440 (5016ms)  <- NO GAP
  Frame 153: session_pts = 153 * 33 * 90 = 454,410 (5049ms)
  ...
```

**Key insight**: Session PTS is computed from `output_clock_.FrameCount()`, not from block CT. This ensures monotonic PTS regardless of block boundaries.

---

## Section D: Timestamp/DTS Strategy and Fixes

### Current DTS Issue Analysis

**Symptom**: VLC/ffplay report "DTS out of order" at block boundaries.

**Root Causes**:

1. **FIXED**: Per-block encoder reinit - now using session-long encoder
2. **REMAINING**: CT-based PTS calculation has block-relative component

**Current code** (`RealTimeExecution.cpp:232-239`):
```cpp
if (last_ct_ms_ >= 0 && frame.ct_ms < last_ct_ms_) {
    // CT dropped - block transition
    pts_offset_90k_ += (last_ct_ms_ + kFrameDurationMs) * 90;
}
int64_t pts_90k = frame.ct_ms * 90 + pts_offset_90k_;
```

**Problem**: This calculation is complex and error-prone. If block B's first CT is not exactly 0, or if timing is off, PTS can be wrong.

### Correct Solution: Session-Based PTS

Replace CT-relative PTS with session-absolute PTS:

```cpp
// In ContinuousOutputController::Run():
int64_t frame_index = output_clock_.FrameCount();
int64_t session_pts_90k = frame_index * 3003;  // 33.37ms in 90kHz units (for 29.97fps)
// OR for 30fps:
int64_t session_pts_90k = frame_index * 3000;  // 33.33ms in 90kHz units

encoder_->encodeFrame(frame, session_pts_90k);
```

**This guarantees**:
- PTS is always monotonically increasing (frame_index always increases)
- PTS never depends on block CT (which resets)
- No complex offset tracking needed

### DTS vs PTS for B-frames

For encoders with B-frames, DTS < PTS. FFmpeg handles this internally:
- DTS = PTS - (B-frame delay)
- The muxer tracks this automatically

**The "DTS out of order" warnings occur when**:
1. Encoder is reset (DTS tracking lost) - FIXED with session-long encoder
2. PTS jumps backwards (not possible with session-based PTS)
3. Timestamp calculation error (fixed with simple formula)

### PAT/PMT Strategy

**Current**: PAT/PMT written once in `avformat_write_header()`.

**Required for broadcast**:
- PAT: Every 100ms (per DVB spec) or at least every 500ms
- PMT: Every 100ms or at least every 500ms

**Fix**: Use mpegts muxer option:
```cpp
// In EncoderPipeline::open():
av_dict_set(&muxer_opts, "mpegts_flags", "resend_headers+pat_pmt_at_frames", 0);
av_dict_set(&muxer_opts, "sdt_period", "0.5", 0);  // 500ms
av_dict_set(&muxer_opts, "pat_period", "0.1", 0);  // 100ms
```

---

## Section E: Tests + Manual Proof Steps

### Automated Contract Tests

#### TEST-OUTPUT-001: No Inter-Frame Gap > 40ms

```cpp
// File: pkg/air/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp

TEST(ContinuousOutput, NoGapExceedsFrameDuration) {
    // Setup: Create test harness that captures TS packet timestamps
    MockTsCapture capture;
    ContinuousOutputController controller(&capture, test_encoder);

    // Feed 2 blocks (5s each = 304 frames)
    controller.FeedBlock(CreateTestBlock(0, 5000));
    controller.FeedBlock(CreateTestBlock(5000, 10000));

    // Run for 10 seconds of simulated time
    controller.RunFor(std::chrono::seconds(10));

    // Verify: Check inter-packet gaps
    auto packets = capture.GetPackets();
    ASSERT_GE(packets.size(), 300);  // At least 300 packets

    for (size_t i = 1; i < packets.size(); ++i) {
        int64_t gap_ms = (packets[i].pts - packets[i-1].pts) / 90;
        EXPECT_LE(gap_ms, 40) << "Gap at packet " << i << " was " << gap_ms << "ms";
    }
}
```

#### TEST-OUTPUT-002: Block Boundary Produces Continuous TS

```cpp
TEST(ContinuousOutput, BlockBoundaryContinuous) {
    MockTsCapture capture;
    ContinuousOutputController controller(&capture, test_encoder);

    // Specifically test the boundary
    controller.FeedBlock(CreateTestBlock(0, 5000));
    controller.FeedBlock(CreateTestBlock(5000, 10000));

    controller.RunFor(std::chrono::seconds(10));

    // Find packets around the 5000ms boundary
    auto packets = capture.GetPackets();
    int64_t boundary_pts_90k = 5000 * 90;  // 450000

    int64_t prev_pts = -1;
    for (const auto& pkt : packets) {
        if (pkt.pts >= boundary_pts_90k - 6000 && pkt.pts <= boundary_pts_90k + 6000) {
            if (prev_pts >= 0) {
                int64_t delta = pkt.pts - prev_pts;
                // Should be ~3000 (one frame duration in 90kHz)
                EXPECT_GE(delta, 2900);
                EXPECT_LE(delta, 3100);
            }
            prev_pts = pkt.pts;
        }
    }

    // Verify encoder was NOT reinitialized
    EXPECT_EQ(test_encoder->InitCount(), 1) << "Encoder should init exactly once";
}
```

#### TEST-TUNEIN-001: First TS Packet Within 250ms

```cpp
TEST(ContinuousOutput, FastTuneIn) {
    MockTsCapture capture;

    auto start = std::chrono::steady_clock::now();

    ContinuousOutputController controller(&capture, test_encoder);
    controller.FeedBlock(CreateTestBlock(0, 5000));
    controller.Start();

    // Wait for first packet
    while (capture.GetPackets().empty() &&
           std::chrono::steady_clock::now() - start < std::chrono::seconds(5)) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    auto first_packet_time = std::chrono::steady_clock::now();
    auto latency_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        first_packet_time - start).count();

    EXPECT_LE(latency_ms, 250) << "First packet took " << latency_ms << "ms";

    // Verify first packet contains PAT/PMT
    auto packets = capture.GetPackets();
    ASSERT_FALSE(packets.empty());
    EXPECT_TRUE(packets[0].has_pat) << "First packet should contain PAT";
}
```

### Manual Verification Procedure

#### Step 1: Start Server

```bash
source pkg/core/.venv/bin/activate
python -m retrovue.runtime.verify_first_on_air --server
```

**Expected logs**:
```
[INFO] FIRST-ON-AIR: Starting Verification Server
[INFO] Server listening on http://0.0.0.0:9999
```

#### Step 2: Connect ffplay

```bash
ffplay -fflags nobuffer -flags low_delay -probesize 32 \
       http://127.0.0.1:9999/channel/mock.ts 2>&1 | tee ffplay.log
```

**Expected behavior**:
- Video appears within 1 second
- No "DTS out of order" warnings
- Continuous playback (no freezes)

#### Step 3: Monitor Server Logs

**Look for these lines**:
```
[BlockPlanExecution] Session encoder opened: 640x480 @ 30fps
[METRIC] first_packet_latency_ms=XXX      # Should be < 250
[RealTimeEncoderSink] Using shared session encoder (no re-init)
[BlockPlanExecution] Block BLOCK-mock-0 completed: ct=5016ms
[METRIC] boundary_gap_ms=XXX              # Should be < 40
[RealTimeEncoderSink] Using shared session encoder (no re-init)  # SAME encoder
```

**Bad signs**:
```
[WARN] Source swap but next not ready - will pad  # Preload failed
[METRIC] boundary_gap_ms=22000                     # THE BUG - 22s gap
```

#### Step 4: Let Play for 30+ Seconds

Watch for block transitions (every 5s). Each transition should be seamless.

#### Step 5: Disconnect

Press Ctrl+C in ffplay. Server should log:
```
[INFO] INV-VIEWER-LIFECYCLE-002: Last viewer left
[BlockPlanExecution] Session encoder closed
```

#### Step 6: Verify ffplay.log

```bash
grep -E "(DTS|corrupt|discontinuity)" ffplay.log
```

**Expected**: No output (no errors)

---

## Section F: Minimal Code-Change Plan

### Phase 1: Instrumentation (Diagnose)

**Files**:
- `pkg/air/src/playout_service.cpp`
- `pkg/air/src/blockplan/RealTimeExecution.cpp`

**Changes**:
- Add timing metrics at all transition points
- Capture and log:
  - `block_fetch_time_ms`
  - `asset_probe_time_ms` (per asset)
  - `decoder_open_time_ms`
  - `boundary_gap_ms` (time between last frame of block N and first frame of block N+1)
  - `first_frame_latency_ms` (from session start)

### Phase 2: Preload Infrastructure (Reduce Gap)

**New Files**:
- `pkg/air/include/retrovue/blockplan/BlockSource.hpp`
- `pkg/air/src/blockplan/BlockSource.cpp`

**Changes**:
- Create `BlockSource` class with background preload
- Modify `BlockPlanExecutionThread` to use two BlockSources (A/B)
- Start preloading Block B when Block A is 50% complete

### Phase 3: Continuous Output Loop (Guarantee R2)

**New Files**:
- `pkg/air/include/retrovue/blockplan/ContinuousOutputController.hpp`
- `pkg/air/src/blockplan/ContinuousOutputController.cpp`
- `pkg/air/include/retrovue/blockplan/OutputClock.hpp`

**Changes**:
- Create `OutputClock` with fixed 33ms tick
- Create `ContinuousOutputController` as the main execution loop
- Replace `BlockPlanExecutionThread` with `ContinuousOutputController::Run()`
- Add `encodePadFrame()` to `EncoderPipeline`

### Phase 4: Fast Tune-in (R1)

**Files**:
- `pkg/air/src/playout_sinks/mpegts/EncoderPipeline.cpp`

**Changes**:
- Emit pad frames immediately on encoder open (no wait for content)
- Set `zerolatency` preset for x264 or equivalent for NVENC
- Reduce encoder lookahead to minimum (1-2 frames)
- Emit first keyframe within 100ms

### Phase 5: Contract Tests

**New Files**:
- `pkg/air/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp`

**Changes**:
- Add TEST-OUTPUT-001, TEST-OUTPUT-002, TEST-TUNEIN-001
- Add to CMakeLists.txt

### Summary of Key Functions to Edit

| File | Function | Change |
|------|----------|--------|
| `playout_service.cpp` | `BlockPlanExecutionThread` | Replace with ContinuousOutputController |
| `RealTimeExecution.cpp` | `RealTimeBlockExecutor::Execute` | Remove (replaced by continuous loop) |
| `EncoderPipeline.cpp` | `open()` | Emit first PAT/PMT immediately |
| `EncoderPipeline.cpp` | NEW: `encodePadFrame()` | Generate black+silence frame |
| NEW: `BlockSource.cpp` | `AssignBlock()` | Background asset probe + decoder open |
| NEW: `ContinuousOutputController.cpp` | `Run()` | Main 33ms tick loop |

---

## Architectural Note

This design preserves all existing invariants:
- **Core is reactive; AIR is autonomous**: No change. Core still feeds blocks, AIR executes autonomously.
- **2-block lookahead**: Preserved. BlockSource A/B provides the same window.
- **No mid-block control-plane chatter**: Preserved. Only BlockCompleted/SessionEnded events.
- **Padding is timing enforcement**: Explicit. Pad frames maintain cadence when content unavailable.

The key architectural change is moving from **serial block execution** to **continuous output with source switching**. This is the minimal change required to meet broadcast requirements.
