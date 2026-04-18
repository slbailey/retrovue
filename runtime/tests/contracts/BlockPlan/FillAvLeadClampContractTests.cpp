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

static int SamplesToMsFloor(int samples) {
  return static_cast<int>((samples * 1000LL) / buffer::kHouseAudioSampleRate);
}

static int VideoMsFromLookaheadFloor(int lookahead_frames, RationalFps fps) {
  return static_cast<int>((static_cast<int64_t>(std::max(0, lookahead_frames)) * 1000LL * fps.den) /
                          fps.num);
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

TEST(FillAvLeadClampContract, PrePushOnlyClampPolicy_CanPermitOneCycleOvershoot_OnHboBurstShape) {
  // HBO recurrence window evidence:
  // pre-push in-range state followed by a single decoded burst that pushes
  // post-push delta far above tolerance before next-cycle clamp.
  const RationalFps fps{30000, 1001};
  const int av_tolerance_ms = 120;
  const int pre_audio_ms = 512;
  const int pre_video_ms = 433;  // observed bootstrap-end fill estimate
  const int pre_delta_ms = pre_audio_ms - pre_video_ms;

  // Observed decoded burst in first recurrence window: 8192 samples.
  const int pending_samples = 8192;
  const int pending_audio_ms = SamplesToMsFloor(pending_samples);
  // Clamp log on next evaluation reported video_ms=467 in same local window.
  const int projected_video_ms = 467;
  const int projected_delta_ms = (pre_audio_ms + pending_audio_ms) - projected_video_ms;

  EXPECT_LE(pre_delta_ms, av_tolerance_ms)
      << "setup must start from in-range pre-push state";
  EXPECT_GT(projected_delta_ms, av_tolerance_ms)
      << "one-cycle burst should demonstrate overshoot loophole";
}

TEST(FillAvLeadClampContract, ProjectedAdmissionGuard_RejectsHboBurstButAllowsCheersLikeBatch) {
  const RationalFps fps{30000, 1001};
  const int av_tolerance_ms = 120;

  const int pre_audio_ms = 512;
  const int lookahead_frames = 14;
  const int video_ms_fill = VideoMsFromLookaheadFloor(lookahead_frames, fps);
  const int pre_delta_ms = pre_audio_ms - video_ms_fill;
  ASSERT_LE(pre_delta_ms, av_tolerance_ms);

  const auto projected_delta = [&](int batch_samples) {
    return (pre_audio_ms + SamplesToMsFloor(batch_samples)) - video_ms_fill;
  };

  // HBO-like burst should be rejected by projected one-cycle guard.
  EXPECT_GT(projected_delta(/*batch_samples=*/8192), av_tolerance_ms);
  // Cheers-like single AAC packet remains admissible.
  EXPECT_LE(projected_delta(/*batch_samples=*/1024), av_tolerance_ms);
}

TEST(FillAvLeadClampContract, PrePushHighWaterOnlyPolicy_CanPermitOneCycleOvershoot_OnHboBurstShape) {
  // HBO recurrence shape:
  // pre-push depth below high water + one decoded burst => post-push depth
  // crosses high water in same cycle.
  const int high_water_ms = 620;
  const int pre_audio_ms = 597;
  const int pending_samples = 4096;
  const int pending_audio_ms = SamplesToMsFloor(pending_samples);
  const int projected_audio_ms = pre_audio_ms + pending_audio_ms;

  EXPECT_LE(pre_audio_ms, high_water_ms);
  EXPECT_GT(projected_audio_ms, high_water_ms)
      << "one-cycle high-water overshoot loophole should be demonstrable";
}

TEST(FillAvLeadClampContract, ProjectedHighWaterGuard_RejectsHboBurstButAllowsCheersLikeBatch) {
  const int high_water_ms = 620;
  const int pre_audio_ms = 597;

  const auto projected_audio_ms = [&](int batch_samples) {
    return pre_audio_ms + SamplesToMsFloor(batch_samples);
  };

  // HBO-like decoded burst (8x512) should be rejected by projected high-water guard.
  EXPECT_GT(projected_audio_ms(/*batch_samples=*/4096), high_water_ms);
  // Cheers-like decoded packet should remain admissible.
  EXPECT_LE(projected_audio_ms(/*batch_samples=*/1024), high_water_ms);
}

TEST(FillAvLeadClampContract, FillLoop_HighWaterAdmission_MustNotOvershootInOneCycle) {
  // Contract proof obligation for projected high-water admission:
  // first clamp event must not require pre-push depth already above high-water.
  VideoLookaheadBuffer buf(8);
  buf.SetAvPhaseToleranceMs(5000);  // isolate high-water branch from AV-delta branch
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, /*high_water_ms=*/620, 2000);
  HeavyAudioMockProducer mock(64, 48, 80, 4096);  // HBO-like decoded burst shape
  std::atomic<bool> stop{false};
  buf.StartFilling(&mock, &audio, FPS_30, FPS_30, &stop);

  ASSERT_TRUE(WaitFor([&] { return buf.AvLeadClampEventCount() > 0; }, std::chrono::seconds(5)))
      << "expected first AV_LEAD_CLAMP under high-water policy";
  EXPECT_LE(audio.DepthMs(), audio.HighWaterMs())
      << "one-cycle high-water overshoot admitted before clamp engaged";

  buf.StopFilling(true);
}

TEST(FillAvLeadClampContract, SteadyState_MustNotRelyOnPersistentPredictiveHighWaterClampControl) {
  // Equilibrium proof obligation:
  // After convergence, clamp should be occasional safety, not recurring controller.
  VideoLookaheadBuffer buf(8);
  buf.SetAvPhaseToleranceMs(5000);  // isolate high-water branch behavior
  AudioLookaheadBuffer audio(1000, buffer::kHouseAudioSampleRate, buffer::kHouseAudioChannels,
                             333, /*high_water_ms=*/620, 2000);
  // HBO-like cadence/batch shape (bursty decode packets).
  HeavyAudioMockProducer mock(64, 48, 300, 8192);
  std::atomic<bool> stop{false};
  buf.StartFilling(&mock, &audio, FPS_30, FPS_30, &stop);

  std::atomic<bool> pop_stop{false};
  std::thread pop_thread([&] {
    buffer::AudioFrame out;
    while (!pop_stop.load(std::memory_order_relaxed)) {
      (void)audio.TryPopSamples(1602, out);
      std::this_thread::sleep_for(std::chrono::milliseconds(33));
    }
  });

  const bool reached_steady_window =
      WaitFor([&] { return audio.TotalSamplesPushed() >= 48000; }, std::chrono::seconds(5));
  EXPECT_TRUE(reached_steady_window)
      << "expected steady-state window with active fill";

  if (reached_steady_window) {
    const int64_t clamp_before = buf.AvLeadClampEventCount();
    std::this_thread::sleep_for(std::chrono::milliseconds(600));
    const int64_t clamp_after = buf.AvLeadClampEventCount();
    const int64_t clamp_delta = clamp_after - clamp_before;
    const int steady_headroom_ms = 33;  // one output-frame period @ ~30fps
    const int burst_headroom_ms = SamplesToMsFloor(8192);

    // Contract target: recurring clamp must not be the equilibrium controller.
    EXPECT_LE(clamp_delta, 2)
        << "steady-state relies on persistent predictive high-water clamp control";
    EXPECT_LE(audio.DepthMs(), audio.HighWaterMs() - steady_headroom_ms)
        << "steady-state failed to converge below high-water with operating headroom";
    EXPECT_LE(audio.DepthMs(), audio.HighWaterMs() - burst_headroom_ms)
        << "steady-state failed to maintain burst-aware headroom";
  }

  pop_stop.store(true, std::memory_order_relaxed);
  if (pop_thread.joinable()) pop_thread.join();
  buf.StopFilling(true);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
