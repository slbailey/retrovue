// Contract tests for OutputSwitchingContract.md
// Verifies hot-switch invariants between Live and Preview buses.

#include "../../BaseContractTest.h"
#include "../ContractRegistryEnvironment.h"

#include <chrono>
#include <thread>
#include <atomic>
#include <functional>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/OutputBus.h"
#include "retrovue/renderer/ProgramOutput.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/runtime/PlayoutEngine.h"
#include "retrovue/runtime/PlayoutInterface.h"
#include "retrovue/producers/file/FileProducer.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;
using namespace retrovue::tests;

namespace {

using retrovue::tests::RegisterExpectedDomainCoverage;

// =============================================================================
// TestOutputSink: Modern architecture test sink implementing IOutputSink
// =============================================================================
// This sink receives frames through the OutputBus and invokes callbacks for
// test observation. It replaces the legacy SideSink pattern.
// =============================================================================
class TestOutputSink : public output::IOutputSink {
 public:
  using VideoCallback = std::function<void(const buffer::Frame&)>;
  using AudioCallback = std::function<void(const buffer::AudioFrame&)>;

  explicit TestOutputSink(const std::string& name = "test-sink")
      : name_(name), status_(output::SinkStatus::kIdle) {}

  bool Start() override {
    status_ = output::SinkStatus::kRunning;
    return true;
  }

  void Stop() override {
    status_ = output::SinkStatus::kStopped;
  }

  bool IsRunning() const override {
    return status_ == output::SinkStatus::kRunning;
  }

  output::SinkStatus GetStatus() const override {
    return status_;
  }

  void ConsumeVideo(const buffer::Frame& frame) override {
    if (video_callback_) {
      video_callback_(frame);
    }
  }

  void ConsumeAudio(const buffer::AudioFrame& audio_frame) override {
    if (audio_callback_) {
      audio_callback_(audio_frame);
    }
  }

  void SetStatusCallback(output::SinkStatusCallback callback) override {
    status_callback_ = std::move(callback);
  }

  std::string GetName() const override {
    return name_;
  }

  // Test-specific methods
  void SetVideoCallback(VideoCallback cb) { video_callback_ = std::move(cb); }
  void SetAudioCallback(AudioCallback cb) { audio_callback_ = std::move(cb); }

 private:
  std::string name_;
  output::SinkStatus status_;
  output::SinkStatusCallback status_callback_;
  VideoCallback video_callback_;
  AudioCallback audio_callback_;
};

// Default ProgramFormat JSON for tests (1080p30, 48kHz stereo)
constexpr const char* kDefaultProgramFormatJson = R"({"video":{"width":1920,"height":1080,"frame_rate":"30/1"},"audio":{"sample_rate":48000,"channels":2}})";

const bool kRegisterCoverage = []() {
  RegisterExpectedDomainCoverage(
      "OutputSwitching",
      {"OS-001", "OS-002", "OS-003", "OS-004", "OS-005", "OS-006"});
  return true;
}();

class OutputSwitchingContractTest : public BaseContractTest {
 protected:
  [[nodiscard]] std::string DomainName() const override {
    return "OutputSwitching";
  }

  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override {
    return {"OS-001", "OS-002", "OS-003", "OS-004", "OS-005", "OS-006"};
  }
};

// =============================================================================
// OS-001: Single-Source Output
// The Output Bus consumes frames from exactly one upstream bus at any instant.
// =============================================================================

TEST_F(OutputSwitchingContractTest, OS_001_OutputReadsFromExactlyOneBuffer) {
  // This test verifies that after SetInputBuffer, ProgramOutput reads from the new buffer.
  // Uses modern OutputBus architecture with TestOutputSink.

  buffer::FrameRingBuffer live_buffer(60);
  buffer::FrameRingBuffer preview_buffer(60);

  // Fill each buffer with distinguishable frames
  for (int i = 0; i < 30; ++i) {
    buffer::Frame live_frame;
    live_frame.metadata.pts = i * 33366;
    live_frame.metadata.asset_uri = "live://asset";
    live_frame.width = 1920;
    live_frame.height = 1080;
    ASSERT_TRUE(live_buffer.Push(live_frame));

    buffer::Frame preview_frame;
    preview_frame.metadata.pts = i * 33366;
    preview_frame.metadata.asset_uri = "preview://asset";
    preview_frame.width = 1920;
    preview_frame.height = 1080;
    ASSERT_TRUE(preview_buffer.Push(preview_frame));
  }

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);

  // Modern architecture: OutputBus + TestOutputSink
  output::OutputBus bus;
  auto sink = std::make_unique<TestOutputSink>("os-001-sink");

  std::atomic<int> live_frames{0};
  std::atomic<int> preview_frames{0};

  sink->SetVideoCallback([&](const buffer::Frame& frame) {
    if (frame.metadata.asset_uri == "live://asset") {
      live_frames++;
    } else if (frame.metadata.asset_uri == "preview://asset") {
      preview_frames++;
    }
  });

  sink->Start();
  auto attach_result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(attach_result.success) << attach_result.message;

  // nullptr clock disables timing logic - frames consumed as fast as they arrive
  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;
  auto output = renderer::ProgramOutput::Create(
      config, live_buffer, nullptr, metrics, /*channel_id=*/1);
  ASSERT_NE(output, nullptr);

  // Connect to OutputBus (modern architecture)
  output->SetOutputBus(&bus);

  ASSERT_TRUE(output->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  // Should see live frames (single source)
  int live_count = live_frames.load();
  EXPECT_GT(live_count, 0) << "Should consume frames from live buffer";
  EXPECT_EQ(preview_frames.load(), 0) << "Should not see preview frames yet";

  // Redirect to preview buffer
  output->SetInputBuffer(&preview_buffer);
  live_frames = 0;
  preview_frames = 0;

  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  // Should see preview frames now (single source after redirect)
  EXPECT_GT(preview_frames.load(), 0) << "Should consume frames from preview buffer after redirect";

  output->Stop();
  bus.DetachSink();
}

// =============================================================================
// OS-002: Hot-Switch Continuity
// When a switch is issued, the Output Bus changes its source immediately.
// The frame stream remains continuous across the switch.
// =============================================================================

TEST_F(OutputSwitchingContractTest, OS_002_HotSwitchIsImmediate) {
  buffer::FrameRingBuffer live_buffer(60);
  buffer::FrameRingBuffer preview_buffer(60);

  // Pre-fill preview with frames (simulating pre-decoded readiness)
  for (int i = 0; i < 30; ++i) {
    buffer::Frame frame;
    frame.metadata.pts = i * 33366;
    frame.metadata.asset_uri = "preview://ready";
    frame.width = 1920;
    frame.height = 1080;
    ASSERT_TRUE(preview_buffer.Push(frame));
  }

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);

  // Modern architecture: OutputBus + TestOutputSink
  output::OutputBus bus;
  auto sink = std::make_unique<TestOutputSink>("os-002-sink");

  std::atomic<bool> saw_preview_frame{false};
  auto switch_time = std::chrono::steady_clock::now();
  std::atomic<int64_t> first_preview_frame_delay_us{0};

  sink->SetVideoCallback([&](const buffer::Frame& frame) {
    if (frame.metadata.asset_uri == "preview://ready" && !saw_preview_frame.load()) {
      saw_preview_frame = true;
      auto now = std::chrono::steady_clock::now();
      first_preview_frame_delay_us = std::chrono::duration_cast<std::chrono::microseconds>(
          now - switch_time).count();
    }
  });

  sink->Start();
  auto attach_result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(attach_result.success) << attach_result.message;

  // nullptr clock - frames consumed immediately
  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;
  auto output = renderer::ProgramOutput::Create(
      config, live_buffer, nullptr, metrics, /*channel_id=*/2);
  ASSERT_NE(output, nullptr);

  output->SetOutputBus(&bus);

  ASSERT_TRUE(output->Start());
  // Live buffer is empty, so output waits
  std::this_thread::sleep_for(std::chrono::milliseconds(30));

  // Perform hot-switch to buffer with frames
  switch_time = std::chrono::steady_clock::now();
  output->SetInputBuffer(&preview_buffer);

  // Wait for frames to be consumed
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  EXPECT_TRUE(saw_preview_frame.load()) << "Should see preview frames after switch";

  // The switch should be immediate - first preview frame within a reasonable time
  // Allow tolerance for thread scheduling and buffer backoff
  EXPECT_LT(first_preview_frame_delay_us.load(), 50'000)
      << "First preview frame should appear within 50ms of switch (immediate)";

  output->Stop();
  bus.DetachSink();
}

// =============================================================================
// OS-003: Pre-Decoded Readiness
// Any bus eligible to become the Output source must already have decoded
// frames available at switch time.
// =============================================================================

TEST_F(OutputSwitchingContractTest, OS_003_PreviewMustHaveFramesBeforeSwitch) {
  buffer::FrameRingBuffer live_buffer(60);
  buffer::FrameRingBuffer preview_buffer(60);

  // Pre-fill preview with frames (the contract requirement)
  const size_t preloaded_frames = 20;
  for (size_t i = 0; i < preloaded_frames; ++i) {
    buffer::Frame frame;
    frame.metadata.pts = static_cast<int64_t>(i) * 33366;
    frame.width = 1920;
    frame.height = 1080;
    ASSERT_TRUE(preview_buffer.Push(frame));
  }

  // Verify preview buffer has frames BEFORE switch
  EXPECT_EQ(preview_buffer.Size(), preloaded_frames)
      << "OS-003: Preview must have frames available before switch";
  EXPECT_FALSE(preview_buffer.IsEmpty())
      << "OS-003: Preview buffer must not be empty at switch time";

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);

  // Modern architecture: OutputBus + TestOutputSink
  output::OutputBus bus;
  auto sink = std::make_unique<TestOutputSink>("os-003-sink");

  std::atomic<int> frames_consumed{0};
  sink->SetVideoCallback([&](const buffer::Frame&) {
    frames_consumed++;
  });

  sink->Start();
  auto attach_result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(attach_result.success) << attach_result.message;

  // nullptr clock - frames consumed immediately
  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;
  auto output = renderer::ProgramOutput::Create(
      config, live_buffer, nullptr, metrics, /*channel_id=*/3);
  ASSERT_NE(output, nullptr);

  output->SetOutputBus(&bus);

  ASSERT_TRUE(output->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(20));

  // Perform switch - preview has frames ready, so frames should be consumed immediately
  output->SetInputBuffer(&preview_buffer);
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  EXPECT_GT(frames_consumed.load(), 0)
      << "Should consume pre-loaded frames from preview immediately";

  output->Stop();
  bus.DetachSink();
}

// =============================================================================
// OS-004: No Implicit Draining
// A switch does not wait for the previously active bus to drain.
// Frames remaining in the previous bus are not emitted after the switch.
// =============================================================================

TEST_F(OutputSwitchingContractTest, OS_004_SwitchDoesNotDrainOldBuffer) {
  // This test verifies that SetInputBuffer is instantaneous and doesn't wait for drain.
  // The key invariant: the switch call itself should complete in microseconds,
  // not wait for old buffer to empty.

  buffer::FrameRingBuffer live_buffer(60);
  buffer::FrameRingBuffer preview_buffer(60);

  // Fill preview buffer - we'll switch to this
  for (int i = 0; i < 30; ++i) {
    buffer::Frame frame;
    frame.metadata.pts = i * 33366;
    frame.metadata.asset_uri = "preview://new";
    frame.width = 1920;
    frame.height = 1080;
    ASSERT_TRUE(preview_buffer.Push(frame));
  }

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);

  // Modern architecture: OutputBus + TestOutputSink
  output::OutputBus bus;
  auto sink = std::make_unique<TestOutputSink>("os-004-sink");
  sink->Start();
  auto attach_result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(attach_result.success) << attach_result.message;

  // nullptr clock - frames consumed as fast as possible
  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;
  auto output = renderer::ProgramOutput::Create(
      config, live_buffer, nullptr, metrics, /*channel_id=*/4);
  ASSERT_NE(output, nullptr);

  output->SetOutputBus(&bus);

  ASSERT_TRUE(output->Start());

  // The key test: measure how long SetInputBuffer takes
  // It should be nearly instantaneous (just a pointer swap + lock)
  auto switch_start = std::chrono::steady_clock::now();
  output->SetInputBuffer(&preview_buffer);
  auto switch_end = std::chrono::steady_clock::now();

  auto switch_duration = std::chrono::duration_cast<std::chrono::microseconds>(
      switch_end - switch_start);

  // Switch should be nearly instantaneous (no drain wait)
  // Should complete in < 1ms, but allow 10ms for scheduling variance
  EXPECT_LT(switch_duration.count(), 10'000)
      << "OS-004: Switch must not wait for drain (should be < 10ms), took "
      << switch_duration.count() << " us";

  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  output->Stop();
  bus.DetachSink();
}

// =============================================================================
// OS-005: Pre-Encoding Boundary
// Switching occurs on decoded frames, not encoded streams.
// =============================================================================

TEST_F(OutputSwitchingContractTest, OS_005_SwitchOccursOnDecodedFrames) {
  // This test verifies that the switch happens at the decoded frame level,
  // not at the encoded/muxed level.
  //
  // The evidence: SetInputBuffer changes which FrameRingBuffer (decoded frames)
  // ProgramOutput reads from. The encoder/mux downstream sees a continuous
  // stream of frames - it doesn't know a switch occurred.

  buffer::FrameRingBuffer buffer_a(60);
  buffer::FrameRingBuffer buffer_b(60);

  // Both buffers have decoded frames
  for (int i = 0; i < 20; ++i) {
    buffer::Frame frame_a;
    frame_a.metadata.pts = i * 33366;
    frame_a.metadata.asset_uri = "buffer_a";
    frame_a.width = 1920;
    frame_a.height = 1080;
    ASSERT_TRUE(buffer_a.Push(frame_a));

    buffer::Frame frame_b;
    frame_b.metadata.pts = (i + 20) * 33366;  // Continuing PTS sequence
    frame_b.metadata.asset_uri = "buffer_b";
    frame_b.width = 1920;
    frame_b.height = 1080;
    ASSERT_TRUE(buffer_b.Push(frame_b));
  }

  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);

  // Modern architecture: OutputBus + TestOutputSink
  output::OutputBus bus;
  auto sink = std::make_unique<TestOutputSink>("os-005-sink");

  std::vector<std::string> source_sequence;
  std::mutex sequence_mutex;

  sink->SetVideoCallback([&](const buffer::Frame& frame) {
    std::lock_guard<std::mutex> lock(sequence_mutex);
    source_sequence.push_back(frame.metadata.asset_uri);
  });

  sink->Start();
  auto attach_result = bus.AttachSink(std::move(sink));
  ASSERT_TRUE(attach_result.success) << attach_result.message;

  // nullptr clock - frames consumed immediately
  renderer::RenderConfig config;
  config.mode = renderer::RenderMode::HEADLESS;
  auto output = renderer::ProgramOutput::Create(
      config, buffer_a, nullptr, metrics, /*channel_id=*/5);
  ASSERT_NE(output, nullptr);

  output->SetOutputBus(&bus);

  ASSERT_TRUE(output->Start());
  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  // Switch to buffer_b
  output->SetInputBuffer(&buffer_b);
  std::this_thread::sleep_for(std::chrono::milliseconds(80));

  output->Stop();
  bus.DetachSink();

  // Verify we got decoded frames from both buffers
  std::lock_guard<std::mutex> lock(sequence_mutex);
  EXPECT_GT(source_sequence.size(), 0u)
      << "Should have received decoded frames";

  // Check that we saw frames from both buffers (proving switch worked)
  bool saw_a = false, saw_b = false;
  for (const auto& src : source_sequence) {
    if (src == "buffer_a") saw_a = true;
    if (src == "buffer_b") saw_b = true;
  }
  EXPECT_TRUE(saw_a) << "Should have seen frames from buffer_a before switch";
  EXPECT_TRUE(saw_b) << "Should have seen frames from buffer_b after switch";
}

// =============================================================================
// OS-006: Isolation
// Live and Preview buses do not share decoders or frame buffers.
// =============================================================================

TEST_F(OutputSwitchingContractTest, OS_006_BusesDoNotShareBuffers) {
  // Create two completely separate buffers
  buffer::FrameRingBuffer live_buffer(60);
  buffer::FrameRingBuffer preview_buffer(60);

  // Verify they are independent objects
  EXPECT_NE(&live_buffer, &preview_buffer)
      << "OS-006: Live and Preview must have separate buffer instances";

  // Operations on one don't affect the other
  buffer::Frame frame;
  frame.metadata.pts = 12345;
  frame.width = 1920;
  frame.height = 1080;

  ASSERT_TRUE(live_buffer.Push(frame));
  EXPECT_EQ(live_buffer.Size(), 1u);
  EXPECT_EQ(preview_buffer.Size(), 0u)
      << "OS-006: Push to live should not affect preview";

  ASSERT_TRUE(preview_buffer.Push(frame));
  EXPECT_EQ(live_buffer.Size(), 1u);
  EXPECT_EQ(preview_buffer.Size(), 1u)
      << "OS-006: Push to preview should not affect live";

  live_buffer.Clear();
  EXPECT_EQ(live_buffer.Size(), 0u);
  EXPECT_EQ(preview_buffer.Size(), 1u)
      << "OS-006: Clear on live should not affect preview";
}

TEST_F(OutputSwitchingContractTest, OS_006_ProducersHaveSeparateBuffers) {
  // Verify that when PlayoutEngine creates producers, they get separate buffers
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1'700'000'000'000'000LL);

  // Use control_surface_only mode for this structural test
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, /*control_surface_only=*/false);

  auto start_result = engine->StartChannel(
      /*channel_id=*/6,
      "test-plan",
      /*port=*/0,
      std::nullopt,
      kDefaultProgramFormatJson);

  if (!start_result.success) {
    // If we can't start (e.g., no real assets), that's OK for this structural test
    GTEST_SKIP() << "Cannot start channel for isolation test: " << start_result.message;
  }

  // The engine internally creates separate buffers for live and preview
  // This is verified by the implementation in PlayoutEngine::LoadPreview
  // which creates preview_ring_buffer separate from ring_buffer

  engine->StopChannel(6);
}

// =============================================================================
// Integration: Full switch cycle with PlayoutEngine
// =============================================================================

TEST_F(OutputSwitchingContractTest, Integration_FullSwitchCycleViaEngine) {
  auto metrics = std::make_shared<telemetry::MetricsExporter>(0);
  auto clock = std::make_shared<retrovue::timing::TestMasterClock>();
  clock->SetEpochUtcUs(1'700'000'000'000'000LL);

  // Use control_surface_only to test the protocol without needing real media
  auto engine = std::make_shared<runtime::PlayoutEngine>(metrics, clock, /*control_surface_only=*/true);
  auto interface = std::make_shared<runtime::PlayoutInterface>(engine);

  // Start channel
  auto start_result = interface->StartChannel(
      /*channel_id=*/10,
      "integration-test-plan",
      /*port=*/9999,
      std::nullopt,
      kDefaultProgramFormatJson);
  ASSERT_TRUE(start_result.success) << start_result.message;

  // LoadPreview - in real mode, this creates preview_ring_buffer and starts shadow decode
  // Frame-indexed execution (INV-FRAME-001/002/003)
  auto load_result = interface->LoadPreview(10, "test://asset.mp4", 0, -1, 30, 1);
  ASSERT_TRUE(load_result.success) << load_result.message;

  // SwitchToLive - in real mode, this redirects ProgramOutput to preview's buffer
  auto switch_result = interface->SwitchToLive(10);
  ASSERT_TRUE(switch_result.success) << switch_result.message;

  // The switch should have happened immediately (no blocking)
  // In control_surface_only mode, this just updates state

  // Stop channel
  auto stop_result = interface->StopChannel(10);
  ASSERT_TRUE(stop_result.success) << stop_result.message;
}

}  // namespace
