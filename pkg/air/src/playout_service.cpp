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
#include <queue>
#include <string>
#include <thread>
#include <utility>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

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

    // Phase 8.0/8.3/8.4: per-channel stream writer (UDS client).
    // One TS mux per channel per active stream session. Session = AttachStream → DetachStream/StopChannel.
    // Within a session: mux created once, FD fixed, no restart on segment boundaries. SwitchToLive swaps frame source only.
    struct PlayoutControlImpl::StreamWriterState
    {
      int fd = -1;
      std::atomic<bool> stop{false};
      std::thread writer_thread;
      bool close_fd_on_exit = true;
      std::string asset_path;
      int32_t channel_id = -1;
      std::shared_ptr<runtime::PlayoutController> controller;
      
      // Phase 8.9: Encoder pipeline persists for the entire channel lifetime
      // Created once when channel starts, destroyed only when channel stops
      std::unique_ptr<playout_sinks::mpegts::EncoderPipeline> encoder;
#if defined(__linux__) || defined(__APPLE__)
      pid_t ffmpeg_pid = -1;
#else
      int ffmpeg_pid = -1;
#endif

      // Phase 8.4: frame queue for TS mux (renderer thread enqueues, FfmpegLoop dequeues).
      std::mutex mux_queue_mutex;
      std::queue<buffer::Frame> mux_frame_queue;
      static constexpr size_t kMuxQueueMax = 30;

      // Phase 8.9: audio frame queue for TS mux
      std::mutex mux_audio_queue_mutex;
      std::queue<buffer::AudioFrame> mux_audio_frame_queue;
      static constexpr size_t kMuxAudioQueueMax = 30;

      void EnqueueFrameForMux(const buffer::Frame& frame)
      {
        std::lock_guard<std::mutex> lock(mux_queue_mutex);
        if (mux_frame_queue.size() >= kMuxQueueMax)
          mux_frame_queue.pop();
        mux_frame_queue.push(frame);
      }

      bool DequeueFrameForMux(buffer::Frame* out)
      {
        if (!out)
          return false;
        std::lock_guard<std::mutex> lock(mux_queue_mutex);
        if (mux_frame_queue.empty())
          return false;
        *out = std::move(mux_frame_queue.front());
        mux_frame_queue.pop();
        return true;
      }

      // Phase 8.9: Audio frame enqueue/dequeue
      void EnqueueAudioFrameForMux(const buffer::AudioFrame& audio_frame)
      {
        std::lock_guard<std::mutex> lock(mux_audio_queue_mutex);
        if (mux_audio_frame_queue.size() >= kMuxAudioQueueMax)
          mux_audio_frame_queue.pop();
        mux_audio_frame_queue.push(audio_frame);
      }

      bool DequeueAudioFrameForMux(buffer::AudioFrame* out)
      {
        if (!out)
          return false;
        std::lock_guard<std::mutex> lock(mux_audio_queue_mutex);
        if (mux_audio_frame_queue.empty())
          return false;
        *out = std::move(mux_audio_frame_queue.front());
        mux_audio_frame_queue.pop();
        return true;
      }

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
      // Phase 8.4: Persistent TS mux per session — one mux per channel per session, same FD; no PID/continuity reset within session.
      static int WriteToFdCallback(void* opaque, uint8_t* buf, int buf_size)
      {
        auto* s = static_cast<StreamWriterState*>(opaque);
        if (!s || s->fd < 0)
          return -1;
        ssize_t n = write(s->fd, buf, buf_size);
        return (n == static_cast<ssize_t>(buf_size)) ? buf_size : -1;
      }

      void FfmpegLoop()
      {
        (void)asset_path;
        (void)ffmpeg_pid;
        if (fd < 0)
          return;
        
        // Encoder should already be created and opened before this thread starts
        if (!encoder || !encoder->IsInitialized())
        {
          std::cerr << "[Phase8.4] Encoder not initialized for channel " << channel_id << std::endl;
          return;
        }
        
        std::cout << "[Phase8.4] Encoder loop started for channel " << channel_id << std::endl;
        bool had_frames_before = false;  // Track if we had frames before to detect switch
        while (!stop.load(std::memory_order_acquire) && fd >= 0)
        {
          // Phase 8.9: Process both video and audio frames
          bool processed_any = false;

          // Process video frame
          buffer::Frame frame;
          if (DequeueFrameForMux(&frame))
          {
            // Frame.metadata.pts is in microseconds; encoder expects 90kHz.
            const int64_t pts90k = (frame.metadata.pts * 90000) / 1'000'000;
            if (!encoder->encodeFrame(frame, pts90k))
            {
              // Encode failures are non-fatal - log and continue
              std::cerr << "[Phase8.4] Video encode failed for channel " << channel_id 
                        << ", continuing..." << std::endl;
            }
            processed_any = true;
            had_frames_before = true;
          }

          // Phase 8.9: Process audio frame
          buffer::AudioFrame audio_frame;
          if (DequeueAudioFrameForMux(&audio_frame))
          {
            // AudioFrame.pts_us is in microseconds; encoder expects 90kHz.
            const int64_t audio_pts90k = (audio_frame.pts_us * 90000) / 1'000'000;
            if (!encoder->encodeAudioFrame(audio_frame, audio_pts90k))
            {
              // Encode failures are non-fatal - log and continue
              std::cerr << "[Phase8.4] Audio encode failed for channel " << channel_id 
                        << ", continuing..." << std::endl;
            }
            processed_any = true;
            had_frames_before = true;
          }
          
          // Phase 8.9: If we had frames before but now both queues are empty,
          // we're likely switching producers. Flush encoder buffers to ensure
          // all audio from the previous producer is encoded.
          // Use a static counter to avoid flushing too frequently
          static int empty_iterations = 0;
          if (had_frames_before && !processed_any)
          {
            // Check if both queues are empty
            bool video_empty = mux_frame_queue.empty();
            bool audio_empty = false;
            {
              std::lock_guard<std::mutex> lock(mux_audio_queue_mutex);
              audio_empty = mux_audio_frame_queue.empty();
            }
            
            if (video_empty && audio_empty)
            {
              empty_iterations++;
              // Wait for several iterations to ensure it's really a switch, not just a brief gap
              if (empty_iterations >= 10) {  // ~50ms at 5ms sleep intervals
                std::cout << "[Phase8.4] Queues empty for " << empty_iterations 
                          << " iterations - flushing encoder buffers" << std::endl;
                encoder->flushAudio();
                had_frames_before = false;  // Reset after flush
                empty_iterations = 0;
              }
            }
            else
            {
              empty_iterations = 0;  // Reset if frames arrive
            }
          }
          else
          {
            empty_iterations = 0;  // Reset if we processed frames
          }

          if (!processed_any)
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        
        // Encoder is closed in destructor, not here
        std::cout << "[Phase8.4] Encoder loop stopped for channel " << channel_id << std::endl;
        if (controller && channel_id >= 0) {
          controller->UnregisterMuxFrameCallback(channel_id);
          controller->UnregisterMuxAudioFrameCallback(channel_id);
        }
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
        
        // Phase 8.9: Close encoder only when StreamWriterState is destroyed (channel teardown)
        if (encoder)
        {
          encoder->close();
          encoder.reset();
          std::cout << "[Phase8.4] Encoder closed for channel " << channel_id << std::endl;
        }
        
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
        std::shared_ptr<runtime::PlayoutController> controller,
        bool control_surface_only)
        : controller_(std::move(controller)),
          control_surface_only_(control_surface_only)
    {
      std::cout << "[PlayoutControlImpl] Service initialized (API version: " << kApiVersion
                << ", control_surface_only=" << control_surface_only_ << ")" << std::endl;
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
        std::cout << "[LoadPreview] Channel " << channel_id << " preview load failed: " << result.message << std::endl;
        return grpc::Status::OK;
      }
      
      std::cout << "[LoadPreview] Channel " << channel_id
                << " preview loaded successfully (shadow_decode_started="
                << std::boolalpha << result.shadow_decode_started << ")" << std::endl;
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

      // Phase 8.3/8.4: Switch is frame-source only. Encoder and TS mux stay alive across switches.
      // Engine has already stopped the old FrameProducer and atomically promoted preview → live.
      // Do NOT stop/join/restart the writer thread or reinitialize encoder/AVFormatContext/PTS.
      {
        std::lock_guard<std::mutex> lock(stream_mutex_);
        auto it = stream_writers_.find(channel_id);
        std::optional<std::string> path = controller_->GetLiveAssetPath(channel_id);
        if (it != stream_writers_.end() && it->second && path && !path->empty())
        {
          StreamWriterState* state = it->second.get();
          state->asset_path = *path;
          state->controller = controller_;
          if (!state->writer_thread.joinable()) {
            // First switch: create encoder once, then start writer thread (one per channel/session).
            state->close_fd_on_exit = false;
            state->stop.store(false, std::memory_order_release);
            
            // Phase 8.9: Create encoder once when channel starts (fixed audio/video profile)
            playout_sinks::mpegts::MpegTSPlayoutSinkConfig config;
            config.stub_mode = false;
            config.persistent_mux = true;
            config.target_fps = 30.0;
            config.target_width = 640;   // Phase 8.6: per-channel fixed resolution
            config.target_height = 480;
            config.bitrate = 5000000;
            config.gop_size = 30;
            
            state->encoder = std::make_unique<playout_sinks::mpegts::EncoderPipeline>(config);
            if (!state->encoder->open(config, state, &StreamWriterState::WriteToFdCallback))
            {
              std::cerr << "[Phase8.4] Encoder open failed for channel " << channel_id << std::endl;
              state->encoder.reset();
              return grpc::Status::OK;
            }
            std::cout << "[Phase8.4] Encoder created and opened for channel " << channel_id << std::endl;
            
            controller_->RegisterMuxFrameCallback(channel_id, [state](const buffer::Frame& f) {
              state->EnqueueFrameForMux(f);
            });
            // Phase 8.9: Register audio frame callback
            controller_->RegisterMuxAudioFrameCallback(channel_id, [state](const buffer::AudioFrame& af) {
              state->EnqueueAudioFrameForMux(af);
            });
            state->writer_thread = std::thread(&StreamWriterState::FfmpegLoop, state);
            std::cout << "[SwitchToLive] Channel " << channel_id << " streaming TS from " << *path << std::endl;
          } else {
            // Already running: encoder persists; engine already swapped producer. No PAT/PMT reset, same PCR/PTS.
            std::cout << "[SwitchToLive] Channel " << channel_id << " now streaming TS from " << *path 
                      << " (encoder persists)" << std::endl;
          }
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

      // Phase 8.4/8.6: This FD is the single write side for the channel. Phase 8.6: do not write
      // dummy bytes (HELLO) in normal mode; stream stays silent until SwitchToLive writes real MPEG-TS.
      // Phase 8.0 contract tests use --control-surface-only so we still start HelloLoop in that mode.
      auto state = std::make_unique<StreamWriterState>();
      state->fd = fd;
      state->channel_id = channel_id;
      if (control_surface_only_)
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
