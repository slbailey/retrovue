// Repository: Retrovue-playout
// Component: Pipeline Manager
// Purpose: Continuous output loop with TAKE-at-commit source selection (P3.0 + P3.1a + P3.1b)
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/PipelineManager.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "retrovue/blockplan/PlaybackTraceTypes.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/blockplan/PadProducer.hpp"
#include "retrovue/blockplan/ProducerPreloader.hpp"
#include "retrovue/blockplan/SeamPreparer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/output/SocketSink.h"
#include "retrovue/util/Logger.hpp"
#include "time/SystemTimeSource.hpp"

// Define RETROVUE_DEBUG_PAD_EMIT to enable per-tick pad frame logging.
// Disabled by default — zero runtime cost when off.
// Enable at build time: -DRETROVUE_DEBUG_PAD_EMIT
// #define RETROVUE_DEBUG_PAD_EMIT

#ifdef __linux__
#include <sys/socket.h>
#endif

extern "C" {
#include <libavutil/error.h>
}

#if defined(__linux__) || defined(__APPLE__)
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#endif

namespace retrovue::blockplan {

using retrovue::util::Logger;

// INV-AUDIO-PRIME-001: Minimum audio buffer depth (ms) required from
// TickProducer::PrimeFirstTick.  The preloader worker thread calls
// PrimeFirstTick which accumulates audio into the primed frame's audio
// vector.  StartFilling() consumes the primed frame synchronously, pushing
// all accumulated audio to the AudioLookaheadBuffer in one non-blocking call.
// 500ms provides headroom above LOW_WATER (333ms), preventing micro-underruns
// during initial playback before the fill thread reaches steady state.
static constexpr int kMinAudioPrimeMs = 500;
// Segment swap gate: minimum incoming buffer depth before swapping (avoids async fill race).
static constexpr int kMinSegmentSwapAudioMs = 500;
static constexpr int kMinSegmentSwapVideoFrames = 1;

// B-chain fill: minimum lead time (frames/ms) so segment prep reaches target depth before seam.
static constexpr int kMinSegmentPrepHeadroomMs = 250;
static constexpr int kMinSegmentPrepHeadroomFrames = 8;

// Task 2: Format fence_tick for logging — sentinel INT64_MAX prints as "UNARMED".
static std::string FormatFenceTick(int64_t tick) {
  if (tick == std::numeric_limits<int64_t>::max()) return "UNARMED";
  return std::to_string(tick);
}

// INV-FENCE-TAKE-READY-001: Max time (ms) to hold last A frame before escalating to standby (slot 'S').
static constexpr int64_t kDegradedHoldMaxMs = 5000;

PipelineManager::PipelineManager(
    BlockPlanSessionContext* ctx,
    Callbacks callbacks,
    std::shared_ptr<ITimeSource> time_source)
    : ctx_(ctx),
      callbacks_(std::move(callbacks)),
      time_source_(time_source ? std::move(time_source)
                               : std::make_shared<SystemTimeSource>()),
      live_(std::make_unique<TickProducer>(ctx->width, ctx->height,
                                     ctx->fps_num, ctx->fps_den)),
      seam_preparer_(std::make_unique<SeamPreparer>()) {
  metrics_.channel_id = ctx->channel_id;
}

PipelineManager::~PipelineManager() {
  Stop();
}

void PipelineManager::Start() {
  if (started_) return;
  started_ = true;
  ctx_->stop_requested.store(false, std::memory_order_release);
  reaper_shutdown_.store(false, std::memory_order_release);
  reaper_thread_ = std::thread(&PipelineManager::ReaperLoop, this);
  thread_ = std::thread(&PipelineManager::Run, this);
}

void PipelineManager::Stop() {
  if (!started_) return;
  ctx_->stop_requested.store(true, std::memory_order_release);
  ctx_->queue_cv.notify_all();
  seam_preparer_->Cancel();
  if (thread_.joinable()) {
    thread_.join();
  }
  started_ = false;

  // Shutdown reaper and drain any pending threads.
  reaper_shutdown_.store(true, std::memory_order_release);
  reaper_cv_.notify_all();
  if (reaper_thread_.joinable()) {
    reaper_thread_.join();
  }
  // Drain remaining queue (defensive: join any threads that were pushed
  // but not yet processed).
  {
    std::lock_guard<std::mutex> lock(reaper_mutex_);
    while (!reaper_queue_.empty()) {
      ReapJob job = std::move(reaper_queue_.front());
      reaper_queue_.pop();
      if (job.thread.joinable()) job.thread.join();
    }
  }

  // Defensive thread-joinable audit: after Run() exits and thread_ is joined,
  // no owned threads should remain joinable.  Hitting any of these means the
  // teardown in Run() (section 7) missed a join — a latent std::terminate bug.
  if (deferred_fill_thread_.joinable()) {
    { std::ostringstream oss;
      oss << "[PipelineManager] BUG: deferred_fill_thread_ still joinable "
          << "after Stop(). Joining to prevent std::terminate.";
      Logger::Error(oss.str()); }
    deferred_fill_thread_.join();
  }
  if (video_buffer_ && video_buffer_->IsFilling()) {
    { std::ostringstream oss;
      oss << "[PipelineManager] BUG: video fill thread still running "
          << "after Stop(). Stopping to prevent std::terminate.";
      Logger::Error(oss.str()); }
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=stop_defensive_video tick=stop";
        Logger::Info(oss.str()); }
      video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=stop_defensive_video tick=stop dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
  }
  if (preview_video_buffer_ && preview_video_buffer_->IsFilling()) {
    { std::ostringstream oss;
      oss << "[PipelineManager] BUG: preview video fill thread still running "
          << "after Stop(). Stopping to prevent std::terminate.";
      Logger::Error(oss.str()); }
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=stop_defensive_preview tick=stop";
        Logger::Info(oss.str()); }
      preview_video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=stop_defensive_preview tick=stop dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
  }
  if (segment_b_video_buffer_ && segment_b_video_buffer_->IsFilling()) {
    { std::ostringstream oss;
      oss << "[PipelineManager] BUG: segment B video fill thread still running "
          << "after Stop(). Stopping to prevent std::terminate.";
      Logger::Error(oss.str()); }
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=stop_defensive_segment_b tick=stop";
        Logger::Info(oss.str()); }
      segment_b_video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=stop_defensive_segment_b tick=stop dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
  }
  if (pad_b_video_buffer_ && pad_b_video_buffer_->IsFilling()) {
    { std::ostringstream oss;
      oss << "[PipelineManager] BUG: pad B video fill thread still running "
          << "after Stop(). Stopping to prevent std::terminate.";
      Logger::Error(oss.str()); }
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=stop_defensive_pad_b tick=stop";
        Logger::Info(oss.str()); }
      pad_b_video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=stop_defensive_pad_b tick=stop dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
  }
}

std::string PipelineManager::GetBlockIdFromProducer(producers::IProducer* p) {
  if (!p) return "none";
  auto* tp = dynamic_cast<ITickProducer*>(p);
  return tp ? tp->GetBlock().block_id : "?";
}

void PipelineManager::CleanupDeferredFill() {
  // Never block tick loop: hand job to reaper. Owners stay in job until join.
  if (!deferred_fill_thread_.joinable()) return;

  ReapJob job;
  job.job_id = reap_job_id_.fetch_add(1, std::memory_order_relaxed);
  job.block_id = GetBlockIdFromProducer(deferred_producer_.get());
  job.thread = std::move(deferred_fill_thread_);
  job.producer = std::move(deferred_producer_);
  job.video_buffer = std::move(deferred_video_buffer_);
  job.audio_buffer = std::move(deferred_audio_buffer_);

  HandOffToReaper(std::move(job));
}

void PipelineManager::HandOffToReaper(ReapJob job) {
  if (!job.thread.joinable()) return;
  { std::ostringstream oss;
    oss << "[PipelineManager] REAP_ENQUEUE job_id=" << job.job_id
        << " block_id=" << (job.block_id.empty() ? "none" : job.block_id);
    Logger::Info(oss.str()); }
  std::lock_guard<std::mutex> lock(reaper_mutex_);
  reaper_queue_.push(std::move(job));
  reaper_cv_.notify_one();
}

void PipelineManager::ReaperLoop() {
  while (true) {
    ReapJob job;
    int queued_after_pop = 0;
    {
      std::unique_lock<std::mutex> lock(reaper_mutex_);
      reaper_cv_.wait(lock, [this] {
        return reaper_shutdown_.load(std::memory_order_acquire) ||
               !reaper_queue_.empty();
      });
      if (reaper_shutdown_.load(std::memory_order_acquire) &&
          reaper_queue_.empty()) {
        return;
      }
      if (!reaper_queue_.empty()) {
        job = std::move(reaper_queue_.front());
        reaper_queue_.pop();
        queued_after_pop = static_cast<int>(reaper_queue_.size());
      }
    }
    if (job.thread.joinable()) {
      { std::ostringstream oss;
        oss << "[Reaper] REAP_JOIN_BEGIN job_id=" << job.job_id
            << " block_id=" << (job.block_id.empty() ? "none" : job.block_id)
            << " queued=" << queued_after_pop;
        Logger::Info(oss.str()); }
      auto t0 = std::chrono::steady_clock::now();
      job.thread.join();
      auto join_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[Reaper] REAP_JOIN_END job_id=" << job.job_id
            << " join_ms=" << join_ms
            << " queued=" << queued_after_pop;
        Logger::Info(oss.str()); }
    }
    // job destructs here — producers/buffers destroyed AFTER join
  }
}

PipelineMetrics PipelineManager::SnapshotMetrics() const {
  std::lock_guard<std::mutex> lock(metrics_mutex_);
  return metrics_;
}

std::string PipelineManager::GenerateMetricsText() const {
  std::lock_guard<std::mutex> lock(metrics_mutex_);
  return metrics_.GeneratePrometheusText();
}

// =============================================================================
// TryLoadLiveProducer — load live_ from preloaded preview or queue.
// Called ONLY when live_ is EMPTY — outside the timed tick window.
// =============================================================================

void PipelineManager::TryLoadLiveProducer() {
  // P3.1b: first try to adopt a preloaded preview_
  if (preview_ &&
      AsTickProducer(preview_.get())->GetState() == ITickProducer::State::kReady) {
    live_ = std::move(preview_);
    return;
  }

  // Check if preloader has finished
  auto preloaded = TryTakePreviewProducer();
  if (preloaded && AsTickProducer(preloaded.get())->GetState() == ITickProducer::State::kReady) {
    live_ = std::move(preloaded);
    return;
  }

  // Fallback: synchronous load from queue (P3.1a behavior)
  FedBlock block;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    if (ctx_->block_queue.empty()) return;

    block = ctx_->block_queue.front();
    ctx_->block_queue.erase(ctx_->block_queue.begin());
  }

  // AssignBlock is synchronous and may stall (probe + open + seek).
  // This is acceptable: it occurs only at block boundaries when no
  // content is playing.  The tick loop resumes on the next
  // WaitForFrame() absolute deadline.
  AsTickProducer(live_.get())->AssignBlock(block);
}

// =============================================================================
// TryKickoffBlockPreload — start preloading the next block if conditions met.
// Called outside the tick window only.
// =============================================================================

void PipelineManager::TryKickoffBlockPreload(int64_t tick) {
  // Guard 1: Live must be READY (no preload during PADDED_GAP — handled by
  // the dedicated PADDED_GAP exit path instead).
  if (AsTickProducer(live_.get())->GetState() != ITickProducer::State::kReady) return;

  // Guard 2: SeamPreparer already has a block result — wait for PRE-TAKE to consume it.
  // Job ownership: single block_result_ slot; we never submit the next block until we take,
  // so the result we take is always for the block we last submitted (no overwrite by a later block).
  if (seam_preparer_->HasBlockResult()) return;

  // INV-SEAM-SUBMIT-SAFE: Callers must NOT gate Submit() on IsRunning().
  // The queue is sorted by seam_frame — priority is structural, not temporal.
  // Gating on IsRunning() starves segment prep when block prep is in-flight,
  // causing segment MISS at seam time.  See: FIX-seam-prep-starvation.md

  bool has_next = false;
  FedBlock block;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    has_next = !ctx_->block_queue.empty();
    if (!has_next) {
      if (tick >= 0 && block_fence_frame_ != INT64_MAX &&
          (block_fence_frame_ - tick) < 3000 &&
          (tick == block_fence_frame_ || tick % 900 == 0)) {
        { std::ostringstream oss;
          oss << "[PipelineManager] PREROLL_DIAG"
              << " tick=" << tick
              << " fence_tick=" << FormatFenceTick(block_fence_frame_)
              << " has_next_block=0"
              << " preview_exists=" << (preview_ != nullptr)
              << " seam_preparer_has_block=0"
              << " seam_preparer_running=" << seam_preparer_->IsRunning();
          Logger::Info(oss.str()); }
      }
      return;
    }
    block = ctx_->block_queue.front();
    ctx_->block_queue.erase(ctx_->block_queue.begin());
  }

  expected_preroll_block_id_ = block.block_id;
  expected_preroll_first_seg_content_ =
      !block.segments.empty() && block.segments[0].segment_type != SegmentType::kPad;
  last_submitted_block_ = block;
  last_submitted_block_valid_ = true;
  if (block.block_id != retry_attempted_block_id_) {
    retry_attempted_block_id_.clear();  // New block eligible for one retry
  }

  { std::ostringstream oss;
    oss << "[PipelineManager] PREROLL_SUBMIT block_id=" << block.block_id
        << " fence_tick=" << FormatFenceTick(block_fence_frame_);
    Logger::Info(oss.str()); }

  SeamRequest req;
  req.type = SeamRequestType::kBlock;
  req.block = block;
  req.seam_frame = block_fence_frame_;
  req.width = ctx_->width;
  req.height = ctx_->height;
  req.fps = ctx_->fps;
  req.min_audio_prime_ms = kMinAudioPrimeMs;
  req.parent_block_id = block.block_id;
  seam_preparer_->Submit(std::move(req));

  std::string first_seg_uri(block.segments.empty() ? "none" : block.segments[0].asset_uri);
  { std::ostringstream oss;
    oss << "[PipelineManager] PREROLL_ARMED"
        << " tick=" << tick
        << " fence_tick=" << FormatFenceTick(block_fence_frame_)
        << " block=" << block.block_id
        << " first_seg_asset_uri=" << (first_seg_uri.empty() ? "empty" : first_seg_uri)
        << " preview_exists=" << (preview_ != nullptr);
    Logger::Info(oss.str()); }
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.next_preload_started_count++;
  }
}

// =============================================================================
// TryTakePreviewProducer — non-blocking check for preloader result.
// =============================================================================

std::unique_ptr<producers::IProducer> PipelineManager::TryTakePreviewProducer(int64_t headroom_ms) {
  auto result = seam_preparer_->TakeBlockResult();
  if (!result) return nullptr;

  { std::ostringstream oss;
    oss << "[PipelineManager] PREROLL_TAKE_RESULT block_id=" << result->block_id
        << " segment_type=" << SegmentTypeName(result->segment_type)
        << " decoder_used=" << (result->producer && AsTickProducer(result->producer.get())->HasDecoder() ? "Y" : "N");
    Logger::Info(oss.str()); }

  // Content block with no decoder (open/seek failed in worker).
  // Keep the producer so fence/PADDED_GAP path can adopt it and run as all-pad.
  if (result->segment_type != SegmentType::kPad && result->producer &&
      !AsTickProducer(result->producer.get())->HasDecoder()) {
    { std::ostringstream oss;
      oss << "[PipelineManager] PREROLL_DECODER_FAILED"
          << " block_id=" << result->block_id
          << " reason=content_block_no_decoder keeping_as_preview";
      Logger::Warn(oss.str()); }
    // Retry once if fence headroom > 2000ms and we have the block to re-submit.
    if (headroom_ms >= 2000 && last_submitted_block_valid_ &&
        last_submitted_block_.block_id == result->block_id &&
        result->block_id != retry_attempted_block_id_) {
      retry_attempted_block_id_ = result->block_id;
      SeamRequest retry_req;
      retry_req.type = SeamRequestType::kBlock;
      retry_req.block = last_submitted_block_;
      retry_req.seam_frame = block_fence_frame_;
      retry_req.width = ctx_->width;
      retry_req.height = ctx_->height;
      retry_req.fps = ctx_->fps;
      retry_req.min_audio_prime_ms = kMinAudioPrimeMs;
      retry_req.parent_block_id = last_submitted_block_.block_id;
      seam_preparer_->Submit(std::move(retry_req));
      { std::ostringstream retry_oss;
        retry_oss << "[PipelineManager] PREROLL_RETRY block_id=" << result->block_id
                  << " headroom_ms=" << headroom_ms;
        Logger::Info(retry_oss.str()); }
    }
    return std::move(result->producer);  // Keep decoderless producer — fence/PADDED_GAP path will run it as all-pad.
  }

  last_submitted_block_valid_ = false;
  retry_attempted_block_id_.clear();

  // Policy B: capture audio prime depth for TAKE_READINESS and degraded_take_count.
  preview_audio_prime_depth_ms_ = result->audio_prime_depth_ms;

  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.next_preload_ready_count++;
  }
  return std::move(result->producer);
}

// =============================================================================
// Run() — P3.0 + P3.1a + P3.1b main loop (pad + TAKE-at-commit)
// =============================================================================

void PipelineManager::Run() {
  { std::ostringstream oss;
    oss << "[PipelineManager] Starting execution thread for channel "
        << ctx_->channel_id;
    Logger::Info(oss.str()); }

  // ========================================================================
  // 1. SESSION SETUP
  // ========================================================================
  auto session_start_time = std::chrono::steady_clock::now();
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.session_start_epoch_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            session_start_time.time_since_epoch()).count();
    metrics_.continuous_mode_active = true;
  }

  std::string termination_reason = "unknown";

  // ========================================================================
  // 2. SESSION-LONG ENCODER
  // ========================================================================
  playout_sinks::mpegts::MpegTSPlayoutSinkConfig enc_config;
  enc_config.target_width = ctx_->width;
  enc_config.target_height = ctx_->height;
  enc_config.target_fps = ctx_->fps;
  enc_config.enable_audio = true;
  enc_config.gop_size = 90;      // I-frame every 3 seconds
  enc_config.bitrate = 2000000;  // 2 Mbps

  auto session_encoder =
      std::make_unique<playout_sinks::mpegts::EncoderPipeline>(enc_config);

  // --- Non-blocking socket sink (Bug B: decouple write from tick loop) ---
  // dup() the fd so SocketSink can take ownership without closing ctx_->fd.
  int sink_fd = dup(ctx_->fd);
  if (sink_fd < 0) {
    { std::ostringstream oss;
      oss << "[PipelineManager] dup(fd) failed: " << strerror(errno);
      Logger::Error(oss.str()); }
    if (callbacks_.on_session_ended && !session_ended_fired_) {
      session_ended_fired_ = true;
      callbacks_.on_session_ended("dup_failed", 0);
    }
    return;
  }

  // INV-SOCKET-NONBLOCK: SocketSink requires O_NONBLOCK.
  int flags = fcntl(sink_fd, F_GETFL, 0);
  if (flags < 0 || fcntl(sink_fd, F_SETFL, flags | O_NONBLOCK) < 0) {
    Logger::Error("[PipelineManager] fcntl(O_NONBLOCK) failed");
    ::close(sink_fd);
    if (callbacks_.on_session_ended && !session_ended_fired_) {
      session_ended_fired_ = true;
      callbacks_.on_session_ended("nonblock_failed", 0);
    }
    return;
  }

  // Bound UDS kernel send buffer to limit post-fence old-tail latency.
  // At ~284.6 KB/s TS wire rate, 32 KB ≈ 115 ms (Linux doubles to ~64 KB ≈ 225 ms).
#ifdef __linux__
  {
    const int requested_sndbuf = 32768;
    if (setsockopt(sink_fd, SOL_SOCKET, SO_SNDBUF,
                   &requested_sndbuf, sizeof(requested_sndbuf)) < 0) {
      { std::ostringstream oss;
        oss << "[PipelineManager] WARNING: setsockopt(SO_SNDBUF="
            << requested_sndbuf << ") failed: " << strerror(errno)
            << " (continuing with default)";
        Logger::Warn(oss.str()); }
    }
    int effective_sndbuf = 0;
    socklen_t elen = sizeof(effective_sndbuf);
    if (getsockopt(sink_fd, SOL_SOCKET, SO_SNDBUF,
                   &effective_sndbuf, &elen) == 0) {
      { std::ostringstream oss;
        oss << "[PipelineManager] UDS SO_SNDBUF: requested="
            << requested_sndbuf << " effective=" << effective_sndbuf;
        Logger::Info(oss.str()); }
    }
  }
#endif

  // Buffer capacity: 32 KB ≈ 115 ms at ~284.6 KB/s TS wire rate.
  // Small buffer bounds post-fence old-tail latency; backpressure via
  // WaitAndConsumeBytes blocks the tick thread until the writer drains.
  static constexpr size_t kSinkBufferCapacity = 32 * 1024;
  auto socket_sink = std::make_unique<output::SocketSink>(
      sink_fd, "pipeline-sink", kSinkBufferCapacity);

  // INV-AUDIO-BOOTSTRAP-GATE-001: Hold TS emission until audio bootstrap.
  // encoder->open() writes TS header (PAT/PMT) through the AVIO callback,
  // which enqueues into SocketSink.  Without the gate, these bytes reach
  // the socket before audio is ready, causing Core to see FIRST_RECV_DATA
  // and start serving a stream with no audio.
  socket_sink->HoldEmission();

  // Slow-consumer detach → clean session stop.
  // output_detached is checked in the tick loop condition for immediate exit
  // without waiting for the next boundary check or spamming write errors.
  std::atomic<bool> output_detached{false};
  socket_sink->SetDetachOnOverflow(true);
  socket_sink->SetDetachCallback([this, &output_detached](const std::string& reason) {
    { std::ostringstream oss;
      oss << "[PipelineManager] SocketSink detach: " << reason;
      Logger::Error(oss.str()); }
    output_detached.store(true, std::memory_order_release);
    ctx_->stop_requested.store(true, std::memory_order_release);
  });

  // Write callback context: enqueue into SocketSink (blocking if full).
  struct SessionWriteContext {
    output::SocketSink* sink;
    int64_t bytes_written;
  };
  SessionWriteContext write_ctx{socket_sink.get(), 0};

  // AVIO write callback — backpressure via blocking wait.
  //
  // When the SocketSink buffer is full, WaitAndConsumeBytes blocks the tick
  // thread (up to 500 ms) until the writer thread drains space.  This is
  // safe because:
  //   - Writer thread only reads the queue and calls send() — no dependency
  //     on the tick thread, so no circular wait / deadlock.
  //   - OutputClock pacing is upstream of encodeFrame; blocking here simply
  //     delays the tick, and the next OutputClock sleep self-corrects.
  //   - On close/detach, drain_cv_ is signalled so the wait exits promptly.
  //
  // Timeout (500 ms) → AVERROR(EPIPE) → encoder error → session stop.
  // This only fires if the consumer is critically stuck (no drain for 500 ms).
  static constexpr int kAvioWaitMs = 500;
  auto write_callback = [](void* opaque, uint8_t* buf, int buf_size) -> int {
    auto* wctx = static_cast<SessionWriteContext*>(opaque);
    if (wctx->sink->IsDetached() || wctx->sink->IsClosed()) {
      return AVERROR(EPIPE);
    }
    if (wctx->sink->WaitAndConsumeBytes(
            reinterpret_cast<const uint8_t*>(buf),
            static_cast<size_t>(buf_size),
            std::chrono::milliseconds(kAvioWaitMs))) {
      wctx->bytes_written += buf_size;
      return buf_size;
    }
    // Timed out or closed — signal broken pipe to FFmpeg.
    return AVERROR(EPIPE);
  };

  auto encoder_open_start = std::chrono::steady_clock::now();
  if (!session_encoder->open(enc_config, &write_ctx, write_callback)) {
    Logger::Error("[PipelineManager] Failed to open session encoder");
    if (callbacks_.on_session_ended && !session_ended_fired_) {
      session_ended_fired_ = true;
      callbacks_.on_session_ended("encoder_failed", 0);
    }
    return;
  }
  auto encoder_open_end = std::chrono::steady_clock::now();
  auto encoder_open_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      encoder_open_end - encoder_open_start).count();

  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.encoder_open_count = 1;
    metrics_.encoder_open_ms = encoder_open_ms;
  }

  { std::ostringstream oss;
    oss << "[PipelineManager] Session encoder opened: "
        << ctx_->width << "x" << ctx_->height << " @ " << ctx_->fps
        << "fps, open_ms=" << encoder_open_ms;
    Logger::Info(oss.str()); }

  // Disable EncoderPipeline's internal output timing gate.
  // Verified: GateOutputTiming() is purely a pacing sleep (media PTS vs wall
  // clock).  PTS monotonicity is enforced separately by EnforceMonotonicDts().
  // The tick loop provides authoritative pacing via OutputClock::WaitForFrame;
  // GateOutputTiming would double-gate and add blocking sleep inside the
  // AVIO write path — exactly what Bug B eliminates.
  session_encoder->SetOutputTimingEnabled(false);

  // Disable EncoderPipeline's independent audio silence injection
  // (INV-P9-AUDIO-LIVENESS).  PipelineManager is the sole audio authority:
  // it sends exactly one audio frame per tick via encodeAudioFrame() — either
  // real content from the AudioLookaheadBuffer or silence from PadProducer /
  // FENCE_AUDIO_PAD.  If the encoder also generates silence in
  // GenerateSilenceFrames(), both streams hit the mux, doubling audio samples
  // and desynchronising A/V.
  session_encoder->SetAudioLivenessEnabled(false);

  // ========================================================================
  // ARCHITECTURAL TELEMETRY
  // ========================================================================
  constexpr auto kExecutionMode = PlayoutExecutionMode::kContinuousOutput;
  { std::ostringstream oss;
    oss << "[INV-PLAYOUT-AUTHORITY] channel_id=" << ctx_->channel_id
        << " | playout_path=blockplan"
        << " | encoder_scope=session"
        << " | execution_model="
        << PlayoutExecutionModeToString(kExecutionMode)
        << " | format=" << ctx_->width << "x" << ctx_->height
        << "@" << ctx_->fps;
    Logger::Info(oss.str()); }

  // ========================================================================
  // 3. CREATE OUTPUT CLOCK
  // ========================================================================
  OutputClock clock(ctx_->fps_num, ctx_->fps_den);

  // INV-PAD-PRODUCER: Session-lifetime pad source.
  pad_producer_ = std::make_unique<PadProducer>(
      ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);

  // INV-JIP-ANCHOR-001 / INV-BLOCK-WALLFENCE-001: Session epoch for fence math.
  // When Core provides join_utc_ms (non-zero), use it as the authoritative
  // epoch.  This is the wall-clock instant Core captured at the 0→1 viewer
  // transition — before subprocess spawn, gRPC wait, and stream attach.
  // Using it eliminates startup-delay JIP drift: fences are computed from
  // the same T_join that Core used for JIP math.
  // Fallback to system_clock::now() for legacy / test paths (join_utc_ms == 0).
  if (ctx_->join_utc_ms > 0) {
    session_epoch_utc_ms_ = ctx_->join_utc_ms;
    { std::ostringstream oss;
      oss << "[PipelineManager] INV-JIP-ANCHOR-001: session_epoch_utc_ms="
          << session_epoch_utc_ms_ << " (Core-authoritative join_utc_ms)";
      Logger::Info(oss.str()); }
  } else {
    session_epoch_utc_ms_ = time_source_->NowUtcMs();
    { std::ostringstream oss;
      oss << "[PipelineManager] INV-JIP-ANCHOR-001: session_epoch_utc_ms="
          << session_epoch_utc_ms_ << " (local clock fallback, join_utc_ms=0)";
      Logger::Info(oss.str()); }
  }

  // ========================================================================
  // 4. LOOKAHEAD BUFFERS + AUDIO PTS TRACKING
  // ========================================================================
  static constexpr int kAudioSamplesPerFrame = 1024;  // pad silence size
  int64_t audio_samples_emitted = 0;

  // INV-AUDIO-LOOKAHEAD-001: Create lookahead buffer for broadcast-grade audio.
  // Audio frames from decode are pushed here; tick loop pops exact per-tick
  // sample counts.  Underflow = hard fault (session stop).
  const auto& bcfg = ctx_->buffer_config;
  int audio_target = bcfg.audio_target_depth_ms;  // default: 1000
  int audio_low = bcfg.audio_low_water_ms > 0
      ? bcfg.audio_low_water_ms
      : std::max(1, audio_target / 3);
  audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
      audio_target, buffer::kHouseAudioSampleRate,
      buffer::kHouseAudioChannels, audio_low);

  // Track audio ticks and buffer-emitted samples separately from pad samples.
  // Used for exact per-tick sample computation (drift-free rational arithmetic).
  int64_t audio_ticks_emitted = 0;
  int64_t audio_buffer_samples_emitted = 0;

  // OUT-SEG-005b: Track consecutive fallback ticks for broadcast KPI.
  // Counts ticks in a row where decoded audio was NOT emitted from a real asset.
  int64_t current_consecutive_fallback_ticks = 0;

  // INV-VIDEO-LOOKAHEAD-001: Create video lookahead buffer.
  // Background fill thread decodes ahead; tick loop pops one frame per tick.
  // Target depth: ~500ms at output FPS (e.g. 15 frames at 30fps).
  int video_target_depth = bcfg.video_target_depth_frames > 0
      ? bcfg.video_target_depth_frames
      : static_cast<int>(std::max(1.0, ctx_->fps * 0.5));
  int video_low_water = bcfg.video_low_water_frames > 0
      ? bcfg.video_low_water_frames
      : std::max(1, video_target_depth / 3);
  video_buffer_ = std::make_unique<VideoLookaheadBuffer>(
      video_target_depth, video_low_water);
  video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");

  // Persistent pad B chain: created once, always-ready for PAD seams (swap only).
  pad_b_producer_ = std::make_unique<TickProducer>(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
  pad_b_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(15, 5);
  pad_b_video_buffer_->SetBufferLabel("PAD_B_VIDEO_BUFFER");
  int pad_a_target = bcfg.audio_target_depth_ms;
  int pad_a_low = bcfg.audio_low_water_ms > 0
      ? bcfg.audio_low_water_ms
      : std::max(1, pad_a_target / 3);
  pad_b_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
      pad_a_target, buffer::kHouseAudioSampleRate,
      buffer::kHouseAudioChannels, pad_a_low);
  pad_b_video_buffer_->StartFilling(
      AsTickProducer(pad_b_producer_.get()), pad_b_audio_buffer_.get(),
      0.0, ctx_->fps, &ctx_->stop_requested);

  // Initialize fence_epoch_utc_ms_ to the same value as session_epoch_utc_ms_.
  // It will be re-anchored to system_clock::now() at clock.Start().
  // This initial value is needed so that compute_fence_frame works correctly
  // for the first block loaded BEFORE clock.Start().
  fence_epoch_utc_ms_ = session_epoch_utc_ms_;

  // ========================================================================
  // 5. TRY LOADING FIRST BLOCK (before main loop)
  // ========================================================================
  TryLoadLiveProducer();

  // INV-AUDIO-PRIME-001: Prime first block's audio BEFORE clock start.
  // Subsequent blocks are primed by ProducerPreloader::Worker, but block A
  // is loaded synchronously and must be primed here to avoid FENCE_AUDIO_PAD
  // at tick 0.  PrimeFirstTick is safe: it only decodes, no timing dependency.
  {
    bool state_ready = AsTickProducer(live_.get())->GetState() == ITickProducer::State::kReady;
    bool has_decoder = AsTickProducer(live_.get())->HasDecoder();
    { std::ostringstream oss;
      oss << "[PipelineManager] PRIME_CHECK: state_ready=" << state_ready
          << " has_decoder=" << has_decoder;
      Logger::Info(oss.str()); }
    if (state_ready && has_decoder) {
      auto prime_result =
          static_cast<TickProducer*>(live_.get())->PrimeFirstTick(kMinAudioPrimeMs);
      { std::ostringstream oss;
        oss << "[PipelineManager] PRIME_RESULT: met=" << prime_result.met_threshold
            << " depth_ms=" << prime_result.actual_depth_ms
            << " audio_buf_depth=" << audio_buffer_->DepthMs();
        Logger::Info(oss.str()); }
      if (!prime_result.met_threshold) {
        { std::ostringstream oss;
          oss << "[PipelineManager] INV-AUDIO-PRIME-001: block A prime shortfall"
              << " wanted_ms=" << kMinAudioPrimeMs
              << " got_ms=" << prime_result.actual_depth_ms;
          Logger::Warn(oss.str()); }
      }
    } else {
      Logger::Info("[PipelineManager] PRIME_SKIPPED: no decoder on live block");
    }
  }

  // P3.1b: Kick off preload for next block immediately
  TryKickoffBlockPreload(0);

  // ========================================================================
  // 6. MAIN LOOP
  // ========================================================================
  // Convenience: get ITickProducer* for live_ (refreshed after swaps)
  auto live_tp = [this]() { return AsTickProducer(live_.get()); };

  // Audit helper: emit BLOCK_START log for the current live block.
  auto emit_block_start = [&live_tp](const char* source) {
    const auto& blk = live_tp()->GetBlock();
    std::ostringstream oss;
    oss << "[PipelineManager] BLOCK_START"
        << " block=" << blk.block_id
        << " asset=" << (live_tp()->HasDecoder() && !blk.segments.empty()
            ? blk.segments[0].asset_uri : "pad")
        << " offset_ms=" << (!blk.segments.empty()
            ? blk.segments[0].asset_start_offset_ms : 0)
        << " frames=" << live_tp()->FramesPerBlock()
        << " source=" << source;
    Logger::Info(oss.str());
  };

  int64_t session_frame_index = 0;

  // INV-FENCE-PTS-DECOUPLE: PTS origin offsets.
  // Set when the emission gate opens (first tick starts at frame 0).
  // PTS is computed relative to these origins so that bootstrap delay D
  // (which advances fence_epoch_utc_ms_ forward) doesn't create a PTS
  // jump that desynchronizes video from audio.
  //   video_pts_90k = FrameIndexToPts90k(session_frame_index - pts_origin_frame_index)
  //   audio_pts_90k = SamplesToPts90k(audio_samples_emitted - pts_origin_audio_samples)
  // At normal startup both origins are 0, so this is identity.
  int64_t pts_origin_frame_index = 0;
  int64_t pts_origin_audio_samples = 0;

  // INV-PAD-PRODUCER-007: Content-before-pad gate.
  // Do not emit pad until at least one real content frame has been committed.
  // This ensures the encoder's first IDR comes from real content.
  bool first_real_frame_committed = false;

  // INV-BLOCK-WALLFENCE-001: Compute absolute session frame for block fence.
  // Uses rational fps_num/fps_den — NOT ms-quantized frame_duration_ms.
  // Formula: fence_tick = ceil(delta_ms * fps_num / (fps_den * 1000))
  // Integer ceil: (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)
  const int64_t fence_fps_num = ctx_->fps_num;
  const int64_t fence_fps_den = ctx_->fps_den;
  auto compute_fence_frame = [this, fence_fps_num, fence_fps_den](const FedBlock& block) -> int64_t {
    int64_t delta_ms = block.end_utc_ms - fence_epoch_utc_ms_;
    if (delta_ms <= 0) return 0;
    int64_t denominator = fence_fps_den * 1000;
    return (delta_ms * fence_fps_num + denominator - 1) / denominator;
  };

  std::chrono::steady_clock::time_point prev_frame_time{};
  bool have_prev_frame_time = false;
  // Track whether we're past the live block's fence and waiting for next
  bool past_fence = false;

  // P3.3: Per-block playback accumulator
  BlockAccumulator block_acc;
  if (live_tp()->GetState() == ITickProducer::State::kReady) {
    block_fence_frame_ = compute_fence_frame(live_tp()->GetBlock());
    // INV-FRAME-BUDGET-002: Budget derived from fence, not FramesPerBlock().
    remaining_block_frames_ = block_fence_frame_ - session_frame_index;
    if (remaining_block_frames_ < 0) remaining_block_frames_ = 0;
    block_acc.Reset(live_tp()->GetBlock().block_id);
    emit_block_start("queue");
    // INV-VIDEO-LOOKAHEAD-001: Start fill thread (cadence resolved inside).
    video_buffer_->StartFilling(
        live_tp(), audio_buffer_.get(),
        live_tp()->GetInputFPS(), ctx_->fps,
        &ctx_->stop_requested);

    // Step 4 probe: JIP/session-first-block path — decoder opened and primed synchronously
    // before first tick; StartFilling called. Compare with natural rollover (B primed async).
    { std::ostringstream oss;
      oss << "[PipelineManager] SESSION_FIRST_BLOCK"
          << " block=" << live_tp()->GetBlock().block_id
          << " decoder_opened=" << (live_tp()->HasDecoder() ? "Y" : "N")
          << " prime_done_before_clock=Y"
          << " StartFilling_called=Y"
          << " path=JIP_or_cold_start";
      Logger::Info(oss.str()); }

    // INV-SEAM-SEG: Block activation — extract boundaries and compute segment seam frames.
    block_activation_frame_ = session_frame_index;
    live_parent_block_ = live_tp()->GetBlock();
    live_boundaries_ = AsTickProducer(live_.get())->GetBoundaries();
    ComputeSegmentSeamFrames();
    ArmSegmentPrep(session_frame_index);

    // Block is now LIVE — notify subscribers.
    if (callbacks_.on_block_started) {
      BlockActivationContext actx;
      actx.timeline_frame_index = session_frame_index;
      actx.block_fence_tick = block_fence_frame_;
      actx.utc_ms = time_source_->NowUtcMs();
      callbacks_.on_block_started(live_parent_block_, actx);
    }

    // Fire on_segment_start for the first segment of the block.
    if (callbacks_.on_segment_start) {
      callbacks_.on_segment_start(-1, 0, live_parent_block_, session_frame_index);
    }

    // Begin segment proof tracking for first segment.
    if (!live_parent_block_.segments.empty()) {
      const auto& seg0 = live_parent_block_.segments[0];
      block_acc.BeginSegment(
          0, seg0.asset_uri,
          static_cast<int64_t>(std::ceil(
              static_cast<double>(seg0.segment_duration_ms) /
              static_cast<double>(clock.FrameDurationMs()))),
          seg0.segment_type, seg0.event_id);
    }

    // ====================================================================
    // INV-AUDIO-PRIME-002: Hard gate — do not start tick loop until
    // AudioLookaheadBuffer depth >= kMinAudioPrimeMs.
    //
    // StartFilling() consumed the primed frame synchronously (pushing its
    // audio into the AudioLookaheadBuffer) and spawned the fill thread.
    // The fill thread decodes at faster-than-real-time, but at cold start
    // the primed audio may be insufficient (PrimeFirstTick shortfall on
    // cold file cache / slow I/O).  Without this gate, tick 0 consumes
    // the shallow buffer immediately, causing AUDIO_UNDERFLOW_SILENCE and
    // garbled TS on first playout.
    //
    // The gate gives the fill thread wall-clock time to build depth.
    // Typical wait: 50-200ms.  Bounded by the same 2-second timeout used
    // in PrimeFirstTick.  If timeout expires, degrade gracefully (same
    // behavior as before this gate existed).
    //
    // Gate threshold is kMinAudioPrimeMs (500ms) — the same value the
    // system uses for PrimeFirstTick.  One threshold, one enforcement.
    // ====================================================================
    {
      constexpr int kGateTimeoutMs = 2000;
      constexpr int kMarginFrames = 8;
      constexpr int kBootstrapCapFrames = 60;

      auto gate_start = std::chrono::steady_clock::now();
      int depth_ms = audio_buffer_->DepthMs();

      // INV-AUDIO-PRIME-003: Bootstrap fill phase.
      // The fill thread parks when video_depth >= target_depth_frames_ (15).
      // With cadence active (23.976→30), 15 pushed frames yield only ~490ms
      // audio — below the 500ms gate threshold.  Enter BOOTSTRAP phase so
      // the fill thread continues decoding until audio depth is satisfied,
      // bounded by a hard video cap.
      //
      // GetInputFPS() may return 0 if the decoder hasn't finished probing
      // (cold start, slow NFS).  Fall back to 24.0 fps — a conservative
      // estimate that covers 23.976 (NTSC film) through 25 (PAL).
      constexpr double kFallbackInputFps = 24.0;
      double input_fps = live_tp()->GetInputFPS();
      if (input_fps <= 0.0) input_fps = kFallbackInputFps;
      int bootstrap_target = std::max(
          video_buffer_->TargetDepthFrames(),
          static_cast<int>(std::ceil(
              kMinAudioPrimeMs * input_fps / 1000.0)) + kMarginFrames);
      auto bootstrap_epoch_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now().time_since_epoch()).count();

      { std::ostringstream oss;
        oss << "[PipelineManager] INV-AUDIO-PRIME-003: bootstrap_start"
            << " bootstrap_epoch_ms=" << bootstrap_epoch_ms
            << " audio_depth_ms=" << depth_ms
            << " video_depth=" << video_buffer_->DepthFrames()
            << " steady_target=" << video_buffer_->TargetDepthFrames()
            << " bootstrap_target=" << bootstrap_target
            << " bootstrap_cap=" << kBootstrapCapFrames
            << " have_last_decoded=" << (video_buffer_->IsPrimed() ? 1 : 0);
        Logger::Info(oss.str()); }

      video_buffer_->EnterBootstrap(
          bootstrap_target, kBootstrapCapFrames, kMinAudioPrimeMs,
          bootstrap_epoch_ms);

      int gate_poll_count = 0;
      while (depth_ms < kMinAudioPrimeMs) {
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - gate_start).count();
        if (elapsed >= kGateTimeoutMs) {
          { std::ostringstream oss;
            oss << "[PipelineManager] INV-AUDIO-PRIME-002: gate timeout"
                << " depth_ms=" << depth_ms
                << " required=" << kMinAudioPrimeMs
                << " elapsed_ms=" << elapsed
                << " pushed=" << audio_buffer_->TotalSamplesPushed()
                << " popped=" << audio_buffer_->TotalSamplesPopped()
                << " video_depth=" << video_buffer_->DepthFrames();
            Logger::Warn(oss.str()); }
          break;
        }
        if (ctx_->stop_requested.load(std::memory_order_acquire)) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        depth_ms = audio_buffer_->DepthMs();
        gate_poll_count++;
        // Log every 100ms during gate wait
        if (gate_poll_count % 100 == 0) {
          { std::ostringstream oss;
            oss << "[PipelineManager] GATE_POLL elapsed_ms=" << elapsed
                << " audio_depth_ms=" << depth_ms
                << " pushed=" << audio_buffer_->TotalSamplesPushed()
                << " popped=" << audio_buffer_->TotalSamplesPopped()
                << " video_depth=" << video_buffer_->DepthFrames()
                << " fill_phase=" << static_cast<int>(video_buffer_->GetFillPhase());
            Logger::Info(oss.str()); }
        }
      }

      // Restore steady-state fill policy.
      video_buffer_->EndBootstrap();

      auto gate_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - gate_start).count();

      { std::ostringstream oss;
        oss << "[PipelineManager] INV-AUDIO-PRIME-003: bootstrap_end"
            << " bootstrap_epoch_ms=" << bootstrap_epoch_ms
            << " audio_depth_ms=" << audio_buffer_->DepthMs()
            << " video_depth=" << video_buffer_->DepthFrames()
            << " steady_target=" << video_buffer_->TargetDepthFrames()
            << " gate_ms=" << gate_elapsed;
        Logger::Info(oss.str()); }
    }
  }

  // INV-AUDIO-BOOTSTRAP-GATE-001: Audio depth satisfied (or no producer) —
  // allow TS emission to socket.  Placed after the audio gate and outside
  // the state-ready conditional so it fires unconditionally.
  socket_sink->OpenEmissionGate();
  { std::ostringstream oss;
    oss << "[PipelineManager] INV-AUDIO-BOOTSTRAP-GATE-001: emission gate opened"
        << " audio_depth_ms=" << audio_buffer_->DepthMs();
    Logger::Info(oss.str()); }
  { std::ostringstream oss;
    oss << "[PipelineManager] STREAM_READY";
    Logger::Info(oss.str()); }

  // ========================================================================
  // 5b. START OUTPUT CLOCK (monotonic epoch) — after audio depth gate.
  // INV-TICK-MONOTONIC-UTC-ANCHOR-001: Tick deadline enforcement anchored
  // to monotonic clock.  Captured AFTER the audio depth gate so tick 0 is
  // not born late.  The gate ensures the AudioLookaheadBuffer has enough
  // runway to survive initial consumption without underflow.
  //
  // INV-FENCE-WALLCLOCK-ANCHOR: Re-anchor fence epoch to actual tick-loop
  // start time.  session_epoch_utc_ms_ (Core join_utc_ms) is NOT mutated —
  // it remains the authoritative editorial epoch.
  //
  // fence_epoch_utc_ms_ absorbs the bootstrap delay D so that fence frames
  // fire at the correct wall-clock instants.  PTS origins remain at 0,
  // so PTS computation is unaffected (no A/V desync).
  // ========================================================================
  clock.Start();
  {
    // INV-FENCE-WALLCLOCK-ANCHOR: Re-anchor fence epoch to actual tick-loop
    // start time.  session_epoch_utc_ms_ (Core join_utc_ms) is NOT mutated —
    // it remains the authoritative editorial epoch.
    //
    // fence_epoch_utc_ms_ absorbs the bootstrap delay D so that fence frames
    // fire at the correct wall-clock instants.  PTS origins remain at 0,
    // so PTS computation is unaffected (no A/V desync).
    int64_t join_epoch = session_epoch_utc_ms_;
    fence_epoch_utc_ms_ = time_source_->NowUtcMs();
    int64_t D_ms = fence_epoch_utc_ms_ - join_epoch;
    { std::ostringstream oss;
      oss << "[PipelineManager] INV-FENCE-WALLCLOCK-ANCHOR:"
          << " join_utc_ms=" << join_epoch
          << " fence_epoch_utc_ms=" << fence_epoch_utc_ms_
          << " D_ms=" << D_ms;
      Logger::Info(oss.str()); }

    // Recompute first block's fence with corrected fence epoch.
    if (live_tp()->GetState() == ITickProducer::State::kReady) {
      block_fence_frame_ = compute_fence_frame(live_tp()->GetBlock());
      remaining_block_frames_ = block_fence_frame_ - session_frame_index;
      if (remaining_block_frames_ < 0) remaining_block_frames_ = 0;
      // Re-sync next_seam_frame_ so TAKE fires at the updated fence.
      UpdateNextSeamFrame();
    }
  }
  // P3.3: Seam transition tracking
  std::string prev_completed_block_id;
  int64_t fence_session_frame = -1;
  int64_t fence_pad_counter = 0;  // pad frames since last fence

  // Seam-proof diagnostics: track fence activation for post-emission logging.
  // Answers: did block B activate on the fence tick? Is there cross-block bleed?
  int64_t seam_proof_fence_tick = -1;        // Outgoing block's fence tick
  std::string seam_proof_outgoing_id;        // Outgoing block ID at last fence
  std::string seam_proof_incoming_id;        // Incoming block ID (empty = no swap)
  bool seam_proof_swapped = false;           // Whether swap succeeded
  bool seam_proof_first_frame_logged = true; // First incoming content frame logged?

  // TAKE rotation guard: ensures post-TAKE housekeeping (B→A rotation,
  // A fill stop, outgoing block finalization) fires exactly once per fence.
  bool take_rotated = false;

  // INV-PAD-PRODUCER: Track pad/content transitions for diagnostic logging.
  // Rate-limited: one log line per transition, not per frame.
  bool prev_was_pad = false;

  while (!ctx_->stop_requested.load(std::memory_order_acquire) &&
         !output_detached.load(std::memory_order_acquire)) {
    // INV-TICK-DEADLINE-DISCIPLINE-001 R1 + INV-TICK-MONOTONIC-UTC-ANCHOR-001 R2:
    // Compute monotonic deadline, detect lateness, conditionally sleep.
    // Causal order: compute_deadline → wait/detect → fence → emit → work → increment.
    auto deadline = clock.DeadlineFor(session_frame_index);
    auto now_mono = std::chrono::steady_clock::now();
    bool tick_is_late = (now_mono > deadline);

    if (!tick_is_late) {
      // On-time: sleep until deadline (monotonic enforcement).
      std::this_thread::sleep_until(deadline);
    }
    auto wake_time = std::chrono::steady_clock::now();

    if (tick_is_late) {
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      metrics_.late_ticks_total++;
    }

    if (ctx_->stop_requested.load(std::memory_order_acquire) ||
        output_detached.load(std::memory_order_acquire)) break;

    // INV-FENCE-PTS-DECOUPLE: PTS relative to emission origin.
    // At normal startup origins are 0 → identity.
    int64_t video_pts_90k = clock.FrameIndexToPts90k(
        session_frame_index - pts_origin_frame_index);
    int64_t audio_pts_90k =
        ((audio_samples_emitted - pts_origin_audio_samples) * 90000) /
        buffer::kHouseAudioSampleRate;

    // ==================================================================
    // PRE-TAKE READINESS: Peek only — never consume.
    // B is created in EnsureIncomingBReadyForSeam (called when take_segment).
    // ==================================================================
    const int32_t next_segment_index = current_segment_index_ + 1;
    auto seg_peek = seam_preparer_->PeekSegmentResult();
    if (seg_peek && seg_peek->parent_block_id == live_parent_block_.block_id &&
        seg_peek->parent_segment_index == next_segment_index) {
      // Next segment preroll ready; EnsureIncomingBReadyForSeam consumes at seam tick.
    }

    if (!preview_ && seam_preparer_->HasBlockResult()) {
      int64_t headroom_ms = (block_fence_frame_ != INT64_MAX && block_fence_frame_ > session_frame_index)
          ? static_cast<int64_t>((block_fence_frame_ - session_frame_index) * clock.FrameDurationMs())
          : -1;
      preview_ = TryTakePreviewProducer(headroom_ms);
      if (preview_) {
        auto* ptp = AsTickProducer(preview_.get());
        const bool met = (preview_audio_prime_depth_ms_ >= kMinAudioPrimeMs);
        std::string first_uri(ptp->GetBlock().segments.empty() ? "none" : ptp->GetBlock().segments[0].asset_uri);
        { std::ostringstream oss;
          oss << "[PipelineManager] PREROLL_STATUS"
              << " block=" << ptp->GetBlock().block_id
              << " next_block_opened=Y first_seg_asset_uri=" << (first_uri.empty() ? "empty" : first_uri)
              << " decoder_used=" << (ptp->HasDecoder() ? "Y" : "N")
              << " met_threshold=" << met
              << " depth_ms=" << preview_audio_prime_depth_ms_
              << " wanted_ms=" << kMinAudioPrimeMs;
          Logger::Info(oss.str()); }
      }
    }
    if (preview_ && !preview_video_buffer_ &&
        AsTickProducer(preview_.get())->GetState() == ITickProducer::State::kReady) {
      preview_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(
          video_buffer_->TargetDepthFrames(), video_buffer_->LowWaterFrames());
      preview_video_buffer_->SetBufferLabel("PREVIEW_AUDIO_BUFFER");
      const auto& pcfg = ctx_->buffer_config;
      int pa_target = pcfg.audio_target_depth_ms;
      int pa_low = pcfg.audio_low_water_ms > 0
          ? pcfg.audio_low_water_ms
          : std::max(1, pa_target / 3);
      preview_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
          pa_target, buffer::kHouseAudioSampleRate,
          buffer::kHouseAudioChannels, pa_low);
      auto* preview_tp = AsTickProducer(preview_.get());
      // INV-AUDIO-PREROLL-ISOLATION-001: Snapshot live audio depth before preview fill.
      int live_audio_before = audio_buffer_ ? audio_buffer_->DepthMs() : -1;
      preview_video_buffer_->StartFilling(
          preview_tp, preview_audio_buffer_.get(),
          preview_tp->GetInputFPS(), ctx_->fps,
          &ctx_->stop_requested);
      // INV-AUDIO-PREROLL-ISOLATION-001: Verify live audio was not mutated by preview fill.
      if (audio_buffer_ && live_audio_before >= 0) {
        int live_audio_after = audio_buffer_->DepthMs();
        if (live_audio_after < live_audio_before - 1) {  // 1ms tolerance for concurrent pop
          std::ostringstream oss;
          oss << "[PipelineManager] INV-AUDIO-PREROLL-ISOLATION-001 VIOLATION:"
              << " live_audio_before=" << live_audio_before
              << " live_audio_after=" << live_audio_after
              << " delta=" << (live_audio_after - live_audio_before);
          Logger::Error(oss.str());
        }
      }
      { std::ostringstream oss;
        oss << "[PipelineManager] PREROLL_START"
            << " block=" << preview_tp->GetBlock().block_id
            << " fence_tick=" << FormatFenceTick(block_fence_frame_)
            << " tick=" << session_frame_index
            << " headroom=" << (block_fence_frame_ - session_frame_index);
        Logger::Info(oss.str()); }
    }

    // Step 2 probe: one tick before fence — was next block opened, first seg opened, B primed?
    if (session_frame_index == block_fence_frame_ - 1 && block_fence_frame_ != INT64_MAX) {
      std::string next_block_id("none");
      std::string first_seg_uri;
      bool next_fed = false;
      if (preview_) {
        auto* ptp = AsTickProducer(preview_.get());
        next_block_id = ptp->GetBlock().block_id;
        if (!ptp->GetBlock().segments.empty()) {
          first_seg_uri = ptp->GetBlock().segments[0].asset_uri;
        }
        if (preview_video_buffer_) next_fed = preview_video_buffer_->IsPrimed();
      }
      { std::ostringstream oss;
        oss << "[PipelineManager] PRE_FENCE_TICK"
            << " tick=" << session_frame_index
            << " fence_tick=" << FormatFenceTick(block_fence_frame_)
            << " next_block_id=" << next_block_id
            << " next_block_opened=" << (preview_ != nullptr)
            << " first_seg_asset_uri=" << (first_seg_uri.empty() ? "empty" : first_seg_uri)
            << " next_fed=" << next_fed;
        Logger::Info(oss.str()); }
    }

    // ==================================================================
    // FRAME-ACCURATE TAKE — source selection at the commitment point.
    //
    // The TAKE decision happens HERE, at the pop that binds a frame to
    // tick T.  Both producer A (live) and producer B (preview) may have
    // prerolled buffers.  The selector is purely:
    //   T < fence_tick  → pop from A buffers
    //   T >= fence_tick → pop from B buffers (or pad if B not primed)
    //
    // After the first B-source frame is committed (the TAKE fires),
    // a one-shot rotation moves B→A and updates the fence for the
    // next block.  A's fill thread is stopped; A's buffers are
    // destroyed.  From that point, A is the former B, and the cycle
    // repeats.
    // ==================================================================

    bool is_pad = true;
    VideoBufferFrame vbf;
    int audio_frames_this_tick = 0;
    bool committed_b_frame_this_tick = false;   // Rotation only when we actually committed a B frame.
    bool using_degraded_held_this_tick = false;  // DEGRADED_TAKE_MODE: output held frame + silence this tick.

    // ── TAKE: unified source selection based on tick vs next seam ──
    const bool take = (session_frame_index >= next_seam_frame_);
    const bool take_b = take && (next_seam_type_ == SeamType::kBlock);
    const bool take_segment = take && (next_seam_type_ == SeamType::kSegment);

    // Policy B: TAKE_READINESS — log audio headroom at the moment of TAKE.
    if (take_b && !take_rotated && preview_) {
      const bool met = (preview_audio_prime_depth_ms_ >= kMinAudioPrimeMs);
      { std::ostringstream oss;
        oss << "[PipelineManager] TAKE_READINESS"
            << " block=" << AsTickProducer(preview_.get())->GetBlock().block_id
            << " depth_ms_at_take=" << preview_audio_prime_depth_ms_
            << " wanted_ms=" << kMinAudioPrimeMs
            << " met_threshold=" << met;
        Logger::Info(oss.str()); }
    }

    VideoLookaheadBuffer* v_src = nullptr;
    if (take_b && preview_video_buffer_) {
      v_src = preview_video_buffer_.get();        // Block swap: B buffers
    } else if (take_segment && segment_b_video_buffer_) {
      v_src = segment_b_video_buffer_.get();  // Segment seam path (video may pre-roll on B)
    } else if (take_b) {
      v_src = preview_video_buffer_.get();         // Block swap: may be null
    } else {
      v_src = video_buffer_.get();                 // No swap: A buffers
    }

    // INV-SEAM-AUDIO-001: segment-B audio must not be consumed by tick loop
    // until SEGMENT_TAKE_COMMIT succeeds.
    bool segment_swap_committed = false;
    AudioLookaheadBuffer* a_src = SelectAudioSourceForTick(
        take_b,
        take_segment,
        segment_swap_committed,
        audio_buffer_.get(),
        preview_audio_buffer_.get(),
        segment_b_audio_buffer_.get());
    const char* commit_slot = take_b ? "B" : (take_segment ? "S" : "A");
    // Authoritative TAKE slot source for fingerprint:
    //   'A' = live buffer slot, 'B' = preview buffer slot, 'P' = pad.
    // This is a slot identifier, not a block identity.  After PADDED_GAP
    // exit, the new block occupies the live slot and is labeled 'A'.
    // Use active_block_id (from live_tp()->GetBlock()) for block identity.
    char take_source_char = 'P';

    // FENCE_TRANSITION probe: at block fence (take_b && !take_rotated), log
    // current/next block, whether B is fed, producer/decoder state, first-seg uri.
    if (take_b && !take_rotated) {
      std::string next_block_id("none");
      bool next_fed = false;
      std::string producer_state_str("none");
      bool decoder_state = false;
      std::string first_seg_asset_uri;
      if (preview_) {
        auto* ptp = AsTickProducer(preview_.get());
        next_block_id = ptp->GetBlock().block_id;
        producer_state_str = (ptp->GetState() == ITickProducer::State::kReady) ? "kReady" : "other";
        decoder_state = ptp->HasDecoder();
        if (!ptp->GetBlock().segments.empty()) {
          first_seg_asset_uri = ptp->GetBlock().segments[0].asset_uri;
        }
        if (preview_video_buffer_) next_fed = preview_video_buffer_->IsPrimed();
      }
      { std::ostringstream oss;
        oss << "[PipelineManager] FENCE_TRANSITION"
            << " tick=" << session_frame_index
            << " fence_tick=" << FormatFenceTick(block_fence_frame_)
            << " current_block_id=" << live_parent_block_.block_id
            << " next_block_id=" << next_block_id
            << " next_block_fed=" << next_fed
            << " producer_state=" << producer_state_str
            << " decoder_state=" << (decoder_state ? "has_decoder" : "no_decoder")
            << " first_seg_asset_uri=" << (first_seg_asset_uri.empty() ? "empty" : first_seg_asset_uri);
        Logger::Info(oss.str()); }

      // Preview ownership: preroll_owner_block_id must match next_block_id.
      if (preview_ && !expected_preroll_block_id_.empty() && next_block_id != expected_preroll_block_id_) {
        { std::ostringstream oss;
          oss << "[PipelineManager] PREROLL_OWNERSHIP_VIOLATION"
              << " expected=" << expected_preroll_block_id_
              << " actual_next=" << next_block_id
              << " tick=" << session_frame_index;
          Logger::Error(oss.str()); }
      }
    }

    // INV-PREROLL-READY-001: On the fence tick, B SHOULD be primed.
    // If it's not, log the failure mode for diagnostics.  The TAKE
    // falls through to pad — no correctness violation, but a missed
    // preroll that should be investigated.
    if (take_b && (!v_src || !v_src->IsPrimed()) && !take_rotated) {
      { std::ostringstream oss;
        oss << "[PipelineManager] INV-PREROLL-READY-001: B NOT PRIMED at fence"
            << " tick=" << session_frame_index
            << " fence_tick=" << FormatFenceTick(block_fence_frame_)
            << " preview_exists=" << (preview_ != nullptr)
            << " preview_vbuf=" << (preview_video_buffer_ != nullptr)
            << " seam_has_block=" << seam_preparer_->HasBlockResult();
        Logger::Warn(oss.str()); }
    }

    // INV-VIDEO-LOOKAHEAD-001: Sample IsPrimed BEFORE TryPopFrame to prevent
    // TOCTOU race.  The fill thread may push between a failed TryPopFrame and
    // a subsequent IsPrimed check, causing a false underflow detection.
    // Sampling first is safe: only the tick loop pops, so if IsPrimed is true
    // the frame is guaranteed to still be in the deque when TryPopFrame runs.
    const bool a_was_primed = (!take_b && v_src) ? v_src->IsPrimed() : false;

    if (v_src && v_src->TryPopFrame(vbf)) {
      session_encoder->encodeFrame(vbf.video, video_pts_90k);
      is_pad = false;
      take_source_char = take_b ? 'B' : 'A';
      last_good_video_frame_ = vbf.video;
      has_last_good_video_frame_ = true;
      last_good_asset_uri_ = vbf.asset_uri;
      last_good_block_id_ = live_tp()->GetState() == ITickProducer::State::kReady
          ? live_tp()->GetBlock().block_id : std::string();
      last_good_offset_ms_ = vbf.block_ct_ms;
      if (!vbf.video.data.empty()) {
        size_t y_size = static_cast<size_t>(vbf.video.width * vbf.video.height);
        last_good_y_crc32_ = CRC32YPlane(vbf.video.data.data(),
                                        std::min(y_size, vbf.video.data.size()));
      } else {
        last_good_y_crc32_ = 0;
      }
      if (take_b) {
        committed_b_frame_this_tick = true;
        degraded_take_active_ = false;  // Exiting degraded: B frame committed.
      }
    } else if (take_b) {
      // B not primed or empty at fence — PADDED_GAP.
      const char* pad_cause = "no_preview_buffers";
      if (v_src) {
        if (!v_src->IsPrimed())
          pad_cause = "buffer_not_primed";
        else
          pad_cause = "buffer_empty_after_primed";
      }
      bool first_seg_is_pad = false;
      if (preview_ && !AsTickProducer(preview_.get())->GetBlock().segments.empty()) {
        first_seg_is_pad =
            (AsTickProducer(preview_.get())->GetBlock().segments[0].segment_type == SegmentType::kPad);
      }
      // When preview_ was discarded (zombie), we don't have segment info; use submitted block.
      bool next_block_first_seg_content = preview_ ? !first_seg_is_pad : expected_preroll_first_seg_content_;

      // INV-FENCE-TAKE-READY-001 / DEGRADED_TAKE_MODE: content-first but B not primed at fence.
      // Do not crash. Log violation once per fence event; enter degraded take (hold last A frame + silence).
      if (next_block_first_seg_content) {
        const bool entering_degraded = !degraded_take_active_;
        if (entering_degraded) {
          degraded_entered_frame_index_ = session_frame_index;
          degraded_escalated_to_standby_ = false;
          int64_t headroom_ms = (block_fence_frame_ != INT64_MAX && block_fence_frame_ > session_frame_index)
              ? static_cast<int64_t>((block_fence_frame_ - session_frame_index) * clock.FrameDurationMs())
              : -1;
          { std::ostringstream oss;
            oss << "[PipelineManager] INV-FENCE-TAKE-READY-001 VIOLATION DEGRADED_TAKE_MODE"
                << " tick=" << session_frame_index
                << " fence_tick=" << FormatFenceTick(block_fence_frame_)
                << " next_block_id=" << (preview_ ? AsTickProducer(preview_.get())->GetBlock().block_id : expected_preroll_block_id_)
                << " cause=" << pad_cause
                << " headroom_ms=" << headroom_ms;
            Logger::Error(oss.str()); }
        }
        degraded_take_active_ = true;
        // Bounded escalation: after HOLD_MAX_MS switch to standby (slot 'S') — continuous output, no tick skip.
        const int64_t degraded_elapsed_ms = (session_frame_index - degraded_entered_frame_index_) *
            static_cast<int64_t>(clock.FrameDurationMs());
        if (degraded_elapsed_ms >= kDegradedHoldMaxMs) {
          degraded_escalated_to_standby_ = true;
        }
        if (degraded_escalated_to_standby_) {
          session_encoder->encodeFrame(pad_producer_->VideoFrame(), video_pts_90k);
          is_pad = true;
          take_source_char = 'S';  // Standby (bounded hold escalation)
          // Audio: silence handled below in audio path
        } else if (has_last_good_video_frame_) {
          session_encoder->encodeFrame(last_good_video_frame_, video_pts_90k);
          is_pad = false;
          take_source_char = 'H';  // Held frame (degraded)
          using_degraded_held_this_tick = true;
        }
        // else: no held frame (should not happen after first real frame); fall through to FENCE_PAD_CAUSE
      }

      if (!using_degraded_held_this_tick && !degraded_escalated_to_standby_) {
        { std::ostringstream oss;
          oss << "[PipelineManager] FENCE_PAD_CAUSE"
            << " tick=" << session_frame_index
            << " cause=" << pad_cause
            << " segment_type_first_seg=" << (first_seg_is_pad ? "PAD" : "content")
            << " decoder_returned_empty=" << (preview_ && AsTickProducer(preview_.get())->HasDecoder() && v_src && !v_src->IsPrimed() ? "likely" : "n/a");
        Logger::Info(oss.str()); }
      }
    } else if (a_was_primed) {
      // A was primed before TryPopFrame, but pop still failed → genuine underflow.
      { std::ostringstream oss;
        oss << "[PipelineManager] INV-VIDEO-LOOKAHEAD-001: UNDERFLOW"
            << " frame=" << session_frame_index
            << " buffer_depth=" << v_src->DepthFrames()
            << " total_pushed=" << v_src->TotalFramesPushed()
            << " total_popped=" << v_src->TotalFramesPopped();
        Logger::Error(oss.str()); }
      { std::lock_guard<std::mutex> lock(metrics_mutex_); metrics_.detach_count++; }
      ctx_->stop_requested.store(true, std::memory_order_release);
      break;
    }
    // else: A not primed (no block loaded yet or buffer warming up) — pad.

    // INV-PAD-PRODUCER-007: Content-before-pad gate.
    // Do not emit pad until at least one real content frame has been committed,
    // UNLESS no decoder is available (unresolvable asset or no block loaded).
    // This ensures the encoder's first IDR comes from real content when possible,
    // while still allowing pad-only sessions to produce output.
    if (is_pad && !first_real_frame_committed) {
      // Gate opens if: (a) live has a decoder that might produce frames soon
      // (video buffer is priming), AND we haven't seen a real frame yet.
      // Gate stays closed ONLY while a decoder exists and content is expected.
      bool decoder_might_produce = (live_tp()->GetState() == ITickProducer::State::kReady
                                    && live_tp()->HasDecoder()
                                    && video_buffer_ && !video_buffer_->IsPrimed());
      if (decoder_might_produce) {
        // Skip this tick — content is priming and should arrive shortly.
        continue;
      }
      // No decoder, or buffer already primed (but popped nothing = underflow
      // handled above), or no block loaded — allow pad emission.
    }
    if (!is_pad && !first_real_frame_committed) {
      first_real_frame_committed = true;
    }

    // INV-PAD-PRODUCER: Log TAKE pad/content transitions (rate-limited).
    if (is_pad && !prev_was_pad) {
      { std::ostringstream oss;
        oss << "[PipelineManager] TAKE_PAD_ENTER"
            << " tick=" << session_frame_index
            << " slot=" << commit_slot;
        Logger::Info(oss.str()); }
    } else if (!is_pad && prev_was_pad) {
      { std::ostringstream oss;
        oss << "[PipelineManager] TAKE_PAD_EXIT"
            << " tick=" << session_frame_index
            << " slot=" << commit_slot
            << " block=" << (live_tp()->GetState() == ITickProducer::State::kReady
                ? live_tp()->GetBlock().block_id : "none");
        Logger::Info(oss.str()); }
    }
    prev_was_pad = is_pad;

    // TAKE commit log: emitted on every fence-adjacent tick and the
    // first 3 ticks of each block for seam verification.
    if (take_b || session_frame_index == block_fence_frame_ - 1 ||
        (session_frame_index < block_fence_frame_ &&
         session_frame_index >= block_fence_frame_ - 3)) {
      std::string block_id;
      std::string asset_uri;
      if (take_b && preview_ &&
          AsTickProducer(preview_.get())->GetState() == ITickProducer::State::kReady) {
        block_id = AsTickProducer(preview_.get())->GetBlock().block_id;
      } else       if (!take_b &&
                 live_tp()->GetState() == ITickProducer::State::kReady) {
        block_id = live_tp()->GetBlock().block_id;
      }
      if (using_degraded_held_this_tick) {
        asset_uri = "held";
      } else if (!is_pad) {
        asset_uri = vbf.asset_uri;
      }
      { std::ostringstream oss;
        oss << "[PipelineManager] TAKE_COMMIT"
            << " tick=" << session_frame_index
            << " fence_tick=" << FormatFenceTick(block_fence_frame_)
            << " slot=" << commit_slot
            << " is_pad=" << is_pad
            << " block=" << (block_id.empty() ? "none" : block_id)
            << " asset=" << (asset_uri.empty() ? (is_pad ? "pad" : "unknown") : asset_uri)
            << " v_buf_depth=" << (v_src ? v_src->DepthFrames() : -1)
            << " a_buf_depth_ms=" << (a_src ? a_src->DepthMs() : -1);
        Logger::Info(oss.str()); }
    }

    // ==================================================================
    // POST-TAKE ROTATION: Execute when fence has fired and we are ready to
    // transition.  Two cases:
    //   1. B committed a frame this tick (normal seamless swap).
    //   2. B failed to prime (pad at fence) — fence has fired, block A is
    //      done, enter PADDED_GAP immediately.  Do NOT loop in fence-pad
    //      state; the old block ended, respect the timeline and move forward.
    //      INV-BLOCK-WALLFENCE-001: fence timing is respected (fence already fired).
    //      INV-TICK-GUARANTEED-OUTPUT: pad continues under gap mode.
    // ==================================================================
    const bool fence_fired_b_missing = take_b && !take_rotated && !committed_b_frame_this_tick;
    if (take_b && !take_rotated && (committed_b_frame_this_tick || fence_fired_b_missing)) {
      take_rotated = true;

      // Step 1: Join PREVIOUS fence's deferred fill thread.
      { auto t0 = std::chrono::steady_clock::now();
        { std::ostringstream oss;
          oss << "[PipelineManager] CLEANUP_DEFERRED_FILL_BEGIN tick="
              << session_frame_index << " context=block_take";
          Logger::Info(oss.str()); }
        CleanupDeferredFill();
        auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t0).count();
        { std::ostringstream oss;
          oss << "[PipelineManager] CLEANUP_DEFERRED_FILL_END tick="
              << session_frame_index << " context=block_take dt_ms=" << dt_ms;
          Logger::Info(oss.str()); }
      }

      // Step 1b: Guard against stale preview buffers.
      // TryLoadLiveProducer may have consumed preview_ (moved to live_)
      // but left preview_video_buffer_ with a running fill thread.
      // Stop and clear them so the swap logic below sees a consistent state.
      if (preview_video_buffer_ && !preview_) {
        { auto t0 = std::chrono::steady_clock::now();
          { std::ostringstream oss;
            oss << "[PipelineManager] STOP_FILLING_BEGIN context=stale_preview_block_take tick="
                << session_frame_index;
            Logger::Info(oss.str()); }
          preview_video_buffer_->StopFilling(/*flush=*/true);
          auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
              std::chrono::steady_clock::now() - t0).count();
          { std::ostringstream oss;
            oss << "[PipelineManager] STOP_FILLING_END context=stale_preview_block_take tick="
                << session_frame_index << " dt_ms=" << dt_ms;
            Logger::Info(oss.str()); }
        }
        preview_video_buffer_.reset();
        preview_audio_buffer_.reset();
      }

      // Step 2: Move outgoing buffers out — do not mutate in place.
      // The fill thread may still be running; mutating the buffer while
      // the fill thread writes to it is a data race.
      auto outgoing_video_buffer = std::move(video_buffer_);
      auto outgoing_audio_buffer = std::move(audio_buffer_);
      auto detached = outgoing_video_buffer->StopFillingAsync(/*flush=*/true);

      // Step 3: Snapshot outgoing block and finalize accumulator.
      // INV-BLOCK-IDENTITY-001:
      // Block identity is owned by PipelineManager and must survive producer swaps.
      // Segment operations (including MISS PAD fallback) are allowed to replace
      // live_ with a different producer, but block completion identity must remain
      // stable and reflect the block that was activated at take-commit time.
      // Do NOT derive block identity from live_->GetBlock().
      const FedBlock outgoing_block = live_parent_block_;
      const int64_t outgoing_fence_frame = block_fence_frame_;
      std::optional<BlockPlaybackSummary> outgoing_summary;
      std::optional<BlockPlaybackProof> outgoing_proof;
      int64_t ct_at_fence_ms = -1;
      if (!block_acc.block_id.empty()) {
        auto summary = block_acc.Finalize();
        ct_at_fence_ms = summary.last_block_ct_ms;
        auto proof = BuildPlaybackProof(
            outgoing_block, summary, clock.FrameDurationMs(),
            block_acc.GetSegmentProofs());
        outgoing_summary = std::move(summary);
        outgoing_proof = std::move(proof);
      }

      // Step 4: Save old live_ for deferred cleanup.
      auto outgoing_producer = std::move(live_);

      // Step 5: Rotate B → A.
      bool swapped = false;
      if (preview_video_buffer_) {
        // B buffers become the new A buffers.
        video_buffer_ = std::move(preview_video_buffer_);
        video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");
        audio_buffer_ = std::move(preview_audio_buffer_);
        live_ = std::move(preview_);
        swapped = true;
      } else {
        // B was never prerolled — check for late preview or sync fallback.
        // This mirrors the old fence fallback paths.
        if (preview_ &&
            AsTickProducer(preview_.get())->GetState() == ITickProducer::State::kReady) {
          live_ = std::move(preview_);
          swapped = true;
        }
        if (!swapped) {
          auto preloaded = TryTakePreviewProducer();
          if (preloaded &&
              AsTickProducer(preloaded.get())->GetState() == ITickProducer::State::kReady) {
            live_ = std::move(preloaded);
            swapped = true;
          }
        }
        // INV-FENCE-FALLBACK-SYNC-001: Synchronous queue drain is mandatory.
        // When preload missed the fence and queue is non-empty, pop and sync-load
        // the next block instead of entering PADDED_GAP.  This is the only path
        // that lets depth>=3 eliminate starvation-induced gaps.
        if (!swapped) {
          FedBlock fallback_block;
          bool got_block = false;
          {
            std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
            if (!ctx_->block_queue.empty()) {
              fallback_block = ctx_->block_queue.front();
              ctx_->block_queue.erase(ctx_->block_queue.begin());
              got_block = true;
            }
          }
          if (got_block) {
            { std::ostringstream oss;
              oss << "[PipelineManager] INV-FENCE-FALLBACK-SYNC-001"
                  << " block_id=" << fallback_block.block_id
                  << " reason=preview_not_ready"
                  << " fence_frame=" << session_frame_index;
              Logger::Info(oss.str()); }
            auto fresh = std::make_unique<TickProducer>(
                ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
            AsTickProducer(fresh.get())->AssignBlock(fallback_block);
            live_ = std::move(fresh);
            swapped = true;
          }
        }
        // If swapped via fallback, create fresh A buffers and start fill.
        // Outgoing buffers are moved out; do not reuse them.
        if (swapped) {
          video_buffer_ = std::make_unique<VideoLookaheadBuffer>(
              outgoing_video_buffer ? outgoing_video_buffer->TargetDepthFrames() : 15,
              outgoing_video_buffer ? outgoing_video_buffer->LowWaterFrames() : 5);
          video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");
          const auto& fbcfg = ctx_->buffer_config;
          int fa_target = fbcfg.audio_target_depth_ms;
          int fa_low = fbcfg.audio_low_water_ms > 0
              ? fbcfg.audio_low_water_ms
              : std::max(1, fa_target / 3);
          audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
              fa_target, buffer::kHouseAudioSampleRate,
              buffer::kHouseAudioChannels, fa_low);
          video_buffer_->StartFilling(
              AsTickProducer(live_.get()), audio_buffer_.get(),
              AsTickProducer(live_.get())->GetInputFPS(), ctx_->fps,
              &ctx_->stop_requested);
        }
      }

      if (!swapped) {
        // No B available — PADDED_GAP.
        live_ = std::make_unique<TickProducer>(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
        // Fresh buffers — outgoing buffers will die with the deferred fill thread.
        video_buffer_ = std::make_unique<VideoLookaheadBuffer>(15, 5);
        video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");
        {
          const auto& gbcfg = ctx_->buffer_config;
          int ga_target = gbcfg.audio_target_depth_ms;
          int ga_low = gbcfg.audio_low_water_ms > 0
              ? gbcfg.audio_low_water_ms
              : std::max(1, ga_target / 3);
          audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
              ga_target, buffer::kHouseAudioSampleRate,
              buffer::kHouseAudioChannels, ga_low);
        }
        block_fence_frame_ = INT64_MAX;
        next_seam_frame_ = INT64_MAX;
        next_seam_type_ = SeamType::kNone;
        past_fence = true;
        { std::lock_guard<std::mutex> lock(metrics_mutex_);
          metrics_.fence_preload_miss_count++;
          metrics_.padded_gap_count++; }
        { std::ostringstream oss;
          oss << "[PipelineManager] PADDED_GAP_ENTER"
              << " fence_frame=" << session_frame_index
              << " outgoing=" << (outgoing_summary ? outgoing_summary->block_id : "none");
          Logger::Info(oss.str()); }
      }

      // INV-EVIDENCE-ORDER-001: BLOCK_FENCE(A) must fire BEFORE BLOCK_START(B).
      // Emit completion evidence for the outgoing block before activating the
      // new one.  This guarantees the legal evidence order:
      //   BLOCK_START(A) → ... → BLOCK_FENCE(A) → BLOCK_START(B)
      if (callbacks_.on_block_completed) {
        callbacks_.on_block_completed(outgoing_block, ct_at_fence_ms, session_frame_index);
      }

      if (swapped) {
        block_fence_frame_ = compute_fence_frame(live_tp()->GetBlock());
        remaining_block_frames_ = block_fence_frame_ - session_frame_index;
        if (remaining_block_frames_ < 0) remaining_block_frames_ = 0;
        {
          std::lock_guard<std::mutex> lock(metrics_mutex_);
          metrics_.source_swap_count++;
        }
        past_fence = false;

        block_acc.Reset(live_tp()->GetBlock().block_id);
        emit_block_start("take");

        // INV-SEAM-SEG: Block activation — extract boundaries and compute segment seam frames.
        block_activation_frame_ = session_frame_index;
        live_parent_block_ = live_tp()->GetBlock();
        live_boundaries_ = AsTickProducer(live_.get())->GetBoundaries();
        ComputeSegmentSeamFrames();
        ArmSegmentPrep(session_frame_index);

        // Block is now LIVE — notify subscribers.
        if (callbacks_.on_block_started) {
          BlockActivationContext actx;
          actx.timeline_frame_index = session_frame_index;
          actx.block_fence_tick = block_fence_frame_;
          actx.utc_ms = time_source_->NowUtcMs();
          callbacks_.on_block_started(live_parent_block_, actx);
        }

        // Fire on_segment_start for the first segment of the new block.
        if (callbacks_.on_segment_start) {
          callbacks_.on_segment_start(-1, 0, live_parent_block_, session_frame_index);
        }

        // Begin segment proof tracking for first segment.
        if (!live_parent_block_.segments.empty()) {
          const auto& seg0 = live_parent_block_.segments[0];
          block_acc.BeginSegment(
              0, seg0.asset_uri,
              static_cast<int64_t>(std::ceil(
                  static_cast<double>(seg0.segment_duration_ms) /
                  static_cast<double>(clock.FrameDurationMs()))),
              seg0.segment_type, seg0.event_id);
        }

        int audio_depth = audio_buffer_->DepthMs();
        if (audio_depth < kMinAudioPrimeMs) {
          { std::ostringstream oss;
            oss << "[PipelineManager] INV-AUDIO-PRIME-001 WARN: audio_depth_ms="
                << audio_depth << " required=" << kMinAudioPrimeMs
                << " at fence frame " << session_frame_index
                << " block=" << live_tp()->GetBlock().block_id
                << " — safety-net silence will cover";
            Logger::Warn(oss.str()); }
        }

        // Policy B: track degraded TAKEs where audio prime was below threshold.
        // Uses preview_audio_prime_depth_ms_ captured at preloader TakeSource time.
        if (preview_audio_prime_depth_ms_ < kMinAudioPrimeMs) {
          { std::ostringstream oss;
            oss << "[PipelineManager] DEGRADED_TAKE"
                << " block=" << live_tp()->GetBlock().block_id
                << " prime_depth_ms=" << preview_audio_prime_depth_ms_
                << " wanted_ms=" << kMinAudioPrimeMs
                << " audio_buf_depth_ms=" << audio_depth;
            Logger::Warn(oss.str()); }
          std::lock_guard<std::mutex> lock(metrics_mutex_);
          metrics_.degraded_take_count++;
        }

        TryKickoffBlockPreload(session_frame_index);
      }

      // Step 6: Store deferred thread + producer + buffers for later cleanup.
      deferred_fill_thread_ = std::move(detached.thread);
      deferred_producer_ = std::move(outgoing_producer);
      deferred_video_buffer_ = std::move(outgoing_video_buffer);
      deferred_audio_buffer_ = std::move(outgoing_audio_buffer);

      // Step 7: Emit finalization logs.
      if (outgoing_summary) {
        Logger::Info(FormatPlaybackSummary(*outgoing_summary));
        if (callbacks_.on_block_summary) {
          callbacks_.on_block_summary(*outgoing_summary);
        }
      }
      if (outgoing_proof) {
        Logger::Info(FormatPlaybackProof(*outgoing_proof));
        if (callbacks_.on_playback_proof) {
          callbacks_.on_playback_proof(*outgoing_proof);
        }
      }

      if (outgoing_summary) {
        int64_t base_offset = !outgoing_block.segments.empty()
            ? outgoing_block.segments[0].asset_start_offset_ms : 0;
        std::ostringstream oss;
        oss << "[PipelineManager] BLOCK_COMPLETE"
            << " block=" << outgoing_summary->block_id
            << " fence_frame=" << outgoing_fence_frame
            << " emitted=" << outgoing_summary->frames_emitted
            << " pad=" << outgoing_summary->pad_frames
            << " asset=" << (!outgoing_summary->asset_uris.empty()
                ? outgoing_summary->asset_uris[0] : "pad");
        if (outgoing_summary->first_block_ct_ms >= 0) {
          oss << " range_ms="
              << (base_offset + outgoing_summary->first_block_ct_ms)
              << "->"
              << (base_offset + outgoing_summary->last_block_ct_ms);
        }
        Logger::Info(oss.str());
      }

      {
        int64_t now_utc_ms = time_source_->NowUtcMs();
        int64_t delta_ms = now_utc_ms - outgoing_block.end_utc_ms;
        std::ostringstream oss;
        oss << "[PipelineManager] INV-BLOCK-WALLFENCE-001: FENCE"
            << " block=" << outgoing_block.block_id
            << " scheduled_end_ms=" << outgoing_block.end_utc_ms
            << " actual_ms=" << now_utc_ms
            << " delta_ms=" << delta_ms
            << " ct_at_fence_ms=" << ct_at_fence_ms
            << " fence_frame=" << outgoing_fence_frame
            << " session_frame=" << session_frame_index
            << " remaining_budget=" << remaining_block_frames_;
        Logger::Info(oss.str());
      }

      // Task 4: Structured fence proof summary — single source of seam evidence.
      {
        int64_t fence_tick_val = compute_fence_frame(outgoing_block);
        int64_t emitted = outgoing_summary ? outgoing_summary->frames_emitted : 0;
        int64_t pad = outgoing_summary ? outgoing_summary->pad_frames : 0;
        // truncated_by_fence: content was still available but fence ended the block.
        // Signal: zero pad frames AND emitted < fence tick (content cut short).
        bool truncated = (pad == 0 && emitted < fence_tick_val);
        // early_exhaustion: content ran out before fence — had to pad.
        bool exhausted = (pad > 0);
        std::ostringstream oss;
        oss << "[FENCE_PROOF]"
            << " block_id=" << outgoing_block.block_id
            << " swap_tick=" << session_frame_index
            << " fence_tick=" << fence_tick_val
            << " ticks_emitted=" << emitted
            << " frames_emitted=" << emitted
            << " audio_depth_at_fence=" << (outgoing_audio_buffer
                ? outgoing_audio_buffer->DepthMs() : -1)
            << " truncated_by_fence=" << (truncated ? "Y" : "N")
            << " early_exhaustion=" << (exhausted ? "Y" : "N")
            << " primed_success=" << (swapped ? "Y" : "N");
        Logger::Info(oss.str());
      }

      prev_completed_block_id = outgoing_block.block_id;
      fence_session_frame = session_frame_index;
      fence_pad_counter = 0;

      if (swapped && !prev_completed_block_id.empty()) {
        SeamTransitionLog seam;
        seam.from_block_id = prev_completed_block_id;
        seam.to_block_id = live_tp()->GetBlock().block_id;
        seam.fence_frame = fence_session_frame;
        seam.pad_frames_at_fence = 0;
        seam.seamless = true;
        Logger::Info(FormatSeamTransition(seam));
        if (callbacks_.on_seam_transition) {
          callbacks_.on_seam_transition(seam);
        }
      }

      // NOTE: on_block_completed already fired above (INV-EVIDENCE-ORDER-001).
      {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.total_blocks_executed++;
      }
      ctx_->blocks_executed++;

      seam_proof_fence_tick = compute_fence_frame(outgoing_block);
      seam_proof_outgoing_id = outgoing_block.block_id;
      seam_proof_incoming_id = swapped ? live_tp()->GetBlock().block_id : "";
      seam_proof_swapped = swapped;
      seam_proof_first_frame_logged = false;

      { std::ostringstream oss;
        oss << "[PipelineManager] SEAM_PROOF_FENCE"
            << " tick=" << session_frame_index
            << " fence_tick=" << seam_proof_fence_tick
            << " outgoing=" << seam_proof_outgoing_id
            << " incoming=" << (seam_proof_incoming_id.empty()
                ? "none" : seam_proof_incoming_id)
            << " swapped=" << swapped
            << " video_pts_90k=" << video_pts_90k
            << " audio_pts_90k=" << audio_pts_90k
            << " av_delta_90k=" << (video_pts_90k - audio_pts_90k)
            << " video_buf_depth=" << video_buffer_->DepthFrames()
            << " audio_buf_depth_ms=" << audio_buffer_->DepthMs();
        Logger::Info(oss.str()); }

      // Reset take_rotated for next fence cycle.
      take_rotated = false;
    }

    // ==================================================================
    // SEGMENT POST-TAKE: On the segment seam tick, swap segment preview
    // into live.  Only fires when take_segment is true (not a block seam).
    // Gate: defer swap until incoming segment meets minimum readiness.
    // ==================================================================
    if (take_segment) {
      const int32_t to_seg = current_segment_index_ + 1;
      EnsureIncomingBReadyForSeam(to_seg, session_frame_index);
      std::optional<IncomingState> incoming = GetIncomingSegmentState(to_seg);

      if (!incoming) {
        // No incoming source (no segment B, no worker result).
        if (last_logged_defer_seam_frame_ != next_seam_frame_) {
          last_logged_defer_seam_frame_ = next_seam_frame_;
          { std::ostringstream oss;
            oss << "[PipelineManager] SEGMENT_SWAP_DEFERRED"
                << " reason=no_incoming"
                << " incoming_audio_ms=-1"
                << " incoming_video_frames=-1"
                << " tick=" << session_frame_index;
            Logger::Info(oss.str()); }
        }
        // Keep current live; do not call PerformSegmentSwap.
      } else if (!IsIncomingSegmentEligibleForSwap(*incoming)) {
        if (last_logged_defer_seam_frame_ != next_seam_frame_) {
          last_logged_defer_seam_frame_ = next_seam_frame_;
          { std::ostringstream oss;
            oss << "[PipelineManager] SEGMENT_SWAP_DEFERRED"
                << " reason=not_ready"
                << " incoming_audio_ms=" << incoming->incoming_audio_ms
                << " incoming_video_frames=" << incoming->incoming_video_frames
                << " tick=" << session_frame_index;
            Logger::Info(oss.str()); }
        }
        // Keep current live; do not call PerformSegmentSwap.
      } else {
        // Eligible: perform swap.
        last_logged_defer_seam_frame_ = -1;  // Reset so next seam can log if deferred.
        // SEGMENT_TAKE_COMMIT: log decision state BEFORE swap (a_src still valid).
        { std::ostringstream oss;
          const char* to_type_str =
              (to_seg < static_cast<int32_t>(live_parent_block_.segments.size()))
                  ? SegmentTypeName(live_parent_block_.segments[to_seg].segment_type)
                  : "OUT_OF_RANGE";
          oss << "[PipelineManager] SEGMENT_TAKE_COMMIT"
              << " tick=" << session_frame_index
              << " from_segment=" << current_segment_index_
              << " to_segment=" << to_seg << " (" << to_type_str << ")"
              << " is_pad=" << is_pad
              << " segment_b_audio_depth_ms=" << incoming->incoming_audio_ms
              << " segment_b_video_depth_frames=" << incoming->incoming_video_frames
              << " audio_depth_ms=" << (a_src ? a_src->DepthMs() : -1)
              << " audio_gen=" << (a_src ? a_src->CurrentGeneration() : 0)
              << " asset=" << (is_pad ? "pad" : (vbf.asset_uri.empty() ? "none" : vbf.asset_uri))
              << " seg_b_ready=" << (segment_b_video_buffer_ != nullptr);
          Logger::Info(oss.str()); }

        PerformSegmentSwap(session_frame_index);

        // INV-SEAM-AUDIO-001: only after commit may tick loop consume segment-B audio.
        segment_swap_committed = true;
        a_src = SelectAudioSourceForTick(
            take_b,
            take_segment,
            segment_swap_committed,
            audio_buffer_.get(),
            preview_audio_buffer_.get(),
            segment_b_audio_buffer_.get());
        { std::ostringstream oss;
          oss << "[PipelineManager] SEGMENT_SWAP_POST"
              << " tick=" << session_frame_index
              << " live_audio_depth_ms=" << (a_src ? a_src->DepthMs() : -1);
          Logger::Info(oss.str()); }

        // Begin segment proof tracking for the new segment.
        if (current_segment_index_ < static_cast<int32_t>(live_parent_block_.segments.size())) {
          const auto& seg = live_parent_block_.segments[current_segment_index_];
          block_acc.BeginSegment(
              current_segment_index_, seg.asset_uri,
              static_cast<int64_t>(std::ceil(
                  static_cast<double>(seg.segment_duration_ms) /
                  static_cast<double>(clock.FrameDurationMs()))),
              seg.segment_type, seg.event_id);
        }
      }
    }

    if (is_pad) {
      // INV-PAD-PRODUCER-005: TAKE selects PadProducer at commitment point.
      // Same encodeFrame path as content (single commitment path).
      // INV-PAD-PRODUCER-001: No per-tick allocation — pre-allocated frames.
#ifdef RETROVUE_DEBUG_PAD_EMIT
      { std::ostringstream oss;
        oss << "[PipelineManager] DBG-PAD-EMIT"
            << " frame=" << session_frame_index
            << " slot=" << take_source_char
            << " y_crc32=0x" << std::hex << pad_producer_->VideoCRC32() << std::dec
            << " video_pts_90k=" << video_pts_90k;
        Logger::Info(oss.str()); }
#endif
      session_encoder->encodeFrame(pad_producer_->VideoFrame(), video_pts_90k);

      // INV-PAD-PRODUCER-002: Audio uses same rational accumulator as content.
      int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
      int64_t next_total =
          ((audio_ticks_emitted + 1) * sr * ctx_->fps_den) / ctx_->fps_num;
      int pad_samples_this_tick =
          static_cast<int>(next_total - audio_buffer_samples_emitted);

      // Zero-alloc: reuse pre-allocated silence buffer, just set nb_samples.
      auto& pad_audio = pad_producer_->SilenceTemplate();
      pad_audio.nb_samples = pad_samples_this_tick;
      session_encoder->encodeAudioFrame(pad_audio, audio_pts_90k,
                                        /*is_silence_pad=*/true);

      audio_samples_emitted += pad_samples_this_tick;
      audio_buffer_samples_emitted += pad_samples_this_tick;
      audio_ticks_emitted++;
      audio_frames_this_tick = 1;

      if (past_fence) {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.fence_pad_frames_total++;
      }

      // OUT-SEG-005b: Pad tick = fallback (no real decoded audio).
      current_consecutive_fallback_ticks++;
    }

    // ==================================================================
    // INV-AUDIO-LOOKAHEAD-001: Centralized audio emission from buffer.
    // On every non-pad tick, pop exactly one tick's worth of samples
    // from the AudioLookaheadBuffer.  Audio is only pushed to the buffer
    // on decode ticks (cadence repeats produce no audio); the buffer
    // accumulates enough to cover repeat ticks.
    // Underflow = hard fault → session stop.
    //
    // FENCE AUDIO CONTINUITY: After audio_buffer_->Reset() at a fence,
    // the buffer may be empty if the primed frame had no audio packets
    // (demuxer returned video before audio).  In that case, emit pad
    // silence at the correct PTS so audio never skips a tick — otherwise
    // the A/V delta permanently drifts by 1 frame period per fence.
    // ==================================================================
    // Exact per-tick sample count via rational arithmetic (drift-free).
    int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
    int64_t next_total =
        ((audio_ticks_emitted + 1) * sr * ctx_->fps_den) / ctx_->fps_num;
    int samples_this_tick =
        static_cast<int>(next_total - audio_buffer_samples_emitted);

    if (using_degraded_held_this_tick) {
      // DEGRADED_TAKE_MODE: hold last video frame + silence (no pop from B).
      static constexpr int kChannels = buffer::kHouseAudioChannels;
      static constexpr int kSampleRate = buffer::kHouseAudioSampleRate;
      buffer::AudioFrame silence;
      silence.sample_rate = kSampleRate;
      silence.channels = kChannels;
      silence.nb_samples = samples_this_tick;
      silence.data.resize(
          static_cast<size_t>(samples_this_tick * kChannels) * sizeof(int16_t), 0);
      session_encoder->encodeAudioFrame(silence, audio_pts_90k,
                                         /*is_silence_pad=*/true);
      audio_samples_emitted += samples_this_tick;
      audio_buffer_samples_emitted += samples_this_tick;
      audio_ticks_emitted++;
      audio_frames_this_tick = 1;
      current_consecutive_fallback_ticks++;
    } else if (!is_pad) {
      if (a_src && a_src->IsPrimed()) {
        buffer::AudioFrame audio_out;
        if (a_src->TryPopSamples(samples_this_tick, audio_out)) {
          session_encoder->encodeAudioFrame(audio_out, audio_pts_90k, false);
          audio_samples_emitted += samples_this_tick;
          audio_buffer_samples_emitted += samples_this_tick;
          audio_ticks_emitted++;
          audio_frames_this_tick = 1;
          // OUT-SEG-005b: Real decoded audio — reset fallback streak.
          current_consecutive_fallback_ticks = 0;
        } else {
          // INV-TICK-GUARANTEED-OUTPUT: Audio underflow MUST NOT terminate
          // the session.  Inject silence to bridge the gap (e.g. segment
          // transition where filler decoder hasn't filled the audio buffer
          // yet).  Log diagnostic for observability.
          { std::ostringstream oss;
            oss << "[PipelineManager] AUDIO_UNDERFLOW_SILENCE"
                << " frame=" << session_frame_index
                << " buffer_depth_ms=" << a_src->DepthMs()
                << " needed=" << samples_this_tick
                << " total_pushed=" << a_src->TotalSamplesPushed()
                << " total_popped=" << a_src->TotalSamplesPopped();
            Logger::Warn(oss.str()); }

          static constexpr int kChannels = buffer::kHouseAudioChannels;
          static constexpr int kSampleRate = buffer::kHouseAudioSampleRate;

          buffer::AudioFrame silence;
          silence.sample_rate = kSampleRate;
          silence.channels = kChannels;
          silence.nb_samples = samples_this_tick;
          silence.data.resize(
              static_cast<size_t>(samples_this_tick * kChannels) * sizeof(int16_t), 0);

          session_encoder->encodeAudioFrame(silence, audio_pts_90k,
                                             /*is_silence_pad=*/true);
          audio_samples_emitted += samples_this_tick;
          audio_buffer_samples_emitted += samples_this_tick;
          audio_ticks_emitted++;
          audio_frames_this_tick = 1;
          { std::lock_guard<std::mutex> lock(metrics_mutex_); metrics_.audio_silence_injected++; }
          // OUT-SEG-005b: Underflow silence = fallback tick.
          current_consecutive_fallback_ticks++;
        }
      } else {
        // SAFETY NET: Audio buffer not primed despite INV-AUDIO-PRIME-001.
        // This should never happen — if it does, the priming in StartFilling
        // didn't reach the threshold (e.g., content with no audio track).
        // Emit pad silence to prevent A/V drift; log at WARNING level.
        //
        // DEPRECATED for BlockPlan live playout.  This inline silence
        // generation allocates per-tick and bypasses the TAKE commitment
        // path.  INV-PAD-PRODUCER replaces it: PadProducer provides
        // pre-allocated silence via SilenceTemplate() through the TAKE.
        // Retained as a defensive fallback until all audio-prime edge
        // cases are verified to be unreachable.
        static constexpr int kChannels = buffer::kHouseAudioChannels;
        static constexpr int kSampleRate = buffer::kHouseAudioSampleRate;

        buffer::AudioFrame silence;
        silence.sample_rate = kSampleRate;
        silence.channels = kChannels;
        silence.nb_samples = samples_this_tick;
        silence.data.resize(
            static_cast<size_t>(samples_this_tick * kChannels) * sizeof(int16_t), 0);

        session_encoder->encodeAudioFrame(silence, audio_pts_90k,
                                           /*is_silence_pad=*/true);
        audio_samples_emitted += samples_this_tick;
        audio_buffer_samples_emitted += samples_this_tick;
        audio_ticks_emitted++;
        audio_frames_this_tick = 1;

        { std::ostringstream oss;
          oss << "[PipelineManager] WARNING FENCE_AUDIO_PAD: audio not primed"
              << " tick=" << session_frame_index
              << " samples=" << samples_this_tick
              << " audio_pts_90k=" << audio_pts_90k
              << " video_pts_90k=" << video_pts_90k;
          Logger::Warn(oss.str()); }
        // OUT-SEG-005b: Fence pad silence = fallback tick.
        current_consecutive_fallback_ticks++;
      }
    }
    // else: is_pad — pad audio handled below (pad_producer_ path).

    // OUT-SEG-005b: Update max consecutive fallback ticks metric.
    if (current_consecutive_fallback_ticks > 0) {
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      if (current_consecutive_fallback_ticks > metrics_.max_consecutive_audio_fallback_ticks) {
        metrics_.max_consecutive_audio_fallback_ticks = current_consecutive_fallback_ticks;
      }
    }

    // INV-AUDIO-BUFFER-POLICY-001: Toggle audio boost on the video fill
    // thread.  When audio is below LOW_WATER, the fill thread's effective
    // target depth doubles so it decodes more frames (and thus more audio)
    // before parking.  Disabled once audio recovers above HIGH_WATER.
    if (video_buffer_ && audio_buffer_ && !is_pad) {
      if (audio_buffer_->IsBelowLowWater()) {
        video_buffer_->SetAudioBoost(true);
      } else if (audio_buffer_->IsAboveHighWater()) {
        video_buffer_->SetAudioBoost(false);
      }
    }

    // ==================================================================
    // SEAM_PROOF_TICK: Per-frame source attribution on fence tick ±4.
    // Answers: is the video frame from the incoming block?  Is audio
    // from the incoming block?  Is there a PTS discontinuity at the seam?
    // ==================================================================
    if (seam_proof_fence_tick >= 0 &&
        session_frame_index >= seam_proof_fence_tick &&
        session_frame_index < seam_proof_fence_tick + 5) {

      std::string video_source_block;
      if (live_tp()->GetState() == ITickProducer::State::kReady) {
        video_source_block = live_tp()->GetBlock().block_id;
      }

      // Classify audio source for this tick.
      const char* audio_source = "none";
      if (is_pad) {
        audio_source = "pad_frame";  // Full pad frame (video + audio)
      } else if (audio_frames_this_tick > 0 && audio_buffer_->IsPrimed()) {
        audio_source = "buffer";     // Popped from AudioLookaheadBuffer
      } else if (audio_frames_this_tick > 0) {
        audio_source = "fence_pad";  // Fence silence (buffer not yet primed)
      }

      { std::ostringstream oss;
        oss << "[PipelineManager] SEAM_PROOF_TICK"
            << " tick=" << session_frame_index
            << " fence_tick=" << seam_proof_fence_tick
            << " is_pad=" << is_pad
            << " video_block=" << (video_source_block.empty()
                ? "none" : video_source_block)
            << " video_asset=" << (is_pad ? "pad"
                : (vbf.asset_uri.empty() ? "unknown" : vbf.asset_uri))
            << " video_decoded=" << (!is_pad && vbf.was_decoded)
            << " video_ct_ms=" << (is_pad ? -1 : vbf.block_ct_ms)
            << " video_pts_90k=" << video_pts_90k
            << " audio_pts_90k=" << audio_pts_90k
            << " av_delta_90k=" << (video_pts_90k - audio_pts_90k)
            << " audio_source=" << audio_source
            << " audio_buf_depth_ms=" << audio_buffer_->DepthMs()
            << " video_buf_depth=" << video_buffer_->DepthFrames();
        Logger::Info(oss.str()); }
    }

    // SEAM_PROOF_FIRST_FRAME: Log when first non-pad frame from the incoming
    // block reaches the encoder.  activation_delay_ticks=0 means the incoming
    // block's first frame was emitted on the fence tick itself.
    if (!seam_proof_first_frame_logged && !is_pad &&
        seam_proof_fence_tick >= 0) {
      seam_proof_first_frame_logged = true;
      int64_t activation_delay = session_frame_index - seam_proof_fence_tick;
      { std::ostringstream oss;
        oss << "[PipelineManager] SEAM_PROOF_FIRST_FRAME"
            << " tick=" << session_frame_index
            << " fence_tick=" << seam_proof_fence_tick
            << " incoming=" << seam_proof_incoming_id
            << " activation_delay_ticks=" << activation_delay
            << " video_pts_90k=" << video_pts_90k
            << " audio_pts_90k=" << audio_pts_90k
            << " av_delta_90k=" << (video_pts_90k - audio_pts_90k)
            << " video_asset=" << vbf.asset_uri
            << " video_ct_ms=" << vbf.block_ct_ms
            << " video_decoded=" << vbf.was_decoded;
        Logger::Info(oss.str()); }
    }

    // HEARTBEAT: telemetry snapshot for performance regression detection.
    // ~3000 ticks ≈ 100s at 30fps.  Metrics are always available via
    // /metrics endpoint regardless of log frequency.
    //
    // Field meanings and healthy ranges:
    //   frame         Session frame index (output ticks). No "healthy" value; informational.
    //   video         current/target frame depth. Healthy: depth near target (e.g. 14/15);
    //                 consistently below low-water (default 5) triggers LOW_WATER warnings.
    //   refill        Decoder fill rate (fps): frames pushed into video buffer per second,
    //                 session-long average. Healthy: >= output fps (e.g. >= 30 at 30fps output;
    //                 with 23.976→30 cadence, >= ~24 is sufficient). Low = decode can't keep up.
    //   decode_p95    95th percentile decode latency (microseconds) per frame. Healthy:
    //                 well below frame interval (e.g. < ~33000 us at 30fps); high = slow decode.
    //   audio         current/target audio buffer depth (ms). Healthy: depth near target
    //                 (e.g. 456/1000); below low-water (default target/3) triggers LOW_WATER.
    //   a_pushed      Total audio samples pushed (cumulative). Should track a_popped; large
    //                 gap (pushed >> popped) = backpressure; (popped >> pushed) = underflow.
    //   a_popped      Total audio samples popped (cumulative). See a_pushed.
    //   sink          Bytes currently buffered / socket sink capacity (bytes). Healthy: low
    //                 current (e.g. 0/32768) = consumer keeping up; near capacity = slow
    //                 consumer, risk of detach-on-overflow.
    static constexpr int64_t kHeartbeatInterval = 3000;
    if (session_frame_index % kHeartbeatInterval == 0) {
      // Snapshot live metrics under metrics_mutex_.
      {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        if (video_buffer_) {
          metrics_.video_buffer_depth_frames = video_buffer_->DepthFrames();
          metrics_.video_buffer_underflows = video_buffer_->UnderflowCount();
          metrics_.video_buffer_frames_pushed = video_buffer_->TotalFramesPushed();
          metrics_.video_buffer_frames_popped = video_buffer_->TotalFramesPopped();
          metrics_.decode_latency_p95_us = video_buffer_->DecodeLatencyP95Us();
          metrics_.decode_latency_mean_us = video_buffer_->DecodeLatencyMeanUs();
          metrics_.video_refill_rate_fps = video_buffer_->RefillRateFps();
          metrics_.video_low_water_frames = video_buffer_->LowWaterFrames();
        }
        if (audio_buffer_) {
          metrics_.audio_buffer_depth_ms = audio_buffer_->DepthMs();
          metrics_.audio_buffer_underflows = audio_buffer_->UnderflowCount();
          metrics_.audio_buffer_samples_pushed = audio_buffer_->TotalSamplesPushed();
          metrics_.audio_buffer_samples_popped = audio_buffer_->TotalSamplesPopped();
          metrics_.audio_low_water_ms = audio_buffer_->LowWaterMs();
        }
      }

      // Single consolidated log line — atomic write to prevent interleave.
      { std::ostringstream oss;
        oss << "[PipelineManager] HEARTBEAT"
            << " frame=" << session_frame_index;
        if (video_buffer_) {
          oss << " video=" << video_buffer_->DepthFrames()
              << "/" << video_buffer_->HighWaterFrames()
              << " refill=" << video_buffer_->RefillRateFps() << "fps"
              << " decode_p95=" << video_buffer_->DecodeLatencyP95Us() << "us";
        }
        if (audio_buffer_) {
          int64_t a_pushed = audio_buffer_->TotalSamplesPushed();
          int64_t a_popped = audio_buffer_->TotalSamplesPopped();
          oss << " audio=" << audio_buffer_->DepthMs() << "ms"
              << "/" << audio_buffer_->TargetDepthMs() << "ms"
              << " a_pushed=" << a_pushed
              << " a_popped=" << a_popped;
        }
        {
          std::lock_guard<std::mutex> lock(metrics_mutex_);
          if (metrics_.audio_silence_injected > 0) {
            oss << " silence_injected=" << metrics_.audio_silence_injected;
          }
        }
        if (socket_sink) {
          oss << " sink=" << socket_sink->GetCurrentBufferSize()
              << "/" << socket_sink->GetBufferCapacity();
        }
        Logger::Info(oss.str()); }

      // Low-water warnings (throttled to heartbeat interval).
      if (video_buffer_ && video_buffer_->IsBelowLowWater()) {
        { std::ostringstream oss;
          oss << "[PipelineManager] LOW_WATER video="
              << video_buffer_->DepthFrames()
              << " threshold=" << video_buffer_->LowWaterFrames();
          Logger::Warn(oss.str()); }
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.video_low_water_events++;
      }
      if (audio_buffer_ && audio_buffer_->IsBelowLowWater()) {
        { std::ostringstream oss;
          oss << "[PipelineManager] LOW_WATER audio="
              << audio_buffer_->DepthMs() << "ms"
              << " threshold=" << audio_buffer_->LowWaterMs() << "ms";
          Logger::Warn(oss.str()); }
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.audio_low_water_events++;
      }
    }

    // P3.2: Emit frame fingerprint for seam verification
    if (callbacks_.on_frame_emitted) {
      FrameFingerprint fp;
      fp.session_frame_index = session_frame_index;
      fp.is_pad = is_pad;
      fp.commit_slot = take_source_char;
      if (live_tp()->GetState() == ITickProducer::State::kReady) {
        fp.active_block_id = live_tp()->GetBlock().block_id;
      }
      if (is_pad) {
        // INV-PAD-PRODUCER-003: Cached CRC32 — no per-tick recomputation. Also standby ('S').
        fp.asset_uri = PadProducer::kAssetUri;
        fp.y_crc32 = pad_producer_->VideoCRC32();
      } else if (using_degraded_held_this_tick && has_last_good_video_frame_) {
        // No-unintentional-black: held frame must match last A content fingerprint.
        fp.asset_uri = last_good_asset_uri_;
        fp.active_block_id = last_good_block_id_;
        fp.asset_offset_ms = last_good_offset_ms_;
        fp.y_crc32 = last_good_y_crc32_;
      } else if (vbf.was_decoded) {
        fp.asset_uri = vbf.asset_uri;
        fp.asset_offset_ms = vbf.block_ct_ms;
        const auto& vid = vbf.video;
        if (!vid.data.empty()) {
          size_t y_size = static_cast<size_t>(vid.width * vid.height);
          fp.y_crc32 = CRC32YPlane(vid.data.data(),
                                    std::min(y_size, vid.data.size()));
        }
      }
      callbacks_.on_frame_emitted(fp);
    }

    // P3.3: Accumulate frame into current block summary
    // ct_ms = -1 sentinel when vbf is cadence repeat or hold-last.
    // Accumulator only updates CT tracking when ct_ms >= 0.
    if (live_tp()->GetState() == ITickProducer::State::kReady &&
        !block_acc.block_id.empty()) {
      std::string uri;
      int64_t ct_ms = -1;
      if (!is_pad && vbf.was_decoded) {
        uri = vbf.asset_uri;
        ct_ms = vbf.block_ct_ms;
      }
      block_acc.AccumulateFrame(session_frame_index, is_pad, uri, ct_ms);
    }

    // P3.3: Count pad frames after fence for seam tracking
    if (past_fence && is_pad) {
      fence_pad_counter++;
    }

    // INV-FRAME-BUDGET-003: Every emitted frame decrements by exactly 1.
    // Applies to real, freeze, and pad frames equally.
    if (remaining_block_frames_ > 0) {
      remaining_block_frames_--;
    }

    // LOAD NEXT from queue if source is empty AND no active block fence.
    // INV-BLOCK-WALLFENCE-003: A new block may only be loaded when no
    // active block owns the timeline.  block_fence_frame_ == INT64_MAX
    // is the sentinel for "no current block" — set at session init and
    // on PADDED_GAP entry.  Any other value means a block's fence is
    // still pending; the tick loop MUST continue emitting from the
    // current block (freeze/pad) until the fence fires.
    if (live_tp()->GetState() == ITickProducer::State::kEmpty &&
        block_fence_frame_ == INT64_MAX) {
      bool had_preview = (preview_ != nullptr);
      TryLoadLiveProducer();  // Outside timed tick window

      if (live_tp()->GetState() == ITickProducer::State::kReady) {
        block_fence_frame_ = compute_fence_frame(live_tp()->GetBlock());
        // INV-FRAME-BUDGET-002: Budget derived from fence, not FramesPerBlock().
        remaining_block_frames_ = block_fence_frame_ - session_frame_index;
        if (remaining_block_frames_ < 0) remaining_block_frames_ = 0;

        // P3.3: Emit seam transition log (padded transition)
        if (!prev_completed_block_id.empty()) {
          SeamTransitionLog seam;
          seam.from_block_id = prev_completed_block_id;
          seam.to_block_id = live_tp()->GetBlock().block_id;
          seam.fence_frame = fence_session_frame;
          seam.pad_frames_at_fence = fence_pad_counter;
          seam.seamless = (fence_pad_counter == 0);
          Logger::Info(FormatSeamTransition(seam));
          if (callbacks_.on_seam_transition) {
            callbacks_.on_seam_transition(seam);
          }
          prev_completed_block_id.clear();
        }

        // P3.3: Reset accumulator for new block
        block_acc.Reset(live_tp()->GetBlock().block_id);
        emit_block_start((had_preview && !preview_) ? "preview" : "queue");
        // INV-VIDEO-LOOKAHEAD-001: Stop preview fill before starting live fill.
        // TryLoadLiveProducer moved preview_ → live_, so the PREVIEW fill
        // thread and the about-to-start LIVE fill thread share the same
        // TickProducer.  Stop the PREVIEW fill first to prevent concurrent
        // TryGetFrame on a non-thread-safe producer.
        if (preview_video_buffer_ && preview_video_buffer_->IsFilling()) {
          { auto t0 = std::chrono::steady_clock::now();
            { std::ostringstream oss;
              oss << "[PipelineManager] STOP_FILLING_BEGIN context=padded_gap_exit tick="
                  << session_frame_index;
              Logger::Info(oss.str()); }
            preview_video_buffer_->StopFilling(/*flush=*/true);
            auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - t0).count();
            { std::ostringstream oss;
              oss << "[PipelineManager] STOP_FILLING_END context=padded_gap_exit tick="
                  << session_frame_index << " dt_ms=" << dt_ms;
              Logger::Info(oss.str()); }
          }
        }
        preview_video_buffer_.reset();
        preview_audio_buffer_.reset();
        // INV-VIDEO-LOOKAHEAD-001: Start fill thread with loaded producer.
        video_buffer_->StartFilling(
            live_tp(), audio_buffer_.get(),
            live_tp()->GetInputFPS(), ctx_->fps,
            &ctx_->stop_requested);

        // INV-SEAM-SEG: Block activation — extract boundaries and compute segment seam frames.
        block_activation_frame_ = session_frame_index;
        live_parent_block_ = live_tp()->GetBlock();
        live_boundaries_ = AsTickProducer(live_.get())->GetBoundaries();
        ComputeSegmentSeamFrames();
        ArmSegmentPrep(session_frame_index);

        // Block is now LIVE — notify subscribers.
        if (callbacks_.on_block_started) {
          BlockActivationContext actx;
          actx.timeline_frame_index = session_frame_index;
          actx.block_fence_tick = block_fence_frame_;
          actx.utc_ms = time_source_->NowUtcMs();
          callbacks_.on_block_started(live_parent_block_, actx);
        }

        // Fire on_segment_start for the first segment of the new block.
        if (callbacks_.on_segment_start) {
          callbacks_.on_segment_start(-1, 0, live_parent_block_, session_frame_index);
        }

        // Begin segment proof tracking for first segment.
        if (!live_parent_block_.segments.empty()) {
          const auto& seg0 = live_parent_block_.segments[0];
          block_acc.BeginSegment(
              0, seg0.asset_uri,
              static_cast<int64_t>(std::ceil(
                  static_cast<double>(seg0.segment_duration_ms) /
                  static_cast<double>(clock.FrameDurationMs()))),
              seg0.segment_type, seg0.event_id);
        }

        { std::ostringstream oss;
          oss << "[PipelineManager] PADDED_GAP_EXIT"
              << " frame=" << session_frame_index
              << " gap_frames=" << fence_pad_counter
              << " block=" << live_tp()->GetBlock().block_id;
          Logger::Info(oss.str()); }
        fence_pad_counter = 0;

        past_fence = false;
        // Kick off preload for the next one
        TryKickoffBlockPreload(session_frame_index);
      }
    }

    // P3.1b: Try to start preloading if conditions met
    // (stash + preroll moved to pre-TAKE readiness block above)
    TryKickoffBlockPreload(session_frame_index);

    // ---- Inter-frame gap measurement ----
    if (have_prev_frame_time) {
      auto gap_us = std::chrono::duration_cast<std::chrono::microseconds>(
          wake_time - prev_frame_time).count();
      double gap_ms = gap_us / 1000.0;
      if (gap_ms > 50) {
        const char* phase =
            past_fence ? "past_fence"
            : (take_b ? "block_take" : (take_segment ? "segment_take" : "tick"));
        { std::ostringstream oss;
          oss << "[PipelineManager] TICK_GAP gap_ms=" << gap_ms
              << " tick=" << session_frame_index
              << " fence_tick=" << FormatFenceTick(block_fence_frame_)
              << " phase=" << phase;
          Logger::Info(oss.str()); }
      }
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      metrics_.sum_inter_frame_gap_us += gap_us;
      metrics_.frame_gap_count++;
      if (gap_us > metrics_.max_inter_frame_gap_us) {
        metrics_.max_inter_frame_gap_us = gap_us;
      }
    }
    prev_frame_time = wake_time;
    have_prev_frame_time = true;

    // Update counters
    {
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      metrics_.continuous_frames_emitted_total++;
      if (is_pad) {
        metrics_.pad_frames_emitted_total++;
      }
    }

    session_frame_index++;
  }

  // ========================================================================
  // 7. TEARDOWN
  // ========================================================================
  if (ctx_->stop_requested.load(std::memory_order_acquire) &&
      termination_reason == "unknown") {
    termination_reason = "stopped";
  }

  // Join any deferred fill thread from the last fence swap.
  { auto t0 = std::chrono::steady_clock::now();
    { std::ostringstream oss;
      oss << "[PipelineManager] CLEANUP_DEFERRED_FILL_BEGIN tick=teardown context=teardown";
      Logger::Info(oss.str()); }
    CleanupDeferredFill();
    auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - t0).count();
    { std::ostringstream oss;
      oss << "[PipelineManager] CLEANUP_DEFERRED_FILL_END tick=teardown context=teardown dt_ms="
          << dt_ms;
      Logger::Info(oss.str()); }
  }

  // INV-VIDEO-LOOKAHEAD-001: Stop video fill thread before resetting producers.
  if (video_buffer_) {
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=teardown_video tick=teardown";
        Logger::Info(oss.str()); }
      video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=teardown_video tick=teardown dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
  }
  // Stop B preroll buffers if still running.
  if (preview_video_buffer_) {
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=teardown_preview tick=teardown";
        Logger::Info(oss.str()); }
      preview_video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=teardown_preview tick=teardown dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
    preview_video_buffer_.reset();
  }
  preview_audio_buffer_.reset();

  // Stop segment B buffers if still running.
  if (segment_b_video_buffer_) {
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=teardown_segment_b tick=teardown";
        Logger::Info(oss.str()); }
      segment_b_video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=teardown_segment_b tick=teardown dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
    segment_b_video_buffer_.reset();
  }
  segment_b_audio_buffer_.reset();
  segment_b_producer_.reset();

  // Stop persistent pad B chain if still running.
  if (pad_b_video_buffer_) {
    { auto t0 = std::chrono::steady_clock::now();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_BEGIN context=teardown_pad_b tick=teardown";
        Logger::Info(oss.str()); }
      pad_b_video_buffer_->StopFilling(/*flush=*/true);
      auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now() - t0).count();
      { std::ostringstream oss;
        oss << "[PipelineManager] STOP_FILLING_END context=teardown_pad_b tick=teardown dt_ms="
            << dt_ms;
        Logger::Info(oss.str()); }
    }
    pad_b_video_buffer_.reset();
  }
  pad_b_audio_buffer_.reset();
  pad_b_producer_.reset();

  // INV-PAD-PRODUCER: Release session-lifetime pad source.
  pad_producer_.reset();

  // Cancel seam preparer and reset sources before closing encoder
  seam_preparer_->Cancel();
  preview_.reset();
  live_tp()->Reset();
  block_fence_frame_ = INT64_MAX;
  remaining_block_frames_ = 0;

  if (session_encoder) {
    session_encoder->close();
    { std::ostringstream oss;
      oss << "[PipelineManager] Session encoder closed: "
          << write_ctx.bytes_written << " bytes written";
      Logger::Info(oss.str()); }
  }

  // Close SocketSink AFTER encoder — encoder->close() flushes final packets
  // through the write callback into the sink buffer.  SocketSink::Close()
  // signals the writer thread to drain remaining bytes and shut down.
  if (socket_sink) {
    socket_sink->Close();
    { std::ostringstream oss;
      oss << "[PipelineManager] SocketSink closed: delivered="
          << socket_sink->GetBytesDelivered()
          << " enqueued=" << socket_sink->GetBytesEnqueued()
          << " errors=" << socket_sink->GetWriteErrors()
          << " detached=" << socket_sink->IsDetached();
      Logger::Info(oss.str()); }
  }

  {
    auto session_end_time = std::chrono::steady_clock::now();
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.encoder_close_count = 1;
    metrics_.session_duration_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            session_end_time - session_start_time).count();
    metrics_.continuous_mode_active = false;

    // INV-AUDIO-LOOKAHEAD-001: Capture audio buffer metrics at session end.
    if (audio_buffer_) {
      metrics_.audio_buffer_depth_ms = audio_buffer_->DepthMs();
      metrics_.audio_buffer_underflows = audio_buffer_->UnderflowCount();
      metrics_.audio_buffer_samples_pushed = audio_buffer_->TotalSamplesPushed();
      metrics_.audio_buffer_samples_popped = audio_buffer_->TotalSamplesPopped();
    }

    // INV-VIDEO-LOOKAHEAD-001: Capture video buffer metrics at session end.
    if (video_buffer_) {
      metrics_.video_buffer_depth_frames = video_buffer_->DepthFrames();
      metrics_.video_buffer_underflows = video_buffer_->UnderflowCount();
      metrics_.video_buffer_frames_pushed = video_buffer_->TotalFramesPushed();
      metrics_.video_buffer_frames_popped = video_buffer_->TotalFramesPopped();
      metrics_.decode_latency_p95_us = video_buffer_->DecodeLatencyP95Us();
      metrics_.decode_latency_mean_us = video_buffer_->DecodeLatencyMeanUs();
      metrics_.video_refill_rate_fps = video_buffer_->RefillRateFps();
    }
  }

  { std::ostringstream oss;
    oss << "[PipelineManager] Thread exiting: frames_emitted="
        << session_frame_index
        << ", reason=" << termination_reason;
    Logger::Info(oss.str()); }

  if (callbacks_.on_session_ended && !session_ended_fired_) {
    session_ended_fired_ = true;
    callbacks_.on_session_ended(termination_reason, session_frame_index);
  }
}

void PipelineManager::SetPreloaderDelayHook(
    std::function<void()> hook) {
  seam_preparer_->SetDelayHook(std::move(hook));
}

AudioLookaheadBuffer* PipelineManager::SelectAudioSourceForTick(
    bool take_block,
    bool take_segment,
    bool segment_swap_committed,
    AudioLookaheadBuffer* live_audio,
    AudioLookaheadBuffer* preview_audio,
    AudioLookaheadBuffer* segment_b_audio) {
  if (take_block) {
    return preview_audio;
  }
  if (take_segment) {
    return segment_swap_committed ? segment_b_audio : live_audio;
  }
  return live_audio;
}


// =============================================================================
// MakeSyntheticSegmentBlock — build single-segment FedBlock for segment prep
// =============================================================================

FedBlock PipelineManager::MakeSyntheticSegmentBlock(
    const FedBlock& parent, int32_t seg_idx,
    const std::vector<SegmentBoundary>& boundaries) {
  assert(seg_idx < static_cast<int32_t>(parent.segments.size()) &&
         "MakeSyntheticSegmentBlock: seg_idx out of range in parent block");
  assert(seg_idx < static_cast<int32_t>(boundaries.size()) &&
         "MakeSyntheticSegmentBlock: seg_idx out of range in boundaries");

  FedBlock synth;
  synth.block_id = parent.block_id;
  synth.channel_id = parent.channel_id;
  synth.start_utc_ms = parent.start_utc_ms + boundaries[seg_idx].start_ct_ms;
  synth.end_utc_ms = parent.start_utc_ms + boundaries[seg_idx].end_ct_ms;

  FedBlock::Segment seg = parent.segments[seg_idx];
  seg.segment_index = 0;  // Single-segment block
  synth.segments.push_back(std::move(seg));

  assert(synth.segments.size() == 1 &&
         "MakeSyntheticSegmentBlock: result must have exactly 1 segment");
  return synth;
}

// =============================================================================
// ComputeSegmentSeamFrames — populate segment_seam_frames_ from live_boundaries_
// =============================================================================

void PipelineManager::ComputeSegmentSeamFrames() {
  segment_seam_frames_.clear();
  current_segment_index_ = 0;
  const int64_t fps_num = ctx_->fps_num;
  const int64_t fps_den = ctx_->fps_den;
  int64_t denom = fps_den * 1000;
  for (const auto& boundary : live_boundaries_) {
    int64_t ct_ms = boundary.end_ct_ms;
    int64_t seam = (ct_ms > 0)
        ? block_activation_frame_ + (ct_ms * fps_num + denom - 1) / denom
        : block_activation_frame_;
    segment_seam_frames_.push_back(seam);
  }
  UpdateNextSeamFrame();
}

// =============================================================================
// UpdateNextSeamFrame — set next_seam_frame_ = min(next segment seam, block fence)
// =============================================================================

void PipelineManager::UpdateNextSeamFrame() {
  int64_t next_seg = INT64_MAX;
  // Current segment's end is the next segment seam — UNLESS it's the last segment.
  if (current_segment_index_ + 1 <
      static_cast<int32_t>(segment_seam_frames_.size())) {
    next_seg = segment_seam_frames_[current_segment_index_];
  }
  if (next_seg < block_fence_frame_) {
    next_seam_frame_ = next_seg;
    next_seam_type_ = SeamType::kSegment;
  } else {
    next_seam_frame_ = block_fence_frame_;
    next_seam_type_ = SeamType::kBlock;
  }
}

// =============================================================================
// ArmSegmentPrep — submit segment N+1 prep to SeamPreparer
// =============================================================================

void PipelineManager::ArmSegmentPrep(int64_t session_frame_index) {
  // No-op for single-segment blocks or when on the last segment.
  if (live_boundaries_.size() <= 1) return;
  int32_t next_seg = current_segment_index_ + 1;
  if (next_seg >= static_cast<int32_t>(live_boundaries_.size())) return;

  // FIX (skip-PAD prep): PAD segments are handled inline in PerformSegmentSwap --
  // they need no decoder, no file I/O, and no async worker involvement.
  // Scan forward from next_seg to find the first non-PAD segment to prep.
  // This gives the worker the full duration of the current content segment as
  // lead time, instead of racing a 1-frame PAD window (which always loses).
  int32_t target_seg = next_seg;
  while (target_seg < static_cast<int32_t>(live_parent_block_.segments.size()) &&
         live_parent_block_.segments[target_seg].segment_type == SegmentType::kPad) {
    target_seg++;
  }
  // If all remaining segments are PAD (or block ends here), nothing to prep.
  if (target_seg >= static_cast<int32_t>(live_parent_block_.segments.size())) {
    return;
  }

  // Guard: don't re-arm if the worker already has a result for the target segment.
  // This prevents double-submission when a PAD inline swap calls ArmSegmentPrep
  // and the content prep was already armed at block activation.
  if (seam_preparer_->HasSegmentResult()) {
    auto peek = seam_preparer_->PeekSegmentResult();
    if (peek && peek->parent_block_id == live_parent_block_.block_id &&
        peek->parent_segment_index == target_seg) {
      return;  // Already prepped -- PerformSegmentSwap will consume at seam tick.
    }
  }

  // Use live_parent_block_ (the original multi-segment block stored at block
  // activation), NOT live_->GetBlock().  After a segment swap, live_ holds a
  // synthetic single-segment block, so live_->GetBlock().segments[target_seg]
  // would be out of range.
  FedBlock synth = MakeSyntheticSegmentBlock(
      live_parent_block_, target_seg, live_boundaries_);

  // Determine segment type for logging.
  const char* seg_type_name = "UNKNOWN";
  if (target_seg < static_cast<int32_t>(live_parent_block_.segments.size())) {
    seg_type_name = SegmentTypeName(
        live_parent_block_.segments[target_seg].segment_type);
  }

  // seam_frame = the session frame when the target segment activates
  //            = end of the segment immediately before target_seg.
  int32_t seam_boundary_idx = target_seg - 1;
  int64_t seam_frame_val =
      (seam_boundary_idx < static_cast<int32_t>(segment_seam_frames_.size()))
      ? segment_seam_frames_[seam_boundary_idx]
      : INT64_MAX;

  // Lead time: frames/ms from this tick until seam. Must be >= required for B-chain to reach target depth.
  int64_t headroom_frames = (seam_frame_val != INT64_MAX && seam_frame_val > session_frame_index)
      ? (seam_frame_val - session_frame_index)
      : 0;
  int64_t headroom_ms = (headroom_frames > 0 && ctx_->fps_num > 0)
      ? (headroom_frames * 1000 * ctx_->fps_den) / ctx_->fps_num
      : 0;
  int64_t required_frames_from_ms = (kMinSegmentPrepHeadroomMs * ctx_->fps_num + 1000 * ctx_->fps_den - 1)
      / (1000 * ctx_->fps_den);
  int64_t required_headroom_frames = std::max(
      static_cast<int64_t>(kMinSegmentPrepHeadroomFrames),
      required_frames_from_ms);

  if (headroom_frames < required_headroom_frames) {
    std::ostringstream oss;
    oss << "[PipelineManager] SEAM_PREP_HEADROOM_LOW"
        << " headroom_frames=" << headroom_frames
        << " headroom_ms=" << headroom_ms
        << " required_frames=" << required_headroom_frames
        << " target_segment=" << target_seg
        << " seam_frame=" << FormatFenceTick(seam_frame_val)
        << " tick=" << session_frame_index;
    Logger::Warn(oss.str());
  }

  SeamRequest req;
  req.type = SeamRequestType::kSegment;
  req.block = std::move(synth);
  req.seam_frame = seam_frame_val;
  req.width = ctx_->width;
  req.height = ctx_->height;
  req.fps = ctx_->fps;
  req.min_audio_prime_ms = kMinAudioPrimeMs;
  req.parent_block_id = live_parent_block_.block_id;
  req.segment_index = target_seg;
  seam_preparer_->Submit(std::move(req));

  { std::ostringstream oss;
    oss << "[PipelineManager] SEGMENT_PREP_ARMED"
        << " tick=" << session_frame_index
        << " parent_block=" << live_parent_block_.block_id
        << " next_segment=" << target_seg
        << " segment_type=" << seg_type_name
        << " seam_frame=" << FormatFenceTick(seam_frame_val)
        << " headroom_frames=" << headroom_frames
        << " headroom_ms=" << headroom_ms
        << " required_frames=" << required_headroom_frames;
    if (target_seg != next_seg) {
      oss << " skipped_pads=" << (target_seg - next_seg);
    }
    Logger::Info(oss.str()); }
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.segment_prep_armed_count++;
  }
}

// =============================================================================
// EnsureIncomingBReadyForSeam — create B (segment_b_*) before eligibility gate
// =============================================================================

void PipelineManager::EnsureIncomingBReadyForSeam(int32_t to_seg, int64_t session_frame_index) {
  if (to_seg >= static_cast<int32_t>(live_parent_block_.segments.size())) {
    return;
  }
  const SegmentType seg_type = live_parent_block_.segments[to_seg].segment_type;
  const bool is_pad = (seg_type == SegmentType::kPad);

  // Already have B for this seam (e.g. from previous tick).
  if (segment_b_video_buffer_ && segment_b_audio_buffer_) {
    return;
  }

  // PAD: use persistent pad_b_* (created at session init). No segment_b_* for PAD.
  if (is_pad) {
    return;
  }

  // CONTENT: take result and create B + StartFilling (so swap never allocates A).
  if (!seam_preparer_->HasSegmentResult()) {
    return;
  }
  auto peek = seam_preparer_->PeekSegmentResult();
  if (!peek || peek->parent_block_id != live_parent_block_.block_id ||
      peek->parent_segment_index != to_seg) {
    return;
  }
  auto result = seam_preparer_->TakeSegmentResult();
  if (!result || !result->producer) {
    return;
  }
  segment_b_producer_ = std::move(result->producer);
  const auto& bcfg = ctx_->buffer_config;
  int a_target = bcfg.audio_target_depth_ms;
  int a_low = bcfg.audio_low_water_ms > 0
      ? bcfg.audio_low_water_ms
      : std::max(1, a_target / 3);
  segment_b_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(15, 5);
  segment_b_video_buffer_->SetBufferLabel("SEGMENT_B_VIDEO_BUFFER");
  segment_b_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
      a_target, buffer::kHouseAudioSampleRate,
      buffer::kHouseAudioChannels, a_low);
  int seg_live_audio_before = audio_buffer_ ? audio_buffer_->DepthMs() : -1;
  segment_b_video_buffer_->StartFilling(
      AsTickProducer(segment_b_producer_.get()), segment_b_audio_buffer_.get(),
      AsTickProducer(segment_b_producer_.get())->GetInputFPS(), ctx_->fps,
      &ctx_->stop_requested);
  if (audio_buffer_ && seg_live_audio_before >= 0) {
    int seg_live_audio_after = audio_buffer_->DepthMs();
    if (seg_live_audio_after < seg_live_audio_before - 1) {
      std::ostringstream oss;
      oss << "[PipelineManager] INV-AUDIO-PREROLL-ISOLATION-001 VIOLATION:"
          << " context=SEGMENT_B_PREROLL"
          << " live_audio_before=" << seg_live_audio_before
          << " live_audio_after=" << seg_live_audio_after;
      Logger::Error(oss.str());
    }
  }
  { std::ostringstream oss;
    oss << "[PipelineManager] EnsureIncomingBReadyForSeam B_ready"
        << " tick=" << session_frame_index
        << " to_segment=" << to_seg
        << " segment_b_audio_depth_ms=" << segment_b_audio_buffer_->DepthMs()
        << " segment_b_video_depth_frames=" << segment_b_video_buffer_->DepthFrames();
    Logger::Info(oss.str()); }
}

// =============================================================================
// Segment seam eligibility gate
// =============================================================================

std::optional<IncomingState> PipelineManager::GetIncomingSegmentState(int32_t to_seg) const {
  if (to_seg >= static_cast<int32_t>(live_parent_block_.segments.size())) {
    return std::nullopt;
  }
  const SegmentType seg_type = live_parent_block_.segments[to_seg].segment_type;
  const bool is_pad = (seg_type == SegmentType::kPad);

  // CONTENT: only report state from actual B buffers (segment_b_*).
  if (segment_b_video_buffer_ && segment_b_audio_buffer_) {
    IncomingState s;
    s.incoming_audio_ms = segment_b_audio_buffer_->DepthMs();
    s.incoming_video_frames = segment_b_video_buffer_->DepthFrames();
    s.is_pad = is_pad;
    s.segment_type = seg_type;
    return s;
  }

  // PAD: report state from persistent pad_b_* when present; else synthetic (always eligible).
  if (is_pad) {
    IncomingState s;
    s.is_pad = true;
    s.segment_type = SegmentType::kPad;
    if (pad_b_video_buffer_ && pad_b_audio_buffer_) {
      s.incoming_audio_ms = pad_b_audio_buffer_->DepthMs();
      s.incoming_video_frames = pad_b_video_buffer_->DepthFrames();
    } else {
      s.incoming_audio_ms = 0;
      s.incoming_video_frames = 1;  // PadProducer on demand; infinite
    }
    return s;
  }

  // CONTENT with no B: not eligible (swap deferred until B exists and meets depth).
  return std::nullopt;
}

bool PipelineManager::IsIncomingSegmentEligibleForSwap(const IncomingState& incoming) const {
  if (incoming.is_pad) {
    // PAD: minimal prebuffer. PadProducer is session-lifetime, loopable (same
    // frame/silence every tick), no buffered content; sustains continuous output.
    return true;
  }
  // CONTENT: require minimum audio depth and video frames to avoid underflow.
  return incoming.incoming_audio_ms >= kMinSegmentSwapAudioMs &&
         incoming.incoming_video_frames >= kMinSegmentSwapVideoFrames;
}

// =============================================================================
// PerformSegmentSwap — segment POST-TAKE: swap B into A only (no A allocation)
// =============================================================================

void PipelineManager::PerformSegmentSwap(int64_t session_frame_index) {
  // Capture from/to segment info BEFORE any mutations.
  const int32_t from_seg = current_segment_index_;
  const int32_t to_seg = current_segment_index_ + 1;
  const char* from_type = "UNKNOWN";
  const char* to_type = "UNKNOWN";
  if (from_seg < static_cast<int32_t>(live_parent_block_.segments.size())) {
    from_type = SegmentTypeName(live_parent_block_.segments[from_seg].segment_type);
  }
  SegmentType to_seg_type = SegmentType::kContent;
  if (to_seg < static_cast<int32_t>(live_parent_block_.segments.size())) {
    to_seg_type = live_parent_block_.segments[to_seg].segment_type;
    to_type = SegmentTypeName(to_seg_type);
  }
  const bool incoming_is_pad = (to_seg_type == SegmentType::kPad);

  // Step 1: Join any deferred fill thread.
  { auto t0 = std::chrono::steady_clock::now();
    { std::ostringstream oss;
      oss << "[PipelineManager] CLEANUP_DEFERRED_FILL_BEGIN tick="
          << session_frame_index << " context=segment_swap";
      Logger::Info(oss.str()); }
    CleanupDeferredFill();
    auto dt_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - t0).count();
    { std::ostringstream oss;
      oss << "[PipelineManager] CLEANUP_DEFERRED_FILL_END tick="
          << session_frame_index << " context=segment_swap dt_ms=" << dt_ms;
      Logger::Info(oss.str()); }
  }

  // Step 2: Move outgoing A out FIRST so we can stop fill and hand off.
  // ReapJob holds owners until join. No allocation of A in this function.
  auto outgoing_video_buffer = std::move(video_buffer_);
  auto outgoing_audio_buffer = std::move(audio_buffer_);
  auto outgoing_producer = std::move(live_);
  auto detached = outgoing_video_buffer->StopFillingAsync(/*flush=*/true);

  const char* prep_mode = "MISS";
  const char* swap_branch = "NONE";
  bool pad_swap_used_pad_b = false;  // Recreate pad_b_* after handoff if true.

  if (incoming_is_pad && pad_b_video_buffer_ && pad_b_audio_buffer_) {
    // PAD seam: swap A with persistent pad B only. No A allocation.
    video_buffer_ = std::move(pad_b_video_buffer_);
    audio_buffer_ = std::move(pad_b_audio_buffer_);
    live_ = std::move(pad_b_producer_);
    video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");
    prep_mode = "INSTANT";
    swap_branch = "PAD_SWAP";
    pad_swap_used_pad_b = true;
  } else if (segment_b_video_buffer_ && segment_b_audio_buffer_) {
    // CONTENT: swap only — B into A slots. No allocation.
    video_buffer_ = std::move(segment_b_video_buffer_);
    audio_buffer_ = std::move(segment_b_audio_buffer_);
    live_ = std::move(segment_b_producer_);
    video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");
    prep_mode = "PREROLLED";
    swap_branch = "SWAP_B_TO_A";
  } else {
    // INV-SEAM-SEG-007: MISS — create B (only), then move B into A slots.
    segment_b_producer_ = std::make_unique<TickProducer>(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
    segment_b_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(15, 5);
    segment_b_video_buffer_->SetBufferLabel("SEGMENT_B_VIDEO_BUFFER");
    const auto& bcfg = ctx_->buffer_config;
    int a_target = bcfg.audio_target_depth_ms;
    int a_low = bcfg.audio_low_water_ms > 0
        ? bcfg.audio_low_water_ms
        : std::max(1, a_target / 3);
    segment_b_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
        a_target, buffer::kHouseAudioSampleRate,
        buffer::kHouseAudioChannels, a_low);
    segment_b_video_buffer_->StartFilling(
        AsTickProducer(segment_b_producer_.get()), segment_b_audio_buffer_.get(),
        0.0, ctx_->fps, &ctx_->stop_requested);
    video_buffer_ = std::move(segment_b_video_buffer_);
    audio_buffer_ = std::move(segment_b_audio_buffer_);
    live_ = std::move(segment_b_producer_);
    video_buffer_->SetBufferLabel("LIVE_AUDIO_BUFFER");
    prep_mode = "MISS";
    swap_branch = "MISS";
    { std::ostringstream oss;
      oss << "[PipelineManager] SEGMENT_SEAM_PAD_FALLBACK"
          << " tick=" << session_frame_index
          << " segment_index=" << current_segment_index_;
      Logger::Warn(oss.str()); }
    {
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      metrics_.segment_seam_miss_count++;
    }
  }

  if (swap_branch != "MISS") {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.segment_seam_ready_count++;
  }
  if (incoming_is_pad && swap_branch != "MISS") {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.segment_seam_pad_inline_count++;
  }

  // Step 3: Advance segment index and update next seam frame.
  current_segment_index_++;
  UpdateNextSeamFrame();

  // Step 4: Hand off ex-A to reaper.
  ReapJob job;
  job.job_id = reap_job_id_.fetch_add(1, std::memory_order_relaxed);
  job.block_id = GetBlockIdFromProducer(outgoing_producer.get());
  job.thread = std::move(detached.thread);
  job.producer = std::move(outgoing_producer);
  job.video_buffer = std::move(outgoing_video_buffer);
  job.audio_buffer = std::move(outgoing_audio_buffer);
  HandOffToReaper(std::move(job));

  // Step 4b: Recreate persistent pad B after PAD swap so it is ready for next PAD.
  if (pad_swap_used_pad_b) {
    const auto& pad_bcfg = ctx_->buffer_config;
    int pad_a_target = pad_bcfg.audio_target_depth_ms;
    int pad_a_low = pad_bcfg.audio_low_water_ms > 0
        ? pad_bcfg.audio_low_water_ms
        : std::max(1, pad_a_target / 3);
    pad_b_producer_ = std::make_unique<TickProducer>(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
    pad_b_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(15, 5);
    pad_b_video_buffer_->SetBufferLabel("PAD_B_VIDEO_BUFFER");
    pad_b_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
        pad_a_target, buffer::kHouseAudioSampleRate,
        buffer::kHouseAudioChannels, pad_a_low);
    pad_b_video_buffer_->StartFilling(
        AsTickProducer(pad_b_producer_.get()), pad_b_audio_buffer_.get(),
        0.0, ctx_->fps, &ctx_->stop_requested);
  }

  // Step 5: Arm next segment prep.
  ArmSegmentPrep(session_frame_index);

  if (callbacks_.on_segment_start) {
    callbacks_.on_segment_start(from_seg, to_seg, live_parent_block_, session_frame_index);
  }

  { std::ostringstream oss;
    oss << "[PipelineManager] SEGMENT_SEAM_TAKE"
        << " tick=" << session_frame_index
        << " from_segment=" << from_seg << " (" << from_type << ")"
        << " to_segment=" << to_seg << " (" << to_type << ")"
        << " prep_mode=" << prep_mode
        << " swap_branch=" << swap_branch
        << " next_seam_frame=" << FormatFenceTick(next_seam_frame_);
    Logger::Info(oss.str()); }
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.segment_seam_count++;
  }
}

}  // namespace retrovue::blockplan
