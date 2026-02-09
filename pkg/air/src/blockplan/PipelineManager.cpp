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
#include "retrovue/blockplan/ProducerPreloader.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/output/SocketSink.h"

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
// At 30fps, one tick ≈ 33ms.  100ms gives ~3 ticks of margin.
static constexpr int kMinAudioPrimeMs = 100;

PipelineManager::PipelineManager(
    BlockPlanSessionContext* ctx,
    Callbacks callbacks)
    : ctx_(ctx),
      callbacks_(std::move(callbacks)),
      live_(std::make_unique<TickProducer>(ctx->width, ctx->height,
                                                    ctx->fps)),
      preloader_(std::make_unique<ProducerPreloader>()) {
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
  preloader_->Cancel();
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
// EmitPadFrame — black video + silent audio at the given PTS
// =============================================================================

void PipelineManager::EmitPadFrame(
    playout_sinks::mpegts::EncoderPipeline* encoder,
    int64_t video_pts_90k,
    int64_t audio_pts_90k) {
  // --- Video: black YUV420P frame ---
  const int w = ctx_->width;
  const int h = ctx_->height;
  const int y_size = w * h;
  const int uv_size = (w / 2) * (h / 2);

  buffer::Frame frame;
  frame.width = w;
  frame.height = h;
  frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));

  // Y = 0x10 (broadcast black), U/V = 0x80 (neutral chroma)
  std::memset(frame.data.data(), 0x10, static_cast<size_t>(y_size));
  std::memset(frame.data.data() + y_size, 0x80, static_cast<size_t>(2 * uv_size));

  encoder->encodeFrame(frame, video_pts_90k);

  // --- Audio: silence (1024 samples, stereo S16) ---
  static constexpr int kSamplesPerFrame = 1024;
  static constexpr int kChannels = buffer::kHouseAudioChannels;
  static constexpr int kSampleRate = buffer::kHouseAudioSampleRate;

  buffer::AudioFrame audio;
  audio.sample_rate = kSampleRate;
  audio.channels = kChannels;
  audio.nb_samples = kSamplesPerFrame;
  audio.data.resize(
      static_cast<size_t>(kSamplesPerFrame * kChannels) * sizeof(int16_t), 0);

  encoder->encodeAudioFrame(audio, audio_pts_90k, /*is_silence_pad=*/true);
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
// TryKickoffPreviewPreload — start preloading the next block if conditions met.
// Called outside the tick window only.
// =============================================================================

void PipelineManager::TryKickoffPreviewPreload() {
  // Only preload when: live is READY, preview is empty, no preload running
  if (AsTickProducer(live_.get())->GetState() != ITickProducer::State::kReady) return;
  if (preview_) return;  // Already have a preloaded preview
  if (preloader_->IsReady()) return;  // Preload finished, not yet consumed

  FedBlock block;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    if (ctx_->block_queue.empty()) return;
    block = ctx_->block_queue.front();
    ctx_->block_queue.erase(ctx_->block_queue.begin());
  }

  preloader_->StartPreload(block, ctx_->width, ctx_->height, ctx_->fps,
                           kMinAudioPrimeMs);
  {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.next_preload_started_count++;
  }
}

// =============================================================================
// TryTakePreviewProducer — non-blocking check for preloader result.
// =============================================================================

std::unique_ptr<producers::IProducer> PipelineManager::TryTakePreviewProducer() {
  auto src = preloader_->TakeSource();
  if (src) {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.next_preload_ready_count++;
  }
  return src;
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

  // INV-BLOCK-WALLFENCE-001: Capture UTC schedule epoch BEFORE blocking I/O.
  // Fence math maps absolute UTC schedule times (block.end_utc_ms) to session
  // frame indices.  The epoch must reflect when the schedule timeline started,
  // not when the first frame was emitted — the schedule is running regardless
  // of probe/open/seek latency.
  session_epoch_utc_ms_ = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

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

  // P3.1b: Kick off preload for next block immediately
  TryKickoffPreviewPreload();

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
    if (!preview_ && preloader_->IsReady()) {
      preview_ = TryTakePreviewProducer();
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

    // ── TAKE: select source based on tick vs fence ──
    const bool take_b = (session_frame_index >= block_fence_frame_);
    VideoLookaheadBuffer* v_src = take_b
        ? preview_video_buffer_.get() : video_buffer_.get();
    AudioLookaheadBuffer* a_src = take_b
        ? preview_audio_buffer_.get() : audio_buffer_.get();
    const char* commit_source = take_b ? "B" : "A";
    // Authoritative TAKE source for fingerprint: 'A', 'B', or 'P' (pad).
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
                << " preloader_ready=" << preloader_->IsReady()
                << std::endl;
    }

    if (v_src && v_src->IsPrimed() && v_src->TryPopFrame(vbf)) {
      session_encoder->encodeFrame(vbf.video, video_pts_90k);
      is_pad = false;
      take_source_char = take_b ? 'B' : 'A';
    } else if (take_b) {
      // B not primed at fence — PADDED_GAP.  A is NEVER consulted.
      // (pad frame emitted below)
    } else if (v_src && v_src->IsPrimed()) {
      // A underflow — hard fault: session stop.
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
    // else: A not primed (no block loaded) — falls through to pad.

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
                << " source=" << commit_source
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

        int audio_depth = audio_buffer_->DepthMs();
        if (audio_depth < kMinAudioPrimeMs) {
          std::cerr << "[PipelineManager] INV-AUDIO-PRIME-001 WARN: audio_depth_ms="
                    << audio_depth << " required=" << kMinAudioPrimeMs
                    << " at fence frame " << session_frame_index
                    << " block=" << live_tp()->GetBlock().block_id
                    << " — safety-net silence will cover" << std::endl;
        }

        TryKickoffPreviewPreload();
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

    if (is_pad) {
      EmitPadFrame(session_encoder.get(), video_pts_90k, audio_pts_90k);
      audio_samples_emitted += kAudioSamplesPerFrame;
      audio_frames_this_tick = 1;
      if (past_fence) {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.fence_pad_frames_total++;
      }
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
        } else {
          // UNDERFLOW — hard fault: detach viewer, stop session.
          std::cerr << "[PipelineManager] INV-AUDIO-LOOKAHEAD-001: UNDERFLOW"
                    << " frame=" << session_frame_index
                    << " buffer_depth_ms=" << a_src->DepthMs()
                    << " needed=" << samples_this_tick
                    << " total_pushed=" << a_src->TotalSamplesPushed()
                    << " total_popped=" << a_src->TotalSamplesPopped()
                    << std::endl;
          { std::lock_guard<std::mutex> lock(metrics_mutex_); metrics_.detach_count++; }
          ctx_->stop_requested.store(true, std::memory_order_release);
          break;
        }
      } else {
        // SAFETY NET: Audio buffer not primed despite INV-AUDIO-PRIME-001.
        // This should never happen — if it does, the priming in StartFilling
        // didn't reach the threshold (e.g., content with no audio track).
        // Emit pad silence to prevent A/V drift; log at WARNING level.
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
        std::cout << " audio=" << audio_buffer_->DepthMs() << "ms"
                  << "/" << audio_buffer_->TargetDepthMs() << "ms";
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
      fp.commit_source = take_source_char;
      if (live_tp()->GetState() == ITickProducer::State::kReady) {
        fp.active_block_id = live_tp()->GetBlock().block_id;
      }
      if (!is_pad && vbf.was_decoded) {
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

    // LOAD NEXT from queue if source is empty (fallback path).
    // G6 FIX: No late-tick guard for kEmpty — pad-mode ticks have no decode
    // work; loading a block is always preferable to emitting more pad frames.
    if (live_tp()->GetState() == ITickProducer::State::kEmpty) {
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
        std::cout << "[PipelineManager] PADDED_GAP_EXIT"
                  << " frame=" << session_frame_index
                  << " gap_frames=" << fence_pad_counter
                  << " block=" << live_tp()->GetBlock().block_id
                  << std::endl;
        fence_pad_counter = 0;

        past_fence = false;
        // Kick off preload for the next one
        TryKickoffPreviewPreload();
      }
    }

    // P3.1b: Try to start preloading if conditions met
    // (stash + preroll moved to pre-TAKE readiness block above)
    TryKickoffPreviewPreload();

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

  // Cancel preloader and reset sources before closing encoder
  preloader_->Cancel();
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
  preloader_->SetDelayHook(std::move(hook));
}

}  // namespace retrovue::blockplan
