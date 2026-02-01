// Repository: Retrovue-playout
// Component: Program Output
// Purpose: Consumes decoded frames and delivers program signal to OutputBus or display.
// Copyright (c) 2025 RetroVue

#include "retrovue/renderer/ProgramOutput.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <limits>
#include <thread>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

#ifdef RETROVUE_SDL2_AVAILABLE
extern "C" {
#include <SDL2/SDL.h>
}
#endif

#include "retrovue/output/OutputBus.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/timing/MasterClock.h"

namespace retrovue::renderer {

namespace {
constexpr double kWaitFudgeSeconds = 0.001;                // wake a millisecond early
constexpr double kDropThresholdSeconds = -0.008;           // drop when we are 8 ms late (MC-003)
constexpr int kMinDepthForDrop = 5;                        // keep buffer from starving
constexpr int64_t kSpinThresholdUs = 200;                  // busy wait for last 0.2 ms
constexpr int64_t kSpinSleepUs = 100;                      // fine-grained wait window
constexpr int64_t kEmptyBufferBackoffUs = 5'000;           // MC-004: allow producer to refill
constexpr int64_t kErrorBackoffUs = 10'000;                // MC-004 recovery assistance

inline void WaitUntilUtc(const std::shared_ptr<timing::MasterClock>& clock,
                         int64_t target_utc_us,
                         const std::atomic<bool>* stop_flag = nullptr) {
  if (!clock || target_utc_us <= 0) {
    return;
  }

  while (true) {
    if (stop_flag && stop_flag->load(std::memory_order_acquire)) {
      break;
    }

    const int64_t now = clock->now_utc_us();
    const int64_t remaining = target_utc_us - now;
    if (remaining <= 0) {
      break;
    }

    const int64_t sleep_us =
        (remaining > 2'000) ? remaining - 1'000
                            : std::max<int64_t>(remaining / 2, 200);
    std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
  }
}

inline void WaitForMicros(const std::shared_ptr<timing::MasterClock>& clock,
                          int64_t duration_us,
                          const std::atomic<bool>* stop_flag = nullptr) {
  if (duration_us <= 0) {
    return;
  }
  if (clock) {
    WaitUntilUtc(clock, clock->now_utc_us() + duration_us, stop_flag);
    return;
  }
  const int64_t chunk_us = 1'000;
  int64_t remaining_us = duration_us;
  while (remaining_us > 0) {
    if (stop_flag && stop_flag->load(std::memory_order_acquire)) {
      break;
    }
    const int64_t sleep_us = std::min<int64_t>(remaining_us, chunk_us);
    std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
    remaining_us -= sleep_us;
  }
}

inline int64_t WaitFudgeUs() {
  return static_cast<int64_t>(kWaitFudgeSeconds * 1'000'000.0);
}
}  // namespace

ProgramOutput::ProgramOutput(const RenderConfig& config,
                             buffer::FrameRingBuffer& input_buffer,
                             const std::shared_ptr<timing::MasterClock>& clock,
                             const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                             int32_t channel_id)
    : config_(config),
      input_buffer_(&input_buffer),  // Store as pointer for hot-switch support
      clock_(clock),
      metrics_(metrics),
      channel_id_(channel_id),
      running_(false),
      stop_requested_(false),
      last_pts_(0),
      last_frame_time_utc_(0),
      fallback_last_frame_time_(std::chrono::steady_clock::now()) {}

ProgramOutput::~ProgramOutput() { Stop(); }

std::unique_ptr<ProgramOutput> ProgramOutput::Create(
    const RenderConfig& config, buffer::FrameRingBuffer& input_buffer,
    const std::shared_ptr<timing::MasterClock>& clock,
    const std::shared_ptr<telemetry::MetricsExporter>& metrics,
    int32_t channel_id) {
  if (config.mode == RenderMode::PREVIEW) {
#ifdef RETROVUE_SDL2_AVAILABLE
    return std::make_unique<PreviewProgramOutput>(config, input_buffer, clock, metrics,
                                                 channel_id);
#else
    std::cerr << "[ProgramOutput] WARNING: SDL2 not available, using headless mode"
              << std::endl;
    return std::make_unique<HeadlessProgramOutput>(config, input_buffer, clock, metrics,
                                                   channel_id);
#endif
  }

  return std::make_unique<HeadlessProgramOutput>(config, input_buffer, clock, metrics,
                                                  channel_id);
}

bool ProgramOutput::Start() {
  if (running_.load(std::memory_order_acquire)) {
    std::cerr << "[ProgramOutput] Already running" << std::endl;
    return false;
  }

  stop_requested_.store(false, std::memory_order_release);

  // =========================================================================
  // INV-P10.5-AUDIO-FORMAT-LOCK: Lock pad audio format at channel start
  // =========================================================================
  // Pad audio format is locked to canonical values (48000 Hz, 2 channels).
  // This prevents AUDIO_FORMAT_CHANGE after TS header is written.
  // The format is NEVER changed, regardless of producer audio format.
  // =========================================================================
  LockPadAudioFormat();
  std::cout << "[ProgramOutput] INV-P10.5-AUDIO-FORMAT-LOCK: Pad audio locked to "
            << kCanonicalPadSampleRate << "Hz/" << kCanonicalPadChannels << "ch" << std::endl;

  if (metrics_) {
    telemetry::ChannelMetrics initial_snapshot;
    initial_snapshot.state = telemetry::ChannelState::READY;
    initial_snapshot.buffer_depth_frames = input_buffer_->Size();
    initial_snapshot.frame_gap_seconds = 0.0;
    initial_snapshot.corrections_total = stats_.corrections_total;
    std::cout << "[ProgramOutput] Registering channel " << channel_id_
              << " with MetricsExporter" << std::endl;
    metrics_->SubmitChannelMetrics(channel_id_, initial_snapshot);
  }

  render_thread_ = std::make_unique<std::thread>(&ProgramOutput::RenderLoop, this);

  std::cout << "[ProgramOutput] Started" << std::endl;
  return true;
}

void ProgramOutput::Stop() {
  if (!running_.load(std::memory_order_acquire) && !render_thread_) {
    return;
  }

  std::cout << "[ProgramOutput] Stopping..." << std::endl;
  stop_requested_.store(true, std::memory_order_release);

  if (render_thread_ && render_thread_->joinable()) {
    render_thread_->join();
  }

  render_thread_.reset();
  running_.store(false, std::memory_order_release);

  if (metrics_) {
    telemetry::ChannelMetrics final_snapshot;
    if (!metrics_->GetChannelMetrics(channel_id_, final_snapshot)) {
      final_snapshot = telemetry::ChannelMetrics{};
    }
    final_snapshot.buffer_depth_frames = input_buffer_->Size();
    final_snapshot.frame_gap_seconds = stats_.frame_gap_ms / 1000.0;
    final_snapshot.corrections_total = stats_.corrections_total;
    std::cout << "[ProgramOutput] Flushing final metrics snapshot for channel "
              << channel_id_ << std::endl;
    metrics_->SubmitChannelMetrics(channel_id_, final_snapshot);
  }

  std::cout << "[ProgramOutput] Stopped. Total frames rendered: "
            << stats_.frames_rendered << std::endl;
}

void ProgramOutput::SetNoContentSegment(bool value) {
  no_content_segment_ = value;
  if (value) {
    std::cout << "[ProgramOutput] INV-P8-ZERO-FRAME-BOOTSTRAP: No-content segment, "
              << "pad frames allowed immediately" << std::endl;
  }
}

void ProgramOutput::RenderLoop() {
  std::cout << "[ProgramOutput] Output loop started (mode="
            << (config_.mode == RenderMode::HEADLESS ? "HEADLESS" : "PREVIEW")
            << "), RealTimeHoldPolicy ENABLED" << std::endl;

  if (!Initialize()) {
    std::cerr << "[ProgramOutput] Failed to initialize" << std::endl;
    return;
  }

  running_.store(true, std::memory_order_release);
  if (clock_) {
    last_frame_time_utc_ = clock_->now_utc_us();
  } else {
    fallback_last_frame_time_ = std::chrono::steady_clock::now();
  }

  // ===========================================================================
  // INV-PACING-ENFORCEMENT-002: RealTimeHoldPolicy initialization
  // ===========================================================================
  // Initialize pacing state for wall-clock gated emission.
  // Frame period will be updated when we learn it from the first real frame.
  // ===========================================================================
  pacing_last_emission_us_ = 0;
  pacing_frame_period_us_ = pad_frame_duration_us_;  // Default 33333us (30fps)

  while (!stop_requested_.load(std::memory_order_acquire)) {
    // =========================================================================
    // INV-P10-SINK-GATE: Don't consume frames until output sink is attached
    // =========================================================================
    {
      std::lock_guard<std::mutex> bus_lock(output_bus_mutex_);
      std::lock_guard<std::mutex> side_lock(side_sink_mutex_);
      if (!output_bus_ && !side_sink_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        continue;
      }
    }

    // =========================================================================
    // INV-PACING-ENFORCEMENT-002 CLAUSE 1: Wall-clock pacing
    // "emit at most one frame per frame period"
    // "Wall-clock (or MasterClock) is the sole pacing authority"
    // =========================================================================
    int64_t now_wall_us = 0;
    if (clock_) {
      now_wall_us = clock_->now_utc_us();
    } else {
      now_wall_us = std::chrono::duration_cast<std::chrono::microseconds>(
          std::chrono::steady_clock::now().time_since_epoch()).count();
    }

    // Calculate next emission deadline
    int64_t next_deadline_us = 0;
    if (pacing_last_emission_us_ == 0) {
      // First iteration - emit immediately, establish baseline
      next_deadline_us = now_wall_us;
      pacing_last_emission_us_ = now_wall_us;
    } else {
      next_deadline_us = pacing_last_emission_us_ + pacing_frame_period_us_;
    }

    // =========================================================================
    // INV-PACING-ENFORCEMENT-002 CLAUSE 1: Wait until deadline
    // "SHALL NOT emit frames faster than real time"
    // =========================================================================
    if (now_wall_us < next_deadline_us) {
      const int64_t wait_us = next_deadline_us - now_wall_us;
      if (wait_us > 1000) {  // Only sleep if > 1ms
        WaitForMicros(clock_, wait_us - 500, &stop_requested_);  // Wake slightly early
      }
      // Spin-wait for precise timing
      while (!stop_requested_.load(std::memory_order_acquire)) {
        if (clock_) {
          now_wall_us = clock_->now_utc_us();
        } else {
          now_wall_us = std::chrono::duration_cast<std::chrono::microseconds>(
              std::chrono::steady_clock::now().time_since_epoch()).count();
        }
        if (now_wall_us >= next_deadline_us) break;
        std::this_thread::yield();
      }
    }

    if (stop_requested_.load(std::memory_order_acquire)) break;

    // Phase 7: Get current buffer pointer under lock to support hot-switching.
    buffer::FrameRingBuffer* current_buffer;
    {
      std::lock_guard<std::mutex> lock(input_buffer_mutex_);
      current_buffer = input_buffer_;
    }

    // Record wall time at frame processing start
    int64_t frame_start_utc = now_wall_us;
    std::chrono::steady_clock::time_point frame_start_fallback;
    if (!clock_) {
      frame_start_fallback = std::chrono::steady_clock::now();
    }

    buffer::Frame frame;
    bool using_pad_frame = false;
    bool using_freeze_frame = false;

    // Check buffer depth BEFORE Pop for diagnostic purposes
    size_t video_depth_before_pop = current_buffer->Size();

    // Calculate lateness for telemetry
    const int64_t frame_lateness_us = now_wall_us - next_deadline_us;

    if (!current_buffer->Pop(frame)) {
      // =========================================================================
      // INV-AIR-CONTENT-BEFORE-PAD: Gate pad/freeze until first real frame
      // =========================================================================
      if (!first_real_frame_emitted_ && !no_content_segment_) {
        static uint64_t content_wait_count = 0;
        if (++content_wait_count == 1 || content_wait_count % 100 == 0) {
          std::cout << "[ProgramOutput] INV-AIR-CONTENT-BEFORE-PAD: Waiting for first real content frame "
                    << "(wait_count=" << content_wait_count << ")" << std::endl;
        }
        // Still respect pacing - update emission time even when waiting
        pacing_last_emission_us_ = now_wall_us;
        continue;
      }

      // =========================================================================
      // INV-PACING-ENFORCEMENT-002 CLAUSE 2: Freeze-then-Pad
      // No frame available - apply RealTimeHoldPolicy
      // =========================================================================
      if (!pacing_has_last_frame_) {
        // =====================================================================
        // Edge case: No frame to freeze (startup before first real frame)
        // Must emit pad frame directly
        // =====================================================================
        goto emit_pad_frame;
      }

      if (!pacing_in_freeze_mode_) {
        // =====================================================================
        // CLAUSE 2A: Start freeze episode
        // "re-emit the last successfully emitted real frame"
        // =====================================================================
        pacing_freeze_start_us_ = now_wall_us;
        pacing_in_freeze_mode_ = true;
        pacing_late_events_++;

        std::cout << "[ProgramOutput] INV-PACING-002: FREEZE frame="
                  << stats_.frames_rendered << " lateness="
                  << (frame_lateness_us / 1000) << "ms" << std::endl;

        // Re-emit last frame (freeze)
        frame = pacing_last_emitted_frame_;
        using_freeze_frame = true;
        pacing_freeze_frames_++;
        pacing_current_freeze_streak_++;

      } else if ((now_wall_us - pacing_freeze_start_us_) < pacing_freeze_window_us_) {
        // =====================================================================
        // CLAUSE 2A: Continue freeze within window
        // "Maximum continuous freeze duration: 250ms"
        // =====================================================================
        frame = pacing_last_emitted_frame_;
        using_freeze_frame = true;
        pacing_freeze_frames_++;
        pacing_current_freeze_streak_++;
        pacing_freeze_duration_ms_ = (now_wall_us - pacing_freeze_start_us_) / 1000;

      } else {
        // =====================================================================
        // CLAUSE 2B: Freeze window exceeded - switch to pad
        // "If the freeze window is exceeded... emit pad frames"
        // =====================================================================
        std::cout << "[ProgramOutput] INV-PACING-002: PAD after freeze window exceeded ("
                  << ((now_wall_us - pacing_freeze_start_us_) / 1000) << "ms)" << std::endl;

        // Record max freeze streak
        if (pacing_current_freeze_streak_ > pacing_max_freeze_streak_) {
          pacing_max_freeze_streak_ = pacing_current_freeze_streak_;
        }
        pacing_current_freeze_streak_ = 0;

        goto emit_pad_frame;
      }

      // Skip pad frame generation - we're using freeze frame
      goto frame_ready;

emit_pad_frame:

      // =========================================================================
      // INV-P10.5-OUTPUT-SAFETY-RAIL: Emit pad frame when producer is starved
      // =========================================================================
      // Output must NEVER stall. If no producer frame is available, emit a
      // deterministic black video frame and silence audio to maintain CT
      // continuity. No waiting, no blocking, no multi-second pauses.
      //
      // This is NOT "filler" content - it's a continuity guarantee.
      // Producer starvation, EOF, shadow readiness, or gating must NOT stop output.
      // =========================================================================

      // -----------------------------------------------------------------------
      // INV-P10-PAD-REASON: Classify pad frame cause for diagnostics
      // -----------------------------------------------------------------------
      PadReason reason = PadReason::UNKNOWN;
      if (video_depth_before_pop == 0) {
        reason = PadReason::BUFFER_TRULY_EMPTY;
        pads_buffer_empty_++;
      } else {
        // Buffer had frames but Pop failed - shouldn't happen with current impl
        reason = PadReason::UNKNOWN;
        pads_unknown_++;
      }

      // -----------------------------------------------------------------------
      // INV-NO-PAD-WHILE-DEPTH-HIGH: Log violation if pad emitted while depth >= 10
      // -----------------------------------------------------------------------
      if (video_depth_before_pop >= kDepthHighThreshold) {
        pad_while_depth_high_++;
        std::cout << "[ProgramOutput] INV-NO-PAD-WHILE-DEPTH-HIGH VIOLATION: Pad emitted while depth="
                  << video_depth_before_pop << " >= " << kDepthHighThreshold
                  << " (violations=" << pad_while_depth_high_ << ")" << std::endl;
      }

      if (!pad_frame_initialized_) {
        // First time starvation before we've seen any real frames.
        // Use defaults (1920x1080 @ 30fps). Will be corrected on first real frame.
        pad_frame_initialized_ = true;
        std::cout << "[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Using default pad frame params "
                  << pad_frame_width_ << "x" << pad_frame_height_
                  << " @ " << (1'000'000 / pad_frame_duration_us_) << "fps" << std::endl;
      }

      // -----------------------------------------------------------------------
      // INV-PTS-DERIVES-CT: Pad PTS must equal CT at moment of emission
      // -----------------------------------------------------------------------
      // Pad frames derive PTS directly from TimelineController (CT).
      // No local accumulation. No fallback to last_pts_.
      // This ensures PTS continuity across segment boundaries and producer switches.
      // See: RULE-PAD-001, RULE-PO-001, INV-NO-LOCAL-EPOCHS
      // -----------------------------------------------------------------------
      int64_t pad_pts_us = 0;
      if (clock_) {
        pad_pts_us = clock_->now_utc_us() - clock_->get_epoch_utc_us();
      } else {
        // Fallback: no clock available (should not happen in production)
        // Use last_pts_ + duration only as emergency fallback
        pad_pts_us = last_pts_ + pad_frame_duration_us_;
      }

      frame = GeneratePadFrame(pad_pts_us);
      using_pad_frame = true;
      pad_frames_emitted_++;

      if (pad_frames_emitted_ == 1 || pad_frames_emitted_ % 30 == 0) {
        std::cout << "[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad frame #"
                  << pad_frames_emitted_ << " at PTS=" << pad_pts_us << "us"
                  << " reason=" << PadReasonToString(reason) << std::endl;

        // =====================================================================
        // PRIMITIVE INVARIANT DISCRIMINATION PROBE
        // =====================================================================
        // When pad frames are emitted, log data needed to identify which
        // primitive invariant is violated:
        //   - INV-PACING-001: pad_rate >> real-time, decode_active=true, eof=false
        //   - INV-DECODE-RATE-001: pad_rate = real-time, decode_active=true, eof=false
        //   - INV-SEGMENT-CONTENT-001: pad_rate = real-time, decode_active=false, eof=true
        //
        // See: docs/contracts/semantics/PrimitiveInvariants.md (Discrimination Matrix)
        // =====================================================================
        const int64_t now_us = clock_ ? clock_->now_utc_us()
                                      : std::chrono::duration_cast<std::chrono::microseconds>(
                                            std::chrono::steady_clock::now().time_since_epoch()).count();

        // Calculate pad emission rate over recent window
        double pad_rate_fps = 0.0;
        if (pacing_probe_window_start_us_ > 0) {
          const int64_t elapsed_us = now_us - pacing_probe_window_start_us_;
          if (elapsed_us > 0) {
            pad_rate_fps = static_cast<double>(pacing_probe_window_frames_) *
                           1'000'000.0 / static_cast<double>(elapsed_us);
          }
        }

        const double target_fps = 1'000'000.0 / static_cast<double>(pad_frame_duration_us_);
        const bool rate_is_fast = (pad_rate_fps > target_fps * 2.0);

        std::cout << "[ProgramOutput] DISCRIMINATION PROBE: "
                  << "pad_count=" << pad_frames_emitted_ << ", "
                  << "emission_rate=" << pad_rate_fps << "fps "
                  << (rate_is_fast ? "(>>real-time)" : "(~real-time)") << ", "
                  << "buffer_depth=" << video_depth_before_pop << ", "
                  << "fast_emissions=" << pacing_probe_fast_emissions_
                  << std::endl;
      }

      // Process any ready audio from buffer (same as before)
      while (true) {
        const buffer::AudioFrame* peeked = current_buffer->PeekAudioFrame();
        if (!peeked) break;

        if (clock_) {
          const int64_t audio_deadline_utc = clock_->scheduled_to_utc_us(peeked->pts_us);
          const int64_t now_utc = clock_->now_utc_us();
          if (audio_deadline_utc > now_utc) {
            break;  // Audio is in the future - hold for next iteration
          }
        }

        buffer::AudioFrame audio_frame;
        if (!current_buffer->PopAudioFrame(audio_frame)) break;

        std::lock_guard<std::mutex> bus_lock(output_bus_mutex_);
        if (output_bus_) {
          output_bus_->RouteAudio(audio_frame);
        } else {
          std::lock_guard<std::mutex> lock(audio_side_sink_mutex_);
          if (audio_side_sink_) {
            audio_side_sink_(audio_frame);
          }
        }
      }

      // =========================================================================
      // INV-P10.5: Pad audio is GATED by pad video emission AND format lock
      // =========================================================================
      // Pad audio is emitted ONLY when:
      //   1. Pad video is emitted (which it always is in this code path)
      //   2. Audio format is locked (channel has started)
      //
      // If audio format is not locked, emit VIDEO-ONLY pad to avoid
      // introducing a new audio format that could cause AUDIO_FORMAT_CHANGE.
      //
      // samples_per_frame = sample_rate / fps + remainder
      // This keeps filler phase-continuous across frames.
      // =========================================================================
      if (current_buffer->IsAudioEmpty() && audio_format_locked_) {
        // Compute exact samples for this video frame duration with fractional accumulation
        // Always use canonical sample rate, never infer from producer
        const double fps = 1'000'000.0 / static_cast<double>(pad_frame_duration_us_);
        const double exact_samples = static_cast<double>(kCanonicalPadSampleRate) / fps + audio_sample_remainder_;
        const int samples = static_cast<int>(std::floor(exact_samples));
        audio_sample_remainder_ = exact_samples - static_cast<double>(samples);

        buffer::AudioFrame pad_audio = GeneratePadAudio(pad_pts_us, samples);

        std::lock_guard<std::mutex> bus_lock(output_bus_mutex_);
        if (output_bus_) {
          output_bus_->RouteAudio(pad_audio);
        } else {
          std::lock_guard<std::mutex> lock(audio_side_sink_mutex_);
          if (audio_side_sink_) {
            audio_side_sink_(pad_audio);
          }
        }
      } else if (current_buffer->IsAudioEmpty() && !audio_format_locked_) {
        // Audio format not yet locked - emit video-only pad
        // This prevents introducing a new audio format before encoder is ready
        if (pad_frames_emitted_ == 1) {
          std::cout << "[ProgramOutput] INV-P10.5-AUDIO-FORMAT-LOCK: Video-only pad (audio format not locked)"
                    << std::endl;
        }
      }

      // INV-PACING-ENFORCEMENT-002: Skip the real-frame else block
      goto frame_ready;
    } else {
      // =========================================================================
      // INV-PACING-ENFORCEMENT-002 CLAUSE 2: Recovery from freeze mode
      // "RECOVERED real frame available"
      // =========================================================================
      if (pacing_in_freeze_mode_) {
        std::cout << "[ProgramOutput] INV-PACING-002: RECOVERED real frame available"
                  << " after " << (pacing_freeze_duration_ms_) << "ms freeze" << std::endl;

        // Record max freeze streak before resetting
        if (pacing_current_freeze_streak_ > pacing_max_freeze_streak_) {
          pacing_max_freeze_streak_ = pacing_current_freeze_streak_;
        }
        pacing_current_freeze_streak_ = 0;
        pacing_in_freeze_mode_ = false;
        pacing_freeze_duration_ms_ = 0;
      }

      // Learn frame parameters from first real frame for future pad frames
      if (!pad_frame_initialized_ && frame.width > 0 && frame.height > 0) {
        pad_frame_width_ = frame.width;
        pad_frame_height_ = frame.height;
        if (frame.metadata.duration > 0.0) {
          pad_frame_duration_us_ = static_cast<int64_t>(frame.metadata.duration * 1'000'000.0);
          // Also update pacing frame period to match real content
          pacing_frame_period_us_ = pad_frame_duration_us_;
        }
        pad_frame_initialized_ = true;
        std::cout << "[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Learned pad frame params "
                  << pad_frame_width_ << "x" << pad_frame_height_
                  << " @ " << (1'000'000 / pad_frame_duration_us_) << "fps" << std::endl;
      }

      // =========================================================================
      // INV-PACING-ENFORCEMENT-002: Record frame for potential freeze re-emission
      // =========================================================================
      // Store the real frame so it can be re-emitted if buffer starves.
      pacing_last_emitted_frame_ = frame;
      pacing_has_last_frame_ = true;
    }

frame_ready:

    double frame_gap_ms = 0.0;
    if (clock_) {
      const int64_t deadline_utc = clock_->scheduled_to_utc_us(frame.metadata.pts);
      const int64_t now_utc = clock_->now_utc_us();
      const int64_t gap_us = deadline_utc - now_utc;
      const double gap_s = static_cast<double>(gap_us) / 1'000'000.0;
      frame_gap_ms = gap_s * 1000.0;

      if (gap_s > 0.0) {
        const int64_t deadline_utc =
            clock_->scheduled_to_utc_us(frame.metadata.pts);
        const int64_t target_utc = deadline_utc - WaitFudgeUs();
        WaitUntilUtc(clock_, target_utc, &stop_requested_);

        int64_t remaining_us =
            clock_->scheduled_to_utc_us(frame.metadata.pts) - clock_->now_utc_us();
        while (remaining_us > kSpinThresholdUs && !stop_requested_.load(std::memory_order_acquire)) {
          const int64_t spin_us =
              std::min<int64_t>(remaining_us / 2, kSpinSleepUs);
          WaitForMicros(clock_, spin_us, &stop_requested_);
          remaining_us =
              clock_->scheduled_to_utc_us(frame.metadata.pts) - clock_->now_utc_us();
        }
      }
      // =========================================================================
      // INV-PACING-ENFORCEMENT-002 CLAUSE 3: NO FRAME DROPPING
      // =========================================================================
      // The system "SHALL NOT drop or skip real frames" to recover from lateness.
      // Previous drop logic removed per RealTimeHoldPolicy.
      // Late frames are emitted immediately; output cadence is preserved.
      // =========================================================================
    } else {
      auto now = std::chrono::steady_clock::now();
      frame_gap_ms =
          std::chrono::duration<double, std::milli>(now - fallback_last_frame_time_).count();
      fallback_last_frame_time_ = now;
    }

    RenderFrame(frame);

    {
      std::lock_guard<std::mutex> bus_lock(output_bus_mutex_);
      if (output_bus_) {
        output_bus_->RouteVideo(frame);
      } else {
        std::lock_guard<std::mutex> lock(side_sink_mutex_);
        if (side_sink_) {
          side_sink_(frame);
        }
      }
    }

    // =========================================================================
    // INV-AIR-CONTENT-BEFORE-PAD: Mark first real frame as emitted
    // =========================================================================
    // Once first real content frame is routed to output, pad frames are allowed.
    // This ensures VLC receives decodable content (with IDR/SPS/PPS) first.
    if (!first_real_frame_emitted_) {
      first_real_frame_emitted_ = true;
      std::cout << "[ProgramOutput] INV-AIR-CONTENT-BEFORE-PAD: First real content frame emitted, "
                << "pad frames now allowed. PTS=" << frame.metadata.pts << "us"
                << " size=" << frame.width << "x" << frame.height << std::endl;
    }

    // =========================================================================
    // INV-P8-SUCCESSOR-OBSERVABILITY: Notify observer on first real successor video
    // =========================================================================
    // Real video (non-pad) admitted into ProgramOutput. Fire observer exactly once
    // per segment so TimelineController can advance commit_gen.
    if (!using_pad_frame && frame.metadata.asset_uri != "pad://black") {
      std::lock_guard<std::mutex> lock(successor_observer_mutex_);
      if (on_successor_video_emitted_ && !successor_observer_fired_for_segment_) {
        successor_observer_fired_for_segment_ = true;
        on_successor_video_emitted_();
      }
    }

    // =========================================================================
    // INV-P9-OUTPUT-CT-GATE: No frame emitted to sink before its CT
    // =========================================================================
    // No audio or video frame may be emitted to any sink before its CT.
    //
    // Producers may decode early and buffers may fill early, but release to
    // output must be gated by CT. This prevents "audio too fast" during switches
    // where audio was decoded ahead of video.
    //
    // Implementation: Peek audio frame, check if its CT is ready for release.
    // Only pop and route if CT <= wall_clock_now.
    // =========================================================================
    int audio_frames_consumed = 0;
    int audio_frames_held = 0;
    while (true) {
      // Peek to check CT authority before consuming
      const buffer::AudioFrame* peeked = current_buffer->PeekAudioFrame();
      if (!peeked) {
        break;  // No more audio frames
      }

      // INV-P9-OUTPUT-CT-GATE: Gate audio release on CT vs wall-clock
      if (clock_) {
        const int64_t audio_deadline_utc = clock_->scheduled_to_utc_us(peeked->pts_us);
        const int64_t now_utc = clock_->now_utc_us();
        if (audio_deadline_utc > now_utc) {
          // Audio frame is in the future - hold it for next iteration
          audio_frames_held++;
          break;
        }
      }

      // CT is ready - pop and route
      buffer::AudioFrame audio_frame;
      if (!current_buffer->PopAudioFrame(audio_frame)) {
        break;  // Race condition - frame was consumed elsewhere
      }
      audio_frames_consumed++;

      {
        std::lock_guard<std::mutex> bus_lock(output_bus_mutex_);
        if (output_bus_) {
          output_bus_->RouteAudio(audio_frame);
        } else {
          std::lock_guard<std::mutex> lock(audio_side_sink_mutex_);
          if (audio_side_sink_) {
            audio_side_sink_(audio_frame);
          }
        }
      }
    }
    if (audio_frames_consumed > 0 && stats_.frames_rendered % 100 == 0) {
      std::cout << "[ProgramOutput] Consumed " << audio_frames_consumed
                << " audio frames for video frame #" << stats_.frames_rendered << std::endl;
    }

    int64_t frame_end_utc = 0;
    std::chrono::steady_clock::time_point frame_end_fallback;
    if (clock_) {
      frame_end_utc = clock_->now_utc_us();
    } else {
      frame_end_fallback = std::chrono::steady_clock::now();
    }

    double render_time_ms = 0.0;
    if (clock_) {
      render_time_ms =
          static_cast<double>(frame_end_utc - frame_start_utc) / 1'000.0;
      last_frame_time_utc_ = frame_end_utc;
    } else {
      render_time_ms =
          std::chrono::duration<double, std::milli>(frame_end_fallback - frame_start_fallback)
              .count();
      fallback_last_frame_time_ = frame_end_fallback;
    }

    UpdateStats(render_time_ms, frame_gap_ms);
    PublishMetrics(frame_gap_ms);

    // =========================================================================
    // INV-PACING-001 DIAGNOSTIC PROBE: Detect render loop pacing violations
    // =========================================================================
    // Measures wall-clock time between frame emissions to detect when frames
    // are emitted at CPU speed instead of target frame rate.
    //
    // Violation signature: gap << frame_duration (e.g., <1ms instead of 33ms)
    // See: docs/contracts/semantics/PrimitiveInvariants.md
    // =========================================================================
    {
      const int64_t now_us = clock_ ? clock_->now_utc_us()
                                    : std::chrono::duration_cast<std::chrono::microseconds>(
                                          std::chrono::steady_clock::now().time_since_epoch()).count();

      // Initialize probe on first emission
      if (pacing_probe_last_emission_us_ == 0) {
        pacing_probe_last_emission_us_ = now_us;
        pacing_probe_window_start_us_ = now_us;
        pacing_probe_window_frames_ = 0;
      }

      pacing_probe_total_emissions_++;
      pacing_probe_window_frames_++;

      // Measure inter-frame gap
      const int64_t emission_gap_us = now_us - pacing_probe_last_emission_us_;
      pacing_probe_last_emission_us_ = now_us;

      // Detect pacing violation: gap < threshold * frame_duration
      const int64_t expected_gap_us = pad_frame_duration_us_;  // ~33333us at 30fps
      const int64_t violation_threshold_us = static_cast<int64_t>(
          expected_gap_us * kPacingViolationThreshold);

      if (emission_gap_us > 0 && emission_gap_us < violation_threshold_us &&
          pacing_probe_total_emissions_ > 1) {
        pacing_probe_fast_emissions_++;
      }

      // Check 1-second window for rate measurement
      const int64_t window_elapsed_us = now_us - pacing_probe_window_start_us_;
      if (window_elapsed_us >= kPacingProbeWindowUs) {
        const double window_fps = static_cast<double>(pacing_probe_window_frames_) *
                                  1'000'000.0 / static_cast<double>(window_elapsed_us);
        const double target_fps = 1'000'000.0 / static_cast<double>(pad_frame_duration_us_);

        // Log INV-PACING-001 probe data
        const bool is_violation = (window_fps > target_fps * 2.0);  // 2x = clear violation
        if (is_violation && !pacing_violation_logged_) {
          pacing_violation_logged_ = true;
          std::cout << "[ProgramOutput] INV-PACING-001 VIOLATION DETECTED: "
                    << "emission_rate=" << window_fps << "fps "
                    << "(expected=" << target_fps << "fps), "
                    << "fast_emissions=" << pacing_probe_fast_emissions_ << "/" << pacing_probe_total_emissions_
                    << ", pad_frames=" << pad_frames_emitted_
                    << ", using_pad=" << (using_pad_frame ? "true" : "false")
                    << std::endl;
        }

        // Reset window
        pacing_probe_window_start_us_ = now_us;
        pacing_probe_window_frames_ = 0;
      }
    }

    if (stats_.frames_rendered % 100 == 0) {
      std::cout << "[ProgramOutput] Rendered " << stats_.frames_rendered
                << " frames, avg render time: " << stats_.average_render_time_ms << "ms, "
                << "fps: " << stats_.current_render_fps
                << ", gap: " << frame_gap_ms << "ms" << std::endl;
    }

    last_pts_ = frame.metadata.pts;
    // Contract-level observability: first PTS for AIR_AS_RUN_FRAME_RANGE (real frame only).
    if (!first_pts_set_ && frame.metadata.asset_uri != "pad://black") {
      first_pts_ = frame.metadata.pts;
      first_pts_set_ = true;
    }

    // =========================================================================
    // INV-PACING-ENFORCEMENT-002: Update emission timestamp for next iteration
    // =========================================================================
    // Record wall-clock time of this emission for pacing the next frame.
    // This ensures exactly one frame per frame period regardless of path taken.
    if (clock_) {
      pacing_last_emission_us_ = clock_->now_utc_us();
    } else {
      pacing_last_emission_us_ = std::chrono::duration_cast<std::chrono::microseconds>(
          std::chrono::steady_clock::now().time_since_epoch()).count();
    }
  }

  Cleanup();
  running_.store(false, std::memory_order_release);

  std::cout << "[ProgramOutput] Output loop exited" << std::endl;
}

void ProgramOutput::UpdateStats(double render_time_ms, double frame_gap_ms) {
  stats_.frames_rendered++;
  stats_.frame_gap_ms = frame_gap_ms;

  const double alpha = 0.1;
  stats_.average_render_time_ms =
      alpha * render_time_ms + (1.0 - alpha) * stats_.average_render_time_ms;

  if (frame_gap_ms > 0.0) {
    stats_.current_render_fps = 1000.0 / frame_gap_ms;
  }
}

void ProgramOutput::PublishMetrics(double frame_gap_ms) {
  if (!metrics_) {
    return;
  }

  telemetry::ChannelMetrics snapshot;
  if (!metrics_->GetChannelMetrics(channel_id_, snapshot)) {
    snapshot = telemetry::ChannelMetrics{};
  }

  snapshot.buffer_depth_frames = input_buffer_->Size();
  snapshot.frame_gap_seconds = frame_gap_ms / 1000.0;
  snapshot.corrections_total = stats_.corrections_total;
  metrics_->SubmitChannelMetrics(channel_id_, snapshot);
}

void ProgramOutput::setProducer(producers::IProducer* producer) {
  (void)producer;
  std::cout << "[ProgramOutput] Producer reference updated" << std::endl;
}

void ProgramOutput::resetPipeline() {
  std::cout << "[ProgramOutput] Resetting pipeline..." << std::endl;

  input_buffer_->Clear();

  // -------------------------------------------------------------------------
  // INV-NO-LOCAL-EPOCHS: Do NOT reset timing state
  // -------------------------------------------------------------------------
  // Pipeline reset clears buffers only. Timing state (last_pts_, etc.) must
  // NOT be modified. Pad frames derive PTS from CT, not from last_pts_.
  // Resetting last_pts_ would create conditions for epoch discontinuity.
  // See: RULE-PO-002
  // -------------------------------------------------------------------------

  if (clock_) {
    last_frame_time_utc_ = clock_->now_utc_us();
  } else {
    fallback_last_frame_time_ = std::chrono::steady_clock::now();
  }

  std::cout << "[ProgramOutput] Pipeline reset complete" << std::endl;
}

void ProgramOutput::SetSideSink(std::function<void(const buffer::Frame&)> fn) {
  std::lock_guard<std::mutex> lock(side_sink_mutex_);
  side_sink_ = std::move(fn);
}

void ProgramOutput::ClearSideSink() {
  std::lock_guard<std::mutex> lock(side_sink_mutex_);
  side_sink_ = nullptr;
}

void ProgramOutput::SetAudioSideSink(std::function<void(const buffer::AudioFrame&)> fn) {
  std::lock_guard<std::mutex> lock(audio_side_sink_mutex_);
  audio_side_sink_ = std::move(fn);
}

void ProgramOutput::ClearAudioSideSink() {
  std::lock_guard<std::mutex> lock(audio_side_sink_mutex_);
  audio_side_sink_ = nullptr;
}

void ProgramOutput::SetOutputBus(output::OutputBus* bus) {
  std::lock_guard<std::mutex> lock(output_bus_mutex_);

  // INV-P9-NO-BUS-REPLACEMENT: Idempotent - same bus is no-op.
  if (output_bus_ == bus) {
    return;
  }

  // INV-P9-NO-BUS-REPLACEMENT: Changing bus while one is set is a violation.
  // Once a channel has a bus and sink attached, bus identity must not change.
  if (output_bus_ != nullptr && bus != nullptr) {
    std::cerr << "[ProgramOutput] INV-P9-NO-BUS-REPLACEMENT FATAL: SetOutputBus called with "
              << "different bus (old=" << static_cast<void*>(output_bus_)
              << " new=" << static_cast<void*>(bus)
              << "). Bus must not be replaced." << std::endl;
    std::abort();
  }

  output_bus_ = bus;
  std::cout << "[DBG-PO] SetOutputBus channel=" << channel_id_
            << " bus=" << static_cast<void*>(bus)
            << " (idempotent skip if same)" << std::endl;
  if (bus) {
    std::cout << "[ProgramOutput] OutputBus set (frames will route through bus)" << std::endl;
  }
}

void ProgramOutput::ClearOutputBus() {
  std::lock_guard<std::mutex> lock(output_bus_mutex_);
  output_bus_ = nullptr;
  std::cout << "[ProgramOutput] OutputBus cleared (frames will use legacy callbacks)" << std::endl;
}

void ProgramOutput::SetInputBuffer(buffer::FrameRingBuffer* buffer) {
  {
    std::lock_guard<std::mutex> lock(input_buffer_mutex_);
    input_buffer_ = buffer;
  }
  // Contract-level observability: new segment; reset first PTS for AIR_AS_RUN.
  first_pts_ = 0;
  first_pts_set_ = false;
  // INV-P8-SUCCESSOR-OBSERVABILITY: New segment when buffer changes; reset latch.
  {
    std::lock_guard<std::mutex> lock(successor_observer_mutex_);
    successor_observer_fired_for_segment_ = false;
  }
  std::cout << "[ProgramOutput] Input buffer redirected (hot-switch)" << std::endl;
}

void ProgramOutput::SetOnSuccessorVideoEmitted(OnSuccessorVideoEmittedCallback callback) {
  std::lock_guard<std::mutex> lock(successor_observer_mutex_);
  on_successor_video_emitted_ = std::move(callback);
}

int64_t ProgramOutput::GetLastEmittedPTS() const {
  // Phase 7: Return last emitted PTS for continuity across segment boundaries
  // This is read by SwitchToLive to align the next segment's PTS
  return last_pts_;
}

int64_t ProgramOutput::GetFirstEmittedPTS() const {
  return first_pts_set_ ? first_pts_ : 0;
}

// =============================================================================
// INV-P10.5-OUTPUT-SAFETY-RAIL: Pad frame generation
// =============================================================================
// When producer is starved (buffer empty), output must continue with
// deterministic black video and silence audio to maintain CT continuity.
// No freeze, no stall, no multi-second pause.
// =============================================================================

buffer::Frame ProgramOutput::GeneratePadFrame(int64_t pts_us) {
  buffer::Frame frame;
  frame.width = pad_frame_width_;
  frame.height = pad_frame_height_;
  frame.metadata.pts = pts_us;
  frame.metadata.dts = pts_us;
  frame.metadata.duration = static_cast<double>(pad_frame_duration_us_) / 1'000'000.0;
  frame.metadata.asset_uri = "pad://black";
  frame.metadata.has_ct = true;  // Pad frames have valid CT

  // YUV420 black frame: Y=16 (black), U=V=128 (neutral chroma)
  const int y_size = pad_frame_width_ * pad_frame_height_;
  const int uv_size = (pad_frame_width_ / 2) * (pad_frame_height_ / 2);
  frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));

  // Fill Y plane with 16 (black in TV range)
  std::memset(frame.data.data(), 16, static_cast<size_t>(y_size));
  // Fill U and V planes with 128 (neutral chroma)
  std::memset(frame.data.data() + y_size, 128, static_cast<size_t>(2 * uv_size));

  return frame;
}

buffer::AudioFrame ProgramOutput::GeneratePadAudio(int64_t pts_us, int nb_samples) {
  buffer::AudioFrame audio;
  audio.pts_us = pts_us;
  // INV-P10.5-AUDIO-FORMAT-LOCK: Always use canonical format, never infer from producer
  audio.sample_rate = kCanonicalPadSampleRate;
  audio.channels = kCanonicalPadChannels;
  audio.nb_samples = nb_samples;

  // S16 interleaved silence: all zeros
  const size_t data_size = static_cast<size_t>(nb_samples) *
                           static_cast<size_t>(kCanonicalPadChannels) * sizeof(int16_t);
  audio.data.resize(data_size, 0);

  return audio;
}

// ============================================================================
// HeadlessProgramOutput
// ============================================================================

HeadlessProgramOutput::HeadlessProgramOutput(const RenderConfig& config,
                                             buffer::FrameRingBuffer& input_buffer,
                                             const std::shared_ptr<timing::MasterClock>& clock,
                                             const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                                             int32_t channel_id)
    : ProgramOutput(config, input_buffer, clock, metrics, channel_id) {}

HeadlessProgramOutput::~HeadlessProgramOutput() {}

bool HeadlessProgramOutput::Initialize() {
  std::cout << "[HeadlessProgramOutput] Initialized (no display output)" << std::endl;
  return true;
}

void HeadlessProgramOutput::RenderFrame(const buffer::Frame& frame) {
  (void)frame;
}

void HeadlessProgramOutput::Cleanup() {
  std::cout << "[HeadlessProgramOutput] Cleanup complete" << std::endl;
}

// ============================================================================
// PreviewProgramOutput
// ============================================================================

#ifdef RETROVUE_SDL2_AVAILABLE

PreviewProgramOutput::PreviewProgramOutput(const RenderConfig& config,
                                           buffer::FrameRingBuffer& input_buffer,
                                           const std::shared_ptr<timing::MasterClock>& clock,
                                           const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                                           int32_t channel_id)
    : ProgramOutput(config, input_buffer, clock, metrics, channel_id),
      window_(nullptr),
      sdl_renderer_(nullptr),
      texture_(nullptr) {}

PreviewProgramOutput::~PreviewProgramOutput() {}

bool PreviewProgramOutput::Initialize() {
  std::cout << "[PreviewProgramOutput] Initializing SDL2..." << std::endl;

  if (SDL_Init(SDL_INIT_VIDEO) < 0) {
    std::cerr << "[PreviewProgramOutput] SDL_Init failed: " << SDL_GetError() << std::endl;
    return false;
  }

  SDL_Window* window = SDL_CreateWindow(
      config_.window_title.c_str(),
      SDL_WINDOWPOS_CENTERED,
      SDL_WINDOWPOS_CENTERED,
      config_.window_width,
      config_.window_height,
      SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE);

  if (!window) {
    std::cerr << "[PreviewProgramOutput] SDL_CreateWindow failed: " << SDL_GetError()
              << std::endl;
    SDL_Quit();
    return false;
  }
  window_ = window;

  Uint32 flags = SDL_RENDERER_ACCELERATED;
  if (config_.vsync_enabled) {
    flags |= SDL_RENDERER_PRESENTVSYNC;
  }

  SDL_Renderer* renderer = SDL_CreateRenderer(window, -1, flags);
  if (!renderer) {
    std::cerr << "[PreviewProgramOutput] SDL_CreateRenderer failed: " << SDL_GetError()
              << std::endl;
    SDL_DestroyWindow(window);
    SDL_Quit();
    return false;
  }
  sdl_renderer_ = renderer;

  SDL_Texture* texture = SDL_CreateTexture(
      renderer,
      SDL_PIXELFORMAT_IYUV,
      SDL_TEXTUREACCESS_STREAMING,
      config_.window_width,
      config_.window_height);

  if (!texture) {
    std::cerr << "[PreviewProgramOutput] SDL_CreateTexture failed: " << SDL_GetError()
              << std::endl;
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return false;
  }
  texture_ = texture;

  std::cout << "[PreviewProgramOutput] Initialized successfully: "
            << config_.window_width << "x" << config_.window_height << std::endl;

  return true;
}

void PreviewProgramOutput::RenderFrame(const buffer::Frame& frame) {
  SDL_Window* window = static_cast<SDL_Window*>(window_);
  SDL_Renderer* renderer = static_cast<SDL_Renderer*>(sdl_renderer_);
  SDL_Texture* texture = static_cast<SDL_Texture*>(texture_);

  SDL_Event event;
  while (SDL_PollEvent(&event)) {
    if (event.type == SDL_QUIT) {
      stop_requested_.store(true, std::memory_order_release);
      return;
    }
  }

  if (!frame.data.empty()) {
    int y_size = frame.width * frame.height;
    int uv_size = (frame.width / 2) * (frame.height / 2);

    const uint8_t* y_plane = frame.data.data();
    const uint8_t* u_plane = y_plane + y_size;
    const uint8_t* v_plane = u_plane + uv_size;

    SDL_UpdateYUVTexture(
        texture,
        nullptr,
        y_plane, frame.width,
        u_plane, frame.width / 2,
        v_plane, frame.width / 2);
  }

  SDL_RenderClear(renderer);
  SDL_RenderCopy(renderer, texture, nullptr, nullptr);
  SDL_RenderPresent(renderer);
}

void PreviewProgramOutput::Cleanup() {
  std::cout << "[PreviewProgramOutput] Cleaning up SDL2..." << std::endl;

  if (texture_) {
    SDL_DestroyTexture(static_cast<SDL_Texture*>(texture_));
    texture_ = nullptr;
  }

  if (sdl_renderer_) {
    SDL_DestroyRenderer(static_cast<SDL_Renderer*>(sdl_renderer_));
    sdl_renderer_ = nullptr;
  }

  if (window_) {
    SDL_DestroyWindow(static_cast<SDL_Window*>(window_));
    window_ = nullptr;
  }

  SDL_Quit();
  std::cout << "[PreviewProgramOutput] Cleanup complete" << std::endl;
}

#else
// Stub implementations when SDL2 not available

PreviewProgramOutput::PreviewProgramOutput(const RenderConfig& config,
                                           buffer::FrameRingBuffer& input_buffer,
                                           const std::shared_ptr<timing::MasterClock>& clock,
                                           const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                                           int32_t channel_id)
    : ProgramOutput(config, input_buffer, clock, metrics, channel_id),
      window_(nullptr),
      sdl_renderer_(nullptr),
      texture_(nullptr) {}

PreviewProgramOutput::~PreviewProgramOutput() {}

bool PreviewProgramOutput::Initialize() {
  std::cerr << "[PreviewProgramOutput] ERROR: SDL2 not available. Rebuild with SDL2 for preview mode."
            << std::endl;
  return false;
}

void PreviewProgramOutput::RenderFrame(const buffer::Frame& frame) {
  (void)frame;
}

void PreviewProgramOutput::Cleanup() {}

#endif  // RETROVUE_SDL2_AVAILABLE

}  // namespace retrovue::renderer
