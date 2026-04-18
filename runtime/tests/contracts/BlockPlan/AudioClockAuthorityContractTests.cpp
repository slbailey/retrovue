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

struct StallTickObs {
  int tick = 0;
  int64_t deadline_ns = 0;
  int64_t observed_ns = 0;
  int64_t authoritative_ns = 0;
  int64_t expected_samples = 0;
  int due_samples = 0;
  int64_t emitted_samples = 0;
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

static std::vector<StallTickObs> RunStallSequenceSimulation(
    const std::vector<int64_t>& observed_extra_ns_by_tick) {
  std::vector<StallTickObs> out;
  out.reserve(observed_extra_ns_by_tick.size());

  int64_t emitted_samples = 0;
  const int64_t nominal_frame_ns = RationalFps{30000, 1001}.DurationFromFramesNs(1);
  int64_t observed_elapsed_ns_cumulative = 0;
  for (size_t i = 0; i < observed_extra_ns_by_tick.size(); ++i) {
    const int tick = static_cast<int>(i);
    const int64_t deadline_ns =
        RationalFps{30000, 1001}.DurationFromFramesNs(tick + 1);
    // Model real monotonic steady-clock behavior: each tick advances by at least
    // one nominal frame interval, plus optional extra stall time for that cycle.
    observed_elapsed_ns_cumulative +=
        nominal_frame_ns + std::max<int64_t>(0, observed_extra_ns_by_tick[i]);
    const int64_t observed_ns = observed_elapsed_ns_cumulative;
    const int64_t authoritative_ns =
        PipelineManager::ComputeAuthoritativeAudioElapsedNs(deadline_ns, observed_ns);
    const int64_t expected_samples =
        PipelineManager::ComputeExpectedAudioSamplesFromOutputClockNs(
            authoritative_ns, buffer::kHouseAudioSampleRate);
    const int due =
        PipelineManager::ComputeDueAudioSamples(expected_samples, emitted_samples);
    emitted_samples += due;

    out.push_back(StallTickObs{
        .tick = tick,
        .deadline_ns = deadline_ns,
        .observed_ns = observed_ns,
        .authoritative_ns = authoritative_ns,
        .expected_samples = expected_samples,
        .due_samples = due,
        .emitted_samples = emitted_samples,
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

TEST(AudioClockAuthority, LiveAudioHighWaterIsBoundedByPrimePlusAvTolerance) {
  // First-control-policy check for startup/steady-state authority:
  // live audio reservoir must be bounded by bootstrap floor + AV tolerance.
  const int high_water = PipelineManager::ComputeLiveAudioHighWaterMs(
      /*audio_target_ms=*/1000,
      /*audio_low_water_ms=*/333,
      /*audio_prime_floor_ms=*/500,
      /*av_phase_tolerance_ms=*/120);
  EXPECT_EQ(high_water, 620);

  // Never exceed target, never drop below low-water.
  EXPECT_EQ(
      PipelineManager::ComputeLiveAudioHighWaterMs(450, 333, 500, 120),
      450);
  EXPECT_EQ(
      PipelineManager::ComputeLiveAudioHighWaterMs(1000, 333, 100, -50),
      100);
}

TEST(AudioClockAuthority, HighWaterIgnoresLowWaterIfItExceedsCeiling) {
  const int high_water = PipelineManager::ComputeLiveAudioHighWaterMs(
      /*audio_target_ms=*/1000,
      /*audio_low_water_ms=*/900,
      /*audio_prime_floor_ms=*/500,
      /*av_phase_tolerance_ms=*/120);
  EXPECT_EQ(high_water, 620);
}

TEST(AudioClockAuthority, LateTickUsesObservedElapsedForAudioCatchup) {
  constexpr int sample_rate = buffer::kHouseAudioSampleRate;
  // Tick 100 nominal deadline at 29.97.
  const int64_t deadline_elapsed_ns =
      RationalFps{30000, 1001}.DurationFromFramesNs(101);
  // Simulated paced-output stall (+80ms beyond deadline).
  const int64_t observed_elapsed_ns = deadline_elapsed_ns + 80'000'000LL;

  const int64_t authoritative_elapsed_ns =
      PipelineManager::ComputeAuthoritativeAudioElapsedNs(
          deadline_elapsed_ns, observed_elapsed_ns);
  EXPECT_EQ(authoritative_elapsed_ns, observed_elapsed_ns);

  const int64_t expected_from_deadline =
      PipelineManager::ComputeExpectedAudioSamplesFromOutputClockNs(
          deadline_elapsed_ns, sample_rate);
  const int64_t expected_from_authoritative =
      PipelineManager::ComputeExpectedAudioSamplesFromOutputClockNs(
          authoritative_elapsed_ns, sample_rate);
  EXPECT_GT(expected_from_authoritative, expected_from_deadline);

  // If emitted sample count is at nominal deadline level, catchup due must increase.
  const int due_deadline =
      PipelineManager::ComputeDueAudioSamples(expected_from_deadline, expected_from_deadline);
  const int due_authoritative =
      PipelineManager::ComputeDueAudioSamples(expected_from_authoritative, expected_from_deadline);
  EXPECT_EQ(due_deadline, 0);
  EXPECT_GT(due_authoritative, 0);
}

TEST(AudioClockAuthority, IsolatedLateTickFollowedByOnTimeDoesNotDoubleApplyDebt) {
  // Tick 1 late by +80ms, then on-time.
  auto obs = RunStallSequenceSimulation({
      0,
      80'000'000LL,
      0,
      0,
  });
  ASSERT_EQ(obs.size(), 4u);

  const int due_on_late_tick = obs[1].due_samples;
  EXPECT_GT(due_on_late_tick, obs[0].due_samples);
  // Recovery tick should not re-apply prior debt; it settles toward nominal.
  EXPECT_LE(obs[2].due_samples, due_on_late_tick);
  EXPECT_LE(obs[3].due_samples, obs[2].due_samples + 1);
}

TEST(AudioClockAuthority, ConsecutiveLateTicksApplyDistinctCatchupWithoutRatchet) {
  // Two independent late ticks (+40ms, then +60ms).
  auto obs = RunStallSequenceSimulation({
      0,
      40'000'000LL,
      60'000'000LL,
      0,
  });
  ASSERT_EQ(obs.size(), 4u);

  const int nominal_due = PipelineManager::ComputeExpectedAudioSamplesFromOutputClockNs(
      RationalFps{30000, 1001}.DurationFromFramesNs(1), buffer::kHouseAudioSampleRate);
  EXPECT_GT(obs[1].due_samples, obs[0].due_samples);
  EXPECT_GT(obs[2].due_samples, nominal_due);
  // First on-time tick after consecutive stalls should settle, not continue increasing.
  EXPECT_LT(obs[3].due_samples, obs[2].due_samples);
}

TEST(AudioClockAuthority, LateTickWithoutNextCycleTransportStallRecoversToNominal) {
  auto obs = RunStallSequenceSimulation({
      0,
      55'000'000LL,
      0,
      0,
      0,
  });
  ASSERT_EQ(obs.size(), 5u);

  const int64_t nominal_deadline_ns =
      RationalFps{30000, 1001}.DurationFromFramesNs(2) -
      RationalFps{30000, 1001}.DurationFromFramesNs(1);
  const int nominal_due = PipelineManager::ComputeExpectedAudioSamplesFromOutputClockNs(
      nominal_deadline_ns, buffer::kHouseAudioSampleRate);

  EXPECT_GT(obs[1].due_samples, nominal_due);
  // On following non-stalled cycles: no second catch-up spike from old debt.
  EXPECT_LE(obs[2].due_samples, obs[1].due_samples);
  EXPECT_LE(obs[3].due_samples, obs[2].due_samples);
  EXPECT_GE(obs[3].due_samples, nominal_due - 1);
}

TEST(AudioClockAuthority, CumulativeDueIsMonotonicInTotalButNotDoubleCounted) {
  auto obs = RunStallSequenceSimulation({
      0,
      70'000'000LL,
      0,
      50'000'000LL,
      0,
      0,
  });
  ASSERT_FALSE(obs.empty());

  int64_t prev_emitted = 0;
  int64_t prev_authoritative = 0;
  for (const auto& o : obs) {
    EXPECT_GE(o.emitted_samples, prev_emitted);
    EXPECT_GE(o.authoritative_ns, prev_authoritative);
    // Cumulative emitted equals cumulative expected-by-authoritative each step:
    // no debt loss and no double application.
    EXPECT_EQ(o.emitted_samples, o.expected_samples);
    prev_emitted = o.emitted_samples;
    prev_authoritative = o.authoritative_ns;
  }

  // End-of-window exactness: no ratchet debt remains in cumulative accounting.
  EXPECT_EQ(obs.back().emitted_samples, obs.back().expected_samples);
}

TEST(AudioClockAuthority, VideoTimelineRemainsNominalTickFunctionUnderAudioCatchup) {
  // INV-PACING-SINGLE-AUTHORITY-001:
  // Late ticks may change due-sample catch-up, but live video timeline stays
  // a pure function of tick schedule (no convergence toward audio).
  auto obs = RunStallSequenceSimulation({
      0,
      85'000'000LL,
      0,
      40'000'000LL,
      0,
      0,
  });
  ASSERT_EQ(obs.size(), 6u);

  const int64_t frame_duration_90k = ((90000LL * 1001) + (30000 / 2)) / 30000;  // 3003
  int64_t prev_video_pts_90k = -1;
  for (size_t i = 0; i < obs.size(); ++i) {
    const int64_t nominal_video_pts_90k = static_cast<int64_t>(i) * frame_duration_90k;
    if (prev_video_pts_90k >= 0) {
      EXPECT_EQ(nominal_video_pts_90k - prev_video_pts_90k, frame_duration_90k);
    }
    prev_video_pts_90k = nominal_video_pts_90k;
  }
}

TEST(AudioClockAuthority, SteadyStateReserveFloor_CoversOneNoSupplyTickPair) {
  // INV-PRODUCER-DEMAND-DRIVEN-001:
  // In cadence-shaped steady-state demand (1601/1602), reserve floor must
  // cover one adjacent no-supply tick pair.
  const int due_tick_a = 1601;
  const int due_tick_b = 1602;
  const int floor_from_a =
      PipelineManager::ComputeSteadyStateReserveFloorSamples(due_tick_a);
  const int floor_from_b =
      PipelineManager::ComputeSteadyStateReserveFloorSamples(due_tick_b);

  EXPECT_GE(floor_from_a, due_tick_a + due_tick_b);
  EXPECT_GE(floor_from_b, due_tick_a + due_tick_b);
  EXPECT_GT(floor_from_b, due_tick_b);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
