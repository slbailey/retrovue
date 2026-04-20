// AIR vNext — status RPC + lifecycle event smoke test.
//
// Verifies two observability surfaces added in the Mode-C slice:
//   1. GetSessionStatus RPC returns sensible values at each phase
//      (NONE → Warming → OnAir → Stopping).
//   2. Lifecycle observer receives state transitions in the expected order.
//
// Pattern mirrors grpc_start_stop_integration_test.cpp: in-process gRPC
// server + UDS reader thread + SampleA pipeline.

#include <grpcpp/grpcpp.h>
#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "air_control.grpc.pb.h"
#include "air_session.hpp"
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

bool FixtureExists(const std::string& path) {
  return std::filesystem::exists(path);
}

// Spin up gRPC server in-process on an ephemeral port, return port + server
// + running_thread. Caller is responsible for Shutdown + join.
struct ServerHandle {
  std::unique_ptr<grpc::Server> server;
  int port = 0;
};

ServerHandle StartServer(AirControlServiceImpl* service) {
  grpc::ServerBuilder builder;
  int picked_port = 0;
  builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(),
                           &picked_port);
  builder.RegisterService(service);
  ServerHandle h;
  h.server = builder.BuildAndStart();
  h.port = picked_port;
  return h;
}

TEST(GrpcStatusTest, StatusAndLifecycleEventsFlowThroughPhases) {
  const std::string input = ResolveSampleA();
  if (!FixtureExists(input)) {
    GTEST_SKIP() << "SampleA not found at " << input;
  }

  // Capture lifecycle events via a custom observer installed on the session.
  // We need to reach into the service's session to install the observer —
  // simplest path: install it on the service's session directly before
  // starting the server (the service's session member is accessible because
  // the test is in the same namespace).
  AirControlServiceImpl service;

  std::mutex events_mu;
  std::vector<StateTransitionEvent> events;
  // Set observer before the server starts — observer is read by the encode
  // thread during OpenAir. NOTE: AirControlServiceImpl doesn't expose its
  // session_ member, so this test uses a freshly constructed AirSession in
  // a subordinate pattern. We verify events via a dedicated session that
  // receives the observer; the RPC flow uses the service's internal session
  // (which uses the default stderr observer). The test validates:
  //   - default observer doesn't crash
  //   - custom observer can be installed and fires correctly (validated in
  //     a separate simpler test below)

  auto srv = StartServer(&service);
  ASSERT_GT(srv.port, 0);

  const std::string uds_path =
      "/tmp/air_status_test_" + std::to_string(getpid()) + ".sock";
  ::unlink(uds_path.c_str());

  int listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(listen_fd, 0);
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  std::strncpy(addr.sun_path, uds_path.c_str(), sizeof(addr.sun_path) - 1);
  ASSERT_EQ(::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)), 0);
  ASSERT_EQ(::listen(listen_fd, 1), 0);

  std::atomic<int64_t> total_read{0};
  std::thread reader([&]() {
    int conn = ::accept(listen_fd, nullptr, nullptr);
    if (conn < 0) return;
    std::vector<uint8_t> buf(64 * 1024);
    for (;;) {
      ssize_t n = ::read(conn, buf.data(), buf.size());
      if (n <= 0) break;
      total_read.fetch_add(n);
    }
    ::close(conn);
  });

  auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(srv.port),
                                     grpc::InsecureChannelCredentials());
  auto stub = retrovue::air::v1::AirControl::NewStub(channel);

  // --- Status before StartChannel should be NONE ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.state(), retrovue::air::v1::SESSION_STATE_NONE);
    EXPECT_EQ(resp.frames_encoded(), 0);
  }

  // --- StartChannel ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StartChannelRequest req;
    req.set_channel_id(1);
    req.set_input_path(input);
    req.set_output_uds_path(uds_path);
    auto* c = req.mutable_canonical();
    c->set_video_width(968);
    c->set_video_height(720);
    c->set_video_fps_num(30000);
    c->set_video_fps_den(1001);
    c->set_audio_sample_rate(48000);
    c->set_audio_channels(2);
    retrovue::air::v1::StartChannelResponse resp;
    ASSERT_TRUE(stub->StartChannel(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok()) << resp.message();
  }

  // --- Poll status until state == ON_AIR (or timeout) ---
  retrovue::air::v1::SessionStateProto last_state =
      retrovue::air::v1::SESSION_STATE_UNSPECIFIED;
  int64_t on_air_frames = 0;
  int64_t on_air_bootstrap_us = -1;
  for (int i = 0; i < 50; ++i) {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    last_state = resp.state();
    on_air_frames = resp.frames_encoded();
    on_air_bootstrap_us = resp.bootstrap_total_duration_us();
    if (last_state == retrovue::air::v1::SESSION_STATE_ON_AIR) break;
  }
  EXPECT_EQ(last_state, retrovue::air::v1::SESSION_STATE_ON_AIR);
  EXPECT_GT(on_air_bootstrap_us, 0);

  // --- Let some frames flow, verify counters advance ---
  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_GT(resp.frames_encoded(), on_air_frames);
    EXPECT_GT(resp.bytes_written(), 0);
  }

  // --- StopChannel ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StopChannelRequest req;
    req.set_channel_id(1);
    retrovue::air::v1::StopChannelResponse resp;
    ASSERT_TRUE(stub->StopChannel(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok());
  }

  // --- Status after stop should be STOPPING (terminal) ---
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.state(), retrovue::air::v1::SESSION_STATE_STOPPING);
  }

  srv.server->Shutdown();
  reader.join();
  ::close(listen_fd);
  ::unlink(uds_path.c_str());
  EXPECT_GT(total_read.load(), 0);
}

// Direct test of lifecycle observer on a standalone AirSession. Runs
// without gRPC; exercises only the observer + state machine.
TEST(LifecycleObserverTest, FiresOnEveryTransitionInExpectedOrder) {
  const std::string input = ResolveSampleA();
  if (!FixtureExists(input)) {
    GTEST_SKIP() << "SampleA not found";
  }

  // Create a socketpair for the session's output; reader drains to /dev/null.
  int fds[2];
  ASSERT_EQ(::socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
  std::atomic<bool> reader_running{true};
  std::thread reader([&]() {
    uint8_t buf[4096];
    while (reader_running.load()) {
      ssize_t n = ::read(fds[0], buf, sizeof(buf));
      if (n <= 0) break;
    }
  });

  std::mutex events_mu;
  std::vector<StateTransitionEvent> events;

  {
    AirSession session;
    session.SetLifecycleObserver([&](const StateTransitionEvent& e) {
      std::lock_guard<std::mutex> lk(events_mu);
      events.push_back(e);
    });

    ChannelCanonical canonical{
        .video = VideoCanonical{.width = 968, .height = 720,
                                .frame_rate = {30000, 1001},
                                .pixel_format = PixelFormat::kYuv420p},
        .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};

    ASSERT_TRUE(session.AttachOutput(fds[1]));
    ASSERT_TRUE(session.AssignContent(input, canonical));
    ASSERT_TRUE(session.OpenAir());

    // Wait for OnAir.
    for (int i = 0; i < 50; ++i) {
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
      if (session.State() == SessionState::OnAir) break;
    }
    EXPECT_EQ(session.State(), SessionState::OnAir);

    session.Close();
  }

  reader_running.store(false);
  ::close(fds[0]);
  reader.join();

  // Expect at least: Warming -> Ready -> OnAir -> Stopping.
  // (Warming is entered first from the default-constructed state, which
  // happens to also be Warming — TransitionTo is a no-op in that case.
  // The observable sequence starts with Ready or OnAir depending on
  // whether the default-to-Warming was suppressed.)
  std::vector<SessionState> transitions;
  {
    std::lock_guard<std::mutex> lk(events_mu);
    for (const auto& e : events) transitions.push_back(e.to);
  }
  ASSERT_GE(transitions.size(), 3u)
      << "expected >=3 transitions (Ready, OnAir, Stopping); got "
      << transitions.size();
  // Ensure Ready, OnAir, and Stopping all appear in order.
  auto find_idx = [&](SessionState s) -> int {
    for (int i = 0; i < (int)transitions.size(); ++i)
      if (transitions[i] == s) return i;
    return -1;
  };
  const int ri = find_idx(SessionState::Ready);
  const int oi = find_idx(SessionState::OnAir);
  const int si = find_idx(SessionState::Stopping);
  EXPECT_GE(ri, 0);
  EXPECT_GE(oi, 0);
  EXPECT_GE(si, 0);
  if (ri >= 0 && oi >= 0) EXPECT_LT(ri, oi);
  if (oi >= 0 && si >= 0) EXPECT_LT(oi, si);
}

}  // namespace
}  // namespace retrovue::air
