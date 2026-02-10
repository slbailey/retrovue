// Repository: Retrovue-playout
// Component: Pipeline Manager
// Purpose: Continuous output loop with TAKE-at-commit source selection (P3.0 + P3.1a + P3.1b)
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/PipelineManager.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <iostream>
#include <memory>
#include <optional>
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

// INV-AUDIO-PRIME-001: Minimum audio buffer depth (ms) required from
// TickProducer::PrimeFirstTick.  The preloader worker thread calls
// PrimeFirstTick which accumulates audio into the primed frame's audio
// vector.  StartFilling() consumes the primed frame synchronously, pushing
// all accumulated audio to the AudioLookaheadBuffer in one non-blocking call.
// 500ms provides headroom above LOW_WATER (333ms), preventing micro-underruns
// during initial playback before the fill thread reaches steady state.
static constexpr int kMinAudioPrimeMs = 500;

PipelineManager::PipelineManager(
    BlockPlanSessionContext* ctx,
    Callbacks callbacks)
    : ctx_(ctx),
      callbacks_(std::move(callbacks)),
      live_(std::make_unique<TickProducer>(ctx->width, ctx->height,
                                                    ctx->fps)),
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

  // Defensive thread-joinable audit: after Run() exits and thread_ is joined,
  // no owned threads should remain joinable.  Hitting any of these means the
  // teardown in Run() (section 7) missed a join — a latent std::terminate bug.
  if (deferred_fill_thread_.joinable()) {
    std::cerr << "[PipelineManager] BUG: deferred_fill_thread_ still joinable "
              << "after Stop(). Joining to prevent std::terminate." << std::endl;
    deferred_fill_thread_.join();
  }
  if (video_buffer_ && video_buffer_->IsFilling()) {
    std::cerr << "[PipelineManager] BUG: video fill thread still running "
              << "after Stop(). Stopping to prevent std::terminate." << std::endl;
    video_buffer_->StopFilling(/*flush=*/true);
  }
  if (preview_video_buffer_ && preview_video_buffer_->IsFilling()) {
    std::cerr << "[PipelineManager] BUG: preview video fill thread still running "
              << "after Stop(). Stopping to prevent std::terminate." << std::endl;
    preview_video_buffer_->StopFilling(/*flush=*/true);
  }
  if (segment_preview_video_buffer_ && segment_preview_video_buffer_->IsFilling()) {
    std::cerr << "[PipelineManager] BUG: segment preview video fill thread still running "
              << "after Stop(). Stopping to prevent std::terminate." << std::endl;
    segment_preview_video_buffer_->StopFilling(/*flush=*/true);
  }
}

void PipelineManager::CleanupDeferredFill() {
  if (deferred_fill_thread_.joinable()) {
    deferred_fill_thread_.join();
  }
  deferred_producer_.reset();
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
  std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
  if (ctx_->block_queue.empty()) return;

  FedBlock block = ctx_->block_queue.front();
  ctx_->block_queue.erase(ctx_->block_queue.begin());

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
  if (seam_preparer_->HasBlockResult()) return;

  // Guard 3: SeamPreparer worker is currently running and no block result yet — don't cancel.
  if (seam_preparer_->IsRunning() && !seam_preparer_->HasBlockResult()) return;

  bool has_next = false;
  FedBlock block;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    has_next = !ctx_->block_queue.empty();
    if (!has_next) {
      if (tick >= 0 && block_fence_frame_ != INT64_MAX &&
          (block_fence_frame_ - tick) < 3000 &&
          (tick == block_fence_frame_ || tick % 900 == 0)) {
        std::cout << "[PipelineManager] PREROLL_DIAG"
                  << " tick=" << tick
                  << " fence_tick=" << block_fence_frame_
                  << " has_next_block=0"
                  << " preview_exists=" << (preview_ != nullptr)
                  << " seam_preparer_has_block=0"
                  << " seam_preparer_running=" << seam_preparer_->IsRunning()
                  << std::endl;
      }
      return;
    }
    block = ctx_->block_queue.front();
    ctx_->block_queue.erase(ctx_->block_queue.begin());
  }

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

  std::cout << "[PipelineManager] PREROLL_ARMED"
            << " tick=" << tick
            << " fence_tick=" << block_fence_frame_
            << " block=" << block.block_id
            << " preview_exists=" << (preview_ != nullptr)
            << std::endl;
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.next_preload_started_count++;
  }
}

// =============================================================================
// TryTakePreviewProducer — non-blocking check for preloader result.
// =============================================================================

std::unique_ptr<producers::IProducer> PipelineManager::TryTakePreviewProducer() {
  auto result = seam_preparer_->TakeBlockResult();
  if (!result) return nullptr;

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
  std::cout << "[PipelineManager] Starting execution thread for channel "
            << ctx_->channel_id << std::endl;

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
    std::cerr << "[PipelineManager] dup(fd) failed: " << strerror(errno)
              << std::endl;
    if (callbacks_.on_session_ended && !session_ended_fired_) {
      session_ended_fired_ = true;
      callbacks_.on_session_ended("dup_failed");
    }
    return;
  }

  // INV-SOCKET-NONBLOCK: SocketSink requires O_NONBLOCK.
  int flags = fcntl(sink_fd, F_GETFL, 0);
  if (flags < 0 || fcntl(sink_fd, F_SETFL, flags | O_NONBLOCK) < 0) {
    std::cerr << "[PipelineManager] fcntl(O_NONBLOCK) failed" << std::endl;
    ::close(sink_fd);
    if (callbacks_.on_session_ended && !session_ended_fired_) {
      session_ended_fired_ = true;
      callbacks_.on_session_ended("nonblock_failed");
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
      std::cerr << "[PipelineManager] WARNING: setsockopt(SO_SNDBUF="
                << requested_sndbuf << ") failed: " << strerror(errno)
                << " (continuing with default)" << std::endl;
    }
    int effective_sndbuf = 0;
    socklen_t elen = sizeof(effective_sndbuf);
    if (getsockopt(sink_fd, SOL_SOCKET, SO_SNDBUF,
                   &effective_sndbuf, &elen) == 0) {
      std::cerr << "[PipelineManager] UDS SO_SNDBUF: requested="
                << requested_sndbuf << " effective=" << effective_sndbuf
                << std::endl;
    }
  }
#endif

  // Buffer capacity: 32 KB ≈ 115 ms at ~284.6 KB/s TS wire rate.
  // Small buffer bounds post-fence old-tail latency; backpressure via
  // WaitAndConsumeBytes blocks the tick thread until the writer drains.
  static constexpr size_t kSinkBufferCapacity = 32 * 1024;
  auto socket_sink = std::make_unique<output::SocketSink>(
      sink_fd, "pipeline-sink", kSinkBufferCapacity);

  // Slow-consumer detach → clean session stop.
  // output_detached is checked in the tick loop condition for immediate exit
  // without waiting for the next boundary check or spamming write errors.
  std::atomic<bool> output_detached{false};
  socket_sink->SetDetachOnOverflow(true);
  socket_sink->SetDetachCallback([this, &output_detached](const std::string& reason) {
    std::cerr << "[PipelineManager] SocketSink detach: " << reason << std::endl;
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
    std::cerr << "[PipelineManager] Failed to open session encoder"
              << std::endl;
    if (callbacks_.on_session_ended && !session_ended_fired_) {
      session_ended_fired_ = true;
      callbacks_.on_session_ended("encoder_failed");
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

  std::cout << "[PipelineManager] Session encoder opened: "
            << ctx_->width << "x" << ctx_->height << " @ " << ctx_->fps
            << "fps, open_ms=" << encoder_open_ms << std::endl;

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
  std::cout << "[INV-PLAYOUT-AUTHORITY] channel_id=" << ctx_->channel_id
            << " | playout_path=blockplan"
            << " | encoder_scope=session"
            << " | execution_model="
            << PlayoutExecutionModeToString(kExecutionMode)
            << " | format=" << ctx_->width << "x" << ctx_->height
            << "@" << ctx_->fps << std::endl;

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
    std::cout << "[PipelineManager] INV-JIP-ANCHOR-001: session_epoch_utc_ms="
              << session_epoch_utc_ms_ << " (Core-authoritative join_utc_ms)"
              << std::endl;
  } else {
    session_epoch_utc_ms_ = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    std::cout << "[PipelineManager] INV-JIP-ANCHOR-001: session_epoch_utc_ms="
              << session_epoch_utc_ms_ << " (local clock fallback, join_utc_ms=0)"
              << std::endl;
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

  // ========================================================================
  // 5. TRY LOADING FIRST BLOCK (before main loop)
  // ========================================================================
  TryLoadLiveProducer();

  // INV-AUDIO-PRIME-001: Prime first block's audio BEFORE clock start.
  // Subsequent blocks are primed by ProducerPreloader::Worker, but block A
  // is loaded synchronously and must be primed here to avoid FENCE_AUDIO_PAD
  // at tick 0.  PrimeFirstTick is safe: it only decodes, no timing dependency.
  if (AsTickProducer(live_.get())->GetState() == ITickProducer::State::kReady &&
      AsTickProducer(live_.get())->HasDecoder()) {
    auto prime_result =
        static_cast<TickProducer*>(live_.get())->PrimeFirstTick(kMinAudioPrimeMs);
    if (!prime_result.met_threshold) {
      std::cerr << "[PipelineManager] INV-AUDIO-PRIME-001: block A prime shortfall"
                << " wanted_ms=" << kMinAudioPrimeMs
                << " got_ms=" << prime_result.actual_depth_ms << std::endl;
    }
  }

  // P3.1b: Kick off preload for next block immediately
  TryKickoffBlockPreload(0);

  // ========================================================================
  // 5b. START OUTPUT CLOCK (monotonic epoch) — after blocking I/O completes.
  // INV-TICK-MONOTONIC-UTC-ANCHOR-001: Tick deadline enforcement anchored
  // to monotonic clock, captured here so tick 0 is not born late.
  // Separated from UTC schedule epoch (captured above) to prevent
  // probe+open+seek latency from triggering a starvation spiral.
  // ========================================================================
  clock.Start();

  // ========================================================================
  // 6. MAIN LOOP
  // ========================================================================
  // Convenience: get ITickProducer* for live_ (refreshed after swaps)
  auto live_tp = [this]() { return AsTickProducer(live_.get()); };

  // Audit helper: emit BLOCK_START log for the current live block.
  auto emit_block_start = [&live_tp](const char* source) {
    const auto& blk = live_tp()->GetBlock();
    std::cout << "[PipelineManager] BLOCK_START"
              << " block=" << blk.block_id
              << " asset=" << (live_tp()->HasDecoder() && !blk.segments.empty()
                  ? blk.segments[0].asset_uri : "pad")
              << " offset_ms=" << (!blk.segments.empty()
                  ? blk.segments[0].asset_start_offset_ms : 0)
              << " frames=" << live_tp()->FramesPerBlock()
              << " source=" << source << std::endl;
  };

  int64_t session_frame_index = 0;

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
    int64_t delta_ms = block.end_utc_ms - session_epoch_utc_ms_;
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

    // INV-SEAM-SEG: Block activation — extract boundaries and compute segment seam frames.
    block_activation_frame_ = session_frame_index;
    live_parent_block_ = live_tp()->GetBlock();
    live_boundaries_ = AsTickProducer(live_.get())->GetBoundaries();
    ComputeSegmentSeamFrames();
    ArmSegmentPrep(session_frame_index);
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

    // Compute PTS (unchanged from P3.0)
    int64_t video_pts_90k = clock.FrameIndexToPts90k(session_frame_index);
    int64_t audio_pts_90k =
        (audio_samples_emitted * 90000) / buffer::kHouseAudioSampleRate;

    // ==================================================================
    // PRE-TAKE READINESS: Stash + preroll BEFORE source selection.
    //
    // The preloader worker may have finished during the sleep.  We must
    // capture the result and start B's fill thread NOW so the TAKE can
    // select B on this tick.  If this ran at the tail, a preloader that
    // finishes during the fence tick's sleep would be invisible to the
    // TAKE, causing a needless pad frame.
    //
    // StartFilling is synchronous for the primed frame: it calls
    // HasPrimedFrame() → TryGetFrame() → push, all non-blocking,
    // so this adds no decode I/O to the tick-critical path.
    // ==================================================================
    // INV-SEAM-SEG: Segment PRE-TAKE readiness — stash segment preview if ready.
    if (!segment_preview_ && seam_preparer_->HasSegmentResult()) {
      auto seg_result = seam_preparer_->TakeSegmentResult();
      if (seg_result) {
        segment_preview_ = std::move(seg_result->producer);
        std::cout << "[PipelineManager] SEGMENT_PREROLL_STATUS"
                  << " block=" << seg_result->block_id
                  << " segment_index=" << seg_result->segment_index
                  << " segment_type=" << SegmentTypeName(seg_result->segment_type)
                  << " audio_depth_ms=" << seg_result->audio_prime_depth_ms
                  << std::endl;
      }
    }
    if (segment_preview_ && !segment_preview_video_buffer_ &&
        AsTickProducer(segment_preview_.get())->GetState() == ITickProducer::State::kReady) {
      segment_preview_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(
          video_buffer_->TargetDepthFrames(), video_buffer_->LowWaterFrames());
      const auto& scfg = ctx_->buffer_config;
      int sa_target = scfg.audio_target_depth_ms;
      int sa_low = scfg.audio_low_water_ms > 0
          ? scfg.audio_low_water_ms
          : std::max(1, sa_target / 3);
      segment_preview_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
          sa_target, buffer::kHouseAudioSampleRate,
          buffer::kHouseAudioChannels, sa_low);
      auto* seg_tp = AsTickProducer(segment_preview_.get());
      segment_preview_video_buffer_->StartFilling(
          seg_tp, segment_preview_audio_buffer_.get(),
          seg_tp->GetInputFPS(), ctx_->fps,
          &ctx_->stop_requested);
      std::cout << "[PipelineManager] SEGMENT_PREROLL_START"
                << " tick=" << session_frame_index
                << " next_seam_frame=" << next_seam_frame_
                << " headroom=" << (next_seam_frame_ - session_frame_index)
                << std::endl;
    }

    if (!preview_ && seam_preparer_->HasBlockResult()) {
      preview_ = TryTakePreviewProducer();
      if (preview_) {
        const bool met = (preview_audio_prime_depth_ms_ >= kMinAudioPrimeMs);
        std::cout << "[PipelineManager] PREROLL_STATUS"
                  << " block=" << AsTickProducer(preview_.get())->GetBlock().block_id
                  << " met_threshold=" << met
                  << " depth_ms=" << preview_audio_prime_depth_ms_
                  << " wanted_ms=" << kMinAudioPrimeMs
                  << std::endl;
      }
    }
    if (preview_ && !preview_video_buffer_ &&
        AsTickProducer(preview_.get())->GetState() == ITickProducer::State::kReady) {
      preview_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(
          video_buffer_->TargetDepthFrames(), video_buffer_->LowWaterFrames());
      const auto& pcfg = ctx_->buffer_config;
      int pa_target = pcfg.audio_target_depth_ms;
      int pa_low = pcfg.audio_low_water_ms > 0
          ? pcfg.audio_low_water_ms
          : std::max(1, pa_target / 3);
      preview_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
          pa_target, buffer::kHouseAudioSampleRate,
          buffer::kHouseAudioChannels, pa_low);
      auto* preview_tp = AsTickProducer(preview_.get());
      preview_video_buffer_->StartFilling(
          preview_tp, preview_audio_buffer_.get(),
          preview_tp->GetInputFPS(), ctx_->fps,
          &ctx_->stop_requested);
      std::cout << "[PipelineManager] PREROLL_START"
                << " block=" << preview_tp->GetBlock().block_id
                << " fence_tick=" << block_fence_frame_
                << " tick=" << session_frame_index
                << " headroom=" << (block_fence_frame_ - session_frame_index)
                << std::endl;
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

    // ── TAKE: unified source selection based on tick vs next seam ──
    const bool take = (session_frame_index >= next_seam_frame_);
    const bool take_b = take && (next_seam_type_ == SeamType::kBlock);
    const bool take_segment = take && (next_seam_type_ == SeamType::kSegment);

    // Policy B: TAKE_READINESS — log audio headroom at the moment of TAKE.
    if (take_b && !take_rotated && preview_) {
      const bool met = (preview_audio_prime_depth_ms_ >= kMinAudioPrimeMs);
      std::cout << "[PipelineManager] TAKE_READINESS"
                << " block=" << AsTickProducer(preview_.get())->GetBlock().block_id
                << " depth_ms_at_take=" << preview_audio_prime_depth_ms_
                << " wanted_ms=" << kMinAudioPrimeMs
                << " met_threshold=" << met
                << std::endl;
    }

    VideoLookaheadBuffer* v_src;
    AudioLookaheadBuffer* a_src;
    if (take_b && preview_video_buffer_) {
      v_src = preview_video_buffer_.get();        // Block swap: B buffers
      a_src = preview_audio_buffer_.get();
    } else if (take_segment && segment_preview_video_buffer_) {
      v_src = segment_preview_video_buffer_.get(); // Segment swap: segment B buffers
      a_src = segment_preview_audio_buffer_.get();
    } else if (take_b) {
      v_src = preview_video_buffer_.get();         // Block swap: may be null
      a_src = preview_audio_buffer_.get();
    } else {
      v_src = video_buffer_.get();                 // No swap: A buffers
      a_src = audio_buffer_.get();
    }
    const char* commit_slot = take_b ? "B" : (take_segment ? "S" : "A");
    // Authoritative TAKE slot source for fingerprint:
    //   'A' = live buffer slot, 'B' = preview buffer slot, 'P' = pad.
    // This is a slot identifier, not a block identifier.  After PADDED_GAP
    // exit, the new block occupies the live slot and is labeled 'A'.
    // Use active_block_id (from live_tp()->GetBlock()) for block identity.
    char take_source_char = 'P';

    // INV-PREROLL-READY-001: On the fence tick, B SHOULD be primed.
    // If it's not, log the failure mode for diagnostics.  The TAKE
    // falls through to pad — no correctness violation, but a missed
    // preroll that should be investigated.
    if (take_b && (!v_src || !v_src->IsPrimed()) && !take_rotated) {
      std::cerr << "[PipelineManager] INV-PREROLL-READY-001: B NOT PRIMED at fence"
                << " tick=" << session_frame_index
                << " fence_tick=" << block_fence_frame_
                << " preview_exists=" << (preview_ != nullptr)
                << " preview_vbuf=" << (preview_video_buffer_ != nullptr)
                << " seam_has_block=" << seam_preparer_->HasBlockResult()
                << std::endl;
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
    } else if (take_b) {
      // B not primed or empty at fence — PADDED_GAP.
    } else if (a_was_primed) {
      // A was primed before TryPopFrame, but pop still failed → genuine underflow.
      std::cerr << "[PipelineManager] INV-VIDEO-LOOKAHEAD-001: UNDERFLOW"
                << " frame=" << session_frame_index
                << " buffer_depth=" << v_src->DepthFrames()
                << " total_pushed=" << v_src->TotalFramesPushed()
                << " total_popped=" << v_src->TotalFramesPopped()
                << std::endl;
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
      std::cout << "[PipelineManager] TAKE_PAD_ENTER"
                << " tick=" << session_frame_index
                << " slot=" << commit_slot
                << std::endl;
    } else if (!is_pad && prev_was_pad) {
      std::cout << "[PipelineManager] TAKE_PAD_EXIT"
                << " tick=" << session_frame_index
                << " slot=" << commit_slot
                << " block=" << (live_tp()->GetState() == ITickProducer::State::kReady
                    ? live_tp()->GetBlock().block_id : "none")
                << std::endl;
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
      } else if (!take_b &&
                 live_tp()->GetState() == ITickProducer::State::kReady) {
        block_id = live_tp()->GetBlock().block_id;
      }
      if (!is_pad) asset_uri = vbf.asset_uri;
      std::cout << "[PipelineManager] TAKE_COMMIT"
                << " tick=" << session_frame_index
                << " fence_tick=" << block_fence_frame_
                << " slot=" << commit_slot
                << " is_pad=" << is_pad
                << " block=" << (block_id.empty() ? "none" : block_id)
                << " asset=" << (asset_uri.empty() ? (is_pad ? "pad" : "unknown") : asset_uri)
                << " v_buf_depth=" << (v_src ? v_src->DepthFrames() : -1)
                << " a_buf_depth_ms=" << (a_src ? a_src->DepthMs() : -1)
                << std::endl;
    }

    // ==================================================================
    // POST-TAKE ROTATION: On the first tick at or past the fence, stop
    // A's fill thread, rotate B→A, and set up the next block's fence.
    // This runs AFTER the frame is committed so the TAKE itself is the
    // selector — not a buffer swap.
    // ==================================================================
    if (take_b && !take_rotated) {
      take_rotated = true;

      // Step 1: Join PREVIOUS fence's deferred fill thread.
      CleanupDeferredFill();

      // Step 2: Stop A's fill thread (non-blocking async stop).
      auto detached = video_buffer_->StopFillingAsync(/*flush=*/true);
      audio_buffer_->Reset();

      // Step 3: Snapshot outgoing block and finalize accumulator.
      const FedBlock outgoing_block = live_tp()->GetBlock();
      std::optional<BlockPlaybackSummary> outgoing_summary;
      std::optional<BlockPlaybackProof> outgoing_proof;
      int64_t ct_at_fence_ms = -1;
      if (!block_acc.block_id.empty()) {
        auto summary = block_acc.Finalize();
        ct_at_fence_ms = summary.last_block_ct_ms;
        auto proof = BuildPlaybackProof(
            outgoing_block, summary, clock.FrameDurationMs());
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
        if (!swapped && ctx_->fence_fallback_sync) {
          std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
          if (!ctx_->block_queue.empty()) {
            FedBlock block = ctx_->block_queue.front();
            ctx_->block_queue.erase(ctx_->block_queue.begin());
            auto fresh = std::make_unique<TickProducer>(
                ctx_->width, ctx_->height, ctx_->fps);
            AsTickProducer(fresh.get())->AssignBlock(block);
            live_ = std::move(fresh);
            swapped = true;
          }
        }
        // If swapped via fallback, start fill on existing A buffers.
        if (swapped) {
          video_buffer_->StopFilling(/*flush=*/true);
          audio_buffer_->Reset();
          video_buffer_->StartFilling(
              AsTickProducer(live_.get()), audio_buffer_.get(),
              AsTickProducer(live_.get())->GetInputFPS(), ctx_->fps,
              &ctx_->stop_requested);
        }
      }

      if (!swapped) {
        // No B available — PADDED_GAP.
        live_ = std::make_unique<TickProducer>(ctx_->width, ctx_->height, ctx_->fps);
        block_fence_frame_ = INT64_MAX;
        next_seam_frame_ = INT64_MAX;
        next_seam_type_ = SeamType::kNone;
        past_fence = true;
        { std::lock_guard<std::mutex> lock(metrics_mutex_);
          metrics_.fence_preload_miss_count++;
          metrics_.padded_gap_count++; }
        std::cout << "[PipelineManager] PADDED_GAP_ENTER"
                  << " fence_frame=" << session_frame_index
                  << " outgoing=" << (outgoing_summary ? outgoing_summary->block_id : "none")
                  << std::endl;
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

        int audio_depth = audio_buffer_->DepthMs();
        if (audio_depth < kMinAudioPrimeMs) {
          std::cerr << "[PipelineManager] INV-AUDIO-PRIME-001 WARN: audio_depth_ms="
                    << audio_depth << " required=" << kMinAudioPrimeMs
                    << " at fence frame " << session_frame_index
                    << " block=" << live_tp()->GetBlock().block_id
                    << " — safety-net silence will cover" << std::endl;
        }

        // Policy B: track degraded TAKEs where audio prime was below threshold.
        // Uses preview_audio_prime_depth_ms_ captured at preloader TakeSource time.
        if (preview_audio_prime_depth_ms_ < kMinAudioPrimeMs) {
          std::cerr << "[PipelineManager] DEGRADED_TAKE"
                    << " block=" << live_tp()->GetBlock().block_id
                    << " prime_depth_ms=" << preview_audio_prime_depth_ms_
                    << " wanted_ms=" << kMinAudioPrimeMs
                    << " audio_buf_depth_ms=" << audio_depth
                    << std::endl;
          std::lock_guard<std::mutex> lock(metrics_mutex_);
          metrics_.degraded_take_count++;
        }

        TryKickoffBlockPreload(session_frame_index);
      }

      // Step 6: Store deferred thread + producer for later cleanup.
      deferred_fill_thread_ = std::move(detached.thread);
      deferred_producer_ = std::move(outgoing_producer);

      // Step 7: Emit finalization logs.
      if (outgoing_summary) {
        std::cout << FormatPlaybackSummary(*outgoing_summary) << std::endl;
        if (callbacks_.on_block_summary) {
          callbacks_.on_block_summary(*outgoing_summary);
        }
      }
      if (outgoing_proof) {
        std::cout << FormatPlaybackProof(*outgoing_proof) << std::endl;
        if (callbacks_.on_playback_proof) {
          callbacks_.on_playback_proof(*outgoing_proof);
        }
      }

      if (outgoing_summary) {
        int64_t base_offset = !outgoing_block.segments.empty()
            ? outgoing_block.segments[0].asset_start_offset_ms : 0;
        std::cout << "[PipelineManager] BLOCK_COMPLETE"
                  << " block=" << outgoing_summary->block_id
                  << " fence_frame=" << compute_fence_frame(outgoing_block)
                  << " emitted=" << outgoing_summary->frames_emitted
                  << " pad=" << outgoing_summary->pad_frames
                  << " asset=" << (!outgoing_summary->asset_uris.empty()
                      ? outgoing_summary->asset_uris[0] : "pad");
        if (outgoing_summary->first_block_ct_ms >= 0) {
          std::cout << " range_ms="
                    << (base_offset + outgoing_summary->first_block_ct_ms)
                    << "->"
                    << (base_offset + outgoing_summary->last_block_ct_ms);
        }
        std::cout << std::endl;
      }

      {
        int64_t now_utc_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        int64_t delta_ms = now_utc_ms - outgoing_block.end_utc_ms;
        std::cout << "[PipelineManager] INV-BLOCK-WALLFENCE-001: FENCE"
                  << " block=" << outgoing_block.block_id
                  << " scheduled_end_ms=" << outgoing_block.end_utc_ms
                  << " actual_ms=" << now_utc_ms
                  << " delta_ms=" << delta_ms
                  << " ct_at_fence_ms=" << ct_at_fence_ms
                  << " fence_frame=" << compute_fence_frame(outgoing_block)
                  << " session_frame=" << session_frame_index
                  << " remaining_budget=" << remaining_block_frames_
                  << std::endl;
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
        std::cout << FormatSeamTransition(seam) << std::endl;
        if (callbacks_.on_seam_transition) {
          callbacks_.on_seam_transition(seam);
        }
      }

      if (callbacks_.on_block_completed) {
        callbacks_.on_block_completed(outgoing_block, session_frame_index);
      }
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

      std::cout << "[PipelineManager] SEAM_PROOF_FENCE"
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
                << " audio_buf_depth_ms=" << audio_buffer_->DepthMs()
                << std::endl;

      // Reset take_rotated for next fence cycle.
      take_rotated = false;
    }

    // ==================================================================
    // SEGMENT POST-TAKE: On the segment seam tick, swap segment preview
    // into live.  Only fires when take_segment is true (not a block seam).
    // ==================================================================
    if (take_segment) {
      PerformSegmentSwap(session_frame_index);
    }

    if (is_pad) {
      // INV-PAD-PRODUCER-005: TAKE selects PadProducer at commitment point.
      // Same encodeFrame path as content (single commitment path).
      // INV-PAD-PRODUCER-001: No per-tick allocation — pre-allocated frames.
#ifdef RETROVUE_DEBUG_PAD_EMIT
      std::cerr << "[PipelineManager] DBG-PAD-EMIT"
                << " frame=" << session_frame_index
                << " slot=" << take_source_char
                << " y_crc32=0x" << std::hex << pad_producer_->VideoCRC32() << std::dec
                << " video_pts_90k=" << video_pts_90k
                << std::endl;
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
    if (!is_pad) {
      // Exact per-tick sample count via rational arithmetic (drift-free).
      // samples_this_tick = floor((N+1)*sr*fps_den/fps_num)
      //                   - floor(N*sr*fps_den/fps_num)
      int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
      int64_t next_total =
          ((audio_ticks_emitted + 1) * sr * ctx_->fps_den) / ctx_->fps_num;
      int samples_this_tick =
          static_cast<int>(next_total - audio_buffer_samples_emitted);

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
          std::cerr << "[PipelineManager] AUDIO_UNDERFLOW_SILENCE"
                    << " frame=" << session_frame_index
                    << " buffer_depth_ms=" << a_src->DepthMs()
                    << " needed=" << samples_this_tick
                    << " total_pushed=" << a_src->TotalSamplesPushed()
                    << " total_popped=" << a_src->TotalSamplesPopped()
                    << std::endl;

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

        std::cerr << "[PipelineManager] WARNING FENCE_AUDIO_PAD: audio not primed"
                  << " tick=" << session_frame_index
                  << " samples=" << samples_this_tick
                  << " audio_pts_90k=" << audio_pts_90k
                  << " video_pts_90k=" << video_pts_90k
                  << std::endl;
        // OUT-SEG-005b: Fence pad silence = fallback tick.
        current_consecutive_fallback_ticks++;
      }
    }

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

      std::cout << "[PipelineManager] SEAM_PROOF_TICK"
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
                << " video_buf_depth=" << video_buffer_->DepthFrames()
                << std::endl;
    }

    // SEAM_PROOF_FIRST_FRAME: Log when first non-pad frame from the incoming
    // block reaches the encoder.  activation_delay_ticks=0 means the incoming
    // block's first frame was emitted on the fence tick itself.
    if (!seam_proof_first_frame_logged && !is_pad &&
        seam_proof_fence_tick >= 0) {
      seam_proof_first_frame_logged = true;
      int64_t activation_delay = session_frame_index - seam_proof_fence_tick;
      std::cout << "[PipelineManager] SEAM_PROOF_FIRST_FRAME"
                << " tick=" << session_frame_index
                << " fence_tick=" << seam_proof_fence_tick
                << " incoming=" << seam_proof_incoming_id
                << " activation_delay_ticks=" << activation_delay
                << " video_pts_90k=" << video_pts_90k
                << " audio_pts_90k=" << audio_pts_90k
                << " av_delta_90k=" << (video_pts_90k - audio_pts_90k)
                << " video_asset=" << vbf.asset_uri
                << " video_ct_ms=" << vbf.block_ct_ms
                << " video_decoded=" << vbf.was_decoded
                << std::endl;
    }

    // HEARTBEAT: telemetry snapshot for performance regression detection.
    // ~3000 ticks ≈ 100s at 30fps.  Metrics are always available via
    // /metrics endpoint regardless of log frequency.
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

      // Single consolidated log line.
      std::cout << "[PipelineManager] HEARTBEAT"
                << " frame=" << session_frame_index;
      if (video_buffer_) {
        std::cout << " video=" << video_buffer_->DepthFrames()
                  << "/" << video_buffer_->TargetDepthFrames()
                  << " refill=" << video_buffer_->RefillRateFps() << "fps"
                  << " decode_p95=" << video_buffer_->DecodeLatencyP95Us() << "us";
      }
      if (audio_buffer_) {
        int64_t a_pushed = audio_buffer_->TotalSamplesPushed();
        int64_t a_popped = audio_buffer_->TotalSamplesPopped();
        std::cout << " audio=" << audio_buffer_->DepthMs() << "ms"
                  << "/" << audio_buffer_->TargetDepthMs() << "ms"
                  << " a_pushed=" << a_pushed
                  << " a_popped=" << a_popped;
      }
      {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        if (metrics_.audio_silence_injected > 0) {
          std::cout << " silence_injected=" << metrics_.audio_silence_injected;
        }
      }
      if (socket_sink) {
        std::cout << " sink=" << socket_sink->GetCurrentBufferSize()
                  << "/" << socket_sink->GetBufferCapacity();
      }
      std::cout << std::endl;

      // Low-water warnings (throttled to heartbeat interval).
      if (video_buffer_ && video_buffer_->IsBelowLowWater()) {
        std::cerr << "[PipelineManager] LOW_WATER video="
                  << video_buffer_->DepthFrames()
                  << " threshold=" << video_buffer_->LowWaterFrames()
                  << std::endl;
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.video_low_water_events++;
      }
      if (audio_buffer_ && audio_buffer_->IsBelowLowWater()) {
        std::cerr << "[PipelineManager] LOW_WATER audio="
                  << audio_buffer_->DepthMs() << "ms"
                  << " threshold=" << audio_buffer_->LowWaterMs() << "ms"
                  << std::endl;
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
        // INV-PAD-PRODUCER-003: Cached CRC32 — no per-tick recomputation.
        fp.asset_uri = PadProducer::kAssetUri;
        fp.y_crc32 = pad_producer_->VideoCRC32();
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
          std::cout << FormatSeamTransition(seam) << std::endl;
          if (callbacks_.on_seam_transition) {
            callbacks_.on_seam_transition(seam);
          }
          prev_completed_block_id.clear();
        }

        // P3.3: Reset accumulator for new block
        block_acc.Reset(live_tp()->GetBlock().block_id);
        emit_block_start((had_preview && !preview_) ? "preview" : "queue");
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

        std::cout << "[PipelineManager] PADDED_GAP_EXIT"
                  << " frame=" << session_frame_index
                  << " gap_frames=" << fence_pad_counter
                  << " block=" << live_tp()->GetBlock().block_id
                  << std::endl;
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
  CleanupDeferredFill();

  // INV-VIDEO-LOOKAHEAD-001: Stop video fill thread before resetting producers.
  if (video_buffer_) {
    video_buffer_->StopFilling(/*flush=*/true);
  }
  // Stop B preroll buffers if still running.
  if (preview_video_buffer_) {
    preview_video_buffer_->StopFilling(/*flush=*/true);
    preview_video_buffer_.reset();
  }
  preview_audio_buffer_.reset();

  // Stop segment preview buffers if still running.
  if (segment_preview_video_buffer_) {
    segment_preview_video_buffer_->StopFilling(/*flush=*/true);
    segment_preview_video_buffer_.reset();
  }
  segment_preview_audio_buffer_.reset();
  segment_preview_.reset();

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
    std::cout << "[PipelineManager] Session encoder closed: "
              << write_ctx.bytes_written << " bytes written" << std::endl;
  }

  // Close SocketSink AFTER encoder — encoder->close() flushes final packets
  // through the write callback into the sink buffer.  SocketSink::Close()
  // signals the writer thread to drain remaining bytes and shut down.
  if (socket_sink) {
    socket_sink->Close();
    std::cout << "[PipelineManager] SocketSink closed: delivered="
              << socket_sink->GetBytesDelivered()
              << " enqueued=" << socket_sink->GetBytesEnqueued()
              << " errors=" << socket_sink->GetWriteErrors()
              << " detached=" << socket_sink->IsDetached() << std::endl;
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

  std::cout << "[PipelineManager] Thread exiting: frames_emitted="
            << session_frame_index
            << ", reason=" << termination_reason << std::endl;

  if (callbacks_.on_session_ended && !session_ended_fired_) {
    session_ended_fired_ = true;
    callbacks_.on_session_ended(termination_reason);
  }
}

void PipelineManager::SetPreloaderDelayHook(
    std::function<void()> hook) {
  seam_preparer_->SetDelayHook(std::move(hook));
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

  // Use live_parent_block_ (the original multi-segment block stored at block
  // activation), NOT live_->GetBlock().  After a segment swap, live_ holds a
  // synthetic single-segment block, so live_->GetBlock().segments[next_seg]
  // would be out of range.
  FedBlock synth = MakeSyntheticSegmentBlock(
      live_parent_block_, next_seg, live_boundaries_);

  // Determine segment type for logging.
  const char* seg_type_name = "UNKNOWN";
  if (next_seg < static_cast<int32_t>(live_parent_block_.segments.size())) {
    seg_type_name = SegmentTypeName(
        live_parent_block_.segments[next_seg].segment_type);
  }

  SeamRequest req;
  req.type = SeamRequestType::kSegment;
  req.block = std::move(synth);
  req.seam_frame = (current_segment_index_ < static_cast<int32_t>(segment_seam_frames_.size()))
      ? segment_seam_frames_[current_segment_index_]
      : INT64_MAX;
  req.width = ctx_->width;
  req.height = ctx_->height;
  req.fps = ctx_->fps;
  req.min_audio_prime_ms = kMinAudioPrimeMs;
  req.parent_block_id = live_parent_block_.block_id;
  req.segment_index = next_seg;
  seam_preparer_->Submit(std::move(req));

  std::cout << "[PipelineManager] SEGMENT_PREP_ARMED"
            << " tick=" << session_frame_index
            << " parent_block=" << live_parent_block_.block_id
            << " next_segment=" << next_seg
            << " segment_type=" << seg_type_name
            << " seam_frame=" << (current_segment_index_ < static_cast<int32_t>(segment_seam_frames_.size())
                ? segment_seam_frames_[current_segment_index_] : INT64_MAX)
            << std::endl;
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.segment_prep_armed_count++;
  }
}

// =============================================================================
// PerformSegmentSwap — segment POST-TAKE: rotate segment preview into live
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
  CleanupDeferredFill();

  // Step 2: Stop A's fill thread (async).
  auto detached = video_buffer_->StopFillingAsync(/*flush=*/true);
  audio_buffer_->Reset();

  // Step 3: Save old live_ for deferred cleanup.
  auto outgoing_producer = std::move(live_);

  // Step 4: Swap segment preview into live.
  // prep_mode tracks how the incoming segment was acquired:
  //   PREROLLED — preview buffers were filled ahead of time
  //   INSTANT   — PAD segment (trivially prepared, no decoder work)
  //   MISS      — neither preview nor result available; emergency PAD fallback
  const char* prep_mode = "MISS";
  bool swapped = false;
  if (segment_preview_video_buffer_) {
    video_buffer_ = std::move(segment_preview_video_buffer_);
    audio_buffer_ = std::move(segment_preview_audio_buffer_);
    live_ = std::move(segment_preview_);
    swapped = true;
    // PAD segments go through the same prep pipeline but complete trivially
    // (no decoder open, no audio prime).  Label as INSTANT to distinguish
    // from content/filler segments that required real decode work.
    prep_mode = incoming_is_pad ? "INSTANT" : "PREROLLED";
  } else if (seam_preparer_->HasSegmentResult()) {
    auto result = seam_preparer_->TakeSegmentResult();
    if (result && result->producer) {
      live_ = std::move(result->producer);
      // Create fresh buffers and start filling.
      video_buffer_->StopFilling(/*flush=*/true);
      audio_buffer_->Reset();
      video_buffer_ = std::make_unique<VideoLookaheadBuffer>(
          video_buffer_ ? video_buffer_->TargetDepthFrames() : 15,
          video_buffer_ ? video_buffer_->LowWaterFrames() : 5);
      const auto& bcfg = ctx_->buffer_config;
      int a_target = bcfg.audio_target_depth_ms;
      int a_low = bcfg.audio_low_water_ms > 0
          ? bcfg.audio_low_water_ms
          : std::max(1, a_target / 3);
      audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
          a_target, buffer::kHouseAudioSampleRate,
          buffer::kHouseAudioChannels, a_low);
      video_buffer_->StartFilling(
          AsTickProducer(live_.get()), audio_buffer_.get(),
          AsTickProducer(live_.get())->GetInputFPS(), ctx_->fps,
          &ctx_->stop_requested);
      swapped = true;
      prep_mode = incoming_is_pad ? "INSTANT" : "PREROLLED";
    }
  }

  if (!swapped) {
    // INV-SEAM-SEG-007: Segment miss — PAD fallback (no audio underflow).
    live_ = std::make_unique<TickProducer>(ctx_->width, ctx_->height, ctx_->fps);
    video_buffer_ = std::make_unique<VideoLookaheadBuffer>(15, 5);
    const auto& bcfg = ctx_->buffer_config;
    int a_target = bcfg.audio_target_depth_ms;
    int a_low = bcfg.audio_low_water_ms > 0
        ? bcfg.audio_low_water_ms
        : std::max(1, a_target / 3);
    audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(
        a_target, buffer::kHouseAudioSampleRate,
        buffer::kHouseAudioChannels, a_low);
    video_buffer_->StartFilling(
        AsTickProducer(live_.get()), audio_buffer_.get(),
        0.0, ctx_->fps,
        &ctx_->stop_requested);
    swapped = true;
    prep_mode = "MISS";
    std::cerr << "[PipelineManager] SEGMENT_SEAM_PAD_FALLBACK"
              << " tick=" << session_frame_index
              << " segment_index=" << current_segment_index_
              << std::endl;
    {
      std::lock_guard<std::mutex> lock(metrics_mutex_);
      metrics_.segment_seam_miss_count++;
    }
  } else {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.segment_seam_ready_count++;
  }

  // Step 5: Advance segment index and update next seam frame.
  current_segment_index_++;
  UpdateNextSeamFrame();

  // Step 6: Store deferred thread + producer.
  deferred_fill_thread_ = std::move(detached.thread);
  deferred_producer_ = std::move(outgoing_producer);

  // Step 7: Arm next segment prep (call site #4).
  ArmSegmentPrep(session_frame_index);

  // Step 8: Log and metrics.
  std::cout << "[PipelineManager] SEGMENT_SEAM_TAKE"
            << " tick=" << session_frame_index
            << " from_segment=" << from_seg << " (" << from_type << ")"
            << " to_segment=" << to_seg << " (" << to_type << ")"
            << " prep_mode=" << prep_mode
            << " next_seam_frame=" << next_seam_frame_
            << std::endl;
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.segment_seam_count++;
  }
}

}  // namespace retrovue::blockplan
