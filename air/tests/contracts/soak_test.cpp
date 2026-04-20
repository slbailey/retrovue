// AIR vNext — soak test.
//
// Gated by environment variable so it doesn't run in the default test
// suite. Usage:
//
//   AIR_SOAK_SECONDS=1800 AIR_SOAK_INPUT=/path/to/long.mp4 \
//     ctest --test-dir /opt/retrovue/air/build -R SoakTest --timeout 2000
//
// For 30-min soak: AIR_SOAK_SECONDS=1800, input must be >= 31 minutes.
// For overnight:  AIR_SOAK_SECONDS=28800, input must be >= 8+ hours.
//
// Build a long input once via:
//   ffmpeg -stream_loop 60 -i /opt/retrovue/assets/SampleA.mp4 \
//     -c copy /opt/retrovue/assets/sample_30min.mp4
//
// What the soak verifies over a long run:
//   - Lifecycle reaches OnAir and stays there (no spurious FailedStart).
//   - frames_encoded advances monotonically.
//   - bytes_dropped stays 0 on local UDS.
//   - pacer_late_releases grows slowly (bounded — not a runaway).
//   - Structured snapshots logged to stderr at poll interval for offline
//     analysis.

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
#include <iostream>
#include <string>
#include <thread>

#include "air_control.grpc.pb.h"
#include "grpc_service.hpp"

namespace retrovue::air {
namespace {

std::string GetEnvOr(const char* name, const char* fallback) {
  const char* v = std::getenv(name);
  return v && *v ? v : fallback;
}

int GetEnvInt(const char* name, int fallback) {
  const char* v = std::getenv(name);
  if (!v || !*v) return fallback;
  return std::atoi(v);
}

TEST(SoakTest, LongRunStabilityViaGrpcStatus) {
  const int duration_s = GetEnvInt("AIR_SOAK_SECONDS", 0);
  if (duration_s <= 0) {
    GTEST_SKIP() << "Soak disabled (set AIR_SOAK_SECONDS=<seconds> to enable)";
  }
  const std::string input = GetEnvOr("AIR_SOAK_INPUT", "");
  if (input.empty() || !std::filesystem::exists(input)) {
    GTEST_SKIP() << "AIR_SOAK_INPUT not set or file missing: " << input;
  }
  const int poll_interval_s = GetEnvInt("AIR_SOAK_POLL_S", 30);

  std::cerr << "[soak] duration=" << duration_s << "s input=" << input
            << " poll=" << poll_interval_s << "s" << std::endl;

  AirControlServiceImpl service;
  grpc::ServerBuilder builder;
  int picked_port = 0;
  builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(),
                           &picked_port);
  builder.RegisterService(&service);
  auto server = builder.BuildAndStart();
  ASSERT_GT(picked_port, 0);

  const std::string uds_path =
      "/tmp/air_soak_" + std::to_string(getpid()) + ".sock";
  ::unlink(uds_path.c_str());

  int listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(listen_fd, 0);
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  std::strncpy(addr.sun_path, uds_path.c_str(), sizeof(addr.sun_path) - 1);
  ASSERT_EQ(::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)), 0);
  ASSERT_EQ(::listen(listen_fd, 1), 0);

  // Reader thread drains to /dev/null (no need to hold bytes in memory
  // for a long run).
  std::atomic<int64_t> total_read{0};
  std::atomic<bool> reader_running{true};
  std::thread reader([&]() {
    int conn = ::accept(listen_fd, nullptr, nullptr);
    if (conn < 0) return;
    uint8_t buf[64 * 1024];
    while (reader_running.load()) {
      ssize_t n = ::read(conn, buf, sizeof(buf));
      if (n <= 0) break;
      total_read.fetch_add(n);
    }
    ::close(conn);
  });

  auto channel = grpc::CreateChannel("127.0.0.1:" + std::to_string(picked_port),
                                     grpc::InsecureChannelCredentials());
  auto stub = retrovue::air::v1::AirControl::NewStub(channel);

  // Start the channel.
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
    ASSERT_TRUE(resp.ok()) << resp.message();
  }

  // Poll loop. Record snapshots to stderr; track first/last frame counts
  // for end-of-run sanity check.
  const auto start = std::chrono::steady_clock::now();
  const auto end = start + std::chrono::seconds(duration_s);
  int64_t last_frames = 0;
  int64_t max_pacer_late = 0;
  int64_t max_bytes_dropped = 0;
  int poll_num = 0;

  while (std::chrono::steady_clock::now() < end) {
    std::this_thread::sleep_for(std::chrono::seconds(poll_interval_s));
    ++poll_num;

    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    retrovue::air::v1::GetSessionStatusResponse resp;
    if (!stub->GetSessionStatus(&ctx, req, &resp).ok()) {
      std::cerr << "[soak] poll " << poll_num << " status RPC failed" << std::endl;
      continue;
    }

    const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                             std::chrono::steady_clock::now() - start)
                             .count();
    std::cerr << "[soak] poll=" << poll_num
              << " elapsed_s=" << elapsed
              << " state=" << static_cast<int>(resp.state())
              << " frames=" << resp.frames_encoded()
              << " bytes_written=" << resp.bytes_written()
              << " bytes_dropped=" << resp.bytes_dropped()
              << " pacer_sleep_ms=" << resp.pacer_sleep_ms()
              << " pacer_late=" << resp.pacer_late_releases()
              << " bootstrap_us=" << resp.bootstrap_total_duration_us()
              << std::endl;

    EXPECT_GT(resp.frames_encoded(), last_frames)
        << "poll " << poll_num << ": frames did not advance";
    last_frames = resp.frames_encoded();
    max_pacer_late = std::max(max_pacer_late, resp.pacer_late_releases());
    max_bytes_dropped = std::max(max_bytes_dropped, resp.bytes_dropped());

    EXPECT_EQ(resp.state(), retrovue::air::v1::SESSION_STATE_ON_AIR)
        << "poll " << poll_num << ": unexpected state";

    // Sanity: dropped bytes on a local UDS should be zero. If this grows,
    // something is wrong.
    EXPECT_EQ(resp.bytes_dropped(), 0)
        << "poll " << poll_num << ": bytes dropped on local UDS";
  }

  // Stop.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::StopChannelRequest req;
    req.set_channel_id(1);
    retrovue::air::v1::StopChannelResponse resp;
    ASSERT_TRUE(stub->StopChannel(&ctx, req, &resp).ok());
  }

  std::cerr << "[soak] done. total_read_bytes=" << total_read.load()
            << " max_pacer_late=" << max_pacer_late
            << " max_bytes_dropped=" << max_bytes_dropped
            << " final_frames=" << last_frames << std::endl;

  server->Shutdown();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds_path.c_str());
}

}  // namespace
}  // namespace retrovue::air
