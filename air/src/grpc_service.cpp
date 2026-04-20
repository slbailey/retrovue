// AIR vNext — gRPC AirControl service implementation.
//
// Contract: this file contains NO business logic. It only:
//   1. Serializes StartChannel/StopChannel with a mutex.
//   2. Connects the UDS fd that Core already has bound + listening on.
//   3. Dispatches to AirSession's three-phase startup + Close.
//
// Failure reporting convention:
//   - Protocol-level failures (malformed request, session-state violations,
//     UDS connect failures, pipeline construction failures) are reported via
//     response.ok=false and a human-readable response.message. The gRPC
//     status itself returns OK — the RPC succeeded, the start did not.
//   - The one exception is session-state violation (already on-air, or
//     already has content): that returns FAILED_PRECONDITION at the gRPC
//     level, because the client has called things in the wrong order.

#include "grpc_service.hpp"

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <string>

#include "channel_canonical.hpp"

namespace retrovue::air {

namespace {

// Connect to a Unix Domain Socket path as a SOCK_STREAM client. Returns a
// valid fd on success, or -1 on failure (errno set). Caller owns the fd.
int ConnectUnixStream(const std::string& path, std::string* err_out) {
  if (path.empty()) {
    *err_out = "output_uds_path is empty";
    return -1;
  }
  int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  if (fd < 0) {
    *err_out = std::string("socket(AF_UNIX) failed: ") + std::strerror(errno);
    return -1;
  }
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  if (path.size() >= sizeof(addr.sun_path)) {
    ::close(fd);
    *err_out = "output_uds_path too long for sockaddr_un";
    return -1;
  }
  std::strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
  if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
    const int e = errno;
    ::close(fd);
    *err_out = std::string("connect(") + path +
               ") failed: " + std::strerror(e);
    return -1;
  }
  return fd;
}

ChannelCanonical BuildCanonicalFromProto(
    const retrovue::air::v1::ChannelCanonical& proto) {
  ChannelCanonical c{};
  c.video.width = proto.video_width();
  c.video.height = proto.video_height();
  c.video.frame_rate.num = proto.video_fps_num();
  c.video.frame_rate.den = proto.video_fps_den();
  c.video.pixel_format = PixelFormat::kYuv420p;
  c.audio.sample_rate = proto.audio_sample_rate();
  c.audio.channels = proto.audio_channels();
  return c;
}

}  // namespace

grpc::Status AirControlServiceImpl::StartChannel(
    grpc::ServerContext* /*context*/,
    const retrovue::air::v1::StartChannelRequest* request,
    retrovue::air::v1::StartChannelResponse* response) {
  std::lock_guard<std::mutex> lock(mu_);

  // 1. Session-state preconditions. Single session per process.
  if (session_.IsOnAir() || session_.HasContent() || session_.HasOutput()) {
    const std::string msg = "session already active";
    response->set_ok(false);
    response->set_message(msg);
    return grpc::Status(grpc::StatusCode::FAILED_PRECONDITION, msg);
  }

  // 2. Connect the byte-path UDS. Core has bound + is listening.
  std::string connect_err;
  const int fd = ConnectUnixStream(request->output_uds_path(), &connect_err);
  if (fd < 0) {
    response->set_ok(false);
    response->set_message(connect_err);
    return grpc::Status::OK;
  }

  // 3. AttachOutput (phase 1).
  if (!session_.AttachOutput(fd)) {
    ::close(fd);
    response->set_ok(false);
    response->set_message("AttachOutput failed");
    return grpc::Status::OK;
  }

  // 4. AssignContent (phase 2).
  const ChannelCanonical canonical = BuildCanonicalFromProto(request->canonical());
  if (!session_.AssignContent(request->input_path(), canonical)) {
    session_.Close();  // resets fd + unique_ptrs for a clean retry.
    response->set_ok(false);
    response->set_message("AssignContent failed for input_path=" +
                          request->input_path());
    return grpc::Status::OK;
  }

  // 5. OpenAir (phase 3).
  if (!session_.OpenAir()) {
    session_.Close();
    response->set_ok(false);
    response->set_message("OpenAir failed");
    return grpc::Status::OK;
  }

  response->set_ok(true);
  response->set_message("");
  return grpc::Status::OK;
}

grpc::Status AirControlServiceImpl::StopChannel(
    grpc::ServerContext* /*context*/,
    const retrovue::air::v1::StopChannelRequest* /*request*/,
    retrovue::air::v1::StopChannelResponse* response) {
  std::lock_guard<std::mutex> lock(mu_);
  session_.Close();  // idempotent
  response->set_ok(true);
  response->set_message("");
  return grpc::Status::OK;
}

}  // namespace retrovue::air
