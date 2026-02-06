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

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "retrovue/blockplan/RealTimeExecution.hpp"
#include "retrovue/blockplan/ContinuousOutputExecutionEngine.hpp"
#include "retrovue/blockplan/SerialBlockExecutionEngine.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/MpegTSOutputSink.h"
#include "retrovue/output/OutputBus.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/renderer/ProgramOutput.h"
#include "retrovue/runtime/PlayoutEngine.h"
#include "retrovue/runtime/ProgramFormat.h"
#include "retrovue/telemetry/MetricsExporter.h"

// Phase 8: Map C++ ResultCode enum to proto ResultCode enum
namespace {
  retrovue::playout::ResultCode MapResultCode(retrovue::runtime::ResultCode code) {
    switch (code) {
      case retrovue::runtime::ResultCode::kOk:
        return retrovue::playout::RESULT_CODE_OK;
      case retrovue::runtime::ResultCode::kNotReady:
        return retrovue::playout::RESULT_CODE_NOT_READY;
      case retrovue::runtime::ResultCode::kRejectedBusy:
        return retrovue::playout::RESULT_CODE_REJECTED_BUSY;
      case retrovue::runtime::ResultCode::kProtocolViolation:
        return retrovue::playout::RESULT_CODE_PROTOCOL_VIOLATION;
      case retrovue::runtime::ResultCode::kFailed:
        return retrovue::playout::RESULT_CODE_FAILED;
      default:
        return retrovue::playout::RESULT_CODE_UNSPECIFIED;
    }
  }
}  // namespace

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

    PlayoutControlImpl::PlayoutControlImpl(
        std::shared_ptr<runtime::PlayoutInterface> interface,
        bool control_surface_only,
        const std::string& forensic_dump_dir)
        : interface_(std::move(interface)),
          control_surface_only_(control_surface_only),
          forensic_dump_dir_(forensic_dump_dir)
    {
      std::cout << "[PlayoutControlImpl] Service initialized (API version: " << kApiVersion
                << ", control_surface_only=" << control_surface_only_;
      if (!forensic_dump_dir_.empty()) {
        std::cout << ", forensic_dump_dir=" << forensic_dump_dir_;
      }
      std::cout << ")" << std::endl;
    }

    PlayoutControlImpl::~PlayoutControlImpl()
    {
      std::cout << "[PlayoutControlImpl] Service shutting down" << std::endl;
      std::lock_guard<std::mutex> lock(stream_mutex_);
      for (auto& [channel_id, state] : stream_states_)
      {
        if (state)
        {
          state->stop.store(true, std::memory_order_release);
          if (state->hello_thread.joinable())
          {
            state->hello_thread.join();
          }
          if (state->fd >= 0)
          {
#if defined(__linux__) || defined(__APPLE__)
            close(state->fd);
#endif
          }
        }
      }
      stream_states_.clear();
    }

    void PlayoutControlImpl::HelloLoop(StreamState* state)
    {
#if defined(__linux__) || defined(__APPLE__)
      while (!state->stop.load(std::memory_order_acquire) && state->fd >= 0)
      {
        ssize_t n = write(state->fd, kPhase80Payload, kPhase80PayloadLen);
        if (n < 0 || static_cast<size_t>(n) != kPhase80PayloadLen)
          break;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
#else
      (void)state;
#endif
    }

    // Convert proto BlockPlan to internal FedBlock type
    PlayoutControlImpl::BlockPlanBlock PlayoutControlImpl::ProtoToBlock(const BlockPlan& proto)
    {
      BlockPlanBlock block;
      block.block_id = proto.block_id();
      block.channel_id = proto.channel_id();
      block.start_utc_ms = proto.start_utc_ms();
      block.end_utc_ms = proto.end_utc_ms();

      for (const auto& seg : proto.segments()) {
        BlockPlanBlock::Segment s;
        s.segment_index = seg.segment_index();
        s.asset_uri = seg.asset_uri();
        s.asset_start_offset_ms = seg.asset_start_offset_ms();
        s.segment_duration_ms = seg.segment_duration_ms();
        block.segments.push_back(s);
      }
      return block;
    }

    // ========================================================================
    // BlockPlanExecutionThread logic has been extracted to:
    //   SerialBlockExecutionEngine (blockplan/SerialBlockExecutionEngine.cpp)
    // This is a mechanical extraction — no logic changes.
    // ========================================================================

    grpc::Status PlayoutControlImpl::StartChannel(grpc::ServerContext *context,
                                                  const StartChannelRequest *request,
                                                  StartChannelResponse *response)
    {
      const int32_t channel_id = request->channel_id();
      const std::string &plan_handle = request->plan_handle();
      const int32_t port = request->port();
      const std::string &program_format_json = request->program_format_json();
      std::optional<std::string> uds_path = std::nullopt;

      std::cout << "[StartChannel] Request received: channel_id=" << channel_id
                << ", plan_handle=" << plan_handle << ", port=" << port
                << ", program_format_json=" << program_format_json << std::endl;

      auto result = interface_->StartChannel(channel_id, plan_handle, port, uds_path, program_format_json);

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

      auto result = interface_->UpdatePlan(channel_id, plan_handle);

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

      // Phase 9.0: StopChannel implies detach (OutputBus::DetachSink is called by engine)
      {
        std::lock_guard<std::mutex> lock(stream_mutex_);
        DetachStreamLocked(channel_id, true);
      }

      auto result = interface_->StopChannel(channel_id);

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
      // Frame-indexed execution (INV-FRAME-001/002/003)
      const int64_t start_frame = request->start_frame();
      const int64_t frame_count = request->frame_count();
      const int32_t fps_numerator = request->fps_numerator();
      const int32_t fps_denominator = request->fps_denominator();

      // INV-FRAME-003: Reject if fps not provided (denominator 0 is invalid)
      if (fps_denominator <= 0) {
        response->set_success(false);
        response->set_message("INV-FRAME-003 violation: fps_denominator must be > 0");
        response->set_result_code(RESULT_CODE_PROTOCOL_VIOLATION);
        std::cout << "[LoadPreview] Rejected: fps_denominator=" << fps_denominator << std::endl;
        return grpc::Status::OK;
      }

      std::cout << "[LoadPreview] Request received: channel_id=" << channel_id
                << ", asset_path=" << asset_path
                << ", start_frame=" << start_frame
                << ", frame_count=" << frame_count
                << ", fps=" << fps_numerator << "/" << fps_denominator << std::endl;

      auto result = interface_->LoadPreview(channel_id, asset_path, start_frame, frame_count, fps_numerator, fps_denominator);

      response->set_success(result.success);
      response->set_message(result.message);
      response->set_shadow_decode_started(result.shadow_decode_started);
      response->set_result_code(MapResultCode(result.result_code));  // Phase 8: Typed result

      if (!result.success) {
        std::cout << "[LoadPreview] Channel " << channel_id << " preview load failed: " << result.message
                  << " (result_code=" << static_cast<int>(result.result_code) << ")" << std::endl;
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
      const int64_t target_boundary_time_ms = request->target_boundary_time_ms();  // P11C-001 (0 = legacy)
      const int64_t issued_at_time_ms = request->issued_at_time_ms();  // P11D-012: INV-LEADTIME-MEASUREMENT-001

      std::cout << "[SwitchToLive] Request received: channel_id=" << channel_id << std::endl;

      auto result = interface_->SwitchToLive(channel_id, target_boundary_time_ms, issued_at_time_ms);

      response->set_success(result.success);
      response->set_message(result.message);
      response->set_pts_contiguous(result.pts_contiguous);
      response->set_live_start_pts(result.live_start_pts);
      response->set_result_code(MapResultCode(result.result_code));  // Phase 8: Typed result
      if (result.switch_completion_time_ms != 0) {
        response->set_switch_completion_time_ms(result.switch_completion_time_ms);  // P11B-001
      }
      if (!result.violation_reason.empty()) {
        response->set_violation_reason(result.violation_reason);  // P11D-004
      }

      if (!result.success) {
        std::cout << "[SwitchToLive] Channel " << channel_id << " switch not complete (result_code="
                  << static_cast<int>(result.result_code) << ")" << std::endl;
        return grpc::Status::OK;
      }

      // INV-FINALIZE-LIVE: Create sink (if FD exists), attach, wire program_output
      // Same path for normal completion and watcher auto-completion.
      {
        std::lock_guard<std::mutex> lock(stream_mutex_);
        TryAttachSinkForChannel(channel_id);
      }

      std::cout << "[SwitchToLive] Channel " << channel_id
                << " switch " << (result.success ? "succeeded" : "failed")
                << ", PTS contiguous: " << std::boolalpha << result.pts_contiguous << std::endl;
      return grpc::Status::OK;
    }

    void PlayoutControlImpl::TryAttachSinkForChannel(int32_t channel_id)
    {
      // Requires stream_mutex_ held
      auto it = stream_states_.find(channel_id);
      if (it == stream_states_.end() || !it->second || it->second->fd < 0)
        return;

      StreamState* state = it->second.get();

      if (control_surface_only_ || interface_->IsOutputSinkAttached(channel_id))
        return;

      // INV-P9-IMMEDIATE-SINK-ATTACH: Attach sink as soon as client connects.
      // Professional broadcast systems attach immediately and emit pad frames
      // until real content is available. This avoids circular dependencies
      // where SwitchToLive waits for sink output but sink waits for SwitchToLive.
      // We only need ProgramFormat (from StartChannel), not live_asset_path.

      auto program_format_opt = interface_->GetProgramFormat(channel_id);
      if (!program_format_opt) {
        std::cerr << "[TryAttachSinkForChannel] Failed to get ProgramFormat for channel "
                  << channel_id << std::endl;
        return;
      }

      const auto& program_format = *program_format_opt;
      playout_sinks::mpegts::MpegTSPlayoutSinkConfig config;
      config.stub_mode = false;
      config.persistent_mux = false;
      config.target_fps = program_format.GetFrameRateAsDouble();
      config.target_width = program_format.video.width;
      config.target_height = program_format.video.height;
      config.bitrate = 5000000;
      config.gop_size = 30;

      std::string sink_name = "channel-" + std::to_string(channel_id) + "-mpeg-ts";
      auto sink = std::make_unique<output::MpegTSOutputSink>(state->fd, config, sink_name);

      // P9-OPT-002: Wire up MetricsExporter for steady-state telemetry
      if (auto metrics = interface_->GetMetricsExporter()) {
        sink->SetMetricsExporter(metrics, channel_id);
      }

      // Forensic dump: auto-enable if --forensic-dump-dir was specified
      if (!forensic_dump_dir_.empty()) {
        std::string dump_path = forensic_dump_dir_ + "/channel_" + std::to_string(channel_id) + ".ts";
        sink->EnableForensicDump(dump_path);
      }

      auto attach_result = interface_->AttachOutputSink(channel_id, std::move(sink));
      if (attach_result.success) {
        std::cout << "[TryAttachSinkForChannel] MpegTSOutputSink attached for channel "
                  << channel_id << std::endl;
        interface_->ConnectRendererToOutputBus(channel_id);
        std::cout << "[TryAttachSinkForChannel] INV-FINALIZE-LIVE: output wired for channel "
                  << channel_id << std::endl;
      } else {
        std::cerr << "[TryAttachSinkForChannel] Failed to attach: " << attach_result.message
                  << std::endl;
      }
    }

    void PlayoutControlImpl::DetachStreamLocked(int32_t channel_id, bool force)
    {
      auto it = stream_states_.find(channel_id);
      if (it == stream_states_.end())
        return;

      StreamState* state = it->second.get();
      if (!state)
        return;

      // Detach sink from OutputBus if attached (query engine for state)
      if (interface_->IsOutputSinkAttached(channel_id))
      {
        // Disconnect program output from OutputBus first
        interface_->DisconnectRendererFromOutputBus(channel_id);
        interface_->DetachOutputSink(channel_id);
        std::cout << "[DetachStream] OutputSink detached for channel " << channel_id << std::endl;
      }

      // Stop HelloLoop thread if running
      state->stop.store(true, std::memory_order_release);
      if (state->hello_thread.joinable())
      {
        state->hello_thread.join();
      }

      // Close FD
      if (state->fd >= 0)
      {
#if defined(__linux__) || defined(__APPLE__)
        close(state->fd);
#endif
        state->fd = -1;
      }

      stream_states_.erase(it);
      std::cout << "[DetachStream] Stream detached for channel " << channel_id << std::endl;
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
        response->set_message("Phase 9.0: only UNIX_DOMAIN_SOCKET transport is supported");
        return grpc::Status::OK;
      }

      std::lock_guard<std::mutex> lock(stream_mutex_);
      auto it = stream_states_.find(channel_id);
      if (it != stream_states_.end())
      {
        if (!replace_existing)
        {
          response->set_success(false);
          response->set_message("Already attached; set replace_existing=true to replace");
          return grpc::Status::OK;
        }
        DetachStreamLocked(channel_id, true);
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

      // Phase 9.0: Store stream state (FD owned by gRPC layer)
      // Sink will be created and attached on SwitchToLive (not here)
      // gRPC layer does NOT track output runtime state - only transport (FD)
      auto state = std::make_unique<StreamState>();
      state->fd = fd;

      // In control_surface_only mode, start HelloLoop for backward compatibility
      if (control_surface_only_)
      {
        state->stop.store(false, std::memory_order_release);
        state->hello_thread = std::thread(&PlayoutControlImpl::HelloLoop, state.get());
      }

      stream_states_[channel_id] = std::move(state);

      // INV-FINALIZE-LIVE: Late attach path — if channel is already live, wire sink now
      TryAttachSinkForChannel(channel_id);

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
      response->set_message("Phase 9.0 UDS not implemented on this platform");
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
      auto it = stream_states_.find(channel_id);
      if (it == stream_states_.end())
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

    // ==========================================================================
    // BlockPlan Mode RPC Implementations
    // ==========================================================================

    grpc::Status PlayoutControlImpl::StartBlockPlanSession(
        grpc::ServerContext* context,
        const StartBlockPlanSessionRequest* request,
        StartBlockPlanSessionResponse* response)
    {
      (void)context;
      const int32_t channel_id = request->channel_id();

      std::cout << "[StartBlockPlanSession] Request: channel_id=" << channel_id
                << ", block_a=" << request->block_a().block_id()
                << ", block_b=" << request->block_b().block_id()
                << std::endl;

      std::lock_guard<std::mutex> lock(blockplan_mutex_);

      // Check if session already active
      if (blockplan_session_ && blockplan_session_->active) {
        response->set_success(false);
        response->set_message("BlockPlan session already active");
        response->set_result_code(BLOCKPLAN_RESULT_ALREADY_ACTIVE);
        return grpc::Status::OK;
      }

      // Check stream is attached
      {
        std::lock_guard<std::mutex> stream_lock(stream_mutex_);
        if (stream_states_.find(channel_id) == stream_states_.end()) {
          response->set_success(false);
          response->set_message("Stream not attached - call AttachStream first");
          response->set_result_code(BLOCKPLAN_RESULT_STREAM_NOT_ATTACHED);
          return grpc::Status::OK;
        }
      }

      // Validate blocks are contiguous
      const auto& block_a = request->block_a();
      const auto& block_b = request->block_b();
      if (block_a.end_utc_ms() != block_b.start_utc_ms()) {
        response->set_success(false);
        response->set_message("Blocks not contiguous: block_a.end != block_b.start");
        response->set_result_code(BLOCKPLAN_RESULT_NOT_CONTIGUOUS);
        return grpc::Status::OK;
      }

      // Create session state
      blockplan_session_ = std::make_unique<BlockPlanSessionState>();
      blockplan_session_->channel_id = channel_id;
      blockplan_session_->active = true;
      blockplan_session_->blocks_executed = 0;
      blockplan_session_->blocks_fed = 0;

      // Get the FD from stream state for output
      {
        std::lock_guard<std::mutex> stream_lock(stream_mutex_);
        auto it = stream_states_.find(channel_id);
        if (it != stream_states_.end() && it->second && it->second->fd >= 0)
        {
          blockplan_session_->fd = it->second->fd;
        }
        else
        {
          response->set_success(false);
          response->set_message("Stream FD not available");
          response->set_result_code(BLOCKPLAN_RESULT_STREAM_NOT_ATTACHED);
          blockplan_session_.reset();
          return grpc::Status::OK;
        }
      }

      // Parse program format from JSON (if provided)
      const std::string& format_json = request->program_format_json();
      if (!format_json.empty()) {
        auto format = runtime::ProgramFormat::FromJson(format_json);
        if (format.has_value()) {
          blockplan_session_->width = format->video.width;
          blockplan_session_->height = format->video.height;
          blockplan_session_->fps = format->GetFrameRateAsDouble();
          if (blockplan_session_->fps <= 0.0) {
            blockplan_session_->fps = 30.0;  // Fallback
          }
        } else {
          std::cerr << "[StartBlockPlanSession] Failed to parse program_format_json" << std::endl;
        }
      }

      // Seed the block queue with both blocks
      {
        std::lock_guard<std::mutex> qlock(blockplan_session_->queue_mutex);
        blockplan_session_->block_queue.push_back(ProtoToBlock(block_a));
        blockplan_session_->block_queue.push_back(ProtoToBlock(block_b));
      }

      std::cout << "[StartBlockPlanSession] Session started for channel " << channel_id
                << " with blocks: " << block_a.block_id() << ", " << block_b.block_id()
                << ", fd=" << blockplan_session_->fd
                << ", format=" << blockplan_session_->width << "x" << blockplan_session_->height
                << "@" << blockplan_session_->fps << "fps"
                << std::endl;

      // ========================================================================
      // ENGINE SELECTION: Select execution engine based on execution mode
      // INV-SERIAL-BLOCK-EXECUTION: Only kSerialBlock is implemented
      // ========================================================================
      constexpr auto kExecutionMode = blockplan::PlayoutExecutionMode::kSerialBlock;

      if (kExecutionMode == blockplan::PlayoutExecutionMode::kSerialBlock) {
        // Create callbacks that delegate to gRPC event emission
        blockplan::SerialBlockExecutionEngine::Callbacks callbacks;
        callbacks.on_block_completed = [this](const blockplan::FedBlock& block, int64_t final_ct_ms) {
          EmitBlockCompleted(blockplan_session_.get(), block, final_ct_ms);
        };
        callbacks.on_session_ended = [this](const std::string& reason) {
          EmitSessionEnded(blockplan_session_.get(), reason);
        };

        blockplan_session_->engine = std::make_unique<blockplan::SerialBlockExecutionEngine>(
            blockplan_session_.get(), std::move(callbacks));

        // Wire engine metrics to Prometheus export
        if (auto metrics_exporter = interface_->GetMetricsExporter()) {
          auto* engine_ptr = static_cast<blockplan::SerialBlockExecutionEngine*>(
              blockplan_session_->engine.get());
          metrics_exporter->RegisterCustomMetricsProvider(
              "serial_block_engine",
              [engine_ptr]() { return engine_ptr->GenerateMetricsText(); });
        }

        blockplan_session_->engine->Start();
      } else if (kExecutionMode == blockplan::PlayoutExecutionMode::kContinuousOutput) {
        // P3.0: ContinuousOutput — pad-only skeleton
        blockplan::ContinuousOutputExecutionEngine::Callbacks callbacks;
        callbacks.on_block_completed = [this](const blockplan::FedBlock& block, int64_t final_ct_ms) {
          EmitBlockCompleted(blockplan_session_.get(), block, final_ct_ms);
        };
        callbacks.on_session_ended = [this](const std::string& reason) {
          EmitSessionEnded(blockplan_session_.get(), reason);
        };

        blockplan_session_->engine = std::make_unique<blockplan::ContinuousOutputExecutionEngine>(
            blockplan_session_.get(), std::move(callbacks));

        // Wire engine metrics to Prometheus export
        if (auto metrics_exporter = interface_->GetMetricsExporter()) {
          auto* engine_ptr = static_cast<blockplan::ContinuousOutputExecutionEngine*>(
              blockplan_session_->engine.get());
          metrics_exporter->RegisterCustomMetricsProvider(
              "continuous_output_engine",
              [engine_ptr]() { return engine_ptr->GenerateMetricsText(); });
        }

        blockplan_session_->engine->Start();
      } else {
        std::cerr << "[StartBlockPlanSession] FATAL: execution_model="
                  << blockplan::PlayoutExecutionModeToString(kExecutionMode)
                  << " is not implemented" << std::endl;
        blockplan_session_.reset();
        response->set_success(false);
        response->set_message("Execution mode not implemented: "
                              + std::string(blockplan::PlayoutExecutionModeToString(kExecutionMode)));
        response->set_result_code(BLOCKPLAN_RESULT_NO_SESSION);
        return grpc::Status::OK;
      }

      response->set_success(true);
      response->set_message("BlockPlan session started");
      response->set_result_code(BLOCKPLAN_RESULT_OK);
      return grpc::Status::OK;
    }

    grpc::Status PlayoutControlImpl::FeedBlockPlan(
        grpc::ServerContext* context,
        const FeedBlockPlanRequest* request,
        FeedBlockPlanResponse* response)
    {
      (void)context;
      const int32_t channel_id = request->channel_id();
      const auto& block = request->block();

      std::cout << "[FeedBlockPlan] Request: channel_id=" << channel_id
                << ", block=" << block.block_id()
                << std::endl;

      std::lock_guard<std::mutex> lock(blockplan_mutex_);

      if (!blockplan_session_ || !blockplan_session_->active) {
        response->set_success(false);
        response->set_message("No active BlockPlan session");
        response->set_result_code(BLOCKPLAN_RESULT_NO_SESSION);
        return grpc::Status::OK;
      }

      if (blockplan_session_->channel_id != channel_id) {
        response->set_success(false);
        response->set_message("Channel ID mismatch");
        response->set_result_code(BLOCKPLAN_RESULT_NO_SESSION);
        return grpc::Status::OK;
      }

      // Add block to queue and notify execution thread
      bool queue_full = false;
      {
        std::lock_guard<std::mutex> qlock(blockplan_session_->queue_mutex);

        // Check queue capacity (2-block window)
        if (blockplan_session_->block_queue.size() >= 2) {
          queue_full = true;
        } else {
          blockplan_session_->block_queue.push_back(ProtoToBlock(block));
          blockplan_session_->blocks_fed++;
        }
      }

      // Notify execution thread that a block is available
      if (!queue_full) {
        blockplan_session_->queue_cv.notify_one();
      }

      std::cout << "[FeedBlockPlan] Fed block " << block.block_id()
                << " (total fed: " << blockplan_session_->blocks_fed << ")"
                << (queue_full ? " [QUEUE_FULL]" : "")
                << std::endl;

      response->set_success(!queue_full);
      response->set_message(queue_full ? "Queue full" : "Block fed");
      response->set_result_code(queue_full ? BLOCKPLAN_RESULT_QUEUE_FULL : BLOCKPLAN_RESULT_OK);
      response->set_queue_full(queue_full);
      return grpc::Status::OK;
    }

    grpc::Status PlayoutControlImpl::StopBlockPlanSession(
        grpc::ServerContext* context,
        const StopBlockPlanSessionRequest* request,
        StopBlockPlanSessionResponse* response)
    {
      (void)context;
      const int32_t channel_id = request->channel_id();
      const std::string& reason = request->reason();

      std::cout << "[StopBlockPlanSession] Request: channel_id=" << channel_id
                << ", reason=" << reason
                << std::endl;

      std::lock_guard<std::mutex> lock(blockplan_mutex_);

      if (!blockplan_session_ || !blockplan_session_->active) {
        response->set_success(true);  // Idempotent
        response->set_message("No active session (idempotent)");
        response->set_final_ct_ms(0);
        response->set_blocks_executed(0);
        return grpc::Status::OK;
      }

      // Unregister engine metrics provider before stopping
      if (auto metrics_exporter = interface_->GetMetricsExporter()) {
        metrics_exporter->UnregisterCustomMetricsProvider("serial_block_engine");
        metrics_exporter->UnregisterCustomMetricsProvider("continuous_output_engine");
      }

      // Stop execution engine (joins thread internally)
      if (blockplan_session_->engine) {
        blockplan_session_->engine->Stop();
        blockplan_session_->engine.reset();
      }

      int64_t final_ct = blockplan_session_->final_ct_ms;
      int32_t blocks_executed = blockplan_session_->blocks_executed;

      blockplan_session_->active = false;
      blockplan_session_.reset();

      std::cout << "[StopBlockPlanSession] Session stopped: reason=" << reason
                << ", final_ct=" << final_ct
                << ", blocks_executed=" << blocks_executed
                << std::endl;

      response->set_success(true);
      response->set_message("Session stopped");
      response->set_final_ct_ms(final_ct);
      response->set_blocks_executed(blocks_executed);
      return grpc::Status::OK;
    }

    // ==========================================================================
    // SubscribeBlockEvents: Server-streaming RPC for boundary-driven feeding
    // ==========================================================================

    grpc::Status PlayoutControlImpl::SubscribeBlockEvents(
        grpc::ServerContext* context,
        const SubscribeBlockEventsRequest* request,
        grpc::ServerWriter<BlockEvent>* writer)
    {
      const int32_t channel_id = request->channel_id();

      std::cout << "[SubscribeBlockEvents] Subscriber connected for channel "
                << channel_id << std::endl;

      // Add subscriber to session
      {
        std::lock_guard<std::mutex> lock(blockplan_mutex_);
        if (!blockplan_session_ || !blockplan_session_->active ||
            blockplan_session_->channel_id != channel_id) {
          std::cout << "[SubscribeBlockEvents] No active session for channel "
                    << channel_id << std::endl;
          return grpc::Status(grpc::StatusCode::NOT_FOUND,
                              "No active BlockPlan session for channel");
        }

        std::lock_guard<std::mutex> event_lock(blockplan_session_->event_mutex);
        blockplan_session_->event_subscribers.push_back(writer);
      }

      // Wait for session to end or client to disconnect
      // The stream stays open until the session ends or client cancels
      while (!context->IsCancelled()) {
        {
          std::lock_guard<std::mutex> lock(blockplan_mutex_);
          if (!blockplan_session_ || !blockplan_session_->active) {
            // Session ended, stream will close
            break;
          }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }

      // Remove subscriber
      {
        std::lock_guard<std::mutex> lock(blockplan_mutex_);
        if (blockplan_session_) {
          std::lock_guard<std::mutex> event_lock(blockplan_session_->event_mutex);
          auto& subs = blockplan_session_->event_subscribers;
          subs.erase(std::remove(subs.begin(), subs.end(), writer), subs.end());
        }
      }

      std::cout << "[SubscribeBlockEvents] Subscriber disconnected for channel "
                << channel_id << std::endl;
      return grpc::Status::OK;
    }

    void PlayoutControlImpl::EmitBlockCompleted(
        BlockPlanSessionState* state,
        const BlockPlanBlock& block,
        int64_t final_ct_ms)
    {
      std::lock_guard<std::mutex> lock(state->event_mutex);

      BlockEvent event;
      event.set_channel_id(state->channel_id);

      auto* completed = event.mutable_block_completed();
      completed->set_block_id(block.block_id);
      completed->set_block_start_utc_ms(block.start_utc_ms);
      completed->set_block_end_utc_ms(block.end_utc_ms);
      completed->set_final_ct_ms(final_ct_ms);
      completed->set_blocks_executed_total(state->blocks_executed);

      std::cout << "[EmitBlockCompleted] block_id=" << block.block_id
                << ", blocks_executed=" << state->blocks_executed
                << ", subscribers=" << state->event_subscribers.size()
                << std::endl;

      // Send to all subscribers (remove failed ones)
      std::vector<grpc::ServerWriter<BlockEvent>*> failed;
      for (auto* writer : state->event_subscribers) {
        if (!writer->Write(event)) {
          failed.push_back(writer);
        }
      }
      for (auto* w : failed) {
        state->event_subscribers.erase(
            std::remove(state->event_subscribers.begin(),
                        state->event_subscribers.end(), w),
            state->event_subscribers.end());
      }
    }

    void PlayoutControlImpl::EmitSessionEnded(
        BlockPlanSessionState* state,
        const std::string& reason)
    {
      std::lock_guard<std::mutex> lock(state->event_mutex);

      BlockEvent event;
      event.set_channel_id(state->channel_id);

      auto* ended = event.mutable_session_ended();
      ended->set_reason(reason);
      ended->set_final_ct_ms(state->final_ct_ms);
      ended->set_blocks_executed_total(state->blocks_executed);

      std::cout << "[EmitSessionEnded] reason=" << reason
                << ", blocks_executed=" << state->blocks_executed
                << ", subscribers=" << state->event_subscribers.size()
                << std::endl;

      // Send to all subscribers
      for (auto* writer : state->event_subscribers) {
        writer->Write(event);
      }
      state->event_subscribers.clear();
    }

  } // namespace playout
} // namespace retrovue
