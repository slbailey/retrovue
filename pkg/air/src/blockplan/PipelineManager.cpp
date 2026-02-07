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

#if defined(__linux__) || defined(__APPLE__)
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
    live_ticks_ = 0;
    return;
  }

  // Check if preloader has finished
  auto preloaded = TryTakePreviewProducer();
  if (preloaded && AsTickProducer(preloaded.get())->GetState() == ITickProducer::State::kReady) {
    live_ = std::move(preloaded);
    live_ticks_ = 0;
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
  live_ticks_ = 0;
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
  TryLoadLiveProducer();

  // P3.1b: Kick off preload for next block immediately
  TryKickoffPreviewPreload();

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
  std::chrono::steady_clock::time_point prev_frame_time{};
  bool have_prev_frame_time = false;
  // Track whether we're past the live block's fence and waiting for next
  bool past_fence = false;

  // P3.3: Per-block playback accumulator
  BlockAccumulator block_acc;
  if (live_tp()->GetState() == ITickProducer::State::kReady) {
    block_acc.Reset(live_tp()->GetBlock().block_id);
    emit_block_start("queue");
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
    std::optional<FrameData> frame_data;

    // TRY REAL FRAME from live producer (engine owns the tick)
    if (live_tp()->GetState() == ITickProducer::State::kReady) {
      live_ticks_++;  // Engine owns time
      frame_data = live_tp()->TryGetFrame();  // Producer reacts
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
    if (live_tp()->GetState() == ITickProducer::State::kReady &&
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
    // FENCE CHECK (engine-owned, not Producer)
    // P3.1b: At fence, try to swap to preloaded preview_.
    // ==================================================================
    if (live_tp()->GetState() == ITickProducer::State::kReady &&
        live_ticks_ >= live_tp()->FramesPerBlock()) {

      // P3.3: Finalize and emit playback summary + proof before completion callback
      if (!block_acc.block_id.empty()) {
        auto summary = block_acc.Finalize();
        std::cout << FormatPlaybackSummary(summary) << std::endl;
        if (callbacks_.on_block_summary) {
          callbacks_.on_block_summary(summary);
        }

        // P3.3b: Build and emit playback proof (wanted vs showed)
        auto proof = BuildPlaybackProof(
            live_tp()->GetBlock(), summary, clock.FrameDurationMs());
        std::cout << FormatPlaybackProof(proof) << std::endl;
        if (callbacks_.on_playback_proof) {
          callbacks_.on_playback_proof(proof);
        }

        // Audit: BLOCK_COMPLETE
        {
          const auto& blk = live_tp()->GetBlock();
          int64_t base_offset = !blk.segments.empty()
              ? blk.segments[0].asset_start_offset_ms : 0;
          std::cout << "[PipelineManager] BLOCK_COMPLETE"
                    << " block=" << summary.block_id
                    << " frames=" << live_tp()->FramesPerBlock()
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

      // P3.3: Record completed block for seam tracking
      prev_completed_block_id = live_tp()->GetBlock().block_id;
      fence_session_frame = session_frame_index;
      fence_pad_counter = 0;

      // Fire completion callback for the live block
      if (callbacks_.on_block_completed) {
        callbacks_.on_block_completed(live_tp()->GetBlock(),
                                      session_frame_index);
      }
      {
        std::lock_guard<std::mutex> lock(metrics_mutex_);
        metrics_.total_blocks_executed++;
      }
      ctx_->blocks_executed++;

      // P3.1b: Try to swap — check preloaded preview_ first
      bool swapped = false;

      // 1) Already have a preview_ ready?
      if (preview_ &&
          AsTickProducer(preview_.get())->GetState() == ITickProducer::State::kReady) {
        live_ = std::move(preview_);
        live_ticks_ = 0;
        swapped = true;
      }

      // 2) Preloader has one ready?
      if (!swapped) {
        auto preloaded = TryTakePreviewProducer();
        if (preloaded &&
            AsTickProducer(preloaded.get())->GetState() == ITickProducer::State::kReady) {
          live_ = std::move(preloaded);
          live_ticks_ = 0;
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

        // Immediately kick off preload for the following block
        TryKickoffPreviewPreload();
      } else {
        // No next available — reset live and enter pad mode
        live_tp()->Reset();
        live_ticks_ = 0;
        past_fence = true;
      }
    }

    // LOAD NEXT from queue if source is empty (fallback path)
    if (live_tp()->GetState() == ITickProducer::State::kEmpty) {
      bool had_preview = (preview_ != nullptr);
      TryLoadLiveProducer();  // Outside timed tick window

      if (live_tp()->GetState() == ITickProducer::State::kReady) {
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
  live_ticks_ = 0;

  if (session_encoder) {
    session_encoder->close();
    std::cout << "[PipelineManager] Session encoder closed: "
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
