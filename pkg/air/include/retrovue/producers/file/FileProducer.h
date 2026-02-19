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

// Forward declarations for FFmpeg types (opaque pointers, global scope)
struct AVFormatContext;
struct AVCodecContext;
struct AVFrame;
struct AVPacket;
struct SwsContext;
struct SwrContext;

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
  // INV-FRAME-001: Segment boundaries are frame-indexed, not time-derived.
  struct ProducerConfig
  {
    std::string asset_uri;       // URI or path to video file
    int target_width;            // Target frame width (e.g., 1920)
    int target_height;           // Target frame height (e.g., 1080)
    double target_fps;           // Target frames per second (e.g., 30.0)
    bool stub_mode;              // If true, generate fake frames instead of decoding
    int tcp_port;                // TCP port for FFmpeg streaming (stub mode)

    // Frame-indexed execution (INV-P10-FRAME-INDEXED-EXECUTION)
    int64_t start_frame;         // First frame index within asset to decode
    int64_t frame_count;         // Exact number of frames to produce (-1 = until EOF)

    // Legacy time-based fields (deprecated, for backward compatibility)
    int64_t start_offset_ms;     // Deprecated: use start_frame instead
    int64_t hard_stop_time_ms;   // Deprecated: use frame_count instead

    // INV-FPS-RESAMPLE: Override source fps for testing (0 = auto-detect from file)
    double stub_source_fps = 0.0;

    ProducerConfig()
        : target_width(1920),
          target_height(1080),
          target_fps(30.0),
          stub_mode(false),
          tcp_port(12345),
          start_frame(0),
          frame_count(-1),       // -1 means until EOF (legacy behavior)
          start_offset_ms(0),
          hard_stop_time_ms(0) {}
  };

  // Event callback for producer events (for test harness)
  using ProducerEventCallback = std::function<void(const std::string &event_type, const std::string &message)>;

  // P8-EOF-001: Callback when live producer reaches decoder EOF (segment_id, ct_at_eof_us, frames_delivered).
  // PlayoutEngine uses this for content deficit detection; EOF does NOT advance boundary.
  using LiveProducerEOFCallback = std::function<void(const std::string& segment_id, int64_t ct_at_eof_us, int64_t frames_delivered)>;

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
  // INV-FPS-RESAMPLE: Frame-rate mismatch tolerance.
  // Treat source and target fps within ±1% as "same rate" to avoid unnecessary
  // resampling for 29.97 vs 30, probe noise, or container metadata rounding.
  // If a known use case requires tighter or looser matching, make this a
  // ProducerConfig field; do not add per-case heuristics.
  constexpr double kFpsMatchToleranceRatio = 0.01;

  // INV-FPS-RESAMPLE: Resampler gate result
  enum class ResampleGateResult {
    HOLD,  // Frame absorbed — caller should continue decoding, do NOT emit
    EMIT,  // output_frame updated with tick-stamped frame — caller should emit
    PASS   // Resampler inactive — emit frame as-is
  };

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
    void RequestStop() override;
    bool IsStopped() const override;

    // Initiates graceful teardown with bounded drain timeout.
    void RequestTeardown(std::chrono::milliseconds drain_timeout);

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

    // INV-P8-ZERO-FRAME-READY: Returns configured frame count.
    // Used to detect zero-frame segments for bootstrap frame handling.
    int64_t GetConfiguredFrameCount() const { return config_.frame_count; }

    // P8-PLAN-001 INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001: Planning authority and delivered count for deficit detection.
    int64_t GetPlannedFrameCount() const { return planned_frame_count_; }
    int64_t GetFramesDelivered() const { return frames_delivered_.load(std::memory_order_acquire); }

    // P8-EOF-001: Set callback for decoder EOF (segment_id, ct_at_eof_us, frames_delivered). Idempotent signal.
    void SetLiveProducerEOFCallback(LiveProducerEOFCallback callback);

    // Contract-level observability: as-run stats for AIR_AS_RUN_FRAME_RANGE.
    std::optional<AsRunFrameStats> GetAsRunFrameStats() const override;

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
    std::atomic<bool> writes_disabled_;  // Phase 7: Hard write barrier for RequestStop
    std::atomic<uint64_t> frames_produced_;
    // P8-PLAN-001 INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001: planning authority from Core; deficit detection
    int64_t planned_frame_count_ = -1;           // Set from config at start; -1 = until EOF
    std::atomic<int64_t> frames_delivered_{0};  // Frames delivered to buffer (for early EOF detection)
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
    bool eof_signaled_;       // P8-EOF-001: DECODER_EOF signaled to PlayoutEngine only once per segment
    bool truncation_logged_;  // P8-PLAN-003: log CONTENT_TRUNCATED only once per segment
    LiveProducerEOFCallback live_producer_eof_callback_;
    double time_base_;  // Stream time base for PTS/DTS conversion
    // MT-DOMAIN ONLY: These variables must NEVER hold CT values.
    // MT = Media Time (raw decoder PTS, typically 0 to media duration)
    // CT = Channel Time (timeline-mapped, can be hours into channel playback)
    int64_t last_mt_pts_us_;  // For PTS monotonicity enforcement (MT ONLY!)
    int64_t last_decoded_mt_pts_us_;  // PTS of last decoded frame (MT ONLY!)
    int64_t first_mt_pts_us_;  // PTS of first frame for time mapping (MT ONLY!)
    bool video_epoch_set_ = false;  // True once VIDEO_EPOCH_SET has fired (replaces first_mt_pts_us_==0 sentinel)
    int64_t playback_start_utc_us_;  // UTC time when first frame was decoded (for pacing)

    // Phase 8.9: Audio decoder subsystem
    AVCodecContext* audio_codec_ctx_;
    AVFrame* audio_frame_;
    int audio_stream_index_;
    double audio_time_base_;  // Audio stream time base for PTS conversion
    bool audio_eof_reached_;
    int64_t last_audio_pts_us_;  // Last audio frame PTS (for monotonicity)

    // INV-P10.5-HOUSE-AUDIO-FORMAT: Resampler for converting to house format
    // All audio MUST be resampled to house format (48kHz, 2ch, S16) before output.
    // EncoderPipeline never negotiates format - it assumes correctness.
    // FFmpeg type kept unambiguous: global ::SwrContext* (see PlayoutInvariants / broadcast-grade fix).
    ::SwrContext* audio_swr_ctx_;
    int audio_swr_src_rate_;      // Source sample rate for current swr context
    int audio_swr_src_channels_;  // Source channels for current swr context
    int audio_swr_src_fmt_;       // Source sample format (AVSampleFormat) for current swr context

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
    bool seek_discard_logged_;    // INV-SEEK-DISCARD: Log once at start of discard phase
    int audio_frame_count_;       // Total audio frames processed
    int frames_since_producer_start_;  // Frames since this producer started
    int audio_skip_count_;        // Audio frames skipped waiting for video epoch
    int audio_drop_count_;
    int debug_mt_delta_count_ = 0;  // Ricola-only: first 10 MT deltas (diagnostic)
    // ======================================================================
    // INV-FPS-RESAMPLE: PTS-driven output tick resampling (frame synchronizer)
    // ======================================================================
    // House rate tick grid is authoritative. For each output tick (1/target_fps),
    // we select the latest decoded frame with PTS <= tick boundary.
    // Fast sources (60->30): intermediate frames skipped naturally.
    // Slow sources (23.976->30): last frame repeated on empty ticks.
    // VFR/non-standard: handled uniformly via PTS comparison.
    // ======================================================================
    double source_fps_ = 0.0;                          // Detected source frame rate
    int64_t output_tick_interval_us_ = 0;              // Target frame period in us
    int64_t next_output_tick_us_ = -1;                 // Next tick boundary in MT domain
    bool resample_active_ = false;                     // True when source fps != target fps
    buffer::Frame held_frame_storage_;                  // Held candidate for current tick
    bool held_frame_valid_ = false;

    // Resampler gate: processes a decoded frame through the tick grid.
    // Called from both ProduceRealFrame and ProduceStubFrame.
    ResampleGateResult ResampleGate(buffer::Frame& output_frame, int64_t& base_pts_us);

    // Resampler emit helper: stamps PTS to tick grid, handles VIDEO_EPOCH_SET,
    // pacing, and push. This is the ONLY place resampler-emitted frames touch
    // the output buffer. Enforces single-emit-per-tick mechanically.
    // Returns true if frame was pushed, false if stopped/truncated.
    bool EmitFrameAtTick(buffer::Frame& frame, int64_t tick_pts_us);

    // Drain any pending decoded audio frames from the audio codec.
    // Called after video frame emission in both resampled and non-resampled paths
    // to maintain A/V interleaving. Audio packet dispatch (demux-level) happens
    // in the av_read_frame loop; this drains the decoder's output queue.
    void DrainAudioDecoderIfNeeded();

    // Pending frame promotion: called at top of produce loop.
    // Returns true if a repeat frame was emitted (caller should skip decode).
    bool ResamplePromotePending(buffer::Frame& output_frame, int64_t& base_pts_us);                    // Whether held_frame_storage_ has content
    int64_t held_frame_mt_us_ = -1;                    // MT PTS of held frame
    uint64_t resample_frames_decoded_ = 0;             // Source frames decoded (resampler scope)
    uint64_t resample_frames_emitted_ = 0;
    // Pending frame: decoded frame saved when it crossed a tick boundary
    // and the held frame needs repeat emission for intermediate ticks
    buffer::Frame pending_frame_storage_;
    bool pending_frame_valid_ = false;
    int64_t pending_frame_mt_us_ = -1;

    // Consecutive repeat emission counter (for freeze-frame diagnostics).
    // Incremented when ResamplePromotePending emits a repeat; reset when
    // a non-repeat frame is emitted via ResampleGate or pending is promoted.
    uint64_t consecutive_repeat_emits_ = 0;
    static constexpr uint64_t kRepeatLogThreshold = 30;  // Log every N consecutive repeats
             // Output frames emitted
        // Audio frames dropped due to buffer full
    int audio_mapping_gate_drop_count_;  // Phase 8: Audio dropped while segment mapping pending
    bool audio_ungated_logged_;   // Whether we've logged audio ungating (one-shot)

    // INV-P8-AUDIO-GATE Fix #2: Track if mapping locked this iteration.
    // When video AdmitFrame() locks the mapping, audio on the same iteration
    // MUST be processed ungated. This flag overrides the shadow gating check.
    bool mapping_locked_this_iteration_;

    // RULE-P10-DECODE-GATE: Count of decode-gate blocking episodes for metrics
    int decode_gate_block_count_;

    // INV-P10-SLOT-BASED-UNBLOCK: Track blocking state for slot-based gating
    // When true, we're blocked at capacity waiting for one slot to free
    bool decode_gate_blocked_;

    // ==========================================================================
    // INV-P9-STEADY-003: Symmetric A/V backpressure tracking
    // ==========================================================================
    // Counters track frames emitted to enforce A/V delta <= 1 frame.
    // Audio MUST NOT run more than 1 frame ahead of video.
    // When audio_count > video_count + 1, audio push must wait.
    // ==========================================================================
    std::atomic<int64_t> steady_state_video_count_{0};
    std::atomic<int64_t> steady_state_audio_count_{0};
    bool av_delta_violation_logged_ = false;

    // ==========================================================================
    // INV-DECODE-RATE-001: Diagnostic probe state for decode rate monitoring
    // ==========================================================================
    // Tracks decode rate to detect when producer falls behind real-time.
    // Violation: decode rate < target_fps during steady state (not seek/startup).
    // See: docs/contracts/semantics/PrimitiveInvariants.md
    // ==========================================================================
    int64_t decode_probe_window_start_us_ = 0;     // Start of current measurement window
    uint64_t decode_probe_window_frames_ = 0;      // Frames decoded in current window
    double decode_probe_last_rate_ = 0.0;          // Last measured decode rate (fps)
    bool decode_probe_in_seek_ = false;            // True while discarding to seek target
    bool decode_rate_violation_logged_ = false;    // Log violation once per episode
    static constexpr int64_t kDecodeProbeWindowUs = 1'000'000;  // 1-second window

    // ==========================================================================
    // HYPOTHESIS TEST T3: Audio vs video packet rate tracking
    // ==========================================================================
    // Tracks packets processed to detect when audio decodes faster than video.
    // H1 predicts: audio_packets_processed >> video_packets_processed
    // ==========================================================================
    uint64_t audio_packets_processed_ = 0;         // Total audio packets decoded
    uint64_t video_packets_processed_ = 0;         // Total video packets decoded
    int64_t av_rate_probe_start_us_ = 0;           // Start of A/V rate measurement window
    uint64_t av_rate_probe_audio_count_ = 0;       // Audio packets in window
    uint64_t av_rate_probe_video_count_ = 0;       // Video packets in window
    bool av_rate_imbalance_logged_ = false;        // Log imbalance once per episode

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

    // INV-P9-STEADY-003: Check if audio can push (A/V delta <= 1)
    // Returns true if audio is allowed to push without violating A/V delta.
    // If false, audio must wait for video to catch up.
    bool CanAudioAdvance() const;
  };

} // namespace retrovue::producers::file

#endif // RETROVUE_PRODUCERS_FILE_FILE_PRODUCER_H_
