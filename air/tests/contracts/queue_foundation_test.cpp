// AIR vNext — Phase B queue-foundation test (segment-aware).
//
// Validates the execution-queue surface in Phase B (re-do):
//   1. StartChannel with seed_block (multi-segment) initializes the queue.
//   2. SupplyBlock appends a queued Block (with its segment list).
//   3. GetSessionStatus reports queue_depth (Block grain) and segment_depth.
//
// Does NOT exercise seams or segment transitions (Phase C). Playback still
// terminates at active Block's first-segment EOF.

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

// Build a Block proto with N segments all pointing at `asset_path`. Used
// to exercise queue_depth (Block grain) and segment_depth (internal sum)
// reporting. Phase B does not execute multi-segment walks; Phase C will.
void BuildBlockProto(retrovue::air::v1::Block* out,
                     const std::string& block_id,
                     const std::string& asset_path,
                     int segment_count,
                     int64_t start_utc_ms,
                     int64_t segment_duration_ms = 10000) {
  out->set_block_id(block_id);
  out->set_start_utc_ms(start_utc_ms);
  out->set_end_utc_ms(start_utc_ms + segment_count * segment_duration_ms);
  FillCheersCanonical(out->mutable_canonical());
  for (int i = 0; i < segment_count; ++i) {
    auto* seg = out->add_segments();
    seg->set_segment_id(block_id + ":" + std::to_string(i));
    seg->set_asset_uri(asset_path);
    seg->set_asset_start_offset_ms(0);
    seg->set_duration_ms(segment_duration_ms);
    seg->set_segment_index(i);
  }
}

TEST(QueueFoundationTest, SeedAndSupplyBlocksWithMultipleSegments) {
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

  // --- StartChannel with a 3-segment seed Block ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StartChannelRequest req;
    req.set_channel_id(1);
    req.set_output_uds_path(uds);
    FillCheersCanonical(req.mutable_canonical());
    BuildBlockProto(req.mutable_seed_block(), "block-A", input, 3,
                    /*start_utc_ms=*/1'700'000'000'000LL);

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

  // --- After seed: queue_depth=1 Block, segment_depth=3 Segments ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.state(), retrovue::air::v1::SESSION_STATE_ON_AIR);
    EXPECT_EQ(resp.queue_depth(), 1)
        << "expected 1 Block (active only) after seed";
    EXPECT_EQ(resp.segment_depth(), 3)
        << "expected 3 Segments (all in active block A)";
  }

  // --- SupplyBlock appends a 2-segment Block B ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::SupplyBlockRequest req;
    req.set_channel_id(1);
    req.set_predecessor_id("block-A");
    BuildBlockProto(req.mutable_block(), "block-B", input, 2,
                    /*start_utc_ms=*/1'700'000'030'000LL);
    retrovue::air::v1::SupplyBlockResponse resp;
    ASSERT_TRUE(stub->SupplyBlock(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok()) << "SupplyBlock rejected: " << resp.reason();
  }

  // --- After SupplyBlock: queue_depth=2, segment_depth=5 ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.queue_depth(), 2) << "expected 2 Blocks (active + 1 queued)";
    EXPECT_EQ(resp.segment_depth(), 5) << "expected 5 Segments (3 + 2)";
  }

  // --- Supply a single-segment Block C ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::SupplyBlockRequest req;
    req.set_channel_id(1);
    req.set_predecessor_id("block-B");
    BuildBlockProto(req.mutable_block(), "block-C", input, 1,
                    /*start_utc_ms=*/1'700'000'050'000LL);
    retrovue::air::v1::SupplyBlockResponse resp;
    ASSERT_TRUE(stub->SupplyBlock(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok());
  }

  // --- queue_depth=3 Blocks, segment_depth=6 Segments ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.queue_depth(), 3) << "expected 3 Blocks";
    EXPECT_EQ(resp.segment_depth(), 6) << "expected 6 Segments (3 + 2 + 1)";
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
    EXPECT_EQ(resp.queue_depth(), 0) << "queue should be empty after Close";
    EXPECT_EQ(resp.segment_depth(), 0) << "no segments after Close";
  }

  server->Shutdown();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());
}

// Reject path: Block with zero segments is malformed per the truth.
TEST(QueueFoundationTest, SupplyBlockWithEmptySegmentsReturnsEmptySegments) {
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

  const std::string uds =
      "/tmp/air_queue_empty_segs_" + std::to_string(getpid()) + ".sock";
  ::unlink(uds.c_str());
  int listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(listen_fd, 0);
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  std::strncpy(addr.sun_path, uds.c_str(), sizeof(addr.sun_path) - 1);
  ASSERT_EQ(::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)), 0);
  ASSERT_EQ(::listen(listen_fd, 1), 0);
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

  // Seed with a valid 1-segment Block.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StartChannelRequest req;
    req.set_channel_id(1);
    req.set_output_uds_path(uds);
    FillCheersCanonical(req.mutable_canonical());
    BuildBlockProto(req.mutable_seed_block(), "block-A", input, 1,
                    /*start_utc_ms=*/1'700'000'000'000LL);
    retrovue::air::v1::StartChannelResponse resp;
    ASSERT_TRUE(stub->StartChannel(&ctx, req, &resp).ok());
    ASSERT_TRUE(resp.ok()) << resp.message();
  }

  // SupplyBlock with empty segments — must be rejected.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::SupplyBlockRequest req;
    req.set_channel_id(1);
    req.set_predecessor_id("block-A");
    auto* b = req.mutable_block();
    b->set_block_id("block-malformed");
    b->set_start_utc_ms(1);
    b->set_end_utc_ms(2);
    FillCheersCanonical(b->mutable_canonical());
    // No segments added — this is what makes it malformed.
    retrovue::air::v1::SupplyBlockResponse resp;
    ASSERT_TRUE(stub->SupplyBlock(&ctx, req, &resp).ok());
    EXPECT_FALSE(resp.ok());
    EXPECT_EQ(resp.reason(), "EMPTY_SEGMENTS");
  }

  // StopChannel.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StopChannelRequest req;
    req.set_channel_id(1);
    retrovue::air::v1::StopChannelResponse resp;
    ASSERT_TRUE(stub->StopChannel(&ctx, req, &resp).ok());
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
  // Structurally valid block (IR2.1) so the only admission failure
  // here is NO_SESSION.
  b->set_start_utc_ms(1'700'000'000'000LL);
  b->set_end_utc_ms(1'700'000'000'000LL + 1000);
  auto* seg = b->add_segments();
  seg->set_segment_id("orphan:0");
  seg->set_asset_uri("/does/not/matter");
  seg->set_duration_ms(1000);
  seg->set_segment_index(0);

  retrovue::air::v1::SupplyBlockResponse resp;
  ASSERT_TRUE(stub->SupplyBlock(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "NO_SESSION");

  server->Shutdown();
}

}  // namespace
}  // namespace retrovue::air
