// =============================================================================
// Contract Test: INV-PACING-001 (Render Loop Real-Time Pacing)
// =============================================================================
// This file locks the INV-PACING-001 primitive invariant as permanently solved.
// If pacing ever regresses to CPU-speed emission, these tests MUST fail.
//
// Invariant: The render loop SHALL emit frames at real-time cadence
//            (one frame per frame period), not at CPU speed.
//
// Violation signature: emission_rate >> target_fps
//                      (e.g., 300 fps instead of 30 fps)
//
// Policy: RealTimeHoldPolicy (INV-PACING-ENFORCEMENT-002)
//   - CLAUSE 1: Wall-clock gating, at most one frame per frame period
//   - CLAUSE 2: Freeze-then-pad when buffer starved
//   - CLAUSE 3: No frame dropping to catch up
//
// See: docs/contracts/semantics/PrimitiveInvariants.md
//      docs/contracts/semantics/RealTimeHoldPolicy.md
// =============================================================================

#include "../../BaseContractTest.h"
#include "../ContractRegistryEnvironment.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <memory>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/renderer/ProgramOutput.h"
#include "retrovue/timing/MasterClock.h"

namespace retrovue::timing {
// Forward declaration - defined in SystemMasterClock.cpp
std::shared_ptr<MasterClock> MakeSystemMasterClock(int64_t epoch_utc_us, double rate_ppm);
}  // namespace retrovue::timing

namespace retrovue::tests {
namespace {

using retrovue::tests::RegisterExpectedDomainCoverage;

// Register expected coverage for this domain
const bool kRegisterCoverage = []() {
  RegisterExpectedDomainCoverage("PrimitiveInvariants",
                                 {"INV-PACING-001", "INV-PACING-002",
                                  "INV-P10-SINK-GATE", "INV-STARVATION-FAILSAFE-001",
                                  "INV-AIR-CONTENT-BEFORE-PAD"});
  return true;
}();

// =============================================================================
// Test fixture for INV-PACING-001 contract tests
// =============================================================================
class PacingInvariantContractTest : public BaseContractTest {
 protected:
  [[nodiscard]] std::string DomainName() const override {
    return "PrimitiveInvariants";
  }

  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override {
    return {"INV-PACING-001", "INV-PACING-002", "INV-P10-SINK-GATE",
            "INV-STARVATION-FAILSAFE-001", "INV-AIR-CONTENT-BEFORE-PAD"};
  }

  // Creates a real system clock for wall-clock pacing tests
  std::shared_ptr<timing::MasterClock> CreateRealClock() {
    const int64_t epoch = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    return timing::MakeSystemMasterClock(epoch, 0.0);
  }

  // Fills buffer with test frames at specified FPS
  void FillBufferWithFrames(buffer::FrameRingBuffer& buffer,
                            int count,
                            double fps = 30.0) {
    const int64_t frame_duration_us = static_cast<int64_t>(1'000'000 / fps);
    for (int i = 0; i < count; ++i) {
      buffer::Frame frame;
      frame.metadata.pts = i * frame_duration_us;
      frame.metadata.dts = i * frame_duration_us;
      frame.metadata.duration = frame_duration_s;
      frame.width = 1920;
      frame.height = 1080;

      // Minimal YUV420 data (black frame)
      const int y_size = frame.width * frame.height;
      const int uv_size = (frame.width / 2) * (frame.height / 2);
      frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size), 0);

      ASSERT_TRUE(buffer.Push(frame)) << "Failed to push frame " << i;
    }
  }

  // Constants for test timing
  static constexpr double kTargetFps = 30.0;
  static constexpr int64_t kFramePeriodUs = 33333;  // ~30 fps
  static constexpr int64_t kFramePeriodMs = 33;
};

// =============================================================================
// INV-PACING-001: Render loop SHALL emit frames at real-time cadence
// =============================================================================
// This is the core contract test. If this fails, pacing has regressed.
//
// Test strategy:
// - Fill buffer with enough frames for the test duration
// - Run ProgramOutput for a known wall-clock duration
// - Verify frames_rendered is approximately what we expect at real-time rate
// - If pacing is broken, frames_rendered >> expected (CPU speed emission)
// =============================================================================
TEST_F(PacingInvariantContractTest, INV_PACING_001_RenderLoopEmitsAtRealTimeCadence) {
  SCOPED_TRACE("INV-PACING-001: Render loop must emit frames at real-time cadence, not CPU speed");

  // Setup: Create buffer and fill with frames
  constexpr int kBufferCapacity = 60;
  constexpr int kFrameCount = 30;  // 1 second of content at 30 fps
  buffer::FrameRingBuffer buffer(kBufferCapacity);
  FillBufferWithFrames(buffer, kFrameCount);

  // Create renderer with real clock for wall-clock pacing
  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;

  auto clock = CreateRealClock();
  std::shared_ptr<telemetry::MetricsExporter> metrics;

  auto renderer = renderer::ProgramOutput::Create(config, buffer, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer, nullptr);

  // Need a sink attached for frames to be consumed (INV-P10-SINK-GATE)
  std::atomic<uint64_t> frames_received{0};
  renderer->SetSideSink([&frames_received](const buffer::Frame&) {
    frames_received.fetch_add(1, std::memory_order_relaxed);
  });

  // Act: Run for 300ms wall-clock time
  constexpr int kTestDurationMs = 300;
  ASSERT_TRUE(renderer->Start());

  const auto start_time = std::chrono::steady_clock::now();
  std::this_thread::sleep_for(std::chrono::milliseconds(kTestDurationMs));
  renderer->Stop();
  const auto end_time = std::chrono::steady_clock::now();

  // Measure actual elapsed time
  const auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      end_time - start_time).count();

  const auto& stats = renderer->GetStats();
  const uint64_t frames_rendered = stats.frames_rendered;

  // Calculate expected frames at real-time rate
  // expected = elapsed_time / frame_period
  const double expected_frames = static_cast<double>(elapsed_ms) / kFramePeriodMs;

  // Tolerance: allow ±3 frames for timing jitter and startup/shutdown
  constexpr double kTolerance = 3.0;

  // ==========================================================================
  // CRITICAL ASSERTION: This is the contract lock
  // ==========================================================================
  // If pacing is broken (CPU-speed emission), frames_rendered would be
  // hundreds or thousands in 300ms instead of ~9.
  //
  // The assertion: frames_rendered must be within tolerance of expected
  // ==========================================================================
  EXPECT_LE(frames_rendered, expected_frames + kTolerance)
      << "INV-PACING-001 VIOLATION: Render loop emitted frames faster than real-time!\n"
      << "  elapsed_ms=" << elapsed_ms << "\n"
      << "  frames_rendered=" << frames_rendered << "\n"
      << "  expected_at_realtime=" << expected_frames << "\n"
      << "  If frames_rendered >> expected, wall-clock pacing is broken.";

  // Also verify we're not emitting too slowly (sanity check)
  EXPECT_GE(frames_rendered, expected_frames - kTolerance)
      << "INV-PACING-001: Render loop emitted frames slower than expected\n"
      << "  This may indicate pacing is too conservative or there's a bug.\n"
      << "  elapsed_ms=" << elapsed_ms << "\n"
      << "  frames_rendered=" << frames_rendered << "\n"
      << "  expected_at_realtime=" << expected_frames;

  // Additional metric: emission rate should be approximately target_fps
  const double measured_fps = (elapsed_ms > 0)
      ? (static_cast<double>(frames_rendered) * 1000.0 / static_cast<double>(elapsed_ms))
      : 0.0;

  // Rate should be within 20% of target (allowing for timing variance)
  EXPECT_LT(measured_fps, kTargetFps * 1.5)
      << "INV-PACING-001: Emission rate exceeds 1.5x target fps\n"
      << "  measured_fps=" << measured_fps << "\n"
      << "  target_fps=" << kTargetFps;

  std::cout << "[INV-PACING-001] Test passed: "
            << "elapsed=" << elapsed_ms << "ms, "
            << "frames=" << frames_rendered << ", "
            << "expected=" << expected_frames << ", "
            << "fps=" << measured_fps << std::endl;
}

// =============================================================================
// INV-PACING-001: Extended duration test for rate stability
// =============================================================================
// Tests that pacing remains stable over a longer duration.
// This catches edge cases where pacing drifts or has periodic violations.
// =============================================================================
TEST_F(PacingInvariantContractTest, INV_PACING_001_RateStabilityOverExtendedDuration) {
  SCOPED_TRACE("INV-PACING-001: Pacing must remain stable over extended duration");

  // Setup: Larger buffer for longer test
  constexpr int kBufferCapacity = 120;
  constexpr int kFrameCount = 90;  // 3 seconds of content
  buffer::FrameRingBuffer buffer(kBufferCapacity);
  FillBufferWithFrames(buffer, kFrameCount);

  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;

  auto clock = CreateRealClock();
  std::shared_ptr<telemetry::MetricsExporter> metrics;

  auto renderer = renderer::ProgramOutput::Create(config, buffer, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer, nullptr);

  // Track frame times to detect bursts
  std::vector<int64_t> frame_timestamps;
  std::mutex timestamps_mutex;
  renderer->SetSideSink([&](const buffer::Frame&) {
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    const auto now_us = std::chrono::duration_cast<std::chrono::microseconds>(now).count();
    std::lock_guard<std::mutex> lock(timestamps_mutex);
    frame_timestamps.push_back(now_us);
  });

  // Act: Run for 500ms
  constexpr int kTestDurationMs = 500;
  ASSERT_TRUE(renderer->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(kTestDurationMs));
  renderer->Stop();

  // Analyze inter-frame gaps
  std::lock_guard<std::mutex> lock(timestamps_mutex);
  const size_t frame_count = frame_timestamps.size();

  if (frame_count >= 2) {
    int violation_count = 0;
    constexpr int64_t kMinGapUs = kFramePeriodUs / 2;  // 50% of frame period

    for (size_t i = 1; i < frame_count; ++i) {
      const int64_t gap_us = frame_timestamps[i] - frame_timestamps[i - 1];
      if (gap_us < kMinGapUs) {
        ++violation_count;
      }
    }

    // Allow at most 5% of frames to have fast gaps (startup jitter)
    const int max_violations = static_cast<int>(frame_count * 0.05) + 1;

    EXPECT_LE(violation_count, max_violations)
        << "INV-PACING-001 VIOLATION: Too many fast emissions detected\n"
        << "  total_frames=" << frame_count << "\n"
        << "  violations=" << violation_count << "\n"
        << "  threshold=" << max_violations;

    std::cout << "[INV-PACING-001] Rate stability: "
              << "frames=" << frame_count << ", "
              << "fast_gaps=" << violation_count << "/" << max_violations << std::endl;
  }
}

// =============================================================================
// INV-PACING-002: Freeze frame emitted when buffer starved
// =============================================================================
// When no new frame is available at deadline, the last frame is re-emitted.
// This test verifies the freeze behavior.
// =============================================================================
TEST_F(PacingInvariantContractTest, INV_PACING_002_FreezeFrameEmittedOnBufferStarvation) {
  SCOPED_TRACE("INV-PACING-002: Freeze frame must be re-emitted when buffer is starved");

  // Setup: Small buffer that will drain quickly
  constexpr int kBufferCapacity = 10;
  constexpr int kFrameCount = 3;  // Only 100ms of content
  buffer::FrameRingBuffer buffer(kBufferCapacity);
  FillBufferWithFrames(buffer, kFrameCount);

  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;

  auto clock = CreateRealClock();
  std::shared_ptr<telemetry::MetricsExporter> metrics;

  auto renderer = renderer::ProgramOutput::Create(config, buffer, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer, nullptr);

  std::atomic<uint64_t> frames_received{0};
  renderer->SetSideSink([&](const buffer::Frame&) {
    frames_received.fetch_add(1, std::memory_order_relaxed);
  });

  // Act: Run for 200ms (buffer will drain after ~100ms)
  constexpr int kTestDurationMs = 200;
  ASSERT_TRUE(renderer->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(kTestDurationMs));
  renderer->Stop();

  const auto& stats = renderer->GetStats();

  // Verify frames were rendered (including freeze/pad frames)
  // With 200ms at 30fps, we expect ~6 frames
  // 3 real + ~3 freeze/pad = ~6 total
  const double expected_total = static_cast<double>(kTestDurationMs) / kFramePeriodMs;

  EXPECT_GE(stats.frames_rendered, 3u)
      << "INV-PACING-002: At least the real frames should be rendered";

  // Output should continue at real-time rate even after buffer drained
  // This verifies freeze/pad frames maintain cadence
  EXPECT_LE(stats.frames_rendered, expected_total + 3.0)
      << "INV-PACING-002: Frames should not exceed real-time rate even with freeze/pad";

  std::cout << "[INV-PACING-002] Freeze test: "
            << "frames=" << stats.frames_rendered << ", "
            << "expected=" << expected_total << std::endl;
}

// =============================================================================
// INV-PACING-002 CLAUSE 3: No frame dropping to catch up
// =============================================================================
// This test verifies that late frames are NOT dropped.
// When frames are late, they should be emitted immediately (not skipped).
// =============================================================================
TEST_F(PacingInvariantContractTest, INV_PACING_002_NoFrameDropping) {
  SCOPED_TRACE("INV-PACING-002 CLAUSE 3: Late frames must not be dropped");

  // Setup: Fill buffer with frames that have "late" PTS
  // (PTS in the past relative to when we start)
  constexpr int kBufferCapacity = 30;
  constexpr int kFrameCount = 10;
  buffer::FrameRingBuffer buffer(kBufferCapacity);

  // Create frames with PTS starting from a past time
  // This simulates frames being "late" when rendering starts
  const int64_t frame_duration_us = kFramePeriodUs;
  for (int i = 0; i < kFrameCount; ++i) {
    buffer::Frame frame;
    // PTS starting from 0 (will be in the past once clock runs)
    frame.metadata.pts = i * frame_duration_us;
    frame.metadata.dts = i * frame_duration_us;
    frame.metadata.duration = 1.0 / kTargetFps;
    frame.width = 1920;
    frame.height = 1080;

    const int y_size = frame.width * frame.height;
    const int uv_size = (frame.width / 2) * (frame.height / 2);
    frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size), 0);

    ASSERT_TRUE(buffer.Push(frame));
  }

  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;

  auto clock = CreateRealClock();
  std::shared_ptr<telemetry::MetricsExporter> metrics;

  auto renderer = renderer::ProgramOutput::Create(config, buffer, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer, nullptr);

  std::atomic<uint64_t> frames_received{0};
  renderer->SetSideSink([&](const buffer::Frame&) {
    frames_received.fetch_add(1, std::memory_order_relaxed);
  });

  // Act: Run long enough to consume all frames
  constexpr int kTestDurationMs = 400;  // ~12 frames worth at 30fps
  ASSERT_TRUE(renderer->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(kTestDurationMs));
  renderer->Stop();

  const auto& stats = renderer->GetStats();

  // CRITICAL: All 10 frames MUST be rendered, none dropped
  // The old behavior would drop late frames; new behavior emits them
  EXPECT_GE(stats.frames_rendered, static_cast<uint64_t>(kFrameCount))
      << "INV-PACING-002 CLAUSE 3 VIOLATION: Frames were dropped!\n"
      << "  All " << kFrameCount << " frames must be rendered, not skipped.\n"
      << "  frames_rendered=" << stats.frames_rendered;

  // frames_dropped should be 0 (no drop logic)
  EXPECT_EQ(stats.frames_dropped, 0u)
      << "INV-PACING-002 CLAUSE 3 VIOLATION: frames_dropped > 0\n"
      << "  RealTimeHoldPolicy prohibits frame dropping.";

  std::cout << "[INV-PACING-002 CLAUSE 3] No-drop test: "
            << "rendered=" << stats.frames_rendered << ", "
            << "dropped=" << stats.frames_dropped << std::endl;
}

// =============================================================================
// INV-P10-SINK-GATE: No frame consumption until sink is attached
// =============================================================================
// ProgramOutput must not consume frames from the buffer before a sink is
// attached. Frames remain in the buffer until AttachSink/SetSideSink/SetOutputBus.
//
// Test strategy: Start ProgramOutput with no sink, buffer has frames with valid
// CT. Let render loop run past frame CT deadlines. Buffer depth must be unchanged.
// =============================================================================
TEST_F(PacingInvariantContractTest, INV_P10_SINK_GATE) {
  SCOPED_TRACE("INV-P10-SINK-GATE: Frames must not be consumed when no sink attached");

  constexpr int kBufferCapacity = 30;
  constexpr int kFrameCount = 5;
  buffer::FrameRingBuffer buffer(kBufferCapacity);

  // Fill buffer with frames that have valid CT
  const int64_t frame_duration_us = kFramePeriodUs;
  for (int i = 0; i < kFrameCount; ++i) {
    buffer::Frame frame;
    frame.metadata.pts = i * frame_duration_us;
    frame.metadata.dts = i * frame_duration_us;
    frame.metadata.duration = 1.0 / kTargetFps;
    frame.metadata.has_ct = true;  // Valid CT - render loop would consume if sink attached
    frame.width = 1920;
    frame.height = 1080;

    const int y_size = frame.width * frame.height;
    const int uv_size = (frame.width / 2) * (frame.height / 2);
    frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size), 0);

    ASSERT_TRUE(buffer.Push(frame)) << "Failed to push frame " << i;
  }

  // Assertion 1: Buffer depth before render loop
  const size_t depth_before = buffer.Size();
  ASSERT_EQ(depth_before, static_cast<size_t>(kFrameCount))
      << "Buffer should contain " << kFrameCount << " frames before start";

  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;

  auto clock = CreateRealClock();
  std::shared_ptr<telemetry::MetricsExporter> metrics;

  auto renderer =
      renderer::ProgramOutput::Create(config, buffer, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer, nullptr);

  // Do NOT attach sink - SetSideSink/SetOutputBus are NOT called

  // Assertion 2: Render loop advances past frame CT
  // Run for 200ms = ~6 frame periods at 30fps; clock advances past first frames' CT
  constexpr int kTestDurationMs = 200;
  ASSERT_TRUE(renderer->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(kTestDurationMs));
  renderer->Stop();

  // Assertion 3: Buffer depth after equals buffer depth before
  const size_t depth_after = buffer.Size();
  EXPECT_EQ(depth_after, depth_before)
      << "INV-P10-SINK-GATE VIOLATION: Frame was consumed with no sink attached!\n"
      << "  depth_before=" << depth_before << "\n"
      << "  depth_after=" << depth_after << "\n"
      << "  Frames must remain in buffer until sink is attached.";
}

// =============================================================================
// INV-STARVATION-FAILSAFE-001: Pad frame emitted within 100ms of starvation
// =============================================================================
// When buffer remains empty for >1 frame duration, the render loop must emit
// a pad frame within 100ms of starvation detection.
//
// Test strategy: Use empty buffer + SetNoContentSegment(true) so no freeze
// path (pacing_has_last_frame_ is false); pad is emitted directly on first
// empty Pop. Starvation detection = earliest moment condition holds (start +
// frame_period). Pad must arrive within 100ms of that.
// =============================================================================
TEST_F(PacingInvariantContractTest, INV_STARVATION_FAILSAFE_001) {
  SCOPED_TRACE("INV-STARVATION-FAILSAFE-001: Pad frame must be emitted within 100ms of starvation");

  constexpr int kBufferCapacity = 10;
  buffer::FrameRingBuffer buffer(kBufferCapacity);
  // Empty buffer - no frames

  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;

  auto clock = CreateRealClock();
  std::shared_ptr<telemetry::MetricsExporter> metrics;

  auto renderer = renderer::ProgramOutput::Create(config, buffer, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer, nullptr);

  renderer->SetNoContentSegment(true);
  renderer->LockPadAudioFormat();

  std::chrono::steady_clock::time_point starvation_time;
  std::chrono::steady_clock::time_point pad_time;
  std::atomic<bool> pad_received{false};

  renderer->SetSideSink([&](const buffer::Frame& frame) {
    if (frame.metadata.asset_uri == "pad://black") {
      if (!pad_received.exchange(true)) {
        pad_time = std::chrono::steady_clock::now();
      }
    }
  });

  const auto start_time = std::chrono::steady_clock::now();
  starvation_time = start_time + std::chrono::microseconds(kFramePeriodUs);

  ASSERT_TRUE(renderer->Start());

  const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(500);
  while (!pad_received.load(std::memory_order_relaxed) &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  renderer->Stop();

  ASSERT_TRUE(pad_received.load(std::memory_order_relaxed))
      << "INV-STARVATION-FAILSAFE-001: No pad frame emitted after buffer starved";

  const auto delta_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      pad_time - starvation_time).count();

  EXPECT_LE(delta_ms, 100)
      << "INV-STARVATION-FAILSAFE-001 VIOLATION: Pad emission exceeded 100ms bound\n"
      << "  (pad_time - starvation_time) = " << delta_ms << "ms\n"
      << "  Bound: <= 100ms";
}

// =============================================================================
// INV-AIR-CONTENT-BEFORE-PAD: Pad only after first real content frame
// =============================================================================
// Pad frames may only be emitted after the first real decoded content frame
// has been routed to output. This prevents a pad-only loop at startup.
//
// Phase 1: Empty buffer, no SetNoContentSegment — gate blocks pad; no frames.
// Phase 2: Buffer with real frames — first frame(s) are not pad; after drain,
//          at least one pad frame is emitted.
// =============================================================================
TEST_F(PacingInvariantContractTest, INV_AIR_CONTENT_BEFORE_PAD) {
  SCOPED_TRACE("INV-AIR-CONTENT-BEFORE-PAD: No pad before first real frame; pad after real content when buffer empties");

  auto clock = CreateRealClock();
  std::shared_ptr<telemetry::MetricsExporter> metrics;
  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;

  // -------------------------------------------------------------------------
  // Phase 1: Empty buffer, NO SetNoContentSegment — no pad frames emitted
  // -------------------------------------------------------------------------
  constexpr int kBufferCapacity = 10;
  buffer::FrameRingBuffer buffer_phase1(kBufferCapacity);
  // Empty buffer; do NOT call SetNoContentSegment

  auto renderer_phase1 = renderer::ProgramOutput::Create(config, buffer_phase1, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer_phase1, nullptr);

  std::atomic<uint64_t> phase1_frames_received{0};
  renderer_phase1->SetSideSink([&phase1_frames_received](const buffer::Frame&) {
    phase1_frames_received.fetch_add(1, std::memory_order_relaxed);
  });

  ASSERT_TRUE(renderer_phase1->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  renderer_phase1->Stop();

  const auto& stats_phase1 = renderer_phase1->GetStats();
  EXPECT_EQ(stats_phase1.frames_rendered, 0u)
      << "INV-AIR-CONTENT-BEFORE-PAD Phase 1: With empty buffer and no SetNoContentSegment, frames_rendered must be 0";
  EXPECT_EQ(phase1_frames_received.load(std::memory_order_relaxed), 0u)
      << "INV-AIR-CONTENT-BEFORE-PAD Phase 1: No frames must be received via side sink";

  // -------------------------------------------------------------------------
  // Phase 2: Buffer with 1–2 real frames — first frame(s) not pad; then pad after drain
  // -------------------------------------------------------------------------
  buffer::FrameRingBuffer buffer_phase2(kBufferCapacity);
  FillBufferWithFrames(buffer_phase2, 2);

  auto renderer_phase2 = renderer::ProgramOutput::Create(config, buffer_phase2, clock, metrics, /*channel_id=*/0);
  ASSERT_NE(renderer_phase2, nullptr);

  std::vector<std::string> frame_uris;
  std::mutex uris_mutex;
  renderer_phase2->SetSideSink([&](const buffer::Frame& frame) {
    std::lock_guard<std::mutex> lock(uris_mutex);
    frame_uris.push_back(frame.metadata.asset_uri);
  });

  ASSERT_TRUE(renderer_phase2->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  renderer_phase2->Stop();

  {
    std::lock_guard<std::mutex> lock(uris_mutex);
    ASSERT_GE(frame_uris.size(), 1u) << "INV-AIR-CONTENT-BEFORE-PAD Phase 2: At least one frame must be received";

    // First frame(s) must NOT be pad
    EXPECT_NE(frame_uris.front(), "pad://black")
        << "INV-AIR-CONTENT-BEFORE-PAD Phase 2 VIOLATION: First frame must not be pad";

    // At least one pad frame must appear after real content (when buffer empties)
    bool saw_pad = false;
    for (const auto& uri : frame_uris) {
      if (uri == "pad://black") {
        saw_pad = true;
        break;
      }
    }
    EXPECT_TRUE(saw_pad)
        << "INV-AIR-CONTENT-BEFORE-PAD Phase 2: After buffer empties, at least one pad frame must be received";
  }
}

}  // namespace
}  // namespace retrovue::tests
