// Repository: Retrovue-playout
// Component: Program Block Authority Contract Tests
// Purpose: Verify outcomes defined in program_block_authority_contract.md
// Contract Reference: pkg/air/docs/contracts/coordination/ProgramBlockAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-BLOCK-001: BlockTransferOccursOnlyAtFence
//   T-BLOCK-002: BlockLifecycleEventsAreEmitted
//   T-BLOCK-003: BlockCompletionIsRecordedAtFence
//   T-BLOCK-004: BlockToBlockTransitionSatisfiesSegmentContinuity
//   T-BLOCK-005: MissingNextBlockPadsInsteadOfStopping

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

using test_infra::kBootGuardMs;
using test_infra::kBlockTimeOffsetMs;
using test_infra::kStdBlockMs;
using test_infra::kShortBlockMs;

// =============================================================================
// Test Fixture
// =============================================================================

class ProgramBlockAuthorityContractTest : public ::testing::Test {
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
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      completed_fence_frames_.push_back(ct);
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
    callbacks.on_playback_proof = [this](const BlockPlaybackProof& proof) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      proofs_.push_back(proof);
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
  std::vector<int64_t> completed_fence_frames_;
  std::vector<SeamTransitionLog> seam_logs_;
  std::vector<BlockPlaybackSummary> summaries_;
  std::vector<BlockPlaybackProof> proofs_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// T-BLOCK-001: BlockTransferOccursOnlyAtFence
// Contract: OUT-BLOCK-001 — Block ownership MUST transfer only at fence tick.
//
// Scenario: Two wall-anchored blocks (A=1s, B=1s). Collect fingerprints.
// Verify: all frames with active_block_id=="A" have session_frame_index
// strictly less than the fence tick; all "B" frames are at or after it.
// No content lifecycle event advances ownership early.
// =============================================================================
TEST_F(ProgramBlockAuthorityContractTest, T_BLOCK_001_BlockTransferOccursOnlyAtFence) {
  auto now = NowMs();

  FedBlock block_a = MakeBlock("blk001a", now, kStdBlockMs);
  FedBlock block_b = MakeBlock("blk001b", now + kStdBlockMs, kStdBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 10000))
      << "Block A must complete at its fence";

  // Let B run for a bit, then stop.
  std::this_thread::sleep_for(std::chrono::milliseconds(1500));
  engine_->Stop();

  auto fps = SnapshotFingerprints();

  // Derive fence tick from fingerprints: first frame where active_block_id
  // changes from block A.  The ct value from on_block_completed is
  // ct_at_fence_ms (content time in milliseconds), not a frame index.
  int64_t a_fence_tick = -1;
  for (size_t i = 1; i < fps.size(); ++i) {
    if (fps[i].active_block_id != "blk001a") {
      a_fence_tick = static_cast<int64_t>(i);
      break;
    }
  }
  ASSERT_GT(a_fence_tick, 0) << "Must find block transition in fingerprints";
  ASSERT_GT(fps.size(), static_cast<size_t>(a_fence_tick))
      << "Must have fingerprints past the fence tick";

  // OUT-BLOCK-001: Verify no B-identified frames before the fence.
  for (const auto& fp : fps) {
    if (fp.active_block_id == "blk001b") {
      EXPECT_GE(fp.session_frame_index, a_fence_tick)
          << "OUT-BLOCK-001 VIOLATION: block B frame at index "
          << fp.session_frame_index << " appeared before fence tick "
          << a_fence_tick;
    }
    if (fp.active_block_id == "blk001a" && !fp.is_pad) {
      EXPECT_LT(fp.session_frame_index, a_fence_tick)
          << "OUT-BLOCK-001 VIOLATION: block A content frame at index "
          << fp.session_frame_index << " appeared at or after fence tick "
          << a_fence_tick;
    }
  }

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// T-BLOCK-002: BlockLifecycleEventsAreEmitted
// Contract: OUT-BLOCK-002 — On block start and completion, the system MUST
// emit block lifecycle events containing block_id, scheduled wall-clock end,
// actual fence tick, and verdict/proof fields.
//
// Scenario: Single block (1s, synthetic). Verify on_block_completed fires
// with correct block_id, and on_block_summary + on_playback_proof fire with
// the required fields.
// =============================================================================
TEST_F(ProgramBlockAuthorityContractTest, T_BLOCK_002_BlockLifecycleEventsAreEmitted) {
  auto now = NowMs();

  // Schedule after bootstrap so fence fires at the correct wall-clock instant.
  FedBlock block = MakeBlock("blk002", now + kBlockTimeOffsetMs, kShortBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 8000))
      << "Block must complete at fence";

  // Let post-fence pad run briefly, then stop.
  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  engine_->Stop();

  // OUT-BLOCK-002: on_block_completed fired with correct block_id.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_EQ(completed_blocks_.size(), 1u);
    EXPECT_EQ(completed_blocks_[0], "blk002");
  }

  // OUT-BLOCK-002: on_block_summary fired with required fields.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(summaries_.size(), 1u)
        << "OUT-BLOCK-002: on_block_summary must fire at block completion";
    const auto& s = summaries_[0];
    EXPECT_EQ(s.block_id, "blk002")
        << "Summary must contain block_id";
    EXPECT_GT(s.frames_emitted, 0)
        << "Summary must contain emitted frame count";
    EXPECT_GE(s.first_session_frame_index, 0)
        << "Summary must contain session frame range";
  }

  // OUT-BLOCK-002: on_playback_proof fired with verdict.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(proofs_.size(), 1u)
        << "OUT-BLOCK-002: on_playback_proof must fire at block completion";
    const auto& p = proofs_[0];
    EXPECT_EQ(p.wanted.block_id, "blk002")
        << "Proof must contain block_id";
    // Synthetic block → all pad → verdict is ALL_PAD.
    EXPECT_EQ(p.verdict, PlaybackProofVerdict::kAllPad)
        << "Proof verdict must reflect actual execution";
  }
}

// =============================================================================
// T-BLOCK-003: BlockCompletionIsRecordedAtFence
// Contract: OUT-BLOCK-003 — On fence tick, the outgoing block MUST be
// finalized with emitted frame count, pad frame count, and a completion event.
//
// Scenario: Single block (1s, synthetic). Verify on_block_summary contains
// accurate frame counts matching the metrics.
// =============================================================================
TEST_F(ProgramBlockAuthorityContractTest, T_BLOCK_003_BlockCompletionIsRecordedAtFence) {
  auto now = NowMs();

  // Schedule after bootstrap so fence fires at the correct wall-clock instant.
  FedBlock block = MakeBlock("blk003", now + kBlockTimeOffsetMs, kShortBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 8000));

  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  engine_->Stop();

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(summaries_.size(), 1u)
        << "on_block_summary must fire at fence";
    const auto& s = summaries_[0];

    // OUT-BLOCK-003: Emitted frame count present and positive.
    EXPECT_GT(s.frames_emitted, 0)
        << "OUT-BLOCK-003: block must have emitted frames";

    // OUT-BLOCK-003: Pad frame count recorded.
    // Synthetic block → all pad → pad == total.
    EXPECT_EQ(s.pad_frames, s.frames_emitted)
        << "OUT-BLOCK-003: pad count must equal total for synthetic block";

    // OUT-BLOCK-003: Block ID recorded.
    EXPECT_EQ(s.block_id, "blk003");

    // OUT-BLOCK-003: Session frame range recorded.
    EXPECT_GE(s.first_session_frame_index, 0);
    EXPECT_GE(s.last_session_frame_index, s.first_session_frame_index);
  }

  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.total_blocks_executed, 1)
      << "OUT-BLOCK-003: block completion event must be recorded";
}

// =============================================================================
// T-BLOCK-004: BlockToBlockTransitionSatisfiesSegmentContinuity
// Contract: OUT-BLOCK-004 — Block-to-block transition MUST invoke segment
// continuity outcomes (cross-reference: Segment Continuity Contract).
//
// Scenario: Two wall-anchored blocks (A=1s, B=1s, synthetic). Verify:
// - No session death (OUT-SEG-002)
// - Audio continuous (OUT-SEG-003 via pad)
// - Tick loop not blocked (OUT-SEG-005)
// - Seam transition logged (OUT-BLOCK-002/003)
// =============================================================================
TEST_F(ProgramBlockAuthorityContractTest, T_BLOCK_004_BlockToBlockTransitionSatisfiesSegmentContinuity) {
  auto now = NowMs();

  FedBlock block_a = MakeBlock("blk004a", now, kShortBlockMs);
  FedBlock block_b = MakeBlock("blk004b", now + kShortBlockMs, kShortBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 8000))
      << "Both blocks must complete";

  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-SEG-002 (via OUT-BLOCK-004): No session death.
  EXPECT_EQ(m.detach_count, 0)
      << "OUT-BLOCK-004/SEG-002: block-to-block must not kill session";

  // OUT-SEG-005 (via OUT-BLOCK-004): Tick loop not blocked.
  EXPECT_LT(m.max_inter_frame_gap_us, 50000)
      << "OUT-BLOCK-004/SEG-005: tick loop must not block at block transition";

  // Both blocks completed.
  EXPECT_GE(m.total_blocks_executed, 2);
  EXPECT_GE(m.source_swap_count, 1)
      << "Must have at least 1 source swap (A→B)";

  // Seam transition logged.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_GE(seam_logs_.size(), 1u)
        << "OUT-BLOCK-004: seam transition log must be emitted at block boundary";
    if (!seam_logs_.empty()) {
      EXPECT_EQ(seam_logs_[0].from_block_id, "blk004a");
      EXPECT_EQ(seam_logs_[0].to_block_id, "blk004b");
    }
  }

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// T-BLOCK-005: MissingNextBlockPadsInsteadOfStopping
// Contract: OUT-BLOCK-005 — Missing/late next block MUST result in PADDED_GAP,
// not stream death.
//
// Scenario: Single block (1s, synthetic). No block B in queue at fence.
// Verify session enters PAD mode, continues output, and records PADDED_GAP.
// =============================================================================
TEST_F(ProgramBlockAuthorityContractTest, T_BLOCK_005_MissingNextBlockPadsInsteadOfStopping) {
  auto now = NowMs();

  // Only block A in queue. At fence, no B → PADDED_GAP.
  // Schedule after bootstrap so fence fires at the correct wall-clock instant.
  FedBlock block_a = MakeBlock("blk005", now + kBlockTimeOffsetMs, kStdBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // kBootGuardMs + duration + margin for post-fence pad.
  std::this_thread::sleep_for(std::chrono::milliseconds(
      kBootGuardMs + kStdBlockMs + 500));
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // OUT-BLOCK-005: Continue continuous output (no teardown).
  EXPECT_EQ(m.detach_count, 0)
      << "OUT-BLOCK-005 VIOLATION: missing next block killed session";

  // OUT-BLOCK-005: Record the gap as PADDED_GAP.
  EXPECT_GE(m.padded_gap_count, 1)
      << "OUT-BLOCK-005: padded_gap_count must increment when no next block";

  // OUT-BLOCK-005: Pad frames emitted after fence.
  EXPECT_GT(m.fence_pad_frames_total, 0)
      << "OUT-BLOCK-005: must emit pad frames during PADDED_GAP";

  // OUT-BLOCK-005: Session survived and emitted frames past the fence.
  // At 30fps, 1s = 30 frames. We expect > 30 (block A) + some pad.
  EXPECT_GT(m.continuous_frames_emitted_total, 30)
      << "Session must continue emitting past the fence";

  // Block A completed.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(completed_blocks_.size(), 1u);
    EXPECT_EQ(completed_blocks_[0], "blk005");
  }

  // Session ended cleanly.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "OUT-BLOCK-005: session must end cleanly";
  }
}

}  // namespace
}  // namespace retrovue::blockplan::testing
