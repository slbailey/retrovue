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

  // ORCH-SWITCH-SUCCESSOR-OBSERVED: Callback invoked once per real (non-pad)
  // video frame encoded. Used to gate segment commit and switch completion.
  using OnSuccessorVideoEmittedCallback = std::function<void()>;
  void SetOnSuccessorVideoEmitted(OnSuccessorVideoEmittedCallback callback);

  // P9-OPT-002: Set metrics exporter for steady-state telemetry
  void SetMetricsExporter(std::shared_ptr<telemetry::MetricsExporter> metrics, int32_t channel_id);

  // =========================================================================
  // Forensic TS Tap (runtime toggle)
  // =========================================================================
  // Enable: mirrors all TS bytes to file (non-blocking, passive)
  // Disable: closes file, stops mirroring
  // Safe to call at any time after construction.
  // =========================================================================
  void EnableForensicDump(const std::string& path);
  void DisableForensicDump();
  bool IsForensicDumpEnabled() const { return forensic_enabled_.load(std::memory_order_acquire); }

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
  std::atomic<uint64_t> dbg_bytes_enqueued_{0};     // Bytes enqueued to SocketSink buffer
  std::atomic<uint64_t> dbg_bytes_dropped_{0};      // Bytes dropped (sink closed/detached)
  std::atomic<uint64_t> dbg_packets_written_{0};
  std::atomic<uint64_t> dbg_video_frames_enqueued_{0};
  std::atomic<uint64_t> dbg_audio_frames_enqueued_{0};
  // LAW-OUTPUT-LIVENESS: Liveness detector MUST query SocketSink::GetLastAcceptedTime()
  // dbg_last_attempt_time_ is when FFmpeg callback was invoked (diagnostic only)
  std::chrono::steady_clock::time_point dbg_last_attempt_time_;  // Callback invoked
  std::chrono::steady_clock::time_point dbg_output_heartbeat_time_;
  std::chrono::steady_clock::time_point dbg_enqueue_heartbeat_time_;

  // =========================================================================
  // INV-P10-FRAME-DROP-POLICY: Overflow drop tracking
  // =========================================================================
  // These drops are CONTRACT VIOLATIONS - sink overflow should not be routine.
  // Correct behavior: backpressure propagates upstream to throttle decode.
  // These counters exist to make violations visible, not to normalize them.
  // =========================================================================
  std::atomic<uint64_t> video_frames_dropped_{0};
  std::atomic<uint64_t> audio_frames_dropped_{0};

  // =========================================================================
  // INV-FALLBACK-001: Upstream starvation detection
  // =========================================================================
  // Fallback mode ONLY triggers after confirmed upstream starvation.
  // last_real_frame_dequeue_time_: Updated ONLY when real frame is dequeued.
  // kFallbackGraceWindowUs: Must elapse with empty queue before fallback.
  // =========================================================================
  std::chrono::steady_clock::time_point last_real_frame_dequeue_time_;
  static constexpr int64_t kFallbackGraceWindowUs = 100'000;  // 100ms = ~3 frames at 30fps

  // =========================================================================
  // INV-LIVENESS-SEPARATION: Separate upstream and downstream clocks
  // =========================================================================
  // Upstream frame clock: tracks when real frames are dequeued from producer
  // Downstream delivery clock: tracks when bytes reach kernel socket buffer
  //
  // CRITICAL: These are INDEPENDENT failure modes:
  // - Upstream starvation (no frames) MAY trigger fallback
  // - Downstream stall (consumer not draining) MUST NOT trigger fallback
  // =========================================================================
  static constexpr int64_t kDownstreamStallThresholdMs = 500;  // Log stall after 500ms
  static constexpr int64_t kUpstreamStarvationThresholdMs = 100;  // Same as grace window

  // =========================================================================
  // INV-LATE-FRAME-THRESHOLD: Ignore sub-millisecond "lateness"
  // =========================================================================
  // A frame arriving 100us "late" is effectively on-time due to scheduling jitter.
  // Only count as late if > threshold, to avoid misleading warnings.
  // =========================================================================
  static constexpr int64_t kLateFrameThresholdUs = 2'000;  // 2ms threshold

  // =========================================================================
  // INV-BOOT-FAST-EMIT: Bypass pacing during boot window
  // =========================================================================
  // For fast channel join, emit TS packets as fast as possible for the first
  // N milliseconds after sink attach. This ensures PAT/PMT and initial frames
  // reach the consumer immediately. Pacing only kicks in after boot window.
  // =========================================================================
  static constexpr int64_t kBootFastEmitWindowMs = 250;  // 250ms boot window
  std::atomic<bool> boot_fast_emit_active_{true};  // Starts active, cleared after window

  // ORCH-SWITCH-SUCCESSOR-OBSERVED: Called when a real video frame is encoded
  OnSuccessorVideoEmittedCallback on_successor_video_emitted_;

  // =========================================================================
  // Forensic TS Tap (runtime-enabled, passive, non-blocking)
  // =========================================================================
  // Mirrors bytes after mux, before socket. Never blocks. Can be enabled
  // at runtime after sink exists. Does not alter flow control.
  // =========================================================================
  std::atomic<bool> forensic_enabled_{false};
  int forensic_fd_ = -1;

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
  // When audio queue is empty, transport continues (LAW-OUTPUT-LIVENESS).
  // Video proceeds alone; A/V sync is a content-plane concern.
  // =========================================================================
  std::atomic<bool> silence_injection_disabled_{false};

  // =========================================================================
  // P9-OPT-002: Steady-state metrics
  // =========================================================================
  std::shared_ptr<telemetry::MetricsExporter> metrics_exporter_;
  int32_t channel_id_{0};

  // =========================================================================
  // INV-TS-CONTINUITY: Null packet emission for transport continuity
  // =========================================================================
  // Broadcast-grade TS streams emit null packets (PID 0x1FFF) during gaps.
  // This guarantees:
  //   - No EOF detection by consumers (continuous byte flow)
  //   - No VLC re-probe (TS sync maintained)
  //   - No false slow-consumer detach (buffer never appears stagnant)
  // =========================================================================
  static constexpr size_t kTsPacketSize = 188;
  static constexpr size_t kNullPacketClusterSize = 7;  // Match AVIO buffer
  uint8_t null_packet_cluster_[kTsPacketSize * kNullPacketClusterSize];
  bool null_packets_initialized_ = false;
  std::atomic<uint64_t> null_packets_emitted_{0};

  // Track last time TS bytes were actually written (for null packet injection)
  std::atomic<int64_t> last_ts_write_time_us_{0};
  static constexpr int64_t kNullPacketIntervalUs = 50'000;  // 50ms max gap

  // Initialize null packet buffer (called once at start)
  void InitNullPackets();
  // Emit null packets to maintain transport continuity
  void EmitNullPackets();
  // Update last TS write timestamp (called from AVIO callback)
  void MarkTsWritten();
  // Check if null packets needed based on time since last TS
  void EmitNullPacketsIfNeeded();
};

}  // namespace retrovue::output

#endif  // RETROVUE_OUTPUT_MPEGTS_OUTPUT_SINK_H_
