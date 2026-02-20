// Repository: Retrovue-playout
// Component: P6 Audio Liveness Contract
// Purpose: Regression coverage for seam audio-source ordering invariants.
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <retrovue/blockplan/AudioLookaheadBuffer.hpp>
#include <retrovue/blockplan/PipelineManager.hpp>
#include <retrovue/buffer/FrameRingBuffer.h>

namespace retrovue::blockplan::testing {
namespace {

static buffer::AudioFrame MakeAudioFrame(int nb_samples, int16_t fill = 0) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels = buffer::kHouseAudioChannels;
  frame.nb_samples = nb_samples;
  const int bytes_per_sample =
      buffer::kHouseAudioChannels * static_cast<int>(sizeof(int16_t));
  frame.data.resize(static_cast<size_t>(nb_samples * bytes_per_sample));
  auto* samples = reinterpret_cast<int16_t*>(frame.data.data());
  for (int i = 0; i < nb_samples * buffer::kHouseAudioChannels; i++) {
    samples[i] = fill;
  }
  return frame;
}

TEST(P6_AudioLivenessNotBlockedByVideoBackpressure,
     DeferredSegmentSwapKeepsTickLoopOnLiveAudioBuffer) {
  AudioLookaheadBuffer live_audio(1000);
  AudioLookaheadBuffer preview_audio(1000);
  AudioLookaheadBuffer seg_b_audio(1000);

  // Arrange: seam reached, but incoming segment-B audio below 500ms threshold.
  live_audio.Push(MakeAudioFrame(48000));   // 1000ms
  seg_b_audio.Push(MakeAudioFrame(2400));   // 50ms (< 500ms defer condition)
  ASSERT_LT(seg_b_audio.DepthMs(), 500);

  AudioLookaheadBuffer* a_src = PipelineManager::SelectAudioSourceForTick(
      /*take_block=*/false,
      /*take_segment=*/true,
      /*segment_swap_committed=*/false,
      &live_audio,
      &preview_audio,
      &seg_b_audio);

  // INV-SEAM-AUDIO-001: while deferred, tick loop must not consume segment-B audio.
  ASSERT_NE(a_src, &seg_b_audio);
  ASSERT_EQ(a_src, &live_audio);

  const int64_t b_popped_before = seg_b_audio.TotalSamplesPopped();
  const int64_t live_popped_before = live_audio.TotalSamplesPopped();

  buffer::AudioFrame out;
  ASSERT_TRUE(a_src->TryPopSamples(1600, out));

  EXPECT_EQ(seg_b_audio.TotalSamplesPopped(), b_popped_before);
  EXPECT_GT(live_audio.TotalSamplesPopped(), live_popped_before);
}

TEST(P6_AudioLivenessNotBlockedByVideoBackpressure,
     SegmentBSwapCommitsOnlyAfterThresholdThenBindsAudioSource) {
  AudioLookaheadBuffer live_audio(1000);
  AudioLookaheadBuffer preview_audio(1000);
  AudioLookaheadBuffer seg_b_audio(1000);

  live_audio.Push(MakeAudioFrame(48000));

  // Deferred phase.
  seg_b_audio.Push(MakeAudioFrame(2400));  // 50ms
  ASSERT_LT(seg_b_audio.DepthMs(), 500);

  AudioLookaheadBuffer* deferred_src = PipelineManager::SelectAudioSourceForTick(
      false, true, false, &live_audio, &preview_audio, &seg_b_audio);
  ASSERT_EQ(deferred_src, &live_audio);

  const int64_t b_popped_before = seg_b_audio.TotalSamplesPopped();
  buffer::AudioFrame out;
  ASSERT_TRUE(deferred_src->TryPopSamples(1600, out));
  EXPECT_EQ(seg_b_audio.TotalSamplesPopped(), b_popped_before);

  // Simulate pre-roll filling B until gate threshold is satisfied.
  seg_b_audio.Push(MakeAudioFrame(24000));  // +500ms
  ASSERT_GE(seg_b_audio.DepthMs(), 500);

  // Commit phase: only now may tick loop bind to segment-B audio.
  AudioLookaheadBuffer* committed_src = PipelineManager::SelectAudioSourceForTick(
      false, true, true, &live_audio, &preview_audio, &seg_b_audio);
  ASSERT_EQ(committed_src, &seg_b_audio);

  const int64_t b_popped_commit_before = seg_b_audio.TotalSamplesPopped();
  ASSERT_TRUE(committed_src->TryPopSamples(1600, out));
  EXPECT_GT(seg_b_audio.TotalSamplesPopped(), b_popped_commit_before);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
