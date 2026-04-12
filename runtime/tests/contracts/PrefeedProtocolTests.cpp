// Repository: Retrovue-playout
// Component: P11D-008 Prefeed Protocol Contract Tests
// Purpose: Verify INV-CONTROL-NO-POLL-001 — late prefeed returns PROTOCOL_VIOLATION
// Contract: docs/contracts/tasks/phase11/P11D-008.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <chrono>
#include <fstream>

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

// P11D-004: Minimum lead time (ms) — must match PlayoutEngine.cpp kMinPrefeedLeadTimeMs
constexpr int64_t kMinPrefeedLeadTimeMs = 5000;

}  // namespace

// =============================================================================
// TEST_INV_CONTROL_NO_POLL_001_LatePrefeedReturnsProtocolViolation (P11D-008)
// =============================================================================
// Given: Engine with MasterClock at 0, StartChannel + LoadPreview done (needs real asset)
// When: SwitchToLive with target_boundary_time_ms = 500 (lead 500ms < 5000ms)
// Then: Response status is PROTOCOL_VIOLATION, violation_reason non-empty
// Note: Requires a test asset at /opt/retrovue/assets/SampleA.mp4 (same as Phase9/10 tests).

static const char* GetTestAssetPath() {
  return "/opt/retrovue/assets/SampleA.mp4";
}

TEST(PrefeedProtocolTests, LatePrefeedReturnsProtocolViolation) {
  const char* asset_path = GetTestAssetPath();
  std::ifstream f(asset_path);
  if (!f.good()) {
    GTEST_SKIP() << "Test asset not found: " << asset_path
                 << " (create /opt/retrovue/assets/SampleA.mp4 to run full PROTOCOL_VIOLATION test)";
  }
  f.close();

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<timing::TestMasterClock>(0, timing::TestMasterClock::Mode::Deterministic);
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, false);  // full engine for lead-time check
  auto interface = std::make_shared<runtime::PlayoutInterface>(engine);
  retrovue::playout::PlayoutControlImpl service(interface);

  const int32_t channel_id = 1;
  grpc::ServerContext ctx;

  retrovue::playout::StartChannelRequest start_req;
  start_req.set_channel_id(channel_id);
  start_req.set_plan_handle(asset_path);  // full engine uses plan_handle as asset URI for live
  start_req.set_port(50051);
  start_req.set_program_format_json(kDefaultProgramFormatJson);
  retrovue::playout::StartChannelResponse start_resp;
  ASSERT_TRUE(service.StartChannel(&ctx, &start_req, &start_resp).ok()) << "StartChannel failed (need valid asset)";
  ASSERT_TRUE(start_resp.success());

  retrovue::playout::LoadPreviewRequest load_req;
  load_req.set_channel_id(channel_id);
  load_req.set_asset_path(asset_path);
  load_req.set_start_frame(0);
  load_req.set_frame_count(-1);
  load_req.set_fps_numerator(30);
  load_req.set_fps_denominator(1);
  retrovue::playout::LoadPreviewResponse load_resp;
  grpc::ServerContext load_ctx;
  ASSERT_TRUE(service.LoadPreview(&load_ctx, &load_req, &load_resp).ok());
  ASSERT_TRUE(load_resp.success());

  // Target 500ms in future; clock is at 0 so lead = 500ms < kMinPrefeedLeadTimeMs
  const int64_t target_boundary_ms = 500;
  retrovue::playout::SwitchToLiveRequest switch_req;
  switch_req.set_channel_id(channel_id);
  switch_req.set_target_boundary_time_ms(target_boundary_ms);

  retrovue::playout::SwitchToLiveResponse switch_resp;
  grpc::ServerContext switch_ctx;
  grpc::Status st = service.SwitchToLive(&switch_ctx, &switch_req, &switch_resp);

  ASSERT_TRUE(st.ok()) << st.error_message();
  EXPECT_FALSE(switch_resp.success())
      << "INV-CONTROL-NO-POLL-001: Late prefeed must return success=false (PROTOCOL_VIOLATION)";
  EXPECT_EQ(switch_resp.result_code(), retrovue::playout::RESULT_CODE_PROTOCOL_VIOLATION)
      << "INV-CONTROL-NO-POLL-001: Late prefeed must return PROTOCOL_VIOLATION, not NOT_READY";
  EXPECT_FALSE(switch_resp.violation_reason().empty())
      << "PROTOCOL_VIOLATION must include violation_reason";
}

// =============================================================================
// SufficientLeadTimeAccepted (P11D-008)
// =============================================================================
// Given: control_surface_only engine (no wait), target in future with sufficient lead
// When: SwitchToLive with target_boundary_time_ms = now + kMinPrefeedLeadTimeMs + 1000
// Then: Accepted (control_surface path returns immediately; lead check not applied there)
// Note: With control_surface_only the deadline path is not taken; this test verifies
// that when target is provided and lead would be sufficient, the RPC succeeds in control-surface mode.

TEST(PrefeedProtocolTests, SufficientLeadTimeControlSurfaceSucceeds) {
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);  // control_surface_only
  auto interface = std::make_shared<runtime::PlayoutInterface>(engine);
  retrovue::playout::PlayoutControlImpl service(interface, true);  // control_surface_only for service too

  const int32_t channel_id = 1;
  retrovue::playout::StartChannelRequest start_req;
  start_req.set_channel_id(channel_id);
  start_req.set_plan_handle("plan-1");
  start_req.set_port(50051);
  start_req.set_program_format_json(kDefaultProgramFormatJson);
  retrovue::playout::StartChannelResponse start_resp;
  grpc::ServerContext start_ctx;
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
  grpc::ServerContext load_ctx;
  ASSERT_TRUE(service.LoadPreview(&load_ctx, &load_req, &load_resp).ok());
  ASSERT_TRUE(load_resp.success());

  const int64_t target_ms = 1738340400000;  // Far future; in control_surface path no lead check
  retrovue::playout::SwitchToLiveRequest switch_req;
  switch_req.set_channel_id(channel_id);
  switch_req.set_target_boundary_time_ms(target_ms);
  retrovue::playout::SwitchToLiveResponse switch_resp;
  grpc::ServerContext switch_ctx;
  grpc::Status st = service.SwitchToLive(&switch_ctx, &switch_req, &switch_resp);

  ASSERT_TRUE(st.ok()) << st.error_message();
  EXPECT_TRUE(switch_resp.success()) << switch_resp.message();
  // control_surface path may leave result_code UNSPECIFIED (0) or set OK (1)
  EXPECT_TRUE(switch_resp.result_code() == retrovue::playout::RESULT_CODE_OK ||
              switch_resp.result_code() == retrovue::playout::RESULT_CODE_UNSPECIFIED)
      << "result_code=" << switch_resp.result_code();
}
