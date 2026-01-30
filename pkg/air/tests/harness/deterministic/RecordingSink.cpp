// Repository: Retrovue-playout
// Component: Deterministic Test Harness - Recording Sink Implementation
// Purpose: IOutputSink implementation that records frames for test assertions.
// Copyright (c) 2025 RetroVue

#include "RecordingSink.h"

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::tests::harness::deterministic {

RecordingSink::RecordingSink()
    : status_(output::SinkStatus::kIdle) {}

bool RecordingSink::Start() {
  output::SinkStatus expected = output::SinkStatus::kIdle;
  if (!status_.compare_exchange_strong(expected, output::SinkStatus::kRunning)) {
    return false;
  }
  if (status_callback_) {
    status_callback_(output::SinkStatus::kRunning, "Recording started");
  }
  return true;
}

void RecordingSink::Stop() {
  status_.store(output::SinkStatus::kStopped);
  if (status_callback_) {
    status_callback_(output::SinkStatus::kStopped, "Recording stopped");
  }
}

bool RecordingSink::IsRunning() const {
  auto s = status_.load();
  return s == output::SinkStatus::kRunning || s == output::SinkStatus::kBackpressure;
}

output::SinkStatus RecordingSink::GetStatus() const {
  return status_.load();
}

void RecordingSink::ConsumeVideo(const buffer::Frame& frame) {
  if (!IsRunning()) {
    return;
  }

  RecordedFrame recorded;
  recorded.source = ClassifyFrame(frame);
  recorded.producer_id = frame.metadata.asset_uri;
  recorded.pts = frame.metadata.pts;
  recorded.dts = frame.metadata.dts;
  recorded.frame_index = static_cast<int>(frames_.size());

  frames_.push_back(recorded);
}

void RecordingSink::ConsumeAudio(const buffer::AudioFrame& /*audio_frame*/) {
  // Audio frames are not recorded in this test harness.
  // The deterministic harness focuses on video frame continuity.
}

void RecordingSink::SetStatusCallback(output::SinkStatusCallback callback) {
  status_callback_ = std::move(callback);
}

std::string RecordingSink::GetName() const {
  return "RecordingSink";
}

size_t RecordingSink::FrameCount() const {
  return frames_.size();
}

const RecordedFrame& RecordingSink::GetFrame(size_t index) const {
  return frames_.at(index);
}

const std::vector<RecordedFrame>& RecordingSink::GetFrames() const {
  return frames_;
}

bool RecordingSink::AssertMonotonicPTS() const {
  if (frames_.size() < 2) {
    return true;
  }

  for (size_t i = 1; i < frames_.size(); ++i) {
    if (frames_[i].pts <= frames_[i - 1].pts) {
      return false;
    }
  }
  return true;
}

bool RecordingSink::AssertNoFramesBeyondPTS(int64_t max_pts) const {
  for (const auto& frame : frames_) {
    if (frame.pts >= max_pts) {
      return false;
    }
  }
  return true;
}

bool RecordingSink::AssertNoLiveFramesBeyondPTS(int64_t max_pts) const {
  for (const auto& frame : frames_) {
    if (frame.source == FrameSource::LIVE_PRODUCER && frame.pts >= max_pts) {
      return false;
    }
  }
  return true;
}

bool RecordingSink::AssertOnlyBlackFramesAfter(size_t index) const {
  for (size_t i = index + 1; i < frames_.size(); ++i) {
    if (frames_[i].source != FrameSource::BLACK) {
      return false;
    }
  }
  return true;
}

std::optional<size_t> RecordingSink::FindFirstTransitionToBlack() const {
  for (size_t i = 1; i < frames_.size(); ++i) {
    if (frames_[i - 1].source == FrameSource::LIVE_PRODUCER &&
        frames_[i].source == FrameSource::BLACK) {
      return i;
    }
  }
  return std::nullopt;
}

size_t RecordingSink::CountLiveFrames() const {
  size_t count = 0;
  for (const auto& frame : frames_) {
    if (frame.source == FrameSource::LIVE_PRODUCER) {
      ++count;
    }
  }
  return count;
}

size_t RecordingSink::CountBlackFrames() const {
  size_t count = 0;
  for (const auto& frame : frames_) {
    if (frame.source == FrameSource::BLACK) {
      ++count;
    }
  }
  return count;
}

int64_t RecordingSink::GetLastPTS() const {
  if (frames_.empty()) {
    return 0;
  }
  return frames_.back().pts;
}

void RecordingSink::Clear() {
  frames_.clear();
}

FrameSource RecordingSink::ClassifyFrame(const buffer::Frame& frame) {
  if (frame.metadata.asset_uri == kBlackFrameAssetUri) {
    return FrameSource::BLACK;
  }
  return FrameSource::LIVE_PRODUCER;
}

}  // namespace retrovue::tests::harness::deterministic
