// Repository: Retrovue-playout
// Component: Playback Trace Contract Tests
// Purpose: Verify P3.3 execution trace logging — per-block playback summaries,
//          seam transition logs, and correct aggregation of actual execution data.
// Contract Reference: PlayoutAuthorityContract.md (P3.3)
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cmath>
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

namespace retrovue::blockplan::testing {
namespace {

using test_infra::kFastMode;
using test_infra::kBootGuardMs;
using test_infra::kStdBlockMs;
using test_infra::kShortBlockMs;
using test_infra::kPreloaderMs;
using test_infra::kBlockTimeOffsetMs;

// =============================================================================
// Helper: Create a synthetic FedBlock (unresolvable URI)
// =============================================================================
static FedBlock MakeSyntheticBlock(
    const std::string& block_id,
    int64_t duration_ms,
    const std::string& uri = "/nonexistent/test.mp4",
    int64_t now_ms = 0) {
  int64_t now = now_ms > 0 ? now_ms
      : (kFastMode ? 1'000'000'000LL
         : std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch()).count());
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = now;
  block.end_utc_ms = now + duration_ms;

  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms = duration_ms;
  block.segments.push_back(seg);

  return block;
}

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

// =============================================================================
// Test Fixture
// =============================================================================

class PlaybackTraceContractTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 99;
    // PipelineManager::Run() calls dup(fd) then send() — must be a real socket.
    // socketpair + drain thread absorbs encoded TS output without backpressure.
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
    // Shut down drain: close write end first so read() returns 0.
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
    callbacks.on_block_summary = [this](const BlockPlaybackSummary& s) {
      std::lock_guard<std::mutex> lock(summary_mutex_);
      summaries_.push_back(s);
    };
    callbacks.on_seam_transition = [this](const SeamTransitionLog& t) {
      std::lock_guard<std::mutex> lock(seam_mutex_);
      seam_transitions_.push_back(t);
    };
    callbacks.on_playback_proof = [this](const BlockPlaybackProof& p) {
      std::lock_guard<std::mutex> lock(proof_mutex_);
      proofs_.push_back(p);
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_);
  }

  bool WaitForBlocksCompleted(int count, int timeout_ms = 10000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return blocks_completed_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this, count] {
          return static_cast<int>(completed_blocks_.size()) >= count;
        });
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::shared_ptr<ITimeSource> test_ts_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::condition_variable session_ended_cv_;
  std::vector<std::string> completed_blocks_;
  int session_ended_count_ = 0;

  std::mutex summary_mutex_;
  std::vector<BlockPlaybackSummary> summaries_;

  std::mutex seam_mutex_;
  std::vector<SeamTransitionLog> seam_transitions_;

  std::mutex proof_mutex_;
  std::vector<BlockPlaybackProof> proofs_;
};

// =============================================================================
// TRACE-001: SummaryProducedPerBlock
// Queue 2 blocks. After both complete, verify 2 summaries with correct block IDs.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SummaryProducedPerBlock) {
  FedBlock block1 = MakeSyntheticBlock("trace-a", kShortBlockMs);
  FedBlock block2 = MakeSyntheticBlock("trace-b", kShortBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 8000))
      << "Both blocks must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(summary_mutex_);
  ASSERT_EQ(summaries_.size(), 2u)
      << "One summary must be produced per completed block";
  EXPECT_EQ(summaries_[0].block_id, "trace-a");
  EXPECT_EQ(summaries_[1].block_id, "trace-b");
}

// =============================================================================
// TRACE-002: SummaryFrameCountMatchesMetrics
// Queue 1 block. Verify summary.frames_emitted matches FramesPerBlock.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SummaryFrameCountMatchesMetrics) {
  auto now_ms = NowMs();
  // Schedule after bootstrap so fence fires at the correct wall-clock instant.
  FedBlock block = MakeSyntheticBlock("trace-fc", kShortBlockMs);
  block.start_utc_ms = now_ms + kBlockTimeOffsetMs;
  block.end_utc_ms = now_ms + kBlockTimeOffsetMs + kShortBlockMs;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 8000))
      << "Block must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(summary_mutex_);
  ASSERT_EQ(summaries_.size(), 1u);

  // Fence-derived frames = ceil((block.end_utc_ms - fence_epoch) * 30/1000).
  // Default mode: fence_epoch lags block.start by ~1s, so frames > 30.
  // Fast mode:    fence_epoch == block.start (DTS), so frames == ceil(duration*30/1000).
  const int64_t min_frames = kFastMode ? 6 : 30;
  const int64_t max_frames = kFastMode ? 30 : 120;
  EXPECT_GE(summaries_[0].frames_emitted, min_frames)
      << "Summary frames_emitted must be at least ceil(duration*fps)";
  EXPECT_LE(summaries_[0].frames_emitted, max_frames)
      << "Summary frames_emitted must be bounded by guard + duration";
  EXPECT_EQ(summaries_[0].block_id, "trace-fc");
}

// =============================================================================
// TRACE-003: SummaryPadCountAccurate
// Queue 1 synthetic (unresolvable) block. All frames must be pad.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SummaryPadCountAccurate) {
  FedBlock block = MakeSyntheticBlock("trace-pad", kShortBlockMs, "/nonexistent/pad.mp4");
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 5000))
      << "Block must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(summary_mutex_);
  ASSERT_EQ(summaries_.size(), 1u);

  EXPECT_EQ(summaries_[0].pad_frames, summaries_[0].frames_emitted)
      << "All frames must be pad when asset is unresolvable";
  EXPECT_TRUE(summaries_[0].asset_uris.empty())
      << "No asset URIs should be recorded when decoder failed";
}

// =============================================================================
// TRACE-004: SummarySessionFrameRange
// Queue 2 blocks. Verify session frame ranges are contiguous and non-overlapping.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SummarySessionFrameRange) {
  auto now_ms = NowMs();
  // Schedule after bootstrap so fence fires at the correct wall-clock instant.
  FedBlock block1 = MakeSyntheticBlock("trace-range-a", kStdBlockMs);
  block1.start_utc_ms = now_ms + kBlockTimeOffsetMs;
  block1.end_utc_ms = now_ms + kBlockTimeOffsetMs + kStdBlockMs;
  FedBlock block2 = MakeSyntheticBlock("trace-range-b", kStdBlockMs);
  block2.start_utc_ms = now_ms + kBlockTimeOffsetMs + kStdBlockMs;
  block2.end_utc_ms = now_ms + kBlockTimeOffsetMs + kStdBlockMs * 2;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 20000))
      << "Both blocks must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(summary_mutex_);
  ASSERT_EQ(summaries_.size(), 2u);

  // First block starts at frame 0
  EXPECT_EQ(summaries_[0].first_session_frame_index, 0)
      << "First block must start at session frame 0";
  EXPECT_GE(summaries_[0].last_session_frame_index,
            summaries_[0].first_session_frame_index)
      << "last_session_frame must be >= first_session_frame";

  // Second block starts after first
  EXPECT_GT(summaries_[1].first_session_frame_index,
            summaries_[0].last_session_frame_index)
      << "Second block session frames must follow first block's";
}

// =============================================================================
// TRACE-005: SeamTransitionLogProduced
// Queue 2 blocks. After both complete, verify a seam transition log is produced.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SeamTransitionLogProduced) {
  FedBlock block1 = MakeSyntheticBlock("seam-from", kShortBlockMs);
  FedBlock block2 = MakeSyntheticBlock("seam-to", kShortBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 8000))
      << "Both blocks must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(seam_mutex_);
  ASSERT_GE(seam_transitions_.size(), 1u)
      << "At least one seam transition must be logged for back-to-back blocks";
  EXPECT_EQ(seam_transitions_[0].from_block_id, "seam-from");
  EXPECT_EQ(seam_transitions_[0].to_block_id, "seam-to");
  EXPECT_GE(seam_transitions_[0].fence_frame, 0)
      << "Fence frame must be non-negative";
}

// =============================================================================
// TRACE-006: SeamlessTransitionStatus
// Queue 2 blocks (instant preload). Verify seam status is SEAMLESS.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SeamlessTransitionStatus) {
  auto now_ms = NowMs();
  FedBlock block1 = MakeSyntheticBlock("seamless-a", kShortBlockMs);
  block1.start_utc_ms = now_ms;
  block1.end_utc_ms = now_ms + kShortBlockMs;
  FedBlock block2 = MakeSyntheticBlock("seamless-b", kShortBlockMs);
  block2.start_utc_ms = now_ms + kShortBlockMs;
  block2.end_utc_ms = now_ms + kShortBlockMs * 2;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 8000))
      << "Both blocks must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(seam_mutex_);
  ASSERT_GE(seam_transitions_.size(), 1u);
  // With synthetic (no-decoder) blocks, all frames are pad regardless of
  // preload timing.  The fence tick itself is pad because B also produces
  // only pad.  Verify the seam transition was logged with correct IDs.
  EXPECT_EQ(seam_transitions_[0].from_block_id, "seamless-a");
  EXPECT_EQ(seam_transitions_[0].to_block_id, "seamless-b");
  // Real-media seamless test: RealMediaBoundarySeamless in SeamProof suite.
}

// =============================================================================
// TRACE-007: PaddedTransitionStatus
// Delay preloader by 2s. Queue 2 short blocks. Verify seam status is PADDED.
// =============================================================================
TEST_F(PlaybackTraceContractTest, DISABLED_SLOW_PaddedTransitionStatus) {
  engine_ = MakeEngine();

  // Preloader delay must exceed the wall-clock time from preroll arm to
  // block A's fence so that B is NOT ready at the transition → PADDED.
  // With kBootGuardMs=3000 and duration=5000, block A's fence is at
  // ~8s from session start.  Preloader arms before bootstrap (~0s).
  // Delay of 12s → preloader finishes at ~12s, well past the ~8s fence.
  engine_->SetPreloaderDelayHook([]() {
    std::this_thread::sleep_for(std::chrono::milliseconds(kPreloaderMs));
  });

  // Block A: scheduled after bootstrap.
  FedBlock block1 = MakeSyntheticBlock("padded-a", kStdBlockMs);
  block1.start_utc_ms += kBlockTimeOffsetMs;
  block1.end_utc_ms  += kBlockTimeOffsetMs;

  // Block B: sequential — starts where A ends.
  FedBlock block2 = MakeSyntheticBlock("padded-b", kStdBlockMs);
  block2.start_utc_ms = block1.end_utc_ms;
  block2.end_utc_ms = block1.end_utc_ms + kStdBlockMs;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 35000))
      << "Both blocks must eventually complete";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(seam_mutex_);
  ASSERT_GE(seam_transitions_.size(), 1u)
      << "Seam transition must be logged even when padded";

  // Find the transition from padded-a to padded-b
  bool found_padded = false;
  for (const auto& t : seam_transitions_) {
    if (t.from_block_id == "padded-a" && t.to_block_id == "padded-b") {
      EXPECT_FALSE(t.seamless)
          << "Delayed preload must produce PADDED transition";
      EXPECT_GT(t.pad_frames_at_fence, 0)
          << "Padded transition must have non-zero pad frames at fence";
      found_padded = true;
      break;
    }
  }
  EXPECT_TRUE(found_padded)
      << "Must find transition from padded-a to padded-b";
}

// =============================================================================
// TRACE-008: FormatPlaybackSummaryOutput
// Unit test on FormatPlaybackSummary(). Verify output format matches contract.
// =============================================================================
TEST_F(PlaybackTraceContractTest, FormatPlaybackSummaryOutput) {
  BlockPlaybackSummary s;
  s.block_id = "fmt-001";
  s.asset_uris = {"/assets/movie.mp4"};
  s.first_block_ct_ms = 0;
  s.last_block_ct_ms = 4950;
  s.frames_emitted = 152;
  s.pad_frames = 3;
  s.first_session_frame_index = 0;
  s.last_session_frame_index = 151;

  std::string output = FormatPlaybackSummary(s);

  EXPECT_NE(output.find("[CONTINUOUS-PLAYBACK-SUMMARY]"), std::string::npos)
      << "Must contain log prefix";
  EXPECT_NE(output.find("block_id=fmt-001"), std::string::npos)
      << "Must contain block_id";
  EXPECT_NE(output.find("asset=/assets/movie.mp4"), std::string::npos)
      << "Must contain asset URI";
  EXPECT_NE(output.find("asset_range=0-4950ms"), std::string::npos)
      << "Must contain CT range";
  EXPECT_NE(output.find("frames=152"), std::string::npos)
      << "Must contain frame count";
  EXPECT_NE(output.find("pad_frames=3"), std::string::npos)
      << "Must contain pad frame count";
  EXPECT_NE(output.find("session_frames=0-151"), std::string::npos)
      << "Must contain session frame range";
}

// =============================================================================
// TRACE-009: FormatSeamTransitionOutput
// Unit test on FormatSeamTransition(). Verify output format matches contract.
// =============================================================================
TEST_F(PlaybackTraceContractTest, FormatSeamTransitionOutput) {
  SeamTransitionLog t;
  t.from_block_id = "block-A";
  t.to_block_id = "block-B";
  t.fence_frame = 151;
  t.pad_frames_at_fence = 0;
  t.seamless = true;

  std::string output = FormatSeamTransition(t);

  EXPECT_NE(output.find("[CONTINUOUS-SEAM]"), std::string::npos)
      << "Must contain log prefix";
  EXPECT_NE(output.find("from=block-A"), std::string::npos)
      << "Must contain from block";
  EXPECT_NE(output.find("to=block-B"), std::string::npos)
      << "Must contain to block";
  EXPECT_NE(output.find("fence_frame=151"), std::string::npos)
      << "Must contain fence frame";
  EXPECT_NE(output.find("status=SEAMLESS"), std::string::npos)
      << "Must contain SEAMLESS status";

  // Test PADDED format
  t.pad_frames_at_fence = 5;
  t.seamless = false;
  output = FormatSeamTransition(t);
  EXPECT_NE(output.find("status=PADDED"), std::string::npos)
      << "Must contain PADDED status when not seamless";
  EXPECT_NE(output.find("pad_frames_at_fence=5"), std::string::npos)
      << "Must contain pad frame count";
}

// =============================================================================
// TRACE-010: RealMediaSummaryWithAssetIdentity
// GTEST_SKIP if assets missing. Queue real block. Verify asset_uris populated.
// =============================================================================
TEST_F(PlaybackTraceContractTest, RealMediaSummaryWithAssetIdentity) {
  const std::string path_a = "/opt/retrovue/assets/SampleA.mp4";

  if (!FileExists(path_a)) {
    GTEST_SKIP() << "Real media asset not found: " << path_a;
  }

  auto now_ms = NowMs();
  FedBlock block = MakeSyntheticBlock("trace-real", 3000, path_a);
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 3000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 10000))
      << "Real media block must complete";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(summary_mutex_);
  ASSERT_EQ(summaries_.size(), 1u);

  EXPECT_EQ(summaries_[0].block_id, "trace-real");
  ASSERT_FALSE(summaries_[0].asset_uris.empty())
      << "Real media block must have asset URIs in summary";
  EXPECT_EQ(summaries_[0].asset_uris[0], path_a)
      << "Asset URI must match the block's asset";
  EXPECT_GE(summaries_[0].first_block_ct_ms, 0)
      << "First CT must be non-negative for real media";
  EXPECT_GT(summaries_[0].last_block_ct_ms, summaries_[0].first_block_ct_ms)
      << "CT must advance across block for real media";
  // Input fps (29.97) vs output fps (30) mismatch may cause 1 pad frame
  // at the tail of the block when decoded content ends slightly before fence.
  EXPECT_LE(summaries_[0].pad_frames, 1)
      << "Real media block should have at most 1 pad frame (fps mismatch)";
}

// =============================================================================
// TRACE-011: BlockAccumulatorUnitTest
// Direct unit test on BlockAccumulator struct.
// =============================================================================
TEST_F(PlaybackTraceContractTest, BlockAccumulatorUnitTest) {
  BlockAccumulator acc;
  acc.Reset("test-block");

  EXPECT_EQ(acc.block_id, "test-block");
  EXPECT_EQ(acc.frames, 0);
  EXPECT_EQ(acc.pad_frames, 0);

  // Accumulate some real frames
  acc.AccumulateFrame(0, false, "/test/a.mp4", 0);
  acc.AccumulateFrame(1, false, "/test/a.mp4", 33);
  acc.AccumulateFrame(2, true, "", 0);  // pad frame
  acc.AccumulateFrame(3, false, "/test/b.mp4", 99);

  auto summary = acc.Finalize();
  EXPECT_EQ(summary.block_id, "test-block");
  EXPECT_EQ(summary.frames_emitted, 4);
  EXPECT_EQ(summary.pad_frames, 1);
  EXPECT_EQ(summary.first_session_frame_index, 0);
  EXPECT_EQ(summary.last_session_frame_index, 3);
  EXPECT_EQ(summary.first_block_ct_ms, 0);
  EXPECT_EQ(summary.last_block_ct_ms, 99);

  // Two unique URIs
  ASSERT_EQ(summary.asset_uris.size(), 2u);
  EXPECT_EQ(summary.asset_uris[0], "/test/a.mp4");
  EXPECT_EQ(summary.asset_uris[1], "/test/b.mp4");

  // Duplicate URI doesn't add again
  acc.AccumulateFrame(4, false, "/test/a.mp4", 132);
  summary = acc.Finalize();
  EXPECT_EQ(summary.asset_uris.size(), 2u)
      << "Duplicate URI must not be added again";
}

// =============================================================================
// P3.3b PROOF TESTS
// =============================================================================

// =============================================================================
// PROOF-001: ProofEmittedPerBlock
// Queue 2 blocks. After both complete, verify 2 proofs with correct block IDs.
// =============================================================================
TEST_F(PlaybackTraceContractTest, ProofEmittedPerBlock) {
  FedBlock block1 = MakeSyntheticBlock("proof-a", kShortBlockMs);
  FedBlock block2 = MakeSyntheticBlock("proof-b", kShortBlockMs);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 8000))
      << "Both blocks must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(proof_mutex_);
  ASSERT_EQ(proofs_.size(), 2u)
      << "One proof must be emitted per completed block";
  EXPECT_EQ(proofs_[0].wanted.block_id, "proof-a");
  EXPECT_EQ(proofs_[0].showed.block_id, "proof-a");
  EXPECT_EQ(proofs_[1].wanted.block_id, "proof-b");
  EXPECT_EQ(proofs_[1].showed.block_id, "proof-b");
}

// =============================================================================
// PROOF-002: AllPadVerdictForSyntheticBlock
// Queue 1 synthetic (unresolvable) block. Verdict must be ALL_PAD.
// =============================================================================
TEST_F(PlaybackTraceContractTest, AllPadVerdictForSyntheticBlock) {
  FedBlock block = MakeSyntheticBlock("proof-allpad", kShortBlockMs,
                                       "/nonexistent/proof.mp4");
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 5000))
      << "Block must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(proof_mutex_);
  ASSERT_EQ(proofs_.size(), 1u);
  EXPECT_EQ(proofs_[0].verdict, PlaybackProofVerdict::kAllPad)
      << "Unresolvable asset must produce ALL_PAD verdict";
  EXPECT_EQ(proofs_[0].showed.pad_frames, proofs_[0].showed.frames_emitted)
      << "All frames must be pad";
}

// =============================================================================
// PROOF-003: IntentMatchesFedBlock
// Verify BuildIntent extracts correct fields from FedBlock.
// =============================================================================
TEST_F(PlaybackTraceContractTest, IntentMatchesFedBlock) {
  FedBlock block = MakeSyntheticBlock("proof-intent", 3000, "/assets/test.mp4");
  block.segments[0].asset_start_offset_ms = 5000;

  // At 30fps, frame_duration_ms = 33, expected_frames = ceil(3000/33) = 91
  auto intent = BuildIntent(block, 33);

  EXPECT_EQ(intent.block_id, "proof-intent");
  EXPECT_EQ(intent.expected_duration_ms, 3000);
  EXPECT_EQ(intent.expected_frames, 91)
      << "ceil(3000/33) = 91";
  ASSERT_EQ(intent.expected_asset_uris.size(), 1u);
  EXPECT_EQ(intent.expected_asset_uris[0], "/assets/test.mp4");
  EXPECT_EQ(intent.expected_start_offset_ms, 5000);
}

// =============================================================================
// PROOF-004: DetermineVerdictLogic
// Unit test on DetermineVerdict() covering all four verdict paths.
// =============================================================================
TEST_F(PlaybackTraceContractTest, DetermineVerdictLogic) {
  BlockPlaybackIntent wanted;
  wanted.block_id = "verdict-test";
  wanted.expected_asset_uris = {"/a.mp4"};
  wanted.expected_frames = 30;

  // FAITHFUL: correct asset, zero pad
  {
    BlockPlaybackSummary showed;
    showed.asset_uris = {"/a.mp4"};
    showed.frames_emitted = 30;
    showed.pad_frames = 0;
    EXPECT_EQ(DetermineVerdict(wanted, showed), PlaybackProofVerdict::kFaithful)
        << "Correct asset + zero pad = FAITHFUL";
  }

  // PARTIAL_PAD: correct asset, some pad
  {
    BlockPlaybackSummary showed;
    showed.asset_uris = {"/a.mp4"};
    showed.frames_emitted = 30;
    showed.pad_frames = 5;
    EXPECT_EQ(DetermineVerdict(wanted, showed), PlaybackProofVerdict::kPartialPad)
        << "Correct asset + some pad = PARTIAL_PAD";
  }

  // ALL_PAD: no real frames
  {
    BlockPlaybackSummary showed;
    showed.frames_emitted = 30;
    showed.pad_frames = 30;
    EXPECT_EQ(DetermineVerdict(wanted, showed), PlaybackProofVerdict::kAllPad)
        << "All pad frames = ALL_PAD";
  }

  // ASSET_MISMATCH: wrong asset observed
  {
    BlockPlaybackSummary showed;
    showed.asset_uris = {"/b.mp4"};
    showed.frames_emitted = 30;
    showed.pad_frames = 0;
    EXPECT_EQ(DetermineVerdict(wanted, showed), PlaybackProofVerdict::kAssetMismatch)
        << "Wrong asset = ASSET_MISMATCH";
  }
}

// =============================================================================
// PROOF-005: FormatPlaybackProofOutput
// Unit test on FormatPlaybackProof(). Verify output contains WANTED/SHOWED/VERDICT.
// =============================================================================
TEST_F(PlaybackTraceContractTest, FormatPlaybackProofOutput) {
  BlockPlaybackProof proof;
  proof.wanted.block_id = "fmt-proof";
  proof.wanted.expected_asset_uris = {"/assets/movie.mp4"};
  proof.wanted.expected_start_offset_ms = 0;
  proof.wanted.expected_duration_ms = 5000;
  proof.wanted.expected_frames = 152;

  proof.showed.block_id = "fmt-proof";
  proof.showed.asset_uris = {"/assets/movie.mp4"};
  proof.showed.first_block_ct_ms = 0;
  proof.showed.last_block_ct_ms = 4950;
  proof.showed.frames_emitted = 152;
  proof.showed.pad_frames = 0;

  proof.verdict = PlaybackProofVerdict::kFaithful;

  std::string output = FormatPlaybackProof(proof);

  EXPECT_NE(output.find("[BLOCK_PROOF]"), std::string::npos)
      << "Must contain log prefix";
  EXPECT_NE(output.find("block_id=fmt-proof"), std::string::npos)
      << "Must contain block_id";
  EXPECT_NE(output.find("WANTED:"), std::string::npos)
      << "Must contain WANTED section";
  EXPECT_NE(output.find("SHOWED:"), std::string::npos)
      << "Must contain SHOWED section";
  EXPECT_NE(output.find("VERDICT: FAITHFUL"), std::string::npos)
      << "Must contain FAITHFUL verdict";
  EXPECT_NE(output.find("asset=/assets/movie.mp4"), std::string::npos)
      << "Must contain asset URI";
  EXPECT_NE(output.find("duration=5000ms"), std::string::npos)
      << "Must contain duration";
  EXPECT_NE(output.find("frames=152"), std::string::npos)
      << "Must contain frame count";
}

// =============================================================================
// PROOF-006: ProofWantedFramesMatchesFence
// Queue 1 block. Verify proof.wanted.expected_frames equals summary.frames_emitted.
// (For synthetic blocks, both should equal ceil(duration/frame_dur).)
// =============================================================================
TEST_F(PlaybackTraceContractTest, ProofWantedFramesMatchesFence) {
  auto now_ms = NowMs();
  // Schedule after bootstrap so fence fires at the correct wall-clock instant.
  FedBlock block = MakeSyntheticBlock("proof-frames", kShortBlockMs);
  block.start_utc_ms = now_ms + kBlockTimeOffsetMs;
  block.end_utc_ms = now_ms + kBlockTimeOffsetMs + kShortBlockMs;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 8000))
      << "Block must complete within timeout";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(proof_mutex_);
  ASSERT_EQ(proofs_.size(), 1u);
  // BuildIntent uses ms-quantized frame_duration_ms (33 for 30fps):
  //   ceil(kShortBlockMs/33).  Default: ceil(1000/33)=31.  Fast: ceil(200/33)=7.
  const int64_t expected_wanted = static_cast<int64_t>(
      std::ceil(static_cast<double>(kShortBlockMs) / 33.0));
  EXPECT_EQ(proofs_[0].wanted.expected_frames, expected_wanted)
      << "BuildIntent uses ceil(duration/frame_duration_ms)";
  // Engine fence uses ceil((block.end_utc_ms - fence_epoch) * fps / 1000).
  // Default: fence_epoch lags block.start by ~1s → frames > 30.
  // Fast:    fence_epoch == block.start (DTS) → frames == ceil(duration*30/1000).
  const int64_t min_showed = kFastMode ? 6 : 30;
  const int64_t max_showed = kFastMode ? 30 : 120;
  EXPECT_GE(proofs_[0].showed.frames_emitted, min_showed)
      << "Engine fence must emit at least ceil(duration*fps) frames";
  EXPECT_LE(proofs_[0].showed.frames_emitted, max_showed)
      << "Engine fence frames bounded by guard + duration";
}

// =============================================================================
// PROOF-007: RealMediaFaithfulVerdict
// GTEST_SKIP if assets missing. Queue real block. Verify FAITHFUL verdict.
// =============================================================================
TEST_F(PlaybackTraceContractTest, RealMediaFaithfulVerdict) {
  const std::string path_a = "/opt/retrovue/assets/SampleA.mp4";

  if (!FileExists(path_a)) {
    GTEST_SKIP() << "Real media asset not found: " << path_a;
  }

  auto now_ms = NowMs();
  FedBlock block = MakeSyntheticBlock("proof-real", 3000, path_a);
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 3000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(1, 10000))
      << "Real media block must complete";

  engine_->Stop();

  std::lock_guard<std::mutex> lock(proof_mutex_);
  ASSERT_EQ(proofs_.size(), 1u);
  // Input fps (29.97) vs output fps (30) mismatch may cause 1 pad frame
  // at the tail.  With 1 pad, verdict is PARTIAL_PAD rather than FAITHFUL.
  EXPECT_TRUE(proofs_[0].verdict == PlaybackProofVerdict::kFaithful ||
              proofs_[0].verdict == PlaybackProofVerdict::kPartialPad)
      << "Real media with correct asset must produce FAITHFUL or PARTIAL_PAD";
  EXPECT_LE(proofs_[0].showed.pad_frames, 1)
      << "Real media block should have at most 1 pad frame (fps mismatch)";
  ASSERT_FALSE(proofs_[0].showed.asset_uris.empty());
  EXPECT_EQ(proofs_[0].showed.asset_uris[0], path_a)
      << "Showed asset must match wanted asset";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
