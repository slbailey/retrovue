// Repository: Retrovue-playout
// Component: Continuous Output Execution Engine
// Purpose: Continuous output loop with A/B BlockSource swap (P3.0 + P3.1a + P3.1b)
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/ContinuousOutputExecutionEngine.hpp"

#include <chrono>
#include <cstring>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/BlockSource.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "retrovue/blockplan/PlaybackTraceTypes.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/blockplan/SourcePreloader.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

#if defined(__linux__) || defined(__APPLE__)
#include <unistd.h>
#endif

namespace retrovue::blockplan {

ContinuousOutputExecutionEngine::ContinuousOutputExecutionEngine(
    BlockPlanSessionContext* ctx,
    Callbacks callbacks)
    : ctx_(ctx),
      callbacks_(std::move(callbacks)),
      active_source_(std::make_unique<BlockSource>(ctx->width, ctx->height,
                                                    ctx->fps)),
      preloader_(std::make_unique<SourcePreloader>()) {
  metrics_.channel_id = ctx->channel_id;
}

ContinuousOutputExecutionEngine::~ContinuousOutputExecutionEngine() {
  Stop();
}

void ContinuousOutputExecutionEngine::Start() {
  if (started_) return;
  started_ = true;
  ctx_->stop_requested.store(false, std::memory_order_release);
  thread_ = std::thread(&ContinuousOutputExecutionEngine::Run, this);
}

void ContinuousOutputExecutionEngine::Stop() {
  if (!started_) return;
  ctx_->stop_requested.store(true, std::memory_order_release);
  ctx_->queue_cv.notify_all();
  preloader_->Cancel();
  if (thread_.joinable()) {
    thread_.join();
  }
  started_ = false;
}

ContinuousOutputMetrics ContinuousOutputExecutionEngine::SnapshotMetrics() const {
  std::lock_guard<std::mutex> lock(metrics_mutex_);
  return metrics_;
}

std::string ContinuousOutputExecutionEngine::GenerateMetricsText() const {
  std::lock_guard<std::mutex> lock(metrics_mutex_);
  return metrics_.GeneratePrometheusText();
}

// =============================================================================
// EmitPadFrame — black video + silent audio at the given PTS
// =============================================================================

void ContinuousOutputExecutionEngine::EmitPadFrame(
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
// TryLoadActiveBlock — load active_source_ from preloaded next or queue.
// Called ONLY when active_source_ is EMPTY — outside the timed tick window.
// =============================================================================

void ContinuousOutputExecutionEngine::TryLoadActiveBlock() {
  // P3.1b: first try to adopt a preloaded next_source_
  if (next_source_ &&
      next_source_->GetState() == BlockSource::State::kReady) {
    active_source_ = std::move(next_source_);
    source_ticks_ = 0;
    return;
  }

  // Check if preloader has finished
  auto preloaded = TryTakePreloadedNext();
  if (preloaded && preloaded->GetState() == BlockSource::State::kReady) {
    active_source_ = std::move(preloaded);
    source_ticks_ = 0;
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
  active_source_->AssignBlock(block);
  source_ticks_ = 0;
}

// =============================================================================
// TryKickoffNextPreload — start preloading the next block if conditions met.
// Called outside the tick window only.
// =============================================================================

void ContinuousOutputExecutionEngine::TryKickoffNextPreload() {
  // Only preload when: active is READY, next is empty, no preload running
  if (active_source_->GetState() != BlockSource::State::kReady) return;
  if (next_source_) return;  // Already have a preloaded next
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
// TryTakePreloadedNext — non-blocking check for preloader result.
// =============================================================================

std::unique_ptr<BlockSource> ContinuousOutputExecutionEngine::TryTakePreloadedNext() {
  auto src = preloader_->TakeSource();
  if (src) {
    std::lock_guard<std::mutex> lock(metrics_mutex_);
    metrics_.next_preload_ready_count++;
  }
  return src;
}

// =============================================================================
// Run() — P3.0 + P3.1a + P3.1b main loop (pad + A/B BlockSource swap)
// =============================================================================

void ContinuousOutputExecutionEngine::Run() {
  std::cout << "[ContinuousOutput] Starting execution thread for channel "
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
  // 2. SESSION-LONG ENCODER (same pattern as SerialBlockExecutionEngine)
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

  // Session write context for the write callback
  struct SessionWriteContext {
    int fd;
    int64_t bytes_written;
  };
  SessionWriteContext write_ctx{ctx_->fd, 0};

  auto write_callback = [](void* opaque, uint8_t* buf, int buf_size) -> int {
    auto* wctx = static_cast<SessionWriteContext*>(opaque);
#if defined(__linux__) || defined(__APPLE__)
    ssize_t written = write(wctx->fd, buf, static_cast<size_t>(buf_size));
    if (written > 0) {
      wctx->bytes_written += written;
    }
    return static_cast<int>(written);
#else
    (void)buf;
    return buf_size;
#endif
  };

  auto encoder_open_start = std::chrono::steady_clock::now();
  if (!session_encoder->open(enc_config, &write_ctx, write_callback)) {
    std::cerr << "[ContinuousOutput] Failed to open session encoder"
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

  std::cout << "[ContinuousOutput] Session encoder opened: "
            << ctx_->width << "x" << ctx_->height << " @ " << ctx_->fps
            << "fps, open_ms=" << encoder_open_ms << std::endl;

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
  OutputClock clock(ctx_->fps);
  clock.Start();

  // ========================================================================
  // 4. AUDIO PTS TRACKING
  // ========================================================================
  static constexpr int kAudioSamplesPerFrame = 1024;
  int64_t audio_samples_emitted = 0;

  // ========================================================================
  // 5. TRY LOADING FIRST BLOCK (before main loop)
  // ========================================================================
  TryLoadActiveBlock();

  // P3.1b: Kick off preload for next block immediately
  TryKickoffNextPreload();

  // ========================================================================
  // 6. MAIN LOOP
  // ========================================================================
  int64_t session_frame_index = 0;
  std::chrono::steady_clock::time_point prev_frame_time{};
  bool have_prev_frame_time = false;
  // Track whether we're past the active block's fence and waiting for next
  bool past_fence = false;

  // P3.3: Per-block playback accumulator
  BlockAccumulator block_acc;
  if (active_source_->GetState() == BlockSource::State::kReady) {
    block_acc.Reset(active_source_->GetBlock().block_id);
  }
  // P3.3: Seam transition tracking
  std::string prev_completed_block_id;
  int64_t fence_session_frame = -1;
  int64_t fence_pad_counter = 0;  // pad frames since last fence

  while (!ctx_->stop_requested.load(std::memory_order_acquire)) {
    // Wait until absolute deadline for this frame
    auto wake_time = clock.WaitForFrame(session_frame_index);

    if (ctx_->stop_requested.load(std::memory_order_acquire)) break;

    // Compute PTS (unchanged from P3.0)
    int64_t video_pts_90k = clock.FrameIndexToPts90k(session_frame_index);
    int64_t audio_pts_90k =
        (audio_samples_emitted * 90000) / buffer::kHouseAudioSampleRate;

    bool is_pad = true;
    std::optional<BlockSource::FrameData> frame_data;

    // TRY REAL FRAME from active source (engine owns the tick)
    if (active_source_->GetState() == BlockSource::State::kReady) {
      source_ticks_++;  // Engine owns time
      frame_data = active_source_->TryGetFrame();  // BlockSource reacts
      if (frame_data) {
        session_encoder->encodeFrame(frame_data->video, video_pts_90k);
        for (auto& af : frame_data->audio) {
          session_encoder->encodeAudioFrame(af, audio_pts_90k, false);
          audio_samples_emitted += af.nb_samples;
          audio_pts_90k =
              (audio_samples_emitted * 90000) / buffer::kHouseAudioSampleRate;
        }
        is_pad = false;
      }
    }

    if (is_pad) {
      EmitPadFrame(session_encoder.get(), video_pts_90k, audio_pts_90k);
      audio_samples_emitted += kAudioSamplesPerFrame;
      if (past_fence) {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.fence_pad_frames_total++;
      }
    }

    // P3.2: Emit frame fingerprint for seam verification
    if (callbacks_.on_frame_emitted) {
      FrameFingerprint fp;
      fp.session_frame_index = session_frame_index;
      fp.is_pad = is_pad;
      if (active_source_->GetState() == BlockSource::State::kReady) {
        fp.active_block_id = active_source_->GetBlock().block_id;
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
    if (active_source_->GetState() == BlockSource::State::kReady &&
        !block_acc.block_id.empty()) {
      std::string uri;
      int64_t ct_ms = 0;
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

    // ==================================================================
    // FENCE CHECK (engine-owned, not BlockSource)
    // P3.1b: At fence, try to swap to preloaded next_source_.
    // ==================================================================
    if (active_source_->GetState() == BlockSource::State::kReady &&
        source_ticks_ >= active_source_->FramesPerBlock()) {

      // P3.3: Finalize and emit playback summary before completion callback
      if (!block_acc.block_id.empty()) {
        auto summary = block_acc.Finalize();
        std::cout << FormatPlaybackSummary(summary) << std::endl;
        if (callbacks_.on_block_summary) {
          callbacks_.on_block_summary(summary);
        }
      }

      // P3.3: Record completed block for seam tracking
      prev_completed_block_id = active_source_->GetBlock().block_id;
      fence_session_frame = session_frame_index;
      fence_pad_counter = 0;

      // Fire completion callback for the active block
      if (callbacks_.on_block_completed) {
        callbacks_.on_block_completed(active_source_->GetBlock(),
                                      session_frame_index);
      }
      {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.total_blocks_executed++;
      }
      ctx_->blocks_executed++;

      // P3.1b: Try to swap — check preloaded next_source_ first
      bool swapped = false;

      // 1) Already have a next_source_ ready?
      if (next_source_ &&
          next_source_->GetState() == BlockSource::State::kReady) {
        active_source_ = std::move(next_source_);
        source_ticks_ = 0;
        swapped = true;
      }

      // 2) Preloader has one ready?
      if (!swapped) {
        auto preloaded = TryTakePreloadedNext();
        if (preloaded &&
            preloaded->GetState() == BlockSource::State::kReady) {
          active_source_ = std::move(preloaded);
          source_ticks_ = 0;
          swapped = true;
        }
      }

      if (swapped) {
        {
          std::lock_guard<std::mutex> lock(metrics_mutex_);
          metrics_.source_swap_count++;
        }
        past_fence = false;

        // P3.3: Emit seam transition log (seamless swap)
        if (!prev_completed_block_id.empty()) {
          SeamTransitionLog seam;
          seam.from_block_id = prev_completed_block_id;
          seam.to_block_id = active_source_->GetBlock().block_id;
          seam.fence_frame = fence_session_frame;
          seam.pad_frames_at_fence = 0;
          seam.seamless = true;
          std::cout << FormatSeamTransition(seam) << std::endl;
          if (callbacks_.on_seam_transition) {
            callbacks_.on_seam_transition(seam);
          }
        }

        // P3.3: Reset accumulator for new block
        block_acc.Reset(active_source_->GetBlock().block_id);

        // Immediately kick off preload for the following block
        TryKickoffNextPreload();
      } else {
        // No next available — reset active and enter pad mode
        active_source_->Reset();
        source_ticks_ = 0;
        past_fence = true;
      }
    }

    // LOAD NEXT from queue if source is empty (fallback path)
    if (active_source_->GetState() == BlockSource::State::kEmpty) {
      TryLoadActiveBlock();  // Outside timed tick window

      if (active_source_->GetState() == BlockSource::State::kReady) {
        // P3.3: Emit seam transition log (padded transition)
        if (!prev_completed_block_id.empty()) {
          SeamTransitionLog seam;
          seam.from_block_id = prev_completed_block_id;
          seam.to_block_id = active_source_->GetBlock().block_id;
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
        block_acc.Reset(active_source_->GetBlock().block_id);
        fence_pad_counter = 0;

        past_fence = false;
        // Kick off preload for the next one
        TryKickoffNextPreload();
      }
    }

    // P3.1b: Opportunistically check preloader result and stash it
    if (!next_source_ && preloader_->IsReady()) {
      next_source_ = TryTakePreloadedNext();
    }

    // P3.1b: Try to start preloading if conditions met
    TryKickoffNextPreload();

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
  next_source_.reset();
  active_source_->Reset();
  source_ticks_ = 0;

  if (session_encoder) {
    session_encoder->close();
    std::cout << "[ContinuousOutput] Session encoder closed: "
              << write_ctx.bytes_written << " bytes written" << std::endl;
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

  std::cout << "[ContinuousOutput] Thread exiting: frames_emitted="
            << session_frame_index
            << ", reason=" << termination_reason << std::endl;

  if (callbacks_.on_session_ended && !session_ended_fired_) {
    session_ended_fired_ = true;
    callbacks_.on_session_ended(termination_reason);
  }
}

void ContinuousOutputExecutionEngine::SetPreloaderDelayHook(
    std::function<void()> hook) {
  preloader_->SetDelayHook(std::move(hook));
}

}  // namespace retrovue::blockplan
