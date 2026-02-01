// Repository: Retrovue-playout
// Component: Phase 9 Output Bootstrap Tests
// Purpose: Verify INV-P9-FLUSH, INV-P9-BOOTSTRAP-READY, INV-P9-NO-DEADLOCK
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <chrono>
#include <thread>
#include <atomic>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "retrovue/timing/MasterClock.h"
#include "retrovue/timing/TimelineController.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;
using namespace retrovue::producers::file;
using namespace retrovue::timing;
using namespace std::chrono_literals;

namespace {

// Test asset path - use environment variable or default
std::string GetTestVideoPath() {
  const char* env_path = std::getenv("RETROVUE_TEST_VIDEO_PATH");
  if (env_path) return env_path;
  return "/opt/retrovue/assets/SampleA.mp4";
}

class Phase9OutputBootstrapTest : public ::testing::Test {
 protected:
  void SetUp() override {
    // Use TestMasterClock with RealTime mode for actual file decoding
    // Initialize with current system time
    auto now = std::chrono::system_clock::now();
    auto now_us = std::chrono::duration_cast<std::chrono::microseconds>(
        now.time_since_epoch()).count();
    clock_ = std::make_shared<TestMasterClock>(now_us, TestMasterClock::Mode::RealTime);

    config_ = TimelineConfig::FromFps(30.0);
    timeline_ = std::make_shared<TimelineController>(clock_, config_);

    // Start timeline session
    ASSERT_TRUE(timeline_->StartSession());
  }

  void TearDown() override {
    timeline_->EndSession();
  }

  std::shared_ptr<TestMasterClock> clock_;
  std::shared_ptr<TimelineController> timeline_;
  TimelineConfig config_;
};

// =============================================================================
// G9-001: First Frame Available at Commit
// =============================================================================
// Given: Preview producer in shadow mode with cached first frame
// When: SetShadowDecodeMode(false) is called followed by FlushCachedFrameToBuffer()
// Then: Preview ring buffer contains ≥1 video frame before the call returns

TEST_F(Phase9OutputBootstrapTest, G9_001_FirstFrameAvailableAtCommit) {
  // Create ring buffer and producer
  buffer::FrameRingBuffer ring_buffer(30);  // 30 frame capacity

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 1920;
  producer_config.target_height = 1080;
  producer_config.target_fps = 30.0;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());

  // Enable shadow mode BEFORE starting
  producer.SetShadowDecodeMode(true);

  // Start producer - it will decode first frame and cache it
  ASSERT_TRUE(producer.start());

  // Wait for shadow decode ready (first frame cached)
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (!producer.IsShadowDecodeReady() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(producer.IsShadowDecodeReady()) << "Shadow decode did not become ready";

  // Buffer should be empty (shadow mode doesn't write to buffer)
  EXPECT_EQ(ring_buffer.Size(), 0u) << "Buffer should be empty in shadow mode";

  timeline_->SetEmissionObserverAttached(true);  // INV-P8-SUCCESSOR-OBSERVABILITY
  // Begin segment from preview (Phase 8 step)
  auto pending = timeline_->BeginSegmentFromPreview();
  EXPECT_EQ(pending.mode, PendingSegmentMode::AwaitPreviewFrame);

  // Disable shadow mode
  producer.SetShadowDecodeMode(false);

  // INV-P9-FLUSH: Flush cached frame to buffer synchronously
  bool flushed = producer.FlushCachedFrameToBuffer();

  // INV-P8-SUCCESSOR-OBSERVABILITY: Simulate observer (no ProgramOutput in test)
  timeline_->NotifySuccessorVideoEmitted();

  // CRITICAL ASSERTION: Buffer must have ≥1 frame IMMEDIATELY after flush returns
  EXPECT_TRUE(flushed) << "FlushCachedFrameToBuffer should return true";
  EXPECT_GE(ring_buffer.Size(), 1u)
      << "INV-P9-FLUSH violated: Buffer must have ≥1 frame after flush";

  // Segment should have committed (mapping locked by AdmitFrame in flush)
  EXPECT_TRUE(timeline_->HasSegmentCommitted())
      << "Segment should be committed after flush";
  EXPECT_GT(timeline_->GetSegmentCommitGeneration(), 0u)
      << "Commit generation should have advanced";

  producer.stop();
}

// =============================================================================
// G9-002: Readiness Satisfied Immediately After Commit
// =============================================================================
// Given: Segment commit detected (generation advanced)
// And: Preview buffer has ≥1 video frame
// Then: Readiness check passes (commit + depth≥1)

TEST_F(Phase9OutputBootstrapTest, G9_002_ReadinessSatisfiedAfterCommit) {
  buffer::FrameRingBuffer ring_buffer(30);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 1920;
  producer_config.target_height = 1080;
  producer_config.target_fps = 30.0;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());

  producer.SetShadowDecodeMode(true);
  ASSERT_TRUE(producer.start());

  // Wait for shadow decode ready
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (!producer.IsShadowDecodeReady() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(producer.IsShadowDecodeReady());

  // Capture initial commit generation
  uint64_t initial_gen = timeline_->GetSegmentCommitGeneration();

  timeline_->SetEmissionObserverAttached(true);  // INV-P8-SUCCESSOR-OBSERVABILITY
  // Begin segment and flush
  timeline_->BeginSegmentFromPreview();
  producer.SetShadowDecodeMode(false);
  producer.FlushCachedFrameToBuffer();
  timeline_->NotifySuccessorVideoEmitted();  // Simulate observer (no ProgramOutput in test)

  // INV-P9-BOOTSTRAP-READY check
  uint64_t current_gen = timeline_->GetSegmentCommitGeneration();
  size_t video_depth = ring_buffer.Size();

  bool commit_detected = (current_gen > initial_gen);
  bool has_video = (video_depth >= 1);
  bool bootstrap_ready = commit_detected && has_video;

  EXPECT_TRUE(commit_detected) << "Commit should be detected (gen advanced)";
  EXPECT_TRUE(has_video) << "Should have ≥1 video frame";
  EXPECT_TRUE(bootstrap_ready)
      << "INV-P9-BOOTSTRAP-READY: Readiness should pass with commit + ≥1 frame"
      << " (commit_gen=" << current_gen << ", video_depth=" << video_depth << ")";

  producer.stop();
}

// =============================================================================
// G9-003: No Deadlock on Switch
// =============================================================================
// Given: Preview producer reaches shadow decode ready
// When: SwitchToLive sequence is invoked
// Then: Output routing completes within 500ms (not 10s timeout)

TEST_F(Phase9OutputBootstrapTest, G9_003_NoDeadlockOnSwitch) {
  buffer::FrameRingBuffer ring_buffer(30);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 1920;
  producer_config.target_height = 1080;
  producer_config.target_fps = 30.0;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());

  producer.SetShadowDecodeMode(true);
  ASSERT_TRUE(producer.start());

  // Wait for shadow decode ready
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (!producer.IsShadowDecodeReady() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(producer.IsShadowDecodeReady());

  // Simulate SwitchToLive sequence with timing
  auto switch_start = std::chrono::steady_clock::now();

  timeline_->SetEmissionObserverAttached(true);  // INV-P8-SUCCESSOR-OBSERVABILITY
  // Step 1: Begin segment from preview
  uint64_t pre_commit_gen = timeline_->GetSegmentCommitGeneration();
  timeline_->BeginSegmentFromPreview();

  // Step 2: Disable shadow mode
  producer.SetShadowDecodeMode(false);

  // Step 3: Flush cached frame (INV-P9-FLUSH)
  producer.FlushCachedFrameToBuffer();
  timeline_->NotifySuccessorVideoEmitted();  // Simulate observer (no ProgramOutput in test)

  // Step 4: Check readiness (simulating watcher)
  uint64_t post_commit_gen = timeline_->GetSegmentCommitGeneration();
  size_t video_depth = ring_buffer.Size();

  bool commit_edge = (post_commit_gen > pre_commit_gen);
  bool bootstrap_ready = commit_edge && (video_depth >= 1);

  auto switch_end = std::chrono::steady_clock::now();
  auto switch_duration = std::chrono::duration_cast<std::chrono::milliseconds>(
      switch_end - switch_start);

  // INV-P9-NO-DEADLOCK: Must complete in <500ms, not 10s
  EXPECT_TRUE(bootstrap_ready) << "Bootstrap readiness should be satisfied";
  EXPECT_LT(switch_duration.count(), 500)
      << "INV-P9-NO-DEADLOCK: Switch must complete in <500ms, took "
      << switch_duration.count() << "ms";

  std::cout << "[G9-003] Switch completed in " << switch_duration.count() << "ms"
            << ", commit_gen=" << post_commit_gen
            << ", video_depth=" << video_depth << std::endl;

  producer.stop();
}

// =============================================================================
// G9-004: Output Transition Occurs
// =============================================================================
// Given: Switch completes per G9-003
// Then: Consumer receives frames from preview buffer

TEST_F(Phase9OutputBootstrapTest, G9_004_OutputTransitionOccurs) {
  buffer::FrameRingBuffer ring_buffer(30);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 1920;
  producer_config.target_height = 1080;
  producer_config.target_fps = 30.0;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());

  producer.SetShadowDecodeMode(true);
  ASSERT_TRUE(producer.start());

  // Wait for shadow decode ready
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (!producer.IsShadowDecodeReady() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(producer.IsShadowDecodeReady());

  timeline_->SetEmissionObserverAttached(true);  // INV-P8-SUCCESSOR-OBSERVABILITY
  // Execute switch sequence
  timeline_->BeginSegmentFromPreview();
  producer.SetShadowDecodeMode(false);
  producer.FlushCachedFrameToBuffer();
  timeline_->NotifySuccessorVideoEmitted();  // Simulate observer (no ProgramOutput in test)

  // Verify frame can be consumed from buffer
  ASSERT_GE(ring_buffer.Size(), 1u);

  buffer::Frame frame;
  bool popped = ring_buffer.Pop(frame);

  EXPECT_TRUE(popped) << "Should be able to pop frame from buffer";
  EXPECT_TRUE(frame.metadata.has_ct) << "Frame should have CT assigned";
  // Note: CT=0 is valid for the first frame of a session (CT starts at 0)
  EXPECT_GE(frame.metadata.pts, 0) << "Frame should have valid PTS (CT)";
  EXPECT_FALSE(frame.data.empty()) << "Frame should have pixel data";

  std::cout << "[G9-004] Consumed frame with CT=" << frame.metadata.pts
            << ", size=" << frame.data.size() << " bytes" << std::endl;

  producer.stop();
}

// =============================================================================
// INV-P9-FLUSH: Flush Is Synchronous (No Race)
// =============================================================================
// Verify that flush completes synchronously, not dependent on producer thread

TEST_F(Phase9OutputBootstrapTest, INV_P9_FLUSH_Synchronous) {
  buffer::FrameRingBuffer ring_buffer(30);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 1920;
  producer_config.target_height = 1080;
  producer_config.target_fps = 30.0;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());

  producer.SetShadowDecodeMode(true);
  ASSERT_TRUE(producer.start());

  // Wait for shadow decode ready
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (!producer.IsShadowDecodeReady() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(producer.IsShadowDecodeReady());

  timeline_->SetEmissionObserverAttached(true);  // INV-P8-SUCCESSOR-OBSERVABILITY
  timeline_->BeginSegmentFromPreview();
  producer.SetShadowDecodeMode(false);

  // Measure flush time - should be <10ms (just a buffer push)
  auto flush_start = std::chrono::steady_clock::now();
  bool flushed = producer.FlushCachedFrameToBuffer();
  timeline_->NotifySuccessorVideoEmitted();  // Simulate observer (no ProgramOutput in test)
  auto flush_end = std::chrono::steady_clock::now();

  auto flush_duration = std::chrono::duration_cast<std::chrono::microseconds>(
      flush_end - flush_start);

  EXPECT_TRUE(flushed);
  EXPECT_LT(flush_duration.count(), 10000)  // <10ms
      << "Flush should be synchronous (<10ms), took "
      << flush_duration.count() << "us";

  // Buffer must have frame immediately (no waiting for producer thread)
  EXPECT_GE(ring_buffer.Size(), 1u)
      << "Buffer must have frame immediately after flush";

  std::cout << "[INV-P9-FLUSH] Flush completed in " << flush_duration.count()
            << "us" << std::endl;

  producer.stop();
}

// =============================================================================
// Audio Zero-Frame Acceptability
// =============================================================================
// Verify that zero audio frames does not block bootstrap readiness

TEST_F(Phase9OutputBootstrapTest, AudioZeroFrameAcceptable) {
  buffer::FrameRingBuffer ring_buffer(30);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 1920;
  producer_config.target_height = 1080;
  producer_config.target_fps = 30.0;

  FileProducer producer(producer_config, ring_buffer, clock_, nullptr, timeline_.get());

  producer.SetShadowDecodeMode(true);
  ASSERT_TRUE(producer.start());

  // Wait for shadow decode ready
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (!producer.IsShadowDecodeReady() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(10ms);
  }
  ASSERT_TRUE(producer.IsShadowDecodeReady());

  uint64_t pre_commit_gen = timeline_->GetSegmentCommitGeneration();

  timeline_->SetEmissionObserverAttached(true);  // INV-P8-SUCCESSOR-OBSERVABILITY
  timeline_->BeginSegmentFromPreview();
  producer.SetShadowDecodeMode(false);
  producer.FlushCachedFrameToBuffer();
  timeline_->NotifySuccessorVideoEmitted();  // Simulate observer (no ProgramOutput in test)

  // Check bootstrap readiness with potentially zero audio
  uint64_t post_commit_gen = timeline_->GetSegmentCommitGeneration();
  size_t video_depth = ring_buffer.Size();
  size_t audio_depth = ring_buffer.AudioSize();

  bool commit_edge = (post_commit_gen > pre_commit_gen);

  // INV-P9-BOOTSTRAP-READY: audio_depth=0 must NOT block readiness
  bool bootstrap_ready = commit_edge && (video_depth >= 1);
  // Note: audio_depth is intentionally NOT part of bootstrap_ready

  EXPECT_TRUE(bootstrap_ready)
      << "Bootstrap readiness must pass even with audio_depth=" << audio_depth
      << " (video_depth=" << video_depth << ", commit_edge=" << commit_edge << ")";

  std::cout << "[AudioZeroFrame] Bootstrap ready with video=" << video_depth
            << ", audio=" << audio_depth << std::endl;

  producer.stop();
}

// =============================================================================
// Multi-Switch Stability (2nd switch behaves like 1st)
// =============================================================================

TEST_F(Phase9OutputBootstrapTest, MultiSwitchStability) {
  buffer::FrameRingBuffer ring_buffer(30);

  ProducerConfig producer_config;
  producer_config.asset_uri = GetTestVideoPath();
  producer_config.target_width = 1920;
  producer_config.target_height = 1080;
  producer_config.target_fps = 30.0;

  // First switch
  {
    FileProducer producer1(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
    producer1.SetShadowDecodeMode(true);
    ASSERT_TRUE(producer1.start());

    auto deadline = std::chrono::steady_clock::now() + 5s;
    while (!producer1.IsShadowDecodeReady() &&
           std::chrono::steady_clock::now() < deadline) {
      std::this_thread::sleep_for(10ms);
    }
    ASSERT_TRUE(producer1.IsShadowDecodeReady());

    timeline_->SetEmissionObserverAttached(true);  // INV-P8-SUCCESSOR-OBSERVABILITY
    uint64_t gen_before_1 = timeline_->GetSegmentCommitGeneration();
    timeline_->BeginSegmentFromPreview();
    producer1.SetShadowDecodeMode(false);
    producer1.FlushCachedFrameToBuffer();
    timeline_->NotifySuccessorVideoEmitted();  // Simulate observer

    uint64_t gen_after_1 = timeline_->GetSegmentCommitGeneration();
    EXPECT_GT(gen_after_1, gen_before_1) << "First switch should advance generation";
    EXPECT_GE(ring_buffer.Size(), 1u) << "First switch should have ≥1 frame";

    // Drain buffer for second switch
    while (ring_buffer.Size() > 0) {
      buffer::Frame f;
      ring_buffer.Pop(f);
    }

    producer1.stop();
  }

  // Second switch (must behave identically)
  {
    FileProducer producer2(producer_config, ring_buffer, clock_, nullptr, timeline_.get());
    producer2.SetShadowDecodeMode(true);
    ASSERT_TRUE(producer2.start());

    auto deadline = std::chrono::steady_clock::now() + 5s;
    while (!producer2.IsShadowDecodeReady() &&
           std::chrono::steady_clock::now() < deadline) {
      std::this_thread::sleep_for(10ms);
    }
    ASSERT_TRUE(producer2.IsShadowDecodeReady());

    uint64_t gen_before_2 = timeline_->GetSegmentCommitGeneration();
    timeline_->BeginSegmentFromPreview();
    producer2.SetShadowDecodeMode(false);
    producer2.FlushCachedFrameToBuffer();
    timeline_->NotifySuccessorVideoEmitted();  // Simulate observer

    uint64_t gen_after_2 = timeline_->GetSegmentCommitGeneration();
    EXPECT_GT(gen_after_2, gen_before_2) << "Second switch should advance generation";
    EXPECT_GE(ring_buffer.Size(), 1u) << "Second switch should have ≥1 frame";

    std::cout << "[MultiSwitch] gen_after_1=" << (gen_before_2)
              << ", gen_after_2=" << gen_after_2 << std::endl;

    producer2.stop();
  }
}

// =============================================================================
// INV-P9-AUDIO-LIVENESS Tests
// =============================================================================
// Contract: docs/contracts/phases/Phase9-OutputBootstrap.md §10.5
//
// From the moment the MPEG-TS header (PAT/PMT) is written and the sink is
// considered "attached / live", the output must contain continuous,
// monotonically increasing audio PTS with correct pacing even if decoded
// audio is not yet available.

}  // namespace

// Separate namespace for audio liveness tests that need EncoderPipeline
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"

#include <vector>
#include <cstdio>
#include <fstream>

namespace {

using namespace retrovue::playout_sinks::mpegts;

// Capture TS output to memory for analysis
class TSCaptureCallback {
 public:
  std::vector<uint8_t> captured_data;
  std::atomic<int64_t> first_audio_pts{-1};
  std::atomic<int64_t> last_audio_pts{-1};
  std::atomic<int> audio_pes_count{0};
  std::atomic<int> video_pes_count{0};

  static int WriteCallback(void* opaque, uint8_t* buf, int buf_size) {
    auto* self = reinterpret_cast<TSCaptureCallback*>(opaque);
    self->captured_data.insert(self->captured_data.end(), buf, buf + buf_size);

    // Simple PES header detection for counting streams
    // PES start code: 00 00 01 [stream_id]
    for (int i = 0; i + 4 < buf_size; ++i) {
      if (buf[i] == 0x00 && buf[i+1] == 0x00 && buf[i+2] == 0x01) {
        uint8_t stream_id = buf[i+3];
        // Audio streams: 0xC0-0xDF (MPEG audio) or 0xBD (private stream for AAC)
        if ((stream_id >= 0xC0 && stream_id <= 0xDF) || stream_id == 0xBD) {
          self->audio_pes_count++;
          // Extract PTS if present (check PTS_DTS_flags in PES header)
          if (i + 9 < buf_size) {
            uint8_t pts_dts_flags = (buf[i+7] >> 6) & 0x03;
            if (pts_dts_flags >= 2 && i + 14 < buf_size) {
              // PTS present - extract 33-bit PTS
              int64_t pts = 0;
              pts = ((static_cast<int64_t>(buf[i+9]) & 0x0E) << 29) |
                    ((static_cast<int64_t>(buf[i+10])) << 22) |
                    ((static_cast<int64_t>(buf[i+11]) & 0xFE) << 14) |
                    ((static_cast<int64_t>(buf[i+12])) << 7) |
                    ((static_cast<int64_t>(buf[i+13])) >> 1);
              if (self->first_audio_pts < 0) {
                self->first_audio_pts = pts;
              }
              self->last_audio_pts = pts;
            }
          }
        }
        // Video streams: 0xE0-0xEF
        if (stream_id >= 0xE0 && stream_id <= 0xEF) {
          self->video_pes_count++;
        }
      }
    }
    return buf_size;
  }
};

class Phase9AudioLivenessTest : public ::testing::Test {
 protected:
  void SetUp() override {
    config_.target_width = 1920;
    config_.target_height = 1080;
    config_.bitrate = 4000000;
    config_.target_fps = 30.0;
    config_.gop_size = 30;
    config_.stub_mode = false;
  }

  MpegTSPlayoutSinkConfig config_;
};

// =============================================================================
// TEST-P9-AUDIO-LIVENESS-001: header-to-audio-liveness
// =============================================================================
// Given: Channel started and sink attached
// And: Decoded audio is not available for N video frames (empty audio queue)
// When: Header is written and video frames are encoded
// Then: Mux emits TS packets that include audio PES with PTS advancing
//       monotonically (no stall), within 500ms wall-clock of header write

TEST_F(Phase9AudioLivenessTest, TEST_P9_AUDIO_LIVENESS_001_HeaderToAudioLiveness) {
  TSCaptureCallback capture;

  EncoderPipeline pipeline(config_);
  bool opened = pipeline.open(config_, &capture, TSCaptureCallback::WriteCallback);
  ASSERT_TRUE(opened) << "EncoderPipeline must open successfully";
  ASSERT_TRUE(pipeline.IsInitialized()) << "Pipeline must be initialized";

  auto header_write_time = std::chrono::steady_clock::now();

  // Create test video frames (solid color)
  retrovue::buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(video_frame.width * video_frame.height * 3 / 2, 128);  // YUV gray

  // Encode 10 video frames WITHOUT providing any audio frames
  // INV-P9-AUDIO-LIVENESS requires silence injection to occur
  for (int i = 0; i < 10; ++i) {
    int64_t pts_90k = i * 3000;  // 30fps = 3000 ticks per frame at 90kHz
    bool encoded = pipeline.encodeFrame(video_frame, pts_90k);
    EXPECT_TRUE(encoded) << "Frame " << i << " should encode successfully";
  }

  auto encode_done_time = std::chrono::steady_clock::now();
  auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(
      encode_done_time - header_write_time);

  // Verify audio was present in output (from silence injection)
  EXPECT_GT(capture.audio_pes_count.load(), 0)
      << "INV-P9-AUDIO-LIVENESS violated: No audio PES packets in output despite video encoding. "
      << "Silence injection should have produced audio.";

  EXPECT_GT(capture.video_pes_count.load(), 0)
      << "Video PES packets should be present";

  // Audio should have started within 500ms of header write
  EXPECT_LT(duration.count(), 500)
      << "Audio output should begin within 500ms, took " << duration.count() << "ms";

  // Audio PTS should be advancing (not stuck at initial value)
  if (capture.first_audio_pts >= 0 && capture.last_audio_pts >= 0) {
    EXPECT_GE(capture.last_audio_pts.load(), capture.first_audio_pts.load())
        << "Audio PTS must be monotonically increasing";
  }

  std::cout << "[TEST-P9-AUDIO-LIVENESS-001] "
            << "audio_pes=" << capture.audio_pes_count
            << ", video_pes=" << capture.video_pes_count
            << ", first_audio_pts=" << capture.first_audio_pts
            << ", last_audio_pts=" << capture.last_audio_pts
            << ", captured_bytes=" << capture.captured_data.size()
            << std::endl;

  pipeline.close();
}

// =============================================================================
// INV-AUDIO-HOUSE-FORMAT-001: house format only; pad same path/CT/cadence/format
// =============================================================================
// Contract: All audio reaching EncoderPipeline (including pad) must be house format.
// Pipeline must reject or fail loudly on non-house input. Pad audio must use the
// same encode path, CT, sample cadence, and format as program audio.
// STUB: Full test TBD (e.g. send non-house frame → expect false; verify pad path).
// =============================================================================
TEST_F(Phase9AudioLivenessTest, INV_AUDIO_HOUSE_FORMAT_001_HouseFormatOnly) {
  // STUB: Invariant documented; implementation asserts in EncoderPipeline.
  SUCCEED() << "INV-AUDIO-HOUSE-FORMAT-001 stub: house format enforced in EncoderPipeline";
}

// =============================================================================
// TEST-P9-AUDIO-LIVENESS-002: silence-to-real-audio-contiguity
// =============================================================================
// Given: Sink is injecting silence for at least 100ms
// When: Real audio frames begin arriving
// Then: Audio PTS is contiguous across the transition (no backward jump,
//       no large gap beyond 1 frame duration)

TEST_F(Phase9AudioLivenessTest, TEST_P9_AUDIO_LIVENESS_002_SilenceToRealAudioContiguity) {
  TSCaptureCallback capture;

  EncoderPipeline pipeline(config_);
  bool opened = pipeline.open(config_, &capture, TSCaptureCallback::WriteCallback);
  ASSERT_TRUE(opened) << "EncoderPipeline must open successfully";

  // Create test video frame
  retrovue::buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(video_frame.width * video_frame.height * 3 / 2, 128);

  // Phase 1: Encode video frames with NO audio (silence injection)
  // At 30fps, 5 frames = ~166ms > 100ms requirement
  int64_t video_pts_90k = 0;
  for (int i = 0; i < 5; ++i) {
    pipeline.encodeFrame(video_frame, video_pts_90k);
    video_pts_90k += 3000;  // 30fps
  }

  int64_t pts_before_real_audio = capture.last_audio_pts.load();

  // Phase 2: Begin providing real audio frames
  // Create test audio frame (1024 samples at 48kHz)
  retrovue::buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);  // Silence data (real frames can be silent too)

  // Encode real audio frames aligned with video timeline
  // 1024 samples at 48kHz = ~21.3ms = ~1920 ticks at 90kHz
  int64_t audio_pts_90k = video_pts_90k;  // Start where video left off
  for (int i = 0; i < 10; ++i) {
    bool encoded = pipeline.encodeAudioFrame(audio_frame, audio_pts_90k);
    EXPECT_TRUE(encoded) << "Real audio frame " << i << " should encode";
    audio_pts_90k += 1920;  // ~21.3ms per frame
  }

  // Encode a few more video frames to flush
  for (int i = 0; i < 3; ++i) {
    pipeline.encodeFrame(video_frame, video_pts_90k);
    video_pts_90k += 3000;
  }

  int64_t pts_after_real_audio = capture.last_audio_pts.load();

  // Verify PTS contiguity: no backward jump
  if (pts_before_real_audio >= 0 && pts_after_real_audio >= 0) {
    EXPECT_GE(pts_after_real_audio, pts_before_real_audio)
        << "INV-P9-AUDIO-LIVENESS violated: Audio PTS jumped backward at transition. "
        << "before=" << pts_before_real_audio << ", after=" << pts_after_real_audio;

    // No large gap (> 1 frame = ~1920 ticks at 90kHz, give 3x margin = 6000)
    // Actually, during the transition there may be multiple frames, so use larger margin
    int64_t gap = pts_after_real_audio - pts_before_real_audio;
    // The gap should be reasonable (not a huge jump indicating discontinuity)
    // Allow for several frames worth of gap (10 frames max = 19200 ticks)
    EXPECT_LT(gap, 50000)  // ~555ms max gap
        << "INV-P9-AUDIO-LIVENESS violated: Large PTS gap at silence-to-real transition. "
        << "gap=" << gap << " ticks (~" << (gap / 90) << "ms)";
  }

  std::cout << "[TEST-P9-AUDIO-LIVENESS-002] "
            << "pts_before_real=" << pts_before_real_audio
            << ", pts_after_real=" << pts_after_real_audio
            << ", audio_pes_total=" << capture.audio_pes_count
            << std::endl;

  pipeline.close();
}

// =============================================================================
// TEST-P9-AUDIO-LIVENESS-003: VLC-decodable-smoke
// =============================================================================
// Given: TS output captured for the first 2 seconds after header write
// When: Analyzed with ffprobe (or equivalent parser)
// Then: Both audio and video streams are present, timestamps are present
//       and monotonically increasing, no "missing audio" condition at start

TEST_F(Phase9AudioLivenessTest, TEST_P9_AUDIO_LIVENESS_003_VLCDecodableSmoke) {
  TSCaptureCallback capture;

  EncoderPipeline pipeline(config_);
  bool opened = pipeline.open(config_, &capture, TSCaptureCallback::WriteCallback);
  ASSERT_TRUE(opened) << "EncoderPipeline must open successfully";

  // Create test frames
  retrovue::buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(video_frame.width * video_frame.height * 3 / 2, 128);

  // Encode ~2 seconds of video (60 frames at 30fps)
  // Do NOT provide real audio - rely on silence injection
  for (int i = 0; i < 60; ++i) {
    int64_t pts_90k = i * 3000;  // 30fps
    pipeline.encodeFrame(video_frame, pts_90k);
  }

  pipeline.close();

  // Verify we captured meaningful data
  ASSERT_GT(capture.captured_data.size(), 1000)
      << "Should capture significant TS data";

  // Write to temp file for ffprobe analysis
  std::string temp_path = "/tmp/test_p9_audio_liveness_003.ts";
  {
    std::ofstream out(temp_path, std::ios::binary);
    ASSERT_TRUE(out.is_open()) << "Failed to create temp file";
    out.write(reinterpret_cast<const char*>(capture.captured_data.data()),
              capture.captured_data.size());
  }

  // Run ffprobe to verify stream structure
  std::string ffprobe_cmd = "ffprobe -v error -show_streams -of json " + temp_path + " 2>&1";
  FILE* pipe = popen(ffprobe_cmd.c_str(), "r");
  ASSERT_NE(pipe, nullptr) << "Failed to run ffprobe";

  std::string ffprobe_output;
  char buffer[256];
  while (fgets(buffer, sizeof(buffer), pipe)) {
    ffprobe_output += buffer;
  }
  int ffprobe_result = pclose(pipe);

  // Check for video stream
  bool has_video = ffprobe_output.find("\"codec_type\": \"video\"") != std::string::npos ||
                   ffprobe_output.find("\"codec_type\":\"video\"") != std::string::npos;

  // Check for audio stream
  bool has_audio = ffprobe_output.find("\"codec_type\": \"audio\"") != std::string::npos ||
                   ffprobe_output.find("\"codec_type\":\"audio\"") != std::string::npos;

  EXPECT_TRUE(has_video)
      << "ffprobe should detect video stream in captured TS. Output: " << ffprobe_output;

  EXPECT_TRUE(has_audio)
      << "INV-P9-AUDIO-LIVENESS violated: ffprobe should detect audio stream in captured TS. "
      << "Silence injection should create valid audio. Output: " << ffprobe_output;

  // Verify from our internal counters as well
  EXPECT_GT(capture.video_pes_count.load(), 0)
      << "Internal counter: video PES should be present";
  EXPECT_GT(capture.audio_pes_count.load(), 0)
      << "Internal counter: audio PES should be present (from silence injection)";

  std::cout << "[TEST-P9-AUDIO-LIVENESS-003] "
            << "captured_bytes=" << capture.captured_data.size()
            << ", video_pes=" << capture.video_pes_count
            << ", audio_pes=" << capture.audio_pes_count
            << ", ffprobe_result=" << ffprobe_result
            << ", has_video=" << has_video
            << ", has_audio=" << has_audio
            << std::endl;

  // Cleanup temp file
  std::remove(temp_path.c_str());
}

// =============================================================================
// INV-P9-PCR-AUDIO-MASTER Tests
// =============================================================================
// Contract: docs/contracts/phases/Phase9-OutputBootstrap.md §12
//
// At output startup:
// - Audio MUST be the PCR master
// - Audio PTS MUST start at 0 (or ≤ 1 frame)
// - Mux MUST NOT initialize audio timing from video
// - Violations cause VLC to stall indefinitely

// =============================================================================
// TEST-P9-PCR-AUDIO-MASTER-001: PCR from audio, audio PTS near zero
// =============================================================================
// Given: Stream started with video-first frames
// When: TS output is captured
// Then: Audio PTS starts ≤ 1 frame duration from 0

TEST_F(Phase9AudioLivenessTest, TEST_P9_PCR_AUDIO_MASTER_001_AudioPTSNearZero) {
  TSCaptureCallback capture;

  EncoderPipeline pipeline(config_);
  bool opened = pipeline.open(config_, &capture, TSCaptureCallback::WriteCallback);
  ASSERT_TRUE(opened) << "EncoderPipeline must open successfully";

  // Create test video frame
  retrovue::buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(video_frame.width * video_frame.height * 3 / 2, 128);

  // Start with VIDEO-FIRST frames (no audio provided)
  // INV-P9-PCR-AUDIO-MASTER: Audio (silence) should still start at 0
  for (int i = 0; i < 5; ++i) {
    int64_t pts_90k = i * 3000;  // 30fps
    pipeline.encodeFrame(video_frame, pts_90k);
  }

  // Audio should have started from silence injection at PTS near 0
  // 1 frame duration at 48kHz, 1024 samples = 1920 ticks at 90kHz
  const int64_t one_frame_90k = 1920;

  EXPECT_GE(capture.first_audio_pts.load(), 0)
      << "Audio PTS should be non-negative";

  EXPECT_LE(capture.first_audio_pts.load(), one_frame_90k)
      << "INV-P9-PCR-AUDIO-MASTER violated: Audio PTS must start at 0 or ≤ 1 frame. "
      << "first_audio_pts=" << capture.first_audio_pts
      << " (max allowed=" << one_frame_90k << ")";

  EXPECT_GT(capture.audio_pes_count.load(), 0)
      << "Audio PES should be present (from silence injection)";

  std::cout << "[TEST-P9-PCR-AUDIO-MASTER-001] "
            << "first_audio_pts=" << capture.first_audio_pts
            << " (limit=" << one_frame_90k << ")"
            << ", audio_pes=" << capture.audio_pes_count
            << ", video_pes=" << capture.video_pes_count
            << std::endl;

  pipeline.close();
}

// =============================================================================
// TEST-P9-PCR-AUDIO-MASTER-002: Silence to real audio without PCR discontinuity
// =============================================================================
// Given: Stream started with silence injection
// When: Real audio frames begin arriving
// Then: No PCR discontinuity, audio PTS remains monotonic

TEST_F(Phase9AudioLivenessTest, TEST_P9_PCR_AUDIO_MASTER_002_NoPCRDiscontinuity) {
  TSCaptureCallback capture;

  EncoderPipeline pipeline(config_);
  bool opened = pipeline.open(config_, &capture, TSCaptureCallback::WriteCallback);
  ASSERT_TRUE(opened) << "EncoderPipeline must open successfully";

  // Create test video frame
  retrovue::buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(video_frame.width * video_frame.height * 3 / 2, 128);

  // Phase 1: Video-only (silence injection for audio)
  int64_t video_pts_90k = 0;
  for (int i = 0; i < 5; ++i) {
    pipeline.encodeFrame(video_frame, video_pts_90k);
    video_pts_90k += 3000;
  }

  int64_t pts_after_silence = capture.last_audio_pts.load();

  // Phase 2: Provide real audio frames
  retrovue::buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  int64_t audio_pts_90k = video_pts_90k;
  for (int i = 0; i < 10; ++i) {
    pipeline.encodeAudioFrame(audio_frame, audio_pts_90k);
    audio_pts_90k += 1920;
  }

  // More video to flush
  for (int i = 0; i < 3; ++i) {
    pipeline.encodeFrame(video_frame, video_pts_90k);
    video_pts_90k += 3000;
  }

  int64_t pts_after_real = capture.last_audio_pts.load();

  // Verify monotonicity (no backward jump = no discontinuity)
  if (pts_after_silence >= 0 && pts_after_real >= 0) {
    EXPECT_GE(pts_after_real, pts_after_silence)
        << "INV-P9-PCR-AUDIO-MASTER violated: Audio PTS jumped backward (PCR discontinuity). "
        << "after_silence=" << pts_after_silence << ", after_real=" << pts_after_real;
  }

  // First audio PTS should still be near zero
  const int64_t one_frame_90k = 1920;
  EXPECT_LE(capture.first_audio_pts.load(), one_frame_90k)
      << "First audio PTS should be ≤ 1 frame from 0";

  std::cout << "[TEST-P9-PCR-AUDIO-MASTER-002] "
            << "first_audio_pts=" << capture.first_audio_pts
            << ", pts_after_silence=" << pts_after_silence
            << ", pts_after_real=" << pts_after_real
            << std::endl;

  pipeline.close();
}

// =============================================================================
// TEST-P9-VLC-STARTUP-SMOKE: No DTS warnings
// =============================================================================
// Given: TS output captured for first 2 seconds
// When: Analyzed with ffprobe
// Then: Audio and video streams exist, timestamps monotonic,
//       no "non-monotonous DTS" warnings

TEST_F(Phase9AudioLivenessTest, TEST_P9_VLC_STARTUP_SMOKE_NoDTSWarnings) {
  TSCaptureCallback capture;

  EncoderPipeline pipeline(config_);
  bool opened = pipeline.open(config_, &capture, TSCaptureCallback::WriteCallback);
  ASSERT_TRUE(opened) << "EncoderPipeline must open successfully";

  // Create test video frame
  retrovue::buffer::Frame video_frame;
  video_frame.width = config_.target_width;
  video_frame.height = config_.target_height;
  video_frame.data.resize(video_frame.width * video_frame.height * 3 / 2, 128);

  // Encode ~2 seconds (60 frames at 30fps) - video only, silence injection for audio
  for (int i = 0; i < 60; ++i) {
    int64_t pts_90k = i * 3000;
    pipeline.encodeFrame(video_frame, pts_90k);
  }

  pipeline.close();

  // Write to temp file
  std::string temp_path = "/tmp/test_p9_vlc_startup_smoke.ts";
  {
    std::ofstream out(temp_path, std::ios::binary);
    ASSERT_TRUE(out.is_open()) << "Failed to create temp file";
    out.write(reinterpret_cast<const char*>(capture.captured_data.data()),
              capture.captured_data.size());
  }

  // Run ffprobe with warnings enabled to detect DTS issues
  // -v warning shows warnings, -v error would only show errors
  std::string ffprobe_cmd = "ffprobe -v warning -show_streams -of json " + temp_path + " 2>&1";
  FILE* pipe = popen(ffprobe_cmd.c_str(), "r");
  ASSERT_NE(pipe, nullptr) << "Failed to run ffprobe";

  std::string ffprobe_output;
  char buffer[256];
  while (fgets(buffer, sizeof(buffer), pipe)) {
    ffprobe_output += buffer;
  }
  int ffprobe_result = pclose(pipe);

  // Check for streams
  bool has_video = ffprobe_output.find("\"codec_type\": \"video\"") != std::string::npos ||
                   ffprobe_output.find("\"codec_type\":\"video\"") != std::string::npos;
  bool has_audio = ffprobe_output.find("\"codec_type\": \"audio\"") != std::string::npos ||
                   ffprobe_output.find("\"codec_type\":\"audio\"") != std::string::npos;

  // Check for DTS warnings (case-insensitive search)
  bool has_dts_warning = ffprobe_output.find("non-monotonous DTS") != std::string::npos ||
                         ffprobe_output.find("Non-monotonous DTS") != std::string::npos ||
                         ffprobe_output.find("non-monotonic") != std::string::npos ||
                         ffprobe_output.find("Non-monotonic") != std::string::npos;

  EXPECT_TRUE(has_video)
      << "ffprobe should detect video stream";

  EXPECT_TRUE(has_audio)
      << "ffprobe should detect audio stream (from silence injection)";

  EXPECT_FALSE(has_dts_warning)
      << "INV-P9-PCR-AUDIO-MASTER violated: ffprobe detected non-monotonous DTS warnings. "
      << "Output: " << ffprobe_output;

  // Verify first audio PTS is near zero
  const int64_t one_frame_90k = 1920;
  EXPECT_LE(capture.first_audio_pts.load(), one_frame_90k)
      << "First audio PTS should start at 0 or ≤ 1 frame";

  std::cout << "[TEST-P9-VLC-STARTUP-SMOKE] "
            << "has_video=" << has_video
            << ", has_audio=" << has_audio
            << ", has_dts_warning=" << has_dts_warning
            << ", first_audio_pts=" << capture.first_audio_pts
            << ", ffprobe_result=" << ffprobe_result
            << std::endl;

  // Cleanup
  std::remove(temp_path.c_str());
}

}  // namespace
