// Repository: Retrovue-playout
// Component: BlockPlan Real-Time Execution
// Purpose: Real implementations of executor interfaces for production execution
// Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
// Copyright (c) 2025 RetroVue
//
// This provides real-time execution that matches the semantics of the test
// infrastructure exactly. The same BlockPlanExecutor logic runs, but with:
// - Real wall clock (with pacing)
// - Real file probing for asset durations
// - Real decoding/encoding via FileProducer and EncoderPipeline

#ifndef RETROVUE_BLOCKPLAN_REALTIME_EXECUTION_HPP_
#define RETROVUE_BLOCKPLAN_REALTIME_EXECUTION_HPP_

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/decode/FFmpegDecoder.h"

// Forward declarations
namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
struct MpegTSPlayoutSinkConfig;
}  // namespace retrovue::playout_sinks::mpegts

namespace retrovue::blockplan {
struct BlockPreloadContext;
}  // namespace retrovue::blockplan

namespace retrovue::blockplan::realtime {

// =============================================================================
// Real-Time Clock
// Provides wall clock time with real-time pacing
// =============================================================================

class RealTimeClock {
 public:
  RealTimeClock();

  // Get current wall clock time (milliseconds since epoch or start)
  int64_t NowMs() const;

  // Advance wall clock by delta (sleeps for real-time pacing)
  void AdvanceMs(int64_t delta_ms);

  // Set absolute wall clock time (adjusts epoch offset)
  void SetMs(int64_t ms);

  // Set start epoch (for aligning with block start time)
  void SetEpoch(int64_t epoch_ms);

 private:
  int64_t epoch_ms_ = 0;
  std::chrono::steady_clock::time_point start_time_;
  int64_t virtual_offset_ms_ = 0;
};

// =============================================================================
// Real Asset Source
// Probes real files for duration using FFmpeg
// =============================================================================

class RealAssetSource {
 public:
  // Probe asset and cache duration
  // Returns true if asset is valid
  bool ProbeAsset(const std::string& uri);

  // Get asset duration (-1 if not found/probed)
  int64_t GetDuration(const std::string& uri) const;

  // Check if asset has been probed
  bool HasAsset(const std::string& uri) const;

  // For compatibility with FakeAssetSource interface
  struct AssetInfo {
    std::string uri;
    int64_t duration_ms = 0;
    bool valid = false;
  };

  const AssetInfo* GetAsset(const std::string& uri) const;

 private:
  std::map<std::string, AssetInfo> assets_;
};

// =============================================================================
// Real-Time Encoding Sink
// Receives EmittedFrame metadata, generates/decodes frames, encodes to MPEG-TS
// =============================================================================

struct SinkConfig {
  int fd = -1;           // Output file descriptor (UDS socket)
  int width = 640;       // Output width
  int height = 480;      // Output height
  double fps = 30.0;     // Frame rate
  int audio_rate = 48000;
  int audio_channels = 2;
  // INV-PTS-MONOTONIC: Initial PTS offset for session continuity across blocks
  int64_t initial_pts_offset_90k = 0;
  // ==========================================================================
  // SESSION-LONG ENCODER: Shared encoder pipeline for entire session
  // ==========================================================================
  // When non-null, use this shared pipeline instead of creating a new one.
  // This ensures continuity counters, muxer state, and encoder state persist
  // across block boundaries, fixing DTS out-of-order warnings.
  // The caller (playout_service) owns this pipeline for the session lifetime.
  playout_sinks::mpegts::EncoderPipeline* shared_encoder = nullptr;
};

// Frame metadata (matches testing::EmittedFrame structure)
struct FrameMetadata {
  int64_t ct_ms = 0;
  int64_t wall_ms = 0;
  int32_t segment_index = 0;
  bool is_pad = false;
  std::string asset_uri;
  int64_t asset_offset_ms = 0;
};

class RealTimeEncoderSink {
 public:
  explicit RealTimeEncoderSink(const SinkConfig& config);
  ~RealTimeEncoderSink();

  // Initialize encoder pipeline (or use shared pipeline if configured)
  bool Open();

  // Emit a frame (decodes if needed, encodes, writes to FD)
  bool EmitFrame(const FrameMetadata& frame);

  // Install a preloaded decoder for the first segment.
  // Must be called AFTER Open() and BEFORE the first EmitFrame().
  // Transfers ownership of the decoder to this sink.
  // If the asset_uri or offset don't match the first frame, the sink
  // will detect the mismatch and re-seek (graceful fallback).
  void InstallPreloadedDecoder(std::unique_ptr<decode::FFmpegDecoder> decoder,
                               const std::string& asset_uri,
                               int64_t seek_target_ms);

  // Finalize block (does NOT close shared encoder - only resets per-block state)
  void Close();

  // Statistics
  size_t FrameCount() const { return frame_count_; }
  int64_t BytesWritten() const { return bytes_written_; }
  // INV-PTS-MONOTONIC: Get final PTS offset for next block's session continuity.
  // Returns the offset needed for the NEXT block to maintain monotonic PTS.
  // This includes the current block's duration contribution.
  int64_t FinalPtsOffset90k() const {
    if (last_ct_ms_ < 0) {
      return pts_offset_90k_;  // No frames emitted
    }
    // Next block starts where this block ended: base + (last_ct + frame_duration) * 90
    return pts_offset_90k_ + (last_ct_ms_ + kFrameDurationMs) * 90;
  }

  // Get last emitted video/audio PTS for tripwire assertions
  int64_t LastVideoPts90k() const { return last_video_pts_90k_; }
  int64_t LastAudioPts90k() const { return last_audio_pts_90k_; }

 private:
  // Generate black video frame
  void GenerateBlackFrame(uint8_t* y_plane, uint8_t* u_plane, uint8_t* v_plane);

  // Encode and write a video frame
  bool EncodeFrame(const uint8_t* y_data, const uint8_t* u_data, const uint8_t* v_data,
                   int64_t pts_90k);

  SinkConfig config_;
  // Owned encoder (created per-block if no shared encoder)
  std::unique_ptr<playout_sinks::mpegts::EncoderPipeline> owned_encoder_;
  // Points to shared or owned encoder
  playout_sinks::mpegts::EncoderPipeline* encoder_ = nullptr;
  // True if we're using a shared encoder (don't close it)
  bool using_shared_encoder_ = false;

  size_t frame_count_ = 0;
  int64_t bytes_written_ = 0;
  int64_t last_ct_ms_ = -1;
  int64_t pts_offset_90k_ = 0;

  // ==========================================================================
  // TRIPWIRE: Track last emitted PTS for monotonicity assertions
  // ==========================================================================
  int64_t last_video_pts_90k_ = -1;
  int64_t last_audio_pts_90k_ = -1;

  // Frame buffers
  std::vector<uint8_t> y_buffer_;
  std::vector<uint8_t> u_buffer_;
  std::vector<uint8_t> v_buffer_;

  // Video decoder for real frame data
  std::unique_ptr<decode::FFmpegDecoder> decoder_;
  std::string current_asset_uri_;
  int64_t current_asset_offset_ms_ = -1;
  int64_t next_frame_offset_ms_ = 0;
  static constexpr int64_t kFrameDurationMs = 33;  // ~30fps

  // Audio state: track when real audio starts to disable silence injection
  bool audio_started_ = false;

  // ==========================================================================
  // SEEK ACCURACY: Track desired vs actual frame positions per block
  // ==========================================================================
  // Desired = executor-computed asset_offset_ms from FrameMetadata
  // Actual  = decoder PTS (microseconds from asset start, / 1000 for ms)
  int64_t desired_start_ms_ = -1;   // First real frame's requested offset
  int64_t actual_start_ms_ = -1;    // First real frame's decoded PTS (ms)
  int64_t desired_end_ms_ = -1;     // Last real frame's requested offset
  int64_t actual_end_ms_ = -1;      // Last real frame's decoded PTS (ms)
  size_t real_frames_decoded_ = 0;  // Count of successfully decoded frames

  // ==========================================================================
  // INV-PTS-MONOTONIC / INV-AUDIO-VIDEO-SYNC: Audio PTS must be CT-based
  // ==========================================================================
  // Audio PTS is computed from samples emitted (not decoder timestamps).
  // This ensures audio and video share the same monotonic timeline.
  // audio_pts_90k = pts_offset_90k_ + (audio_samples_emitted_ * 90000 / sample_rate)
  int64_t audio_samples_emitted_ = 0;
  static constexpr int kAudioSampleRate = 48000;  // House format sample rate
};

// =============================================================================
// Real-Time Block Executor
// Wraps BlockPlanExecutor with real-time components
// =============================================================================

class RealTimeBlockExecutor {
 public:
  struct Config {
    SinkConfig sink;
    std::function<void(const std::string&)> diagnostic;  // Optional logging
  };

  // Per-block frame cadence metrics captured during Execute()
  struct FrameCadenceMetrics {
    int64_t frames_emitted = 0;
    int64_t max_inter_frame_gap_us = 0;   // Max time between consecutive EmitFrame calls
    int64_t sum_inter_frame_gap_us = 0;   // Sum for computing mean
    int32_t frame_gaps_over_40ms = 0;     // Count of gaps exceeding 40ms (~1.2x frame period)
  };

  struct Result {
    enum class Code {
      kSuccess,
      kAssetError,
      kLookaheadExhausted,
      kTerminated,
      kEncoderError,
    };
    Code code = Code::kSuccess;
    int64_t final_ct_ms = 0;
    // INV-PTS-MONOTONIC: Final PTS offset to pass to next block for continuity
    int64_t final_pts_offset_90k = 0;
    std::string error_detail;
    // Per-block frame cadence metrics (passive observation)
    FrameCadenceMetrics frame_cadence;
  };

  explicit RealTimeBlockExecutor(const Config& config);
  ~RealTimeBlockExecutor();

  // Execute a validated block plan in real-time
  // Blocks until: fence reached, failure occurs, or termination requested
  // Optional preload context provides pre-probed assets and/or pre-opened decoder.
  // If preload is nullptr or incomplete, falls back to synchronous behavior.
  Result Execute(const ValidatedBlockPlan& plan,
                 const JoinParameters& join_params,
                 BlockPreloadContext* preload = nullptr);

  // Request graceful termination
  void RequestTermination();

 private:
  Config config_;
  std::atomic<bool> termination_requested_{false};

  RealTimeClock clock_;
  RealAssetSource assets_;
  std::unique_ptr<RealTimeEncoderSink> sink_;

  // Find segment index for given CT
  int32_t FindSegmentForCt(const std::vector<SegmentBoundary>& boundaries,
                           int64_t ct_ms) const;

  // Get segment by index
  const Segment* GetSegmentByIndex(const BlockPlan& plan,
                                    int32_t segment_index) const;

  // Emit diagnostic message
  void Diag(const std::string& msg);

  // Pacing: use absolute deadline to maintain consistent frame rate
  std::chrono::steady_clock::time_point next_frame_deadline_;
  bool deadline_initialized_ = false;
};

}  // namespace retrovue::blockplan::realtime

#endif  // RETROVUE_BLOCKPLAN_REALTIME_EXECUTION_HPP_
