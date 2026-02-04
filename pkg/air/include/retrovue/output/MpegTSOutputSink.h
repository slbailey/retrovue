// Repository: Retrovue-playout
// Component: MpegTSOutputSink
// Purpose: Concrete output sink that encodes frames to MPEG-TS over UDS/TCP.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_OUTPUT_MPEGTS_OUTPUT_SINK_H_
#define RETROVUE_OUTPUT_MPEGTS_OUTPUT_SINK_H_

#include <atomic>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>

#include <functional>

#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/SocketSink.h"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

namespace retrovue::telemetry {
class MetricsExporter;
}  // namespace retrovue::telemetry

namespace retrovue::buffer {
struct Frame;
struct AudioFrame;
}  // namespace retrovue::buffer

namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
}  // namespace retrovue::playout_sinks::mpegts

namespace retrovue::output {

// MpegTSOutputSink encodes video and audio frames to MPEG-TS.
//
// This is a concrete implementation of IOutputSink that:
// - Owns an EncoderPipeline for encoding/muxing
// - Owns frame queues for video and audio
// - Runs a MuxLoop thread that drains queues and encodes
// - Writes encoded TS packets to a file descriptor (UDS/TCP)
//
// Thread model:
// - ConsumeVideo/ConsumeAudio called from render thread (enqueue)
// - MuxLoop runs in dedicated worker thread (dequeue + encode)
// - Start/Stop called from control thread
class MpegTSOutputSink : public IOutputSink {
 public:
  // Constructs sink with a connected file descriptor and encoding config.
  // fd: Connected socket (UDS or TCP). Sink does NOT own the fd; caller must manage.
  // config: Encoding configuration (fps, resolution, bitrate, etc.)
  // name: Human-readable name for logging (e.g., "channel-1-mpeg-ts")
  MpegTSOutputSink(int fd,
                   const playout_sinks::mpegts::MpegTSPlayoutSinkConfig& config,
                   const std::string& name = "MpegTSOutputSink");

  ~MpegTSOutputSink() override;

  // Disable copy and move
  MpegTSOutputSink(const MpegTSOutputSink&) = delete;
  MpegTSOutputSink& operator=(const MpegTSOutputSink&) = delete;

  // IOutputSink interface
  bool Start() override;
  void Stop() override;
  bool IsRunning() const override;
  SinkStatus GetStatus() const override;
  void ConsumeVideo(const buffer::Frame& frame) override;
  void ConsumeAudio(const buffer::AudioFrame& audio_frame) override;
  void SetStatusCallback(SinkStatusCallback callback) override;
  std::string GetName() const override;

  // INV-SWITCH-SUCCESSOR-EMISSION: Callback invoked once per real (non-pad)
  // video frame encoded. Used to gate segment commit and switch completion.
  using OnSuccessorVideoEmittedCallback = std::function<void()>;
  void SetOnSuccessorVideoEmitted(OnSuccessorVideoEmittedCallback callback);

  // P9-OPT-002: Set metrics exporter for steady-state telemetry
  void SetMetricsExporter(std::shared_ptr<telemetry::MetricsExporter> metrics, int32_t channel_id);

 private:
  // Main mux loop (runs in worker thread).
  // Drains frame queues and encodes to MPEG-TS.
  void MuxLoop();

  // Enqueue/dequeue helpers (thread-safe)
  void EnqueueVideoFrame(const buffer::Frame& frame);
  void EnqueueAudioFrame(const buffer::AudioFrame& audio_frame);
  bool DequeueVideoFrame(buffer::Frame* out);
  bool DequeueAudioFrame(buffer::AudioFrame* out);

  // Write callback for EncoderPipeline (C-style for FFmpeg AVIO)
  static int WriteToFdCallback(void* opaque, uint8_t* buf, int buf_size);

  // Update status and invoke callback
  void SetStatus(SinkStatus status, const std::string& message = "");

  // Configuration
  int fd_;  // Not owned
  playout_sinks::mpegts::MpegTSPlayoutSinkConfig config_;
  std::string name_;

  // Status
  std::atomic<SinkStatus> status_;
  mutable std::mutex status_mutex_;
  SinkStatusCallback status_callback_;

  // Encoder pipeline (owns FFmpeg encoder/muxer)
  std::unique_ptr<playout_sinks::mpegts::EncoderPipeline> encoder_;

  // Socket transport (non-blocking byte consumer)
  std::unique_ptr<SocketSink> socket_sink_;

  // Frame queues (renderer thread enqueues, MuxLoop dequeues)
  mutable std::mutex video_queue_mutex_;
  std::queue<buffer::Frame> video_queue_;
  static constexpr size_t kMaxVideoQueueSize = 30;

  mutable std::mutex audio_queue_mutex_;
  std::queue<buffer::AudioFrame> audio_queue_;
  static constexpr size_t kMaxAudioQueueSize = 30;

  // Worker thread
  std::atomic<bool> stop_requested_;
  std::thread mux_thread_;

  // =========================================================================
  // DEBUG INSTRUMENTATION - remove after diagnosis
  // =========================================================================
  std::atomic<uint64_t> dbg_bytes_written_{0};
  std::atomic<uint64_t> dbg_packets_written_{0};
  std::atomic<uint64_t> dbg_video_frames_enqueued_{0};
  std::atomic<uint64_t> dbg_audio_frames_enqueued_{0};
  std::chrono::steady_clock::time_point dbg_last_write_time_;
  std::chrono::steady_clock::time_point dbg_output_heartbeat_time_;
  std::chrono::steady_clock::time_point dbg_enqueue_heartbeat_time_;

  // INV-SWITCH-SUCCESSOR-EMISSION: Called when a real video frame is encoded
  OnSuccessorVideoEmittedCallback on_successor_video_emitted_;

  // =========================================================================
  // INV-P9-STEADY-001: Steady-state entry detection
  // =========================================================================
  // Steady-state is entered when: sink attached AND buffer depth >= 1 AND
  // timing epoch established. Once entered, output owns pacing authority.
  //
  // These flags are detection scaffolding for Phase 9 contracts. They do NOT
  // change behavior in this task (P9-CORE-001); behavior changes come later.
  // =========================================================================
  std::atomic<bool> steady_state_entered_{false};
  std::atomic<bool> pcr_paced_active_{false};
  static constexpr size_t kSteadyStateMinDepth = 1;

 public:
  // INV-P9-STEADY-001: Test hook - check if steady-state has been entered
  bool IsSteadyStateEntered() const {
    return steady_state_entered_.load(std::memory_order_acquire);
  }

  // INV-P9-STEADY-001: Test hook - check if PCR pacing is active
  bool IsPcrPacedActive() const {
    return pcr_paced_active_.load(std::memory_order_acquire);
  }

  // INV-P9-STEADY-008: Test hook - check if silence injection is disabled
  bool IsSilenceInjectionDisabled() const {
    return silence_injection_disabled_.load(std::memory_order_acquire);
  }

 private:
  // =========================================================================
  // INV-P9-STEADY-008: No Silence Injection After Attach
  // =========================================================================
  // When steady-state begins, silence injection MUST be disabled.
  // Producer audio is the ONLY audio source.
  // When audio queue is empty, mux MUST stall (video waits with audio).
  // =========================================================================
  std::atomic<bool> silence_injection_disabled_{false};

  // =========================================================================
  // P9-OPT-002: Steady-state metrics
  // =========================================================================
  std::shared_ptr<telemetry::MetricsExporter> metrics_exporter_;
  int32_t channel_id_{0};
};

}  // namespace retrovue::output

#endif  // RETROVUE_OUTPUT_MPEGTS_OUTPUT_SINK_H_
