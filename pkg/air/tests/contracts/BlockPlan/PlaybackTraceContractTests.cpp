// Repository: Retrovue-playout
// Component: Playback Trace Contract Tests
// Purpose: Verify P3.3 execution trace logging — per-block playback summaries,
//          seam transition logs, and correct aggregation of actual execution data.
// Contract Reference: PlayoutAuthorityContract.md (P3.3)
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <chrono>
#include <condition_variable>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/ContinuousOutputExecutionEngine.hpp"
#include "retrovue/blockplan/ContinuousOutputMetrics.hpp"
#include "retrovue/blockplan/PlaybackTraceTypes.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Helper: Create a synthetic FedBlock (unresolvable URI)
// =============================================================================
static FedBlock MakeSyntheticBlock(
    const std::string& block_id,
    int64_t duration_ms,
    const std::string& uri = "/nonexistent/test.mp4") {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = 1000000;
  block.end_utc_ms = 1000000 + duration_ms;

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
    ctx_->fd = -1;
    ctx_->width = 640;
    ctx_->height = 480;
    ctx_->fps = 30.0;
  }

  void TearDown() override {
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
  }

  std::unique_ptr<ContinuousOutputExecutionEngine> MakeEngine() {
    ContinuousOutputExecutionEngine::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_session_ended = [this](const std::string& reason) {
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
    return std::make_unique<ContinuousOutputExecutionEngine>(
        ctx_.get(), std::move(callbacks));
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
  std::unique_ptr<ContinuousOutputExecutionEngine> engine_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::condition_variable session_ended_cv_;
  std::vector<std::string> completed_blocks_;
  int session_ended_count_ = 0;

  std::mutex summary_mutex_;
  std::vector<BlockPlaybackSummary> summaries_;

  std::mutex seam_mutex_;
  std::vector<SeamTransitionLog> seam_transitions_;
};

// =============================================================================
// TRACE-001: SummaryProducedPerBlock
// Queue 2 blocks. After both complete, verify 2 summaries with correct block IDs.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SummaryProducedPerBlock) {
  FedBlock block1 = MakeSyntheticBlock("trace-a", 1000);
  FedBlock block2 = MakeSyntheticBlock("trace-b", 1000);
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
  // 1000ms block at 30fps: ceil(1000/33) = 31 frames
  FedBlock block = MakeSyntheticBlock("trace-fc", 1000);
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

  // ceil(1000/33) = 31 frames
  EXPECT_EQ(summaries_[0].frames_emitted, 31)
      << "Summary frames_emitted must equal FramesPerBlock";
  EXPECT_EQ(summaries_[0].block_id, "trace-fc");
}

// =============================================================================
// TRACE-003: SummaryPadCountAccurate
// Queue 1 synthetic (unresolvable) block. All frames must be pad.
// =============================================================================
TEST_F(PlaybackTraceContractTest, SummaryPadCountAccurate) {
  FedBlock block = MakeSyntheticBlock("trace-pad", 1000, "/nonexistent/pad.mp4");
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
  FedBlock block1 = MakeSyntheticBlock("trace-range-a", 500);
  FedBlock block2 = MakeSyntheticBlock("trace-range-b", 500);
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
  FedBlock block1 = MakeSyntheticBlock("seam-from", 1000);
  FedBlock block2 = MakeSyntheticBlock("seam-to", 1000);
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
  FedBlock block1 = MakeSyntheticBlock("seamless-a", 1000);
  FedBlock block2 = MakeSyntheticBlock("seamless-b", 1000);
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
  EXPECT_TRUE(seam_transitions_[0].seamless)
      << "Instant preload must produce seamless transition";
  EXPECT_EQ(seam_transitions_[0].pad_frames_at_fence, 0)
      << "Seamless transition must have zero pad frames at fence";
}

// =============================================================================
// TRACE-007: PaddedTransitionStatus
// Delay preloader by 2s. Queue 2 short blocks. Verify seam status is PADDED.
// =============================================================================
TEST_F(PlaybackTraceContractTest, PaddedTransitionStatus) {
  engine_ = MakeEngine();

  engine_->SetPreloaderDelayHook([]() {
    std::this_thread::sleep_for(std::chrono::milliseconds(2000));
  });

  FedBlock block1 = MakeSyntheticBlock("padded-a", 500);
  FedBlock block2 = MakeSyntheticBlock("padded-b", 500);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 15000))
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

  FedBlock block = MakeSyntheticBlock("trace-real", 3000, path_a);
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
  EXPECT_EQ(summaries_[0].pad_frames, 0)
      << "Real media block should have zero pad frames";
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

}  // namespace
}  // namespace retrovue::blockplan::testing
