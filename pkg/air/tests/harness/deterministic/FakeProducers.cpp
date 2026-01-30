// Repository: Retrovue-playout
// Component: Deterministic Test Harness - Fake Producers Implementation
// Purpose: Synthetic producers for deterministic testing without real media files.
// Copyright (c) 2025 RetroVue

#include "FakeProducers.h"

#include "timing/TestMasterClock.h"

namespace retrovue::tests::harness::deterministic {

// FakeProducerBase implementation

FakeProducerBase::FakeProducerBase(const std::string& asset_uri,
                                   buffer::FrameRingBuffer& ring_buffer,
                                   std::shared_ptr<timing::TestMasterClock> clock)
    : asset_uri_(asset_uri),
      ring_buffer_(ring_buffer),
      clock_(std::move(clock)),
      running_(false),
      frames_emitted_(0),
      current_pts_us_(0) {}

bool FakeProducerBase::start() {
  if (running_.load()) {
    return false;  // Already running
  }
  running_.store(true);
  return true;
}

void FakeProducerBase::stop() {
  running_.store(false);
}

bool FakeProducerBase::isRunning() const {
  return running_.load();
}

bool FakeProducerBase::Tick() {
  if (!running_.load()) {
    return false;
  }

  if (ShouldEmitFrame()) {
    EmitFrame();
    return true;
  }
  return false;
}

void FakeProducerBase::EmitFrame() {
  buffer::Frame frame;

  // Build synthetic frame metadata
  frame.metadata.pts = current_pts_us_.load();
  frame.metadata.dts = current_pts_us_.load();
  frame.metadata.duration = static_cast<double>(kFrameIntervalUs) / 1'000'000.0;
  frame.metadata.asset_uri = asset_uri_;

  // Minimal synthetic frame data (1x1 black pixel in YUV420)
  frame.width = 1;
  frame.height = 1;
  frame.data.resize(1 + 1, 0);  // Y=0 (black), U=128, V=128 would be neutral

  // Push to ring buffer (may fail if full, but that's expected in tests)
  ring_buffer_.Push(frame);

  // Advance state
  frames_emitted_.fetch_add(1);
  current_pts_us_.fetch_add(kFrameIntervalUs);
}

// FiniteProducer implementation

FiniteProducer::FiniteProducer(const std::string& asset_uri,
                               buffer::FrameRingBuffer& ring_buffer,
                               std::shared_ptr<timing::TestMasterClock> clock,
                               int64_t frame_count)
    : FakeProducerBase(asset_uri, ring_buffer, std::move(clock)),
      frame_limit_(frame_count) {}

bool FiniteProducer::ShouldEmitFrame() const {
  return frames_emitted_.load() < frame_limit_;
}

bool FiniteProducer::IsExhausted() const {
  return frames_emitted_.load() >= frame_limit_;
}

// InfiniteProducer implementation

InfiniteProducer::InfiniteProducer(const std::string& asset_uri,
                                   buffer::FrameRingBuffer& ring_buffer,
                                   std::shared_ptr<timing::TestMasterClock> clock)
    : FakeProducerBase(asset_uri, ring_buffer, std::move(clock)) {}

// ClampedProducer implementation

ClampedProducer::ClampedProducer(const std::string& asset_uri,
                                 buffer::FrameRingBuffer& ring_buffer,
                                 std::shared_ptr<timing::TestMasterClock> clock,
                                 int64_t end_pts_us)
    : FakeProducerBase(asset_uri, ring_buffer, std::move(clock)),
      end_pts_us_(end_pts_us) {}

bool ClampedProducer::ShouldEmitFrame() const {
  // Only emit if the next frame's PTS would be BEFORE the end boundary.
  return current_pts_us_.load() < end_pts_us_;
}

bool ClampedProducer::IsExhausted() const {
  // Exhausted when the next frame would exceed or equal the end boundary.
  return current_pts_us_.load() >= end_pts_us_;
}

}  // namespace retrovue::tests::harness::deterministic
