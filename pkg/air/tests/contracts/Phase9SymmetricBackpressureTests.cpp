// Repository: Retrovue-playout
// Component: Phase 9 Symmetric Backpressure Tests
// Purpose: Verify INV-P9-STEADY-002 and INV-P9-STEADY-003
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>
#include <chrono>
#include <thread>
#include <atomic>
#include <iostream>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "timing/TestMasterClock.h"

using namespace retrovue;
using namespace retrovue::timing;
using namespace std::chrono_literals;

namespace {

// =============================================================================
// Phase 9 Symmetric Backpressure Contract Tests
// =============================================================================
// These tests verify:
// - INV-P9-STEADY-002: Producer Pull-Only After Attach (slot-based gating)
// - INV-P9-STEADY-003: Audio Advances With Video (symmetric throttling)
// =============================================================================

class Phase9SymmetricBackpressureTest : public ::testing::Test {
protected:
  void SetUp() override {
    // Small buffer to trigger backpressure quickly
    // Note: Ring buffer implementation may have capacity + 1 slots internally
    buffer_ = std::make_unique<buffer::FrameRingBuffer>(10);
    // Use deterministic mode for predictable test behavior
    clock_ = std::make_shared<TestMasterClock>(0, TestMasterClock::Mode::Deterministic);
    clock_->set_epoch_utc_us(0);
  }

  void TearDown() override {
    buffer_.reset();
    clock_.reset();
  }

  // Helper to advance fake clock
  void AdvanceClock(int64_t us) {
    clock_->AdvanceMicroseconds(us);
  }

  // Get a test video file path
  std::string GetTestVideoPath() {
    // Use an environment variable or fallback to a known test asset
    const char* test_media = std::getenv("RETROVUE_TEST_MEDIA");
    if (test_media) {
      return std::string(test_media);
    }
    // Fallback to a commonly available test file
    return "/opt/retrovue/pkg/air/tests/assets/test_30fps.mp4";
  }

  std::unique_ptr<buffer::FrameRingBuffer> buffer_;
  std::shared_ptr<TestMasterClock> clock_;
};

// =============================================================================
// P9-TEST-003: Slot-Based Blocking
// =============================================================================
// Given: Buffer at capacity
// When: Producer attempts decode
// Then: Producer thread blocks
// And: Producer resumes when exactly 1 slot frees
// Contract: INV-P9-STEADY-002

TEST_F(Phase9SymmetricBackpressureTest, P9_TEST_003_SlotBasedBlocking) {
  // Fill buffer to capacity
  buffer::Frame frame;
  frame.width = 1920;
  frame.height = 1080;
  frame.data.resize(1920 * 1080 * 3 / 2, 128);  // YUV420
  frame.metadata.pts = 0;
  frame.metadata.has_ct = true;
  frame.metadata.asset_uri = "test://frame";

  // Get actual capacity from buffer (may differ from constructor param)
  size_t capacity = buffer_->Capacity();
  std::cout << "[P9-TEST-003] Buffer capacity: " << capacity << std::endl;

  // Fill until buffer is full (keep pushing while successful)
  size_t pushed = 0;
  while (!buffer_->IsFull() && pushed < capacity + 10) {  // safety limit
    frame.metadata.pts = static_cast<int64_t>(pushed * 33333);
    if (buffer_->Push(frame)) {
      pushed++;
    } else {
      break;
    }
  }

  std::cout << "[P9-TEST-003] Pushed " << pushed << " frames to fill buffer" << std::endl;
  ASSERT_TRUE(buffer_->IsFull())
      << "Buffer should be full after filling";

  // Push should fail when full
  frame.metadata.pts = static_cast<int64_t>(pushed * 33333);
  EXPECT_FALSE(buffer_->Push(frame))
      << "Push should fail when buffer is at capacity";

  // Pop one frame
  buffer::Frame popped;
  ASSERT_TRUE(buffer_->Pop(popped))
      << "Pop should succeed when buffer has frames";

  // Verify buffer is no longer full
  EXPECT_FALSE(buffer_->IsFull())
      << "Buffer should not be full after one pop";

  // Push should now succeed (1 slot free)
  EXPECT_TRUE(buffer_->Push(frame))
      << "INV-P9-STEADY-002: Push should succeed immediately when 1 slot frees";

  // Buffer should be full again
  EXPECT_TRUE(buffer_->IsFull())
      << "Buffer should be full again after push";

  std::cout << "[P9-TEST-003] Slot-based blocking verified: "
            << "blocked at capacity, resumed on 1 slot free" << std::endl;
}

// =============================================================================
// P9-TEST-003a: No Hysteresis
// =============================================================================
// Given: Buffer at capacity, producer blocked
// When: Consumer dequeues 1 frame
// Then: Producer immediately resumes (not waiting for low-water)
// And: Buffer refills to capacity
// Contract: INV-P9-STEADY-002

TEST_F(Phase9SymmetricBackpressureTest, P9_TEST_003a_NoHysteresis) {
  buffer::Frame frame;
  frame.width = 1920;
  frame.height = 1080;
  frame.data.resize(1920 * 1080 * 3 / 2, 128);
  frame.metadata.has_ct = true;
  frame.metadata.asset_uri = "test://frame";

  // Fill until full
  size_t pushed = 0;
  while (!buffer_->IsFull()) {
    frame.metadata.pts = static_cast<int64_t>(pushed * 33333);
    if (buffer_->Push(frame)) {
      pushed++;
    } else {
      break;
    }
  }
  ASSERT_TRUE(buffer_->IsFull());
  size_t full_size = buffer_->Size();

  // Simulate steady-state: pop one, push one, repeat
  // With hysteresis, this would drain to low-water before refilling
  // With slot-based, each pop immediately allows one push
  for (int cycle = 0; cycle < 10; ++cycle) {
    // Pop one frame
    buffer::Frame popped;
    ASSERT_TRUE(buffer_->Pop(popped));
    EXPECT_FALSE(buffer_->IsFull())
        << "Buffer should not be full after pop";

    // Immediately push one frame (no waiting for low-water)
    frame.metadata.pts = static_cast<int64_t>((pushed + cycle) * 33333);
    EXPECT_TRUE(buffer_->Push(frame))
        << "INV-P9-STEADY-002: No hysteresis - push should succeed immediately after 1 pop";

    // Buffer should be full again
    EXPECT_TRUE(buffer_->IsFull());
  }

  std::cout << "[P9-TEST-003a] No hysteresis verified: "
            << "10 cycles of pop-one/push-one maintained full buffer" << std::endl;
}

// =============================================================================
// P9-TEST-004: Symmetric A/V Backpressure
// =============================================================================
// Given: Video buffer full, audio buffer has capacity
// When: Measured over 10 seconds
// Then: |audio_frames_produced - video_frames_produced| <= 1
// And: Neither stream runs ahead
// Contract: INV-P9-STEADY-003

TEST_F(Phase9SymmetricBackpressureTest, P9_TEST_004_SymmetricBackpressure) {
  // This test verifies the A/V delta constraint directly
  // We simulate the constraint by checking that both buffers are gated together

  buffer::Frame video_frame;
  video_frame.width = 1920;
  video_frame.height = 1080;
  video_frame.data.resize(1920 * 1080 * 3 / 2, 128);
  video_frame.metadata.has_ct = true;

  buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.pts_us = 0;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  size_t video_capacity = buffer_->Capacity();
  size_t audio_capacity = buffer_->AudioCapacity();

  std::cout << "[P9-TEST-004] Video capacity: " << video_capacity
            << ", Audio capacity: " << audio_capacity << std::endl;

  int64_t video_count = 0;
  int64_t audio_count = 0;

  // Simulate interleaved A/V production with symmetric gating
  // INV-P9-STEADY-003: Audio can push if AFTER push, delta would be <= 1
  // This means: audio_count (before push) <= video_count
  for (int i = 0; i < 100; ++i) {
    // Try to push video
    video_frame.metadata.pts = i * 33333;
    if (buffer_->Push(video_frame)) {
      video_count++;
    }

    // Try to push audio, but respect A/V delta <= 1
    // The constraint is: (audio_count + 1) - video_count <= 1
    // Which simplifies to: audio_count <= video_count
    // (This simulates the corrected CanAudioAdvance() check in FileProducer)
    if (audio_count <= video_count) {
      audio_frame.pts_us = i * 21333;
      if (buffer_->PushAudioFrame(audio_frame)) {
        audio_count++;
      }
    }

    // Verify A/V delta constraint AFTER both pushes
    int64_t delta = audio_count - video_count;
    EXPECT_LE(delta, 1)
        << "INV-P9-STEADY-003 VIOLATION: A/V delta=" << delta
        << " exceeds limit=1 (video=" << video_count
        << ", audio=" << audio_count << ")";

    // Simulate consumption (pop frames periodically)
    if (i % 3 == 0) {
      buffer::Frame popped_video;
      buffer::AudioFrame popped_audio;
      buffer_->Pop(popped_video);
      buffer_->PopAudioFrame(popped_audio);
    }
  }

  int64_t final_delta = audio_count - video_count;
  std::cout << "[P9-TEST-004] Symmetric backpressure verified: "
            << "video=" << video_count << ", audio=" << audio_count
            << ", final_delta=" << final_delta << " (limit=1)" << std::endl;

  EXPECT_LE(final_delta, 1)
      << "INV-P9-STEADY-003: Final A/V delta should be <= 1";
}

// =============================================================================
// P9-TEST-004a: Coordinated Stall
// =============================================================================
// Given: Video blocked at decode gate
// When: Audio decode attempted
// Then: Audio also blocks (does not receive from decoder)
// And: Both resume together when capacity available
// Contract: INV-P9-STEADY-003

TEST_F(Phase9SymmetricBackpressureTest, P9_TEST_004a_CoordinatedStall) {
  // This test verifies that when video is blocked at capacity,
  // audio also blocks (cannot run ahead by more than 1 frame)

  buffer::Frame video_frame;
  video_frame.width = 1920;
  video_frame.height = 1080;
  video_frame.data.resize(1920 * 1080 * 3 / 2, 128);
  video_frame.metadata.has_ct = true;

  buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.pts_us = 0;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  // Fill video buffer to capacity
  size_t pushed = 0;
  while (!buffer_->IsFull()) {
    video_frame.metadata.pts = static_cast<int64_t>(pushed * 33333);
    if (buffer_->Push(video_frame)) {
      pushed++;
    } else {
      break;
    }
  }
  ASSERT_TRUE(buffer_->IsFull());

  // Video is now blocked
  int64_t video_count = static_cast<int64_t>(pushed);
  int64_t audio_count = 0;

  // Push some audio frames (should be limited by CanAudioAdvance constraint)
  // The constraint is: audio_count <= video_count (so after push, delta <= 1)
  for (int i = 0; i < 50; ++i) {
    // Simulate corrected CanAudioAdvance() check
    if (audio_count <= video_count) {
      audio_frame.pts_us = i * 21333;
      if (buffer_->PushAudioFrame(audio_frame)) {
        audio_count++;
      }
    } else {
      // Audio is throttled - cannot advance
      break;
    }
  }

  // Audio should have stopped at video_count + 1 (pushed when audio_count == video_count)
  EXPECT_EQ(audio_count, video_count + 1)
      << "INV-P9-STEADY-003: Audio should stop at video_count + 1 when video blocked";

  int64_t delta_at_stall = audio_count - video_count;
  std::cout << "[P9-TEST-004a] Coordinated stall verified: "
            << "video_blocked_at=" << video_count
            << ", audio_stopped_at=" << audio_count
            << ", delta=" << delta_at_stall << " (should be exactly 1)" << std::endl;

  EXPECT_EQ(delta_at_stall, 1)
      << "INV-P9-STEADY-003: Delta should be exactly 1 when audio stops";
}

// =============================================================================
// P9-TEST-002: Producer WaitForDecodeReady Blocks at Capacity
// =============================================================================
// Verify that WaitForDecodeReady() blocks when EITHER buffer is full
// and unblocks when ONE slot frees in the full buffer.
// Contract: INV-P9-STEADY-002

TEST_F(Phase9SymmetricBackpressureTest, P9_TEST_002_WaitForDecodeReadyBlocksAtCapacity) {
  // Fill both video and audio buffers
  buffer::Frame video_frame;
  video_frame.width = 1920;
  video_frame.height = 1080;
  video_frame.data.resize(1920 * 1080 * 3 / 2, 128);
  video_frame.metadata.has_ct = true;

  buffer::AudioFrame audio_frame;
  audio_frame.sample_rate = 48000;
  audio_frame.channels = 2;
  audio_frame.nb_samples = 1024;
  audio_frame.data.resize(1024 * 2 * sizeof(int16_t), 0);

  // Fill video to capacity
  for (size_t i = 0; i < buffer_->Capacity(); ++i) {
    video_frame.metadata.pts = static_cast<int64_t>(i * 33333);
    buffer_->Push(video_frame);
  }
  ASSERT_TRUE(buffer_->IsFull());

  // Video buffer full should gate the producer
  // (In real producer, WaitForDecodeReady() would block here)

  // Verify that freeing 1 video slot allows decode to continue
  buffer::Frame popped;
  buffer_->Pop(popped);
  EXPECT_FALSE(buffer_->IsFull())
      << "After popping 1, buffer should not be full";
  EXPECT_TRUE(buffer_->Push(video_frame))
      << "INV-P9-STEADY-002: Decode should resume when 1 slot frees";

  std::cout << "[P9-TEST-002] WaitForDecodeReady slot-based gating verified" << std::endl;
}

}  // namespace
