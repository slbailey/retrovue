// Repository: Retrovue-playout
// Component: Serial Block Execution Engine
// Purpose: Mechanical extraction of BlockPlanExecutionThread into engine wrapper
// Contract Reference: INV-SERIAL-BLOCK-EXECUTION, INV-ONE-ENCODER-PER-SESSION
// Copyright (c) 2025 RetroVue
//
// This file contains the EXACT logic from PlayoutControlImpl::BlockPlanExecutionThread,
// extracted into SerialBlockExecutionEngine::Run(). No logic changes.

#include "retrovue/blockplan/SerialBlockExecutionEngine.hpp"

#include <chrono>
#include <iostream>
#include <memory>
#include <string>
#include <utility>

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockPlanValidator.hpp"
#include "retrovue/blockplan/RealTimeExecution.hpp"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

#if defined(__linux__) || defined(__APPLE__)
#include <unistd.h>
#endif

namespace retrovue::blockplan {

SerialBlockExecutionEngine::SerialBlockExecutionEngine(
    BlockPlanSessionContext* session_ctx,
    Callbacks callbacks)
    : ctx_(session_ctx),
      callbacks_(std::move(callbacks)) {
  metrics_.channel_id = session_ctx->channel_id;
}

SerialBlockMetrics SerialBlockExecutionEngine::SnapshotMetrics() const {
  std::lock_guard<std::mutex> lock(metrics_mutex_);
  return metrics_;
}

std::string SerialBlockExecutionEngine::GenerateMetricsText() const {
  std::lock_guard<std::mutex> lock(metrics_mutex_);
  return metrics_.GeneratePrometheusText();
}

SerialBlockExecutionEngine::~SerialBlockExecutionEngine() {
  Stop();
}

void SerialBlockExecutionEngine::Start() {
  if (started_) return;
  started_ = true;
  ctx_->stop_requested.store(false, std::memory_order_release);
  thread_ = std::thread(&SerialBlockExecutionEngine::Run, this);
}

void SerialBlockExecutionEngine::Stop() {
  if (!started_) return;
  ctx_->stop_requested.store(true, std::memory_order_release);
  ctx_->queue_cv.notify_all();
  if (thread_.joinable()) {
    thread_.join();
  }
  started_ = false;
}

// =============================================================================
// Run() — extracted verbatim from PlayoutControlImpl::BlockPlanExecutionThread
// =============================================================================
void SerialBlockExecutionEngine::Run() {
  std::cout << "[BlockPlanExecution] Starting execution thread for channel "
            << ctx_->channel_id << std::endl;

  // ========================================================================
  // INSTRUMENTATION: Session-level timing
  // ========================================================================
  auto session_start_time = std::chrono::steady_clock::now();
  std::string prev_block_id;  // Track for boundary gap measurement
  std::chrono::steady_clock::time_point prev_block_last_frame_time;
  bool have_prev_block_time = false;

  // Initialize session metrics
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.session_start_epoch_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        session_start_time.time_since_epoch()).count();
    metrics_.session_active = true;
  }

  // Track termination reason for SessionEnded event
  std::string termination_reason = "unknown";

  // ========================================================================
  // SESSION-LONG ENCODER: Create encoder ONCE for entire session
  // ========================================================================
  // This fixes DTS out-of-order warnings by:
  // - Maintaining continuity counters across blocks
  // - Preserving encoder/muxer state (DTS tracking)
  // - Not re-writing PAT/PMT per block
  // - Avoiding encoder priming delays at block boundaries
  // ========================================================================
  playout_sinks::mpegts::MpegTSPlayoutSinkConfig enc_config;
  enc_config.target_width = ctx_->width;
  enc_config.target_height = ctx_->height;
  enc_config.target_fps = ctx_->fps;
  enc_config.enable_audio = true;
  enc_config.gop_size = 90;      // I-frame every 3 seconds
  enc_config.bitrate = 2000000;  // 2 Mbps

  auto session_encoder = std::make_unique<playout_sinks::mpegts::EncoderPipeline>(enc_config);

  // Session write context for callback (must outlive encoder)
  struct SessionWriteContext {
    int fd;
    int64_t bytes_written;
    bool first_write_logged;
    std::chrono::steady_clock::time_point session_start;
    std::atomic<int64_t> first_ts_packet_ms{0};  // 0 = not yet written
  };
  SessionWriteContext write_ctx{ctx_->fd, 0, false, session_start_time};

  // Write callback (stateless - uses opaque pointer)
  auto write_callback = [](void* opaque, uint8_t* buf, int buf_size) -> int {
    auto* wctx = static_cast<SessionWriteContext*>(opaque);
#if defined(__linux__) || defined(__APPLE__)
    ssize_t written = write(wctx->fd, buf, static_cast<size_t>(buf_size));
    if (written > 0) {
      wctx->bytes_written += written;
      // ================================================================
      // INSTRUMENTATION: First TS write timing (tune-in latency)
      // ================================================================
      if (!wctx->first_write_logged) {
        wctx->first_write_logged = true;
        auto now = std::chrono::steady_clock::now();
        auto tunein_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now - wctx->session_start).count();
        std::cout << "[METRIC] tunein_first_ts_ms=" << tunein_ms << std::endl;
        wctx->first_ts_packet_ms.store(tunein_ms, std::memory_order_release);
      }
    }
    return static_cast<int>(written);
#else
    (void)buf;
    return buf_size;
#endif
  };

  // Open the session encoder
  auto encoder_open_start = std::chrono::steady_clock::now();
  if (!session_encoder->open(enc_config, &write_ctx, write_callback)) {
    std::cerr << "[BlockPlanExecution] Failed to open session encoder" << std::endl;
    if (callbacks_.on_session_ended) {
      callbacks_.on_session_ended("encoder_failed");
    }
    return;
  }
  auto encoder_open_end = std::chrono::steady_clock::now();
  auto encoder_open_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      encoder_open_end - encoder_open_start).count();
  std::cout << "[METRIC] encoder_open_ms=" << encoder_open_ms
            << " channel_id=" << ctx_->channel_id << std::endl;

  // Record encoder open metrics
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.encoder_open_count = 1;
    metrics_.encoder_open_ms = encoder_open_ms;
  }

  std::cout << "[BlockPlanExecution] Session encoder opened: "
            << ctx_->width << "x" << ctx_->height << " @ " << ctx_->fps << "fps"
            << std::endl;

  // ========================================================================
  // ARCHITECTURAL TELEMETRY: One-time per-session declaration (AIR side)
  // INV-SERIAL-BLOCK-EXECUTION: Declare execution mode from enum
  // ========================================================================
  constexpr auto kExecutionMode = PlayoutExecutionMode::kSerialBlock;
  std::cout << "[INV-PLAYOUT-AUTHORITY] channel_id=" << ctx_->channel_id
            << " | playout_path=blockplan"
            << " | encoder_scope=session"
            << " | execution_model=" << PlayoutExecutionModeToString(kExecutionMode)
            << " | format=" << ctx_->width << "x" << ctx_->height << "@" << ctx_->fps
            << std::endl;

  // Configure the real-time sink with shared encoder
  realtime::SinkConfig sink_config;
  sink_config.fd = ctx_->fd;
  sink_config.width = ctx_->width;
  sink_config.height = ctx_->height;
  sink_config.fps = ctx_->fps;
  // INV-PTS-MONOTONIC: Initialize PTS offset for session continuity across blocks
  sink_config.initial_pts_offset_90k = 0;
  // SESSION-LONG ENCODER: Share the encoder across all blocks
  sink_config.shared_encoder = session_encoder.get();

  // Create executor config with diagnostics
  realtime::RealTimeBlockExecutor::Config exec_config;
  exec_config.sink = sink_config;
  exec_config.diagnostic = [](const std::string& msg) {
    std::cout << msg << std::endl;
  };

  // INV-PTS-MONOTONIC: Track accumulated PTS offset across blocks
  int64_t session_pts_offset_90k = 0;

  // Main execution loop - process blocks from queue
  while (!ctx_->stop_requested.load(std::memory_order_acquire))
  {
    // ========================================================================
    // INSTRUMENTATION: Block fetch timing (includes queue wait)
    // ========================================================================
    auto block_fetch_start = std::chrono::steady_clock::now();

    // Get next block from queue
    FedBlock current_block;
    {
      std::unique_lock<std::mutex> lock(ctx_->queue_mutex);

      // Wait for a block to be available
      if (ctx_->block_queue.empty()) {
        // Check if we should wait or exit
        if (ctx_->stop_requested.load(std::memory_order_acquire)) {
          break;
        }

        // INSTRUMENTATION: Log queue wait
        auto wait_start = std::chrono::steady_clock::now();
        ctx_->queue_cv.wait_for(lock, std::chrono::milliseconds(100));
        auto wait_end = std::chrono::steady_clock::now();
        auto wait_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            wait_end - wait_start).count();
        if (wait_ms > 10) {  // Only log significant waits
          std::cout << "[METRIC] queue_wait_ms=" << wait_ms
                    << " channel_id=" << ctx_->channel_id << std::endl;
        }
        continue;
      }

      // Get and remove the first block
      current_block = ctx_->block_queue.front();
      ctx_->block_queue.erase(ctx_->block_queue.begin());
    }

    auto block_fetch_end = std::chrono::steady_clock::now();
    auto block_fetch_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        block_fetch_end - block_fetch_start).count();
    std::cout << "[METRIC] block_fetch_ms=" << block_fetch_ms
              << " block_id=" << current_block.block_id << std::endl;

    std::cout << "[BlockPlanExecution] Executing block: " << current_block.block_id
              << " (" << current_block.start_utc_ms << "-" << current_block.end_utc_ms << ")"
              << std::endl;

    // Convert to blockplan types
    BlockPlan plan = FedBlockToBlockPlan(current_block);

    // ========================================================================
    // INSTRUMENTATION: Asset probe timing (per asset)
    // ========================================================================
    auto probe_total_start = std::chrono::steady_clock::now();
    realtime::RealAssetSource assets;
    for (const auto& seg : plan.segments) {
      auto probe_start = std::chrono::steady_clock::now();
      if (!assets.ProbeAsset(seg.asset_uri)) {
        std::cerr << "[BlockPlanExecution] Failed to probe asset: " << seg.asset_uri << std::endl;
        // Continue with next block or terminate
        continue;
      }
      auto probe_end = std::chrono::steady_clock::now();
      auto probe_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          probe_end - probe_start).count();
      std::cout << "[METRIC] asset_probe_ms=" << probe_ms
                << " uri=" << seg.asset_uri
                << " block_id=" << current_block.block_id << std::endl;
    }
    auto probe_total_end = std::chrono::steady_clock::now();
    auto probe_total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        probe_total_end - probe_total_start).count();
    std::cout << "[METRIC] asset_probe_total_ms=" << probe_total_ms
              << " block_id=" << current_block.block_id << std::endl;

    // Accumulate asset probe metrics
    {
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      metrics_.assets_probed += static_cast<int32_t>(plan.segments.size());
      metrics_.sum_asset_probe_ms += probe_total_ms;
      if (probe_total_ms > metrics_.max_asset_probe_ms) {
        metrics_.max_asset_probe_ms = probe_total_ms;
      }
    }

    // Create asset duration function for validator
    auto duration_fn = [&assets](const std::string& uri) -> int64_t {
      return assets.GetDuration(uri);
    };

    // Validate block plan
    BlockPlanValidator validator(duration_fn);
    auto validation = validator.Validate(plan, plan.start_utc_ms);

    if (!validation.valid) {
      std::cerr << "[BlockPlanExecution] Block validation failed: " << validation.detail << std::endl;
      ctx_->final_ct_ms = 0;
      termination_reason = "error";
      break;
    }

    // Compute join parameters (start at block beginning)
    ValidatedBlockPlan validated{plan, validation.boundaries, plan.start_utc_ms};
    auto join_result = JoinComputer::ComputeJoinParameters(validated, plan.start_utc_ms);

    if (!join_result.valid) {
      std::cerr << "[BlockPlanExecution] Join computation failed" << std::endl;
      termination_reason = "error";
      break;
    }

    // INV-PTS-MONOTONIC: Update sink config with session PTS offset before execution
    exec_config.sink.initial_pts_offset_90k = session_pts_offset_90k;

    // ========================================================================
    // INSTRUMENTATION: Execute timing and boundary gap
    // ========================================================================
    auto execute_start = std::chrono::steady_clock::now();

    // Log boundary gap from previous block (if any)
    if (have_prev_block_time) {
      auto boundary_gap_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          execute_start - prev_block_last_frame_time).count();
      std::cout << "[METRIC] boundary_gap_ms=" << boundary_gap_ms
                << " prev_block=" << prev_block_id
                << " next_block=" << current_block.block_id << std::endl;

      // Accumulate boundary gap metrics
      {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.boundary_gaps_measured++;
        metrics_.sum_boundary_gap_ms += boundary_gap_ms;
        if (boundary_gap_ms > metrics_.max_boundary_gap_ms) {
          metrics_.max_boundary_gap_ms = boundary_gap_ms;
        }
      }
    }

    // Log time from session start to first block execute
    if (ctx_->blocks_executed == 0) {
      auto tunein_to_execute_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          execute_start - session_start_time).count();
      std::cout << "[METRIC] tunein_to_first_execute_ms=" << tunein_to_execute_ms
                << " channel_id=" << ctx_->channel_id << std::endl;
    }

    // Create and run executor
    realtime::RealTimeBlockExecutor executor(exec_config);
    auto result = executor.Execute(validated, join_result.params);

    auto execute_end = std::chrono::steady_clock::now();
    auto execute_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        execute_end - execute_start).count();
    std::cout << "[METRIC] block_execute_ms=" << execute_ms
              << " block_id=" << current_block.block_id
              << " frames=" << result.final_ct_ms / 33 << std::endl;

    // Store for next boundary gap calculation
    prev_block_id = current_block.block_id;
    prev_block_last_frame_time = execute_end;
    have_prev_block_time = true;

    // INV-PTS-MONOTONIC: Capture PTS offset from completed block for next block
    session_pts_offset_90k = result.final_pts_offset_90k;

    ctx_->final_ct_ms = result.final_ct_ms;
    ctx_->blocks_executed++;

    // Accumulate frame cadence and block-level metrics
    {
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      metrics_.total_blocks_executed = ctx_->blocks_executed;
      metrics_.total_frames_emitted += result.frame_cadence.frames_emitted;
      metrics_.frame_gaps_over_40ms += result.frame_cadence.frame_gaps_over_40ms;
      metrics_.sum_inter_frame_gap_us += result.frame_cadence.sum_inter_frame_gap_us;
      // frame_gap_count: frames_emitted - 1 per block (inter-frame gaps)
      if (result.frame_cadence.frames_emitted > 1) {
        metrics_.frame_gap_count += result.frame_cadence.frames_emitted - 1;
      }
      if (result.frame_cadence.max_inter_frame_gap_us > metrics_.max_inter_frame_gap_us) {
        metrics_.max_inter_frame_gap_us = result.frame_cadence.max_inter_frame_gap_us;
      }
      // Capture first-TS-packet timing if available
      auto first_ts_ms = write_ctx.first_ts_packet_ms.load(std::memory_order_acquire);
      if (first_ts_ms > 0 && metrics_.time_to_first_ts_packet_ms == 0) {
        metrics_.time_to_first_ts_packet_ms = first_ts_ms;
      }
    }

    std::cout << "[BlockPlanExecution] Block " << current_block.block_id
              << " completed: ct=" << result.final_ct_ms << "ms"
              << ", result=" << static_cast<int>(result.code)
              << ", frames=" << result.frame_cadence.frames_emitted
              << std::endl;

    // Emit BlockCompleted event to subscribers (fires after fence)
    if (callbacks_.on_block_completed) {
      callbacks_.on_block_completed(current_block, result.final_ct_ms);
    }

    // Check for errors
    if (result.code != realtime::RealTimeBlockExecutor::Result::Code::kSuccess &&
        result.code != realtime::RealTimeBlockExecutor::Result::Code::kTerminated) {
      std::cerr << "[BlockPlanExecution] Execution error: " << result.error_detail << std::endl;
      termination_reason = "error";
      break;
    }

    if (result.code == realtime::RealTimeBlockExecutor::Result::Code::kTerminated) {
      std::cout << "[BlockPlanExecution] Terminated by request" << std::endl;
      termination_reason = "stopped";
      break;
    }

    // Check if there's another block (lookahead)
    {
      std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
      if (ctx_->block_queue.empty()) {
        std::cout << "[BlockPlanExecution] LOOKAHEAD_EXHAUSTED at fence" << std::endl;
        termination_reason = "lookahead_exhausted";
        break;
      }
    }
  }

  // If we exited due to stop_requested (from main loop condition), set reason
  if (ctx_->stop_requested.load(std::memory_order_acquire) && termination_reason == "unknown") {
    termination_reason = "stopped";
  }

  // ========================================================================
  // SESSION-LONG ENCODER: Close the encoder at session end
  // ========================================================================
  if (session_encoder) {
    session_encoder->close();
    std::cout << "[BlockPlanExecution] Session encoder closed: "
              << write_ctx.bytes_written << " bytes written" << std::endl;
  }

  // Record session end metrics
  {
    auto session_end_time = std::chrono::steady_clock::now();
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.encoder_close_count = 1;
    metrics_.session_end_epoch_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        session_end_time.time_since_epoch()).count();
    metrics_.session_duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        session_end_time - session_start_time).count();
    metrics_.session_active = false;
  }

  std::cout << "[BlockPlanExecution] Thread exiting: blocks_executed=" << ctx_->blocks_executed
            << ", final_ct=" << ctx_->final_ct_ms << "ms"
            << ", reason=" << termination_reason << std::endl;

  // Emit SessionEnded event to all subscribers
  if (callbacks_.on_session_ended) {
    callbacks_.on_session_ended(termination_reason);
  }
}

}  // namespace retrovue::blockplan
