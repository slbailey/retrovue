// AIR vNext — Phase B queue-foundation test.
//
// Validates the execution-queue surface added in Phase B:
//   1. StartChannel with seed_block initializes the queue with an active block.
//   2. SupplyBlock appends a queued block.
//   3. GetSessionStatus reports accurate queue_depth.
//
// Does NOT exercise seams (that's Phase C). The second (queued) block never
// actually plays in this test; we only verify the queue surface accepts and
// reports it.

#include <grpcpp/grpcpp.h>
#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <thread>

#include "air_control.grpc.pb.h"
#include "grpc_service.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) return env;
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return AIR_VNEXT_SAMPLE_A_PATH;
#else
  return "";
#endif
}

void FillCheersCanonical(retrovue::air::v1::ChannelCanonical* c) {
  c->set_video_width(968);
  c->set_video_height(720);
  c->set_video_fps_num(30000);
  c->set_video_fps_den(1001);
  c->set_audio_sample_rate(48000);
  c->set_audio_channels(2);
}

TEST(QueueFoundationTest, SeedBlockAndSupplyBlockGrowQueueDepth) {
  const std::string input = ResolveSampleA();
  if (!std::filesystem::exists(input)) {
    GTEST_SKIP() << "SampleA not found";
  }

  AirControlServiceImpl service;
  grpc::ServerBuilder builder;
  int port = 0;
  builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &port);
  builder.RegisterService(&service);
  auto server = builder.BuildAndStart();
  ASSERT_GT(port, 0);

  const std::string uds =
      "/tmp/air_queue_foundation_" + std::to_string(getpid()) + ".sock";
  ::unlink(uds.c_str());
  int listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(listen_fd, 0);
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  std::strncpy(addr.sun_path, uds.c_str(), sizeof(addr.sun_path) - 1);
  ASSERT_EQ(::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)), 0);
  ASSERT_EQ(::listen(listen_fd, 1), 0);

  // Reader drains bytes so AIR's socket writes don't stall. We don't verify
  // content here — that's covered by grpc_start_stop_integration_test.
  std::atomic<bool> reader_running{true};
  std::thread reader([&]() {
    int conn = ::accept(listen_fd, nullptr, nullptr);
    if (conn < 0) return;
    uint8_t buf[16 * 1024];
    while (reader_running.load()) {
      ssize_t n = ::read(conn, buf, sizeof(buf));
      if (n <= 0) break;
    }
    ::close(conn);
  });

  auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(port),
                                     grpc::InsecureChannelCredentials());
  auto stub = retrovue::air::v1::AirControl::NewStub(channel);

  // --- StartChannel with seed_block ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StartChannelRequest req;
    req.set_channel_id(1);
    req.set_output_uds_path(uds);
    FillCheersCanonical(req.mutable_canonical());

    auto* seed = req.mutable_seed_block();
    seed->set_block_id("block-A");
    seed->set_asset_uri(input);
    seed->set_start_utc_ms(1'700'000'000'000LL);
    seed->set_end_utc_ms(1'700'000'030'000LL);  // +30s (matches SampleA)
    seed->set_jip_offset_ms(0);
    FillCheersCanonical(seed->mutable_canonical());

    retrovue::air::v1::StartChannelResponse resp;
    ASSERT_TRUE(stub->StartChannel(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok()) << resp.message();
  }

  // Wait for lifecycle to reach OnAir so queue accounting is stable.
  for (int i = 0; i < 50; ++i) {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    if (stub->GetSessionStatus(&ctx, req, &resp).ok() &&
        resp.state() == retrovue::air::v1::SESSION_STATE_ON_AIR) {
      break;
    }
  }

  // --- Queue depth should be 1 (active only, nothing queued yet) ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.state(), retrovue::air::v1::SESSION_STATE_ON_AIR);
    EXPECT_EQ(resp.queue_depth(), 1)
        << "expected 1 (active only) before any SupplyBlock";
  }

  // --- SupplyBlock appends a queued block ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::SupplyBlockRequest req;
    req.set_channel_id(1);
    req.set_predecessor_id("block-A");
    auto* b = req.mutable_block();
    b->set_block_id("block-B");
    b->set_asset_uri(input);  // reuse SampleA; Phase B doesn't play it
    b->set_start_utc_ms(1'700'000'030'000LL);
    b->set_end_utc_ms(1'700'000'060'000LL);
    b->set_jip_offset_ms(0);
    FillCheersCanonical(b->mutable_canonical());

    retrovue::air::v1::SupplyBlockResponse resp;
    ASSERT_TRUE(stub->SupplyBlock(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok()) << "SupplyBlock rejected: " << resp.reason();
  }

  // --- Queue depth should be 2 (active + 1 queued) ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.queue_depth(), 2)
        << "expected 2 (active + 1 queued) after SupplyBlock";
  }

  // --- Supply one more for good measure ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::SupplyBlockRequest req;
    req.set_channel_id(1);
    req.set_predecessor_id("block-B");
    auto* b = req.mutable_block();
    b->set_block_id("block-C");
    b->set_asset_uri(input);
    b->set_start_utc_ms(1'700'000'060'000LL);
    b->set_end_utc_ms(1'700'000'090'000LL);
    FillCheersCanonical(b->mutable_canonical());

    retrovue::air::v1::SupplyBlockResponse resp;
    ASSERT_TRUE(stub->SupplyBlock(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok());
  }

  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.queue_depth(), 3) << "expected 3 (active + 2 queued)";
  }

  // --- StopChannel clears the queue ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StopChannelRequest req;
    req.set_channel_id(1);
    retrovue::air::v1::StopChannelResponse resp;
    ASSERT_TRUE(stub->StopChannel(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok());
  }

  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.state(), retrovue::air::v1::SESSION_STATE_STOPPING);
    EXPECT_EQ(resp.queue_depth(), 0) << "queue should be cleared after Close";
  }

  server->Shutdown();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());
}

// Reject path: SupplyBlock before any session is active.
TEST(QueueFoundationTest, SupplyBlockWithoutSessionReturnsNoSession) {
  AirControlServiceImpl service;
  grpc::ServerBuilder builder;
  int port = 0;
  builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(), &port);
  builder.RegisterService(&service);
  auto server = builder.BuildAndStart();

  auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(port),
                                     grpc::InsecureChannelCredentials());
  auto stub = retrovue::air::v1::AirControl::NewStub(channel);

  grpc::ClientContext ctx;
  retrovue::air::v1::SupplyBlockRequest req;
  req.set_channel_id(1);
  auto* b = req.mutable_block();
  b->set_block_id("orphan");
  b->set_asset_uri("/does/not/matter");

  retrovue::air::v1::SupplyBlockResponse resp;
  ASSERT_TRUE(stub->SupplyBlock(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "NO_SESSION");

  server->Shutdown();
}

}  // namespace
}  // namespace retrovue::air
