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

void ProgramOutput::RenderLoop() {
  std::cout << "[ProgramOutput] Output loop started (mode="
            << (config_.mode == RenderMode::HEADLESS ? "HEADLESS" : "PREVIEW")
            << ")" << std::endl;

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

  while (!stop_requested_.load(std::memory_order_acquire)) {
    // Phase 7: Get current buffer pointer under lock to support hot-switching.
    // The pointer may change during SwitchToLive, so we read it once per iteration.
    buffer::FrameRingBuffer* current_buffer;
    {
      std::lock_guard<std::mutex> lock(input_buffer_mutex_);
      current_buffer = input_buffer_;
    }

    int64_t frame_start_utc = 0;
    std::chrono::steady_clock::time_point frame_start_fallback;
    if (clock_) {
      frame_start_utc = clock_->now_utc_us();
    } else {
      frame_start_fallback = std::chrono::steady_clock::now();
    }

    buffer::Frame frame;
    bool using_pad_frame = false;
    if (!current_buffer->Pop(frame)) {
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

      if (!pad_frame_initialized_) {
        // First time starvation before we've seen any real frames.
        // Use defaults (1920x1080 @ 30fps). Will be corrected on first real frame.
        pad_frame_initialized_ = true;
        std::cout << "[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Using default pad frame params "
                  << pad_frame_width_ << "x" << pad_frame_height_
                  << " @ " << (1'000'000 / pad_frame_duration_us_) << "fps" << std::endl;
      }

      // Compute next PTS based on last emitted PTS + frame duration
      int64_t pad_pts_us = last_pts_ + pad_frame_duration_us_;

      // If we haven't emitted any frames yet, use current CT
      if (last_pts_ == 0 && clock_) {
        pad_pts_us = clock_->now_utc_us() - clock_->get_epoch_utc_us();
      }

      frame = GeneratePadFrame(pad_pts_us);
      using_pad_frame = true;
      pad_frames_emitted_++;

      if (pad_frames_emitted_ == 1 || pad_frames_emitted_ % 30 == 0) {
        std::cout << "[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Emitting pad frame #"
                  << pad_frames_emitted_ << " at PTS=" << pad_pts_us << "us" << std::endl;
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
    } else {
      // Learn frame parameters from first real frame for future pad frames
      if (!pad_frame_initialized_ && frame.width > 0 && frame.height > 0) {
        pad_frame_width_ = frame.width;
        pad_frame_height_ = frame.height;
        if (frame.metadata.duration > 0.0) {
          pad_frame_duration_us_ = static_cast<int64_t>(frame.metadata.duration * 1'000'000.0);
        }
        pad_frame_initialized_ = true;
        std::cout << "[ProgramOutput] INV-P10.5-OUTPUT-SAFETY-RAIL: Learned pad frame params "
                  << pad_frame_width_ << "x" << pad_frame_height_
                  << " @ " << (1'000'000 / pad_frame_duration_us_) << "fps" << std::endl;
      }
    }

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
      } else if (gap_s < kDropThresholdSeconds &&
                 current_buffer->Size() > kMinDepthForDrop) {
        stats_.frames_dropped++;
        stats_.corrections_total++;
        PublishMetrics(frame_gap_ms);
        continue;
      }
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

    if (stats_.frames_rendered % 100 == 0) {
      std::cout << "[ProgramOutput] Rendered " << stats_.frames_rendered
                << " frames, avg render time: " << stats_.average_render_time_ms << "ms, "
                << "fps: " << stats_.current_render_fps
                << ", gap: " << frame_gap_ms << "ms" << std::endl;
    }

    last_pts_ = frame.metadata.pts;
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

  last_pts_ = 0;
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
  output_bus_ = bus;
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
  std::lock_guard<std::mutex> lock(input_buffer_mutex_);
  input_buffer_ = buffer;
  std::cout << "[ProgramOutput] Input buffer redirected (hot-switch)" << std::endl;
}

int64_t ProgramOutput::GetLastEmittedPTS() const {
  // Phase 7: Return last emitted PTS for continuity across segment boundaries
  // This is read by SwitchToLive to align the next segment's PTS
  return last_pts_;
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
