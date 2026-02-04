// =============================================================================
// Contract Test: INV-P9-SINK-LIVENESS (Output Sink Liveness Policy)
// =============================================================================
// This file locks the sink liveness policy as defined in SinkLivenessPolicy.md.
//
// Policy: Pre-attach discard is legal; post-attach delivery is mandatory.
//
// Invariants tested:
//   INV-P9-SINK-LIVENESS-001: Pre-attach discard is silent (no error)
//   INV-P9-SINK-LIVENESS-002: Post-attach delivery (frames reach sink)
//   INV-P9-SINK-LIVENESS-003: Sink stability (no spontaneous loss)
//
// See: docs/contracts/semantics/SinkLivenessPolicy.md
// =============================================================================

#include "../../BaseContractTest.h"
#include "../ContractRegistryEnvironment.h"

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/OutputBus.h"

namespace retrovue::tests {
namespace {

using retrovue::tests::RegisterExpectedDomainCoverage;

// Register expected coverage for this domain
const bool kRegisterSinkCoverage = []() {
  RegisterExpectedDomainCoverage("SinkLiveness",
                                 {"INV-P9-SINK-LIVENESS-001",
                                  "INV-P9-SINK-LIVENESS-002",
                                  "INV-P9-SINK-LIVENESS-003"});
  return true;
}();

// =============================================================================
// Test sink implementation for contract verification
// =============================================================================
class TestOutputSink : public output::IOutputSink {
 public:
  TestOutputSink() = default;
  ~TestOutputSink() override = default;

  bool Start() override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (status_ != output::SinkStatus::kIdle) {
      return false;
    }
    status_ = output::SinkStatus::kRunning;
    return true;
  }

  void Stop() override {
    std::lock_guard<std::mutex> lock(mutex_);
    status_ = output::SinkStatus::kStopped;
  }

  bool IsRunning() const override {
    std::lock_guard<std::mutex> lock(mutex_);
    return status_ == output::SinkStatus::kRunning ||
           status_ == output::SinkStatus::kBackpressure;
  }

  output::SinkStatus GetStatus() const override {
    std::lock_guard<std::mutex> lock(mutex_);
    return status_;
  }

  void ConsumeVideo(const buffer::Frame& frame) override {
    (void)frame;
    video_frames_received_.fetch_add(1, std::memory_order_relaxed);
  }

  void ConsumeAudio(const buffer::AudioFrame& audio_frame) override {
    (void)audio_frame;
    audio_frames_received_.fetch_add(1, std::memory_order_relaxed);
  }

  void SetStatusCallback(output::SinkStatusCallback callback) override {
    std::lock_guard<std::mutex> lock(mutex_);
    status_callback_ = std::move(callback);
  }

  std::string GetName() const override {
    return "TestOutputSink";
  }

  // Test accessors
  uint64_t GetVideoFramesReceived() const {
    return video_frames_received_.load(std::memory_order_relaxed);
  }

  uint64_t GetAudioFramesReceived() const {
    return audio_frames_received_.load(std::memory_order_relaxed);
  }

 private:
  mutable std::mutex mutex_;
  output::SinkStatus status_ = output::SinkStatus::kIdle;
  output::SinkStatusCallback status_callback_;
  std::atomic<uint64_t> video_frames_received_{0};
  std::atomic<uint64_t> audio_frames_received_{0};
};

// =============================================================================
// Test fixture for INV-P9-SINK-LIVENESS contract tests
// =============================================================================
class SinkLivenessContractTest : public BaseContractTest {
 protected:
  [[nodiscard]] std::string DomainName() const override {
    return "SinkLiveness";
  }

  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override {
    return {"INV-P9-SINK-LIVENESS-001",
            "INV-P9-SINK-LIVENESS-002",
            "INV-P9-SINK-LIVENESS-003"};
  }

  // Creates a test video frame
  buffer::Frame MakeTestVideoFrame(int64_t pts_us) {
    buffer::Frame frame;
    frame.metadata.pts = pts_us;
    frame.metadata.dts = pts_us;
    frame.metadata.duration = 1.0 / 30.0;
    frame.width = 1920;
    frame.height = 1080;
    // Minimal data
    frame.data.resize(100, 0);
    return frame;
  }

  // Creates a test audio frame
  buffer::AudioFrame MakeTestAudioFrame(int64_t pts_us) {
    buffer::AudioFrame frame;
    frame.pts_us = pts_us;
    frame.sample_rate = 48000;
    frame.channels = 2;
    frame.nb_samples = 1024;
    frame.data.resize(1024 * 2 * 2, 0);  // 1024 samples * 2 channels * 2 bytes
    return frame;
  }
};

// =============================================================================
// INV-P9-SINK-LIVENESS-001: Pre-attach discard is silent
// =============================================================================
// When no sink is attached, frames routed to the bus SHALL be silently
// discarded without error. This is the expected pre-attach behavior.
// =============================================================================
TEST_F(SinkLivenessContractTest, INV_P9_SINK_LIVENESS_001_PreAttachDiscardIsSilent) {
  SCOPED_TRACE("INV-P9-SINK-LIVENESS-001: Pre-attach frame discard must be silent");

  // Create OutputBus with no control plane (standalone test)
  output::OutputBus bus;

  // Verify no sink attached
  ASSERT_FALSE(bus.HasSink()) << "Bus should start with no sink";

  // Route multiple video frames - should not throw or error
  for (int i = 0; i < 100; ++i) {
    buffer::Frame frame = MakeTestVideoFrame(i * 33333);
    // This MUST NOT throw, crash, or log warnings
    bus.RouteVideo(frame);
  }

  // Route multiple audio frames - should not throw or error
  for (int i = 0; i < 50; ++i) {
    buffer::AudioFrame audio = MakeTestAudioFrame(i * 21333);
    // This MUST NOT throw, crash, or log warnings
    bus.RouteAudio(audio);
  }

  // Still no sink attached (frames were discarded)
  EXPECT_FALSE(bus.HasSink());

  std::cout << "[INV-P9-SINK-LIVENESS-001] Pre-attach discard: "
            << "100 video + 50 audio frames discarded silently" << std::endl;
}

// =============================================================================
// INV-P9-SINK-LIVENESS-002: Post-attach delivery
// =============================================================================
// Once AttachSink succeeds, all frames routed via RouteVideo and RouteAudio
// MUST be delivered to the attached sink.
// =============================================================================
TEST_F(SinkLivenessContractTest, INV_P9_SINK_LIVENESS_002_PostAttachDelivery) {
  SCOPED_TRACE("INV-P9-SINK-LIVENESS-002: Post-attach frames must reach sink");

  output::OutputBus bus;

  // Create and attach sink
  auto sink = std::make_unique<TestOutputSink>();
  TestOutputSink* sink_ptr = sink.get();  // Keep raw pointer for verification

  auto result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(result.success) << "AttachSink failed: " << result.message;
  ASSERT_TRUE(bus.HasSink()) << "Sink should be attached after AttachSink";

  // Route video frames - all MUST reach sink
  constexpr int kVideoFrameCount = 50;
  for (int i = 0; i < kVideoFrameCount; ++i) {
    buffer::Frame frame = MakeTestVideoFrame(i * 33333);
    bus.RouteVideo(frame);
  }

  // Route audio frames - all MUST reach sink
  constexpr int kAudioFrameCount = 30;
  for (int i = 0; i < kAudioFrameCount; ++i) {
    buffer::AudioFrame audio = MakeTestAudioFrame(i * 21333);
    bus.RouteAudio(audio);
  }

  // ==========================================================================
  // CRITICAL ASSERTION: All frames MUST have reached the sink
  // ==========================================================================
  EXPECT_EQ(sink_ptr->GetVideoFramesReceived(), kVideoFrameCount)
      << "INV-P9-SINK-LIVENESS-002 VIOLATION: Not all video frames reached sink\n"
      << "  sent=" << kVideoFrameCount << "\n"
      << "  received=" << sink_ptr->GetVideoFramesReceived();

  EXPECT_EQ(sink_ptr->GetAudioFramesReceived(), kAudioFrameCount)
      << "INV-P9-SINK-LIVENESS-002 VIOLATION: Not all audio frames reached sink\n"
      << "  sent=" << kAudioFrameCount << "\n"
      << "  received=" << sink_ptr->GetAudioFramesReceived();

  std::cout << "[INV-P9-SINK-LIVENESS-002] Post-attach delivery: "
            << kVideoFrameCount << " video + " << kAudioFrameCount
            << " audio frames delivered" << std::endl;
}

// =============================================================================
// INV-P9-SINK-LIVENESS-002: Mixed pre/post attach behavior
// =============================================================================
// Verifies correct behavior when frames are routed before AND after attach.
// Pre-attach frames should be discarded; post-attach frames should be delivered.
// =============================================================================
TEST_F(SinkLivenessContractTest, INV_P9_SINK_LIVENESS_002_MixedPrePostAttach) {
  SCOPED_TRACE("INV-P9-SINK-LIVENESS-002: Pre-attach discard + post-attach delivery");

  output::OutputBus bus;

  // Route frames before attach - should be discarded
  constexpr int kPreAttachFrames = 20;
  for (int i = 0; i < kPreAttachFrames; ++i) {
    buffer::Frame frame = MakeTestVideoFrame(i * 33333);
    bus.RouteVideo(frame);
  }

  // Now attach sink
  auto sink = std::make_unique<TestOutputSink>();
  TestOutputSink* sink_ptr = sink.get();

  auto result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(result.success);

  // Route frames after attach - should be delivered
  constexpr int kPostAttachFrames = 30;
  for (int i = 0; i < kPostAttachFrames; ++i) {
    buffer::Frame frame = MakeTestVideoFrame((kPreAttachFrames + i) * 33333);
    bus.RouteVideo(frame);
  }

  // Only post-attach frames should have reached sink
  EXPECT_EQ(sink_ptr->GetVideoFramesReceived(), kPostAttachFrames)
      << "Only post-attach frames should reach sink\n"
      << "  pre_attach=" << kPreAttachFrames << " (should be discarded)\n"
      << "  post_attach=" << kPostAttachFrames << " (should be delivered)\n"
      << "  received=" << sink_ptr->GetVideoFramesReceived();

  std::cout << "[INV-P9-SINK-LIVENESS-002] Mixed: "
            << kPreAttachFrames << " discarded, "
            << kPostAttachFrames << " delivered" << std::endl;
}

// =============================================================================
// INV-P9-SINK-LIVENESS-003: Sink stability (explicit detach)
// =============================================================================
// Verifies that detach is explicit and sink remains attached until detach.
// =============================================================================
TEST_F(SinkLivenessContractTest, INV_P9_SINK_LIVENESS_003_SinkStabilityExplicitDetach) {
  SCOPED_TRACE("INV-P9-SINK-LIVENESS-003: Sink remains attached until explicit detach");

  output::OutputBus bus;

  // Attach sink
  auto sink = std::make_unique<TestOutputSink>();
  TestOutputSink* sink_ptr = sink.get();

  auto result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(result.success);
  ASSERT_TRUE(bus.HasSink());

  // Route some frames
  for (int i = 0; i < 10; ++i) {
    buffer::Frame frame = MakeTestVideoFrame(i * 33333);
    bus.RouteVideo(frame);
  }

  // Sink should still be attached
  EXPECT_TRUE(bus.HasSink()) << "Sink should remain attached during frame routing";
  EXPECT_EQ(sink_ptr->GetVideoFramesReceived(), 10u);

  // Route more frames
  for (int i = 10; i < 20; ++i) {
    buffer::Frame frame = MakeTestVideoFrame(i * 33333);
    bus.RouteVideo(frame);
  }

  // Still attached
  EXPECT_TRUE(bus.HasSink()) << "Sink should remain attached";
  EXPECT_EQ(sink_ptr->GetVideoFramesReceived(), 20u);

  // Now explicit detach
  auto detach_result = bus.DetachSink();
  EXPECT_TRUE(detach_result.success) << "DetachSink failed: " << detach_result.message;
  EXPECT_FALSE(bus.HasSink()) << "Sink should be detached after DetachSink";

  // Frames after detach should be discarded (back to pre-attach state)
  for (int i = 20; i < 30; ++i) {
    buffer::Frame frame = MakeTestVideoFrame(i * 33333);
    bus.RouteVideo(frame);
  }

  // No more frames should have reached the detached sink
  // (The sink object is destroyed, but we verified the count before detach)

  std::cout << "[INV-P9-SINK-LIVENESS-003] Stability: "
            << "20 frames delivered before detach, "
            << "10 frames discarded after detach" << std::endl;
}

// =============================================================================
// INV-P9-SINK-LIVENESS-003: Idempotent detach
// =============================================================================
// Verifies that DetachSink is idempotent (calling without attach is no-op).
// =============================================================================
TEST_F(SinkLivenessContractTest, INV_P9_SINK_LIVENESS_003_IdempotentDetach) {
  SCOPED_TRACE("INV-P9-SINK-LIVENESS-003: DetachSink is idempotent");

  output::OutputBus bus;

  // Detach without attach - should be idempotent no-op
  auto result = bus.DetachSink();
  EXPECT_TRUE(result.success) << "DetachSink on empty bus should succeed (idempotent)";
  EXPECT_FALSE(bus.HasSink());

  // Multiple detach calls should all succeed
  for (int i = 0; i < 5; ++i) {
    auto r = bus.DetachSink();
    EXPECT_TRUE(r.success) << "Repeated DetachSink should be idempotent";
  }

  std::cout << "[INV-P9-SINK-LIVENESS-003] Idempotent: "
            << "DetachSink succeeds without prior attach" << std::endl;
}

// =============================================================================
// Phase transition test: attach -> detach -> attach
// =============================================================================
// Verifies correct frame routing through multiple phase transitions.
// =============================================================================
TEST_F(SinkLivenessContractTest, PhaseTransitions_AttachDetachAttach) {
  SCOPED_TRACE("Phase transitions: attach -> detach -> attach");

  output::OutputBus bus;

  // Phase 1: Pre-attach (discard)
  for (int i = 0; i < 5; ++i) {
    bus.RouteVideo(MakeTestVideoFrame(i * 33333));
  }

  // Phase 2: First attach
  auto sink1 = std::make_unique<TestOutputSink>();
  TestOutputSink* sink1_ptr = sink1.get();
  ASSERT_TRUE(bus.AttachSink(std::move(sink1)).success);

  for (int i = 5; i < 15; ++i) {
    bus.RouteVideo(MakeTestVideoFrame(i * 33333));
  }
  EXPECT_EQ(sink1_ptr->GetVideoFramesReceived(), 10u);

  // Phase 3: Detach (back to discard)
  ASSERT_TRUE(bus.DetachSink().success);

  for (int i = 15; i < 20; ++i) {
    bus.RouteVideo(MakeTestVideoFrame(i * 33333));
  }

  // Phase 4: Second attach (new sink)
  auto sink2 = std::make_unique<TestOutputSink>();
  TestOutputSink* sink2_ptr = sink2.get();
  ASSERT_TRUE(bus.AttachSink(std::move(sink2)).success);

  for (int i = 20; i < 30; ++i) {
    bus.RouteVideo(MakeTestVideoFrame(i * 33333));
  }
  EXPECT_EQ(sink2_ptr->GetVideoFramesReceived(), 10u);

  std::cout << "[Phase transitions] "
            << "sink1=10 frames, "
            << "discarded=10 frames, "
            << "sink2=10 frames" << std::endl;
}

}  // namespace
}  // namespace retrovue::tests
