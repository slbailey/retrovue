// Repository: Retrovue-playout
// Component: Program Output
// Purpose: Consumes decoded frames and delivers program signal to OutputBus or display.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RENDERER_PROGRAM_OUTPUT_H_
#define RETROVUE_RENDERER_PROGRAM_OUTPUT_H_

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
namespace retrovue::telemetry {
struct ChannelMetrics;
class MetricsExporter;
}  // namespace retrovue::telemetry

namespace retrovue::timing {
class MasterClock;
}  // namespace retrovue::timing

namespace retrovue::producers {
class IProducer;
}  // namespace retrovue::producers

namespace retrovue::output {
class OutputBus;
}  // namespace retrovue::output

namespace retrovue::renderer {

// RenderMode specifies the output type.
enum class RenderMode {
  HEADLESS = 0,  // No display output (production mode)
  PREVIEW = 1,   // Preview window (debug/development mode)
};

// RenderConfig holds configuration for program output.
struct RenderConfig {
  RenderMode mode;
  int window_width;
  int window_height;
  std::string window_title;
  bool vsync_enabled;

  RenderConfig()
      : mode(RenderMode::HEADLESS),
        window_width(1920),
        window_height(1080),
        window_title("RetroVue Playout Preview"),
        vsync_enabled(true) {}
};

// RenderStats tracks output performance and frame timing.
struct RenderStats {
  uint64_t frames_rendered;
  uint64_t frames_skipped;
  uint64_t frames_dropped;
  uint64_t corrections_total;
  double average_render_time_ms;
  double current_render_fps;
  double frame_gap_ms;  // Time since last frame

  RenderStats()
      : frames_rendered(0),
        frames_skipped(0),
        frames_dropped(0),
        corrections_total(0),
        average_render_time_ms(0.0),
        current_render_fps(0.0),
        frame_gap_ms(0.0) {}
};

// ProgramOutput consumes frames from the ring buffer and delivers program signal.
//
// Design:
// - Abstract base class with two concrete implementations:
//   - HeadlessProgramOutput: Consumes frames without display (production)
//   - PreviewProgramOutput: Opens SDL2/OpenGL window (debug/development)
// - Runs in dedicated output thread
// - Frame timing driven by metadata.pts
// - Back-pressure handling when buffer empty
//
// Thread Model:
// - Output runs in its own thread
// - Pops frames from FrameRingBuffer (thread-safe)
// - Independent from decode thread
//
// Lifecycle:
// 1. Construct with config and ring buffer reference
// 2. Call Start() to begin output
// 3. Call Stop() to gracefully shutdown
// 4. Destructor ensures thread is joined
class ProgramOutput {
 public:
  virtual ~ProgramOutput();

  // Starts the output thread.
  // Returns true if started successfully.
  bool Start();

  // Stops the output thread gracefully.
  void Stop();

  // Returns true if output is currently running.
  bool IsRunning() const { return running_.load(std::memory_order_acquire); }

  // Gets current output statistics.
  const RenderStats& GetStats() const { return stats_; }

  // Sets the producer (for switching between preview and live).
  void setProducer(producers::IProducer* producer);

  // Resets the pipeline (flushes buffers, resets timestamp state).
  // Called when switching producers to ensure clean state.
  void resetPipeline();

  // Redirects input to a different buffer (for hot-switching buses).
  // Per OutputSwitchingContract: Output Bus can change its source immediately.
  // Thread-safe: takes effect on next frame pop.
  void SetInputBuffer(buffer::FrameRingBuffer* buffer);

  // Phase 7: Returns the PTS of the last emitted frame.
  // Used by SwitchToLive to ensure PTS continuity across segment boundaries.
  // Per INV-P7-001: Channel PTS must be monotonically increasing.
  int64_t GetLastEmittedPTS() const;

  // Phase 8.4: Optional callback invoked for each frame (e.g. to feed TS mux).
  void SetSideSink(std::function<void(const buffer::Frame&)> fn);
  void ClearSideSink();

  // Phase 8.9: Optional callback invoked for each audio frame (e.g. to feed TS mux).
  void SetAudioSideSink(std::function<void(const buffer::AudioFrame&)> fn);
  void ClearAudioSideSink();

  // Phase 9.0: OutputBus integration
  // Sets the OutputBus to route frames to (replaces side_sink_ callbacks).
  // OutputBus pointer is NOT owned by ProgramOutput.
  void SetOutputBus(output::OutputBus* bus);
  void ClearOutputBus();

  // Factory method to create appropriate output based on mode.
  static std::unique_ptr<ProgramOutput> Create(
      const RenderConfig& config,
      buffer::FrameRingBuffer& input_buffer,
      const std::shared_ptr<timing::MasterClock>& clock,
      const std::shared_ptr<telemetry::MetricsExporter>& metrics,
      int32_t channel_id);

 protected:
  // Protected constructor - use factory method.
  ProgramOutput(const RenderConfig& config,
                buffer::FrameRingBuffer& input_buffer,
                const std::shared_ptr<timing::MasterClock>& clock,
                const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                int32_t channel_id);

  // Main output loop (runs in output thread).
  void RenderLoop();

  // Subclass-specific initialization.
  virtual bool Initialize() = 0;

  // Subclass-specific frame output.
  virtual void RenderFrame(const buffer::Frame& frame) = 0;

  // Subclass-specific cleanup.
  virtual void Cleanup() = 0;

  // Updates output statistics.
  void UpdateStats(double render_time_ms, double frame_gap_ms);
  void PublishMetrics(double frame_gap_ms);

  // =========================================================================
  // INV-P10.5-OUTPUT-SAFETY-RAIL: Pad frame generation for continuity
  // =========================================================================
  // Generates deterministic black video frame when producer is starved.
  // Frame has correct resolution, format, and PTS to maintain CT continuity.
  buffer::Frame GeneratePadFrame(int64_t pts_us);

  // Generates deterministic silence audio for corresponding duration.
  // Audio has correct sample rate, channels, and PTS to maintain CT continuity.
  buffer::AudioFrame GeneratePadAudio(int64_t pts_us, int nb_samples);

  RenderConfig config_;
  buffer::FrameRingBuffer* input_buffer_;  // Pointer for hot-switch redirection
  mutable std::mutex input_buffer_mutex_;  // Protects input_buffer_ pointer
  RenderStats stats_;

  std::shared_ptr<timing::MasterClock> clock_;
  std::shared_ptr<telemetry::MetricsExporter> metrics_;
  int32_t channel_id_;

  std::atomic<bool> running_;
  std::atomic<bool> stop_requested_;
  std::unique_ptr<std::thread> render_thread_;

  mutable std::mutex side_sink_mutex_;
  std::function<void(const buffer::Frame&)> side_sink_;

  // Phase 8.9: Audio side sink callback
  mutable std::mutex audio_side_sink_mutex_;
  std::function<void(const buffer::AudioFrame&)> audio_side_sink_;

  // Phase 9.0: OutputBus for frame routing (replaces side_sink_ when set)
  mutable std::mutex output_bus_mutex_;
  output::OutputBus* output_bus_ = nullptr;  // Not owned

  int64_t last_pts_;
  int64_t last_frame_time_utc_;
  std::chrono::steady_clock::time_point fallback_last_frame_time_;

  // =========================================================================
  // INV-P10.5-OUTPUT-SAFETY-RAIL: Pad frame state
  // =========================================================================
  // Tracks frame dimensions and rate learned from first real frame.
  // Used to generate matching pad frames when producer is starved.
  bool pad_frame_initialized_ = false;
  int pad_frame_width_ = 1920;
  int pad_frame_height_ = 1080;
  int64_t pad_frame_duration_us_ = 33333;  // Default 30fps
  uint64_t pad_frames_emitted_ = 0;  // Metric: retrovue_pad_frames_emitted_total

  // =========================================================================
  // INV-P10.5-AUDIO-FORMAT-LOCK: Pad audio format is FIXED at channel start
  // =========================================================================
  // Pad audio format is locked to canonical values (48000 Hz, 2 channels).
  // These values NEVER change, regardless of producer audio format.
  // This prevents AUDIO_FORMAT_CHANGE after TS header is written.
  //
  // If producer audio has different format (e.g., 44100 Hz), the encoder's
  // resampler handles it. Pad audio always uses the canonical format.
  // =========================================================================
  static constexpr int kCanonicalPadSampleRate = 48000;
  static constexpr int kCanonicalPadChannels = 2;
  bool audio_format_locked_ = false;  // Set true at channel start

  // Fractional sample accumulator for phase-continuous pad audio.
  // Reset ONLY on segment boundary (CT ownership change), not on first pad frame.
  double audio_sample_remainder_ = 0.0;

 public:
  // Called at channel start to lock pad audio format.
  // Must be called before any frames are emitted.
  void LockPadAudioFormat() {
    audio_format_locked_ = true;
  }

  // Called on segment boundary to reset pad audio phase accumulator.
  // This keeps filler phase-continuous within a segment.
  void ResetPadAudioAccumulator() { audio_sample_remainder_ = 0.0; }
};

// HeadlessProgramOutput consumes frames without displaying them.
class HeadlessProgramOutput : public ProgramOutput {
 public:
  HeadlessProgramOutput(const RenderConfig& config,
                        buffer::FrameRingBuffer& input_buffer,
                        const std::shared_ptr<timing::MasterClock>& clock,
                        const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                        int32_t channel_id);
  ~HeadlessProgramOutput() override;

 protected:
  bool Initialize() override;
  void RenderFrame(const buffer::Frame& frame) override;
  void Cleanup() override;
};

// PreviewProgramOutput displays frames in an SDL2 window.
class PreviewProgramOutput : public ProgramOutput {
 public:
  PreviewProgramOutput(const RenderConfig& config,
                       buffer::FrameRingBuffer& input_buffer,
                       const std::shared_ptr<timing::MasterClock>& clock,
                       const std::shared_ptr<telemetry::MetricsExporter>& metrics,
                       int32_t channel_id);
  ~PreviewProgramOutput() override;

 protected:
  bool Initialize() override;
  void RenderFrame(const buffer::Frame& frame) override;
  void Cleanup() override;

 private:
  // SDL2/OpenGL context (opaque pointers)
  void* window_;       // SDL_Window*
  void* sdl_renderer_;  // SDL_Renderer*
  void* texture_;      // SDL_Texture*
};

}  // namespace retrovue::renderer

#endif  // RETROVUE_RENDERER_PROGRAM_OUTPUT_H_
