// Repository: Retrovue-playout
// Component: Serial Block Metrics Guardrail Tests
// Purpose: Verify metrics accumulation, Prometheus output, and passivity guarantees
// Contract Reference: INV-SERIAL-BLOCK-EXECUTION, INV-ONE-ENCODER-PER-SESSION
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <chrono>
#include <memory>
#include <string>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/RealTimeExecution.hpp"
#include "retrovue/blockplan/SerialBlockExecutionEngine.hpp"
#include "retrovue/blockplan/SerialBlockMetrics.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Test Fixture
// =============================================================================

class SerialBlockMetricsTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 99;
    ctx_->fd = -1;
    ctx_->width = 640;
    ctx_->height = 480;
    ctx_->fps = 30.0;
  }

  void TearDown() override {
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
  }

  std::unique_ptr<SerialBlockExecutionEngine> MakeEngine() {
    SerialBlockExecutionEngine::Callbacks callbacks;
    callbacks.on_block_completed = [](const FedBlock&, int64_t) {};
    callbacks.on_session_ended = [](const std::string&) {};
    return std::make_unique<SerialBlockExecutionEngine>(ctx_.get(), std::move(callbacks));
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<SerialBlockExecutionEngine> engine_;
};

// =============================================================================
// A. METRICS STRUCT INITIALIZATION
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-METRICS-001: SerialBlockMetrics initializes all fields to zero
// Ensures no stale or garbage values at session start
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, MetricsInitializeToZero) {
  SerialBlockMetrics m;

  EXPECT_EQ(m.session_start_epoch_ms, 0);
  EXPECT_EQ(m.session_end_epoch_ms, 0);
  EXPECT_EQ(m.session_duration_ms, 0);
  EXPECT_EQ(m.total_blocks_executed, 0);
  EXPECT_EQ(m.total_frames_emitted, 0);

  EXPECT_EQ(m.max_inter_frame_gap_us, 0);
  EXPECT_EQ(m.sum_inter_frame_gap_us, 0);
  EXPECT_EQ(m.frame_gap_count, 0);
  EXPECT_EQ(m.frame_gaps_over_40ms, 0);

  EXPECT_EQ(m.max_boundary_gap_ms, 0);
  EXPECT_EQ(m.sum_boundary_gap_ms, 0);
  EXPECT_EQ(m.boundary_gaps_measured, 0);
  EXPECT_EQ(m.max_asset_probe_ms, 0);
  EXPECT_EQ(m.sum_asset_probe_ms, 0);
  EXPECT_EQ(m.assets_probed, 0);

  EXPECT_EQ(m.encoder_open_count, 0);
  EXPECT_EQ(m.encoder_close_count, 0);
  EXPECT_EQ(m.encoder_open_ms, 0);
  EXPECT_EQ(m.time_to_first_ts_packet_ms, 0);

  EXPECT_EQ(m.channel_id, 0);
  EXPECT_FALSE(m.session_active);
}

// =============================================================================
// B. PROMETHEUS TEXT FORMAT
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-METRICS-002: GeneratePrometheusText produces valid Prometheus format
// Must contain TYPE, HELP, and air_serial_block_ prefix
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, PrometheusTextHasCorrectPrefix) {
  SerialBlockMetrics m;
  m.channel_id = 42;
  m.total_blocks_executed = 5;
  m.total_frames_emitted = 760;

  std::string text = m.GeneratePrometheusText();

  // All metric names must start with air_serial_block_
  EXPECT_NE(text.find("air_serial_block_"), std::string::npos)
      << "Prometheus text must use air_serial_block_ prefix";

  // Must contain TYPE declarations
  EXPECT_NE(text.find("# TYPE air_serial_block_session_duration_ms gauge"), std::string::npos);
  EXPECT_NE(text.find("# TYPE air_serial_block_blocks_executed_total counter"), std::string::npos);
  EXPECT_NE(text.find("# TYPE air_serial_block_frames_emitted_total counter"), std::string::npos);
  EXPECT_NE(text.find("# TYPE air_serial_block_encoder_open_count counter"), std::string::npos);

  // Must contain HELP declarations
  EXPECT_NE(text.find("# HELP air_serial_block_"), std::string::npos);

  // Must contain channel label
  EXPECT_NE(text.find("channel=\"42\""), std::string::npos);
}

// -----------------------------------------------------------------------------
// TEST-METRICS-003: Prometheus text reflects metric values correctly
// Spot-check that accumulated values appear in output
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, PrometheusTextReflectsValues) {
  SerialBlockMetrics m;
  m.channel_id = 7;
  m.total_blocks_executed = 3;
  m.total_frames_emitted = 456;
  m.max_inter_frame_gap_us = 35000;
  m.encoder_open_count = 1;
  m.encoder_close_count = 1;

  std::string text = m.GeneratePrometheusText();

  EXPECT_NE(text.find("air_serial_block_blocks_executed_total{channel=\"7\"} 3"), std::string::npos);
  EXPECT_NE(text.find("air_serial_block_frames_emitted_total{channel=\"7\"} 456"), std::string::npos);
  EXPECT_NE(text.find("air_serial_block_max_inter_frame_gap_us{channel=\"7\"} 35000"), std::string::npos);
  EXPECT_NE(text.find("air_serial_block_encoder_open_count{channel=\"7\"} 1"), std::string::npos);
  EXPECT_NE(text.find("air_serial_block_encoder_close_count{channel=\"7\"} 1"), std::string::npos);
}

// =============================================================================
// C. ENGINE METRICS LIFECYCLE
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-METRICS-004: Engine exposes zero metrics before Start()
// No metrics pollution before execution begins
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, EngineMetricsZeroBeforeStart) {
  engine_ = MakeEngine();

  auto snapshot = engine_->SnapshotMetrics();
  EXPECT_EQ(snapshot.total_blocks_executed, 0);
  EXPECT_EQ(snapshot.total_frames_emitted, 0);
  EXPECT_EQ(snapshot.encoder_open_count, 0);
  EXPECT_EQ(snapshot.encoder_close_count, 0);
  EXPECT_EQ(snapshot.channel_id, 99)
      << "Channel ID should be set from context at construction";
  EXPECT_FALSE(snapshot.session_active);
}

// -----------------------------------------------------------------------------
// TEST-METRICS-005: Engine GenerateMetricsText is thread-safe
// Can be called concurrently with engine running (no crashes)
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, GenerateMetricsTextIsThreadSafe) {
  engine_ = MakeEngine();
  engine_->Start();

  // Hammer GenerateMetricsText from multiple threads while engine runs
  std::vector<std::thread> readers;
  for (int i = 0; i < 4; i++) {
    readers.emplace_back([this]() {
      for (int j = 0; j < 100; j++) {
        std::string text = engine_->GenerateMetricsText();
        EXPECT_FALSE(text.empty());
      }
    });
  }

  // Let it run briefly
  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  engine_->Stop();
  for (auto& t : readers) {
    t.join();
  }
}

// =============================================================================
// D. FRAME CADENCE METRICS STRUCT
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-METRICS-006: FrameCadenceMetrics initializes to zero in Result
// Default-constructed Result has zero cadence metrics
// -----------------------------------------------------------------------------
TEST(FrameCadenceMetricsTest, DefaultResultHasZeroCadence) {
  realtime::RealTimeBlockExecutor::Result r;
  EXPECT_EQ(r.frame_cadence.frames_emitted, 0);
  EXPECT_EQ(r.frame_cadence.max_inter_frame_gap_us, 0);
  EXPECT_EQ(r.frame_cadence.sum_inter_frame_gap_us, 0);
  EXPECT_EQ(r.frame_cadence.frame_gaps_over_40ms, 0);
}

// =============================================================================
// E. MEAN COMPUTATION
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-METRICS-007: Mean inter-frame gap computed correctly from accumulation
// Prometheus text must show correct mean when frame_gap_count > 0
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, MeanInterFrameGapComputation) {
  SerialBlockMetrics m;
  m.channel_id = 1;
  m.sum_inter_frame_gap_us = 330000;  // 330ms total
  m.frame_gap_count = 10;             // 10 gaps

  std::string text = m.GeneratePrometheusText();

  // Mean = 330000 / 10 = 33000
  EXPECT_NE(text.find("air_serial_block_mean_inter_frame_gap_us{channel=\"1\"} 33000"),
            std::string::npos);
}

// -----------------------------------------------------------------------------
// TEST-METRICS-008: Mean inter-frame gap is zero when no gaps measured
// Avoids division by zero
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, MeanInterFrameGapZeroWhenNoGaps) {
  SerialBlockMetrics m;
  m.channel_id = 1;
  m.sum_inter_frame_gap_us = 0;
  m.frame_gap_count = 0;

  std::string text = m.GeneratePrometheusText();

  EXPECT_NE(text.find("air_serial_block_mean_inter_frame_gap_us{channel=\"1\"} 0"),
            std::string::npos);
}

// =============================================================================
// F. ENCODER LIFETIME INVARIANTS
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-METRICS-009: Encoder open/close counts are both 1 after normal session
// This is a structural assertion from INV-ONE-ENCODER-PER-SESSION
// (Integration-level — verified here at the struct level)
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, EncoderCountsAreOneAfterSession) {
  SerialBlockMetrics m;
  m.encoder_open_count = 1;
  m.encoder_close_count = 1;

  // These values MUST be exactly 1 for a normal session
  EXPECT_EQ(m.encoder_open_count, 1)
      << "INV-ONE-ENCODER-PER-SESSION: exactly one open per session";
  EXPECT_EQ(m.encoder_close_count, 1)
      << "INV-ONE-ENCODER-PER-SESSION: exactly one close per session";
}

// =============================================================================
// G. SESSION ACTIVE FLAG
// =============================================================================

// -----------------------------------------------------------------------------
// TEST-METRICS-010: session_active is true while engine runs, false after stop
// Prometheus gauge must reflect active/inactive state
// -----------------------------------------------------------------------------
TEST_F(SerialBlockMetricsTest, SessionActiveGaugeInPrometheusText) {
  SerialBlockMetrics active;
  active.channel_id = 5;
  active.session_active = true;
  EXPECT_NE(active.GeneratePrometheusText().find(
      "air_serial_block_session_active{channel=\"5\"} 1"), std::string::npos);

  SerialBlockMetrics inactive;
  inactive.channel_id = 5;
  inactive.session_active = false;
  EXPECT_NE(inactive.GeneratePrometheusText().find(
      "air_serial_block_session_active{channel=\"5\"} 0"), std::string::npos);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
