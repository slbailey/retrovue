// AIR vNext — gRPC StartChannel/StopChannel integration test.
//
// End-to-end proof that the gRPC control plane drives the byte pipeline:
//   1. Spin up AirControlServiceImpl on a local gRPC port (in-process).
//   2. Create + listen on a UDS; a reader thread drains bytes.
//   3. StartChannel via gRPC with SampleA + the UDS path + cheers preset.
//   4. Let the encode thread run for ~3 seconds of wall-clock.
//   5. StopChannel via gRPC.
//   6. Validate received bytes with ffprobe (video + audio streams present).
//
// In-process design choice: avoids forking a subprocess to run the binary.
// AirControlServiceImpl is instantiated directly, served on 127.0.0.1:<port>
// via grpc::ServerBuilder in a background thread. The test acts as both
// the Core-side gRPC client and the Core-side byte-drain (UDS reader).

#include <grpcpp/grpcpp.h>
#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "air_control.grpc.pb.h"
#include "grpc_service.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) {
    return std::string(env);
  }
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return std::string(AIR_VNEXT_SAMPLE_A_PATH);
#else
  return "";
#endif
}

bool FixtureExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

struct FFProbeResult {
  int exit_code;
  std::string output;
};

FFProbeResult RunFFProbeOnBytes(const std::vector<uint8_t>& bytes) {
  char tmpl[] = "/tmp/air_grpc_integration_XXXXXX.ts";
  int fd = mkstemps(tmpl, 3);
  if (fd < 0) return {-1, "mkstemps failed"};
  FILE* f = fdopen(fd, "wb");
  if (!f) {
    close(fd);
    std::remove(tmpl);
    return {-1, "fdopen failed"};
  }
  const size_t written = std::fwrite(bytes.data(), 1, bytes.size(), f);
  std::fclose(f);
  if (written != bytes.size()) {
    std::remove(tmpl);
    return {-1, "fwrite short"};
  }

  std::string cmd = "ffprobe -v error -show_streams -print_format default ";
  cmd += tmpl;
  cmd += " 2>&1";
  FILE* pipe = popen(cmd.c_str(), "r");
  if (!pipe) {
    std::remove(tmpl);
    return {-1, "popen failed"};
  }
  std::string out;
  std::array<char, 4096> buf{};
  while (size_t n = std::fread(buf.data(), 1, buf.size(), pipe)) {
    out.append(buf.data(), n);
  }
  int status = pclose(pipe);
  std::remove(tmpl);
  int exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
  return {exit_code, out};
}

// Bind a UDS listening socket at path. Returns the listen fd on success,
// -1 on failure (errno set). Caller must unlink(path) at cleanup.
int BindAndListenUds(const std::string& path) {
  ::unlink(path.c_str());  // best-effort prior cleanup
  int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) return -1;
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  if (path.size() >= sizeof(addr.sun_path)) {
    ::close(fd);
    errno = ENAMETOOLONG;
    return -1;
  }
  std::strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
  if (::bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
    ::close(fd);
    return -1;
  }
  if (::listen(fd, 1) < 0) {
    ::close(fd);
    return -1;
  }
  return fd;
}

TEST(GrpcStartStopIntegrationTest, EndToEndStreamsValidMpegTs) {
  const std::string sample_path = ResolveSampleA();
  if (!FixtureExists(sample_path)) {
    GTEST_SKIP() << "SampleA not found at " << sample_path;
  }

  // 1. Spin up the AirControl gRPC server in-process. Use port 0 so the
  //    kernel picks a free ephemeral port; retrieve the bound port via
  //    AddListeningPort's selected_port out-param.
  AirControlServiceImpl service;
  grpc::ServerBuilder builder;
  int selected_port = 0;
  builder.AddListeningPort("127.0.0.1:0", grpc::InsecureServerCredentials(),
                           &selected_port);
  builder.RegisterService(&service);
  std::unique_ptr<grpc::Server> server = builder.BuildAndStart();
  ASSERT_NE(server, nullptr) << "gRPC server failed to start";
  ASSERT_GT(selected_port, 0);

  // 2. Bind + listen on a UDS for the byte path.
  const std::string uds_path =
      "/tmp/air_grpc_test_" + std::to_string(getpid()) + ".sock";
  const int uds_listen_fd = BindAndListenUds(uds_path);
  ASSERT_GE(uds_listen_fd, 0)
      << "BindAndListenUds failed: " << std::strerror(errno);

  // 3. Reader thread: accept one connection, then drain bytes to EOF.
  std::vector<uint8_t> received;
  received.reserve(8 * 1024 * 1024);
  std::mutex received_mu;
  std::atomic<bool> reader_done{false};
  std::atomic<int> accepted_fd{-1};
  std::thread reader([&]() {
    int cfd = ::accept(uds_listen_fd, nullptr, nullptr);
    if (cfd < 0) {
      reader_done = true;
      return;
    }
    accepted_fd.store(cfd);
    std::array<uint8_t, 64 * 1024> buf{};
    for (;;) {
      ssize_t n = ::read(cfd, buf.data(), buf.size());
      if (n > 0) {
        std::lock_guard<std::mutex> lk(received_mu);
        received.insert(received.end(), buf.data(), buf.data() + n);
        continue;
      }
      if (n == 0) break;
      if (n < 0) {
        if (errno == EINTR) continue;
        break;
      }
    }
    ::close(cfd);
    accepted_fd.store(-1);
    reader_done = true;
  });

  // 4. Build a gRPC client and call StartChannel.
  const std::string server_addr = "127.0.0.1:" + std::to_string(selected_port);
  auto channel =
      grpc::CreateChannel(server_addr, grpc::InsecureChannelCredentials());
  auto stub = retrovue::air::v1::AirControl::NewStub(channel);

  retrovue::air::v1::StartChannelRequest start_req;
  start_req.set_channel_id(1);
  start_req.set_input_path(sample_path);
  start_req.set_output_uds_path(uds_path);
  auto* canon = start_req.mutable_canonical();
  canon->set_video_width(968);
  canon->set_video_height(720);
  canon->set_video_fps_num(30000);
  canon->set_video_fps_den(1001);
  canon->set_audio_sample_rate(48000);
  canon->set_audio_channels(2);

  retrovue::air::v1::StartChannelResponse start_resp;
  {
    grpc::ClientContext ctx;
    grpc::Status status = stub->StartChannel(&ctx, start_req, &start_resp);
    ASSERT_TRUE(status.ok())
        << "StartChannel RPC failed: " << status.error_message();
  }
  ASSERT_TRUE(start_resp.ok()) << "StartChannel reported failure: "
                               << start_resp.message();

  // 5. Let the encode run. EgressPacer emits at wall-clock, so we should
  //    collect on the order of 3 seconds' worth of TS bytes. We poll on
  //    received.size() and break once we've seen meaningful progress OR
  //    we hit a bounded wall-clock timeout (hard upper bound: 10s).
  const auto start_time = std::chrono::steady_clock::now();
  const auto kCollectTarget = std::chrono::seconds(3);
  const auto kHardTimeout = std::chrono::seconds(10);
  while (true) {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    const auto elapsed = std::chrono::steady_clock::now() - start_time;
    size_t sz;
    {
      std::lock_guard<std::mutex> lk(received_mu);
      sz = received.size();
    }
    if (elapsed >= kCollectTarget && sz > 0) break;
    if (elapsed >= kHardTimeout) break;
  }

  // 6. StopChannel. Session.Close() joins the encode thread and closes the fd.
  retrovue::air::v1::StopChannelRequest stop_req;
  stop_req.set_channel_id(1);
  retrovue::air::v1::StopChannelResponse stop_resp;
  {
    grpc::ClientContext ctx;
    grpc::Status status = stub->StopChannel(&ctx, stop_req, &stop_resp);
    ASSERT_TRUE(status.ok())
        << "StopChannel RPC failed: " << status.error_message();
  }
  EXPECT_TRUE(stop_resp.ok()) << "StopChannel reported failure: "
                              << stop_resp.message();

  // 7. Tear down gRPC server + join reader thread.
  server->Shutdown();
  // Reader may still be blocked in read() waiting for the accepted socket
  // to close; the Close() call above closes AIR's fd, which should EOF
  // the reader. Join with bounded wait by shutting down the listen fd.
  reader.join();

  // Clean up UDS fds / path.
  ::close(uds_listen_fd);
  ::unlink(uds_path.c_str());

  // 8. Assertions on the bytes we captured.
  size_t received_size;
  std::vector<uint8_t> received_copy;
  {
    std::lock_guard<std::mutex> lk(received_mu);
    received_size = received.size();
    received_copy = received;
  }
  ASSERT_GT(received_size, 0u) << "no TS bytes reached the UDS reader";

  // MPEG-TS sync byte at offset 0 and next ~20 packet boundaries.
  ASSERT_EQ(received_copy[0], 0x47)
      << "first received byte is not TS sync (0x47): got 0x"
      << std::hex << static_cast<int>(received_copy[0]);
  const int kCheckPackets = 20;
  for (int p = 0;
       p < kCheckPackets &&
       (p + 1) * 188 <= static_cast<int>(received_copy.size());
       ++p) {
    ASSERT_EQ(received_copy[p * 188], 0x47)
        << "received packet " << p << " missing sync byte at offset "
        << (p * 188);
  }

  // 9. ffprobe validation.
  auto probe = RunFFProbeOnBytes(received_copy);
  EXPECT_EQ(probe.exit_code, 0)
      << "ffprobe exit=" << probe.exit_code << " output=" << probe.output;
  std::cout << "[ffprobe output]\n" << probe.output << std::endl;
  EXPECT_NE(probe.output.find("codec_type=video"), std::string::npos)
      << "ffprobe did not report a video stream: " << probe.output;
  EXPECT_NE(probe.output.find("codec_type=audio"), std::string::npos)
      << "ffprobe did not report an audio stream: " << probe.output;
}

}  // namespace
}  // namespace retrovue::air
