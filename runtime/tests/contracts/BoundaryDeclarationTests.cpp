// Repository: Retrovue-playout
// Component: P11C-005 Boundary Declaration Contract Tests
// Purpose: Verify INV-BOUNDARY-DECLARED-001 — target_boundary_time_ms flows in SwitchToLive
// Contract: docs/contracts/tasks/phase11/P11C-005.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <chrono>

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

}  // namespace

// =============================================================================
// TEST_INV_BOUNDARY_DECLARED_001_TargetFlowsFromCoreToAir (P11C-005)
// =============================================================================
// Given: Control-surface-only engine (no media)
// When: SwitchToLive RPC is called with target_boundary_time_ms set
// Then: Request is accepted, response contains switch_completion_time_ms
// And: AIR logs receipt of target_boundary_time_ms (observable in logs)

TEST(BoundaryDeclarationTests, TargetFlowsFromCoreToAir) {
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);  // control_surface_only
  auto interface = std::make_shared<runtime::PlayoutInterface>(engine);
  retrovue::playout::PlayoutControlImpl service(interface);

  const int32_t channel_id = 1;
  const int64_t target_boundary_ms = 1738340400000;  // Example: 2026-02-01 00:00:00.000 UTC

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

  retrovue::playout::SwitchToLiveRequest switch_req;
  switch_req.set_channel_id(channel_id);
  switch_req.set_target_boundary_time_ms(target_boundary_ms);

  retrovue::playout::SwitchToLiveResponse switch_resp;
  grpc::ServerContext switch_ctx;
  grpc::Status switch_st = service.SwitchToLive(&switch_ctx, &switch_req, &switch_resp);

  ASSERT_TRUE(switch_st.ok()) << switch_st.error_message();
  EXPECT_TRUE(switch_resp.success()) << switch_resp.message();
  EXPECT_GT(switch_resp.switch_completion_time_ms(), 0)
      << "INV-BOUNDARY-DECLARED-001: Response must include switch_completion_time_ms (P11B-001)";
}
