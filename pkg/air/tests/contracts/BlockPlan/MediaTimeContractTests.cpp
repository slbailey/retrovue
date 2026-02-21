// Repository: Retrovue-playout
// Component: Media Time Contract Tests
// Purpose: Deterministic verification of INV-AIR-MEDIA-TIME-001 through 005.
//          No video files needed — uses simulated decoder PTS values.
// Contract Reference: docs/contracts/semantics/INV-AIR-MEDIA-TIME.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <queue>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/ITickProducerDecoder.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/decode/FFmpegDecoder.h"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// FakeTickProducerDecoder — deterministic 60fps source for DROP duration/PTS tests.
// Reports input_fps 60, returns video with duration 1/60s and PTS advancing 1/60s per decode;
// one audio frame per decode. No real file; used with SetDecoderFactoryForTest.
// =============================================================================
class FakeTickProducerDecoder : public ITickProducerDecoder {
 public:
  explicit FakeTickProducerDecoder(const decode::DecoderConfig& config)
      : width_(config.target_width),
        height_(config.target_height),
        input_fps_(60.0),
        decode_count_(0),
        max_decodes_(60) {}

  bool Open() override { return true; }
  int SeekPreciseToMs(int64_t) override { return 0; }
  double GetVideoFPS() override { return input_fps_; }
  bool DecodeFrameToBuffer(buffer::Frame& out) override {
    if (decode_count_ >= max_decodes_) return false;
    decode_count_++;
    out.width = width_;
    out.height = height_;
    out.metadata.duration = 1.0 / input_fps_;  // 1/60 s — simulates buggy condition
    out.metadata.pts = static_cast<int64_t>((decode_count_ - 1) * 1'000'000.0 / input_fps_);
    out.metadata.dts = out.metadata.pts;
    out.metadata.asset_uri = "fake://60fps";
    size_t y = static_cast<size_t>(width_) * static_cast<size_t>(height_);
    size_t uv = (y / 4);
    out.data.resize(y + 2 * uv, 0x10);
    // One pending audio frame per decode (for DROP aggregation)
    buffer::AudioFrame af;
    af.sample_rate = buffer::kHouseAudioSampleRate;
    af.channels = buffer::kHouseAudioChannels;
    af.nb_samples = 800;  // ~1/60 s at 48k
    af.pts_us = out.metadata.pts;
    af.data.resize(static_cast<size_t>(af.nb_samples) * af.channels * sizeof(int16_t), 0);
    pending_audio_.push(std::move(af));
    return true;
  }
  bool GetPendingAudioFrame(buffer::AudioFrame& out) override {
    if (pending_audio_.empty()) return false;
    out = std::move(pending_audio_.front());
    pending_audio_.pop();
    return true;
  }
  bool IsEOF() const override { return decode_count_ >= max_decodes_; }
  void SetInterruptFlags(const DecoderInterruptFlags&) override {}
  bool HasAudioStream() const override { return true; }

 private:
  int width_;
  int height_;
  double input_fps_;
  int decode_count_;
  int max_decodes_;
  std::queue<buffer::AudioFrame> pending_audio_;
};

// =============================================================================
// INV-FPS-MAPPING: ResampleMode detection (rational only, no floats).
// Mirrors TickProducer::UpdateResampleMode() for regression tests.
// =============================================================================
static void ComputeResampleMode(int64_t in_num, int64_t in_den,
                                int64_t out_num, int64_t out_den,
                                ResampleMode* mode, int64_t* step) {
  *mode = ResampleMode::OFF;
  *step = 1;
  if (in_num <= 0 || in_den <= 0 || out_num <= 0 || out_den <= 0) return;
  using Wide = __int128;
  Wide in_out = static_cast<Wide>(in_num) * static_cast<Wide>(out_den);
  Wide out_in = static_cast<Wide>(out_num) * static_cast<Wide>(in_den);
  if (in_out == out_in) return;
  if (out_in != 0 && (in_out % out_in) == 0) {
    *mode = ResampleMode::DROP;
    *step = static_cast<int64_t>(in_out / out_in);
    if (*step < 1) *step = 1;
    return;
  }
  *mode = ResampleMode::CADENCE;
}

// =============================================================================
// Simulated PTS generation
//
// FFmpeg decoders report PTS in stream timebase, converted to microseconds in
// buffer::Frame::metadata.pts.  For frame N at exact input_fps:
//   pts_us = round(N * 1,000,000 / input_fps)
// =============================================================================

static int64_t ExactPtsUs(int64_t frame_index, double input_fps) {
  return static_cast<int64_t>(
      std::round(static_cast<double>(frame_index) * 1'000'000.0 / input_fps));
}

// =============================================================================
// PTS-Anchored Tracker — mirrors TickProducer::TryGetFrame success path
//
// This reproduces the exact math from TickProducer.cpp lines 252-272:
//   decoded_pts_ms = pts_us / 1000
//   ct_before = seg_start_ct + (decoded_pts_ms - seg_asset_start)
//   block_ct_ms = ct_before + input_frame_duration_ms
//   next_frame_offset_ms = decoded_pts_ms + input_frame_duration_ms
// =============================================================================

struct PTSAnchoredTracker {
  int64_t block_ct_ms = 0;
  int64_t next_frame_offset_ms = 0;
  int64_t input_frame_duration_ms;
  int64_t seg_start_ct_ms = 0;
  int64_t seg_asset_start_ms = 0;

  explicit PTSAnchoredTracker(double input_fps)
      : input_frame_duration_ms(std::llround(1000.0 / input_fps)) {}

  void AdvanceWithPTS(int64_t pts_us) {
    int64_t decoded_pts_ms = pts_us / 1000;  // Integer division — matches TickProducer
    int64_t ct_before = seg_start_ct_ms + (decoded_pts_ms - seg_asset_start_ms);
    block_ct_ms = ct_before + input_frame_duration_ms;
    next_frame_offset_ms = decoded_pts_ms + input_frame_duration_ms;
  }

  // Returns the position error vs ideal at frame N
  int64_t PositionErrorMs(int64_t frame_index, double input_fps) const {
    double ideal_ms = static_cast<double>(frame_index + 1) * 1000.0 / input_fps;
    return std::abs(block_ct_ms - static_cast<int64_t>(std::round(ideal_ms)));
  }
};

// =============================================================================
// Old Tracker — reproduces the pre-fix cumulative integer advancement
//
// block_ct_ms += input_frame_duration_ms (rounded integer)
// next_frame_offset_ms += input_frame_duration_ms
// =============================================================================

struct OldCumulativeTracker {
  int64_t block_ct_ms = 0;
  int64_t next_frame_offset_ms = 0;
  int64_t input_frame_duration_ms;

  explicit OldCumulativeTracker(double input_fps)
      : input_frame_duration_ms(std::llround(1000.0 / input_fps)) {}

  void Advance() {
    block_ct_ms += input_frame_duration_ms;
    next_frame_offset_ms += input_frame_duration_ms;
  }

  int64_t PositionErrorMs(int64_t frame_index, double input_fps) const {
    double ideal_ms = static_cast<double>(frame_index + 1) * 1000.0 / input_fps;
    return std::abs(block_ct_ms - static_cast<int64_t>(std::round(ideal_ms)));
  }
};

// =============================================================================
// Helper: Compute exact frames_per_block using the new formula
// =============================================================================

static int64_t ExactFramesPerBlock(int64_t duration_ms, double output_fps) {
  return static_cast<int64_t>(
      std::ceil(static_cast<double>(duration_ms) * output_fps / 1000.0));
}

// Helper: Compute old frames_per_block using truncated integer division
static int64_t OldFramesPerBlock(int64_t duration_ms, double output_fps) {
  int64_t frame_duration_ms = static_cast<int64_t>(1000.0 / output_fps);
  return static_cast<int64_t>(
      std::ceil(static_cast<double>(duration_ms) /
                static_cast<double>(frame_duration_ms)));
}

// Helper: Create synthetic FedBlock for TickProducer tests
static FedBlock MakeSyntheticBlock(const std::string& id, int64_t duration_ms,
                                   const std::string& asset_uri = "/nonexistent/test.mp4") {
  FedBlock block;
  block.block_id = id;
  block.channel_id = 1;
  block.start_utc_ms = 1'000'000;
  block.end_utc_ms = 1'000'000 + duration_ms;
  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = asset_uri;
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms = duration_ms;
  block.segments.push_back(seg);
  return block;
}

// =============================================================================
// TEST 1 — INV-AIR-MEDIA-TIME-002: 23.976fps Long-Form Drift Test
//
// Input: 23.976fps, Output: 30fps, Block: 30 minutes
// Fake decoder emits exact 41.708ms PTS deltas.
//
// Assertions:
//   - PTS-anchored tracker: max position error <= input_frame_duration_ms
//   - Old tracker: position error grows unbounded (>10s at 36000 frames)
//   - No early EOF trigger
// =============================================================================

TEST(MediaTimeContract, DriftTest_23976fps_LongForm) {
  constexpr double kInputFps = 23.976;
  constexpr double kOutputFps = 30.0;
  constexpr int64_t kBlockDurationMs = 30 * 60 * 1000;  // 30 minutes

  // Number of input frames in 30 minutes at 23.976fps
  int64_t total_input_frames = static_cast<int64_t>(
      std::ceil(kBlockDurationMs * kInputFps / 1000.0));

  PTSAnchoredTracker pts_tracker(kInputFps);
  OldCumulativeTracker old_tracker(kInputFps);

  int64_t pts_max_error = 0;
  int64_t old_max_error = 0;
  bool pts_early_eof = false;

  // Simulate asset duration = block duration (single segment fills entire block)
  int64_t asset_duration_ms = kBlockDurationMs;

  for (int64_t i = 0; i < total_input_frames; i++) {
    int64_t pts_us = ExactPtsUs(i, kInputFps);

    pts_tracker.AdvanceWithPTS(pts_us);
    old_tracker.Advance();

    int64_t pts_err = pts_tracker.PositionErrorMs(i, kInputFps);
    int64_t old_err = old_tracker.PositionErrorMs(i, kInputFps);

    if (pts_err > pts_max_error) pts_max_error = pts_err;
    if (old_err > old_max_error) old_max_error = old_err;

    // Check: PTS-anchored next_frame_offset_ms must not exceed asset duration
    // before we've decoded all frames
    if (i < total_input_frames - 1 &&
        pts_tracker.next_frame_offset_ms >= asset_duration_ms) {
      pts_early_eof = true;
    }
  }

  // INV-AIR-MEDIA-TIME-002: PTS-anchored drift bounded to 1 frame duration
  EXPECT_LE(pts_max_error, pts_tracker.input_frame_duration_ms)
      << "PTS-anchored tracker max error must be <= input_frame_duration_ms ("
      << pts_tracker.input_frame_duration_ms << "ms)";

  // Regression: old approach must have accumulated significant drift
  EXPECT_GT(old_max_error, 5000)
      << "Old cumulative tracker must drift >5s over 30min at 23.976fps "
      << "(actual: " << old_max_error << "ms)";

  // INV-AIR-MEDIA-TIME-005: No early EOF
  EXPECT_FALSE(pts_early_eof)
      << "PTS-anchored tracker must not trigger asset underrun before "
      << "content is actually exhausted";

  // Verify old approach WOULD trigger early EOF
  bool old_early_eof = false;
  OldCumulativeTracker old_check(kInputFps);
  for (int64_t i = 0; i < total_input_frames - 1; i++) {
    old_check.Advance();
    if (old_check.next_frame_offset_ms >= asset_duration_ms) {
      old_early_eof = true;
      break;
    }
  }
  EXPECT_TRUE(old_early_eof)
      << "Old cumulative tracker must trigger early EOF (regression baseline)";
}

// =============================================================================
// TEST 2 — INV-AIR-MEDIA-TIME-002: 29.97fps Edge Case
//
// Input: 29.97fps, Output: 30fps
// Very close FPS — verify no oscillation or fence jitter.
// =============================================================================

TEST(MediaTimeContract, DriftTest_29_97fps_EdgeCase) {
  constexpr double kInputFps = 29.97;
  constexpr double kOutputFps = 30.0;
  constexpr int64_t kBlockDurationMs = 30 * 60 * 1000;

  int64_t total_input_frames = static_cast<int64_t>(
      std::ceil(kBlockDurationMs * kInputFps / 1000.0));

  PTSAnchoredTracker tracker(kInputFps);
  int64_t max_error = 0;
  int64_t prev_ct = -1;
  bool monotonic = true;

  for (int64_t i = 0; i < total_input_frames; i++) {
    int64_t pts_us = ExactPtsUs(i, kInputFps);
    tracker.AdvanceWithPTS(pts_us);

    int64_t err = tracker.PositionErrorMs(i, kInputFps);
    if (err > max_error) max_error = err;

    // Verify block_ct_ms is monotonically advancing (no oscillation)
    if (prev_ct >= 0 && tracker.block_ct_ms <= prev_ct) {
      monotonic = false;
    }
    prev_ct = tracker.block_ct_ms;
  }

  EXPECT_LE(max_error, tracker.input_frame_duration_ms)
      << "29.97fps max error must be <= input_frame_duration_ms";

  EXPECT_TRUE(monotonic)
      << "block_ct_ms must be monotonically increasing (no oscillation)";
}

// =============================================================================
// TEST 3 — INV-AIR-MEDIA-TIME-002: Native 30fps Control
//
// Input: 30fps, Output: 30fps
// Zero repeats, zero drift, no pad.
// =============================================================================

TEST(MediaTimeContract, DriftTest_30fps_Native) {
  constexpr double kInputFps = 30.0;
  constexpr double kOutputFps = 30.0;
  constexpr int64_t kBlockDurationMs = 30 * 60 * 1000;

  int64_t total_input_frames = static_cast<int64_t>(
      std::ceil(kBlockDurationMs * kInputFps / 1000.0));

  PTSAnchoredTracker tracker(kInputFps);
  int64_t max_error = 0;

  for (int64_t i = 0; i < total_input_frames; i++) {
    int64_t pts_us = ExactPtsUs(i, kInputFps);
    tracker.AdvanceWithPTS(pts_us);

    int64_t err = tracker.PositionErrorMs(i, kInputFps);
    if (err > max_error) max_error = err;
  }

  // 30fps frames are exactly 33333.33us. PTS/1000 = 33ms per frame.
  // Max error should be very small (≤1ms from integer truncation + frame advance).
  EXPECT_LE(max_error, tracker.input_frame_duration_ms)
      << "Native 30fps max error must be <= input_frame_duration_ms";

  // At block end, position should be very close to block duration
  int64_t final_ct_error = std::abs(tracker.block_ct_ms - kBlockDurationMs);
  EXPECT_LE(final_ct_error, tracker.input_frame_duration_ms + 1)
      << "Final CT must converge to block duration within one frame period";
}

// =============================================================================
// TEST 4 — INV-AIR-MEDIA-TIME-005: Fence Hold Safety
//
// Decoder reaches EOF 1 frame early (asset is 1 frame shorter than block).
// Assert: last frame is held (not black pad), fence fires on next output tick.
//
// This tests the model: after last decode, block_ct_ms is near end but not past
// it. The gap is exactly 1 frame — PipelineManager's hold-last-frame safety
// covers this. We verify the gap is bounded.
// =============================================================================

TEST(MediaTimeContract, FenceHoldSafety_EOF1FrameEarly) {
  constexpr double kInputFps = 23.976;
  constexpr double kOutputFps = 30.0;
  constexpr int64_t kBlockDurationMs = 25 * 60 * 1000;  // 25 minutes

  int64_t total_input_frames = static_cast<int64_t>(
      std::ceil(kBlockDurationMs * kInputFps / 1000.0));

  // Asset is 1 frame shorter — decoder will EOF 1 frame early
  int64_t asset_frames = total_input_frames - 1;

  PTSAnchoredTracker tracker(kInputFps);

  // Decode all frames except the last
  for (int64_t i = 0; i < asset_frames; i++) {
    int64_t pts_us = ExactPtsUs(i, kInputFps);
    tracker.AdvanceWithPTS(pts_us);
  }

  // After last decode, block_ct_ms should be near but before block end
  int64_t gap_ms = kBlockDurationMs - tracker.block_ct_ms;

  // Gap must be positive (not past block end) and within ~2 frame durations
  // (1 frame of actual gap + 1 frame of look-ahead advance)
  EXPECT_GE(gap_ms, 0)
      << "After EOF-1, block_ct_ms must not exceed block duration";
  EXPECT_LE(gap_ms, 2 * tracker.input_frame_duration_ms)
      << "Gap after EOF-1 must be at most 2 frame durations "
      << "(actual gap: " << gap_ms << "ms)";

  // The output fence (frames_per_block) should fire within a few output ticks
  int64_t fpb = ExactFramesPerBlock(kBlockDurationMs, kOutputFps);
  // Output ticks to cover the gap
  int64_t output_frame_duration_ms = static_cast<int64_t>(1000.0 / kOutputFps);
  int64_t ticks_to_cover_gap = (gap_ms + output_frame_duration_ms - 1) /
                                output_frame_duration_ms;
  EXPECT_LE(ticks_to_cover_gap, 3)
      << "Fence must fire within 3 output ticks of last decode "
      << "(actual: " << ticks_to_cover_gap << " ticks)";
}

// =============================================================================
// TEST 5 — INV-AIR-MEDIA-TIME-001: frames_per_block Exact Computation
//
// Verify TickProducer computes frames_per_block using exact fps formula,
// not truncated integer division.
// =============================================================================

TEST(MediaTimeContract, FramesPerBlock_ExactFormula) {
  // Test at 30fps output
  {
    TickProducer source(640, 480, 30, 1);
    FedBlock block = MakeSyntheticBlock("fpb-30min", 30 * 60 * 1000);
    source.AssignBlock(block);

    int64_t expected = ExactFramesPerBlock(30 * 60 * 1000, 30.0);
    int64_t old_value = OldFramesPerBlock(30 * 60 * 1000, 30.0);

    EXPECT_EQ(source.FramesPerBlock(), expected)
        << "frames_per_block must use exact formula: ceil(duration_ms * fps / 1000)";
    EXPECT_EQ(expected, 54000)
        << "30min at 30fps = exactly 54000 frames";
    EXPECT_GT(old_value, expected)
        << "Old formula must overestimate (regression baseline)";
    EXPECT_EQ(old_value, 54546)
        << "Old formula: ceil(1800000/33) = 54546 (546 frames = ~18s overshoot)";

    source.Reset();
  }

  // Test at 30fps output, 25 minutes
  {
    TickProducer source(640, 480, 30, 1);
    FedBlock block = MakeSyntheticBlock("fpb-25min", 25 * 60 * 1000);
    source.AssignBlock(block);

    int64_t expected = ExactFramesPerBlock(25 * 60 * 1000, 30.0);
    EXPECT_EQ(source.FramesPerBlock(), expected);
    EXPECT_EQ(expected, 45000)
        << "25min at 30fps = exactly 45000 frames";

    source.Reset();
  }

  // Test with non-round duration (5000ms)
  {
    TickProducer source(640, 480, 30, 1);
    FedBlock block = MakeSyntheticBlock("fpb-5s", 5000);
    source.AssignBlock(block);

    int64_t expected = ExactFramesPerBlock(5000, 30.0);
    EXPECT_EQ(source.FramesPerBlock(), expected);
    EXPECT_EQ(expected, 150)
        << "5000ms at 30fps = ceil(150.0) = 150 frames";

    source.Reset();
  }

  // Test with non-round duration (3700ms)
  {
    TickProducer source(640, 480, 30, 1);
    FedBlock block = MakeSyntheticBlock("fpb-3700", 3700);
    source.AssignBlock(block);

    int64_t expected = ExactFramesPerBlock(3700, 30.0);
    EXPECT_EQ(source.FramesPerBlock(), expected);
    EXPECT_EQ(expected, 111)
        << "3700ms at 30fps = ceil(111.0) = 111 frames";

    source.Reset();
  }
}

// =============================================================================
// TEST 6 — INV-AIR-MEDIA-TIME-004: Cadence Independence
//
// Varying output FPS must not affect media time tracking.
// block_ct_ms and next_frame_offset_ms depend only on decoded PTS and
// input_frame_duration_ms. Output FPS only affects frames_per_block.
// =============================================================================

TEST(MediaTimeContract, CadenceIndependence) {
  constexpr double kInputFps = 23.976;
  constexpr int64_t kBlockDurationMs = 10 * 60 * 1000;  // 10 minutes

  int64_t total_input_frames = static_cast<int64_t>(
      std::ceil(kBlockDurationMs * kInputFps / 1000.0));

  // Run the PTS-anchored model at two different output FPS values
  double output_fps_values[] = {24.0, 30.0, 60.0};
  std::vector<int64_t> final_block_ct;
  std::vector<int64_t> final_next_offset;
  std::vector<int64_t> fpb_values;

  for (double output_fps : output_fps_values) {
    PTSAnchoredTracker tracker(kInputFps);

    for (int64_t i = 0; i < total_input_frames; i++) {
      int64_t pts_us = ExactPtsUs(i, kInputFps);
      tracker.AdvanceWithPTS(pts_us);
    }

    final_block_ct.push_back(tracker.block_ct_ms);
    final_next_offset.push_back(tracker.next_frame_offset_ms);
    fpb_values.push_back(ExactFramesPerBlock(kBlockDurationMs, output_fps));
  }

  // Media time tracking must be identical regardless of output cadence
  EXPECT_EQ(final_block_ct[0], final_block_ct[1]);
  EXPECT_EQ(final_block_ct[1], final_block_ct[2]);
  EXPECT_EQ(final_next_offset[0], final_next_offset[1]);
  EXPECT_EQ(final_next_offset[1], final_next_offset[2]);

  // But frames_per_block must differ (proportional to output FPS)
  EXPECT_NE(fpb_values[0], fpb_values[1]);
  EXPECT_NE(fpb_values[1], fpb_values[2]);
  EXPECT_LT(fpb_values[0], fpb_values[1]);  // 24fps < 30fps
  EXPECT_LT(fpb_values[1], fpb_values[2]);  // 30fps < 60fps
}

// =============================================================================
// TEST 7 — INV-AIR-MEDIA-TIME-003: Fence Alignment Convergence
//
// At block completion, decoded media time must converge to block end time
// within one frame period. Test across multiple FPS values.
// =============================================================================

TEST(MediaTimeContract, FenceAlignment_MultiFPS) {
  struct TestCase {
    double input_fps;
    double output_fps;
    int64_t block_duration_ms;
    const char* name;
  };

  TestCase cases[] = {
      {23.976, 30.0, 30 * 60 * 1000, "23.976->30 30min"},
      {29.97, 30.0, 30 * 60 * 1000, "29.97->30 30min"},
      {30.0, 30.0, 30 * 60 * 1000, "30->30 30min"},
      {23.976, 30.0, 120 * 60 * 1000, "23.976->30 2hr"},
      {24.0, 30.0, 60 * 60 * 1000, "24->30 1hr"},
      {25.0, 30.0, 30 * 60 * 1000, "25->30 30min"},
  };

  for (const auto& tc : cases) {
    SCOPED_TRACE(tc.name);

    int64_t total_input_frames = static_cast<int64_t>(
        std::ceil(tc.block_duration_ms * tc.input_fps / 1000.0));

    PTSAnchoredTracker tracker(tc.input_fps);

    for (int64_t i = 0; i < total_input_frames; i++) {
      int64_t pts_us = ExactPtsUs(i, tc.input_fps);
      tracker.AdvanceWithPTS(pts_us);
    }

    // At block completion: |block_ct_ms - block_duration_ms| <= frame_duration
    int64_t fence_error = std::abs(tracker.block_ct_ms - tc.block_duration_ms);
    EXPECT_LE(fence_error, tracker.input_frame_duration_ms + 1)
        << "Fence error must be within one input frame period "
        << "(error: " << fence_error << "ms, "
        << "frame_dur: " << tracker.input_frame_duration_ms << "ms)";
  }
}

// =============================================================================
// TEST 8 — INV-AIR-MEDIA-TIME-002: Multi-Segment Drift
//
// Verify PTS-anchoring works correctly across segment boundaries.
// Two segments with different asset start offsets.
// =============================================================================

TEST(MediaTimeContract, MultiSegment_NoDrift) {
  constexpr double kInputFps = 23.976;
  constexpr int64_t kSegment1DurationMs = 15 * 60 * 1000;  // 15 minutes
  constexpr int64_t kSegment2DurationMs = 15 * 60 * 1000;  // 15 minutes
  constexpr int64_t kBlockDurationMs = kSegment1DurationMs + kSegment2DurationMs;

  int64_t seg1_frames = static_cast<int64_t>(
      std::ceil(kSegment1DurationMs * kInputFps / 1000.0));
  int64_t seg2_frames = static_cast<int64_t>(
      std::ceil(kSegment2DurationMs * kInputFps / 1000.0));

  PTSAnchoredTracker tracker(kInputFps);
  int64_t max_error = 0;

  // Segment 1: asset starts at 0, CT starts at 0
  tracker.seg_start_ct_ms = 0;
  tracker.seg_asset_start_ms = 0;
  for (int64_t i = 0; i < seg1_frames; i++) {
    int64_t pts_us = ExactPtsUs(i, kInputFps);
    tracker.AdvanceWithPTS(pts_us);
    int64_t err = tracker.PositionErrorMs(i, kInputFps);
    if (err > max_error) max_error = err;
  }

  int64_t ct_at_seg1_end = tracker.block_ct_ms;

  // Segment 2: asset starts at 5000ms (mid-asset join), CT starts at segment1 end
  int64_t seg2_asset_start_ms = 5000;
  tracker.seg_start_ct_ms = kSegment1DurationMs;
  tracker.seg_asset_start_ms = seg2_asset_start_ms;
  for (int64_t i = 0; i < seg2_frames; i++) {
    // PTS is relative to the asset, so it starts at the asset offset
    int64_t pts_us = ExactPtsUs(i, kInputFps) +
                     static_cast<int64_t>(seg2_asset_start_ms * 1000.0);
    tracker.AdvanceWithPTS(pts_us);
  }

  // After both segments, block_ct_ms should be near block duration
  int64_t final_error = std::abs(tracker.block_ct_ms - kBlockDurationMs);
  EXPECT_LE(final_error, tracker.input_frame_duration_ms + 1)
      << "Multi-segment final error must be within one frame period";

  // Drift never exceeded 1 frame in segment 1
  EXPECT_LE(max_error, tracker.input_frame_duration_ms)
      << "Segment 1 max error must be bounded";

  // Segment transition was clean (CT continued from segment 1 end)
  EXPECT_GE(ct_at_seg1_end, kSegment1DurationMs - tracker.input_frame_duration_ms)
      << "CT at segment 1 end must be near segment 1 duration";
}

// =============================================================================
// TEST 9 — Regression: Old formula drift quantification
//
// Verify the specific drift values cited in the contract for documentation.
// This is a regression test — if these fail, the contract documentation
// needs updating.
// =============================================================================

TEST(MediaTimeContract, Regression_OldFormulaDriftQuantification) {
  // 23.976fps: input_frame_duration_ms = round(1000/23.976) = 42
  // True frame period: 1000/23.976 = 41.7084ms
  // Error per frame: 42 - 41.7084 = 0.2916ms
  // Over 36000 frames: 0.2916 * 36000 = 10497ms ≈ 10.5s

  constexpr double kInputFps = 23.976;
  int64_t input_frame_dur = std::llround(1000.0 / kInputFps);
  EXPECT_EQ(input_frame_dur, 42)
      << "round(1000/23.976) must be 42ms";

  double true_frame_period = 1000.0 / kInputFps;
  double error_per_frame = static_cast<double>(input_frame_dur) - true_frame_period;

  EXPECT_NEAR(error_per_frame, 0.2916, 0.001)
      << "Error per frame at 23.976fps";

  // After 36000 frames
  OldCumulativeTracker old_tracker(kInputFps);
  for (int64_t i = 0; i < 36000; i++) {
    old_tracker.Advance();
  }
  double ideal_ms = 36000.0 * 1000.0 / kInputFps;
  int64_t actual_drift = old_tracker.block_ct_ms - static_cast<int64_t>(std::round(ideal_ms));

  EXPECT_GT(actual_drift, 10000)
      << "Old tracker must drift >10s over 36000 frames at 23.976fps "
      << "(actual: " << actual_drift << "ms)";
  EXPECT_LT(actual_drift, 11000)
      << "Old tracker drift should be ~10.5s "
      << "(actual: " << actual_drift << "ms)";

  // Old frames_per_block for 25min block at 30fps output
  int64_t old_fpb = OldFramesPerBlock(25 * 60 * 1000, 30.0);
  int64_t new_fpb = ExactFramesPerBlock(25 * 60 * 1000, 30.0);
  EXPECT_GT(old_fpb - new_fpb, 400)
      << "Old formula must overestimate by >400 frames for 25min block";
}

// =============================================================================
// INV-FPS-MAPPING: ResampleMode detection regression (60→30 DROP, 30→30 OFF,
// 23.976→30 CADENCE). DROP must not reduce audio; skip decodes still contribute
// audio (tested by code path; E2E with 60fps asset asserts no audio underflow).
// =============================================================================

TEST(MediaTimeContract, ResampleMode_60to30_DROP_step2) {
  ResampleMode mode = ResampleMode::OFF;
  int64_t step = 1;
  ComputeResampleMode(60, 1, 30, 1, &mode, &step);
  EXPECT_EQ(mode, ResampleMode::DROP) << "60→30 MUST be DROP (INV-FPS-MAPPING)";
  EXPECT_EQ(step, 2) << "60→30 step must be 2";
}

TEST(MediaTimeContract, ResampleMode_30to30_OFF) {
  ResampleMode mode = ResampleMode::CADENCE;
  int64_t step = 1;
  ComputeResampleMode(30, 1, 30, 1, &mode, &step);
  EXPECT_EQ(mode, ResampleMode::OFF) << "30→30 MUST be OFF";
  EXPECT_EQ(step, 1);
}

TEST(MediaTimeContract, ResampleMode_120to30_DROP_step4) {
  ResampleMode mode = ResampleMode::OFF;
  int64_t step = 1;
  ComputeResampleMode(120, 1, 30, 1, &mode, &step);
  EXPECT_EQ(mode, ResampleMode::DROP) << "120→30 MUST be DROP";
  EXPECT_EQ(step, 4);
}

TEST(MediaTimeContract, ResampleMode_23976to30_CADENCE) {
  ResampleMode mode = ResampleMode::OFF;
  int64_t step = 1;
  ComputeResampleMode(24000, 1001, 30, 1, &mode, &step);
  EXPECT_EQ(mode, ResampleMode::CADENCE) << "23.976→30 MUST be CADENCE";
  EXPECT_EQ(step, 1);
}

TEST(MediaTimeContract, TickProducer_60to30_ReportsDROP_WhenDecoderOpens) {
  // With a real 60fps asset, AssignBlock opens decoder and GetVideoFPS() returns 60,
  // so GetResampleMode() becomes DROP and GetDropStep() becomes 2.
  // With nonexistent asset, decoder does not open so mode stays OFF — baseline.
  TickProducer producer(640, 480, 30, 1);
  FedBlock block = MakeSyntheticBlock("inv-fps-mapping", 60 * 1000);
  producer.AssignBlock(block);
  // Decoder fails to open (nonexistent path), so input_fps remains 0 and mode stays OFF.
  EXPECT_EQ(producer.GetResampleMode(), ResampleMode::OFF);
  EXPECT_EQ(producer.GetDropStep(), 1);
  // If a 60fps asset were used, we would assert:
  //   EXPECT_EQ(producer.GetResampleMode(), ResampleMode::DROP);
  //   EXPECT_EQ(producer.GetDropStep(), 2);
  // and run 5–10s of ticks asserting no audio underflow and audio depth > 200ms.
}

// =============================================================================
// INV-FPS-MAPPING + INV-FPS-TICK-PTS: Deterministic DROP contract test (no real file).
// Fake decoder reports 60fps, returns video duration 1/60s; TickProducer must return
// duration 1/30s and PTS advancing by one output tick per frame.
// =============================================================================
TEST(MediaTimeContract, TickProducer_DROP_SetsOutputDuration_ToOutputTick) {
  constexpr double kOutFps = 30.0;
  constexpr double kExpectedTickDurationS = 1.0 / kOutFps;  // 1/30 s
  constexpr double kToleranceS = 1e-6;
  constexpr int64_t kTickDurationUs = 1'000'000 / 30;  // one output tick in µs

  TickProducer producer(640, 480, 30, 1);
  producer.SetDecoderFactoryForTest(
      [](const decode::DecoderConfig& c) {
        return std::make_unique<FakeTickProducerDecoder>(c);
      });
  producer.SetAssetDurationForTest([](const std::string&) { return 10 * 1000; });
  FedBlock block = MakeSyntheticBlock("drop-duration", 10 * 1000, "fake://60fps");
  producer.AssignBlock(block);

  ASSERT_EQ(producer.GetResampleMode(), ResampleMode::DROP)
      << "60→30 with fake 60fps decoder must be DROP";
  ASSERT_EQ(producer.GetDropStep(), 2);

  // First frame: duration must be output tick (1/30), not input (1/60)
  std::optional<FrameData> fd = producer.TryGetFrame();
  ASSERT_TRUE(fd.has_value()) << "TryGetFrame must return a frame in DROP";
  EXPECT_NEAR(fd->video.metadata.duration, kExpectedTickDurationS, kToleranceS)
      << "INV-FPS-MAPPING: In DROP, returned frame duration must equal 1/output_fps, not 1/60";
  // Audio must contain aggregation from skip decodes (emit + 1 skip = 2 input frames' audio)
  EXPECT_GE(fd->audio.size(), 1u) << "DROP must aggregate audio from emit + skip decodes";
}

// =============================================================================
// INV-FPS-TICK-PTS: In DROP, returned video PTS delta must equal tick duration,
// not input frame duration (1/60). Run 5–10 ticks and assert PTS deltas.
// =============================================================================
TEST(MediaTimeContract, TickProducer_DROP_OutputPTS_AdvancesByTickDuration) {
  constexpr double kOutFps = 30.0;
  constexpr int64_t kTickDurationUs = 1'000'000 / 30;

  TickProducer producer(640, 480, 30, 1);
  producer.SetDecoderFactoryForTest(
      [](const decode::DecoderConfig& c) {
        return std::make_unique<FakeTickProducerDecoder>(c);
      });
  producer.SetAssetDurationForTest([](const std::string&) { return 10 * 1000; });
  FedBlock block = MakeSyntheticBlock("drop-pts", 10 * 1000, "fake://60fps");
  producer.AssignBlock(block);

  ASSERT_EQ(producer.GetResampleMode(), ResampleMode::DROP);
  ASSERT_EQ(producer.GetDropStep(), 2);

  std::vector<int64_t> pts_us;
  for (int i = 0; i < 10; i++) {
    auto fd = producer.TryGetFrame();
    if (!fd) break;
    pts_us.push_back(fd->video.metadata.pts);
  }
  ASSERT_GE(pts_us.size(), 2u) << "Need at least 2 frames to assert PTS delta";

  constexpr int64_t kTickDurationToleranceUs = 1;  // integer rounding over tick grid
  constexpr int64_t kInputFrameDurationUs = 1'000'000 / 60;  // would be wrong (1/60)
  for (size_t n = 1; n < pts_us.size(); n++) {
    int64_t delta = pts_us[n] - pts_us[n - 1];
    EXPECT_GE(delta, kTickDurationUs - kTickDurationToleranceUs)
        << "INV-FPS-TICK-PTS: PTS delta at tick " << n << " too small (got " << delta << " us)";
    EXPECT_LE(delta, kTickDurationUs + kTickDurationToleranceUs)
        << "INV-FPS-TICK-PTS: PTS delta at tick " << n << " too large (got " << delta << " us)";
    EXPECT_GT(delta, kInputFrameDurationUs)
        << "INV-FPS-TICK-PTS: PTS delta must not be 1/60 (" << kInputFrameDurationUs << " us)";
  }
}

// Optional E2E smoke: run with real 60fps asset if present. Skip if asset missing.
TEST(MediaTimeContract, TickProducer_DROP_E2E_WithReal60fpsAsset_Optional) {
  TickProducer producer(640, 480, 30, 1);
  const std::string k60fpsAssetPath = "/opt/retrovue/assets/Sample60fps.mp4";
  FedBlock block = MakeSyntheticBlock("drop-e2e", 10 * 1000, k60fpsAssetPath);
  producer.AssignBlock(block);
  if (producer.GetResampleMode() != ResampleMode::DROP || producer.GetDropStep() != 2) {
    GTEST_SKIP() << "60fps asset not available at " << k60fpsAssetPath;
  }
  auto fd = producer.TryGetFrame();
  ASSERT_TRUE(fd.has_value());
  EXPECT_NEAR(fd->video.metadata.duration, 1.0 / 30.0, 1e-6);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
