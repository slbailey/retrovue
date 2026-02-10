// Repository: Retrovue-playout
// Component: Lookahead Buffer Contract Tests
// Purpose: Enforce the tick-thread-never-decodes model for both video and audio.
//
// Contracts under test:
//   INV-VIDEO-LOOKAHEAD-001  — Video lookahead buffer authority
//   INV-AUDIO-LOOKAHEAD-001  — Audio lookahead buffer authority
//
// Required outcomes:
//   1. Tick emission MUST NOT call decode APIs on the tick thread (A/V).
//   2. Artificial decode stalls MUST NOT disrupt A/V while buffers have headroom.
//   3. Buffer underflow MUST stop/detach the session — no silence/pad/hold.
//   4. Fence tick cuts MUST deliver next block A/V at exactly the scheduled tick
//      index, even under stall injection.
//
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <optional>
#include <set>
#include <thread>
#include <vector>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Test Infrastructure
// =============================================================================

// Helper: create a video Frame with given dimensions and Y-plane fill.
static buffer::Frame MakeVideoFrame(int w, int h, uint8_t y_fill = 0x10) {
  buffer::Frame f;
  f.width = w;
  f.height = h;
  int y_sz = w * h;
  int uv_sz = (w / 2) * (h / 2);
  f.data.resize(static_cast<size_t>(y_sz + 2 * uv_sz));
  std::memset(f.data.data(), y_fill, static_cast<size_t>(y_sz));
  std::memset(f.data.data() + y_sz, 0x80, static_cast<size_t>(2 * uv_sz));
  return f;
}

// Helper: create an AudioFrame with N samples.
static buffer::AudioFrame MakeAudioFrame(int nb_samples, int16_t fill = 0) {
  buffer::AudioFrame af;
  af.sample_rate = buffer::kHouseAudioSampleRate;
  af.channels = buffer::kHouseAudioChannels;
  af.nb_samples = nb_samples;
  af.data.resize(
      static_cast<size_t>(nb_samples * buffer::kHouseAudioChannels) *
          sizeof(int16_t),
      0);
  if (fill != 0) {
    auto* s = reinterpret_cast<int16_t*>(af.data.data());
    for (int i = 0; i < nb_samples * buffer::kHouseAudioChannels; i++) {
      s[i] = fill;
    }
  }
  return af;
}

// Poll until condition is true (with timeout).
template <typename Pred>
static bool WaitFor(Pred pred, std::chrono::milliseconds timeout) {
  auto dl = std::chrono::steady_clock::now() + timeout;
  while (!pred()) {
    if (std::chrono::steady_clock::now() > dl) return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  return true;
}

// ---------------------------------------------------------------------------
// ThreadTrackingProducer — records which thread calls TryGetFrame.
//
// Used by the "tick thread never decodes" tests. Every call to TryGetFrame()
// records the calling thread's ID.  After the test the caller asserts that
// none of those IDs match the tick/test thread.
// ---------------------------------------------------------------------------
class ThreadTrackingProducer : public ITickProducer {
 public:
  ThreadTrackingProducer(int width, int height, double input_fps,
                         int total_frames, const std::string& asset_uri)
      : width_(width),
        height_(height),
        input_fps_(input_fps),
        frames_remaining_(total_frames),
        total_frames_(total_frames),
        asset_uri_(asset_uri) {
    frame_duration_ms_ =
        input_fps > 0.0 ? static_cast<int64_t>(1000.0 / input_fps) : 33;
  }

  // ITickProducer
  void AssignBlock(const FedBlock& blk) override { block_ = blk; }

  std::optional<FrameData> TryGetFrame() override {
    // Record calling thread.
    {
      std::lock_guard<std::mutex> lock(tid_mutex_);
      decode_tids_.push_back(std::this_thread::get_id());
    }

    // Primed frame path.
    if (has_primed_) {
      has_primed_ = false;
      return std::move(*primed_frame_);
    }

    // Optional decode delay.
    if (decode_delay_.count() > 0) {
      std::this_thread::sleep_for(decode_delay_);
    }

    std::lock_guard<std::mutex> lock(data_mutex_);
    if (frames_remaining_ <= 0) return std::nullopt;
    frames_remaining_--;
    int idx = total_frames_ - frames_remaining_ - 1;

    FrameData fd;
    fd.video = MakeVideoFrame(
        width_, height_, static_cast<uint8_t>(0x10 + (idx % 200)));
    fd.asset_uri = asset_uri_;
    fd.block_ct_ms = idx * frame_duration_ms_;
    fd.audio.push_back(MakeAudioFrame(1600));
    return fd;
  }

  void Reset() override {
    std::lock_guard<std::mutex> lock(data_mutex_);
    frames_remaining_ = 0;
  }

  State GetState() const override { return State::kReady; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override { return total_frames_; }
  bool HasDecoder() const override { return true; }
  double GetInputFPS() const override { return input_fps_; }
  bool HasPrimedFrame() const override { return has_primed_; }

  const std::vector<SegmentBoundary>& GetBoundaries() const override {
    static const std::vector<SegmentBoundary> empty;
    return empty;
  }

  // Test helpers
  void SetPrimedFrame(FrameData fd) {
    primed_frame_ = std::move(fd);
    has_primed_ = true;
  }

  void SetDecodeDelay(std::chrono::milliseconds d) { decode_delay_ = d; }

  // Thread tracking queries (call after stopping fill thread).
  std::vector<std::thread::id> GetDecodeTids() const {
    std::lock_guard<std::mutex> lock(tid_mutex_);
    return decode_tids_;
  }

  bool AnyDecodeFromThread(std::thread::id tid) const {
    std::lock_guard<std::mutex> lock(tid_mutex_);
    return std::any_of(decode_tids_.begin(), decode_tids_.end(),
                       [tid](auto id) { return id == tid; });
  }

  int DecodeCount() const {
    std::lock_guard<std::mutex> lock(tid_mutex_);
    return static_cast<int>(decode_tids_.size());
  }

  int FramesRemaining() const {
    std::lock_guard<std::mutex> lock(data_mutex_);
    return frames_remaining_;
  }

 private:
  int width_, height_;
  double input_fps_;
  int64_t frame_duration_ms_;
  mutable std::mutex data_mutex_;
  int frames_remaining_;
  int total_frames_;
  std::string asset_uri_;
  FedBlock block_;

  bool has_primed_ = false;
  std::optional<FrameData> primed_frame_;
  std::chrono::milliseconds decode_delay_{0};

  mutable std::mutex tid_mutex_;
  std::vector<std::thread::id> decode_tids_;
};

// =============================================================================
// SECTION 1 — TICK THREAD NEVER DECODES
//
// INV-VIDEO-LOOKAHEAD-001 R1 / INV-AUDIO-LOOKAHEAD-001 R1
// The tick loop thread MUST NOT call decode APIs (TryGetFrame,
// DecodeFrameToBuffer, GetPendingAudioFrame) at any point after
// the fill thread is started.
// =============================================================================

// ---- 1a: Video decode runs exclusively on the fill thread ----
TEST(LookaheadContract, TickThread_NeverCallsVideoDecodeAPIs) {
  constexpr int kTargetDepth = 10;
  constexpr int kSourceFrames = 200;
  const std::thread::id tick_tid = std::this_thread::get_id();

  VideoLookaheadBuffer buf(kTargetDepth);
  ThreadTrackingProducer prod(64, 48, 30.0, kSourceFrames, "a.mp4");
  std::atomic<bool> stop{false};

  // Start fill thread.
  buf.StartFilling(&prod, nullptr, 30.0, 30.0, &stop);

  // Wait for buffer to reach target depth.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= kTargetDepth; },
                       std::chrono::milliseconds(1000)));

  // Simulate 60 tick-loop iterations on THIS (tick) thread.
  // The tick thread ONLY pops — never decodes.
  for (int t = 0; t < 60; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf))
        << "Unexpected underflow at tick " << t;
    // Minimal sleep to simulate 30fps cadence and give fill thread time.
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  buf.StopFilling(false);

  // ASSERT: zero TryGetFrame calls originated from the tick thread.
  EXPECT_FALSE(prod.AnyDecodeFromThread(tick_tid))
      << "INV-VIDEO-LOOKAHEAD-001 R1 violation: decode API called on tick thread";

  // All decode calls came from exactly one other thread (the fill thread).
  auto tids = prod.GetDecodeTids();
  std::set<std::thread::id> unique_tids(tids.begin(), tids.end());
  unique_tids.erase(tick_tid);
  EXPECT_EQ(unique_tids.size(), 1u)
      << "All decode calls must originate from a single fill thread";
}

// ---- 1b: Audio decode also runs exclusively on the fill thread ----
// Audio frames are produced as a side-effect of video decode (inside
// TryGetFrame). Proving video decode is off the tick thread also proves
// audio decode is off the tick thread.  This test verifies that the
// AudioLookaheadBuffer receives pushes only from the fill thread by
// checking that audio samples are available without the tick thread
// ever having called any decode API.
TEST(LookaheadContract, TickThread_NeverCallsAudioDecodeAPIs) {
  const std::thread::id tick_tid = std::this_thread::get_id();

  VideoLookaheadBuffer vbuf(10);
  AudioLookaheadBuffer abuf(1000);
  ThreadTrackingProducer prod(64, 48, 30.0, 200, "a.mp4");
  std::atomic<bool> stop{false};

  vbuf.StartFilling(&prod, &abuf, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return vbuf.DepthFrames() >= 10; },
                       std::chrono::milliseconds(1000)));

  // Tick thread consumes video and audio — never decodes.
  for (int t = 0; t < 30; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(vbuf.TryPopFrame(vbf));

    // Pop audio (1600 samples for 30fps @ 48kHz).
    buffer::AudioFrame af;
    if (abuf.IsPrimed()) {
      abuf.TryPopSamples(1600, af);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  vbuf.StopFilling(false);

  // Audio was pushed (by fill thread) and popped (by tick thread)
  // without the tick thread ever calling TryGetFrame.
  EXPECT_FALSE(prod.AnyDecodeFromThread(tick_tid))
      << "INV-AUDIO-LOOKAHEAD-001 R1 violation: decode API called on tick thread";
  EXPECT_GT(abuf.TotalSamplesPushed(), 0)
      << "Audio must have been pushed by fill thread";
  EXPECT_GT(abuf.TotalSamplesPopped(), 0)
      << "Audio must have been consumed by tick thread";
}

// ---- 1c: Primed frame retrieval is the only tick-thread exception ----
// StartFilling() may consume the primed frame on the calling (tick) thread.
// This is non-blocking by contract (INV-BLOCK-PRIME-002).  Verify that
// after StartFilling, no further TryGetFrame calls come from the tick thread.
TEST(LookaheadContract, TickThread_PrimedFrameIsOnlyException) {
  const std::thread::id tick_tid = std::this_thread::get_id();

  VideoLookaheadBuffer buf(10);
  ThreadTrackingProducer prod(64, 48, 30.0, 200, "a.mp4");
  std::atomic<bool> stop{false};

  // Arm a primed frame.
  FrameData primed;
  primed.video = MakeVideoFrame(64, 48, 0xAA);
  primed.asset_uri = "primed.mp4";
  primed.block_ct_ms = 0;
  primed.audio.push_back(MakeAudioFrame(1024));
  prod.SetPrimedFrame(std::move(primed));

  // StartFilling will consume primed frame on tick thread.
  buf.StartFilling(&prod, nullptr, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 10; },
                       std::chrono::milliseconds(1000)));

  // Pop 30 frames on tick thread.
  for (int t = 0; t < 30; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf));
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  buf.StopFilling(false);

  // At most ONE TryGetFrame call from tick thread (the primed frame).
  auto tids = prod.GetDecodeTids();
  int tick_thread_calls = static_cast<int>(
      std::count(tids.begin(), tids.end(), tick_tid));
  EXPECT_LE(tick_thread_calls, 1)
      << "At most one decode call (primed frame) may originate from tick thread";

  // All other calls must be from the fill thread.
  int fill_thread_calls = static_cast<int>(tids.size()) - tick_thread_calls;
  EXPECT_GT(fill_thread_calls, 0)
      << "Fill thread must have performed decode calls";
}

// =============================================================================
// SECTION 2 — DECODE STALLS ABSORBED BY BUFFER HEADROOM
//
// INV-VIDEO-LOOKAHEAD-001 R5 / INV-AUDIO-LOOKAHEAD-001 R3
// When decode stalls but buffers have headroom, A/V output MUST
// continue uninterrupted.
// =============================================================================

// ---- 2a: Video buffer absorbs decode stall ----
TEST(LookaheadContract, VideoDecodeStall_BufferAbsorbsLatency) {
  constexpr int kTargetDepth = 15;

  VideoLookaheadBuffer buf(kTargetDepth);
  ThreadTrackingProducer prod(64, 48, 30.0, 500, "a.mp4");
  std::atomic<bool> stop{false};

  buf.StartFilling(&prod, nullptr, 30.0, 30.0, &stop);

  // Wait for full buffer.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= kTargetDepth; },
                       std::chrono::milliseconds(1000)));

  // Inject a decode stall: 25ms per frame.
  // At 30fps (33ms/frame), 25ms decode leaves ~8ms slack.
  // 15 frames of headroom = 500ms safety margin.
  prod.SetDecodeDelay(std::chrono::milliseconds(25));

  // Consume 60 frames at ~30fps (2 seconds).
  // Buffer should never underflow.
  int consumed = 0;
  for (int t = 0; t < 60; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf))
        << "INV-VIDEO-LOOKAHEAD-001 R5 violation: underflow at tick " << t
        << " despite buffer headroom (depth=" << buf.DepthFrames() << ")";
    consumed++;
    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }

  EXPECT_EQ(consumed, 60);
  EXPECT_EQ(buf.UnderflowCount(), 0)
      << "Zero underflows required when buffer has headroom";

  buf.StopFilling(false);
}

// ---- 2b: Audio buffer absorbs decode stall ----
// When video decode stalls, audio production stalls too (side-effect).
// The AudioLookaheadBuffer must have sufficient depth to bridge the gap.
TEST(LookaheadContract, AudioDecodeStall_BufferAbsorbsLatency) {
  constexpr int kVideoTargetDepth = 15;

  VideoLookaheadBuffer vbuf(kVideoTargetDepth);
  AudioLookaheadBuffer abuf(1000);
  ThreadTrackingProducer prod(64, 48, 30.0, 500, "a.mp4");
  std::atomic<bool> stop{false};

  vbuf.StartFilling(&prod, &abuf, 30.0, 30.0, &stop);

  // Wait for buffers to fill.
  ASSERT_TRUE(WaitFor([&] { return vbuf.DepthFrames() >= kVideoTargetDepth; },
                       std::chrono::milliseconds(1000)));
  ASSERT_TRUE(WaitFor([&] { return abuf.IsPrimed(); },
                       std::chrono::milliseconds(1000)));

  // Inject a moderate decode stall.
  prod.SetDecodeDelay(std::chrono::milliseconds(25));

  // Consume 30 ticks (1 second).
  int audio_pops = 0;
  int64_t audio_ticks_emitted = 0;
  int64_t audio_samples_emitted = 0;

  for (int t = 0; t < 30; t++) {
    // Pop video.
    VideoBufferFrame vbf;
    ASSERT_TRUE(vbuf.TryPopFrame(vbf))
        << "Video underflow at tick " << t;

    // Pop audio: exact rational sample count (30fps @ 48kHz = 1600/tick).
    if (abuf.IsPrimed()) {
      int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
      int64_t fps_num = 30, fps_den = 1;
      int64_t next_total = ((audio_ticks_emitted + 1) * sr * fps_den) / fps_num;
      int samples_this_tick = static_cast<int>(next_total - audio_samples_emitted);

      buffer::AudioFrame af;
      if (abuf.TryPopSamples(samples_this_tick, af)) {
        audio_samples_emitted += samples_this_tick;
        audio_ticks_emitted++;
        audio_pops++;
      }
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }

  EXPECT_GT(audio_pops, 0)
      << "Audio must have been consumed during stall period";
  EXPECT_EQ(abuf.UnderflowCount(), 0)
      << "INV-AUDIO-LOOKAHEAD-001 R3 violation: audio underflow despite headroom";

  vbuf.StopFilling(false);
}

// ---- 2c: Combined A/V stall — both buffers sustain output ----
TEST(LookaheadContract, CombinedStall_BothBuffersSustainOutput) {
  VideoLookaheadBuffer vbuf(15);
  AudioLookaheadBuffer abuf(1000);
  ThreadTrackingProducer prod(64, 48, 30.0, 500, "a.mp4");
  std::atomic<bool> stop{false};

  vbuf.StartFilling(&prod, &abuf, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return vbuf.DepthFrames() >= 15; },
                       std::chrono::milliseconds(1000)));

  // Phase 1: no stall — establish steady state.
  for (int t = 0; t < 10; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(vbuf.TryPopFrame(vbf));
    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }

  // Phase 2: inject heavy stall (30ms per decode).
  prod.SetDecodeDelay(std::chrono::milliseconds(30));

  for (int t = 10; t < 40; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(vbuf.TryPopFrame(vbf))
        << "Video underflow at tick " << t << " during stall phase";
    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }

  // Phase 3: stall cleared — buffer should refill.
  prod.SetDecodeDelay(std::chrono::milliseconds(0));

  ASSERT_TRUE(WaitFor([&] { return vbuf.DepthFrames() >= 10; },
                       std::chrono::milliseconds(2000)));

  EXPECT_EQ(vbuf.UnderflowCount(), 0);
  EXPECT_EQ(abuf.UnderflowCount(), 0);

  vbuf.StopFilling(false);
}

// =============================================================================
// SECTION 3 — UNDERFLOW IS HARD FAULT
//
// INV-VIDEO-LOOKAHEAD-001 R3 / INV-AUDIO-LOOKAHEAD-001 R2
// When a primed buffer cannot satisfy a pop, the API MUST return false.
// It MUST NOT inject substitute data (silence, pad, hold-last, black).
// The caller (PipelineManager) treats false as a session-ending fault.
// =============================================================================

// ---- 3a: Video underflow returns false — no pad injected ----
TEST(LookaheadContract, VideoUnderflow_ReturnsFalse_NoPadInjected) {
  VideoLookaheadBuffer buf(5);
  ThreadTrackingProducer prod(64, 48, 30.0, 3, "a.mp4");
  std::atomic<bool> stop{false};

  buf.StartFilling(&prod, nullptr, 30.0, 30.0, &stop);

  // Wait for fill thread to exhaust content (3 real + hold-last to 5).
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(1000)));

  // Stop fill thread — no more frames will be produced.
  buf.StopFilling(false);

  // Drain all buffered frames.
  int depth = buf.DepthFrames();
  for (int i = 0; i < depth; i++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf));
  }
  EXPECT_EQ(buf.DepthFrames(), 0);

  // Next pop MUST fail — no substitute data.
  VideoBufferFrame vbf;
  bool ok = buf.TryPopFrame(vbf);

  EXPECT_FALSE(ok)
      << "INV-VIDEO-LOOKAHEAD-001 R3 violation: TryPopFrame must return false "
         "on underflow, not inject substitute data";
  EXPECT_EQ(buf.UnderflowCount(), 1);
}

// ---- 3b: Audio underflow returns false — no silence injected ----
TEST(LookaheadContract, AudioUnderflow_ReturnsFalse_NoSilenceInjected) {
  AudioLookaheadBuffer buf(1000);

  // Push exactly 3200 samples (2 ticks at 30fps @ 48kHz).
  buf.Push(MakeAudioFrame(1600, 42));
  buf.Push(MakeAudioFrame(1600, 42));
  EXPECT_TRUE(buf.IsPrimed());

  // Pop 2 ticks — succeeds.
  buffer::AudioFrame af;
  ASSERT_TRUE(buf.TryPopSamples(1600, af));
  ASSERT_TRUE(buf.TryPopSamples(1600, af));
  EXPECT_EQ(buf.DepthSamples(), 0);

  // Third pop MUST fail — no silence injected.
  buffer::AudioFrame underflow_af;
  bool ok = buf.TryPopSamples(1600, underflow_af);

  EXPECT_FALSE(ok)
      << "INV-AUDIO-LOOKAHEAD-001 R2 violation: TryPopSamples must return false "
         "on underflow, not inject silence";
  EXPECT_EQ(buf.UnderflowCount(), 1);
}

// ---- 3c: Video underflow never returns substitute data ----
// After underflow, verify the output frame was NOT modified to contain
// a pad pattern (black frame, zero data, etc.).
TEST(LookaheadContract, VideoUnderflow_NeverReturnsSubstituteData) {
  VideoLookaheadBuffer buf(5);

  // Buffer never primed — no fill thread started.
  EXPECT_FALSE(buf.IsPrimed());

  // Try to pop from empty buffer.
  VideoBufferFrame vbf;
  vbf.was_decoded = true;  // set to known state
  vbf.asset_uri = "sentinel";
  vbf.block_ct_ms = 999;

  bool ok = buf.TryPopFrame(vbf);
  EXPECT_FALSE(ok);

  // The output struct must NOT have been modified with substitute data.
  // A correct implementation leaves the struct untouched on failure.
  EXPECT_EQ(vbf.asset_uri, "sentinel")
      << "Output struct must not be modified on underflow";
  EXPECT_EQ(vbf.block_ct_ms, 999)
      << "Output struct must not be modified on underflow";
}

// ---- 3d: Audio underflow never returns substitute data ----
TEST(LookaheadContract, AudioUnderflow_NeverReturnsSubstituteData) {
  AudioLookaheadBuffer buf(1000);

  // Push 100 samples then try to pop 200 — underflow.
  buf.Push(MakeAudioFrame(100, 42));

  buffer::AudioFrame af;
  af.nb_samples = 999;  // sentinel

  bool ok = buf.TryPopSamples(200, af);
  EXPECT_FALSE(ok);
  EXPECT_EQ(buf.UnderflowCount(), 1);

  // Buffer should still contain the 100 samples (not consumed on underflow).
  EXPECT_EQ(buf.DepthSamples(), 100)
      << "Buffer must be untouched after underflow";
}

// ---- 3e: Sequential underflows accumulate ----
TEST(LookaheadContract, UnderflowCount_Accumulates) {
  VideoLookaheadBuffer vbuf(5);
  AudioLookaheadBuffer abuf(1000);

  VideoBufferFrame vbf;
  buffer::AudioFrame af;

  EXPECT_FALSE(vbuf.TryPopFrame(vbf));
  EXPECT_FALSE(vbuf.TryPopFrame(vbf));
  EXPECT_FALSE(vbuf.TryPopFrame(vbf));
  EXPECT_EQ(vbuf.UnderflowCount(), 3);

  EXPECT_FALSE(abuf.TryPopSamples(1600, af));
  EXPECT_FALSE(abuf.TryPopSamples(1600, af));
  EXPECT_EQ(abuf.UnderflowCount(), 2);
}

// =============================================================================
// SECTION 4 — FENCE TICK PRECISION
//
// INV-VIDEO-LOOKAHEAD-001 R4 + INV-BLOCK-WALLFENCE-004
// At the fence tick, the A/B swap MUST deliver the new block's first
// frame on exactly the scheduled tick index.  Even under decode stalls
// the fence tick frame MUST come from the new block.
// =============================================================================

// ---- 4a: Fence tick delivers next block frame at exact index ----
TEST(LookaheadContract, FenceTick_DeliversNextBlock_ExactIndex) {
  constexpr int kFenceTick = 30;
  constexpr int kTotalTicksAfterFence = 10;

  // Block A producer — identifiable by asset_uri.
  ThreadTrackingProducer block_a(64, 48, 30.0, 500, "block_a.mp4");

  // Block B producer — with primed frame.
  ThreadTrackingProducer block_b(64, 48, 30.0, 500, "block_b.mp4");
  FrameData primed_b;
  primed_b.video = MakeVideoFrame(64, 48, 0xBB);
  primed_b.asset_uri = "block_b.mp4";
  primed_b.block_ct_ms = 0;
  primed_b.audio.push_back(MakeAudioFrame(1024));
  block_b.SetPrimedFrame(std::move(primed_b));

  VideoLookaheadBuffer buf(10);
  AudioLookaheadBuffer abuf(1000);
  std::atomic<bool> stop{false};

  // Phase 1: Fill with block A.
  buf.StartFilling(&block_a, &abuf, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 10; },
                       std::chrono::milliseconds(1000)));

  // Consume ticks 0 through fence-1 from block A at ~30fps pace.
  for (int t = 0; t < kFenceTick; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf))
        << "Underflow before fence at tick " << t;
    EXPECT_EQ(vbf.asset_uri, "block_a.mp4")
        << "Pre-fence frames must be from block A";
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  // Phase 2: Fence transition — stop, flush, start with block B.
  buf.StopFilling(/*flush=*/true);
  EXPECT_FALSE(buf.IsPrimed());
  EXPECT_EQ(buf.DepthFrames(), 0);

  buf.StartFilling(&block_b, &abuf, 30.0, 30.0, &stop);

  // Phase 3: Pop the fence tick frame — MUST be from block B.
  VideoBufferFrame fence_frame;
  ASSERT_TRUE(buf.TryPopFrame(fence_frame))
      << "Fence tick frame must be available immediately (primed frame)";
  EXPECT_EQ(fence_frame.asset_uri, "block_b.mp4")
      << "INV-VIDEO-LOOKAHEAD-001 R4 violation: fence tick frame must be from "
         "the next block";
  EXPECT_TRUE(fence_frame.was_decoded)
      << "Fence tick frame should be a decoded frame (primed)";
  // Y-plane fill should match the primed frame.
  EXPECT_EQ(fence_frame.video.data[0], 0xBB);

  // Continue consuming from block B.
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 5; },
                       std::chrono::milliseconds(1000)));
  for (int t = 0; t < kTotalTicksAfterFence; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf));
    EXPECT_EQ(vbf.asset_uri, "block_b.mp4")
        << "Post-fence frames must be from block B";
  }

  buf.StopFilling(false);
}

// ---- 4b: Fence tick precision preserved under decode stall ----
// Block A has a decode stall.  Despite the stall, the fence fires at
// the scheduled tick and the new block's frame is emitted on time.
TEST(LookaheadContract, FenceTick_PrecisionPreservedUnderStall) {
  constexpr int kFenceTick = 20;

  // Block A: 20ms decode delay.
  ThreadTrackingProducer block_a(64, 48, 30.0, 500, "block_a.mp4");
  block_a.SetDecodeDelay(std::chrono::milliseconds(20));

  // Block B: primed frame, no delay.
  ThreadTrackingProducer block_b(64, 48, 30.0, 500, "block_b.mp4");
  FrameData primed_b;
  primed_b.video = MakeVideoFrame(64, 48, 0xCC);
  primed_b.asset_uri = "block_b.mp4";
  primed_b.block_ct_ms = 0;
  primed_b.audio.push_back(MakeAudioFrame(1024));
  block_b.SetPrimedFrame(std::move(primed_b));

  VideoLookaheadBuffer buf(15);
  AudioLookaheadBuffer abuf(1000);
  std::atomic<bool> stop{false};

  // Fill with block A (with stall — fill thread is slower).
  buf.StartFilling(&block_a, &abuf, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 10; },
                       std::chrono::milliseconds(5000)));

  // Consume pre-fence ticks at real-time pace.
  for (int t = 0; t < kFenceTick; t++) {
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf))
        << "Underflow before fence at tick " << t
        << " (depth=" << buf.DepthFrames() << ")";
    std::this_thread::sleep_for(std::chrono::milliseconds(33));
  }

  // Fence transition.
  buf.StopFilling(/*flush=*/true);
  buf.StartFilling(&block_b, &abuf, 30.0, 30.0, &stop);

  // Fence tick frame: MUST be from block B, available immediately.
  VideoBufferFrame fence_frame;
  ASSERT_TRUE(buf.TryPopFrame(fence_frame))
      << "Fence tick frame must be available despite prior stall";
  EXPECT_EQ(fence_frame.asset_uri, "block_b.mp4")
      << "INV-VIDEO-LOOKAHEAD-001 R4 violation: fence tick frame must be from "
         "new block even under prior decode stall";
  EXPECT_EQ(fence_frame.video.data[0], 0xCC);

  buf.StopFilling(false);
}

// ---- 4c: Audio is available at fence tick from new block ----
// At the fence, the new block's first audio frames must be available
// in the AudioLookaheadBuffer (pushed by the fill thread during
// primed frame consumption in StartFilling).
TEST(LookaheadContract, FenceTick_AudioAvailableFromNewBlock) {
  ThreadTrackingProducer block_a(64, 48, 30.0, 500, "block_a.mp4");
  ThreadTrackingProducer block_b(64, 48, 30.0, 500, "block_b.mp4");

  // Block B has a primed frame with identifiable audio (fill=77).
  FrameData primed_b;
  primed_b.video = MakeVideoFrame(64, 48, 0xDD);
  primed_b.asset_uri = "block_b.mp4";
  primed_b.block_ct_ms = 0;
  primed_b.audio.push_back(MakeAudioFrame(1024, 77));
  block_b.SetPrimedFrame(std::move(primed_b));

  VideoLookaheadBuffer vbuf(10);
  AudioLookaheadBuffer abuf(1000);
  std::atomic<bool> stop{false};

  // Fill with block A.
  vbuf.StartFilling(&block_a, &abuf, 30.0, 30.0, &stop);
  ASSERT_TRUE(WaitFor([&] { return vbuf.DepthFrames() >= 10; },
                       std::chrono::milliseconds(1000)));

  // Drain audio from block A.
  while (abuf.DepthSamples() >= 1600) {
    buffer::AudioFrame af;
    abuf.TryPopSamples(1600, af);
  }

  int64_t audio_before_fence = abuf.TotalSamplesPushed();

  // Fence: stop+flush video, start with block B.
  vbuf.StopFilling(/*flush=*/true);
  // Note: audio buffer is NOT flushed — audio continuity across block cuts.

  vbuf.StartFilling(&block_b, &abuf, 30.0, 30.0, &stop);

  // Audio samples from block B's primed frame should now be in the buffer.
  EXPECT_GT(abuf.TotalSamplesPushed(), audio_before_fence)
      << "Block B's primed audio must be pushed during StartFilling";

  vbuf.StopFilling(false);
}

// ---- 4d: Multiple rapid fence transitions are stable ----
TEST(LookaheadContract, FenceTick_RapidTransitions_Stable) {
  std::atomic<bool> stop{false};
  VideoLookaheadBuffer buf(5);
  AudioLookaheadBuffer abuf(1000);

  for (int block_idx = 0; block_idx < 5; block_idx++) {
    std::string uri = "block_" + std::to_string(block_idx) + ".mp4";
    ThreadTrackingProducer prod(64, 48, 30.0, 100, uri);

    FrameData primed;
    primed.video = MakeVideoFrame(64, 48, static_cast<uint8_t>(block_idx));
    primed.asset_uri = uri;
    primed.block_ct_ms = 0;
    primed.audio.push_back(MakeAudioFrame(1024));
    prod.SetPrimedFrame(std::move(primed));

    buf.StartFilling(&prod, &abuf, 30.0, 30.0, &stop);

    // Verify first frame is from this block.
    ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 1; },
                         std::chrono::milliseconds(500)));
    VideoBufferFrame vbf;
    ASSERT_TRUE(buf.TryPopFrame(vbf));
    EXPECT_EQ(vbf.asset_uri, uri)
        << "Fence frame for block " << block_idx << " must be from that block";
    EXPECT_EQ(vbf.video.data[0], static_cast<uint8_t>(block_idx));

    // Pop a few more frames from this block.
    ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 3; },
                         std::chrono::milliseconds(500)));
    for (int t = 0; t < 3; t++) {
      ASSERT_TRUE(buf.TryPopFrame(vbf));
    }

    // Stop+flush before next block.
    buf.StopFilling(/*flush=*/true);
  }

  EXPECT_EQ(buf.UnderflowCount(), 0)
      << "No underflows across rapid block transitions";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
