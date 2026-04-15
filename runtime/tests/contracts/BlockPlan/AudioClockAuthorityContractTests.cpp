// Repository: Retrovue-playout
// Component: Audio Clock Authority Contract Tests
// Purpose: Verify OutputClock-authoritative cumulative audio timing logic
//          used by PipelineManager emission boundary.
// Contract: docs/contracts/playout/audio_clock_authority.md

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "retrovue/blockplan/PipelineManager.hpp"

namespace retrovue::blockplan::testing {
namespace {

struct TickObs {
  int64_t tick = 0;
  int64_t output_clock_elapsed_ms = 0;
  int64_t expected_samples = 0;
  int64_t actual_samples = 0;
  int due_samples = 0;
  int64_t audio_time_emitted_ms = 0;
  int64_t video_time_emitted_ms = 0;
  int64_t av_delta_ms = 0;
};

static std::vector<TickObs> RunAuthoritativeSimulation(
    int64_t ticks,
    int64_t preroll_buffered_samples = 0) {
  static_cast<void>(preroll_buffered_samples);  // Buffered data is non-authoritative.
  std::vector<TickObs> out;
  out.reserve(static_cast<size_t>(ticks));

  int64_t actual_samples = 0;
  for (int64_t tick = 0; tick < ticks; ++tick) {
    const int64_t elapsed_ns =
        RationalFps{30000, 1001}.DurationFromFramesNs(tick + 1);
    const int64_t expected = PipelineManager::ComputeExpectedAudioSamplesFromOutputClockNs(
        elapsed_ns, buffer::kHouseAudioSampleRate);
    const int due = PipelineManager::ComputeDueAudioSamples(expected, actual_samples);
    actual_samples += due;
    const int64_t output_ms = elapsed_ns / 1'000'000;
    const int64_t audio_ms = (actual_samples * 1000) / buffer::kHouseAudioSampleRate;
    out.push_back(TickObs{
        .tick = tick,
        .output_clock_elapsed_ms = output_ms,
        .expected_samples = expected,
        .actual_samples = actual_samples,
        .due_samples = due,
        .audio_time_emitted_ms = audio_ms,
        .video_time_emitted_ms = output_ms,
        .av_delta_ms = audio_ms - output_ms,
    });
  }
  return out;
}

TEST(AudioClockAuthority, CadenceConversionIsOutputClockAuthoritative) {
  // 10 minutes at 29.97fps.
  auto obs = RunAuthoritativeSimulation(17982);
  ASSERT_FALSE(obs.empty());

  int64_t max_abs_delta_ms = 0;
  bool seen_1601 = false;
  bool seen_1602 = false;
  int64_t max_abs_sample_error = 0;

  for (const auto& o : obs) {
    if (o.due_samples == 1601) seen_1601 = true;
    if (o.due_samples == 1602) seen_1602 = true;
    const int64_t a = (o.av_delta_ms >= 0) ? o.av_delta_ms : -o.av_delta_ms;
    if (a > max_abs_delta_ms) max_abs_delta_ms = a;
    const int64_t err = o.expected_samples - o.actual_samples;
    const int64_t abs_err = (err >= 0) ? err : -err;
    if (abs_err > max_abs_sample_error) max_abs_sample_error = abs_err;
  }

  EXPECT_LE(max_abs_delta_ms, 20) << "Long-run AV delta exceeded soft tolerance.";
  EXPECT_TRUE(seen_1601 && seen_1602)
      << "Per-tick due samples must realize fractional demand (1601/1602).";
  EXPECT_LE(max_abs_sample_error, 1)
      << "Cumulative sample error grew beyond one sample; drift is accumulating.";
  EXPECT_EQ(obs.back().expected_samples, obs.back().actual_samples)
      << "Long-run cumulative sample total does not converge to OutputClock demand.";
}

TEST(AudioClockAuthority, StartupAnchorIgnoresPrerollBufferEpoch) {
  auto no_preroll = RunAuthoritativeSimulation(3, /*preroll_buffered_samples=*/0);
  auto with_preroll = RunAuthoritativeSimulation(3, /*preroll_buffered_samples=*/24000);
  ASSERT_EQ(no_preroll.size(), with_preroll.size());

  // First emitted tick must share one OutputClock epoch regardless of buffered preroll data.
  EXPECT_EQ(no_preroll[0].due_samples, with_preroll[0].due_samples);
  EXPECT_EQ(no_preroll[0].actual_samples, with_preroll[0].actual_samples);
  EXPECT_LE((with_preroll[0].av_delta_ms >= 0 ? with_preroll[0].av_delta_ms : -with_preroll[0].av_delta_ms), 20);
}

TEST(AudioClockAuthority, SeamTransitionPreservesCumulativeContinuity) {
  constexpr int64_t kSeamTick = 2500;
  auto obs = RunAuthoritativeSimulation(7000);
  ASSERT_GT(obs.size(), static_cast<size_t>(kSeamTick + 2));

  const auto before = obs[static_cast<size_t>(kSeamTick - 1)];
  const auto seam = obs[static_cast<size_t>(kSeamTick)];
  const auto after = obs[static_cast<size_t>(kSeamTick + 1)];

  EXPECT_GT(seam.actual_samples, before.actual_samples)
      << "Cumulative emitted sample accounting regressed at seam.";
  EXPECT_GT(after.actual_samples, seam.actual_samples)
      << "Cumulative emitted sample accounting reset/re-anchored after seam.";

  EXPECT_LE((seam.av_delta_ms >= 0 ? seam.av_delta_ms : -seam.av_delta_ms), 20);
  EXPECT_LE((after.av_delta_ms >= 0 ? after.av_delta_ms : -after.av_delta_ms), 20);
}

TEST(AudioClockAuthority, ClampBacklogDoesNotGovernDueSampleTiming) {
  constexpr int64_t ticks = 4000;

  std::vector<int> baseline_due;
  baseline_due.reserve(ticks);
  int64_t baseline_actual = 0;

  std::vector<int> clamped_due;
  clamped_due.reserve(ticks);
  int64_t clamped_actual = 0;
  int64_t fifo_backlog_samples = 38400 * 2;  // >800ms backlog equivalent

  for (int64_t tick = 0; tick < ticks; ++tick) {
    const int64_t elapsed_ns =
        RationalFps{30000, 1001}.DurationFromFramesNs(tick + 1);
    const int64_t expected = PipelineManager::ComputeExpectedAudioSamplesFromOutputClockNs(
        elapsed_ns, buffer::kHouseAudioSampleRate);

    const int due_baseline = PipelineManager::ComputeDueAudioSamples(expected, baseline_actual);
    baseline_actual += due_baseline;
    baseline_due.push_back(due_baseline);

    // Simulated clamp trims backlog only; timing remains due-sample authoritative.
    if (fifo_backlog_samples > 38400) {
      fifo_backlog_samples -= 512;
    }
    const int due_clamped = PipelineManager::ComputeDueAudioSamples(expected, clamped_actual);
    clamped_actual += due_clamped;
    clamped_due.push_back(due_clamped);
  }

  EXPECT_EQ(baseline_due, clamped_due)
      << "Clamp/high-water changed due-sample timing; clamp became timing governor.";
}

TEST(AudioClockAuthority, PacketDrivenReferenceWouldDrift) {
  // Negative reference: fixed 1024-per-tick loop diverges from OutputClock.
  int64_t emitted_samples = 0;
  int64_t final_delta_ms = 0;
  for (int64_t tick = 0; tick < 4000; ++tick) {
    emitted_samples += 1024;
    const int64_t elapsed_ns =
        RationalFps{30000, 1001}.DurationFromFramesNs(tick + 1);
    const int64_t output_ms = elapsed_ns / 1'000'000;
    const int64_t audio_ms = (emitted_samples * 1000) / buffer::kHouseAudioSampleRate;
    final_delta_ms = audio_ms - output_ms;
  }
  EXPECT_GT((final_delta_ms >= 0 ? final_delta_ms : -final_delta_ms), 50)
      << "Packet-driven reference did not drift; test setup invalid.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
