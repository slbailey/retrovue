// Repository: Retrovue-playout
// Component: Deterministic Test Harness - Fake Producers
// Purpose: Synthetic producers for deterministic testing without real media files.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_HARNESS_DETERMINISTIC_FAKE_PRODUCERS_H_
#define RETROVUE_TESTS_HARNESS_DETERMINISTIC_FAKE_PRODUCERS_H_

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"

namespace retrovue::timing {
class TestMasterClock;
}

namespace retrovue::tests::harness::deterministic {

// Frame duration for 29.97 fps in microseconds (33,366 µs).
constexpr int64_t kFrameIntervalUs = 33'366;

// FakeProducerBase provides common logic for all fake producers.
// Subclasses implement ShouldEmitFrame() to control emission behavior.
//
// Unlike real producers, fake producers do not run threads.
// The harness calls Tick() to synchronously emit frames.
class FakeProducerBase : public retrovue::producers::IProducer {
 public:
  FakeProducerBase(const std::string& asset_uri,
                   buffer::FrameRingBuffer& ring_buffer,
                   std::shared_ptr<timing::TestMasterClock> clock);

  ~FakeProducerBase() override = default;

  // IProducer interface
  bool start() override;
  void stop() override;
  bool isRunning() const override;

  // Tick advances the producer by one frame interval.
  // If ShouldEmitFrame() returns true, emits a synthetic frame.
  // Returns true if a frame was emitted, false otherwise.
  bool Tick();

  // Returns the number of frames emitted.
  int64_t GetFramesEmitted() const { return frames_emitted_.load(); }

  // Returns the current PTS (what the next frame would have).
  int64_t GetCurrentPts() const { return current_pts_us_.load(); }

  // Returns true if this producer has exhausted its frame supply.
  virtual bool IsExhausted() const = 0;

 protected:
  // Subclasses implement this to control when frames are emitted.
  virtual bool ShouldEmitFrame() const = 0;

  // Emits a synthetic frame to the ring buffer.
  void EmitFrame();

  std::string asset_uri_;
  buffer::FrameRingBuffer& ring_buffer_;
  std::shared_ptr<timing::TestMasterClock> clock_;
  std::atomic<bool> running_;
  std::atomic<int64_t> frames_emitted_;
  std::atomic<int64_t> current_pts_us_;
};

// FiniteProducer emits exactly N frames, then exhausts.
// Used to test dead-man fallback on underrun.
class FiniteProducer : public FakeProducerBase {
 public:
  FiniteProducer(const std::string& asset_uri,
                 buffer::FrameRingBuffer& ring_buffer,
                 std::shared_ptr<timing::TestMasterClock> clock,
                 int64_t frame_count);

  bool IsExhausted() const override;

 protected:
  bool ShouldEmitFrame() const override;

 private:
  int64_t frame_limit_;
};

// InfiniteProducer emits frames forever.
// Used to test normal operation and recovery scenarios.
class InfiniteProducer : public FakeProducerBase {
 public:
  InfiniteProducer(const std::string& asset_uri,
                   buffer::FrameRingBuffer& ring_buffer,
                   std::shared_ptr<timing::TestMasterClock> clock);

  bool IsExhausted() const override { return false; }

 protected:
  bool ShouldEmitFrame() const override { return true; }
};

// ClampedProducer emits frames until PTS reaches end_pts_us.
// Used to test end-PTS boundary enforcement.
class ClampedProducer : public FakeProducerBase {
 public:
  ClampedProducer(const std::string& asset_uri,
                  buffer::FrameRingBuffer& ring_buffer,
                  std::shared_ptr<timing::TestMasterClock> clock,
                  int64_t end_pts_us);

  bool IsExhausted() const override;

  // Returns the end PTS boundary.
  int64_t GetEndPtsUs() const { return end_pts_us_; }

 protected:
  bool ShouldEmitFrame() const override;

 private:
  int64_t end_pts_us_;
};

// ProducerSpec describes how to create a fake producer.
// Used by DeterministicTestHarness to register producer types for paths.
struct ProducerSpec {
  enum class Type {
    FINITE,
    INFINITE,
    CLAMPED
  };

  Type type;
  int64_t param;  // frame_count for FINITE, end_pts_us for CLAMPED

  static ProducerSpec Finite(int64_t frame_count) {
    return {Type::FINITE, frame_count};
  }

  static ProducerSpec Infinite() {
    return {Type::INFINITE, 0};
  }

  static ProducerSpec Clamped(int64_t end_pts_us) {
    return {Type::CLAMPED, end_pts_us};
  }
};

}  // namespace retrovue::tests::harness::deterministic

#endif  // RETROVUE_TESTS_HARNESS_DETERMINISTIC_FAKE_PRODUCERS_H_
