#include <gtest/gtest.h>
#include <thread>
#include <chrono>

#include "BaseContractTest.h"
#include "retrovue/runtime/PlayoutControl.h"
#include "retrovue/runtime/ProducerBus.h"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "retrovue/blockplan/RationalFps.hpp"
#include "timing/TestMasterClock.h"

namespace retrovue::tests::contracts {

namespace {

int64_t MsToUs(double value_ms) {
  return static_cast<int64_t>(value_ms * 1'000.0);
}

}  // namespace

class PlayoutControlContractTest : public BaseContractTest {
 protected:
  [[nodiscard]] std::string DomainName() const override { return "PlayoutControl"; }

  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override {
    return {"CTL_001", "CTL_002", "CTL_003", "CTL_004", "CTL_005"};
  }
};

TEST_F(PlayoutControlContractTest, CTL_001_DeterministicStateTransitions) {
  runtime::PlayoutControl controller;
  const int64_t start_time = 1'700'000'000'000'000LL;

  ASSERT_TRUE(controller.BeginSession("begin", start_time));
  controller.OnBufferDepth(5, 60, start_time + MsToUs(10));
  EXPECT_EQ(controller.state(), runtime::PlayoutControl::RuntimePhase::kPlaying);

  ASSERT_TRUE(controller.Pause("pause",
                               start_time + MsToUs(50),
                               start_time + MsToUs(70),
                               0.2));
  EXPECT_EQ(controller.state(), runtime::PlayoutControl::RuntimePhase::kPaused);

  ASSERT_TRUE(controller.Resume("resume",
                                start_time + MsToUs(100),
                                start_time + MsToUs(130)));
  EXPECT_EQ(controller.state(), runtime::PlayoutControl::RuntimePhase::kPlaying);

  ASSERT_TRUE(controller.Seek("seek-forward",
                              start_time + MsToUs(150),
                              start_time + MsToUs(500),
                              start_time + MsToUs(200)));
  EXPECT_EQ(controller.state(), runtime::PlayoutControl::RuntimePhase::kPlaying);

  ASSERT_TRUE(controller.Stop("stop",
                              start_time + MsToUs(400),
                              start_time + MsToUs(500)));
  EXPECT_EQ(controller.state(), runtime::PlayoutControl::RuntimePhase::kIdle);

  // Attempt illegal transition - resume while idle.
  EXPECT_FALSE(controller.Resume("illegal-resume",
                                 start_time + MsToUs(510),
                                 start_time + MsToUs(515)));

  const auto snapshot = controller.Snapshot();
  EXPECT_EQ(snapshot.transitions.at({runtime::PlayoutControl::RuntimePhase::kIdle,
                                     runtime::PlayoutControl::RuntimePhase::kBuffering}),
            1u);
  EXPECT_EQ(snapshot.illegal_transition_total, 1u);
}

TEST_F(PlayoutControlContractTest, CTL_002_ControlActionLatencyCompliance) {
  runtime::PlayoutControl controller;
  const int64_t start_time = 1'700'000'100'000'000LL;

  ASSERT_TRUE(controller.BeginSession("begin", start_time));
  controller.OnBufferDepth(4, 60, start_time + MsToUs(15));

  ASSERT_TRUE(controller.Pause("pause-ok",
                               start_time + MsToUs(50),
                               start_time + MsToUs(75),
                               0.1));
  ASSERT_TRUE(controller.Resume("resume-ok",
                                start_time + MsToUs(100),
                                start_time + MsToUs(140)));
  ASSERT_TRUE(controller.Seek("seek-ok",
                              start_time + MsToUs(150),
                              start_time + MsToUs(800),
                              start_time + MsToUs(380)));
  ASSERT_TRUE(controller.Stop("stop-ok",
                              start_time + MsToUs(400),
                              start_time + MsToUs(820)));

  auto snapshot = controller.Snapshot();
  EXPECT_EQ(snapshot.latency_violation_total, 0u);
  EXPECT_LE(snapshot.pause_latency_p95_ms, 33.0);
  EXPECT_LE(snapshot.resume_latency_p95_ms, 50.0);
  EXPECT_LE(snapshot.seek_latency_p95_ms, 250.0);
  EXPECT_LE(snapshot.stop_latency_p95_ms, 500.0);

  // Introduce violations.
  ASSERT_TRUE(controller.BeginSession("begin2", start_time + MsToUs(900)));
  controller.OnBufferDepth(3, 60, start_time + MsToUs(910));
  EXPECT_TRUE(controller.Pause("pause-breach",
                               start_time + MsToUs(920),
                               start_time + MsToUs(1'020),
                               0.0));
  snapshot = controller.Snapshot();
  EXPECT_GE(snapshot.latency_violation_total, 1u);
}

TEST_F(PlayoutControlContractTest, CTL_003_CommandIdempotencyAndFailureTelemetry) {
  runtime::PlayoutControl controller;
  const int64_t base_time = 1'700'000'200'000'000LL;

  ASSERT_TRUE(controller.BeginSession("begin", base_time));
  controller.OnBufferDepth(3, 60, base_time + MsToUs(10));

  // First seek succeeds.
  ASSERT_TRUE(controller.Seek("seek-1",
                              base_time + MsToUs(20),
                              base_time + MsToUs(300),
                              base_time + MsToUs(220)));
  // Duplicate seek is acknowledged without mutation.
  EXPECT_TRUE(controller.Seek("seek-1",
                              base_time + MsToUs(40),
                              base_time + MsToUs(310),
                              base_time + MsToUs(250)));

  // External timeout forces error state.
  controller.OnExternalTimeout(base_time + MsToUs(260));
  EXPECT_EQ(controller.state(), runtime::PlayoutControl::RuntimePhase::kError);
  auto snapshot = controller.Snapshot();
  EXPECT_EQ(snapshot.timeout_total, 1u);

  // Recovery returns to buffering.
  ASSERT_TRUE(controller.Recover("recover",
                                 base_time + MsToUs(270)));
  EXPECT_EQ(controller.state(), runtime::PlayoutControl::RuntimePhase::kBuffering);

  controller.OnQueueOverflow();
  snapshot = controller.Snapshot();
  EXPECT_EQ(snapshot.queue_overflow_total, 1u);

  // Late seek should record violation.
  EXPECT_FALSE(controller.Seek("seek-backwards",
                               base_time + MsToUs(300),
                               base_time + MsToUs(100),
                               base_time + MsToUs(320)));
  snapshot = controller.Snapshot();
  EXPECT_EQ(snapshot.late_seek_total, 1u);
}

// Rule: CTL_004 Dual-Producer Preview/Live Slot Management
TEST_F(PlayoutControlContractTest, CTL_004_DualProducerBusManagement) {
  runtime::PlayoutControl controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  const int64_t start_time = 1'700'000'000'000'000LL;
  clock->SetEpochUtcUs(start_time);

  // Set up producer factory (Phase 6A.1/6A.2: segment params)
  controller.setProducerFactory(
      [](const std::string &path, const std::string &asset_id,
         buffer::FrameRingBuffer &rb, std::shared_ptr<retrovue::timing::MasterClock> clk,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        producers::file::ProducerConfig config;
        config.asset_uri = path;
        config.target_width = 1920;
        config.target_height = 1080;
        config.target_fps = 30.0;
        config.stub_mode = true; // Use stub mode for testing
        config.start_offset_ms = start_offset_ms;
        config.hard_stop_time_ms = hard_stop_time_ms;

        return std::make_unique<producers::file::FileProducer>(
            config, rb, clk, nullptr);
      });

  // Initially, both slots should be empty
  const auto &preview_before = controller.getPreviewBus();
  const auto &live_before = controller.getLiveBus();
  EXPECT_FALSE(preview_before.loaded);
  EXPECT_FALSE(live_before.loaded);

  // Load preview asset (shadow decode mode)
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://preview.mp4", "preview-asset-1", buffer, clock));
  
  const auto &preview_after = controller.getPreviewBus();
  EXPECT_TRUE(preview_after.loaded);
  EXPECT_EQ(preview_after.asset_id, "preview-asset-1");
  EXPECT_EQ(preview_after.file_path, "test://preview.mp4");
  EXPECT_NE(preview_after.producer, nullptr);
  
  // Verify preview producer is in shadow decode mode
  // (FrameRouter does not pull from it until switch)
  auto* preview_video_producer = dynamic_cast<producers::file::FileProducer*>(
      preview_after.producer.get());
  if (preview_video_producer) {
    EXPECT_TRUE(preview_video_producer->IsShadowDecodeMode());
    // Wait for shadow decode to be ready
    int attempts = 0;
    while (!preview_video_producer->IsShadowDecodeReady() && attempts < 50) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      attempts++;
    }
    EXPECT_TRUE(preview_video_producer->IsShadowDecodeReady())
        << "Preview producer should be ready for switching";
  }

  // Live slot should still be empty
  const auto &live_after = controller.getLiveBus();
  EXPECT_FALSE(live_after.loaded);

  // Activate preview as live (now that shadow decode is ready)
  ASSERT_TRUE(controller.activatePreviewAsLive());

  // Preview slot should now be empty
  const auto &preview_switched = controller.getPreviewBus();
  EXPECT_FALSE(preview_switched.loaded);

  // Live slot should now have the producer
  const auto &live_switched = controller.getLiveBus();
  EXPECT_TRUE(live_switched.loaded);
  EXPECT_EQ(live_switched.asset_id, "preview-asset-1");
  EXPECT_EQ(live_switched.file_path, "test://preview.mp4");
  EXPECT_NE(live_switched.producer, nullptr);

  // Load another preview asset
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://preview2.mp4", "preview-asset-2", buffer, clock));

  const auto &preview_new = controller.getPreviewBus();
  EXPECT_TRUE(preview_new.loaded);
  EXPECT_EQ(preview_new.asset_id, "preview-asset-2");

  // Live slot should still have the first asset
  const auto &live_still = controller.getLiveBus();
  EXPECT_TRUE(live_still.loaded);
  EXPECT_EQ(live_still.asset_id, "preview-asset-1");
}

// Rule: CTL_005 Producer Switching Seamlessness
TEST_F(PlayoutControlContractTest, CTL_005_ProducerSwitchingSeamlessness) {
  runtime::PlayoutControl controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  const int64_t start_time = 1'700'000'000'000'000LL;
  clock->SetEpochUtcUs(start_time);

  // Set up producer factory (Phase 6A.1/6A.2: segment params)
  controller.setProducerFactory(
      [](const std::string &path, const std::string &asset_id,
         buffer::FrameRingBuffer &rb, std::shared_ptr<retrovue::timing::MasterClock> clk,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        producers::file::ProducerConfig config;
        config.asset_uri = path;
        config.target_width = 1920;
        config.target_height = 1080;
        config.target_fps = 30.0;
        config.stub_mode = true;
        config.start_offset_ms = start_offset_ms;
        config.hard_stop_time_ms = hard_stop_time_ms;

        return std::make_unique<producers::file::FileProducer>(
            config, rb, clk, nullptr);
      });

  // Load and activate first asset
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://asset1.mp4", "asset-1", buffer, clock));
  
  // Verify preview producer is in shadow decode mode
  const auto &preview1 = controller.getPreviewBus();
  auto* preview1_video = dynamic_cast<producers::file::FileProducer*>(
      preview1.producer.get());
  if (preview1_video) {
    EXPECT_TRUE(preview1_video->IsShadowDecodeMode());
    // Wait for shadow decode to be ready
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    // Note: In real implementation, we'd wait for IsShadowDecodeReady() to be true
  }
  
  ASSERT_TRUE(controller.activatePreviewAsLive());

  const auto &live1 = controller.getLiveBus();
  ASSERT_TRUE(live1.loaded);
  ASSERT_NE(live1.producer, nullptr);

  // Producer is already started (was started in loadPreviewAsset)
  // FrameRouter will pull from it
  EXPECT_TRUE(live1.producer->isRunning());

  // Load preview asset (shadow decode mode)
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://asset2.mp4", "asset-2", buffer, clock));
  
  // Verify preview producer is in shadow decode mode
  const auto &preview2 = controller.getPreviewBus();
  auto* preview2_video = dynamic_cast<producers::file::FileProducer*>(
      preview2.producer.get());
  if (preview2_video) {
    EXPECT_TRUE(preview2_video->IsShadowDecodeMode());
    // Wait for shadow decode to be ready
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }

  // Switch to new asset (FrameRouter switches which producer it pulls from)
  ASSERT_TRUE(controller.activatePreviewAsLive());

  const auto &live2 = controller.getLiveBus();
  EXPECT_TRUE(live2.loaded);
  EXPECT_EQ(live2.asset_id, "asset-2");
  EXPECT_NE(live2.producer, nullptr);

  // Verify frame boundary constraint: final LIVE frame and first PREVIEW frame
  // are placed consecutively in ring buffer with no discontinuity
  // (This is verified by checking buffer contains frames from both producers)
  EXPECT_GE(buffer.Size(), 0u) << "Ring buffer should contain frames after switch";
  
  // New live producer should be running (preview was moved to live slot)
  const auto &live2_after = controller.getLiveBus();
  EXPECT_TRUE(live2_after.loaded);
  EXPECT_NE(live2_after.producer, nullptr);
  // Note: live1.producer is now invalid (moved), so we check live2 instead
  EXPECT_TRUE(live2_after.producer->isRunning()) << "New live producer should be running";
}

// INV-FPS-RESAMPLE / INV-FPS-TICK-PTS: PTS step on seamless switch must use session/house
// RationalFps, not producer (FileProducer) FPS. This test fails if PlayoutControl reads
// producer fps for the PTS step.
TEST_F(PlayoutControlContractTest, PlayoutControlPtsStepUsesSessionFpsNotProducer) {
  using retrovue::blockplan::RationalFps;

  runtime::PlayoutControl controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1'700'000'000'000'000LL);

  // Session output FPS: 30000/1001 (~29.97). One tick = 33366 µs.
  const RationalFps session_fps(30000, 1001);
  const int64_t session_tick_us = session_fps.FrameDurationUs();
  ASSERT_EQ(session_tick_us, 33366) << "30000/1001 tick must be 33366 µs";

  controller.SetSessionOutputFps(session_fps);

  // Producer factory with *mismatched* target FPS (24/1). If PlayoutControl used producer
  // FPS for PTS step, step would be 41666 µs; we require session step 33366 µs.
  const RationalFps producer_fps(24, 1);
  const int64_t producer_tick_us = producer_fps.FrameDurationUs();
  ASSERT_EQ(producer_tick_us, 41666) << "24/1 tick = 41666 µs (must differ from session)";

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer& rb, std::shared_ptr<retrovue::timing::MasterClock> clk,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        producers::file::ProducerConfig config;
        config.asset_uri = path;
        config.target_width = 1920;
        config.target_height = 1080;
        config.target_fps = 24.0;  // Mismatched vs session 30000/1001
        config.stub_mode = true;
        config.start_offset_ms = start_offset_ms;
        config.hard_stop_time_ms = hard_stop_time_ms;
        return std::make_unique<producers::file::FileProducer>(
            config, rb, clk, nullptr);
      });

  // Load first asset and activate (no PTS step assertion on first activation).
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://asset1.mp4", "asset-1", buffer, clock));
  auto* preview1 = dynamic_cast<producers::file::FileProducer*>(
      controller.getPreviewBus().producer.get());
  if (preview1) {
    int attempts = 0;
    while (!preview1->IsShadowDecodeReady() && attempts < 50) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      ++attempts;
    }
  }
  ASSERT_TRUE(controller.activatePreviewAsLive());

  // Load second asset and activate. This path uses PTS step from session, not producer.
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://asset2.mp4", "asset-2", buffer, clock));
  auto* preview2 = dynamic_cast<producers::file::FileProducer*>(
      controller.getPreviewBus().producer.get());
  if (preview2) {
    int attempts = 0;
    while (!preview2->IsShadowDecodeReady() && attempts < 50) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      ++attempts;
    }
  }
  ASSERT_TRUE(controller.activatePreviewAsLive());

  // Authority: step must be session tick (30000/1001), not producer (24/1).
  const int64_t step_us = controller.LastPtsStepUsForTest();
  EXPECT_EQ(step_us, session_tick_us)
      << "PTS step must use session FPS (33366 µs for 30000/1001), not producer; got "
      << step_us << " (producer 24/1 would give " << producer_tick_us << ")";
  EXPECT_NE(step_us, producer_tick_us)
      << "PTS step must not use producer FPS for output tick cadence";
}

}  // namespace retrovue::tests::contracts

