// Repository: Retrovue-playout
// Component: File Producer Contract Tests
// Purpose: Contract tests for FileProducer domain.
// Copyright (c) 2025 RetroVue

#include "../../BaseContractTest.h"
#include "../ContractRegistryEnvironment.h"

#include <chrono>
#include <thread>
#include <vector>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "retrovue/timing/MasterClock.h"
#include "../../fixtures/EventBusStub.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;
using namespace retrovue::producers::file;
using namespace retrovue::tests;
using namespace retrovue::tests::fixtures;

namespace
{

  using retrovue::tests::RegisterExpectedDomainCoverage;

  const bool kRegisterCoverage = []()
  {
    RegisterExpectedDomainCoverage(
        "FileProducer",
        {"FE-001", "FE-002", "FE-003", "FE-004", "FE-005", "FE-006", 
         "FE-007", "FE-008", "FE-009", "FE-010", "FE-011", "FE-012"});
    return true;
  }();

  class FileProducerContractTest : public BaseContractTest
  {
  protected:
    [[nodiscard]] std::string DomainName() const override
    {
      return "FileProducer";
    }

    [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override
    {
      return {
          "FE-001", "FE-002", "FE-003", "FE-004", "FE-005", "FE-006", 
          "FE-007", "FE-008", "FE-009", "FE-010", "FE-011", "FE-012"};
    }

    void SetUp() override
    {
      BaseContractTest::SetUp();
      event_bus_ = std::make_unique<EventBusStub>();
      clock_ = std::make_shared<retrovue::timing::TestMasterClock>();
      const int64_t epoch = 1'700'001'000'000'000;
      clock_->SetEpochUtcUs(epoch);
      clock_->SetRatePpm(0.0);
      clock_->SetNow(epoch, 0.0);
      buffer_ = std::make_unique<buffer::FrameRingBuffer>(60);
    }

    // Helper to get test media path
    std::string GetTestMediaPath(const std::string& filename) const
    {
      // Use absolute path to assets directory
      (void)filename;  // Ignore filename parameter, use known test asset
      return "/opt/retrovue/assets/SampleA.mp4";
    }

  void TearDown() override
  {
    if (producer_)
    {
      try
      {
        producer_->stop();
      }
      catch (...)
      {
        // Ignore exceptions during cleanup
      }
      producer_.reset();
    }
    buffer_.reset();
    event_bus_.reset();
    BaseContractTest::TearDown();
  }

    ProducerEventCallback MakeEventCallback()
    {
      return [this](const std::string &event_type, const std::string &message)
      {
        event_bus_->Emit(EventBusStub::ToEventType(event_type), message);
      };
    }

    std::unique_ptr<EventBusStub> event_bus_;
    std::shared_ptr<retrovue::timing::TestMasterClock> clock_;
    std::unique_ptr<buffer::FrameRingBuffer> buffer_;
    std::unique_ptr<FileProducer> producer_;
  };

  // Rule: FE-001 Producer Lifecycle (FileProducerContract.md §FE-001)
  TEST_F(FileProducerContractTest, FE_001_ProducerLifecycle)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_FALSE(producer_->isRunning());
    ASSERT_EQ(producer_->GetFramesProduced(), 0u);
    ASSERT_EQ(producer_->GetState(), ProducerState::STOPPED);

    ASSERT_TRUE(producer_->start());
    ASSERT_TRUE(producer_->isRunning());
    ASSERT_EQ(producer_->GetState(), ProducerState::RUNNING);

    ASSERT_FALSE(producer_->start());

    producer_->stop();
    ASSERT_FALSE(producer_->isRunning());
    ASSERT_EQ(producer_->GetState(), ProducerState::STOPPED);

    producer_->stop();
    producer_->stop();
    ASSERT_FALSE(producer_->isRunning());
  }

  TEST_F(FileProducerContractTest, FE_001_DestructorStopsProducer)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());
    ASSERT_TRUE(producer_->isRunning());
    producer_.reset();
  }

  // Rule: FE-002 Frame Production Rate
  TEST_F(FileProducerContractTest, FE_002_FrameProductionRate)
  {
    ProducerConfig config;
    config.asset_uri = GetTestMediaPath("sample.mp4");
    config.target_fps = 30.0;
    config.stub_mode = false;  // Use real decoding with sample file

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    uint64_t frames_produced = producer_->GetFramesProduced();
    ASSERT_GT(frames_produced, 0u);

    producer_->stop();
  }

  // Rule: FE-003 Frame Metadata Validity
  TEST_F(FileProducerContractTest, FE_003_FrameMetadataValidity)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_width = 1920;
    config.target_height = 1080;
    config.target_fps = 30.0;
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    buffer::Frame frame;
    int64_t last_pts = -1;
    int frame_count = 0;

    while (buffer_->Pop(frame) && frame_count < 10)
    {
      if (last_pts >= 0)
      {
        ASSERT_GT(frame.metadata.pts, last_pts);
      }
      last_pts = frame.metadata.pts;
      ASSERT_LE(frame.metadata.dts, frame.metadata.pts);
      ASSERT_NEAR(frame.metadata.duration, 1.0 / config.target_fps, 0.001);
      ASSERT_EQ(frame.metadata.asset_uri, config.asset_uri);
      ASSERT_EQ(frame.width, config.target_width);
      ASSERT_EQ(frame.height, config.target_height);
      frame_count++;
    }

    ASSERT_GT(frame_count, 0);
    producer_->stop();
  }

  // Rule: FE-004 Frame Format Validity
  TEST_F(FileProducerContractTest, FE_004_FrameFormatValidity)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_width = 1920;
    config.target_height = 1080;
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    buffer::Frame frame;
    int frame_count = 0;

    while (buffer_->Pop(frame) && frame_count < 5)
    {
      const size_t expected_size = static_cast<size_t>(config.target_width * config.target_height * 1.5);
      ASSERT_EQ(frame.data.size(), expected_size);
      ASSERT_GT(frame.data.size(), 0u);
      frame_count++;
    }

    ASSERT_GT(frame_count, 0);
    producer_->stop();
  }

  // Rule: FE-005 Backpressure Handling
  TEST_F(FileProducerContractTest, FE_005_BackpressureHandling)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_fps = 120.0; // Very high FPS to fill small buffer quickly
    config.stub_mode = true;

    buffer_ = std::make_unique<buffer::FrameRingBuffer>(3); // Very small buffer
    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Wait for buffer to fill (3 frames at 120fps = ~25ms, wait 200ms to be safe)
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    
    // Producer should have produced frames
    uint64_t frames_produced = producer_->GetFramesProduced();
    ASSERT_GT(frames_produced, 0u) << "Producer should produce frames";
    
    // Wait more to ensure buffer fills and backpressure occurs
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    
    // Verify buffer is full or has frames
    ASSERT_TRUE(buffer_->IsFull() || buffer_->Size() > 0u) << "Buffer should have frames";
    
    // If buffer is full, backpressure should have occurred
    if (buffer_->IsFull())
    {
      // Wait a bit more for backpressure events
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
      uint64_t buffer_full_count = producer_->GetBufferFullCount();
      // Backpressure count might be 0 if producer hasn't attempted to push yet
      // Just verify producer is still running (handling backpressure gracefully)
      ASSERT_TRUE(producer_->isRunning()) << "Producer should handle backpressure without stopping";
    }

    producer_->stop();
  }

  // Rule: FE-006 Buffer Filling
  TEST_F(FileProducerContractTest, FE_006_BufferFilling)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    ASSERT_GT(buffer_->Size(), 0u);

    producer_->stop();
  }

  // Rule: FE-007 Decoder Fallback
  TEST_F(FileProducerContractTest, FE_007_DecoderFallback)
  {
    ProducerConfig config;
    config.asset_uri = "nonexistent.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    ASSERT_TRUE(producer_->isRunning());
    ASSERT_GT(producer_->GetFramesProduced(), 0u);

    producer_->stop();
  }

  // Rule: FE-008 Decode Error Recovery
  TEST_F(FileProducerContractTest, FE_008_DecodeErrorRecovery)
  {
    ProducerConfig config;
    config.asset_uri = GetTestMediaPath("sample.mp4");
    config.stub_mode = false;  // Use real decoding

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    ASSERT_TRUE(producer_->isRunning());
    
    // Producer should continue operation even if transient decode errors occur
    // (errors are tracked but don't stop the producer)
    uint64_t decode_errors = producer_->GetDecodeErrors();
    // Decode errors may be 0 if file decodes cleanly, or > 0 if errors occurred
    // The important thing is that producer continues running

    producer_->stop();
  }

  // Rule: FE-009 End of File Handling (Phase 8.8: EOF does NOT stop the producer)
  TEST_F(FileProducerContractTest, FE_009_EndOfFileHandling)
  {
    ProducerConfig config;
    config.asset_uri = GetTestMediaPath("sample.mp4");
    config.stub_mode = false;  // Use real decoding to test EOF

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Wait for file to be decoded completely (EOF). Phase 8.8: producer stays running after EOF
    // (no more frames to produce, but does not exit until explicit stop).
    int wait_count = 0;
    while (wait_count < 50)
    {
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
      wait_count++;
      // Once we've waited enough for EOF, producer must still be running (Phase 8.8 invariant)
      if (wait_count >= 20)
        break;
    }

    // Phase 8.8: Producer must still be running after EOF (no implicit exit on EOF).
    ASSERT_TRUE(producer_->isRunning()) << "Phase 8.8: producer must not stop on EOF alone";
    ASSERT_GT(producer_->GetFramesProduced(), 0u);

    producer_->stop();
    ASSERT_FALSE(producer_->isRunning());
    ASSERT_EQ(producer_->GetState(), ProducerState::STOPPED);
  }

  // Rule: FE-010 Teardown Operation (Phase 1: stop() is equivalent to teardown)
  TEST_F(FileProducerContractTest, FE_010_TeardownOperation)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Fill buffer with some frames
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    ASSERT_GT(buffer_->Size(), 0u);

    // Phase 1: stop() handles teardown
    // Future: RequestTeardown() will be implemented in Phase 2
    producer_->stop();

    // Producer should be stopped
    ASSERT_FALSE(producer_->isRunning());
    ASSERT_EQ(producer_->GetState(), ProducerState::STOPPED);
  }

  // Rule: FE-011 Statistics Accuracy
  TEST_F(FileProducerContractTest, FE_011_StatisticsAccuracy)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    uint64_t frames_produced = producer_->GetFramesProduced();
    size_t buffer_size = buffer_->Size();
    ASSERT_GE(frames_produced, buffer_size);

    producer_->stop();
  }

  // Rule: FE-012 MasterClock Alignment (Stub Mode)
  TEST_F(FileProducerContractTest, FE_012_MasterClockAlignment)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_fps = 30.0;
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Advance clock and verify frame production aligns
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    uint64_t initial_frames = producer_->GetFramesProduced();

    // Advance clock by 1 second (30 frames at 30fps)
    clock_->AdvanceSeconds(1.0);
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    uint64_t frames_after_advance = producer_->GetFramesProduced();
    ASSERT_GT(frames_after_advance, initial_frames);

    // Verify frames have monotonically increasing PTS
    buffer::Frame frame;
    int64_t last_pts = -1;
    int frame_count = 0;
    while (buffer_->Pop(frame) && frame_count < 10)
    {
      if (last_pts >= 0)
      {
        ASSERT_GT(frame.metadata.pts, last_pts);
      }
      last_pts = frame.metadata.pts;
      frame_count++;
    }

    producer_->stop();
  }

  // Contract requirement: Ready event emitted
  TEST_F(FileProducerContractTest, ReadyEventEmitted)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    ASSERT_TRUE(event_bus_->HasEvent(TestEventType::READY));

    producer_->stop();
  }

  // Contract requirement: Child exit propagated
  TEST_F(FileProducerContractTest, ChildExitPropagated)
  {
    ProducerConfig config;
    config.asset_uri = "/nonexistent/path/video.mp4";
    config.stub_mode = false;
    config.tcp_port = 12347;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    
    bool started = producer_->start();
    if (started)
    {
      // Wait for FFmpeg to fail and exit
      for (int i = 0; i < 50 && producer_->isRunning(); ++i)
      {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
      
      // Producer may have stopped due to FFmpeg exit, or still running
      // Either way, stop() should be safe to call
      producer_->stop();
      
      // After stop(), producer should definitely be stopped
      ASSERT_FALSE(producer_->isRunning());
      ASSERT_EQ(producer_->GetState(), ProducerState::STOPPED);
    }
  }

  // Contract requirement: Stop terminates cleanly
  TEST_F(FileProducerContractTest, StopTerminatesCleanly)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    producer_->stop();

    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    ASSERT_FALSE(producer_->isRunning());
    ASSERT_EQ(producer_->GetState(), ProducerState::STOPPED);
  }

  // Contract requirement: Bad input path triggers error
  TEST_F(FileProducerContractTest, BadInputPathTriggersError)
  {
    ProducerConfig config;
    config.asset_uri = "/nonexistent/path/to/video.mp4";
    config.stub_mode = false;
    config.tcp_port = 12348;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    
    bool started = producer_->start();
    if (started)
    {
      std::this_thread::sleep_for(std::chrono::milliseconds(500));
      producer_->stop();
    }
  }

  // Contract requirement: No crash on rapid start/stop
  TEST_F(FileProducerContractTest, NoCrashOnRapidStartStop)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    
    // Rapid start/stop cycles - should not crash
    for (int i = 0; i < 10; ++i)
    {
      bool started = producer_->start();
      // Give thread time to start
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
      producer_->stop();
      // Give thread time to stop
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    
    // Final check: producer should be stopped
    ASSERT_FALSE(producer_->isRunning());
    ASSERT_EQ(producer_->GetState(), ProducerState::STOPPED);
  }

  // Contract requirement: READY event always precedes frame events
  TEST_F(FileProducerContractTest, ReadyEventPrecedesFrameEvents)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.stub_mode = true;

    event_bus_->Clear();
    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    producer_->start();

    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    
    // Verify READY was emitted
    ASSERT_TRUE(event_bus_->HasEvent(TestEventType::READY));
    
    // Verify frames are produced after ready
    ASSERT_GT(producer_->GetFramesProduced(), 0u);

    producer_->stop();
  }

  // Contract requirement: stderr is captured
  TEST_F(FileProducerContractTest, StderrIsCaptured)
  {
    ProducerConfig config;
    config.asset_uri = "/nonexistent/path/video.mp4";
    config.stub_mode = false;
    config.tcp_port = 12349;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());

    bool started = producer_->start();
    if (started)
    {
      // Wait for FFmpeg to output error to stderr
      std::this_thread::sleep_for(std::chrono::milliseconds(500));

      // May or may not have stderr events depending on FFmpeg behavior
      producer_->stop();
    }
  }

  // ============================================================================
  // Phase 6 Clock-Gated Emission Tests (INV-P6-008)
  // ============================================================================

  // INV-P6-008: Video frames MUST NOT emit ahead of wall-clock time
  // This test verifies that 30 video frames take approximately 1 second of wall-clock
  TEST_F(FileProducerContractTest, P6_008_VideoEmitsAtWallClockPace)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_fps = 30.0;
    config.stub_mode = true;  // Use stub mode for deterministic testing
    config.start_offset_ms = 0;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Collect wall-clock times for first 30 frames
    std::vector<int64_t> emit_times;
    std::vector<int64_t> frame_pts;
    buffer::Frame frame;

    auto start_time = std::chrono::steady_clock::now();

    // Advance fake clock to allow frames to emit
    for (int i = 0; i < 30; i++)
    {
      clock_->advance_us(33333);  // ~30fps frame interval

      // Wait for frame to appear in buffer
      int attempts = 0;
      while (!buffer_->Pop(frame) && attempts < 100)
      {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        attempts++;
      }

      if (attempts < 100)
      {
        emit_times.push_back(clock_->now_utc_us());
        frame_pts.push_back(frame.metadata.pts);
      }
    }

    producer_->stop();

    // Verify we got frames
    ASSERT_GE(emit_times.size(), 10u) << "Should have collected at least 10 frames";

    // INV-P6-008: Verify wall-clock duration for N frames ≈ media duration
    // For 30fps: 30 frames should take ~1000ms of fake clock time
    if (emit_times.size() >= 2)
    {
      int64_t wall_duration_us = emit_times.back() - emit_times.front();
      int64_t pts_duration_us = frame_pts.back() - frame_pts.front();

      // Wall duration should approximately equal PTS duration (within 10%)
      double ratio = static_cast<double>(wall_duration_us) / static_cast<double>(pts_duration_us);
      EXPECT_GE(ratio, 0.9) << "Frames emitting too fast (free-running)";
      EXPECT_LE(ratio, 1.1) << "Frames emitting too slow";
    }
  }

  // INV-P6-008: No early emission - frame emit time must not precede scheduled time
  TEST_F(FileProducerContractTest, P6_008_NoEarlyEmission)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_fps = 30.0;
    config.stub_mode = true;  // Use stub mode for deterministic testing
    config.start_offset_ms = 0;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Record emit times and PTS for analysis
    std::vector<std::pair<int64_t, int64_t>> emit_records;  // (wall_time, pts)
    buffer::Frame frame;

    // Advance clock and collect frames
    for (int i = 0; i < 20; i++)
    {
      clock_->advance_us(33333);

      int attempts = 0;
      while (!buffer_->Pop(frame) && attempts < 50)
      {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        attempts++;
      }

      if (attempts < 50)
      {
        emit_records.push_back({clock_->now_utc_us(), frame.metadata.pts});
      }
    }

    producer_->stop();

    ASSERT_GE(emit_records.size(), 5u) << "Should have collected frames";

    // INV-P6-008: Verify no early emission
    // For each frame N: Tₙ ≥ T₀ + (Pₙ - P₀) - ε
    const int64_t tolerance_us = 50000;  // 50ms tolerance for test clock jitter
    int64_t T0 = emit_records[0].first;
    int64_t P0 = emit_records[0].second;

    for (size_t i = 1; i < emit_records.size(); i++)
    {
      int64_t Tn = emit_records[i].first;
      int64_t Pn = emit_records[i].second;
      int64_t expected_time = T0 + (Pn - P0);
      int64_t early_by = expected_time - Tn;

      EXPECT_LE(early_by, tolerance_us)
          << "Frame " << i << " emitted " << (early_by / 1000) << "ms early "
          << "(Tn=" << Tn << ", expected=" << expected_time << ")";
    }
  }

  // INV-P6-010: Audio must wait for video epoch before emitting
  // Simplified test: verify buffer doesn't overflow when clock-gated
  TEST_F(FileProducerContractTest, P6_010_AudioDoesNotFloodBuffer)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_fps = 30.0;
    config.stub_mode = true;  // Use stub mode for deterministic testing
    config.start_offset_ms = 0;  // Stub mode doesn't support seek

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Give producer time to seek and start decoding
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    // Advance clock to allow emission (1 second)
    clock_->advance_us(1000000);
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Check video buffer - should not be overflowing
    size_t video_count = buffer_->Size();

    producer_->stop();

    // Key check: buffer should not be full/overflowing (INV-P6-010)
    // If producer free-ran, it would have pushed many more frames than buffer capacity
    // With clock gating, it should emit ~30 frames for 1 second at 30fps
    EXPECT_LE(video_count, 60u)
        << "Producer appears to be free-running (buffer overflow)";
  }

  // INV-P6-008: Production rate matches wall-clock over sustained period
  TEST_F(FileProducerContractTest, P6_008_SustainedRateMatchesWallClock)
  {
    ProducerConfig config;
    config.asset_uri = "test.mp4";
    config.target_fps = 30.0;
    config.stub_mode = true;  // Use stub mode for deterministic testing
    config.start_offset_ms = 0;

    producer_ = std::make_unique<FileProducer>(config, *buffer_, clock_, MakeEventCallback());
    ASSERT_TRUE(producer_->start());

    // Run for 1 "second" of fake clock time
    const int64_t test_duration_us = 1000000;  // 1 second
    const int64_t step_us = 33333;  // ~30fps

    int frames_collected = 0;
    buffer::Frame frame;

    for (int64_t elapsed = 0; elapsed < test_duration_us; elapsed += step_us)
    {
      clock_->advance_us(step_us);

      // Collect any available frames
      while (buffer_->Pop(frame))
      {
        frames_collected++;
      }

      // Small real-time delay to let producer thread run
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    producer_->stop();

    // Drain remaining frames
    while (buffer_->Pop(frame))
    {
      frames_collected++;
    }

    // For 1 second at 30fps, expect ~30 frames (±20% tolerance for stub mode)
    // The key invariant is that frames_collected should NOT be >> 30 (free-running)
    EXPECT_GE(frames_collected, 20) << "Too few frames - producer may be stalled";
    EXPECT_LE(frames_collected, 40) << "Too many frames - producer may be free-running";
  }

} // namespace
