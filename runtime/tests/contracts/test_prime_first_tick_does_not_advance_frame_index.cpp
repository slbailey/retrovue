// Contract: INV-HANDOFF-002 — Priming must not advance the producer output frame index.
// Test: After AssignBlock + PrimeFirstTick, frame_index_ must still be 0.
// Contract Reference: docs/contracts/INV-HANDOFF-002-PRIMING-DOES-NOT-ADVANCE-FRAME-INDEX.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cstdint>
#include <queue>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/ITickProducerDecoder.hpp"
#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/decode/FFmpegDecoder.h"

namespace retrovue::blockplan::testing {
namespace {

constexpr RationalFps kFps_30{30, 1};

// Minimal fake decoder: returns enough frames with audio so PrimeFirstTick(min_audio_prime_ms) completes.
class FakeDecoderForPrime : public ITickProducerDecoder {
 public:
  explicit FakeDecoderForPrime(const decode::DecoderConfig& config)
      : width_(config.target_width),
        height_(config.target_height),
        decode_count_(0),
        max_decodes_(60) {}

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
    out.metadata.asset_uri = "fake://prime";
    size_t y = static_cast<size_t>(width_) * static_cast<size_t>(height_);
    size_t uv = (y / 4);
    out.data.resize(y + 2 * uv, 0x10);
    buffer::AudioFrame af;
    af.sample_rate = buffer::kHouseAudioSampleRate;
    af.channels = buffer::kHouseAudioChannels;
    af.nb_samples = 1600;  // enough that a few decodes reach 500 ms
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
                          const std::string& asset_uri = "fake://prime") {
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

}  // namespace

// INV-HANDOFF-002: PrimeFirstTick must not advance frame_index_.
// Frames decoded during priming are pre-output preparation only.
TEST(InvHandoff002, PrimeFirstTickDoesNotAdvanceFrameIndex) {
  TickProducer producer(640, 480, kFps_30);
  producer.SetDecoderFactoryForTest(
      [](const decode::DecoderConfig& c) {
        return std::make_unique<FakeDecoderForPrime>(c);
      });
  producer.SetAssetDurationForTest([](const std::string&) { return 10 * 1000; });

  FedBlock block = MakeBlock("inv-handoff-002-prime", 10 * 1000);
  producer.AssignBlock(block);
  ASSERT_EQ(producer.GetState(), ITickProducer::State::kReady);

  constexpr int kMinAudioPrimeMs = 500;
  auto result = producer.PrimeFirstTick(kMinAudioPrimeMs);
  ASSERT_TRUE(result.met_threshold) << "Prime must meet audio threshold for test to be valid";

  // INV-HANDOFF-002 Rule 1: frame_index_ must equal 0 after PrimeFirstTick() completes.
  EXPECT_EQ(producer.GetFrameIndex(), 0)
      << "INV-HANDOFF-002: Priming must not advance frame_index_; "
      << "first frame from TryGetFrame must have source_frame_index==0";
}

}  // namespace retrovue::blockplan::testing
