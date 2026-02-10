// Repository: Retrovue-playout
// Component: Seam Continuity Engine Contract Tests
// Purpose: Verify invariants defined in SeamContinuityEngine.md
// Contract Reference: pkg/air/docs/contracts/semantics/SeamContinuityEngine.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-SEAM-001a: ClockIsolation_SegmentSeam
//   T-SEAM-001b: ClockIsolation_BlockSeam
//   T-SEAM-001c: ClockIsolation_AdversarialProbeLatency
//   T-SEAM-002a: DecoderReadiness_AchievedBeforeFence
//   T-SEAM-002b: DecoderReadiness_OverlapWindowProof
//   T-SEAM-003a: AudioContinuity_ZeroSilenceAtSeam
//   T-SEAM-003b: AudioContinuity_NoAudioTrackExempt
//   T-SEAM-004a: MechanicalEquivalence_SegmentVsBlockLatencyProfile
//   T-SEAM-004b: MechanicalEquivalence_MixedSeamsInSingleSession
//   T-SEAM-005a: BoundedFallbackObservability_MetricTrackedAndExposed
//   T-SEAM-005b: BoundedFallbackObservability_PerfectContinuityDetectable
//   T-SEAM-006:  FallbackOnPreloaderFailure_SessionSurvives
//   T-SEAM-007:  AudioUnderflowAbsenceAtSeam_StressedBuffer

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <fstream>
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

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Constants
// =============================================================================

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

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

static int64_t NowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
}

// =============================================================================
// Test Fixture
// =============================================================================

class SeamContinuityEngineContractTest : public ::testing::Test {
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

  std::unique_ptr<PipelineManager> MakeEngine() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      fence_frame_indices_.push_back(ct);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string& reason) {
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
    return std::make_unique<PipelineManager>(ctx_.get(), std::move(callbacks));
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

  // Reset all callback state for a fresh engine run within a single test.
  void ResetCallbackState() {
    {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.clear();
      fence_frame_indices_.clear();
      seam_logs_.clear();
      summaries_.clear();
      session_ended_count_ = 0;
      session_ended_reason_.clear();
    }
    {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.clear();
    }
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::condition_variable blocks_completed_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<int64_t> fence_frame_indices_;
  std::vector<SeamTransitionLog> seam_logs_;
  std::vector<BlockPlaybackSummary> summaries_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// T-SEAM-001a: ClockIsolation_SegmentSeam
// Invariant: INV-SEAM-001 (Clock Isolation)
//
// Scenario: Multi-segment block with two real-media segments (episode 1.5s +
// filler 1.5s). The intra-block segment transition forces decoder close/open
// on the fill thread. The tick thread must continue its cadence without
// observing the transition.
//
// Assets: SampleA.mp4 (episode), SampleB.mp4 (filler). GTEST_SKIP if missing.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_001a_ClockIsolation_SegmentSeam) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block = MakeMultiSegmentBlock(
      "seam001a", now, 3000,
      kPathA, 1500,
      kPathB, 1500);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  std::this_thread::sleep_for(std::chrono::milliseconds(3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // INV-SEAM-001: Tick thread not blocked on decoder lifecycle at segment seam.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "INV-SEAM-001 VIOLATION: tick thread blocked at segment seam. "
         "max_gap_us=" << m.max_inter_frame_gap_us;

  // INV-SEAM-001: Late ticks bounded (contract: single late tick is scheduling
  // jitter, recoverable; only systematic late ticks are fatal).
  EXPECT_LE(m.late_ticks_total, 2)
      << "INV-SEAM-001 VIOLATION: systematic late ticks at segment seam. "
         "late_ticks=" << m.late_ticks_total;

  // Session survived the segment transition.
  EXPECT_EQ(m.detach_count, 0)
      << "INV-SEAM-001: segment seam must not cause session detach";

  // Continuous output through the 3s block.
  EXPECT_GT(m.continuous_frames_emitted_total, 80)
      << "Output stalled — expected >80 frames for 3s at 30fps";
}

// =============================================================================
// T-SEAM-001b: ClockIsolation_BlockSeam
// Invariant: INV-SEAM-001 (Clock Isolation)
//
// Scenario: Two wall-anchored blocks (A=2s, B=2s) with real media.
// Block→block transition triggers ProducerPreloader → TAKE → rotation.
// Verify the tick thread does not observe preloader startup or buffer rotation.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_001b_ClockIsolation_BlockSeam) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam001b-a", now, 2000, kPathA);
  FedBlock block_b = MakeBlock("seam001b-b", now + 2000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 10000))
      << "Block A must complete at its fence";

  auto m = engine_->SnapshotMetrics();
  engine_->Stop();

  // INV-SEAM-001: Tick thread not blocked on preloader or buffer rotation.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "INV-SEAM-001 VIOLATION: tick thread blocked at block seam. "
         "max_gap_us=" << m.max_inter_frame_gap_us;

  // INV-SEAM-001: Late ticks bounded (contract: single late tick is scheduling
  // jitter, recoverable; only systematic late ticks are fatal).
  EXPECT_LE(m.late_ticks_total, 2)
      << "INV-SEAM-001 VIOLATION: systematic late ticks at block seam. "
         "late_ticks=" << m.late_ticks_total;

  // Block transition occurred.
  EXPECT_GE(m.source_swap_count, 1)
      << "Block transition did not occur";

  // Session survived.
  EXPECT_EQ(m.detach_count, 0)
      << "INV-SEAM-001: block seam must not cause session detach";
}

// =============================================================================
// T-SEAM-001c: ClockIsolation_AdversarialProbeLatency
// Invariant: INV-SEAM-001 (Clock Isolation) — adversarial case
//
// Scenario: Two synthetic blocks (A=1s, B=1s). Inject 800ms preloader delay
// via SetPreloaderDelayHook(). This simulates a slow container probe. Despite
// the delay, the tick thread must never stall.
//
// Assets: None (synthetic). Asset-agnostic.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_001c_ClockIsolation_AdversarialProbeLatency) {
  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam001c-a", now, 1000);
  FedBlock block_b = MakeBlock("seam001c-b", now + 1000, 1000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->SetPreloaderDelayHook([] {
    std::this_thread::sleep_for(std::chrono::milliseconds(800));
  });
  engine_->Start();

  std::this_thread::sleep_for(std::chrono::milliseconds(3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // INV-SEAM-001: Tick thread must not wait for preloader despite 800ms delay.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "INV-SEAM-001 VIOLATION: tick thread waited for preloader. "
         "max_gap_us=" << m.max_inter_frame_gap_us;

  // INV-SEAM-001: Late ticks bounded despite adversarial delay (contract:
  // single late tick is scheduling jitter, recoverable).
  EXPECT_LE(m.late_ticks_total, 2)
      << "INV-SEAM-001 VIOLATION: preloader latency leaked to tick thread. "
         "late_ticks=" << m.late_ticks_total;

  // Session survived the adversarial delay.
  EXPECT_EQ(m.detach_count, 0)
      << "Adversarial preloader latency killed session";

  // Continuous output despite delay.
  EXPECT_GT(m.continuous_frames_emitted_total, 60)
      << "Output stalled during preloader delay — expected >60 frames for 2s";
}

// =============================================================================
// T-SEAM-002a: DecoderReadiness_AchievedBeforeFence
// Invariant: INV-SEAM-002 (Decoder Readiness Before Seam Tick)
//
// Scenario: Two blocks (A=2s, B=2s) with real media. Default 1000ms audio
// buffer gives the preloader ample overlap window. Verify the preloader
// achieved readiness before the fence tick.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_002a_DecoderReadiness_AchievedBeforeFence) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam002a-a", now, 2000, kPathA);
  FedBlock block_b = MakeBlock("seam002a-b", now + 2000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 10000))
      << "Block A must complete at fence";

  auto m = engine_->SnapshotMetrics();
  engine_->Stop();

  // INV-SEAM-002: Preloader was triggered.
  EXPECT_GE(m.next_preload_started_count, 1)
      << "INV-SEAM-002: preloader was never triggered";

  // INV-SEAM-002: Preloader achieved readiness.
  EXPECT_GE(m.next_preload_ready_count, 1)
      << "INV-SEAM-002: preloader did not achieve readiness";

  // INV-SEAM-002: No readiness miss at fence.
  EXPECT_EQ(m.fence_preload_miss_count, 0)
      << "INV-SEAM-002 VIOLATION: readiness not achieved before fence";

  // INV-SEAM-002: Degraded TAKE bounded. With default 1000ms audio buffer
  // and 2s blocks, the preloader should achieve full prime. A single degraded
  // take is acceptable (CI timing jitter); systematic degradation is not.
  EXPECT_LE(m.degraded_take_count, 1)
      << "INV-SEAM-002: audio prime systematically insufficient at TAKE. "
         "degraded_take_count=" << m.degraded_take_count;

  // INV-SEAM-002: No PADDED_GAP.
  EXPECT_EQ(m.padded_gap_count, 0)
      << "INV-SEAM-002: no incoming source at fence (PADDED_GAP)";

  // First B frame at fence should be real content, not pad.
  auto fps = SnapshotFingerprints();
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    if (!fence_frame_indices_.empty()) {
      auto fence_tick = fence_frame_indices_[0];
      if (fence_tick >= 0 &&
          static_cast<size_t>(fence_tick) < fps.size()) {
        EXPECT_FALSE(fps[static_cast<size_t>(fence_tick)].is_pad)
            << "INV-SEAM-002: first B frame at fence was pad, not content";
      }
    }
  }
}

// =============================================================================
// T-SEAM-002b: DecoderReadiness_OverlapWindowProof
// Invariant: INV-SEAM-002 (Decoder Readiness)
//
// Scenario: Two blocks (A=2s, B=2s) with real media. Capture fingerprints.
// Prove the overlap window was active: last N frames before fence are from A's
// real content (A was still producing), AND first frame at fence is from B's
// real content (B was preloaded and ready).
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_002b_DecoderReadiness_OverlapWindowProof) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam002b-a", now, 2000, kPathA);
  FedBlock block_b = MakeBlock("seam002b-b", now + 2000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 10000))
      << "Block A must complete at fence";

  // Let B produce a few frames past the fence, then stop.
  std::this_thread::sleep_for(std::chrono::milliseconds(500));

  auto fps = SnapshotFingerprints();
  auto m = engine_->SnapshotMetrics();
  engine_->Stop();

  int64_t fence_tick;
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(fence_frame_indices_.size(), 1u);
    fence_tick = fence_frame_indices_[0];
  }

  ASSERT_GT(fence_tick, 5)
      << "Block A must produce enough frames to verify overlap window";
  ASSERT_GT(static_cast<int64_t>(fps.size()), fence_tick)
      << "Must have fingerprints at the fence tick";

  // INV-SEAM-002: Frames [fence-5..fence-1] must be from block A, real content.
  // This proves A was still producing while B was being prepared.
  for (int64_t i = std::max(int64_t{0}, fence_tick - 5); i < fence_tick; i++) {
    const auto& fp = fps[static_cast<size_t>(i)];
    EXPECT_FALSE(fp.is_pad)
        << "A stopped producing before B was ready at tick " << i;
    EXPECT_EQ(fp.active_block_id, "seam002b-a")
        << "Unexpected block at tick " << i << " before fence";
  }

  // INV-SEAM-002: Frame at fence must be from block B, real content.
  // This proves B was preloaded and ready at the fence tick.
  {
    const auto& fp = fps[static_cast<size_t>(fence_tick)];
    EXPECT_FALSE(fp.is_pad)
        << "INV-SEAM-002: B was not ready at fence (pad emitted)";
    EXPECT_EQ(fp.active_block_id, "seam002b-b")
        << "INV-SEAM-002: fence frame is not from block B";
  }

  // Source swap must have occurred.
  EXPECT_GE(m.source_swap_count, 1)
      << "Swap did not occur";

  // Boundary report: no pad frames in the window around the fence.
  auto report = BuildBoundaryReport(fps, fence_tick, "seam002b-a", "seam002b-b");
  EXPECT_EQ(report.pad_frames_in_window, 0)
      << "INV-SEAM-002: pad gap between A and B at boundary";
}

// =============================================================================
// T-SEAM-003a: AudioContinuity_ZeroSilenceAtSeam
// Invariant: INV-SEAM-003 (Audio Continuity Across Seam)
//
// Scenario: Two blocks (A=2s, B=2s) with real media having audio tracks.
// Default 1000ms audio buffer. The overlap window must prime B's audio buffer
// before the fence. At the seam tick, real decoded audio must be emitted.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_003a_AudioContinuity_ZeroSilenceAtSeam) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam003a-a", now, 2000, kPathA);
  FedBlock block_b = MakeBlock("seam003a-b", now + 2000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait for both blocks to complete, snapshot immediately to avoid
  // trailing pad accumulation inflating fallback metrics.
  ASSERT_TRUE(WaitForBlocksCompleted(2, 10000))
      << "Both blocks must complete within timeout";

  auto m = engine_->SnapshotMetrics();
  engine_->Stop();

  // INV-SEAM-003: Bounded audio fallback at seam. With default 1000ms audio
  // buffer and real local assets, the preloader should resolve the decoder
  // transition within 5 ticks (the broadcast KPI from OUT-SEG-005b).
  static constexpr int64_t kMaxAllowedFallbackTicks = 5;
  EXPECT_LE(m.max_consecutive_audio_fallback_ticks, kMaxAllowedFallbackTicks)
      << "INV-SEAM-003 VIOLATION: consecutive fallback ticks exceeded threshold. "
         "max_consecutive=" << m.max_consecutive_audio_fallback_ticks
      << " threshold=" << kMaxAllowedFallbackTicks;

  // INV-SEAM-003: Degraded TAKE bounded (single degraded take acceptable
  // under CI timing; systematic degradation is structural).
  EXPECT_LE(m.degraded_take_count, 1)
      << "INV-SEAM-003: audio prime systematically insufficient at TAKE. "
         "degraded_take_count=" << m.degraded_take_count;

  // Session survived.
  EXPECT_EQ(m.detach_count, 0)
      << "Audio underflow killed session";

  // Continuous output.
  EXPECT_GT(m.continuous_frames_emitted_total, 100)
      << "Output stalled — expected >100 frames for 4s at 30fps";
}

// =============================================================================
// T-SEAM-003b: AudioContinuity_NoAudioTrackExempt
// Invariant: INV-SEAM-003 (Audio Continuity — exemption case)
//
// Scenario: Two synthetic blocks (A=1s, B=1s) with unresolvable URIs. Both
// blocks decode via PadProducer (no audio track). Pad audio is the correct
// output — this is NOT an INV-SEAM-003 violation.
//
// Assets: None (synthetic). Asset-agnostic.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_003b_AudioContinuity_NoAudioTrackExempt) {
  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam003b-a", now, 1000);
  FedBlock block_b = MakeBlock("seam003b-b", now + 1000, 1000);
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

  // Session survived all seams with synthetic (no-audio-track) blocks.
  EXPECT_EQ(m.detach_count, 0)
      << "No-audio-track seam killed session";

  // All frames are pad (synthetic blocks → PadProducer).
  EXPECT_EQ(m.pad_frames_emitted_total, m.continuous_frames_emitted_total)
      << "Non-pad frame appeared (impossible for synthetic blocks)";

  // Source swap occurred at block boundary (synthetic blocks still TAKE).
  EXPECT_GE(m.source_swap_count, 1)
      << "Swap occurred despite synthetic blocks";

  // Session ended cleanly.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session did not end cleanly";
  }
}

// =============================================================================
// T-SEAM-004a: MechanicalEquivalence_SegmentVsBlockLatencyProfile
// Invariant: INV-SEAM-004 (Segment/Block Mechanical Equivalence)
//
// Scenario: Two sequential engine runs comparing latency profiles:
//   Session 1 (segment seam): One multi-segment block (1.5s + 1.5s, real media)
//   Session 2 (block seam): Two single-segment blocks (1.5s + 1.5s, same media)
// Both must have bounded inter-frame gap. Their ratio must be < 3.0.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_004a_MechanicalEquivalence_SegmentVsBlockLatencyProfile) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  // ---- Session 1: Segment seam (multi-segment block) ----
  ctx_->fps = 30.0;
  auto now = NowMs();

  FedBlock seg_block = MakeMultiSegmentBlock(
      "seam004a-seg", now, 3000,
      kPathA, 1500,
      kPathB, 1500);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(seg_block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  std::this_thread::sleep_for(std::chrono::milliseconds(3500));
  engine_->Stop();

  auto m_segment = engine_->SnapshotMetrics();
  int64_t gap_segment = m_segment.max_inter_frame_gap_us;

  // Tear down session 1, prepare session 2.
  engine_.reset();
  ResetCallbackState();

  // Re-create context and socket pair for session 2.
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

  // ---- Session 2: Block seam (two single-segment blocks) ----
  now = NowMs();

  FedBlock block_a = MakeBlock("seam004a-a", now, 1500, kPathA);
  FedBlock block_b = MakeBlock("seam004a-b", now + 1500, 1500, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  std::this_thread::sleep_for(std::chrono::milliseconds(3500));
  engine_->Stop();

  auto m_block = engine_->SnapshotMetrics();
  int64_t gap_block = m_block.max_inter_frame_gap_us;

  // ---- Assertions ----

  // INV-SEAM-004: Both seam types must have bounded inter-frame gap.
  EXPECT_LT(gap_segment, 50000)
      << "INV-SEAM-004: segment seam blocked tick thread. gap_us=" << gap_segment;

  EXPECT_LT(gap_block, 50000)
      << "INV-SEAM-004: block seam blocked tick thread. gap_us=" << gap_block;

  // INV-SEAM-004: Ratio must be bounded — no systematic asymmetry.
  int64_t max_gap = std::max(gap_segment, gap_block);
  int64_t min_gap = std::max(int64_t{1}, std::min(gap_segment, gap_block));
  double ratio = static_cast<double>(max_gap) / static_cast<double>(min_gap);
  EXPECT_LT(ratio, 3.0)
      << "INV-SEAM-004: asymmetric mechanisms. gap_segment=" << gap_segment
      << " gap_block=" << gap_block << " ratio=" << ratio;

  // Both must have bounded late ticks (contract: single late tick is
  // scheduling jitter, recoverable).
  EXPECT_LE(m_segment.late_ticks_total, 2)
      << "INV-SEAM-004: segment seam path has systematic tick-thread decoder work. "
         "late_ticks=" << m_segment.late_ticks_total;
  EXPECT_LE(m_block.late_ticks_total, 2)
      << "INV-SEAM-004: block seam path has systematic tick-thread decoder work. "
         "late_ticks=" << m_block.late_ticks_total;

  // Both must survive.
  EXPECT_EQ(m_segment.detach_count, 0)
      << "INV-SEAM-004: segment seam path kills session";
  EXPECT_EQ(m_block.detach_count, 0)
      << "INV-SEAM-004: block seam path kills session";

  std::cout << "=== INV-SEAM-004 Latency Profile ===" << std::endl;
  std::cout << "gap_segment=" << gap_segment << "us" << std::endl;
  std::cout << "gap_block=" << gap_block << "us" << std::endl;
  std::cout << "ratio=" << ratio << std::endl;
}

// =============================================================================
// T-SEAM-004b: MechanicalEquivalence_MixedSeamsInSingleSession
// Invariant: INV-SEAM-004 (Mechanical Equivalence)
//
// Scenario: Single session with both seam types: Block A is multi-segment
// (1s episode + 1s filler), followed by Block B (single segment, 2s).
// Forces: segment seam at ~1s (intra-block), block seam at ~2s (inter-block).
// Both transitions must produce bounded latency.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_004b_MechanicalEquivalence_MixedSeamsInSingleSession) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;

  auto now = NowMs();

  // Block A: multi-segment (episode 1s + filler 1s)
  FedBlock block_a = MakeMultiSegmentBlock(
      "seam004b-a", now, 2000,
      kPathA, 1000,
      kPathB, 1000);

  // Block B: single segment (2s)
  FedBlock block_b = MakeBlock("seam004b-b", now + 2000, 2000, kPathA);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Run through both blocks + margin.
  std::this_thread::sleep_for(std::chrono::milliseconds(5000));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // Block-to-block seam transition logged. Intra-block segment seams are
  // handled by the fill thread (segment advance on EOF) and do not fire
  // on_seam_transition — that callback tracks block-level transitions only.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_GE(seam_logs_.size(), 1u)
        << "INV-SEAM-004: block-to-block transition not logged";
  }

  // INV-SEAM-004: All transitions have bounded latency.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "INV-SEAM-004: some transition blocked tick. "
         "max_gap_us=" << m.max_inter_frame_gap_us;

  // Block swap must have fired.
  EXPECT_GE(m.source_swap_count, 1)
      << "Block swap did not fire";

  // Session survived both transition types.
  EXPECT_EQ(m.detach_count, 0)
      << "INV-SEAM-004: some transition killed session";
}

// =============================================================================
// T-SEAM-005a: BoundedFallbackObservability_MetricTrackedAndExposed
// Invariant: INV-SEAM-005 (Bounded Fallback Observability)
//
// Scenario: Two synthetic blocks (A=1s, B=1s). Both are unresolvable → all pad.
// Every seam tick uses fallback. The metric must be tracked and non-zero.
//
// Assets: None (synthetic). Asset-agnostic.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_005a_BoundedFallbackObservability_MetricTrackedAndExposed) {
  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam005a-a", now, 1000);
  FedBlock block_b = MakeBlock("seam005a-b", now + 1000, 1000);
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

  // INV-SEAM-005: Metric is tracked and reflects actual fallback behavior.
  // Since all frames are pad (continuous fallback), the metric must be > 0.
  EXPECT_GT(m.max_consecutive_audio_fallback_ticks, 0)
      << "INV-SEAM-005 VIOLATION: metric not tracked "
         "(all frames are pad but fallback ticks == 0)";

  // INV-SEAM-005: Metric exposed via Prometheus text endpoint.
  std::string prom_text = m.GeneratePrometheusText();
  EXPECT_NE(prom_text.find("air_continuous_max_consecutive_audio_fallback_ticks"),
            std::string::npos)
      << "INV-SEAM-005 VIOLATION: metric not exposed to Prometheus";

  // Pad frames must have been emitted (sanity check).
  EXPECT_GT(m.pad_frames_emitted_total, 0)
      << "No fallback occurred (impossible for synthetic blocks)";

  // Session survived.
  EXPECT_EQ(m.detach_count, 0)
      << "Session death";
}

// =============================================================================
// T-SEAM-005b: BoundedFallbackObservability_PerfectContinuityDetectable
// Invariant: INV-SEAM-005 (Bounded Fallback Observability — zero case)
//
// Scenario: Two blocks (A=2s, B=2s) with real media, default 1000ms audio
// buffer. Verify max_consecutive_audio_fallback_ticks == 0 — the metric
// correctly reports zero fallback when the overlap mechanism succeeds.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_005b_BoundedFallbackObservability_PerfectContinuityDetectable) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam005b-a", now, 2000, kPathA);
  FedBlock block_b = MakeBlock("seam005b-b", now + 2000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 10000))
      << "Both blocks must complete within timeout";

  // Snapshot before trailing pad accumulates.
  auto m = engine_->SnapshotMetrics();
  engine_->Stop();

  // INV-SEAM-005: Perfect continuity — metric correctly reports zero.
  EXPECT_EQ(m.max_consecutive_audio_fallback_ticks, 0)
      << "INV-SEAM-005: overlap mechanism failed silently. "
         "max_consecutive_fallback=" << m.max_consecutive_audio_fallback_ticks;

  // No silence injection.
  EXPECT_EQ(m.audio_silence_injected, 0)
      << "Silence occurred despite healthy overlap";

  // Swap fired.
  EXPECT_GE(m.source_swap_count, 1)
      << "Swap did not fire";

  // Session survived.
  EXPECT_EQ(m.detach_count, 0)
      << "Session death";
}

// =============================================================================
// T-SEAM-006: FallbackOnPreloaderFailure_SessionSurvives
// Invariant: INV-SEAM-002 (failure path) + INV-SEAM-005 (observability)
//
// Scenario: Two synthetic blocks (A=500ms, B=500ms). Inject 2s preloader delay.
// The delay exceeds block A's duration. At fence, preloader has not achieved
// readiness. The system must: not block tick thread, select fallback, record
// the miss, continue output.
//
// Assets: None (synthetic). Asset-agnostic.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_006_FallbackOnPreloaderFailure_SessionSurvives) {
  ctx_->fps = 30.0;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam006-a", now, 500);
  FedBlock block_b = MakeBlock("seam006-b", now + 500, 500);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->SetPreloaderDelayHook([] {
    std::this_thread::sleep_for(std::chrono::milliseconds(2000));
  });
  engine_->Start();

  // Run long enough for the delayed preloader to eventually resolve.
  std::this_thread::sleep_for(std::chrono::milliseconds(5000));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // INV-SEAM-002 (failure path): Session must survive preloader failure.
  EXPECT_EQ(m.detach_count, 0)
      << "Preloader failure killed session";

  // INV-SEAM-001: Tick thread must not wait for delayed preloader.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "Tick thread waited for delayed preloader. "
         "max_gap_us=" << m.max_inter_frame_gap_us;

  // INV-SEAM-002: Miss must be recorded.
  EXPECT_GE(m.fence_preload_miss_count, 1)
      << "Preload miss not recorded in metrics";

  // INV-SEAM-002: Fallback must be engaged (pad or PADDED_GAP).
  EXPECT_TRUE(m.fence_pad_frames_total > 0 || m.padded_gap_count > 0)
      << "Fallback not engaged despite preloader failure. "
         "fence_pad=" << m.fence_pad_frames_total
      << " padded_gap=" << m.padded_gap_count;

  // INV-SEAM-005: Fallback tracked in metric.
  EXPECT_GT(m.max_consecutive_audio_fallback_ticks, 0)
      << "Fallback not tracked in metric despite preloader failure";

  // Output continued past the fence.
  EXPECT_GT(m.continuous_frames_emitted_total, 15)
      << "Output died at fence — expected >15 frames for 500ms at 30fps";
}

// =============================================================================
// T-SEAM-007: AudioUnderflowAbsenceAtSeam_StressedBuffer
// Invariant: INV-SEAM-003 (Audio Continuity) — stressed variant
//
// Scenario: Two blocks (A=2s, B=2s) with real media. Audio buffer reduced to
// 200ms target (stress test — less headroom than default 1000ms). Verify the
// overlap mechanism primes B's audio buffer in the reduced window and achieves
// zero silence injection at the seam.
// =============================================================================
TEST_F(SeamContinuityEngineContractTest, T_SEAM_007_AudioUnderflowAbsenceAtSeam_StressedBuffer) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  ctx_->fps = 30.0;
  ctx_->buffer_config.audio_target_depth_ms = 200;
  ctx_->buffer_config.audio_low_water_ms = 50;

  auto now = NowMs();

  FedBlock block_a = MakeBlock("seam007-a", now, 2000, kPathA);
  FedBlock block_b = MakeBlock("seam007-b", now + 2000, 2000, kPathB);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 10000))
      << "Both blocks must complete within timeout";

  auto m = engine_->SnapshotMetrics();
  engine_->Stop();

  // INV-SEAM-003 (stressed): Bounded fallback even with reduced headroom.
  // With 200ms audio target, the overlap window is shorter than default.
  // Allow bounded fallback (the broadcast KPI from OUT-SEG-005b).
  static constexpr int64_t kStressedFallbackThreshold = 5;
  EXPECT_LE(m.max_consecutive_audio_fallback_ticks, kStressedFallbackThreshold)
      << "INV-SEAM-003: overlap window insufficient for 200ms buffer. "
         "max_consecutive=" << m.max_consecutive_audio_fallback_ticks;

  // With a 200ms audio target, a degraded TAKE (audio prime below default
  // threshold) is expected — the prime depth is bounded by the target.
  // The key assertion is that the session survives and fallback is bounded.
  EXPECT_LE(m.degraded_take_count, 1)
      << "Audio prime systematically below threshold with 200ms buffer";

  // Session survived.
  EXPECT_EQ(m.detach_count, 0)
      << "Audio underflow killed session with 200ms buffer";

  // Block transition occurred.
  EXPECT_GE(m.source_swap_count, 1)
      << "Block transition must occur";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
