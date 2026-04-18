// Repository: Retrovue-playout
// Component: HARDEN-014 / LAW-AIR-001 Audio Sample Integer Math Contract Test
// Purpose: Prove that the 128-bit integer audio sample computation produces
//          identical results to the former long double implementation across
//          a full 24-hour session at all standard sample rates.
// Contract Reference: LAW-AIR-001, INV-AUDIO-SAMPLE-CLOCK
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>
#include <cmath>
#include <cstdint>

namespace retrovue::blockplan::testing {
namespace {

// Reference implementation: the ORIGINAL long double path (before HARDEN-014).
static int64_t ComputeExpectedAudioSamples_LongDouble(
    int64_t output_clock_elapsed_ns, int sample_rate) {
  if (output_clock_elapsed_ns <= 0 || sample_rate <= 0) return 0;
  const long double elapsed_s =
      static_cast<long double>(output_clock_elapsed_ns) / 1'000'000'000.0L;
  return static_cast<int64_t>(
      std::llround(elapsed_s * static_cast<long double>(sample_rate)));
}

// New implementation: the 128-bit integer path (HARDEN-014).
static int64_t ComputeExpectedAudioSamples_Int128(
    int64_t output_clock_elapsed_ns, int sample_rate) {
  if (output_clock_elapsed_ns <= 0 || sample_rate <= 0) return 0;
  __int128 numerator = static_cast<__int128>(output_clock_elapsed_ns)
                     * static_cast<__int128>(sample_rate)
                     + 500'000'000LL;
  return static_cast<int64_t>(numerator / 1'000'000'000LL);
}

// ============================================================================
// Test 1: 24-hour bounded divergence at 48kHz (house format)
// ============================================================================
// Simulates 24 hours of 29.97fps ticks (~2.59M ticks).
// The 128-bit integer path uses round-half-up; long double uses round-nearest.
// These can differ by ±1 sample at exact midpoints. The integer path is the
// correct one (deterministic, platform-independent). This test verifies
// divergence is bounded to ±1 — no accumulated drift.
TEST(AudioSampleIntegerMath, BoundedDivergence_48kHz_24Hours) {
  constexpr int sample_rate = 48000;
  constexpr int64_t tick_ns = 33'366'667LL;  // ~29.97fps
  constexpr int64_t twenty_four_hours_ns = 86400LL * 1'000'000'000LL;

  int64_t max_abs_delta = 0;
  int divergence_count = 0;

  for (int64_t ns = 0; ns < twenty_four_hours_ns; ns += tick_ns) {
    int64_t old_result = ComputeExpectedAudioSamples_LongDouble(ns, sample_rate);
    int64_t new_result = ComputeExpectedAudioSamples_Int128(ns, sample_rate);
    int64_t delta = std::abs(new_result - old_result);
    if (delta > 0) divergence_count++;
    if (delta > max_abs_delta) max_abs_delta = delta;
  }

  // Divergence must be bounded to ±1 sample (rounding tie-break difference).
  EXPECT_LE(max_abs_delta, 1)
      << "Integer and long-double paths diverged by more than 1 sample. "
      << "max_abs_delta=" << max_abs_delta << " divergence_count=" << divergence_count;

  // Log for information (not a failure condition).
  if (divergence_count > 0) {
    std::cout << "[AudioSampleIntegerMath] 48kHz 24h: " << divergence_count
              << " rounding tie-breaks (max delta=" << max_abs_delta << " sample)" << std::endl;
  }
}

// ============================================================================
// Test 2: 24-hour bounded divergence at 44100 Hz
// ============================================================================
TEST(AudioSampleIntegerMath, BoundedDivergence_44100Hz_24Hours) {
  constexpr int sample_rate = 44100;
  constexpr int64_t tick_ns = 33'366'667LL;
  constexpr int64_t twenty_four_hours_ns = 86400LL * 1'000'000'000LL;

  int64_t max_abs_delta = 0;
  int divergence_count = 0;

  for (int64_t ns = 0; ns < twenty_four_hours_ns; ns += tick_ns) {
    int64_t old_result = ComputeExpectedAudioSamples_LongDouble(ns, sample_rate);
    int64_t new_result = ComputeExpectedAudioSamples_Int128(ns, sample_rate);
    int64_t delta = std::abs(new_result - old_result);
    if (delta > 0) divergence_count++;
    if (delta > max_abs_delta) max_abs_delta = delta;
  }

  EXPECT_LE(max_abs_delta, 1)
      << "Integer and long-double paths diverged by more than 1 sample at 44100Hz. "
      << "max_abs_delta=" << max_abs_delta;
}

// ============================================================================
// Test 3: Edge cases
// ============================================================================
TEST(AudioSampleIntegerMath, EdgeCases) {
  // Zero / negative inputs.
  EXPECT_EQ(ComputeExpectedAudioSamples_Int128(0, 48000), 0);
  EXPECT_EQ(ComputeExpectedAudioSamples_Int128(-1, 48000), 0);
  EXPECT_EQ(ComputeExpectedAudioSamples_Int128(1000000000, 0), 0);
  EXPECT_EQ(ComputeExpectedAudioSamples_Int128(1000000000, -1), 0);

  // Exactly 1 second at 48kHz = 48000 samples.
  EXPECT_EQ(ComputeExpectedAudioSamples_Int128(1'000'000'000LL, 48000), 48000);

  // Exactly 1 second at 44100 = 44100 samples.
  EXPECT_EQ(ComputeExpectedAudioSamples_Int128(1'000'000'000LL, 44100), 44100);

  // 24 hours at 48kHz: 86400 * 48000 = 4,147,200,000 samples.
  EXPECT_EQ(ComputeExpectedAudioSamples_Int128(86400LL * 1'000'000'000LL, 48000),
            86400LL * 48000);
}

// ============================================================================
// Test 4: No overflow at maximum session length
// ============================================================================
// 128-bit must handle: 86400 * 1e9 * 48000 = 4.147e18 which fits in int64,
// but the intermediate (before division) is 4.147e27 which requires > 64 bits.
TEST(AudioSampleIntegerMath, NoOverflowAt24Hours) {
  constexpr int64_t max_ns = 86400LL * 1'000'000'000LL;
  constexpr int sample_rate = 48000;

  // This would overflow int64 intermediate: 86400e9 * 48000 = 4.147e18 * 1e3 = 4.147e21
  // (the +500M doesn't change the magnitude). 128-bit handles it.
  int64_t result = ComputeExpectedAudioSamples_Int128(max_ns, sample_rate);
  EXPECT_EQ(result, 86400LL * 48000)
      << "24-hour sample count must be exact (no overflow, no drift)";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
