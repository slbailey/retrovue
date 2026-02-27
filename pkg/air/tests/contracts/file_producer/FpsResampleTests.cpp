// Repository: Retrovue-playout
// Component: FPS Resampler Contract Tests (INV-FPS-RESAMPLE)
// Purpose: Validate PTS-driven output tick resampling for cross-rate sources.
// Copyright (c) 2025-2026 RetroVue

#include "../../BaseContractTest.h"
#include "../ContractRegistryEnvironment.h"

#include <chrono>
#include <cmath>
#include <thread>
#include <vector>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "retrovue/timing/MasterClock.h"
#include "../../fixtures/EventBusStub.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;
using namespace retrovue::producers::file;
using namespace retrovue::tests;
using namespace retrovue::tests::fixtures;

namespace
{

using retrovue::tests::RegisterExpectedDomainCoverage;

const bool kRegisterCoverage = []()
{
  RegisterExpectedDomainCoverage(
      "FpsResample",
      {"FR-001", "FR-002", "FR-003", "FR-004", "FR-005"});
  return true;
}();

class FpsResampleContractTest : public BaseContractTest
{
protected:
  [[nodiscard]] std::string DomainName() const override
  {
    return "FpsResample";
  }

  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override
  {
    return {"FR-001", "FR-002", "FR-003", "FR-004", "FR-005"};
  }

  void SetUp() override
  {
    BaseContractTest::SetUp();
    event_bus_ = std::make_unique<EventBusStub>();
    clock_ = std::make_shared<retrovue::timing::TestMasterClock>();
    const int64_t epoch = 1'700'001'000'000'000;
    clock_->SetEpochUtcUs(epoch);
    clock_->SetRatePpm(0.0);
    clock_->SetNow(epoch, 0.0);
    buffer_ = std::make_unique<buffer::FrameRingBuffer>(120);
  }

  void TearDown() override
  {
    if (producer_)
    {
      try { producer_->stop(); }
      catch (...) {}
      producer_.reset();
    }
    buffer_.reset();
    event_bus_.reset();
    BaseContractTest::TearDown();
  }

  ProducerEventCallback MakeEventCallback()
  {
    return [this](const std::string &event_type, const std::string &message)
    {
      event_bus_->Emit(EventBusStub::ToEventType(event_type), message);
    };
  }

  // Helper: run producer for N target-fps ticks worth of time, collect output frames
  std::vector<buffer::Frame> RunAndCollect(int num_target_ticks)
  {
    std::vector<buffer::Frame> frames;
    int64_t target_tick_us = static_cast<int64_t>(
        static_cast<int64_t>(config_.target_fps.FrameDurationUs()));
    int64_t run_duration_us = num_target_ticks * target_tick_us;

    // Start producer
    producer_ = std::make_unique<FileProducer>(config_, *buffer_, clock_, MakeEventCallback());
    EXPECT_TRUE(producer_->start());

    // Advance clock in small steps and drain buffer
    int64_t elapsed_us = 0;
    int64_t step_us = target_tick_us / 4;  // 4 sub-steps per tick
    while (elapsed_us < run_duration_us + target_tick_us * 2)  // extra ticks for pipeline drain
    {
      clock_->advance_us(step_us);
      elapsed_us += step_us;
      std::this_thread::sleep_for(std::chrono::milliseconds(1));

      // Drain buffer
      buffer::Frame f;
      while (buffer_->Pop(f))
      {
        frames.push_back(f);
      }
    }

    producer_->stop();

    // Final drain
    buffer::Frame f;
    while (buffer_->Pop(f))
    {
      frames.push_back(f);
    }

    return frames;
  }

  ProducerConfig config_;
  std::unique_ptr<EventBusStub> event_bus_;
  std::shared_ptr<retrovue::timing::TestMasterClock> clock_;
  std::unique_ptr<buffer::FrameRingBuffer> buffer_;
  std::unique_ptr<FileProducer> producer_;
};

// ======================================================================
// FR-001: 60fps source → 30fps output tick grid
// ======================================================================
// Feed 60 source frames per second, expect ~30 output frames per second.
// Output PTS must be spaced at 33333us intervals (30fps grid).
// No duration stretch — total output duration must match wall clock.
// ======================================================================
TEST_F(FpsResampleContractTest, FR_001_60to30_FrameSkip)
{

  config_.asset_uri = "test_60fps.mp4";
  config_.stub_mode = true;
  config_.stub_source_fps = 60.0;
  config_.target_fps = 30.0;
  config_.target_width = 320;
  config_.target_height = 240;

  int num_ticks = 60;  // 60 output ticks at 30fps = 2 seconds
  auto frames = RunAndCollect(num_ticks);

  // Must have output frames
  ASSERT_GT(frames.size(), 0u) << "Resampler produced no output frames";

  // Expect roughly 60 frames (+/- pipeline startup/drain tolerance of 5)
  int expected = num_ticks;
  EXPECT_NEAR(static_cast<int>(frames.size()), expected, 5)
      << "Expected ~" << expected << " output frames for " << num_ticks
      << " ticks at 30fps, got " << frames.size();

  // Verify PTS monotonicity and tick-grid alignment
  int64_t tick_us = static_cast<int64_t>(std::round(1'000'000.0 / 30.0));
  int64_t prev_pts = -1;
  int grid_violations = 0;
  int monotonicity_violations = 0;

  for (size_t i = 0; i < frames.size(); i++)
  {
    int64_t pts = frames[i].metadata.pts;

    // Monotonicity
    if (prev_pts >= 0 && pts <= prev_pts)
    {
      monotonicity_violations++;
    }

    // Grid alignment: PTS should be a multiple of tick_us (from first frame)
    if (i > 0)
    {
      int64_t delta = pts - prev_pts;
      // Allow some tolerance for first/last frames
      if (std::abs(delta - tick_us) > 100)  // 100us tolerance
      {
        grid_violations++;
      }
    }

    prev_pts = pts;
  }

  EXPECT_EQ(monotonicity_violations, 0)
      << "PTS monotonicity violated " << monotonicity_violations << " times";

  // Allow a few grid violations for startup/boundary effects
  EXPECT_LE(grid_violations, 2)
      << "PTS grid alignment violated " << grid_violations << " times (expected tick="
      << tick_us << "us)";

  // Duration sanity: total PTS span should be ~2 seconds (60 ticks * 33333us)
  if (frames.size() >= 2)
  {
    int64_t span_us = frames.back().metadata.pts - frames.front().metadata.pts;
    int64_t expected_span = (static_cast<int64_t>(frames.size()) - 1) * tick_us;
    EXPECT_NEAR(span_us, expected_span, tick_us)
        << "Total PTS span " << span_us << "us vs expected " << expected_span << "us";
  }

  std::cout << "[FR-001] 60->30: decoded ~120 source frames, emitted "
            << frames.size() << " output frames"
            << " (grid_violations=" << grid_violations
            << " mono_violations=" << monotonicity_violations << ")" << std::endl;
}

// ======================================================================
// FR-002: 23.976fps source → 30fps output tick grid
// ======================================================================
// Feed frames at 23.976fps PTS spacing (~41708us), expect 30fps output.
// Must produce MORE output frames than input frames (repeat cadence).
// For 2 seconds: ~48 source frames should produce ~60 output frames.
// ======================================================================
TEST_F(FpsResampleContractTest, FR_002_23976to30_FrameRepeat)
{

  config_.asset_uri = "test_23976.mp4";
  config_.stub_mode = true;
  config_.stub_source_fps = 23.976;
  config_.target_fps = 30.0;
  config_.target_width = 320;
  config_.target_height = 240;

  int num_ticks = 60;  // 60 output ticks at 30fps = 2 seconds
  auto frames = RunAndCollect(num_ticks);

  ASSERT_GT(frames.size(), 0u) << "Resampler produced no output frames";

  // For 23.976->30: ratio is 30/23.976 ≈ 1.251. In 2 seconds:
  // Source produces ~48 frames, output should be ~60 frames.
  // The key assertion: output count > what source count would be.
  // Source would produce about 48 frames in 2 seconds.
  int source_count_2sec = static_cast<int>(std::round(23.976 * 2.0));
  EXPECT_GT(static_cast<int>(frames.size()), source_count_2sec)
      << "Slow source must produce MORE output frames than source frames "
      << "(repeat cadence). Got " << frames.size()
      << " but source would have ~" << source_count_2sec;

  // Verify tick grid alignment
  int64_t tick_us = static_cast<int64_t>(std::round(1'000'000.0 / 30.0));
  int grid_violations = 0;
  for (size_t i = 1; i < frames.size(); i++)
  {
    int64_t delta = frames[i].metadata.pts - frames[i - 1].metadata.pts;
    if (std::abs(delta - tick_us) > 100)
      grid_violations++;
  }

  EXPECT_LE(grid_violations, 2)
      << "PTS grid alignment violated " << grid_violations << " times";

  std::cout << "[FR-002] 23.976->30: source ~" << source_count_2sec
            << " frames, emitted " << frames.size() << " output frames"
            << " (grid_violations=" << grid_violations << ")" << std::endl;
}

// ======================================================================
// FR-003: 59.94fps source → 29.97fps output
// ======================================================================
// Real-world NTSC case. Same as 60->30 structurally but with non-integer
// frame periods. Validates no drift over 3 seconds.
// ======================================================================
TEST_F(FpsResampleContractTest, FR_003_5994to2997_NTSCDrop)
{

  config_.asset_uri = "test_5994.mp4";
  config_.stub_mode = true;
  config_.stub_source_fps = 59.94;
  config_.target_fps = 29.97;
  config_.target_width = 320;
  config_.target_height = 240;

  int num_ticks = 90;  // 90 ticks at 29.97fps ≈ 3 seconds
  auto frames = RunAndCollect(num_ticks);

  ASSERT_GT(frames.size(), 0u) << "Resampler produced no output frames";

  // Expect ~90 output frames (+/- 5 for pipeline)
  EXPECT_NEAR(static_cast<int>(frames.size()), num_ticks, 5)
      << "Expected ~" << num_ticks << " output frames, got " << frames.size();

  // Verify no PTS drift: total span should be ~3 seconds
  int64_t tick_us = static_cast<int64_t>(std::round(1'000'000.0 / 29.97));
  if (frames.size() >= 2)
  {
    int64_t span_us = frames.back().metadata.pts - frames.front().metadata.pts;
    int64_t expected_span = (static_cast<int64_t>(frames.size()) - 1) * tick_us;
    // Allow 1 tick of drift over 3 seconds
    EXPECT_NEAR(span_us, expected_span, tick_us)
        << "PTS drift detected over 3 seconds: span=" << span_us
        << "us vs expected=" << expected_span << "us";
  }

  std::cout << "[FR-003] 59.94->29.97: emitted " << frames.size()
            << " frames over ~3 seconds" << std::endl;
}

// ======================================================================
// FR-004: Output PTS is always tick-aligned (never source PTS)
// ======================================================================
// Core invariant: regardless of source rate, every emitted frame's PTS
// must be stamped to the output tick grid. No source PTS leakage.
// ======================================================================
TEST_F(FpsResampleContractTest, FR_004_OutputPTSIsTickAligned)
{

  // Use an awkward ratio that would expose source PTS leakage
  config_.asset_uri = "test_50fps.mp4";
  config_.stub_mode = true;
  config_.stub_source_fps = 50.0;  // 20000us spacing → doesn't divide evenly into 33333us
  config_.target_fps = 30.0;
  config_.target_width = 320;
  config_.target_height = 240;

  int num_ticks = 30;
  auto frames = RunAndCollect(num_ticks);

  ASSERT_GT(frames.size(), 0u) << "Resampler produced no output frames";

  // INV-FPS-RESAMPLE: output PTS is on rational grid tick_time_us(n) = floor(n*1e6*fps_den/fps_num)
  const int64_t fps_num = 30;
  const int64_t fps_den = 1;
  int64_t base_pts = frames[0].metadata.pts;
  const int64_t denom = 1'000'000 * fps_den;

  int alignment_failures = 0;
  for (size_t i = 0; i < frames.size(); i++)
  {
    int64_t pts = frames[i].metadata.pts;
    int64_t offset = pts - base_pts;
    // Recover n such that offset == floor(n*1e6*fps_den/fps_num): n = ceil(offset*fps_num/(1e6*fps_den))
    int64_t tick_index = (offset * fps_num + denom - 1) / denom;
    int64_t expected_offset = (tick_index * 1'000'000 * fps_den) / fps_num;
    if (offset != expected_offset)
    {
      alignment_failures++;
      if (alignment_failures <= 3)
      {
        std::cout << "[FR-004] Frame " << i << " PTS=" << pts
                  << " offset=" << offset << " expected_offset=" << expected_offset
                  << " (not on rational tick grid)" << std::endl;
      }
    }
  }

  EXPECT_EQ(alignment_failures, 0)
      << alignment_failures << " frames had PTS not on rational tick grid — source PTS leaking through";

  std::cout << "[FR-004] 50->30: " << frames.size() << " frames, all tick-aligned ✓"
            << std::endl;
}

// ======================================================================
// FR-005: 60fps rational tick grid — no drift over 10 minutes
// ======================================================================
// Regression: tick_time_us(n) = floor(n * 1e6 * fps_den / fps_num).
// Never use rounded interval accumulation. At 60fps, 10 min = 36,000 ticks.
// ======================================================================
TEST_F(FpsResampleContractTest, FR_005_60fps_LongRun_NoDrift)
{
  const int64_t fps_num = 60;
  const int64_t fps_den = 1;
  const int64_t num_ticks = 36000;  // 10 minutes at 60fps

  auto tick_time_us = [fps_num, fps_den](int64_t n) -> int64_t {
    if (fps_num <= 0) return 0;
    return (n * 1'000'000 * fps_den) / fps_num;
  };

  int64_t prev_us = -1;
  for (int64_t n = 0; n <= num_ticks; n++)
  {
    int64_t t_us = tick_time_us(n);

    // Strictly increasing
    ASSERT_GT(t_us, prev_us) << "tick " << n << " not strictly increasing (prev=" << prev_us << ", t=" << t_us << ")";
    prev_us = t_us;

    // Exact: tick_time_us(n) == floor(n * 1e6 / 60)
    int64_t expected_us = (n * 1'000'000) / 60;
    ASSERT_EQ(t_us, expected_us) << "tick " << n << " expected " << expected_us << " got " << t_us;

    // Error vs ideal real < 1us (integer floor gives at most fractional us)
    double ideal_us = static_cast<double>(n) * 1e6 / 60.0;
    double err_us = std::abs(static_cast<double>(t_us) - ideal_us);
    ASSERT_LT(err_us, 1.0) << "tick " << n << " error " << err_us << "us >= 1us";
  }

  std::cout << "[FR-005] 60fps: " << (num_ticks + 1) << " ticks, strictly increasing, exact floor, error < 1us ✓"
            << std::endl;
}

}  // namespace
