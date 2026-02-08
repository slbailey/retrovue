// Repository: Retrovue-playout
// Component: Pipeline Manager
// Purpose: Continuous output loop with A/B Producer swap (P3.0 + P3.1a + P3.1b)
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/PipelineManager.hpp"

#include <chrono>
#include <cstring>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "retrovue/blockplan/PlaybackTraceTypes.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/blockplan/ProducerPreloader.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/output/SocketSink.h"

extern "C" {
#include <libavutil/error.h>
}

#if defined(__linux__) || defined(__APPLE__)
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#endif

namespace retrovue::blockplan {

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

  preloader_->StartPreload(block, ctx_->width, ctx_->height, ctx_->fps);
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
// Run() — P3.0 + P3.1a + P3.1b main loop (pad + A/B Producer swap)
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

  // Buffer capacity: configurable via kSinkBufferCapacity.
  // Default ~128 KB ≈ 500ms at 2 Mbps.  Small enough to detect slow
  // consumers quickly, large enough to absorb transient kernel pressure.
  // TODO: promote to BlockPlanSessionContext for runtime configurability.
  static constexpr size_t kSinkBufferCapacity = 128 * 1024;
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

  // Write callback context: enqueue into SocketSink (non-blocking).
  struct SessionWriteContext {
    output::SocketSink* sink;
    int64_t bytes_written;
  };
  SessionWriteContext write_ctx{socket_sink.get(), 0};

  // AVIO write callback:
  // - While attached: enqueue bytes, return buf_size on success.
  // - After detach/overflow: return AVERROR(EPIPE) so FFmpeg treats it as a
  //   broken-pipe I/O error and unwinds cleanly (av_write_frame propagates it).
  //   Do NOT return buf_size forever after detach — that lies to AVIO and
  //   keeps the encoder producing packets nobody will ever receive.
  auto write_callback = [](void* opaque, uint8_t* buf, int buf_size) -> int {
    auto* wctx = static_cast<SessionWriteContext*>(opaque);
    if (wctx->sink->IsDetached()) {
      return AVERROR(EPIPE);  // Broken pipe — FFmpeg stops writing
    }
    if (wctx->sink->TryConsumeBytes(
            reinterpret_cast<const uint8_t*>(buf),
            static_cast<size_t>(buf_size))) {
      wctx->bytes_written += buf_size;
      return buf_size;
    }
    // Enqueue failed (overflow triggered detach) — fail the write
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
  // 4. AUDIO PTS TRACKING
  // ========================================================================
  static constexpr int kAudioSamplesPerFrame = 1024;
  int64_t audio_samples_emitted = 0;

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
    InitCadence(live_tp());
  }
  // P3.3: Seam transition tracking
  std::string prev_completed_block_id;
  int64_t fence_session_frame = -1;
  int64_t fence_pad_counter = 0;  // pad frames since last fence

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
    // PROACTIVE FENCE CHECK — INV-BLOCK-WALLFENCE-004:
    // Fires BEFORE frame emission when session_frame_index reaches the
    // fence tick.  The fence tick belongs to the NEW block.
    // Trigger: session_frame_index >= block_fence_frame_ (rational).
    // remaining_block_frames_ == 0 is a verification, not the trigger.
    // ==================================================================
    if (session_frame_index >= block_fence_frame_ &&
        live_tp()->GetState() == ITickProducer::State::kReady) {

      // Snapshot outgoing block before A/B swap.
      const FedBlock outgoing_block = live_tp()->GetBlock();
      int64_t ct_at_fence_ms = -1;

      // P3.3: Finalize and emit playback summary + proof before swap
      if (!block_acc.block_id.empty()) {
        auto summary = block_acc.Finalize();
        ct_at_fence_ms = summary.last_block_ct_ms;
        std::cout << FormatPlaybackSummary(summary) << std::endl;
        if (callbacks_.on_block_summary) {
          callbacks_.on_block_summary(summary);
        }

        // P3.3b: Build and emit playback proof (wanted vs showed)
        auto proof = BuildPlaybackProof(
            outgoing_block, summary, clock.FrameDurationMs());
        std::cout << FormatPlaybackProof(proof) << std::endl;
        if (callbacks_.on_playback_proof) {
          callbacks_.on_playback_proof(proof);
        }

        // Audit: BLOCK_COMPLETE
        {
          int64_t base_offset = !outgoing_block.segments.empty()
              ? outgoing_block.segments[0].asset_start_offset_ms : 0;
          std::cout << "[PipelineManager] BLOCK_COMPLETE"
                    << " block=" << summary.block_id
                    << " fence_frame=" << block_fence_frame_
                    << " emitted=" << summary.frames_emitted
                    << " pad=" << summary.pad_frames
                    << " asset=" << (!summary.asset_uris.empty()
                        ? summary.asset_uris[0] : "pad");
          if (summary.first_block_ct_ms >= 0) {
            std::cout << " range_ms="
                      << (base_offset + summary.first_block_ct_ms)
                      << "->"
                      << (base_offset + summary.last_block_ct_ms);
          }
          std::cout << std::endl;
        }
      }

      // INV-BLOCK-WALLFENCE-001: Diagnostic — wall-clock fence timing.
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
                  << " fence_frame=" << block_fence_frame_
                  << " session_frame=" << session_frame_index
                  << " remaining_budget=" << remaining_block_frames_
                  << std::endl;
      }

      // P3.3: Record completed block for seam tracking
      prev_completed_block_id = outgoing_block.block_id;
      fence_session_frame = session_frame_index;
      fence_pad_counter = 0;

      // INV-BLOCK-WALLFENCE-004: Execute A/B swap BEFORE frame emission.
      bool swapped = false;

      // 1) Already have a preview_ ready?
      if (preview_ &&
          AsTickProducer(preview_.get())->GetState() == ITickProducer::State::kReady) {
        live_ = std::move(preview_);
        swapped = true;
      }

      // 2) Preloader has one ready?
      if (!swapped) {
        auto preloaded = TryTakePreviewProducer();
        if (preloaded &&
            AsTickProducer(preloaded.get())->GetState() == ITickProducer::State::kReady) {
          live_ = std::move(preloaded);
          swapped = true;
        }
      }

      // INV-BLOCK-WALLFENCE-005: BlockCompleted fires AFTER swap.
      if (callbacks_.on_block_completed) {
        callbacks_.on_block_completed(outgoing_block, session_frame_index);
      }
      {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.total_blocks_executed++;
      }
      ctx_->blocks_executed++;

      if (swapped) {
        // Compute fence for the new block.
        block_fence_frame_ = compute_fence_frame(live_tp()->GetBlock());
        // INV-FRAME-BUDGET-002: Budget derived from fence, not FramesPerBlock().
        remaining_block_frames_ = block_fence_frame_ - session_frame_index;
        if (remaining_block_frames_ < 0) remaining_block_frames_ = 0;
        {
          std::lock_guard<std::mutex> lock(metrics_mutex_);
          metrics_.source_swap_count++;
        }
        past_fence = false;

        // P3.3: Emit seam transition log (seamless swap)
        if (!prev_completed_block_id.empty()) {
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

        // P3.3: Reset accumulator for new block
        block_acc.Reset(live_tp()->GetBlock().block_id);
        emit_block_start("preview");
        InitCadence(live_tp());

        // Immediately kick off preload for the following block
        TryKickoffPreviewPreload();
      } else {
        // No next available — reset live and enter pad mode
        live_tp()->Reset();
        block_fence_frame_ = INT64_MAX;
        past_fence = true;
        ResetCadence();
      }
    }

    bool is_pad = true;
    std::optional<FrameData> frame_data;
    bool did_decode = false;
    int audio_frames_this_tick = 0;

    // ================================================================
    // Cadence gate: decide whether to decode or repeat this tick.
    // ratio = input_fps / output_fps (e.g. 0.7992 for 23.976→30).
    // decode_budget accumulates ratio each tick; decode when >= 1.0.
    // This produces a deterministic 4:1 dup pattern for 23.976→30.
    // ================================================================
    bool should_decode = true;
    if (cadence_active_) {
      decode_budget_ += cadence_ratio_;
      if (decode_budget_ >= 1.0) {
        decode_budget_ -= 1.0;
        should_decode = true;
      } else {
        should_decode = false;
      }
    }

    // INV-TICK-DEADLINE-DISCIPLINE-001 R2: When late, MUST NOT block on decode.
    // Force repeat/freeze path — TryGetFrame() is never called when late.
    if (tick_is_late) {
      should_decode = false;
    }

    // INV-BLOCK-PRIME-002 + R2: Primed frames are pre-decoded and non-blocking
    // to retrieve. They qualify as "already available without blocking" and
    // may be selected even on late ticks.
    if (!should_decode &&
        live_tp()->GetState() == ITickProducer::State::kReady &&
        live_tp()->HasPrimedFrame()) {
      should_decode = true;
    }

    // TRY REAL FRAME from live producer (engine owns the tick)
    if (live_tp()->GetState() == ITickProducer::State::kReady) {
      if (should_decode) {
        frame_data = live_tp()->TryGetFrame();  // Producer reacts
        if (frame_data) {
          // Save for potential repeat on next tick
          last_decoded_video_ = frame_data->video;
          have_last_decoded_video_ = true;

          session_encoder->encodeFrame(frame_data->video, video_pts_90k);
          for (auto& af : frame_data->audio) {
            session_encoder->encodeAudioFrame(af, audio_pts_90k, false);
            audio_samples_emitted += af.nb_samples;
            audio_pts_90k =
                (audio_samples_emitted * 90000) / buffer::kHouseAudioSampleRate;
            audio_frames_this_tick++;
            // Save last audio frame for hold-last on late-tick repeats
            last_decoded_audio_ = af;
            have_last_decoded_audio_ = true;
          }
          is_pad = false;
          did_decode = true;
        } else if (have_last_decoded_video_) {
          // Content exhausted but block not finished — hold last frame
          // instead of emitting pad (black). This prevents flicker at
          // end-of-asset when rounding causes content to run out a few
          // hundred ticks before the fence fires.
          session_encoder->encodeFrame(last_decoded_video_, video_pts_90k);
          is_pad = false;
        }
      } else if (have_last_decoded_video_) {
        // Repeat tick: re-encode last video frame with new output PTS.
        session_encoder->encodeFrame(last_decoded_video_, video_pts_90k);
        is_pad = false;
        // did_decode stays false

        // Late ticks: emit tick-aligned audio so the audio timeline advances
        // exactly one tick.  Without this, video PTS advances but audio PTS
        // freezes, causing progressive A/V desync.
        //
        // Hold-last: re-emit the last decoded audio frame (masked to current
        // PTS) to avoid an audible silence blip.  Falls back to silence only
        // if no audio has been decoded yet (session-start edge case).
        //
        // Cadence repeats (should_decode=false due to input_fps < output_fps)
        // intentionally skip audio — the content stream has no extra audio
        // at the higher output rate.  Only late ticks need the correction.
        if (tick_is_late) {
          if (have_last_decoded_audio_) {
            session_encoder->encodeAudioFrame(last_decoded_audio_,
                                              audio_pts_90k, false);
            audio_samples_emitted += last_decoded_audio_.nb_samples;
          } else {
            // No audio decoded yet — silence is the only option.
            buffer::AudioFrame silence;
            silence.sample_rate = buffer::kHouseAudioSampleRate;
            silence.channels = buffer::kHouseAudioChannels;
            silence.nb_samples = kAudioSamplesPerFrame;
            silence.data.resize(
                static_cast<size_t>(kAudioSamplesPerFrame *
                                    buffer::kHouseAudioChannels) *
                    sizeof(int16_t),
                0);
            session_encoder->encodeAudioFrame(silence, audio_pts_90k,
                                              /*is_silence_pad=*/true);
            audio_samples_emitted += kAudioSamplesPerFrame;
          }
          audio_frames_this_tick = 1;
        }
      }
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

    // Per-tick cadence diagnostic (metric 2: decoded, decode_budget, audio_frames)
    // Rate-limited: log every 300 frames (~10 seconds at 30fps) when cadence active
    if (cadence_active_ && session_frame_index % 300 == 0) {
      std::cout << "[PipelineManager] CADENCE_TICK: frame=" << session_frame_index
                << " decoded=" << (did_decode ? 1 : 0)
                << " decode_budget=" << decode_budget_
                << " audio_frames=" << audio_frames_this_tick
                << " video_pts_90k=" << video_pts_90k
                << " audio_pts_90k=" << audio_pts_90k
                << std::endl;
    }

    // Log SocketSink buffer state periodically (every ~10s = 300 ticks at 30fps)
    if (session_frame_index % 300 == 0 && socket_sink) {
      std::cout << "[PipelineManager] sink_buffer="
                << socket_sink->GetCurrentBufferSize()
                << "/" << socket_sink->GetBufferCapacity()
                << " delivered=" << socket_sink->GetBytesDelivered()
                << " errors=" << socket_sink->GetWriteErrors()
                << std::endl;
    }

    // P3.2: Emit frame fingerprint for seam verification
    if (callbacks_.on_frame_emitted) {
      FrameFingerprint fp;
      fp.session_frame_index = session_frame_index;
      fp.is_pad = is_pad;
      if (live_tp()->GetState() == ITickProducer::State::kReady) {
        fp.active_block_id = live_tp()->GetBlock().block_id;
      }
      if (!is_pad && frame_data) {
        fp.asset_uri = frame_data->asset_uri;
        fp.asset_offset_ms = frame_data->block_ct_ms;
        const auto& vid = frame_data->video;
        if (!vid.data.empty()) {
          size_t y_size = static_cast<size_t>(vid.width * vid.height);
          fp.y_crc32 = CRC32YPlane(vid.data.data(),
                                    std::min(y_size, vid.data.size()));
        }
      }
      callbacks_.on_frame_emitted(fp);
    }

    // P3.3: Accumulate frame into current block summary
    // ct_ms = -1 sentinel when no frame_data (cadence repeat or hold-last-frame).
    // Accumulator only updates CT tracking when ct_ms >= 0.
    if (live_tp()->GetState() == ITickProducer::State::kReady &&
        !block_acc.block_id.empty()) {
      std::string uri;
      int64_t ct_ms = -1;
      if (!is_pad && frame_data) {
        uri = frame_data->asset_uri;
        ct_ms = frame_data->block_ct_ms;
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
    // INV-TICK-DEADLINE-DISCIPLINE-001 R2: Skip when late — TryLoadLiveProducer
    // may block on synchronous probe+open+seek.
    if (!tick_is_late &&
        live_tp()->GetState() == ITickProducer::State::kEmpty) {
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
        InitCadence(live_tp());
        fence_pad_counter = 0;

        past_fence = false;
        // Kick off preload for the next one
        TryKickoffPreviewPreload();
      }
    }

    // P3.1b: Opportunistically check preloader result and stash it
    if (!preview_ && preloader_->IsReady()) {
      preview_ = TryTakePreviewProducer();
    }

    // P3.1b: Try to start preloading if conditions met
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
  }

  std::cout << "[PipelineManager] Thread exiting: frames_emitted="
            << session_frame_index
            << ", reason=" << termination_reason << std::endl;

  if (callbacks_.on_session_ended && !session_ended_fired_) {
    session_ended_fired_ = true;
    callbacks_.on_session_ended(termination_reason);
  }
}

// =============================================================================
// InitCadence — detect input/output FPS mismatch and activate frame repeat
// =============================================================================

void PipelineManager::InitCadence(ITickProducer* tp) {
  double input_fps = tp->GetInputFPS();
  double output_fps = ctx_->fps;

  // Log once per asset open (metric 1: input_fps, output_fps)
  std::cout << "[PipelineManager] FPS_CADENCE: input_fps=" << input_fps
            << " output_fps=" << output_fps;

  // Activate cadence only when input is meaningfully slower than output.
  // Tolerance: 2% — avoids activation for 29.97 vs 30.
  if (input_fps > 0.0 && input_fps < output_fps * 0.98) {
    cadence_active_ = true;
    cadence_ratio_ = input_fps / output_fps;
    decode_budget_ = 1.0;  // Guarantees first tick decodes
    have_last_decoded_video_ = false;
    have_last_decoded_audio_ = false;
    std::cout << " cadence=ACTIVE ratio=" << cadence_ratio_ << std::endl;
  } else {
    cadence_active_ = false;
    cadence_ratio_ = 0.0;
    decode_budget_ = 0.0;
    have_last_decoded_video_ = false;
    have_last_decoded_audio_ = false;
    std::cout << " cadence=OFF" << std::endl;
  }
}

void PipelineManager::ResetCadence() {
  cadence_active_ = false;
  cadence_ratio_ = 0.0;
  decode_budget_ = 0.0;
  have_last_decoded_video_ = false;
  last_decoded_video_ = buffer::Frame{};
  have_last_decoded_audio_ = false;
  last_decoded_audio_ = buffer::AudioFrame{};
}

void PipelineManager::SetPreloaderDelayHook(
    std::function<void()> hook) {
  preloader_->SetDelayHook(std::move(hook));
}

}  // namespace retrovue::blockplan
