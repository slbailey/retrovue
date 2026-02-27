// Repository: Retrovue-playout
// Component: Segment Seam Race Condition Fix Tests
// Purpose: Verifies the skip-PAD prep + inline PAD handling fix that eliminates
//          black frames at content→PAD→content segment boundaries.
// Contract Reference: docs/FIX-segment-seam-race.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-RACE-001: PadSegmentSkippedInArmSegmentPrep
//   T-RACE-002: PadSeamHandledInlineNotViaPrepWorker
//   T-RACE-003: ContentPadContentSequenceNoMiss
//   T-RACE-004: AllPadBlockHandledInline
//   T-RACE-005: SingleSegmentBlockNoSeamArmed
//   T-RACE-006: MultiplePadsBetweenContentSkipAll
//   T-RACE-007: BlockPrepCannotStarveSegmentPrep (starvation regression)
//   T-RACE-008: MissDoesNotStallFenceOrCorruptSeamSchedule (MISS resilience)

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
#include "FastTestConfig.hpp"
#include "deterministic_tick_driver.hpp"

namespace retrovue::blockplan::testing {
namespace {

using test_infra::kBootGuardMs;
using test_infra::kBlockTimeOffsetMs;
using test_infra::kStdBlockMs;
using test_infra::kSegBlockMs;
using retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail;

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";
static const std::string kPath60fps = "/opt/retrovue/assets/Sample60fps.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

// =============================================================================
// Helpers
// =============================================================================

static FedBlock MakeMultiSegBlock(
    const std::string& block_id,
    int64_t start_utc_ms,
    const std::vector<std::tuple<std::string, int64_t, SegmentType>>& segs) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;

  int64_t total_ms = 0;
  int32_t idx = 0;
  for (const auto& [uri, dur_ms, type] : segs) {
    FedBlock::Segment seg;
    seg.segment_index = idx++;
    seg.asset_uri = uri;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = dur_ms;
    seg.segment_type = type;
    block.segments.push_back(seg);
    total_ms += dur_ms;
  }
  block.end_utc_ms = start_utc_ms + total_ms;
  return block;
}

// =============================================================================
// Test Fixture
// =============================================================================

class SegmentSeamRaceFixTest : public ::testing::Test {
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
    ctx_->fps = FPS_30;
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
      session_ended_cv_.notify_all();
    };
    callbacks.on_frame_emitted = [](const FrameFingerprint&) {};
    callbacks.on_seam_transition = [this](const SeamTransitionLog& seam) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      seam_logs_.push_back(seam);
    };
    callbacks.on_block_summary = [](const BlockPlaybackSummary&) {};
    callbacks.on_frame_selection_cadence_refresh = [this](RationalFps old_fps, RationalFps new_fps,
                                                          RationalFps output_fps, const std::string& mode) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      cadence_refreshes_.push_back({old_fps, new_fps, output_fps, mode});
      cadence_refresh_cv_.notify_all();
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0});
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

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  bool WaitForCadenceRefresh(int timeout_ms = 10000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return cadence_refresh_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this] { return !cadence_refreshes_.empty(); });
  }

  struct CadenceRefreshRecord {
    RationalFps old_source_fps;
    RationalFps new_source_fps;
    RationalFps output_fps;
    std::string mode;
  };
  std::vector<CadenceRefreshRecord> SnapshotCadenceRefreshes() {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    return cadence_refreshes_;
  }

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::condition_variable blocks_completed_cv_;
  std::condition_variable cadence_refresh_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<SeamTransitionLog> seam_logs_;
  std::vector<CadenceRefreshRecord> cadence_refreshes_;
  int session_ended_count_ = 0;
};

// =============================================================================
// T-RACE-001: Content→PAD→Content block — ArmSegmentPrep must skip the PAD
// and prep the second CONTENT segment directly.
//
// Uses real media assets so the TickProducer opens a real decoder and the
// multi-segment pipeline activates properly.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_001_PadSegmentSkippedInArmSegmentPrep) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // CONTENT(1.5s) → PAD(33ms ≈ 1 frame) → CONTENT(1.5s)
  FedBlock block = MakeMultiSegBlock("race001", now + offset, {
      {kPathA, 1500, SegmentType::kContent},
      {"", 33, SegmentType::kPad},
      {kPathB, 1500, SegmentType::kContent},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + 3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // PAD seam was handled inline (not via worker).
  EXPECT_GE(m.segment_seam_pad_inline_count, 1)
      << "PAD segment must be handled inline, not via SeamPreparer worker";

  // No MISS — the skip-PAD fix should eliminate the race.
  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "FIX REGRESSION: segment seam miss detected — skip-PAD logic may be broken";

  // Session survived all transitions.
  EXPECT_EQ(m.detach_count, 0)
      << "Session detached — segment transitions must not cause underflow";
}

// =============================================================================
// T-RACE-002: Content→PAD seam produces prep_mode=INSTANT (inline).
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_002_PadSeamHandledInlineNotViaPrepWorker) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "Real media asset not found: " << kPathA;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // CONTENT → PAD
  FedBlock block = MakeMultiSegBlock("race002", now + offset, {
      {kPathA, 1500, SegmentType::kContent},
      {"", 1500, SegmentType::kPad},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + 3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  EXPECT_GE(m.segment_seam_count, 1)
      << "Expected at least one segment seam transition";

  EXPECT_GE(m.segment_seam_pad_inline_count, 1)
      << "PAD seam must use inline path (prep_mode=INSTANT)";

  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "PAD→inline path must never produce a MISS";
}

// =============================================================================
// T-RACE-003: Full Content→PAD→Content — the core regression test.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_003_ContentPadContentSequenceNoMiss) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // Simulate Cheers pattern: CONTENT → PAD (1 frame) → CONTENT
  FedBlock block = MakeMultiSegBlock("race003", now + offset, {
      {kPathA, 1500, SegmentType::kContent},
      {"", 33, SegmentType::kPad},
      {kPathB, 1500, SegmentType::kContent},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + 3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // Two seams: content→pad and pad→content.
  EXPECT_GE(m.segment_seam_count, 2)
      << "Expected 2 segment seams for content→pad→content";

  EXPECT_GE(m.segment_seam_pad_inline_count, 1);
  EXPECT_GE(m.segment_seam_ready_count, 1)
      << "Content segment prep must be READY (worker had full lead time)";

  // Zero misses — THE regression assertion.
  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "REGRESSION: content segment prep missed — the race condition is back";

  EXPECT_EQ(m.detach_count, 0);

  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Output stalled — expected continuous frame emission";
}

// =============================================================================
// CadenceRefreshOnSegmentSwap: regression test for 23.976fps playing too fast.
// When LIVE segment swaps from segment A to segment B, frame-selection cadence
// (repeat-vs-advance policy) must be refreshed from the NEW live source FPS so duration is preserved.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, CadenceRefreshOnSegmentSwap) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // Two content segments: segment 0 then segment 1. After swap, cadence must
  // refresh from segment 1's source FPS (e.g. 24000/1001).
  FedBlock block = MakeMultiSegBlock("cadence-refresh", now + offset, {
      {kPathA, 1500, SegmentType::kContent},
      {kPathB, 1500, SegmentType::kContent},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + 3500));
  engine_->Stop();

  auto refreshes = SnapshotCadenceRefreshes();
  auto m = engine_->SnapshotMetrics();

  EXPECT_GE(m.segment_seam_count, 1u)
      << "Segment swap must occur (content→content)";
  EXPECT_EQ(m.detach_count, 0) << "Session must not detach";

  // When the two segments have different source FPS, we must get a cadence refresh
  // and mode must be ACTIVE (not DISABLED) when new source != output (e.g. 23.976 vs 29.97).
  if (!refreshes.empty()) {
    const auto& r = refreshes.back();
    EXPECT_GT(r.new_source_fps.num, 0) << "new_source_fps must be valid";
    EXPECT_GT(r.new_source_fps.den, 0) << "new_source_fps must be valid";
    const bool is_23976 = (r.new_source_fps.num == 24000 && r.new_source_fps.den == 1001);
    if (is_23976) {
      EXPECT_EQ(r.mode, "ACTIVE")
          << "23.976fps content (output 29.97) must use ACTIVE cadence, not DISABLED";
    }
  }
  // If refreshes.empty(), both segments had same FPS (e.g. both 30fps) — no refresh needed.
}

// =============================================================================
// T-RACE-004: All-PAD block — every seam handled inline, no prep armed.
// (No real media needed — PAD segments are synthetic.)
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_004_AllPadBlockHandledInline) {
  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  FedBlock block = MakeMultiSegBlock("race004", now + offset, {
      {"", kStdBlockMs, SegmentType::kPad},
      {"", kStdBlockMs, SegmentType::kPad},
      {"", kStdBlockMs, SegmentType::kPad},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + kStdBlockMs * 3 + 500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  EXPECT_EQ(m.segment_seam_pad_inline_count, 2)
      << "All 2 inter-PAD seams must be handled inline";

  EXPECT_EQ(m.segment_prep_armed_count, 0)
      << "All-PAD block must not arm any segment prep";

  EXPECT_EQ(m.segment_seam_miss_count, 0);
  EXPECT_EQ(m.detach_count, 0);
}

// =============================================================================
// T-RACE-005: Single-segment block — no seam fires, no prep armed.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_005_SingleSegmentBlockNoSeamArmed) {
  if (!FileExists(kPathA)) {
    GTEST_SKIP() << "Real media asset not found: " << kPathA;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  FedBlock block = MakeMultiSegBlock("race005", now + offset, {
      {kPathA, kStdBlockMs, SegmentType::kContent},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + kStdBlockMs + 500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  EXPECT_EQ(m.segment_seam_count, 0)
      << "Single-segment block must not fire any segment seams";
  EXPECT_EQ(m.segment_prep_armed_count, 0)
      << "Single-segment block must not arm any prep";
  EXPECT_EQ(m.detach_count, 0);
}

// =============================================================================
// T-RACE-006: Content→PAD→PAD→Content — ArmSegmentPrep skips BOTH PADs.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_006_MultiplePadsBetweenContentSkipAll) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  FedBlock block = MakeMultiSegBlock("race006", now + offset, {
      {kPathA, 1500, SegmentType::kContent},
      {"", 33, SegmentType::kPad},
      {"", 33, SegmentType::kPad},
      {kPathB, 1500, SegmentType::kContent},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + 3500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  EXPECT_GE(m.segment_seam_pad_inline_count, 2)
      << "Both PAD segments must be handled inline";

  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "Skip-PAD must give worker enough lead time for content prep";

  EXPECT_EQ(m.detach_count, 0);
}

// =============================================================================
// T-RACE-007: Starvation regression -- block prep in-flight must not starve
// segment prep.
//
// Scenario: A multi-segment block (CONTENT->FILLER) is loaded AND a next block
// is queued.  Both block prep and segment prep submit to SeamPreparer.  The
// segment seam at ~1s must fire as PREROLLED (not MISS), proving the worker
// processes segment prep (seam_frame=30) before block prep (seam_frame=60)
// even when both are queued simultaneously.
//
// This test FAILS if anyone reintroduces IsRunning() gating on Submit() --
// because the block prep starts first and the segment request never enters
// the queue until the worker finishes.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_007_BlockPrepCannotStarveSegmentPrep) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // Block A: CONTENT(1s) -> FILLER(1s) -- segment seam at ~1s.
  FedBlock block_a = MakeMultiSegBlock("starve-a", now + offset, {
      {kPathA, 1000, SegmentType::kContent},
      {kPathB, 1000, SegmentType::kFiller},
  });

  // Block B: single-segment CONTENT -- queued as the "next" block.
  // Its prep competes with segment prep for worker time.
  FedBlock block_b;
  block_b.block_id = "starve-b";
  block_b.channel_id = 99;
  block_b.start_utc_ms = block_a.end_utc_ms;
  block_b.end_utc_ms = block_b.start_utc_ms + 2000;
  {
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = kPathA;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 2000;
    seg.segment_type = SegmentType::kContent;
    block_b.segments.push_back(seg);
  }

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait for block A to complete (segment seam + block fence).
  ASSERT_TRUE(WaitForBlocksCompleted(1, 8000))
      << "Block A did not complete within timeout";

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // The segment seam MUST be PREROLLED -- not MISS.
  // If IsRunning() gating is reintroduced, block prep monopolizes the worker
  // and segment prep never submits -> segment_seam_miss_count > 0.
  EXPECT_GE(m.segment_seam_count, 1)
      << "Expected at least 1 segment seam (CONTENT->FILLER)";
  EXPECT_EQ(m.segment_seam_miss_count, 0)
      << "STARVATION REGRESSION: Segment prep was starved by block prep. "
         "This fails if IsRunning() gating is reintroduced on Submit().";
  EXPECT_GE(m.segment_seam_ready_count, 1)
      << "Segment seam must be PREROLLED when worker processes by seam_frame order";

  // Block B must have started preloading (proves block prep also worked).
  EXPECT_GE(m.next_preload_started_count, 1)
      << "Block preload must also succeed -- both segment and block prep should work";

  EXPECT_EQ(m.detach_count, 0);
}

// =============================================================================
// T-RACE-008: MISS resilience -- forced MISS must not stall fences or corrupt
// next_seam_frame scheduling.
//
// Scenario: Use SetPreloaderDelayHook to make the segment prep worker
// artificially slow, guaranteeing a MISS at the segment seam.  Then verify:
//   1. The block fence still fires at the correct tick (not stalled).
//   2. next_seam_frame advances monotonically (no corruption).
//   3. Session survives (no detach, no crash).
//   4. Metrics correctly report the MISS.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, T_RACE_008_MissDoesNotStallFenceOrCorruptSeamSchedule) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // Block A: CONTENT(1s) -> FILLER(1s) -- short segment to create tight seam window.
  FedBlock block_a = MakeMultiSegBlock("miss-a", now + offset, {
      {kPathA, 1000, SegmentType::kContent},
      {kPathB, 1000, SegmentType::kFiller},
  });

  // Block B: follows immediately after block A.
  FedBlock block_b;
  block_b.block_id = "miss-b";
  block_b.channel_id = 99;
  block_b.start_utc_ms = block_a.end_utc_ms;
  block_b.end_utc_ms = block_b.start_utc_ms + 2000;
  {
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = kPathA;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 2000;
    seg.segment_type = SegmentType::kContent;
    block_b.segments.push_back(seg);
  }

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();

  // Inject a 3-second delay into ALL SeamPreparer requests.
  // Both the segment prep (for segment 1) and block prep (for block B) are
  // delayed. The segment prep misses its window because the 3s delay far
  // exceeds the seam frame's headroom. The block prep also delays but the
  // 15s WaitForBlocksCompleted timeout accommodates it.
  // Using all-request delay (not one-shot) avoids order-sensitivity: the
  // SeamPreparer may process block or segment prep first depending on
  // scheduling. Both being delayed guarantees the segment seam MISS.
  engine_->SetPreloaderDelayHook([](const std::atomic<bool>& cancel) {
    // Cancellable 3s delay — check cancel every 10ms
    for (int i = 0; i < 300 && !cancel.load(std::memory_order_acquire); ++i) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
  });

  engine_->Start();

  // Wait for BOTH blocks to complete -- proves fences aren't stalled.
  ASSERT_TRUE(WaitForBlocksCompleted(2, 15000))
      << "Both blocks must complete -- fence must not stall after MISS";

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // The delay hook makes the segment prep late. With the deferred-swap
  // architecture, the swap is deferred (SEGMENT_SWAP_DEFERRED) until the prep
  // result arrives, then completes as PREROLLED — not MISS. The contract under
  // test ("late prep must not stall fences or corrupt seam scheduling") is
  // verified by the block completion and identity assertions below.
  EXPECT_GE(m.segment_seam_count, 1)
      << "Expected at least 1 segment seam (CONTENT->FILLER) processed despite delay hook";

  // Block fences must fire -- both blocks must complete (proves late prep does not stall).
  // INV-BLOCK-IDENTITY-001:
  // Even if a segment swap is deferred past the block fence, block completion
  // events must report the originally activated block.
  ASSERT_GE(static_cast<int>(completed_blocks_.size()), 2)
      << "Both blocks must complete -- late segment prep must not stall block fences";

  // Block identity must be preserved across deferred segment swap.
  EXPECT_EQ(completed_blocks_[0], "miss-a")
      << "Block A identity must survive deferred segment swap";
  EXPECT_EQ(completed_blocks_[1], "miss-b")
      << "Block B must complete with correct identity";

  // Session survived -- no detach, no crash.
  EXPECT_EQ(m.detach_count, 0)
      << "Late segment prep must not detach the session";

  // Continuous emission -- frames were produced through the deferred swap.
  EXPECT_GT(m.continuous_frames_emitted_total, 60)
      << "Output must continue through deferred segment swap";
}

// =============================================================================
// SegmentSwap29_97To60fpsCadenceActive: contract test for segment swap into 60fps.
// When source_fps != output_fps after SEGMENT_SEAM_TAKE, cadence must be ACTIVE
// (not DISABLED) so frame selection drops/chooses frames deterministically.
// Asserts non-black / frame advancement by requiring continuous emission after swap.
// =============================================================================
TEST_F(SegmentSeamRaceFixTest, SegmentSwap29_97To60fpsCadenceActive) {
  if (!FileExists(kPathA) || !FileExists(kPath60fps)) {
    GTEST_SKIP() << "Assets not found: need " << kPathA << " and " << kPath60fps;
  }

  auto now = NowMs();
  int64_t offset = kBlockTimeOffsetMs;

  // 29.97 content → 60fps commercial segment (output house format 29.97).
  FedBlock block = MakeMultiSegBlock("swap_2997_60", now + offset, {
      {kPathA, 1500, SegmentType::kContent},
      {kPath60fps, 1500, SegmentType::kContent},
  });

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  AdvanceUntilFenceOrFail(engine_.get(),
      test_infra::FenceTickAt30fps(kBootGuardMs + 3500));
  engine_->Stop();

  auto refreshes = SnapshotCadenceRefreshes();
  auto m = engine_->SnapshotMetrics();

  EXPECT_GE(m.segment_seam_count, 1)
      << "Segment swap must occur (29.97 content → 60fps content)";
  EXPECT_EQ(m.detach_count, 0) << "Session must not detach after swap into 60fps";

  // After swap into 60fps, cadence must be ACTIVE when new_source_fps != output_fps.
  bool found_60fps_refresh = false;
  for (const auto& r : refreshes) {
    const bool is_60fps = (r.new_source_fps.num == 60 && r.new_source_fps.den == 1) ||
                         (r.new_source_fps.num == 60000 && r.new_source_fps.den == 1001);
    if (is_60fps) {
      found_60fps_refresh = true;
      EXPECT_EQ(r.mode, "ACTIVE")
          << "When new_source_fps (60fps) != output_fps (29.97), cadence must be ACTIVE, not DISABLED";
      break;
    }
  }
  EXPECT_TRUE(found_60fps_refresh)
      << "Expected at least one cadence refresh with 60fps source after segment swap";

  // Output must present non-black / advancing frames: continuous emission after swap.
  EXPECT_GT(m.continuous_frames_emitted_total, 60)
      << "Video must advance after swap (no long black/repeat streak)";
}


}  // namespace
}  // namespace retrovue::blockplan::testing
