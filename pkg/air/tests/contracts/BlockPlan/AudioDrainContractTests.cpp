// Repository: Retrovue-playout
// Component: Audio Drain Contract Tests
// Purpose: Prove compliance with INV-AUDIO-DRAIN-001.
//          All decoded audio frames must be transferred from the decoder into
//          RetroVue-managed buffers during the same decode cycle. The decoder
//          must never serve as a long-term audio buffer.
// Contract Reference: INV-AUDIO-DRAIN-001
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <cstring>
#include <memory>
#include <queue>
#include <vector>

#include "retrovue/blockplan/ITickProducerDecoder.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// ---------------------------------------------------------------------------
// Mock decoder that queues a configurable number of audio frames per video
// decode. This simulates codecs/containers that produce many small audio
// packets per video frame (e.g., 512-sample frames at 48kHz with 24fps video
// produce ~4 audio frames per video frame; AC3/DTS can produce different counts).
// ---------------------------------------------------------------------------
class MultiAudioDecoder : public ITickProducerDecoder {
 public:
  explicit MultiAudioDecoder(int audio_frames_per_decode,
                             int audio_samples_per_frame = 512,
                             int max_video_frames = 30)
      : audio_per_decode_(audio_frames_per_decode),
        samples_per_af_(audio_samples_per_frame),
        max_decodes_(max_video_frames) {}

  bool Open() override { return true; }
  int SeekPreciseToMs(int64_t) override { return 0; }
  RationalFps GetVideoRationalFps() override { return FPS_24; }

  bool DecodeFrameToBuffer(buffer::Frame& out) override {
    if (decode_count_ >= max_decodes_) return false;
    decode_count_++;

    out.width = 64;
    out.height = 48;
    int64_t frame_dur_us = 1'000'000 / 24;
    out.metadata.pts = (decode_count_ - 1) * frame_dur_us;
    out.metadata.dts = out.metadata.pts;
    out.metadata.duration = static_cast<double>(frame_dur_us) / 1'000'000.0;
    out.metadata.asset_uri = "fake://multi_audio";
    size_t y = 64 * 48;
    size_t uv = y / 4;
    out.data.resize(y + 2 * uv, 0x10);

    // Queue N audio frames per video decode.
    for (int i = 0; i < audio_per_decode_; i++) {
      buffer::AudioFrame af;
      af.sample_rate = buffer::kHouseAudioSampleRate;
      af.channels = buffer::kHouseAudioChannels;
      af.nb_samples = samples_per_af_;
      af.pts_us = out.metadata.pts + i * (static_cast<int64_t>(samples_per_af_) * 1'000'000 / af.sample_rate);
      af.data.resize(
          static_cast<size_t>(af.nb_samples) * af.channels * sizeof(int16_t), 0);
      pending_audio_.push(std::move(af));
    }
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

  // Observability: how many audio frames are still in the decoder's queue.
  int PendingAudioCount() const { return static_cast<int>(pending_audio_.size()); }

 private:
  int audio_per_decode_;
  int samples_per_af_;
  int max_decodes_;
  int decode_count_ = 0;
  std::queue<buffer::AudioFrame> pending_audio_;
};

// ---------------------------------------------------------------------------
// Helper: create a TickProducer with a MultiAudioDecoder injected, assign a
// minimal block, and return both (decoder is owned by producer but we keep
// a raw pointer for observability).
// ---------------------------------------------------------------------------
struct TestFixture {
  std::unique_ptr<TickProducer> producer;
  MultiAudioDecoder* decoder_ptr = nullptr;  // non-owning

  static TestFixture Create(int audio_frames_per_decode,
                            int audio_samples_per_frame = 512) {
    TestFixture f;
    int afd = audio_frames_per_decode;
    int aspf = audio_samples_per_frame;
    MultiAudioDecoder* raw = nullptr;

    f.producer = std::make_unique<TickProducer>(64, 48, FPS_30);
    f.producer->SetDecoderFactoryForTest(
        [afd, aspf, &raw](const decode::DecoderConfig&) -> std::unique_ptr<ITickProducerDecoder> {
          auto d = std::make_unique<MultiAudioDecoder>(afd, aspf);
          raw = d.get();
          return d;
        });
    f.producer->SetAssetDurationForTest(
        [](const std::string&) -> int64_t { return 10000; });

    // Assign a minimal block with one segment.
    FedBlock block;
    block.block_id = "test_drain";
    block.start_utc_ms = 0;
    block.end_utc_ms = 5000;
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = "fake://multi_audio";
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 5000;
    block.segments.push_back(seg);
    f.producer->AssignBlock(block);
    f.decoder_ptr = raw;
    return f;
  }
};

// ---------------------------------------------------------------------------
// Test 1: Full drain — no residual audio in decoder after TryGetFrame.
//
// INV-AUDIO-DRAIN-001: When the decoder produces 12 audio frames per video
// decode, TryGetFrame must return all 12 in FrameData::audio.
// With the buggy cap (kMaxAudioFramesPerVideoFrame = 8), only 8 are returned
// and 4 remain in the decoder → TEST FAILS.
// ---------------------------------------------------------------------------
TEST(AudioDrainContract, test_full_drain_no_residual) {
  constexpr int kAudioPerDecode = 12;  // More than any reasonable fixed cap
  auto fix = TestFixture::Create(kAudioPerDecode);

  auto fd = fix.producer->TryGetFrame();
  ASSERT_TRUE(fd.has_value()) << "TryGetFrame must succeed on first call";

  // INV-AUDIO-DRAIN-001: ALL audio frames must be captured.
  EXPECT_EQ(static_cast<int>(fd->audio.size()), kAudioPerDecode)
      << "INV-AUDIO-DRAIN-001 VIOLATED: TryGetFrame returned "
      << fd->audio.size() << " audio frames but decoder produced "
      << kAudioPerDecode << ". Undrained audio remains in the decoder, "
      << "causing progressive A/V desync.";

  // Verify the decoder's pending queue is empty.
  ASSERT_NE(fix.decoder_ptr, nullptr);
  EXPECT_EQ(fix.decoder_ptr->PendingAudioCount(), 0)
      << "INV-AUDIO-DRAIN-001 VIOLATED: Decoder still has "
      << fix.decoder_ptr->PendingAudioCount()
      << " audio frames after TryGetFrame. These will contaminate "
      << "the next decode cycle.";
}

// ---------------------------------------------------------------------------
// Test 2: Variable audio count per decode — all counts captured exactly.
//
// INV-AUDIO-DRAIN-001: Different codecs produce different numbers of audio
// frames per video decode. The drain must adapt to each decode cycle.
// ---------------------------------------------------------------------------
TEST(AudioDrainContract, test_variable_audio_per_decode) {
  // Use a decoder that produces 4 audio frames per video decode.
  // At 512 samples per frame, that's 2048 samples — covers one 24fps
  // video frame at 48kHz (2000 samples needed).
  auto fix = TestFixture::Create(4, 512);

  // Decode 5 video frames. Each should have exactly 4 audio frames.
  for (int i = 0; i < 5; i++) {
    auto fd = fix.producer->TryGetFrame();
    ASSERT_TRUE(fd.has_value()) << "TryGetFrame failed on call " << i;
    EXPECT_EQ(static_cast<int>(fd->audio.size()), 4)
        << "Decode " << i << ": expected 4 audio frames, got "
        << fd->audio.size();
  }

  // Verify nothing accumulated in the decoder.
  ASSERT_NE(fix.decoder_ptr, nullptr);
  EXPECT_EQ(fix.decoder_ptr->PendingAudioCount(), 0);
}

// ---------------------------------------------------------------------------
// Test 3: Large burst — simulates pathological stream with many small packets.
//
// INV-AUDIO-DRAIN-001: Even with 32 audio frames per video decode, all must
// be captured. The safety fuse (64) must not interfere.
// ---------------------------------------------------------------------------
TEST(AudioDrainContract, test_large_burst_fully_drained) {
  constexpr int kAudioPerDecode = 32;
  auto fix = TestFixture::Create(kAudioPerDecode, 256);

  auto fd = fix.producer->TryGetFrame();
  ASSERT_TRUE(fd.has_value());

  EXPECT_EQ(static_cast<int>(fd->audio.size()), kAudioPerDecode)
      << "INV-AUDIO-DRAIN-001 VIOLATED: Large audio burst not fully drained. "
      << "Got " << fd->audio.size() << ", expected " << kAudioPerDecode;

  ASSERT_NE(fix.decoder_ptr, nullptr);
  EXPECT_EQ(fix.decoder_ptr->PendingAudioCount(), 0);
}

// ---------------------------------------------------------------------------
// Test 4: Zero audio frames — no audio stream, no crash.
//
// Edge case: decoder produces 0 audio frames per video decode.
// ---------------------------------------------------------------------------
TEST(AudioDrainContract, test_zero_audio_no_crash) {
  auto fix = TestFixture::Create(0, 512);

  auto fd = fix.producer->TryGetFrame();
  ASSERT_TRUE(fd.has_value());
  EXPECT_EQ(fd->audio.size(), 0u);
}

// ---------------------------------------------------------------------------
// Test 5: Cumulative drain — after N decodes, total audio frames = N * per_decode.
//
// With a cap, undrained audio accumulates in the decoder queue and later
// decode cycles return more than expected (bursty). With full drain, each
// cycle returns exactly per_decode.
// ---------------------------------------------------------------------------
TEST(AudioDrainContract, test_cumulative_drain_no_accumulation) {
  constexpr int kAudioPerDecode = 10;
  auto fix = TestFixture::Create(kAudioPerDecode, 512);

  int64_t total_audio = 0;
  for (int i = 0; i < 10; i++) {
    auto fd = fix.producer->TryGetFrame();
    ASSERT_TRUE(fd.has_value()) << "TryGetFrame failed on call " << i;
    total_audio += static_cast<int64_t>(fd->audio.size());
  }

  // With full drain: exactly 10 * 10 = 100 audio frames.
  // With a cap: fewer than 100 (some stuck in decoder).
  EXPECT_EQ(total_audio, 10 * kAudioPerDecode)
      << "INV-AUDIO-DRAIN-001: Total audio frames after 10 decodes should be "
      << 10 * kAudioPerDecode << " but got " << total_audio
      << ". Audio is leaking inside the decoder.";
}

// ---------------------------------------------------------------------------
// Mock decoder that queues a VARIABLE number of audio frames per video decode,
// specified per-cycle via a vector. This simulates multi-packet scenarios
// where different demuxed packets produce different audio frame counts in
// the same decode cycle (e.g., packet1 → 3 AAC frames, packet2 → 4 AAC frames).
// ---------------------------------------------------------------------------
class MultiPacketAudioDecoder : public ITickProducerDecoder {
 public:
  explicit MultiPacketAudioDecoder(std::vector<int> audio_counts_per_decode,
                                   int audio_samples_per_frame = 512)
      : audio_counts_(std::move(audio_counts_per_decode)),
        samples_per_af_(audio_samples_per_frame) {}

  bool Open() override { return true; }
  int SeekPreciseToMs(int64_t) override { return 0; }
  RationalFps GetVideoRationalFps() override { return FPS_24; }

  bool DecodeFrameToBuffer(buffer::Frame& out) override {
    if (decode_count_ >= static_cast<int>(audio_counts_.size())) return false;
    int audio_count = audio_counts_[decode_count_];
    decode_count_++;

    out.width = 64;
    out.height = 48;
    int64_t frame_dur_us = 1'000'000 / 24;
    out.metadata.pts = (decode_count_ - 1) * frame_dur_us;
    out.metadata.dts = out.metadata.pts;
    out.metadata.duration = static_cast<double>(frame_dur_us) / 1'000'000.0;
    out.metadata.asset_uri = "fake://multi_packet";
    size_t y = 64 * 48;
    size_t uv = y / 4;
    out.data.resize(y + 2 * uv, 0x10);

    for (int i = 0; i < audio_count; i++) {
      buffer::AudioFrame af;
      af.sample_rate = buffer::kHouseAudioSampleRate;
      af.channels = buffer::kHouseAudioChannels;
      af.nb_samples = samples_per_af_;
      af.pts_us = out.metadata.pts + i * (static_cast<int64_t>(samples_per_af_) * 1'000'000 / af.sample_rate);
      af.data.resize(
          static_cast<size_t>(af.nb_samples) * af.channels * sizeof(int16_t), 0);
      pending_audio_.push(std::move(af));
    }
    return true;
  }

  bool GetPendingAudioFrame(buffer::AudioFrame& out) override {
    if (pending_audio_.empty()) return false;
    out = std::move(pending_audio_.front());
    pending_audio_.pop();
    return true;
  }

  bool IsEOF() const override { return decode_count_ >= static_cast<int>(audio_counts_.size()); }
  void SetInterruptFlags(const DecoderInterruptFlags&) override {}
  bool HasAudioStream() const override { return true; }
  PumpResult PumpDecoderOnce(PumpMode) override {
    return decode_count_ >= static_cast<int>(audio_counts_.size()) ? PumpResult::kEof : PumpResult::kProgress;
  }

  int PendingAudioCount() const { return static_cast<int>(pending_audio_.size()); }

 private:
  std::vector<int> audio_counts_;
  int samples_per_af_;
  int decode_count_ = 0;
  std::queue<buffer::AudioFrame> pending_audio_;
};

// ---------------------------------------------------------------------------
// Helper: create a TickProducer with a MultiPacketAudioDecoder injected.
// ---------------------------------------------------------------------------
struct MultiPacketFixture {
  std::unique_ptr<TickProducer> producer;
  MultiPacketAudioDecoder* decoder_ptr = nullptr;

  static MultiPacketFixture Create(std::vector<int> audio_counts) {
    MultiPacketFixture f;
    auto counts = std::make_shared<std::vector<int>>(std::move(audio_counts));
    MultiPacketAudioDecoder* raw = nullptr;

    f.producer = std::make_unique<TickProducer>(64, 48, FPS_30);
    f.producer->SetDecoderFactoryForTest(
        [counts, &raw](const decode::DecoderConfig&) -> std::unique_ptr<ITickProducerDecoder> {
          auto d = std::make_unique<MultiPacketAudioDecoder>(*counts);
          raw = d.get();
          return d;
        });
    f.producer->SetAssetDurationForTest(
        [](const std::string&) -> int64_t { return 10000; });

    FedBlock block;
    block.block_id = "test_multi_packet";
    block.start_utc_ms = 0;
    block.end_utc_ms = 5000;
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = "fake://multi_packet";
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 5000;
    block.segments.push_back(seg);
    f.producer->AssignBlock(block);
    f.decoder_ptr = raw;
    return f;
  }
};

// ---------------------------------------------------------------------------
// Test 6: Multi-packet backlog — two packets produce different audio frame
// counts in the same decode cycle. All frames must be drained.
//
// INV-AUDIO-DRAIN-001: Simulates real AAC/DTS behavior where multiple
// demuxed packets arrive in a single decode cycle. packet1 → 3 audio frames,
// packet2 → 4 audio frames. The decoder queues all 7, and the drain loop
// must capture all 7 — not just the first packet's worth.
// ---------------------------------------------------------------------------
TEST(AudioDrainContract, test_decoder_backlog_from_multiple_packets) {
  // Simulate 3 decode cycles with varying audio frame counts per cycle.
  // Cycle 0: 7 frames (as if 3 + 4 from two packets)
  // Cycle 1: 3 frames (single packet)
  // Cycle 2: 11 frames (as if 4 + 3 + 4 from three packets)
  auto fix = MultiPacketFixture::Create({7, 3, 11});

  // Cycle 0: expect all 7 drained.
  {
    auto fd = fix.producer->TryGetFrame();
    ASSERT_TRUE(fd.has_value()) << "TryGetFrame failed on cycle 0";
    EXPECT_EQ(static_cast<int>(fd->audio.size()), 7)
        << "INV-AUDIO-DRAIN-001 VIOLATED: Cycle 0 produced 7 audio frames "
        << "(multi-packet backlog) but only " << fd->audio.size()
        << " were drained.";
  }

  // Cycle 1: expect all 3 drained.
  {
    auto fd = fix.producer->TryGetFrame();
    ASSERT_TRUE(fd.has_value()) << "TryGetFrame failed on cycle 1";
    EXPECT_EQ(static_cast<int>(fd->audio.size()), 3)
        << "Cycle 1: expected 3 audio frames, got " << fd->audio.size();
  }

  // Cycle 2: expect all 11 drained.
  {
    auto fd = fix.producer->TryGetFrame();
    ASSERT_TRUE(fd.has_value()) << "TryGetFrame failed on cycle 2";
    EXPECT_EQ(static_cast<int>(fd->audio.size()), 11)
        << "INV-AUDIO-DRAIN-001 VIOLATED: Cycle 2 produced 11 audio frames "
        << "(multi-packet backlog) but only " << fd->audio.size()
        << " were drained.";
  }

  // Verify decoder queue is completely empty.
  ASSERT_NE(fix.decoder_ptr, nullptr);
  EXPECT_EQ(fix.decoder_ptr->PendingAudioCount(), 0)
      << "INV-AUDIO-DRAIN-001 VIOLATED: Decoder still has "
      << fix.decoder_ptr->PendingAudioCount()
      << " audio frames after all decode cycles.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
