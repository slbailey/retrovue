// AIR vNext — IR1b pull-path integration test.
//
// Proves the grpc-backed PullResponder satisfies the PullResponder
// contract end-to-end:
//   1. queue below target triggers a GetSuccessorOf request
//   2. Core returns a Block over the wire
//   3. AirSession's pull worker uses the AddQueuedBlock path to
//      enqueue the returned Block
//   4. session remains healthy through the handoff
//
// No admission-validation coverage here — that lands later.

#include <grpcpp/grpcpp.h>
#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <thread>

#include "air_control.grpc.pb.h"
#include "air_session.hpp"
#include "block.hpp"
#include "channel_canonical.hpp"
#include "grpc_pull_responder.hpp"

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

ChannelCanonical TestCanonical() {
  ChannelCanonical c;
  c.video.width = 968;
  c.video.height = 720;
  c.video.frame_rate = {30000, 1001};
  c.video.pixel_format = PixelFormat::kYuv420p;
  c.audio.sample_rate = 48000;
  c.audio.channels = 2;
  return c;
}

Block MakeBlock(const std::string& id, const std::string& asset,
                int seg_count, int64_t start_utc_ms, int64_t seg_ms = 1000) {
  Block b;
  b.block_id = id;
  b.start_utc_ms = start_utc_ms;
  b.end_utc_ms = start_utc_ms + seg_count * seg_ms;
  b.canonical = TestCanonical();
  for (int i = 0; i < seg_count; ++i) {
    Segment s;
    s.segment_id = id + ":" + std::to_string(i);
    s.asset_uri = asset;
    s.asset_start_offset_ms = 0;
    s.duration_ms = seg_ms;
    s.segment_index = i;
    b.segments.push_back(s);
  }
  return b;
}

void FillCanonicalProto(retrovue::air::v1::ChannelCanonical* c) {
  c->set_video_width(968);
  c->set_video_height(720);
  c->set_video_fps_num(30000);
  c->set_video_fps_den(1001);
  c->set_audio_sample_rate(48000);
  c->set_audio_channels(2);
}

void FillBlockProto(retrovue::air::v1::Block* out, const std::string& block_id,
                    const std::string& asset_path, int seg_count,
                    int64_t start_utc_ms, int64_t seg_ms = 1000) {
  out->set_block_id(block_id);
  out->set_start_utc_ms(start_utc_ms);
  out->set_end_utc_ms(start_utc_ms + seg_count * seg_ms);
  FillCanonicalProto(out->mutable_canonical());
  for (int i = 0; i < seg_count; ++i) {
    auto* seg = out->add_segments();
    seg->set_segment_id(block_id + ":" + std::to_string(i));
    seg->set_asset_uri(asset_path);
    seg->set_asset_start_offset_ms(0);
    seg->set_duration_ms(seg_ms);
    seg->set_segment_index(i);
  }
}

// Core stand-in. One-shot: returns Block B exactly once when asked for
// the successor of A. Subsequent calls return supplied=false so the
// pull worker backs off instead of re-enqueuing.
class CoreBlockSupplyStub final
    : public retrovue::air::v1::CoreBlockSupply::Service {
 public:
  CoreBlockSupplyStub(const std::string& asset, int64_t a_start_ms)
      : asset_(asset), a_start_ms_(a_start_ms) {}

  grpc::Status GetSuccessorOf(
      grpc::ServerContext* /*ctx*/,
      const retrovue::air::v1::GetSuccessorOfRequest* req,
      retrovue::air::v1::GetSuccessorOfResponse* resp) override {
    requests_received_.fetch_add(1);
    bool expected = true;
    if (req->predecessor_block_id() == "A" &&
        b_available_.compare_exchange_strong(expected, false)) {
      resp->set_supplied(true);
      FillBlockProto(resp->mutable_block(), "B", asset_, 1,
                     a_start_ms_ + 1000);
      return grpc::Status::OK;
    }
    resp->set_supplied(false);
    return grpc::Status::OK;
  }

  int64_t requests_received() const { return requests_received_.load(); }

 private:
  std::string asset_;
  int64_t a_start_ms_;
  std::atomic<bool> b_available_{true};
  std::atomic<int64_t> requests_received_{0};
};

// UDS byte path for AIR's output. Minimal — just accepts the connection
// and drains bytes; shutdown before join unblocks accept() if no client
// ever connects.
struct UdsFixture {
  std::string uds_path;
  int listen_fd = -1;
  int client_fd = -1;
  std::atomic<bool> reader_running{true};
  std::thread reader;

  void Setup(const std::string& tag) {
    uds_path = "/tmp/air_ir1b_" + tag + "_" + std::to_string(getpid()) + ".sock";
    ::unlink(uds_path.c_str());
    listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, uds_path.c_str(), sizeof(addr.sun_path) - 1);
    ::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    ::listen(listen_fd, 1);
    reader = std::thread([this]() {
      int conn = ::accept(listen_fd, nullptr, nullptr);
      if (conn < 0) return;
      uint8_t buf[16 * 1024];
      while (reader_running.load()) {
        ssize_t n = ::read(conn, buf, sizeof(buf));
        if (n <= 0) break;
      }
      ::close(conn);
    });
    client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un client_addr{};
    client_addr.sun_family = AF_UNIX;
    std::strncpy(client_addr.sun_path, uds_path.c_str(),
                 sizeof(client_addr.sun_path) - 1);
    ::connect(client_fd, reinterpret_cast<sockaddr*>(&client_addr),
              sizeof(client_addr));
  }

  void Teardown() {
    reader_running.store(false);
    if (listen_fd >= 0) ::shutdown(listen_fd, SHUT_RDWR);
    if (reader.joinable()) reader.join();
    if (listen_fd >= 0) ::close(listen_fd);
    ::unlink(uds_path.c_str());
  }
};

TEST(GrpcPullResponderTest, QueueLowTriggersRequestAndEnqueuesReturnedBlock) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  // 1. Stand up in-process CoreBlockSupply server.
  const int64_t a_start = 1'700'000'000'000LL;
  CoreBlockSupplyStub core_impl(asset, a_start);
  int port = 0;
  grpc::ServerBuilder builder;
  builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(),
                           &port);
  builder.RegisterService(&core_impl);
  std::unique_ptr<grpc::Server> server = builder.BuildAndStart();
  ASSERT_NE(server, nullptr);
  auto channel = grpc::CreateChannel(
      "127.0.0.1:" + std::to_string(port),
      grpc::InsecureChannelCredentials());

  // 2. AIR side: UDS output + session seeded with A.
  UdsFixture uds;
  uds.Setup("pull_factory");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  session.SetPullResponder(MakeGrpcPullResponder(channel, /*channel_id=*/1));
  session.SetPullTargetDepth(2);  // active + 1 queued

  // Single-segment A (1000ms). The stub returns B at a_start+1000 —
  // flush with A.end under the IR2.3 continuity rule.
  const Block a = MakeBlock("A", asset, 1, a_start);
  ASSERT_TRUE(session.SeedActiveBlock(a));
  ASSERT_TRUE(session.OpenAir());

  // 3. Wait for the pull worker to trigger + Core to respond + AirSession
  //    to enqueue B via the AddQueuedBlock path. The supplied-counter
  //    increment is AirSession's proof that AddQueuedBlock ran (the
  //    pull worker only bumps supplied_total after invoking the
  //    AddQueuedBlock path on the returned Block).
  const auto deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (session.PullResponsesSuppliedTotal() < 1 &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  EXPECT_GE(session.PullRequestsIssuedTotal(), 1)
      << "pull worker never issued a request";
  EXPECT_GE(session.PullResponsesSuppliedTotal(), 1)
      << "grpc-backed responder never supplied a Block";
  EXPECT_GE(core_impl.requests_received(), 1)
      << "in-process Core stand-in never received an RPC";
  EXPECT_EQ(session.QueueDepth(), 2)
      << "AddQueuedBlock path should have brought depth to active + 1";

  // 4. Session remains healthy.
  EXPECT_NE(session.State(), SessionState::FailedStart);

  session.Close();
  server->Shutdown();
  uds.Teardown();
}

}  // namespace
}  // namespace retrovue::air
