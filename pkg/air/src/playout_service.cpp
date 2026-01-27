// Repository: Retrovue-playout
// Component: PlayoutControl gRPC Service Implementation
// Purpose: Implements the PlayoutControl service interface for channel lifecycle management.
// Copyright (c) 2025 RetroVue

#include "playout_service.h"

#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <iostream>
#include <optional>
#include <string>
#include <thread>
#include <utility>

#if defined(__linux__) || defined(__APPLE__)
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace retrovue
{
  namespace playout
  {

    namespace
    {
      constexpr char kApiVersion[] = "1.0.0";
      constexpr char kPhase80Payload[] = "HELLO\n";
      constexpr size_t kPhase80PayloadLen = 6;
    } // namespace

    // Phase 8.0/8.1: per-channel stream writer (UDS client; HELLO then optional ffmpeg TS)
    struct PlayoutControlImpl::StreamWriterState
    {
      int fd = -1;
      std::atomic<bool> stop{false};
      std::thread writer_thread;
      bool close_fd_on_exit = true;
      std::string asset_path;
#if defined(__linux__) || defined(__APPLE__)
      pid_t ffmpeg_pid = -1;
#else
      int ffmpeg_pid = -1;
#endif

      void HelloLoop()
      {
        while (!stop.load(std::memory_order_acquire) && fd >= 0)
        {
#if defined(__linux__) || defined(__APPLE__)
          ssize_t n = write(fd, kPhase80Payload, kPhase80PayloadLen);
          if (n < 0 || static_cast<size_t>(n) != kPhase80PayloadLen)
            break;
#endif
          std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        if (close_fd_on_exit && fd >= 0)
        {
#if defined(__linux__) || defined(__APPLE__)
          close(fd);
#endif
          fd = -1;
        }
      }

#if defined(__linux__) || defined(__APPLE__)
      void FfmpegLoop()
      {
        const int out_fd = fd;
        fd = -1;
        if (out_fd < 0 || asset_path.empty())
          return;
        pid_t pid = fork();
        if (pid < 0)
          return;
        if (pid == 0)
        {
          dup2(out_fd, STDOUT_FILENO);
          close(out_fd);
          execlp("ffmpeg", "ffmpeg", "-re", "-i", asset_path.c_str(),
                 "-f", "mpegts", "pipe:1", nullptr);
          _exit(127);
        }
        ffmpeg_pid = pid;
        close(out_fd);
        int status = 0;
        waitpid(pid, &status, 0);
        ffmpeg_pid = -1;
      }
#else
      void FfmpegLoop() {}
#endif

      ~StreamWriterState()
      {
        stop.store(true, std::memory_order_release);
#if defined(__linux__) || defined(__APPLE__)
        if (ffmpeg_pid > 0)
        {
          kill(ffmpeg_pid, SIGTERM);
          waitpid(ffmpeg_pid, nullptr, 0);
          ffmpeg_pid = -1;
        }
#endif
        if (writer_thread.joinable())
          writer_thread.join();
        if (fd >= 0)
        {
#if defined(__linux__) || defined(__APPLE__)
          close(fd);
#endif
          fd = -1;
        }
      }
    };

    PlayoutControlImpl::PlayoutControlImpl(
        std::shared_ptr<runtime::PlayoutController> controller)
        : controller_(std::move(controller))
    {
      std::cout << "[PlayoutControlImpl] Service initialized (API version: " << kApiVersion << ")" << std::endl;
    }

    PlayoutControlImpl::~PlayoutControlImpl()
    {
      std::cout << "[PlayoutControlImpl] Service shutting down" << std::endl;
      std::lock_guard<std::mutex> lock(stream_mutex_);
      for (auto it = stream_writers_.begin(); it != stream_writers_.end(); ++it)
        it->second.reset();
      stream_writers_.clear();
    }

    grpc::Status PlayoutControlImpl::StartChannel(grpc::ServerContext *context,
                                                  const StartChannelRequest *request,
                                                  StartChannelResponse *response)
    {
      const int32_t channel_id = request->channel_id();
      const std::string &plan_handle = request->plan_handle();
      const int32_t port = request->port();
      // UDS path is optional - check if field exists in proto
      std::optional<std::string> uds_path = std::nullopt;

      std::cout << "[StartChannel] Request received: channel_id=" << channel_id
                << ", plan_handle=" << plan_handle << ", port=" << port << std::endl;

      // Delegate to controller
      auto result = controller_->StartChannel(channel_id, plan_handle, port, uds_path);
      
      response->set_success(result.success);
      response->set_message(result.message);
      
      if (!result.success) {
        grpc::StatusCode code = grpc::StatusCode::INTERNAL;
        if (result.message.find("already") != std::string::npos) {
          code = grpc::StatusCode::ALREADY_EXISTS;
        } else if (result.message.find("not found") != std::string::npos) {
          code = grpc::StatusCode::NOT_FOUND;
        }
        return grpc::Status(code, result.message);
      }
      
      std::cout << "[StartChannel] Channel " << channel_id << " started successfully" << std::endl;
      return grpc::Status::OK;
    }

    grpc::Status PlayoutControlImpl::UpdatePlan(grpc::ServerContext *context,
                                                const UpdatePlanRequest *request,
                                                UpdatePlanResponse *response)
    {
      const int32_t channel_id = request->channel_id();
      const std::string &plan_handle = request->plan_handle();

      std::cout << "[UpdatePlan] Request received: channel_id=" << channel_id
                << ", plan_handle=" << plan_handle << std::endl;

      // Delegate to controller
      auto result = controller_->UpdatePlan(channel_id, plan_handle);
      
      response->set_success(result.success);
      response->set_message(result.message);
      
      if (!result.success) {
        grpc::StatusCode code = grpc::StatusCode::INTERNAL;
        if (result.message.find("not found") != std::string::npos) {
          code = grpc::StatusCode::NOT_FOUND;
        }
        return grpc::Status(code, result.message);
      }
      
      std::cout << "[UpdatePlan] Channel " << channel_id << " plan updated successfully" << std::endl;
      return grpc::Status::OK;
    }

    grpc::Status PlayoutControlImpl::StopChannel(grpc::ServerContext *context,
                                                 const StopChannelRequest *request,
                                                 StopChannelResponse *response)
    {
      const int32_t channel_id = request->channel_id();
      std::cout << "[StopChannel] Request received: channel_id=" << channel_id << std::endl;

      // Phase 8.0: StopChannel implies detach
      {
        std::lock_guard<std::mutex> lock(stream_mutex_);
        DetachStreamLocked(channel_id, true);
      }
      
      // Delegate to controller
      auto result = controller_->StopChannel(channel_id);
      
      response->set_success(result.success);
      response->set_message(result.message);
      
      if (!result.success) {
        grpc::StatusCode code = grpc::StatusCode::INTERNAL;
        if (result.message.find("not found") != std::string::npos) {
          code = grpc::StatusCode::NOT_FOUND;
        }
        return grpc::Status(code, result.message);
      }
      
      std::cout << "[StopChannel] Channel " << channel_id << " stopped successfully" << std::endl;
      return grpc::Status::OK;
    }

    grpc::Status PlayoutControlImpl::GetVersion(grpc::ServerContext *context,
                                                const ApiVersionRequest *request,
                                                ApiVersion *response)
    {
      std::cout << "[GetVersion] Request received" << std::endl;
      response->set_version(kApiVersion);
      std::cout << "[GetVersion] Returning version: " << kApiVersion << std::endl;
      return grpc::Status::OK;
    }

    grpc::Status PlayoutControlImpl::LoadPreview(grpc::ServerContext *context,
                                                 const LoadPreviewRequest *request,
                                                 LoadPreviewResponse *response)
    {
      const int32_t channel_id = request->channel_id();
      const std::string &asset_path = request->asset_path();
      const int64_t start_offset_ms = request->start_offset_ms();
      const int64_t hard_stop_time_ms = request->hard_stop_time_ms();

      std::cout << "[LoadPreview] Request received: channel_id=" << channel_id
                << ", asset_path=" << asset_path << std::endl;

      // Delegate to controller (start_offset_ms, hard_stop_time_ms accepted for proto/Phase 4; not interpreted in 6A.0)
      auto result = controller_->LoadPreview(channel_id, asset_path, start_offset_ms, hard_stop_time_ms);
      
      response->set_success(result.success);
      response->set_message(result.message);
      response->set_shadow_decode_started(result.shadow_decode_started);
      // Phase 6A.0: error semantics via response success=false, not gRPC Status
      if (!result.success) {
        std::cout << "[LoadPreview] Channel " << channel_id << " preview load failed" << std::endl;
        return grpc::Status::OK;
      }
      
      std::cout << "[LoadPreview] Channel " << channel_id
                << " preview load " << (result.shadow_decode_started ? "succeeded" : "failed")
                << std::endl;
      return grpc::Status::OK;
    }

    grpc::Status PlayoutControlImpl::SwitchToLive(grpc::ServerContext *context,
                                                  const SwitchToLiveRequest *request,
                                                  SwitchToLiveResponse *response)
    {
      const int32_t channel_id = request->channel_id();

      std::cout << "[SwitchToLive] Request received: channel_id=" << channel_id << std::endl;

      // Delegate to controller
      auto result = controller_->SwitchToLive(channel_id);
      
      response->set_success(result.success);
      response->set_message(result.message);
      response->set_pts_contiguous(result.pts_contiguous);
      response->set_live_start_pts(result.live_start_pts);
      // Phase 6A.0: error semantics via response success=false, not gRPC Status
      if (!result.success) {
        std::cout << "[SwitchToLive] Channel " << channel_id << " switch failed" << std::endl;
        return grpc::Status::OK;
      }

      // Phase 8.1: route ffmpeg MPEG-TS to attached stream
      {
        std::lock_guard<std::mutex> lock(stream_mutex_);
        auto it = stream_writers_.find(channel_id);
        std::optional<std::string> path = controller_->GetLiveAssetPath(channel_id);
        if (it != stream_writers_.end() && it->second && path && !path->empty())
        {
          StreamWriterState* state = it->second.get();
          state->close_fd_on_exit = false;
          state->stop.store(true, std::memory_order_release);
          if (state->writer_thread.joinable())
            state->writer_thread.join();
          state->asset_path = *path;
          state->writer_thread = std::thread(&StreamWriterState::FfmpegLoop, state);
          std::cout << "[SwitchToLive] Channel " << channel_id << " streaming TS from " << *path << std::endl;
        }
      }
      
      std::cout << "[SwitchToLive] Channel " << channel_id
                << " switch " << (result.success ? "succeeded" : "failed")
                << ", PTS contiguous: " << std::boolalpha << result.pts_contiguous << std::endl;
      return grpc::Status::OK;
    }

    void PlayoutControlImpl::DetachStreamLocked(int32_t channel_id, bool force)
    {
      (void)force;
      auto it = stream_writers_.find(channel_id);
      if (it == stream_writers_.end())
        return;
      it->second.reset();
      stream_writers_.erase(it);
      std::cout << "[Phase8] Detached stream for channel " << channel_id << std::endl;
    }

    grpc::Status PlayoutControlImpl::AttachStream(grpc::ServerContext* context,
                                                  const AttachStreamRequest* request,
                                                  AttachStreamResponse* response)
    {
      (void)context;
      const int32_t channel_id = request->channel_id();
      const auto transport = request->transport();
      const std::string endpoint = request->endpoint();
      const bool replace_existing = request->replace_existing();

      std::cout << "[AttachStream] Request received: channel_id=" << channel_id
                << ", transport=" << static_cast<int>(transport)
                << ", endpoint=" << endpoint << std::endl;

#if defined(__linux__) || defined(__APPLE__)
      if (transport != StreamTransport::STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET)
      {
        response->set_success(false);
        response->set_message("Phase 8.0: only UNIX_DOMAIN_SOCKET transport is supported");
        return grpc::Status::OK;
      }

      std::lock_guard<std::mutex> lock(stream_mutex_);
      auto it = stream_writers_.find(channel_id);
      if (it != stream_writers_.end())
      {
        if (!replace_existing)
        {
          response->set_success(false);
          response->set_message("Already attached; set replace_existing=true to replace");
          return grpc::Status::OK;
        }
        it->second.reset();
        stream_writers_.erase(it);
      }

      int fd = socket(AF_UNIX, SOCK_STREAM, 0);
      if (fd < 0)
      {
        response->set_success(false);
        response->set_message("socket(AF_UNIX) failed");
        return grpc::Status::OK;
      }

      struct sockaddr_un addr;
      std::memset(&addr, 0, sizeof(addr));
      addr.sun_family = AF_UNIX;
      if (endpoint.size() >= sizeof(addr.sun_path))
      {
        close(fd);
        response->set_success(false);
        response->set_message("Endpoint path too long");
        return grpc::Status::OK;
      }
      std::strncpy(addr.sun_path, endpoint.c_str(), sizeof(addr.sun_path) - 1);
      addr.sun_path[sizeof(addr.sun_path) - 1] = '\0';

      socklen_t len = sizeof(addr);
      if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), len) < 0)
      {
        int e = errno;
        close(fd);
        response->set_success(false);
        response->set_message("connect() failed: " + std::string(strerror(e)));
        return grpc::Status::OK;
      }

      auto state = std::make_unique<StreamWriterState>();
      state->fd = fd;
      state->writer_thread = std::thread(&StreamWriterState::HelloLoop, state.get());
      stream_writers_[channel_id] = std::move(state);

      response->set_success(true);
      response->set_message("Attached");
      response->set_negotiated_transport(StreamTransport::STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET);
      response->set_negotiated_endpoint(endpoint);
      std::cout << "[AttachStream] Channel " << channel_id << " attached to " << endpoint << std::endl;
      return grpc::Status::OK;
#else
      (void)endpoint;
      (void)replace_existing;
      response->set_success(false);
      response->set_message("Phase 8.0 UDS not implemented on this platform");
      return grpc::Status::OK;
#endif
    }

    grpc::Status PlayoutControlImpl::DetachStream(grpc::ServerContext* context,
                                                  const DetachStreamRequest* request,
                                                  DetachStreamResponse* response)
    {
      (void)context;
      const int32_t channel_id = request->channel_id();
      const bool force = request->force();
      std::cout << "[DetachStream] Request received: channel_id=" << channel_id << ", force=" << force << std::endl;

      std::lock_guard<std::mutex> lock(stream_mutex_);
      auto it = stream_writers_.find(channel_id);
      if (it == stream_writers_.end())
      {
        response->set_success(true);
        response->set_message("Not attached (idempotent)");
        return grpc::Status::OK;
      }
      DetachStreamLocked(channel_id, force);
      response->set_success(true);
      response->set_message("Detached");
      return grpc::Status::OK;
    }


  } // namespace playout
} // namespace retrovue
