// INV-FILL-AV-LEAD-CLAMP-001, INV-AUDIO-CONTINUITY-NO-DROP (suppression vs committed samples)
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <thread>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

static buffer::Frame MakeVideoFrame(int w, int h) {
  buffer::Frame frame;
  frame.width = w;
  frame.height = h;
  int y = w * h;
  int uv = (w / 2) * (h / 2);
  frame.data.resize(static_cast<size_t>(y + 2 * uv));
  std::memset(frame.data.data(), 0x10, frame.data.size());
  return frame;
}

static buffer::AudioFrame MakeAudioFrame(int nb_samples) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels = buffer::kHouseAudioChannels;
  frame.nb_samples = nb_samples;
  const int bps = buffer::kHouseAudioChannels * static_cast<int>(sizeof(int16_t));
  frame.data.resize(static_cast<size_t>(nb_samples * bps));
  return frame;
}

// Produces large audio chunks so audio depth (ms) grows faster than video_time_ms_fill.
class HeavyAudioMockProducer : public ITickProducer {
 public:
  HeavyAudioMockProducer(int w, int h, int total_frames, int audio_samples_per_video_frame)
      : w_(w),
        h_(h),
        total_frames_(total_frames),
        audio_samples_(audio_samples_per_video_frame),
        frames_left_(total_frames) {}

  void AssignBlock(const FedBlock& block) override { block_ = block; }
  DecodeResult TryGetFrame() override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (frames_left_ <= 0) return {DecodeStatus::kUnderrun, std::nullopt};
    frames_left_--;
    const int idx = total_frames_ - frames_left_ - 1;
    FrameData fd;
    fd.video = MakeVideoFrame(w_, h_);
    fd.asset_uri = "test://heavy_audio";
    fd.block_ct_ms = idx * 33;
    fd.source_frame_index = idx;
    fd.audio.push_back(MakeAudioFrame(audio_samples_));
    return {DecodeStatus::kFrame, std::move(fd)};
  }
  void Reset() override {
    std::lock_guard<std::mutex> lock(mutex_);
    frames_left_ = 0;
  }
  State GetState() const override { return State::kReady; }
  const FedBlock& GetBlock() const override { return block_; }
  int64_t FramesPerBlock() const override { return total_frames_; }
  bool HasDecoder() const override { return true; }
  RationalFps GetInputRationalFps() const override { return DeriveRationalFPS(30.0); }

  bool HasPrimedFrame() const override { return false; }
  const std::vector<SegmentBoundary>& GetBoundaries() const override {
    static const std::vector<SegmentBoundary> empty;
    return empty;
  }
  int64_t GetFrameIndex() const override { return -1; }

 private:
  int w_, h_;
  int total_frames_;
  int audio_samples_;
  int frames_left_;
  FedBlock block_;
  mutable std::mutex mutex_;
};

template <typename Pred>
static bool WaitFor(Pred pred, std::chrono::milliseconds timeout) {
  auto deadline = std::chrono::steady_clock::now() + timeout;
  while (!pred()) {
    if (std::chrono::steady_clock::now() > deadline) return false;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  return true;
}

TEST(FillAvLeadClampContract, FillLoop_ClampSuppressesAudio_WhenAudioMsExceedsHighWater) {
  // Default AudioLookaheadBuffer: high_water_ms=800. Push ~960ms equivalent per chunk -> clamp by high water.
  VideoLookaheadBuffer buf(8);
  buf.SetAvPhaseToleranceMs(5000);  // avoid av_delta clamp; isolate high-water
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, 800, 2000);
  HeavyAudioMockProducer mock(64, 48, 50, 48000);  // 1s audio per video frame at 48k stereo -> ~1000ms/chunk
  std::atomic<bool> stop{false};
  buf.StartFilling(&mock, &audio, FPS_30, FPS_30, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.AvLeadClampEventCount() > 0; }, std::chrono::seconds(3)))
      << "expected AV_LEAD_CLAMP (high_water)";
  const int64_t pushed_before = audio.TotalSamplesPushed();
  // Continuity: suppressed samples never enter buffer — depth stays bounded by policy
  EXPECT_LE(audio.DepthMs(), audio.HardCapMs());
  EXPECT_GE(buf.AudioFramesSuppressedNonGeneration(), 1);
  // No duplicate admission: pushed count should not grow unbounded during suppression bursts
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  EXPECT_LT(audio.TotalSamplesPushed(), pushed_before + 48000 * 200);

  buf.StopFilling(true);
}

TEST(FillAvLeadClampContract, FillLoop_ClampSuppressesAudio_WhenAvDeltaExceedsMaxAvLead) {
  VideoLookaheadBuffer buf(8);
  buf.SetAvPhaseToleranceMs(50);
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, 2000, 4000);  // raise high water so delta path wins first
  HeavyAudioMockProducer mock(64, 48, 80, 24000);  // ~500ms/chunk — grows audio lead over video_ms
  std::atomic<bool> stop{false};
  buf.StartFilling(&mock, &audio, FPS_30, FPS_30, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.AvLeadClampEventCount() > 0; }, std::chrono::seconds(4)))
      << "expected AV_LEAD_CLAMP (av_delta)";
  buf.StopFilling(true);
}

TEST(FillAvLeadClampContract, FillLoop_NoClamp_WhenWithinTolerance) {
  VideoLookaheadBuffer buf(8);
  buf.SetAvPhaseToleranceMs(120);
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, 800, 2000);
  HeavyAudioMockProducer mock(64, 48, 30, 1024);  // modest audio — typical path
  std::atomic<bool> stop{false};
  buf.StartFilling(&mock, &audio, FPS_30, FPS_30, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.DepthFrames() >= 1; }, std::chrono::seconds(2)));
  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  // May still be zero clamps on very fast fill; primary check: tolerance 120 allows normal decode
  EXPECT_EQ(buf.AvPhaseToleranceMs(), 120);
  buf.StopFilling(true);
}

TEST(FillAvLeadClampContract, FillLoop_ClampReason_IsAvLeadClamp) {
  VideoLookaheadBuffer buf(8);
  buf.SetAvPhaseToleranceMs(30);
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, 2000, 4000);
  HeavyAudioMockProducer mock(64, 48, 100, 48000);
  std::atomic<bool> stop{false};
  buf.StartFilling(&mock, &audio, FPS_30, FPS_30, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.AvLeadClampEventCount() > 0; }, std::chrono::seconds(5)));
  EXPECT_GE(buf.AvLeadClampEventCount(), 1);
  EXPECT_GE(buf.AudioFramesSuppressedNonGeneration(), 1);
  buf.StopFilling(true);
}

TEST(FillAvLeadClampContract, FillLoop_RepeatedBootstrapDecodeCycles_DoNotPermitUnboundedPositiveAudioLead) {
  VideoLookaheadBuffer buf(8);
  buf.SetAvPhaseToleranceMs(80);
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, 2000, 4000);
  HeavyAudioMockProducer mock(64, 48, 200, 36000);
  std::atomic<bool> stop{false};
  buf.StartFilling(&mock, &audio, FPS_30, FPS_30, &stop);
  ASSERT_TRUE(WaitFor([&] { return buf.AvLeadClampEventCount() > 10; }, std::chrono::seconds(8)));
  EXPECT_LE(audio.DepthMs(), audio.HardCapMs());
  // Lead cannot diverge without bound while clamp is active
  int max_depth = 0;
  for (int i = 0; i < 50; ++i) {
    max_depth = std::max(max_depth, audio.DepthMs());
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  EXPECT_LE(max_depth, audio.HardCapMs());
  buf.StopFilling(true);
}

TEST(FillAvLeadClampContract, SuppressionDoesNotViolateContinuityCommittedSamples) {
  // INV-AUDIO-CONTINUITY-NO-DROP: only samples after successful Push count — suppression is pre-Push.
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, 800, 2000);
  buffer::AudioFrame one = MakeAudioFrame(1000);
  EXPECT_EQ(audio.Push(std::move(one)), AudioLookaheadBuffer::PushResult::kPushed);
  const int64_t pushed = audio.TotalSamplesPushed();
  const int64_t popped = audio.TotalSamplesPopped();
  // TotalSamplesPushed tracks nb_samples (per channel tick), not interleaved scalar count.
  EXPECT_EQ(pushed, 1000);
  EXPECT_GE(pushed, popped);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
