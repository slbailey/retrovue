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

// Forward declarations
namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
struct MpegTSPlayoutSinkConfig;
}  // namespace retrovue::playout_sinks::mpegts

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

  // Initialize encoder pipeline
  bool Open();

  // Emit a frame (decodes if needed, encodes, writes to FD)
  bool EmitFrame(const FrameMetadata& frame);

  // Finalize and close
  void Close();

  // Statistics
  size_t FrameCount() const { return frame_count_; }
  int64_t BytesWritten() const { return bytes_written_; }

 private:
  // Generate black video frame
  void GenerateBlackFrame(uint8_t* y_plane, uint8_t* u_plane, uint8_t* v_plane);

  // Encode and write a video frame
  bool EncodeFrame(const uint8_t* y_data, const uint8_t* u_data, const uint8_t* v_data,
                   int64_t pts_90k);

  SinkConfig config_;
  std::unique_ptr<playout_sinks::mpegts::EncoderPipeline> encoder_;

  size_t frame_count_ = 0;
  int64_t bytes_written_ = 0;
  int64_t last_ct_ms_ = -1;
  int64_t pts_offset_90k_ = 0;

  // Frame buffers
  std::vector<uint8_t> y_buffer_;
  std::vector<uint8_t> u_buffer_;
  std::vector<uint8_t> v_buffer_;
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
    std::string error_detail;
  };

  explicit RealTimeBlockExecutor(const Config& config);
  ~RealTimeBlockExecutor();

  // Execute a validated block plan in real-time
  // Blocks until: fence reached, failure occurs, or termination requested
  Result Execute(const ValidatedBlockPlan& plan,
                 const JoinParameters& join_params);

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
};

}  // namespace retrovue::blockplan::realtime

#endif  // RETROVUE_BLOCKPLAN_REALTIME_EXECUTION_HPP_
