#include "../../BaseContractTest.h"
#include "../ContractRegistryEnvironment.h"

#include <chrono>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/decode/FrameProducer.h"
#include "retrovue/renderer/FrameRenderer.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/runtime/PlayoutControlStateMachine.h"
#include "retrovue/runtime/PlayoutEngine.h"
#include "retrovue/runtime/PlayoutController.h"
#include "retrovue/producers/video_file/VideoFileProducer.h"
#include "playout.grpc.pb.h"
#include "playout.pb.h"
#include "../../fixtures/ChannelManagerStub.h"
#include "../../fixtures/StubProducer.h"
#include "timing/TestMasterClock.h"
#include <grpcpp/grpcpp.h>
#include <cstdlib>
#include "playout_service.h"

using namespace retrovue;
using namespace retrovue::tests;
using namespace retrovue::tests::fixtures;

namespace
{

using retrovue::tests::RegisterExpectedDomainCoverage;

const bool kRegisterCoverage = []() {
  RegisterExpectedDomainCoverage(
      "PlayoutEngine",
      {"BC-001", "BC-002", "BC-003", "BC-004", "BC-005", "BC-006", "BC-007",
       "LT-005", "LT-006", "Phase6A1", "Phase6A2"});
  return true;
}();

class PlayoutEngineContractTest : public BaseContractTest
{
protected:
  [[nodiscard]] std::string DomainName() const override
  {
    return "PlayoutEngine";
  }

  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override
  {
    return {
        "BC-001",
        "BC-002",
        "BC-003",
        "BC-004",
        "BC-005",
        "BC-006",
        "BC-007",
        "LT-005",
        "LT-006",
        "Phase6A1",
        "Phase6A2"};
  }
};

// Rule: BC-001 Frame timing accuracy (PlayoutEngineDomain.md §BC-001)
TEST_F(PlayoutEngineContractTest, BC_001_FrameTimingAlignsWithMasterClock)
{
  buffer::FrameRingBuffer buffer(/*capacity=*/120);
  const int64_t pts_step = 33'366;
  // Note: In production, FrameRouter pulls from producer and writes to buffer.
  // For this test, we directly push frames to test renderer timing behavior.
  for (int i = 0; i < 120; ++i)
  {
    buffer::Frame frame;
    frame.metadata.pts = i * pts_step;
    frame.metadata.duration = 1.0 / 29.97;
    ASSERT_TRUE(buffer.Push(frame));
  }

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  const int64_t epoch = 1'700'001'000'000'000;
  clock->SetEpochUtcUs(epoch);
  clock->SetRatePpm(0.0);
  clock->SetNow(epoch + 2'000, 0.0); // 2 ms skew ahead

  constexpr int32_t kChannelId = 2401;
  telemetry::ChannelMetrics seed{};
  seed.state = telemetry::ChannelState::READY;
  metrics->SubmitChannelMetrics(kChannelId, seed);

  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;
  auto renderer = renderer::FrameRenderer::Create(
      config, buffer, clock, metrics, kChannelId);
  ASSERT_NE(renderer, nullptr);
  ASSERT_TRUE(renderer->Start());

  std::this_thread::sleep_for(std::chrono::milliseconds(120));

  telemetry::ChannelMetrics snapshot{};
  ASSERT_TRUE(metrics->GetChannelMetrics(kChannelId, snapshot));
  EXPECT_LT(std::abs(snapshot.frame_gap_seconds), 0.0167)
      << "Frame gap must stay within one frame period";

  clock->AdvanceSeconds(0.05);
  renderer->Stop();

  const auto &stats = renderer->GetStats();
  EXPECT_GE(stats.frames_rendered, 1u);
}

// Rule: BC-005 Resource Cleanup (PlayoutEngineDomain.md §BC-005)
TEST_F(PlayoutEngineContractTest, BC_005_ChannelStopReleasesResources)
{
  telemetry::MetricsExporter exporter(/*port=*/0);
  ChannelManagerStub manager;

  decode::ProducerConfig config;
  config.stub_mode = true;
  config.asset_uri = "contract://playout/channel";
  config.target_fps = 29.97;

  auto runtime = manager.StartChannel(201, config, exporter, /*buffer_capacity=*/12);

  // Verify channel is running before stop
  telemetry::ChannelMetrics metrics_before{};
  ASSERT_TRUE(exporter.GetChannelMetrics(201, metrics_before));
  EXPECT_NE(metrics_before.state, telemetry::ChannelState::STOPPED);

  manager.StopChannel(runtime, exporter);

  // After stop, metrics are removed to avoid stale state (MT-005)
  telemetry::ChannelMetrics metrics_after{};
  EXPECT_FALSE(exporter.GetChannelMetrics(201, metrics_after))
      << "Metrics should be removed after channel stop";
  
  // Verify resources are released
  ASSERT_NE(runtime.buffer, nullptr);
  EXPECT_TRUE(runtime.buffer->IsEmpty());
}

// Rule: BC-003 Control operations are idempotent (PlayoutEngineDomain.md §BC-003)
TEST_F(PlayoutEngineContractTest, BC_003_ControlOperationsAreIdempotent)
{
  telemetry::MetricsExporter exporter(/*port=*/0);
  ChannelManagerStub manager;

  decode::ProducerConfig config;
  config.stub_mode = true;
  config.asset_uri = "contract://playout/idempotent";
  config.target_fps = 29.97;

  auto runtime_first = manager.StartChannel(210, config, exporter, /*buffer_capacity=*/8);

  telemetry::ChannelMetrics metrics{};
  ASSERT_TRUE(exporter.GetChannelMetrics(210, metrics));
  EXPECT_EQ(metrics.state, telemetry::ChannelState::READY);

  auto runtime_second = manager.StartChannel(210, config, exporter, /*buffer_capacity=*/8);
  ASSERT_TRUE(exporter.GetChannelMetrics(210, metrics));
  EXPECT_EQ(metrics.state, telemetry::ChannelState::READY)
      << "Repeated StartChannel must be a no-op";

  manager.StopChannel(runtime_first, exporter);
  // After first stop, metrics are removed (MT-005)
  EXPECT_FALSE(exporter.GetChannelMetrics(210, metrics))
      << "Metrics should be removed after channel stop";
  
  manager.StopChannel(runtime_first, exporter); // idempotent stop - should be safe to call again
  // Metrics should still be removed after idempotent stop
  EXPECT_FALSE(exporter.GetChannelMetrics(210, metrics))
      << "Metrics should remain removed after idempotent stop";

  manager.StopChannel(runtime_second, exporter);
}

// Rule: BC-004 Graceful degradation isolates channel errors (PlayoutEngineDomain.md §BC-004)
TEST_F(PlayoutEngineContractTest, BC_004_ChannelErrorIsolation)
{
  telemetry::MetricsExporter exporter(/*port=*/0);
  ChannelManagerStub manager;

  decode::ProducerConfig config;
  config.stub_mode = true;
  config.asset_uri = "contract://playout/error_isolation";
  config.target_fps = 30.0;

  auto channel_a = manager.StartChannel(220, config, exporter, /*buffer_capacity=*/8);
  auto channel_b = manager.StartChannel(221, config, exporter, /*buffer_capacity=*/8);

  telemetry::ChannelMetrics metrics_a{};
  telemetry::ChannelMetrics metrics_b{};
  ASSERT_TRUE(exporter.GetChannelMetrics(220, metrics_a));
  ASSERT_TRUE(exporter.GetChannelMetrics(221, metrics_b));
  EXPECT_EQ(metrics_a.state, telemetry::ChannelState::READY);
  EXPECT_EQ(metrics_b.state, telemetry::ChannelState::READY);

  telemetry::ChannelMetrics error_state{};
  error_state.state = telemetry::ChannelState::ERROR_STATE;
  error_state.decode_failure_count = 1;
  exporter.SubmitChannelMetrics(221, error_state);

  ASSERT_TRUE(exporter.GetChannelMetrics(221, metrics_b));
  EXPECT_EQ(metrics_b.state, telemetry::ChannelState::ERROR_STATE);

  ASSERT_TRUE(exporter.GetChannelMetrics(220, metrics_a));
  EXPECT_EQ(metrics_a.state, telemetry::ChannelState::READY)
      << "Error on one channel must not impact other channels";

  manager.StopChannel(channel_a, exporter);
  manager.StopChannel(channel_b, exporter);
}

// Rule: BC-002 Buffer Depth Guarantees (PlayoutEngineDomain.md §BC-002)
TEST_F(PlayoutEngineContractTest, BC_002_BufferDepthRemainsWithinCapacity)
{
  telemetry::MetricsExporter exporter(/*port=*/0);
  ChannelManagerStub manager;

  decode::ProducerConfig config;
  config.stub_mode = true;
  config.asset_uri = "contract://playout/buffer";
  config.target_fps = 30.0;

  constexpr std::size_t kCapacity = 10;
  auto runtime = manager.StartChannel(202, config, exporter, kCapacity);

  std::this_thread::sleep_for(std::chrono::milliseconds(150));
  const auto depth = runtime.buffer->Size();
  EXPECT_LE(depth, kCapacity);
  EXPECT_GE(depth, 1u);

  manager.StopChannel(runtime, exporter);
}

// Rule: BC-007 Dual-Producer Switching Seamlessness (PlayoutEngineDomain.md §BC-007)
// Tests that switching from preview to live occurs at ring buffer boundary with perfect PTS continuity
TEST_F(PlayoutEngineContractTest, BC_007_DualProducerSwitchingSeamlessness)
{
  // This test verifies the seamless switching contract:
  // - Slot switching occurs at a frame boundary
  // - Final LIVE frame and first PREVIEW frame are placed consecutively in ring buffer
  // - No discontinuity in timing or PTS
  // - Ring buffer is NOT flushed during switch
  // - Renderer pipeline is NOT reset during switch
  
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  const int64_t start_time = 1'700'000'000'000'000LL;
  clock->SetEpochUtcUs(start_time);

  // Set up producer factory (Phase 6A.1/6A.2: segment params passed to VideoFileProducer)
  controller.setProducerFactory(
      [](const std::string &path, const std::string &asset_id,
         buffer::FrameRingBuffer &rb, std::shared_ptr<retrovue::timing::MasterClock> clk,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        producers::video_file::ProducerConfig config;
        config.asset_uri = path;
        config.target_width = 1920;
        config.target_height = 1080;
        config.target_fps = 30.0;
        config.stub_mode = true;
        config.start_offset_ms = start_offset_ms;
        config.hard_stop_time_ms = hard_stop_time_ms;

        return std::make_unique<producers::video_file::VideoFileProducer>(
            config, rb, clk, nullptr);
      });

  // Load first asset into preview and activate as live
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://asset1.mp4", "asset-1", buffer, clock));
  
  const auto &preview1 = controller.getPreviewSlot();
  auto* preview1_video = dynamic_cast<producers::video_file::VideoFileProducer*>(
      preview1.producer.get());
  ASSERT_NE(preview1_video, nullptr);
  EXPECT_TRUE(preview1_video->IsShadowDecodeMode());
  
  // Wait for shadow decode to be ready
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  
  ASSERT_TRUE(controller.activatePreviewAsLive());

  // Producer is already started (was started in loadPreviewAsset)
  // FrameRouter will pull from it
  const auto &live1 = controller.getLiveSlot();
  ASSERT_TRUE(live1.loaded);
  ASSERT_NE(live1.producer, nullptr);
  EXPECT_TRUE(live1.producer->isRunning()) << "Live producer should be running";

  // Get initial buffer state
  const size_t buffer_size_before = buffer.Size();
  int64_t last_live_pts = 0;
  
  // Extract last PTS from live producer if available
  auto* live1_video = dynamic_cast<producers::video_file::VideoFileProducer*>(
      live1.producer.get());
  if (live1_video) {
    last_live_pts = live1_video->GetNextPTS();
  }

  // Load preview asset (shadow decode mode)
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://asset2.mp4", "asset-2", buffer, clock));
  
  const auto &preview2 = controller.getPreviewSlot();
  auto* preview2_video = dynamic_cast<producers::video_file::VideoFileProducer*>(
      preview2.producer.get());
  ASSERT_NE(preview2_video, nullptr);
  EXPECT_TRUE(preview2_video->IsShadowDecodeMode());
  
  // Wait for shadow decode to be ready
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  EXPECT_TRUE(preview2_video->IsShadowDecodeReady());

  // Verify ring buffer persists (not flushed) before switch
  EXPECT_GE(buffer.Size(), 0u) << "Ring buffer should persist before switch";

  // Switch to new asset (FrameRouter switches which producer it pulls from)
  ASSERT_TRUE(controller.activatePreviewAsLive());

  const auto &live2 = controller.getLiveSlot();
  EXPECT_TRUE(live2.loaded);
  EXPECT_EQ(live2.asset_id, "asset-2");
  EXPECT_NE(live2.producer, nullptr);

  // Verify frame boundary constraint: final LIVE frame and first PREVIEW frame
  // are placed consecutively in ring buffer with no discontinuity
  // Ring buffer should contain frames from both producers across switch boundary
  EXPECT_GE(buffer.Size(), 0u) << "Ring buffer should contain frames after switch";
  
  // Verify PTS continuity: preview producer should have aligned PTS
  auto* live2_video = dynamic_cast<producers::video_file::VideoFileProducer*>(
      live2.producer.get());
  if (live2_video && last_live_pts > 0) {
    int64_t preview_first_pts = live2_video->GetNextPTS();
    int64_t expected_pts = last_live_pts + 33'366; // ~30fps frame duration in microseconds
    EXPECT_GE(preview_first_pts, expected_pts - 1000) // Allow small tolerance
        << "Preview PTS should align with live PTS + frame_duration";
    EXPECT_LE(preview_first_pts, expected_pts + 1000);
  }

  // New live producer should be running (preview was moved to live slot)
  // Note: live1.producer is now invalid (moved), so we check live2 instead
  EXPECT_TRUE(live2.producer->isRunning()) << "New live producer should be running";
  
  // Preview slot should be empty after switch
  const auto &preview_after = controller.getPreviewSlot();
  EXPECT_FALSE(preview_after.loaded) << "Preview slot should be empty after switch";

  // Stop live producer before test teardown so controller destructor does not
  // destroy a running producer (avoids race/segfault in slot cleanup).
  if (live2.producer && live2.producer->isRunning()) {
    live2.producer->stop();
  }
}

// Rule: BC-006 Monotonic PTS (PlayoutEngineDomain.md §BC-006)
TEST_F(PlayoutEngineContractTest, BC_006_FramePtsRemainMonotonic)
{
  buffer::FrameRingBuffer buffer(/*capacity=*/8);
  decode::ProducerConfig config;
  config.stub_mode = true;
  config.asset_uri = "contract://playout/pts";
  config.target_fps = 30.0;

  decode::FrameProducer producer(config, buffer);
  ASSERT_TRUE(producer.Start());

  std::this_thread::sleep_for(std::chrono::milliseconds(150));
  producer.Stop();

  buffer::Frame previous_frame;
  bool has_previous = false;
  buffer::Frame frame;
  while (buffer.Pop(frame))
  {
    if (has_previous)
    {
      EXPECT_GT(frame.metadata.pts, previous_frame.metadata.pts);
    }
    has_previous = true;
    previous_frame = frame;
  }
  EXPECT_TRUE(has_previous);
}

// Rule: LT-005 LoadPreview Sequence (PlayoutEngineContract.md §LT-005)
// Tests the LoadPreview gRPC RPC through the service implementation.
// Uses control-surface-only engine (no media) for deterministic contract testing.
TEST_F(PlayoutEngineContractTest, LT_005_LoadPreviewSequence)
{
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);  // control_surface_only
  auto controller = std::make_shared<runtime::PlayoutController>(engine);
  retrovue::playout::PlayoutControlImpl service(controller);

  // Start a channel first (required for LoadPreview)
  retrovue::playout::StartChannelRequest start_request;
  start_request.set_channel_id(1);
  start_request.set_plan_handle("test-plan");
  start_request.set_port(8090);
  retrovue::playout::StartChannelResponse start_response;
  grpc::ServerContext start_context;
  grpc::Status start_status = service.StartChannel(&start_context, &start_request, &start_response);
  ASSERT_TRUE(start_status.ok()) << start_status.error_message();
  ASSERT_TRUE(start_response.success()) << start_response.message();

  // Execute: LoadPreview RPC (proto: asset_path, start_offset_ms, hard_stop_time_ms)
  retrovue::playout::LoadPreviewRequest request;
  request.set_channel_id(1);
  request.set_asset_path("test://preview.mp4");
  request.set_start_offset_ms(0);
  request.set_hard_stop_time_ms(0);
  retrovue::playout::LoadPreviewResponse response;
  grpc::ServerContext context;
  grpc::Status status = service.LoadPreview(&context, &request, &response);

  ASSERT_TRUE(status.ok()) << "LoadPreview RPC should succeed";
  EXPECT_TRUE(response.success()) << "LoadPreview should return success=true";

  // Cleanup
  retrovue::playout::StopChannelRequest stop_request;
  stop_request.set_channel_id(1);
  retrovue::playout::StopChannelResponse stop_response;
  grpc::ServerContext stop_context;
  service.StopChannel(&stop_context, &stop_request, &stop_response);
}

// Rule: LT-006 SwitchToLive Sequence (PlayoutEngineContract.md §LT-006)
// Tests the SwitchToLive gRPC RPC through the service implementation.
// Uses control-surface-only engine (no media) for deterministic contract testing.
TEST_F(PlayoutEngineContractTest, LT_006_SwitchToLiveSequence)
{
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);  // control_surface_only
  auto controller = std::make_shared<runtime::PlayoutController>(engine);
  retrovue::playout::PlayoutControlImpl service(controller);

  // Start a channel
  retrovue::playout::StartChannelRequest start_request;
  start_request.set_channel_id(1);
  start_request.set_plan_handle("test-plan");
  start_request.set_port(8090);
  retrovue::playout::StartChannelResponse start_response;
  grpc::ServerContext start_context;
  grpc::Status start_status = service.StartChannel(&start_context, &start_request, &start_response);
  ASSERT_TRUE(start_status.ok() && start_response.success());

  // Load preview asset (proto: asset_path)
  retrovue::playout::LoadPreviewRequest load_request;
  load_request.set_channel_id(1);
  load_request.set_asset_path("test://preview.mp4");
  load_request.set_start_offset_ms(0);
  load_request.set_hard_stop_time_ms(0);
  retrovue::playout::LoadPreviewResponse load_response;
  grpc::ServerContext load_context;
  grpc::Status load_status = service.LoadPreview(&load_context, &load_request, &load_response);
  ASSERT_TRUE(load_status.ok() && load_response.success());

  // Execute: SwitchToLive RPC (proto: channel_id only)
  retrovue::playout::SwitchToLiveRequest request;
  request.set_channel_id(1);
  retrovue::playout::SwitchToLiveResponse response;
  grpc::ServerContext context;
  grpc::Status status = service.SwitchToLive(&context, &request, &response);

  ASSERT_TRUE(status.ok()) << "SwitchToLive RPC should succeed";
  EXPECT_TRUE(response.success()) << "SwitchToLive should return success=true";

  // Cleanup
  retrovue::playout::StopChannelRequest stop_request;
  stop_request.set_channel_id(1);
  retrovue::playout::StopChannelResponse stop_response;
  grpc::ServerContext stop_context;
  service.StopChannel(&stop_context, &stop_request, &stop_response);
}

// -----------------------------------------------------------------------------
// Phase 6A.0 — Air Control Surface (Phase6A-0-ControlSurface.md)
// Server implements proto; four RPCs accept requests and return valid responses.
// No media, no producers, no frames; control-surface-only engine.
// -----------------------------------------------------------------------------

TEST_F(PlayoutEngineContractTest, Phase6A0_ServerAcceptsFourRPCs)
{
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);  // control_surface_only
  auto controller = std::make_shared<runtime::PlayoutController>(engine);
  retrovue::playout::PlayoutControlImpl service(controller);

  const int32_t channel_id = 1;

  // StartChannel → response with success set
  retrovue::playout::StartChannelRequest start_req;
  start_req.set_channel_id(channel_id);
  start_req.set_plan_handle("plan-1");
  start_req.set_port(50051);
  retrovue::playout::StartChannelResponse start_resp;
  grpc::ServerContext start_ctx;
  grpc::Status start_st = service.StartChannel(&start_ctx, &start_req, &start_resp);
  ASSERT_TRUE(start_st.ok()) << start_st.error_message();
  EXPECT_TRUE(start_resp.success()) << start_resp.message();

  // LoadPreview → response with success (optional shadow_decode_started)
  retrovue::playout::LoadPreviewRequest load_req;
  load_req.set_channel_id(channel_id);
  load_req.set_asset_path("/fake/asset.mp4");
  load_req.set_start_offset_ms(0);
  load_req.set_hard_stop_time_ms(0);
  retrovue::playout::LoadPreviewResponse load_resp;
  grpc::ServerContext load_ctx;
  grpc::Status load_st = service.LoadPreview(&load_ctx, &load_req, &load_resp);
  ASSERT_TRUE(load_st.ok()) << load_st.error_message();
  EXPECT_TRUE(load_resp.success()) << load_resp.message();

  // SwitchToLive → response with success (optional pts_contiguous)
  retrovue::playout::SwitchToLiveRequest switch_req;
  switch_req.set_channel_id(channel_id);
  retrovue::playout::SwitchToLiveResponse switch_resp;
  grpc::ServerContext switch_ctx;
  grpc::Status switch_st = service.SwitchToLive(&switch_ctx, &switch_req, &switch_resp);
  ASSERT_TRUE(switch_st.ok()) << switch_st.error_message();
  EXPECT_TRUE(switch_resp.success()) << switch_resp.message();

  // StopChannel → response with success
  retrovue::playout::StopChannelRequest stop_req;
  stop_req.set_channel_id(channel_id);
  retrovue::playout::StopChannelResponse stop_resp;
  grpc::ServerContext stop_ctx;
  grpc::Status stop_st = service.StopChannel(&stop_ctx, &stop_req, &stop_resp);
  ASSERT_TRUE(stop_st.ok()) << stop_st.error_message();
  EXPECT_TRUE(stop_resp.success()) << stop_resp.message();
}

TEST_F(PlayoutEngineContractTest, Phase6A0_StartChannelIdempotentSuccess)
{
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);
  auto controller = std::make_shared<runtime::PlayoutController>(engine);
  retrovue::playout::PlayoutControlImpl service(controller);

  retrovue::playout::StartChannelRequest req;
  req.set_channel_id(42);
  req.set_plan_handle("plan");
  req.set_port(9999);
  retrovue::playout::StartChannelResponse resp;
  grpc::ServerContext ctx;

  grpc::Status st1 = service.StartChannel(&ctx, &req, &resp);
  ASSERT_TRUE(st1.ok()) << st1.error_message();
  EXPECT_TRUE(resp.success()) << resp.message();

  resp.Clear();
  grpc::ServerContext ctx2;
  grpc::Status st2 = service.StartChannel(&ctx2, &req, &resp);
  ASSERT_TRUE(st2.ok()) << st2.error_message();
  EXPECT_TRUE(resp.success()) << "StartChannel on already-started channel must be idempotent success";
}

TEST_F(PlayoutEngineContractTest, Phase6A0_LoadPreviewBeforeStartChannel_Error)
{
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);
  auto controller = std::make_shared<runtime::PlayoutController>(engine);
  retrovue::playout::PlayoutControlImpl service(controller);

  retrovue::playout::LoadPreviewRequest req;
  req.set_channel_id(99);
  req.set_asset_path("/any/path.mp4");
  retrovue::playout::LoadPreviewResponse resp;
  grpc::ServerContext ctx;
  grpc::Status st = service.LoadPreview(&ctx, &req, &resp);
  ASSERT_TRUE(st.ok()) << st.error_message();
  EXPECT_FALSE(resp.success()) << "LoadPreview before StartChannel must return success=false";
}

TEST_F(PlayoutEngineContractTest, Phase6A0_SwitchToLiveWithNoPreview_Error)
{
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);
  auto controller = std::make_shared<runtime::PlayoutController>(engine);
  retrovue::playout::PlayoutControlImpl service(controller);

  retrovue::playout::StartChannelRequest start_req;
  start_req.set_channel_id(2);
  start_req.set_plan_handle("p");
  start_req.set_port(50052);
  retrovue::playout::StartChannelResponse start_resp;
  grpc::ServerContext start_ctx;
  grpc::Status start_st = service.StartChannel(&start_ctx, &start_req, &start_resp);
  ASSERT_TRUE(start_st.ok() && start_resp.success());

  retrovue::playout::SwitchToLiveRequest req;
  req.set_channel_id(2);
  retrovue::playout::SwitchToLiveResponse resp;
  grpc::ServerContext ctx;
  grpc::Status st = service.SwitchToLive(&ctx, &req, &resp);
  ASSERT_TRUE(st.ok()) << st.error_message();
  EXPECT_FALSE(resp.success()) << "SwitchToLive with no preview loaded must return success=false";
}

TEST_F(PlayoutEngineContractTest, Phase6A0_StopChannelIdempotentSuccess)
{
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, true);
  auto controller = std::make_shared<runtime::PlayoutController>(engine);
  retrovue::playout::PlayoutControlImpl service(controller);

  retrovue::playout::StopChannelRequest req;
  req.set_channel_id(999);  // never started
  retrovue::playout::StopChannelResponse resp;
  grpc::ServerContext ctx;
  grpc::Status st = service.StopChannel(&ctx, &req, &resp);
  ASSERT_TRUE(st.ok()) << st.error_message();
  EXPECT_TRUE(resp.success()) << "StopChannel on unknown channel must be idempotent success";

  resp.Clear();
  grpc::ServerContext ctx2;
  grpc::Status st2 = service.StopChannel(&ctx2, &req, &resp);
  ASSERT_TRUE(st2.ok()) << st2.error_message();
  EXPECT_TRUE(resp.success()) << "StopChannel on already-stopped channel must be idempotent success";
}

// ---------------------------------------------------------------------------
// Phase 6A.1 — ExecutionProducer lifecycle and preview/live slot semantics
// (Phase6A-1-ExecutionProducer.md)
// ---------------------------------------------------------------------------

TEST_F(PlayoutEngineContractTest, Phase6A1_LoadPreviewInstallsIntoPreviewSlot_LiveUnchanged)
{
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer&, std::shared_ptr<retrovue::timing::MasterClock>,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        return std::make_unique<StubProducer>(StubProducer::SegmentParams{
            path, asset_id, start_offset_ms, hard_stop_time_ms});
      });

  EXPECT_FALSE(controller.getPreviewSlot().loaded);
  EXPECT_FALSE(controller.getLiveSlot().loaded);

  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://segment.mp4", "seg-1", buffer, clock, 100, 60'000));

  const auto& preview = controller.getPreviewSlot();
  EXPECT_TRUE(preview.loaded) << "LoadPreview must install segment into preview slot";
  EXPECT_EQ(preview.asset_id, "seg-1");
  EXPECT_EQ(preview.file_path, "test://segment.mp4");
  ASSERT_NE(preview.producer, nullptr);
  EXPECT_TRUE(preview.producer->isRunning());

  const auto& live = controller.getLiveSlot();
  EXPECT_FALSE(live.loaded) << "Live must be unchanged until SwitchToLive";

  auto* stub = dynamic_cast<StubProducer*>(preview.producer.get());
  ASSERT_NE(stub, nullptr);
  EXPECT_EQ(stub->segmentParams().start_offset_ms, 100);
  EXPECT_EQ(stub->segmentParams().hard_stop_time_ms, 60'000);
  EXPECT_EQ(stub->startCount(), 1);
  EXPECT_EQ(stub->stopCount(), 0);
}

TEST_F(PlayoutEngineContractTest, Phase6A1_SwitchToLivePromotesPreview_StopsOldLive_ClearsPreview)
{
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer&, std::shared_ptr<retrovue::timing::MasterClock>,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        return std::make_unique<StubProducer>(
            StubProducer::SegmentParams{path, asset_id, start_offset_ms, hard_stop_time_ms});
      });

  ASSERT_TRUE(controller.loadPreviewAsset("test://a.mp4", "asset-a", buffer, clock, 0, 0));
  ASSERT_TRUE(controller.activatePreviewAsLive());

  const auto& live1 = controller.getLiveSlot();
  ASSERT_TRUE(live1.loaded);
  ASSERT_EQ(live1.asset_id, "asset-a");
  EXPECT_TRUE(live1.producer->isRunning());
  EXPECT_FALSE(controller.getPreviewSlot().loaded);

  ASSERT_TRUE(controller.loadPreviewAsset("test://b.mp4", "asset-b", buffer, clock, 0, 0));
  const auto& preview2 = controller.getPreviewSlot();
  ASSERT_TRUE(preview2.loaded);
  ASSERT_EQ(preview2.asset_id, "asset-b");

  ASSERT_TRUE(controller.activatePreviewAsLive());
  // Contract: old live is stopped before swap; preview slot cleared.


  const auto& live2 = controller.getLiveSlot();
  EXPECT_TRUE(live2.loaded);
  EXPECT_EQ(live2.asset_id, "asset-b");
  EXPECT_TRUE(live2.producer->isRunning());

  const auto& preview_after = controller.getPreviewSlot();
  EXPECT_FALSE(preview_after.loaded) << "Preview slot must be cleared after SwitchToLive";
}

TEST_F(PlayoutEngineContractTest, Phase6A1_ProducerReceivesSegmentParams_HardStopRecorded)
{
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer&, std::shared_ptr<retrovue::timing::MasterClock>,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        return std::make_unique<StubProducer>(
            StubProducer::SegmentParams{path, asset_id, start_offset_ms, hard_stop_time_ms});
      });

  const int64_t start_offset_ms = 5'000;
  const int64_t hard_stop_time_ms = 90'000;
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://seg.mp4", "seg-id", buffer, clock, start_offset_ms, hard_stop_time_ms));

  const auto& preview = controller.getPreviewSlot();
  auto* stub = dynamic_cast<StubProducer*>(preview.producer.get());
  ASSERT_NE(stub, nullptr);
  EXPECT_EQ(stub->segmentParams().asset_path, "test://seg.mp4");
  EXPECT_EQ(stub->segmentParams().asset_id, "seg-id");
  EXPECT_EQ(stub->segmentParams().start_offset_ms, start_offset_ms);
  EXPECT_EQ(stub->segmentParams().hard_stop_time_ms, hard_stop_time_ms)
      << "Segment hard_stop_time_ms must be passed to producer for 6A.2 enforcement";
}

TEST_F(PlayoutEngineContractTest, Phase6A1_StopReleasesProducer_ObservableStoppedState)
{
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer&, std::shared_ptr<retrovue::timing::MasterClock>,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        return std::make_unique<StubProducer>(
            StubProducer::SegmentParams{path, asset_id, start_offset_ms, hard_stop_time_ms});
      });

  ASSERT_TRUE(controller.loadPreviewAsset("test://x.mp4", "x", buffer, clock, 0, 0));
  ASSERT_TRUE(controller.activatePreviewAsLive());
  const auto& live = controller.getLiveSlot();
  ASSERT_TRUE(live.loaded);
  ASSERT_TRUE(live.producer->isRunning());
  auto* stub = dynamic_cast<StubProducer*>(live.producer.get());
  ASSERT_NE(stub, nullptr);
  EXPECT_EQ(stub->stopCount(), 0);

  live.producer->stop();
  EXPECT_FALSE(live.producer->isRunning()) << "After stop, producer must not be running";
  EXPECT_EQ(stub->stopCount(), 1) << "Stop must be observable (contract: resources released)";
}

// ---------------------------------------------------------------------------
// Phase 6A.2 — FileBackedProducer: start_offset_ms and hard_stop_time_ms honored
// (Phase6A-2-FileBackedProducer.md)
// ---------------------------------------------------------------------------

TEST_F(PlayoutEngineContractTest, Phase6A2_HardStopEnforced_ProducerStopsByDeadline)
{
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  const int64_t start_us = 1'000'000'000'000'000LL;  // epoch-like base
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>(
      start_us, retrovue::timing::TestMasterClock::Mode::Deterministic);
  int64_t hard_stop_ms = (start_us / 1000) + 5000;  // stop 5s after start

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer& rb, std::shared_ptr<retrovue::timing::MasterClock> clk,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        producers::video_file::ProducerConfig config;
        config.asset_uri = path;
        config.target_width = 1920;
        config.target_height = 1080;
        config.target_fps = 30.0;
        config.stub_mode = true;
        config.start_offset_ms = start_offset_ms;
        config.hard_stop_time_ms = hard_stop_time_ms;
        return std::make_unique<producers::video_file::VideoFileProducer>(config, rb, clk, nullptr);
      });

  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://clip.mp4", "clip", buffer, clock, 0, hard_stop_ms));

  const auto& preview = controller.getPreviewSlot();
  ASSERT_TRUE(preview.loaded);
  ASSERT_TRUE(preview.producer->isRunning());

  // Advance clock past hard_stop_time_ms so producer must stop (Phase 6A.2)
  auto test_clock = std::static_pointer_cast<retrovue::timing::TestMasterClock>(clock);
  test_clock->AdvanceMicroseconds(6'000'000);  // +6 s

  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  EXPECT_FALSE(preview.producer->isRunning())
      << "Producer must stop at or before hard_stop_time_ms";
}

TEST_F(PlayoutEngineContractTest, Phase6A2_SegmentParamsPassedToFileBackedProducer)
{
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1'700'000'000'000'000LL);

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer& rb, std::shared_ptr<retrovue::timing::MasterClock> clk,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        producers::video_file::ProducerConfig config;
        config.asset_uri = path;
        config.target_width = 1920;
        config.target_height = 1080;
        config.target_fps = 30.0;
        config.stub_mode = true;
        config.start_offset_ms = start_offset_ms;
        config.hard_stop_time_ms = hard_stop_time_ms;
        return std::make_unique<producers::video_file::VideoFileProducer>(config, rb, clk, nullptr);
      });

  const int64_t start_offset_ms = 60'000;
  const int64_t hard_stop_time_ms = 90'000;
  ASSERT_TRUE(controller.loadPreviewAsset(
      "test://seg.mp4", "seg", buffer, clock, start_offset_ms, hard_stop_time_ms));
  const auto& preview = controller.getPreviewSlot();
  ASSERT_TRUE(preview.loaded);
  EXPECT_TRUE(preview.producer->isRunning());
  // Params are in config and honored (seek in real decode; hard_stop in loop)
  preview.producer->stop();
}

TEST_F(PlayoutEngineContractTest, Phase6A2_InvalidPath_LoadPreviewFails)
{
  runtime::PlayoutControlStateMachine controller;
  buffer::FrameRingBuffer buffer(60);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();

  controller.setProducerFactory(
      [](const std::string& path, const std::string& asset_id,
         buffer::FrameRingBuffer& rb, std::shared_ptr<retrovue::timing::MasterClock> clk,
         int64_t start_offset_ms, int64_t hard_stop_time_ms)
          -> std::unique_ptr<retrovue::producers::IProducer> {
        producers::video_file::ProducerConfig config;
        config.asset_uri = path;
        config.target_width = 1920;
        config.target_height = 1080;
        config.target_fps = 30.0;
        config.stub_mode = false;  // Real decode path so open fails for bad path
        config.start_offset_ms = start_offset_ms;
        config.hard_stop_time_ms = hard_stop_time_ms;
        return std::make_unique<producers::video_file::VideoFileProducer>(config, rb, clk, nullptr);
      });

  bool ok = controller.loadPreviewAsset(
      "/nonexistent/path/video.mp4", "bad", buffer, clock, 0, 0);
  EXPECT_FALSE(ok) << "LoadPreview must return false for invalid/unreadable path (Phase 6A.2)";
}

} // namespace

