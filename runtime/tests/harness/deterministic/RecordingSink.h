// Repository: Retrovue-playout
// Component: Deterministic Test Harness - Recording Sink
// Purpose: IOutputSink implementation that records frames for test assertions.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_HARNESS_DETERMINISTIC_RECORDING_SINK_H_
#define RETROVUE_TESTS_HARNESS_DETERMINISTIC_RECORDING_SINK_H_

#include <atomic>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "FrameSource.h"
#include "retrovue/output/IOutputSink.h"

namespace retrovue::tests::harness::deterministic {

// RecordingSink implements IOutputSink to record frames for test assertions.
// It classifies each frame by source (LIVE_PRODUCER or BLACK) based on asset_uri.
class RecordingSink : public output::IOutputSink {
 public:
  RecordingSink();
  ~RecordingSink() override = default;

  // IOutputSink interface
  bool Start() override;
  void Stop() override;
  bool IsRunning() const override;
  output::SinkStatus GetStatus() const override;
  void ConsumeVideo(const buffer::Frame& frame) override;
  void ConsumeAudio(const buffer::AudioFrame& audio_frame) override;
  void SetStatusCallback(output::SinkStatusCallback callback) override;
  std::string GetName() const override;

  // Test assertion helpers

  // Returns the number of recorded frames.
  size_t FrameCount() const;

  // Returns the recorded frame at the given index.
  const RecordedFrame& GetFrame(size_t index) const;

  // Returns all recorded frames.
  const std::vector<RecordedFrame>& GetFrames() const;

  // Asserts that PTS is strictly monotonically increasing.
  // Returns true if all frames have PTS > previous frame's PTS.
  bool AssertMonotonicPTS() const;

  // Asserts that no frame has PTS >= max_pts.
  // Returns true if all frames have PTS < max_pts.
  bool AssertNoFramesBeyondPTS(int64_t max_pts) const;

  // Asserts that no LIVE frame has PTS >= max_pts (BLACK frames may exceed).
  // Returns true if all LIVE_PRODUCER frames have PTS < max_pts.
  bool AssertNoLiveFramesBeyondPTS(int64_t max_pts) const;

  // Asserts that all frames after the given index are BLACK.
  // Returns true if frames[index+1..end] are all BLACK.
  bool AssertOnlyBlackFramesAfter(size_t index) const;

  // Finds the first transition from LIVE_PRODUCER to BLACK.
  // Returns the index of the first BLACK frame after a LIVE_PRODUCER frame,
  // or nullopt if no such transition exists.
  std::optional<size_t> FindFirstTransitionToBlack() const;

  // Counts frames from LIVE_PRODUCER sources.
  size_t CountLiveFrames() const;

  // Counts frames from BLACK source.
  size_t CountBlackFrames() const;

  // Returns the last frame's PTS, or 0 if no frames recorded.
  int64_t GetLastPTS() const;

  // Clears all recorded frames.
  void Clear();

 private:
  // Classifies a frame by its asset_uri.
  static FrameSource ClassifyFrame(const buffer::Frame& frame);

  std::vector<RecordedFrame> frames_;
  std::atomic<output::SinkStatus> status_;
  output::SinkStatusCallback status_callback_;
};

}  // namespace retrovue::tests::harness::deterministic

#endif  // RETROVUE_TESTS_HARNESS_DETERMINISTIC_RECORDING_SINK_H_
