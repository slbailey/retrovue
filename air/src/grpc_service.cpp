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
  //
  // Phase A compatibility: prefer seed_block if provided; otherwise fall back
  // to the legacy input_path field. In Phase B the queue model will consume
  // seed_block as the initial active block and expect SupplyBlock calls for
  // successors. For now the only effect is which string becomes input_path.
  std::string content_path = request->input_path();
  ChannelCanonical canonical = BuildCanonicalFromProto(request->canonical());
  if (request->has_seed_block()) {
    const auto& seed = request->seed_block();
    content_path = seed.asset_uri();
    // seed_block.canonical, when set, overrides the top-level canonical.
    if (seed.has_canonical()) {
      canonical = BuildCanonicalFromProto(seed.canonical());
    }
  }
  if (!session_.AssignContent(content_path, canonical)) {
    session_.Close();  // resets fd + unique_ptrs for a clean retry.
    response->set_ok(false);
    response->set_message("AssignContent failed for input_path=" + content_path);
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

namespace {

retrovue::air::v1::SessionStateProto ToProto(SessionState s) {
  using P = retrovue::air::v1::SessionStateProto;
  switch (s) {
    case SessionState::Warming:     return P::SESSION_STATE_WARMING;
    case SessionState::Ready:       return P::SESSION_STATE_READY;
    case SessionState::OnAir:       return P::SESSION_STATE_ON_AIR;
    case SessionState::Stopping:    return P::SESSION_STATE_STOPPING;
    case SessionState::FailedStart: return P::SESSION_STATE_FAILED_START;
  }
  return P::SESSION_STATE_UNSPECIFIED;
}

}  // namespace

grpc::Status AirControlServiceImpl::GetSessionStatus(
    grpc::ServerContext* /*context*/,
    const retrovue::air::v1::GetSessionStatusRequest* /*request*/,
    retrovue::air::v1::GetSessionStatusResponse* response) {
  std::lock_guard<std::mutex> lock(mu_);
  // If nothing has ever been started (no output attached), return NONE.
  const bool has_session = session_.HasOutput() || session_.HasContent();
  if (!has_session && session_.State() == SessionState::Warming) {
    response->set_state(retrovue::air::v1::SESSION_STATE_NONE);
    return grpc::Status::OK;
  }
  response->set_state(ToProto(session_.State()));
  response->set_frames_encoded(session_.FramesEncoded());
  response->set_bytes_written(session_.BytesWritten());
  response->set_bytes_dropped(session_.BytesDropped());
  response->set_epipe_count(0);  // emitter-level; expose later if needed
  response->set_pacer_sleep_ms(session_.PacerSleepMs());
  response->set_pacer_late_releases(session_.PacerLateReleases());
  response->set_warming_duration_us(session_.WarmingDurationUs());
  response->set_bootstrap_total_duration_us(session_.BootstrapTotalDurationUs());
  response->set_failed_start_reason(session_.FailedStartReason());
  // Execution-queue diagnostics (Phase A: placeholders; populated in Phase B+).
  response->set_queue_depth(session_.HasContent() ? 1 : 0);
  response->set_pad_bridge_ms_total(0);
  response->set_seams_executed_total(0);
  response->set_revisions_accepted_total(0);
  response->set_revisions_rejected_total(0);
  return grpc::Status::OK;
}

// --- Execution queue handlers (Phase A: proto surface declared; semantics
// arrive in Phase B with the queue model and Phase C with SeamController).
// Stubs return UNIMPLEMENTED so callers see an honest "not yet implemented"
// rather than a silent success.

grpc::Status AirControlServiceImpl::SupplyBlock(
    grpc::ServerContext* /*context*/,
    const retrovue::air::v1::SupplyBlockRequest* /*request*/,
    retrovue::air::v1::SupplyBlockResponse* response) {
  response->set_ok(false);
  response->set_reason("UNIMPLEMENTED_PHASE_A");
  return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                      "SupplyBlock: Phase A stub — queue model lands in Phase B");
}

grpc::Status AirControlServiceImpl::PutBlockRevision(
    grpc::ServerContext* /*context*/,
    const retrovue::air::v1::PutBlockRevisionRequest* /*request*/,
    retrovue::air::v1::PutBlockRevisionResponse* response) {
  response->set_ok(false);
  response->set_reason("UNIMPLEMENTED_PHASE_A");
  return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                      "PutBlockRevision: Phase A stub");
}

grpc::Status AirControlServiceImpl::RetireBlock(
    grpc::ServerContext* /*context*/,
    const retrovue::air::v1::RetireBlockRequest* /*request*/,
    retrovue::air::v1::RetireBlockResponse* response) {
  response->set_ok(false);
  response->set_reason("UNIMPLEMENTED_PHASE_A");
  return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                      "RetireBlock: Phase A stub");
}

}  // namespace retrovue::air
