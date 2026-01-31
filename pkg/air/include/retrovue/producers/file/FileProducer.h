// Repository: Retrovue-playout
// Component: File Producer
// Purpose: Decodes local video/audio files and produces frames for the ring buffer.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PRODUCERS_FILE_FILE_PRODUCER_H_
#define RETROVUE_PRODUCERS_FILE_FILE_PRODUCER_H_

#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"
#include "retrovue/runtime/AspectPolicy.h"

namespace retrovue::timing
{
  class MasterClock;
  class TimelineController;
}

// Forward declarations for FFmpeg types (opaque pointers)
struct AVFormatContext;
struct AVCodecContext;
struct AVFrame;
struct AVPacket;
struct SwsContext;

namespace retrovue::producers::file
{

  // Producer state machine
  enum class ProducerState
  {
    STOPPED,
    STARTING,
    RUNNING,
    STOPPING
  };

  // ProducerConfig holds configuration for file producer (Phase 6A.2 segment params).
  struct ProducerConfig
  {
    std::string asset_uri;       // URI or path to video file
    int target_width;            // Target frame width (e.g., 1920)
    int target_height;           // Target frame height (e.g., 1080)
    double target_fps;           // Target frames per second (e.g., 30.0)
    bool stub_mode;              // If true, generate fake frames instead of decoding
    int tcp_port;                // TCP port for FFmpeg streaming (stub mode)
    int64_t start_offset_ms;     // Phase 8.2: media time (ms); first emitted frame has pts_ms >= this
    int64_t hard_stop_time_ms;   // Phase 8.2: wall-clock epoch ms; stop when MasterClock.now_utc_ms() >= this

    ProducerConfig()
        : target_width(1920),
          target_height(1080),
          target_fps(30.0),
          stub_mode(false),
          tcp_port(12345),
          start_offset_ms(0),
          hard_stop_time_ms(0) {}
  };

  // Event callback for producer events (for test harness)
  using ProducerEventCallback = std::function<void(const std::string &event_type, const std::string &message)>;

  // FileProducer is a self-contained decoder that reads video/audio files,
  // decodes them internally using FFmpeg, and produces decoded YUV420 frames and PCM audio.
  //
  // Responsibilities:
  // - Read video files (MP4, MKV, MOV, etc.)
  // - Decode frames internally using libavformat/libavcodec
  // - Scale frames to target resolution
  // - Convert to YUV420 planar format
  // - Push decoded frames to FrameRingBuffer
  // - Handle backpressure and errors gracefully
  //
  // Architecture:
  // - Self-contained: performs both reading and decoding internally
  // - Outputs only decoded frames (never encoded packets)
  // - Internal decoder subsystem: demuxer, decoder, scaler, frame assembly
  class FileProducer : public retrovue::producers::IProducer
  {
  public:
    // Constructs a producer with the given configuration and output buffer.
    // Phase 8: Optional TimelineController for CT assignment. If provided,
    // the producer emits raw MT and TimelineController assigns CT.
    // If nullptr, legacy behavior (producer computes PTS offset internally).
    FileProducer(
        const ProducerConfig &config,
        buffer::FrameRingBuffer &output_buffer,
        std::shared_ptr<timing::MasterClock> clock = nullptr,
        ProducerEventCallback event_callback = nullptr,
        timing::TimelineController* timeline_controller = nullptr);

    ~FileProducer();

    // Disable copy and move
    FileProducer(const FileProducer &) = delete;
    FileProducer &operator=(const FileProducer &) = delete;

    // IProducer interface
    bool start() override;
    void stop() override;
    bool isRunning() const override;

    // Initiates graceful teardown with bounded drain timeout.
    void RequestTeardown(std::chrono::milliseconds drain_timeout);

    // Forces immediate stop (used when teardown times out).
    void ForceStop();

    // Phase 8: Sets write barrier without stopping the producer.
    // Used when switching segments - old producer can decode but not write.
    void SetWriteBarrier();

    // Returns the total number of decoded frames produced.
    uint64_t GetFramesProduced() const;

    // Returns the number of times the buffer was full (backpressure events).
    uint64_t GetBufferFullCount() const;

    // Returns the number of decode errors encountered.
    uint64_t GetDecodeErrors() const;

    // Returns current producer state.
    ProducerState GetState() const;

    // Shadow decode mode support (for seamless switching)
    // Sets shadow decode mode (decodes frames but does not write to buffer).
    void SetShadowDecodeMode(bool enabled);

    // Returns true if shadow decode mode is enabled.
    bool IsShadowDecodeMode() const;

    // Returns true if shadow decode is ready (first frame decoded and cached).
    bool IsShadowDecodeReady() const;

    // INV-P8-SHADOW-FLUSH: Flush cached shadow frame to buffer immediately.
    // Called by PlayoutEngine after SetShadowDecodeMode(false) to ensure
    // the buffer has frames for readiness check without race condition.
    // Returns true if a frame was flushed, false if no cached frame exists.
    bool FlushCachedFrameToBuffer();

    // Gets the next PTS that will be used for the next frame (for PTS alignment).
    // Returns the PTS that the next decoded frame will have.
    int64_t GetNextPTS() const;

    // Aligns PTS to continue from a target PTS (for seamless switching).
    // Sets the PTS offset so that the next frame will have target_pts.
    // Idempotent: only aligns once, subsequent calls are no-ops.
    void AlignPTS(int64_t target_pts);

    // Returns true if PTS has been aligned (AlignPTS was called).
    bool IsPTSAligned() const;

    // Phase 8: Returns true if the producer has reached end-of-file.
    // Used by INV-P8-EOF-SWITCH to detect when live producer is exhausted.
    bool IsEOF() const;

  private:
    // Main production loop (runs in producer thread).
    void ProduceLoop();

    // Stub implementation: generates synthetic decoded frames (for testing).
    void ProduceStubFrame();

    // Real decode implementation: reads, decodes, scales, and assembles frames.
    bool ProduceRealFrame();

    // Internal decoder subsystem initialization.
    bool InitializeDecoder();
    void CloseDecoder();

    // Internal decoder operations.
    bool ReadPacket();
    bool DecodePacket();
    bool ScaleFrame();
    bool AssembleFrame(buffer::Frame& frame);

    // Phase 8.9: Audio decoding operations.
    bool ReceiveAudioFrames();  // Receive decoded audio frames (packets dispatched by ProduceRealFrame)
    bool ConvertAudioFrame(AVFrame* av_frame, buffer::AudioFrame& output_frame);

    // Emits producer event through callback.
    void EmitEvent(const std::string &event_type, const std::string &message = "");

    // Transitions state (thread-safe).
    void SetState(ProducerState new_state);

    ProducerConfig config_;
    buffer::FrameRingBuffer &output_buffer_;
    std::shared_ptr<timing::MasterClock> master_clock_;
    timing::TimelineController* timeline_controller_;  // Phase 8: optional, for CT assignment
    ProducerEventCallback event_callback_;

    std::atomic<ProducerState> state_;
    std::atomic<bool> stop_requested_;
    std::atomic<bool> teardown_requested_;
    std::atomic<bool> writes_disabled_;  // Phase 7: Hard write barrier for ForceStop
    std::atomic<uint64_t> frames_produced_;
    std::atomic<uint64_t> buffer_full_count_;
    std::atomic<uint64_t> decode_errors_;
    std::chrono::steady_clock::time_point teardown_deadline_;
    std::chrono::milliseconds drain_timeout_;

    std::unique_ptr<std::thread> producer_thread_;

    // Internal decoder subsystem (FFmpeg)
    AVFormatContext* format_ctx_;
    AVCodecContext* codec_ctx_;
    AVFrame* frame_;
    AVFrame* scaled_frame_;
    AVFrame* intermediate_frame_;  // For aspect-preserving scale (if different from target)
    AVPacket* packet_;
    SwsContext* sws_ctx_;
    int video_stream_index_;
    bool decoder_initialized_;
    
    // Aspect ratio handling
    runtime::AspectPolicy aspect_policy_;
    int scale_width_;   // Actual scale dimensions (may differ from target for aspect preserve)
    int scale_height_;
    int pad_x_;         // Padding offset for centered content
    int pad_y_;
    bool eof_reached_;
    bool eof_event_emitted_;  // Phase 8.8: emit "eof" only once; producer stays running until explicit stop
    double time_base_;  // Stream time base for PTS/DTS conversion
    // MT-DOMAIN ONLY: These variables must NEVER hold CT values.
    // MT = Media Time (raw decoder PTS, typically 0 to media duration)
    // CT = Channel Time (timeline-mapped, can be hours into channel playback)
    int64_t last_mt_pts_us_;  // For PTS monotonicity enforcement (MT ONLY!)
    int64_t last_decoded_mt_pts_us_;  // PTS of last decoded frame (MT ONLY!)
    int64_t first_mt_pts_us_;  // PTS of first frame for time mapping (MT ONLY!)
    int64_t playback_start_utc_us_;  // UTC time when first frame was decoded (for pacing)

    // Phase 8.9: Audio decoder subsystem
    AVCodecContext* audio_codec_ctx_;
    AVFrame* audio_frame_;
    int audio_stream_index_;
    double audio_time_base_;  // Audio stream time base for PTS conversion
    bool audio_eof_reached_;
    int64_t last_audio_pts_us_;  // Last audio frame PTS (for monotonicity)

    // Phase 8.2: derived segment end (media PTS in us). -1 = not set. Set when segment goes live.
    int64_t segment_end_pts_us_;

    // Phase 6 (INV-P6-008): Effective seek target in media time (after modulo for looping content)
    // This is the actual PTS threshold for frame admission, not the raw start_offset_ms
    int64_t effective_seek_target_us_;

    // State for stub frame generation
    std::atomic<int64_t> stub_pts_counter_;
    int64_t frame_interval_us_;
    std::atomic<int64_t> next_stub_deadline_utc_;

    // Shadow decode mode support
    std::atomic<bool> shadow_decode_mode_;
    std::atomic<bool> shadow_decode_ready_;
    std::atomic<bool> cached_frame_flushed_;  // INV-P8-SHADOW-FLUSH: true if FlushCachedFrameToBuffer() already pushed
    std::mutex shadow_decode_mutex_;
    std::unique_ptr<buffer::Frame> cached_first_frame_;  // First decoded frame (cached in shadow mode)
    int64_t pts_offset_us_;  // PTS offset for alignment (added to frame PTS)
    std::atomic<bool> pts_aligned_;  // Phase 7: True after AlignPTS called (idempotent guard)

    // Per-instance diagnostic counters (NOT static - must reset on new producer)
    // These track progress within a single producer's lifetime
    int video_frame_count_;       // Total video frames decoded
    int video_discard_count_;     // Video frames discarded before seek target
    int audio_frame_count_;       // Total audio frames processed
    int frames_since_producer_start_;  // Frames since this producer started
    int audio_skip_count_;        // Audio frames skipped waiting for video epoch
    int audio_drop_count_;        // Audio frames dropped due to buffer full
    int audio_mapping_gate_drop_count_;  // Phase 8: Audio dropped while segment mapping pending
    bool audio_ungated_logged_;   // Whether we've logged audio ungating (one-shot)
    int scale_diag_count_;        // Scale diagnostic log counter

    // INV-P8-AUDIO-GATE Fix #2: Track if mapping locked this iteration.
    // When video AdmitFrame() locks the mapping, audio on the same iteration
    // MUST be processed ungated. This flag overrides the shadow gating check.
    bool mapping_locked_this_iteration_;

    // RULE-P10-DECODE-GATE: Count of decode-gate blocking episodes for metrics
    int decode_gate_block_count_;

    // INV-P10-ELASTIC-FLOW-CONTROL: Hysteresis state for elastic gating
    // When true, we're in a blocking episode and must wait for low-water mark
    bool decode_gate_blocked_;

    // ==========================================================================
    // INV-P10-BACKPRESSURE-SYMMETRIC: Unified A/V gating
    // ==========================================================================
    // Audio and video must be gated together. When EITHER buffer is full or
    // write barrier is set, BOTH streams wait. No retries, no dropping.
    // ==========================================================================

    // Returns true if both audio and video can safely push.
    bool CanPushAV() const;

    // Blocks until CanPushAV() returns true or stop is requested.
    // Returns true if ready to push, false if stop was requested.
    bool WaitForAVPushReady();

    // Blocks BEFORE av_read_frame() until both buffers have space.
    // INV-P10-BACKPRESSURE-SYMMETRIC: Gate at decode level, not push level.
    bool WaitForDecodeReady();
  };

} // namespace retrovue::producers::file

#endif // RETROVUE_PRODUCERS_FILE_FILE_PRODUCER_H_
