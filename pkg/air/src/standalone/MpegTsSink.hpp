// Repository: Retrovue-playout
// Component: MpegTsSink for Standalone Harness
// Purpose: Real MPEG-TS file output sink for BlockPlanExecutor verification
// Copyright (c) 2025 RetroVue
//
// This sink produces playable MPEG-TS files for visual verification of:
// - Segment transitions
// - Mid-block joins at correct offset
// - Underrun padding (black/silent)
// - Fence termination
//
// CONSTRAINTS:
// - Passive: receives frames, does not decide timing
// - Deterministic: CT maps directly to PTS with no wall-clock involvement
// - No retries, filler substitution, or waiting
//
// CT → PTS mapping: pts_90k = ct_ms * 90
// This provides 90kHz MPEG-TS timebase from millisecond CT.

#ifndef RETROVUE_STANDALONE_MPEGTS_SINK_HPP_
#define RETROVUE_STANDALONE_MPEGTS_SINK_HPP_

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
struct MpegTSPlayoutSinkConfig;
}  // namespace retrovue::playout_sinks::mpegts

namespace retrovue::blockplan::testing {
struct EmittedFrame;
}  // namespace retrovue::blockplan::testing

namespace retrovue::standalone {

// MpegTsSink encodes frames to a playable MPEG-TS file.
//
// Usage:
//   MpegTsSink sink("/tmp/output.ts", 640, 480, 30.0);
//   if (!sink.Open()) { /* error */ }
//   sink.EmitFrame(frame);  // Called by executor for each frame
//   sink.Close();           // Clean shutdown at fence
//
// The resulting TS file can be played with:
//   ffplay /tmp/output.ts
//   vlc /tmp/output.ts
class MpegTsSink {
 public:
  // Constructs a sink that will write to the specified file path.
  // width/height: Output resolution
  // fps: Target frame rate (affects GOP and timing)
  MpegTsSink(const std::string& output_path, int width, int height, double fps);

  ~MpegTsSink();

  // Disable copy and move
  MpegTsSink(const MpegTsSink&) = delete;
  MpegTsSink& operator=(const MpegTsSink&) = delete;

  // Opens the output file and initializes encoder.
  // Must be called before EmitFrame().
  // Returns true on success.
  bool Open();

  // Emits a frame to the TS output.
  // frame.ct_ms: Content time in milliseconds (maps to PTS)
  // frame.is_pad: If true, emit black video / silent audio
  // frame.asset_uri: For diagnostics only (not used in encoding)
  void EmitFrame(const blockplan::testing::EmittedFrame& frame);

  // Closes the muxer cleanly (writes trailer, flushes buffers).
  // Safe to call multiple times.
  void Close();

  // Returns true if Open() succeeded and Close() hasn't been called.
  bool IsOpen() const { return is_open_; }

  // Statistics
  size_t FramesEncoded() const { return frames_encoded_; }
  size_t PadFramesEncoded() const { return pad_frames_encoded_; }
  int64_t LastPts90k() const { return last_output_pts_90k_; }

 private:
  // Generate a black video frame (YUV420P)
  void GenerateBlackFrame();

  // Generate silent audio frame (PCM S16)
  void GenerateSilentAudio();

  std::string output_path_;
  int width_;
  int height_;
  double fps_;

  std::unique_ptr<playout_sinks::mpegts::MpegTSPlayoutSinkConfig> config_;
  std::unique_ptr<playout_sinks::mpegts::EncoderPipeline> encoder_;

  bool is_open_ = false;
  size_t frames_encoded_ = 0;
  size_t pad_frames_encoded_ = 0;

  // PTS tracking for continuous output across block transitions
  // CT is block-local (resets to 0 per block), but MPEG-TS needs monotonic PTS.
  // We track the last CT and output PTS; when CT drops, add offset to maintain continuity.
  int64_t last_input_ct_ms_ = -1;       // Last CT received (may reset per block)
  int64_t last_output_pts_90k_ = -1;    // Last PTS sent to encoder (monotonic)
  int64_t pts_offset_90k_ = 0;          // Cumulative offset for block transitions

  // Pre-allocated black frame data (YUV420P)
  std::vector<uint8_t> black_frame_data_;

  // Pre-allocated silent audio data (PCM S16 interleaved)
  std::vector<uint8_t> silent_audio_data_;
  int audio_samples_per_frame_ = 0;
};

}  // namespace retrovue::standalone

#endif  // RETROVUE_STANDALONE_MPEGTS_SINK_HPP_
