// Repository: Retrovue-playout
// Component: Deterministic Test Harness
// Purpose: Orchestrates deterministic testing of AIR control-plane and continuity invariants.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_HARNESS_DETERMINISTIC_DETERMINISTIC_TEST_HARNESS_H_
#define RETROVUE_TESTS_HARNESS_DETERMINISTIC_DETERMINISTIC_TEST_HARNESS_H_

#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>

#include "FakeProducers.h"
#include "RecordingSink.h"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/runtime/ProgramFormat.h"

namespace retrovue {
namespace buffer {
class FrameRingBuffer;
}
namespace runtime {
class PlayoutControl;
}
namespace timing {
class TestMasterClock;
}
}  // namespace retrovue

namespace retrovue::tests::harness::deterministic {

// DeterministicTestHarness orchestrates all components for deterministic testing.
//
// It provides:
// - Synthetic time control (no wall-clock dependency)
// - Fake producers that emit frames synchronously
// - Recording sink for frame assertions
// - Direct access to PlayoutControl (no gRPC)
//
// Usage:
//   DeterministicTestHarness harness;
//   harness.RegisterProducerSpec("test://asset.mp4", ProducerSpec::Finite(5));
//   harness.Start();
//   harness.LoadPreview("test://asset.mp4", 0, 0);
//   harness.SwitchToLive();
//   for (int i = 0; i < 10; ++i) {
//     harness.TickProducers();
//     harness.DrainBufferToSink();
//   }
//   EXPECT_TRUE(harness.GetSink().CountBlackFrames() > 0);
class DeterministicTestHarness {
 public:
  DeterministicTestHarness();
  ~DeterministicTestHarness();

  // Configuration (must be called before Start)

  // Registers a producer spec for a path.
  // When LoadPreview is called with this path, the harness creates
  // the corresponding fake producer.
  void RegisterProducerSpec(const std::string& path, ProducerSpec spec);

  // Sets the buffer capacity (default: 60 frames).
  void SetBufferCapacity(size_t capacity);

  // Sets the initial clock time (default: 0).
  void SetInitialTimeUs(int64_t time_us);

  // Lifecycle

  // Starts the harness (creates clock, buffer, PlayoutControl, sink).
  void Start();

  // Stops and tears down all components.
  void Stop();

  // Time control

  // Advances time by the given delta (microseconds).
  void AdvanceTimeUs(int64_t delta_us);

  // Advances time by one frame interval (33,366 µs).
  void AdvanceToNextFrame();

  // Playout control (direct, no gRPC)

  // Loads a producer into the preview bus.
  // Returns true on success.
  bool LoadPreview(const std::string& path,
                   int64_t start_offset_ms = 0,
                   int64_t hard_stop_time_ms = 0);

  // Switches the preview bus to live.
  // Returns true on success.
  bool SwitchToLive();

  // Frame control

  // Ticks all active producers to emit frames.
  // Returns the number of frames emitted.
  int TickProducers();

  // Drains frames from the buffer to the sink.
  // Returns the number of frames drained.
  int DrainBufferToSink();

  // State inspection

  // Returns true if the engine is in black fallback state.
  bool IsInBlackFallback() const;

  // Returns the number of times fallback has been entered (for invariant testing).
  uint64_t GetFallbackEntryCount() const;

  // Returns the recording sink for assertions.
  RecordingSink& GetSink();
  const RecordingSink& GetSink() const;

  // Returns the clock for direct time manipulation.
  std::shared_ptr<timing::TestMasterClock> GetClock() const;

  // Returns the ring buffer for direct inspection.
  buffer::FrameRingBuffer& GetBuffer();

  // Returns the live producer (if any) for direct inspection.
  FakeProducerBase* GetLiveProducer();

  // Returns the preview producer (if any) for direct inspection.
  FakeProducerBase* GetPreviewProducer();

 private:
  // Factory function for creating producers from specs.
  std::unique_ptr<producers::IProducer> CreateProducer(
      const std::string& path,
      const std::string& asset_id,
      buffer::FrameRingBuffer& ring_buffer,
      std::shared_ptr<timing::MasterClock> clock,
      int64_t start_offset_ms,
      int64_t hard_stop_time_ms);

  // Configuration state
  std::unordered_map<std::string, ProducerSpec> producer_specs_;
  size_t buffer_capacity_;
  int64_t initial_time_us_;

  // Runtime state
  bool started_;
  std::shared_ptr<timing::TestMasterClock> clock_;
  std::unique_ptr<buffer::FrameRingBuffer> buffer_;
  std::unique_ptr<runtime::PlayoutControl> playout_control_;
  std::unique_ptr<RecordingSink> sink_;

  // Track active producers for Tick operations
  // (We need raw pointers because unique_ptr ownership is in PlayoutControl)
  FakeProducerBase* live_producer_;
  FakeProducerBase* preview_producer_;

  // Program format for fallback producer configuration
  runtime::ProgramFormat program_format_;
};

}  // namespace retrovue::tests::harness::deterministic

#endif  // RETROVUE_TESTS_HARNESS_DETERMINISTIC_DETERMINISTIC_TEST_HARNESS_H_
