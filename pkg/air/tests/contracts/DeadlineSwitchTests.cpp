// Repository: Retrovue-playout
// Component: P11D-007 Deadline Switch Contract Tests
// Purpose: Verify INV-BOUNDARY-TOLERANCE-001 — switch executes within 1 frame of declared boundary
// Contract: docs/contracts/tasks/phase11/P11D-007.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <chrono>
#include <fstream>
#include <thread>

#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/runtime/PlayoutEngine.h"
#include "retrovue/runtime/PlayoutInterface.h"
#include "playout.pb.h"
#include "playout.grpc.pb.h"
#include "playout_service.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;

namespace {

constexpr const char* kDefaultProgramFormatJson =
    R"({"video":{"width":1920,"height":1080,"frame_rate":"30/1"},"audio":{"sample_rate":48000,"channels":2}})";

static const char* GetTestAssetPath() {
  return "/opt/retrovue/assets/SampleA.mp4";
}

constexpr int64_t kFrameDurationMs = 33;  // ~30fps
constexpr int64_t kTargetBoundaryMs = 5000;  // 5s in future (clock starts at 0)

}  // namespace

// =============================================================================
// TEST_INV_BOUNDARY_TOLERANCE_001_SwitchWithinOneFrame (P11D-007)
// =============================================================================
// Given: Engine with TestMasterClock at 0, StartChannel + LoadPreview done
// When: SwitchToLive issued with target_boundary_time_ms=5000, then clock advanced 5s
// Then: Switch completes; actual switch_completion_time_ms within [5000-33, 5000+33]

TEST(DeadlineSwitchTests, SwitchWithinOneFrame) {
  const char* asset_path = GetTestAssetPath();
  std::ifstream f(asset_path);
  if (!f.good()) {
    GTEST_SKIP() << "Test asset not found: " << asset_path
                 << " (create /opt/retrovue/assets/SampleA.mp4 for deadline switch test)";
  }
  f.close();

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<timing::TestMasterClock>(0, timing::TestMasterClock::Mode::Deterministic);
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, false);
  auto interface = std::make_shared<runtime::PlayoutInterface>(engine);
  retrovue::playout::PlayoutControlImpl service(interface);

  const int32_t channel_id = 1;
  grpc::ServerContext start_ctx, load_ctx;

  retrovue::playout::StartChannelRequest start_req;
  start_req.set_channel_id(channel_id);
  start_req.set_plan_handle(asset_path);
  start_req.set_port(50051);
  start_req.set_program_format_json(kDefaultProgramFormatJson);
  retrovue::playout::StartChannelResponse start_resp;
  ASSERT_TRUE(service.StartChannel(&start_ctx, &start_req, &start_resp).ok());
  ASSERT_TRUE(start_resp.success());

  retrovue::playout::LoadPreviewRequest load_req;
  load_req.set_channel_id(channel_id);
  load_req.set_asset_path(asset_path);
  load_req.set_start_frame(0);
  load_req.set_frame_count(-1);
  load_req.set_fps_numerator(30);
  load_req.set_fps_denominator(1);
  retrovue::playout::LoadPreviewResponse load_resp;
  ASSERT_TRUE(service.LoadPreview(&load_ctx, &load_req, &load_resp).ok());
  ASSERT_TRUE(load_resp.success());

  retrovue::playout::SwitchToLiveRequest switch_req;
  switch_req.set_channel_id(channel_id);
  switch_req.set_target_boundary_time_ms(kTargetBoundaryMs);

  retrovue::playout::SwitchToLiveResponse switch_resp;
  grpc::Status switch_status;
  std::thread switch_thread([&]() {
    grpc::ServerContext switch_ctx;
    switch_status = service.SwitchToLive(&switch_ctx, &switch_req, &switch_resp);
  });

  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  clock->AdvanceMicroseconds(kTargetBoundaryMs * 1000);
  switch_thread.join();

  ASSERT_TRUE(switch_status.ok()) << switch_status.error_message();
  ASSERT_TRUE(switch_resp.success()) << switch_resp.message();

  int64_t actual_ms = switch_resp.switch_completion_time_ms();
  int64_t delta_ms = std::abs(actual_ms - kTargetBoundaryMs);
  EXPECT_LE(delta_ms, kFrameDurationMs)
      << "INV-BOUNDARY-TOLERANCE-001 VIOLATION: Switch completed at " << actual_ms
      << " but boundary was " << kTargetBoundaryMs
      << " (delta: " << delta_ms << "ms, max allowed: " << kFrameDurationMs << "ms)";
}

// =============================================================================
// SwitchAtDeadlineEvenIfNotReady (P11D-007) — control_surface path
// =============================================================================
// With control_surface_only, SwitchToLive with target returns immediately;
// switch_completion_time_ms is set. Verifies the RPC accepts target and returns success.

TEST(DeadlineSwitchTests, SwitchAtDeadlineControlSurfaceAcceptsTarget) {
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);
  auto interface = std::make_shared<runtime::PlayoutInterface>(engine);
  retrovue::playout::PlayoutControlImpl service(interface, true);

  const int32_t channel_id = 1;
  grpc::ServerContext start_ctx, load_ctx, switch_ctx;

  retrovue::playout::StartChannelRequest start_req;
  start_req.set_channel_id(channel_id);
  start_req.set_plan_handle("plan-1");
  start_req.set_port(50051);
  start_req.set_program_format_json(kDefaultProgramFormatJson);
  retrovue::playout::StartChannelResponse start_resp;
  ASSERT_TRUE(service.StartChannel(&start_ctx, &start_req, &start_resp).ok());
  ASSERT_TRUE(start_resp.success());

  retrovue::playout::LoadPreviewRequest load_req;
  load_req.set_channel_id(channel_id);
  load_req.set_asset_path("/fake/asset.mp4");
  load_req.set_start_frame(0);
  load_req.set_frame_count(-1);
  load_req.set_fps_numerator(30);
  load_req.set_fps_denominator(1);
  retrovue::playout::LoadPreviewResponse load_resp;
  ASSERT_TRUE(service.LoadPreview(&load_ctx, &load_req, &load_resp).ok());
  ASSERT_TRUE(load_resp.success());

  const int64_t target_ms = 1738340400000;
  retrovue::playout::SwitchToLiveRequest switch_req;
  switch_req.set_channel_id(channel_id);
  switch_req.set_target_boundary_time_ms(target_ms);
  retrovue::playout::SwitchToLiveResponse switch_resp;
  grpc::Status st = service.SwitchToLive(&switch_ctx, &switch_req, &switch_resp);

  ASSERT_TRUE(st.ok()) << st.error_message();
  EXPECT_TRUE(switch_resp.success()) << switch_resp.message();
  EXPECT_GT(switch_resp.switch_completion_time_ms(), 0)
      << "Response must include switch_completion_time_ms";
}
