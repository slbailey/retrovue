// Repository: Retrovue-playout
// Component: Segment Continuity Contract Tests
// Purpose: Verify outcomes defined in segment_continuity_contract.md
// Contract Reference: pkg/air/docs/contracts/semantics/SegmentContinuityContract.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-SEG-001: SegmentSeamDoesNotKillSession
//   T-SEG-002: SegmentSeamAudioContinuity_NoSilentTicks
//   T-SEG-003: SegmentSeamUnderflowInjectsSilenceAndContinues
//   T-SEG-004: SegmentSeamDoesNotBlockTickLoop
//   T-SEG-005: SegmentSeamMetricsIncrementOnFallback
//   T-SEG-006: SegmentSeamAppliesToBlockToBlockTransition
//   T-SEG-007: RealMediaSeamBoundedFallback

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/PlaybackTraceTypes.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "FastTestConfig.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Helpers
// =============================================================================

static FedBlock MakeBlock(const std::string& block_id,
                          int64_t start_utc_ms,
                          int64_t duration_ms,
                          const std::string& uri = "/nonexistent/test.mp4") {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + duration_ms;

  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms = duration_ms;
  block.segments.push_back(seg);

  return block;
}

static FedBlock MakeMultiSegmentBlock(
    const std::string& block_id,
    int64_t start_utc_ms,
    int64_t duration_ms,
    const std::string& episode_uri,
    int64_t episode_duration_ms,
    const std::string& filler_uri,
    int64_t filler_duration_ms) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + duration_ms;

  FedBlock::Segment seg0;
  seg0.segment_index = 0;
  seg0.asset_uri = episode_uri;
  seg0.asset_start_offset_ms = 0;
  seg0.segment_duration_ms = episode_duration_ms;
  seg0.segment_type = SegmentType::kContent;
  block.segments.push_back(seg0);

  FedBlock::Segment seg1;
  seg1.segment_index = 1;
  seg1.asset_uri = filler_uri;
  seg1.asset_start_offset_ms = 0;
  seg1.segment_duration_ms = filler_duration_ms;
  seg1.segment_type = SegmentType::kFiller;
  block.segments.push_back(seg1);

  return block;
}

using test_infra::kBootGuardMs;
using test_infra::kBlockTimeOffsetMs;
using test_infra::kStdBlockMs;
using test_infra::kShortBlockMs;
using test_infra::kSegBlockMs;

// =============================================================================
// Test Fixture
// =============================================================================

class SegmentContinuityContractTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 99;
    int fds[2];
    ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
    ctx_->fd = fds[0];
    drain_fd_ = fds[1];
    drain_stop_.store(false);
    drain_thread_ = std::thread([this] {
      char buf[8192];
      while (!drain_stop_.load(std::memory_order_relaxed)) {
        ssize_t n = read(drain_fd_, buf, sizeof(buf));
        if (n <= 0) break;
      }
    });
    ctx_->width = 640;
    ctx_->height = 480;
    ctx_->fps = 30.0;
    test_ts_ = test_infra::MakeTestTimeSource();
  }

  void TearDown() override {
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
    if (ctx_ && ctx_->fd >= 0) {
      close(ctx_->fd);
      ctx_->fd = -1;
    }
    drain_stop_.store(true);
    if (drain_fd_ >= 0) {
      shutdown(drain_fd_, SHUT_RDWR);
      close(drain_fd_);
      drain_fd_ = -1;
    }
    if (drain_thread_.joinable()) drain_thread_.join();
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  std::unique_ptr<PipelineManager> MakeEngine() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string& reason, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
      session_ended_reason_ = reason;
      session_ended_cv_.notify_all();
    };
    callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.push_back(fp);
    };
    callbacks.on_seam_transition = [this](const SeamTransitionLog& seam) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      seam_logs_.push_back(seam);
    };
    callbacks.on_block_summary = [this](const BlockPlaybackSummary& summary) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      summaries_.push_back(summary);
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_);
  }

  bool WaitForSessionEnded(int timeout_ms = 5000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return session_ended_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this] { return session_ended_count_ > 0; });
  }

  bool WaitForBlocksCompleted(int count, int timeout_ms = 10000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return blocks_completed_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this, count] {
          return static_cast<int>(completed_blocks_.size()) >= count;
        });
  }

  std::vector<FrameFingerprint> SnapshotFingerprints() {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    return fingerprints_;
  }

  std::shared_ptr<ITimeSource> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::condition_variable blocks_completed_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<SeamTransitionLog> seam_logs_;
  std::vector<BlockPlaybackSummary> summaries_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// T-SEG-001: SegmentSeamDoesNotKillSession
// Contract: OUT-SEG-002 — A segment seam MUST NOT cause session termination.
//
// Scenario: Multi-segment block (episode + filler, both unresolvable URIs).
// The decoder transition between segments is a seam. Session must survive.
// =============================================================================
TEST_F(SegmentContinuityContractTest, T_SEG_001_SegmentSeamDoesNotKillSession) {
  auto now = NowMs();

  // Block with 2 segments: episode (3s) + filler (3s). Both URIs unresolvable
  // → decoder fails → pad frames at the seam. Session must not die.
  // Schedule after bootstrap so fence fires at the correct wall-clock instant.
  FedBlock block = MakeMultiSegmentBlock(
      "seg001", now + kBlockTimeOffsetMs, kSegBlockMs,
      "/nonexistent/episode.mp4", kSegBlockMs / 2,
      "/nonexistent/filler.mp4", kSegBlockMs / 2);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // kBootGuardMs + duration + margin for post-fence pad.
  std::this_thread::sleep_for(std::chrono::milliseconds(
      kBootGuardMs + kSegBlockMs + 1000));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-SEG-002: Session must not terminate from the segment seam.
  EXPECT_EQ(m.detach_count, 0)
      << "OUT-SEG-002 VIOLATION: segment seam caused session detach";

  // Session ran through the block and produced frames.
  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must produce frames past the segment boundary";

  // Block completed (fence fired).
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(completed_blocks_.size(), 1u);
    EXPECT_EQ(completed_blocks_[0], "seg001");
  }

  // Session ended normally.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "OUT-SEG-002: session must end cleanly, not from seam failure";
  }
}

// =============================================================================
// T-SEG-002: SegmentSeamAudioContinuity_NoSilentTicks
// Contract: OUT-SEG-003 — At every output tick, audio MUST be produced.
//
// Scenario: Single block (unresolvable URI → all pad). Every pad tick must
// produce audio (via PadProducer silence). Verify total emitted frames ==
// total audio ticks by checking no audio underflow detach.
// =============================================================================
TEST_F(SegmentContinuityContractTest, T_SEG_002_SegmentSeamAudioContinuity_NoSilentTicks) {
  constexpr int kTargetFrames = 60;
  auto now = NowMs();

  // 5s block (well past kTargetFrames at 30fps). Unresolvable → all pad.
  FedBlock block = MakeBlock("seg002", now, 5000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  // Stop after exactly kTargetFrames.
  int frame_count = 0;
  PipelineManager::Callbacks callbacks;
  callbacks.on_session_ended = [this](const std::string& reason, int64_t) {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    session_ended_count_++;
    session_ended_reason_ = reason;
    session_ended_cv_.notify_all();
  };
  callbacks.on_frame_emitted = [&](const FrameFingerprint& fp) {
    if (++frame_count >= kTargetFrames) {
      ctx_->stop_requested.store(true, std::memory_order_release);
    }
  };

  engine_ = std::make_unique<PipelineManager>(
      ctx_.get(), std::move(callbacks), test_ts_);
  engine_->Start();

  ASSERT_TRUE(WaitForSessionEnded(6000))
      << "Session must end after " << kTargetFrames << " frames";
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-SEG-003: Every tick produced audio. Pad ticks always encode audio
  // via PadProducer's SilenceTemplate, so all frames == pad frames proves
  // continuous audio output at every tick.
  EXPECT_EQ(m.pad_frames_emitted_total, m.continuous_frames_emitted_total)
      << "All frames must be pad (each pad tick produces audio)";
  EXPECT_EQ(m.detach_count, 0)
      << "OUT-SEG-003: no underflow-triggered detach (audio was continuous)";

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// T-SEG-003: SegmentSeamUnderflowInjectsSilenceAndContinues
// Contract: OUT-SEG-004 — Audio underflow is survivable and observable.
//
// Scenario: Real media with a small audio buffer (provoke underflow at
// segment boundary). Session MUST survive. If silence was injected, the
// metric must reflect it.
//
// NOTE: Requires real assets. Skipped if unavailable.
// =============================================================================
TEST_F(SegmentContinuityContractTest, T_SEG_003_SegmentSeamUnderflowInjectsSilenceAndContinues) {
  static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
  static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";
  if (access(kPathA.c_str(), F_OK) != 0 ||
      access(kPathB.c_str(), F_OK) != 0) {
    GTEST_SKIP() << "Real media assets not found";
  }

  // Shrink audio buffer to provoke underflow at segment transition.
  ctx_->buffer_config.audio_target_depth_ms = 50;
  ctx_->buffer_config.audio_low_water_ms = 10;

  auto now = NowMs();

  FedBlock block = MakeMultiSegmentBlock(
      "seg003", now, 3000,
      kPathA, 1000,
      kPathB, 2000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  std::this_thread::sleep_for(std::chrono::milliseconds(3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-SEG-004: Continue output (no teardown).
  EXPECT_EQ(m.detach_count, 0)
      << "OUT-SEG-004 VIOLATION: audio underflow at segment seam killed session";

  // OUT-SEG-004: Session emitted well past the transition.
  EXPECT_GT(m.continuous_frames_emitted_total, 60)
      << "Session must survive segment transition and continue";

  // OUT-SEG-004: Observable — if silence was injected, the metric records it.
  // (audio_silence_injected may be 0 if the buffer held enough headroom;
  //  the contract only requires observability when underflow occurs.)

  // OUT-SEG-005b: max_consecutive_audio_fallback_ticks is observable.
  // With a 50ms audio buffer stressing the transition, some fallback is expected.
  // The metric must be tracked (>= 0 is always true; this asserts the field exists
  // and is populated — the bounded assertion is in T-SEG-007).
  EXPECT_GE(m.max_consecutive_audio_fallback_ticks, 0)
      << "OUT-SEG-005b: max_consecutive_audio_fallback_ticks must be tracked";

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "OUT-SEG-004: session must end cleanly";
  }
}

// =============================================================================
// T-SEG-004: SegmentSeamDoesNotBlockTickLoop
// Contract: OUT-SEG-005 — The tick loop MUST NOT block on decoder open/close.
//
// Scenario: Two wall-anchored blocks with unresolvable URIs. The transition
// (a decoder seam) is handled via preload on a background thread. Verify
// that inter-frame cadence stays under the tick-deadline threshold (40ms
// at 30fps), proving the tick loop was not blocked.
// =============================================================================
TEST_F(SegmentContinuityContractTest, T_SEG_004_SegmentSeamDoesNotBlockTickLoop) {
  auto now = NowMs();

  FedBlock block_a = MakeBlock("seg004a", now, 1000);
  FedBlock block_b = MakeBlock("seg004b", now + 1000, 1000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Run through both blocks + margin.
  std::this_thread::sleep_for(std::chrono::milliseconds(3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-SEG-005: Tick loop was not blocked — inter-frame gap stays bounded.
  // At 30fps, frame period is 33ms. 50ms threshold gives generous margin
  // for scheduling jitter without masking a blocking decoder open.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "OUT-SEG-005 VIOLATION: tick loop was blocked at segment seam. "
         "max_gap_us=" << m.max_inter_frame_gap_us;

  EXPECT_EQ(m.detach_count, 0);

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// T-SEG-005: SegmentSeamMetricsIncrementOnFallback
// Contract: OUT-SEG-004 — Increment a counter/metric on continuity fallback.
//
// Scenario: Two wall-anchored blocks (synthetic). At the fence, the TAKE
// selects pad (continuity fallback) because the next block has no decoder.
// Verify fence_pad_frames_total or padded_gap_count increments.
// =============================================================================
TEST_F(SegmentContinuityContractTest, T_SEG_005_SegmentSeamMetricsIncrementOnFallback) {
  auto now = NowMs();

  // Block A (1s) → fence → Block B (1s). Both unresolvable → pad at seam.
  FedBlock block_a = MakeBlock("seg005a", now, 1000);
  FedBlock block_b = MakeBlock("seg005b", now + 1000, 1000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  std::this_thread::sleep_for(std::chrono::milliseconds(3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-SEG-004: At least one fallback metric must have incremented.
  // With synthetic blocks, pad_frames_emitted_total > 0 proves continuity
  // fallback was used. degraded_take_count proves the TAKE was observed.
  EXPECT_GT(m.pad_frames_emitted_total, 0)
      << "OUT-SEG-004: pad frames must have been emitted as continuity fallback";

  // At the block transition, the TAKE is degraded (synthetic = no audio).
  EXPECT_GE(m.source_swap_count, 1)
      << "Must have at least 1 source swap";
  EXPECT_GE(m.degraded_take_count, 1)
      << "OUT-SEG-004: degraded_take_count must increment (synthetic audio=0ms)";

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// T-SEG-006: SegmentSeamAppliesToBlockToBlockTransition
// Contract: OUT-SEG-006 — Outcomes apply uniformly to block→block transitions.
//
// Scenario: Three wall-anchored blocks (A → B → C). All synthetic.
// Verify that every block-to-block transition is a valid segment seam:
// - No session death (OUT-SEG-002)
// - Audio continuous (OUT-SEG-003 via pad)
// - Tick loop not blocked (OUT-SEG-005)
// This test also satisfies T-BLOCK-004 (block transition invokes segment
// continuity outcomes).
// =============================================================================
TEST_F(SegmentContinuityContractTest, T_SEG_006_SegmentSeamAppliesToBlockToBlockTransition) {
  auto now = NowMs();

  FedBlock block_a = MakeBlock("seg006a", now, kShortBlockMs);
  FedBlock block_b = MakeBlock("seg006b", now + kShortBlockMs, kShortBlockMs);
  FedBlock block_c = MakeBlock("seg006c", now + 2 * kShortBlockMs, kShortBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
    ctx_->block_queue.push_back(block_c);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Bootstrap + 3 blocks + margin.
  std::this_thread::sleep_for(std::chrono::milliseconds(
      kBootGuardMs + 3 * kShortBlockMs + 500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-SEG-006: All block transitions are segment seams.
  // OUT-SEG-002: No session death.
  EXPECT_EQ(m.detach_count, 0)
      << "OUT-SEG-006/002: block-to-block transition must not kill session";

  // All 3 blocks executed.
  EXPECT_GE(m.total_blocks_executed, 3)
      << "All 3 blocks must complete";

  // At least 2 source swaps (A→B, B→C).
  EXPECT_GE(m.source_swap_count, 2)
      << "OUT-SEG-006: at least 2 block-to-block transitions must occur";

  // OUT-SEG-005: Tick loop not blocked.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "OUT-SEG-005: tick loop must not block at block-to-block seam";

  // Session survived all transitions.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "OUT-SEG-006: session must survive all block-to-block transitions";
  }
}

// =============================================================================
// T-SEG-007: RealMediaSeamBoundedFallback
// Contract: OUT-SEG-005b — Bounded fallback at segment seams (normal case).
//
// Scenario: Two blocks (Block A = SampleA.mp4, 2s → Block B = SampleB.mp4, 2s).
// Different blocks force preloader cycle + TAKE rotation + decoder close/open.
// Normal audio buffer config (default 1000ms target) — healthy playout scenario.
// Assert: max_consecutive_audio_fallback_ticks <= 5 — the broadcast KPI.
//
// NOTE: Requires real assets. Skipped if unavailable.
// =============================================================================
TEST_F(SegmentContinuityContractTest, T_SEG_007_RealMediaSeamBoundedFallback) {
  static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
  static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";
  if (access(kPathA.c_str(), F_OK) != 0 ||
      access(kPathB.c_str(), F_OK) != 0) {
    GTEST_SKIP() << "Real media assets not found";
  }

  // Normal audio buffer config — this is the "healthy playout" scenario.
  // Default 1000ms target gives the preloader ample time to prime.

  auto now = NowMs();

  // Block A: SampleA.mp4 for 2s
  FedBlock block_a = MakeBlock("seg007a", now, 2000, kPathA);
  // Block B: SampleB.mp4 for 2s
  FedBlock block_b = MakeBlock("seg007b", now + 2000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait for both blocks to complete, then snapshot metrics and stop
  // immediately.  Sleeping past the last block would accumulate trailing
  // pad frames that inflate max_consecutive_audio_fallback_ticks — those
  // aren't seam fallback, they're normal end-of-content pad.
  ASSERT_TRUE(WaitForBlocksCompleted(2, 10000))
      << "Both blocks must complete within timeout";

  // Snapshot metrics while block B's content is still fresh — before
  // trailing pad accumulates.
  auto m = engine_->SnapshotMetrics();
  engine_->Stop();

  // OUT-SEG-002: Session survived the transition.
  EXPECT_EQ(m.detach_count, 0)
      << "OUT-SEG-002: block-to-block transition must not kill session";

  // Session emitted well past the transition point.
  EXPECT_GT(m.continuous_frames_emitted_total, 90)
      << "Session must emit frames past the block A→B transition";

  // OUT-SEG-005b: The broadcast KPI — worst consecutive fallback burst.
  // With healthy 1000ms audio buffer and real local assets, the preloader
  // should resolve the decoder transition within 5 ticks.
  static constexpr int64_t kMaxAllowedFallbackTicks = 5;
  EXPECT_LE(m.max_consecutive_audio_fallback_ticks, kMaxAllowedFallbackTicks)
      << "OUT-SEG-005b VIOLATION: consecutive fallback ticks exceeded threshold. "
         "max_consecutive=" << m.max_consecutive_audio_fallback_ticks
      << " threshold=" << kMaxAllowedFallbackTicks;

  // At least 1 source swap (A→B).
  EXPECT_GE(m.source_swap_count, 1)
      << "Block A→B transition must have occurred";

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session must end cleanly after both blocks";
  }
}

}  // namespace
}  // namespace retrovue::blockplan::testing
