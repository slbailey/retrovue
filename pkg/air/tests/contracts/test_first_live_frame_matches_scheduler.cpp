// Contract: INV-HANDOFF-002 — First live frame must match scheduler's selected_src for first content tick.
// Test: After AssignBlock, PrimeFirstTick, StartFilling, the frame used at first content tick has
//       source_frame_index == selected_src_first_tick (1 when tick 0 is PAD).
// Contract Reference: docs/contracts/INV-HANDOFF-002-PRIMING-DOES-NOT-ADVANCE-FRAME-INDEX.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <queue>
#include <thread>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/ITickProducerDecoder.hpp"
#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/decode/FFmpegDecoder.h"

namespace retrovue::blockplan::testing {
namespace {

constexpr RationalFps kFps_30{30, 1};

// First content tick: tick 0 is typically PAD, so first content pop is at tick 1 with selected_src=1.
constexpr int64_t kFirstContentTickSelectedSrc = 1;

class FakeDecoderForFirstLive : public ITickProducerDecoder {
 public:
  explicit FakeDecoderForFirstLive(const decode::DecoderConfig& config)
      : width_(config.target_width),
        height_(config.target_height),
        decode_count_(0),
        max_decodes_(120) {}

  bool Open() override { return true; }
  int SeekPreciseToMs(int64_t) override { return 0; }
  RationalFps GetVideoRationalFps() override { return RationalFps(30, 1); }
  bool DecodeFrameToBuffer(buffer::Frame& out) override {
    if (decode_count_ >= max_decodes_) return false;
    decode_count_++;
    out.width = width_;
    out.height = height_;
    out.metadata.duration = 1.0 / 30.0;
    out.metadata.pts = static_cast<int64_t>((decode_count_ - 1) * 1'000'000.0 / 30.0);
    out.metadata.dts = out.metadata.pts;
    out.metadata.asset_uri = "fake://firstlive";
    size_t y = static_cast<size_t>(width_) * static_cast<size_t>(height_);
    size_t uv = (y / 4);
    out.data.resize(y + 2 * uv, 0x10);
    buffer::AudioFrame af;
    af.sample_rate = buffer::kHouseAudioSampleRate;
    af.channels = buffer::kHouseAudioChannels;
    af.nb_samples = 1600;
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
  PumpResult PumpDecoderOnce(PumpMode) override {
    return decode_count_ >= max_decodes_ ? PumpResult::kEof : PumpResult::kProgress;
  }

 private:
  int width_;
  int height_;
  int decode_count_;
  int max_decodes_;
  std::queue<buffer::AudioFrame> pending_audio_;
};

static FedBlock MakeBlock(const std::string& id, int64_t duration_ms,
                          const std::string& asset_uri = "fake://firstlive") {
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

static bool WaitForDepth(const VideoLookaheadBuffer& buf, int min_depth,
                         std::chrono::milliseconds timeout) {
  auto deadline = std::chrono::steady_clock::now() + timeout;
  while (std::chrono::steady_clock::now() < deadline) {
    if (buf.DepthFrames() >= min_depth) return true;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  return false;
}

}  // namespace

// INV-HANDOFF-002 Rule 3: First frame pushed into LIVE_VIDEO_BUFFER must align with
// selected_src for the first content tick. So the frame we pop at "first content tick"
// must have source_frame_index == kFirstContentTickSelectedSrc (1).
TEST(InvHandoff002, FirstLiveFrameMatchesScheduler) {
  TickProducer producer(640, 480, kFps_30);
  producer.SetDecoderFactoryForTest(
      [](const decode::DecoderConfig& c) {
        return std::make_unique<FakeDecoderForFirstLive>(c);
      });
  producer.SetAssetDurationForTest([](const std::string&) { return 30 * 1000; });

  FedBlock block = MakeBlock("inv-handoff-002-firstlive", 30 * 1000);
  producer.AssignBlock(block);
  ASSERT_EQ(producer.GetState(), ITickProducer::State::kReady);

  producer.PrimeFirstTick(500);
  ASSERT_TRUE(producer.HasPrimedFrame());

  VideoLookaheadBuffer video_buf(15, 5);
  video_buf.SetBufferLabel("LIVE_VIDEO_BUFFER");
  AudioLookaheadBuffer audio_buf(1000, 200);
  std::atomic<bool> stop_signal{false};

  video_buf.StartFilling(
      &producer,
      &audio_buf,
      producer.GetInputRationalFps(),
      kFps_30,
      &stop_signal);

  // Wait for at least 2 frames so we have the primed (0) and the next (1).
  ASSERT_TRUE(WaitForDepth(video_buf, 2, std::chrono::seconds(5)))
      << "Fill thread must push at least 2 frames";

  // First pop: frame 0 (would be consumed if tick 0 were content; or we advance to second).
  VideoBufferFrame vbf0;
  ASSERT_TRUE(video_buf.TryPopFrame(vbf0)) << "Buffer must have at least one frame";
  EXPECT_EQ(vbf0.source_frame_index, 0) << "First frame in buffer must be source_frame_index 0";

  // Second pop: frame used at first content tick (tick 1, selected_src=1).
  VideoBufferFrame vbf1;
  ASSERT_TRUE(video_buf.TryPopFrame(vbf1)) << "Buffer must have second frame for first content tick";
  EXPECT_EQ(vbf1.source_frame_index, kFirstContentTickSelectedSrc)
      << "INV-HANDOFF-002: First content tick frame must have source_frame_index == selected_src ("
      << kFirstContentTickSelectedSrc << ")";

  stop_signal.store(true);
  video_buf.StopFilling(true);
}

}  // namespace retrovue::blockplan::testing
