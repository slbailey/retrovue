// Repository: Retrovue-playout
// Component: Seam Proof Contract Tests
// Purpose: Verify P3.2 seam verification infrastructure — fingerprinting,
//          boundary reports, and zero-pad-gap proof at block transitions.
// Contract Reference: PlayoutAuthorityContract.md (P3.2)
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
#include <thread>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/blockplan/ProducerPreloader.hpp"

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

class SeamProofContractTest : public ::testing::Test {
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
      session_ended_cv_.notify_all();
    };
    callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.push_back(fp);
    };
    return std::make_unique<PipelineManager>(
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

  bool WaitForSessionEnded(int timeout_ms = 2000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return session_ended_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this] { return session_ended_count_ > 0; });
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::condition_variable session_ended_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<int64_t> fence_frame_indices_;
  int session_ended_count_ = 0;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// SEAM-PROOF-001: PreloadSuccessZeroFencePad
// Queue 2 synthetic 1000ms blocks. Preload completes instantly (synthetic URI
// fails probe fast). After both complete: fence_pad_frames_total == 0,
// source_swap_count >= 1.
// =============================================================================
TEST_F(SeamProofContractTest, PreloadSuccessZeroFencePad) {
  FedBlock block1 = MakeSyntheticBlock("sp001-a", 1000);
  FedBlock block2 = MakeSyntheticBlock("sp001-b", 1000);
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

  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.fence_pad_frames_total, 0)
      << "Fence pad must be zero when preload succeeds instantly";
  EXPECT_GE(m.source_swap_count, 1)
      << "Source swap must happen for back-to-back blocks";
}

// =============================================================================
// SEAM-PROOF-002: PreloadDelayerCausesFencePad
// SetPreloaderDelayHook(2s sleep). Queue 2 synthetic 500ms blocks. After both:
// fence_pad_frames_total > 0. Proves pad-at-fence detection works.
// =============================================================================
TEST_F(SeamProofContractTest, PreloadDelayerCausesFencePad) {
  engine_ = MakeEngine();

  engine_->SetPreloaderDelayHook([]() {
    std::this_thread::sleep_for(std::chrono::milliseconds(2000));
  });

  FedBlock block1 = MakeSyntheticBlock("sp002-a", 500);
  FedBlock block2 = MakeSyntheticBlock("sp002-b", 500);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_->Start();

  // Block 1 is ~500ms. Preloader has 2s delay. Second block will be delayed.
  // Wait for both to complete (the delay means pad frames at fence).
  ASSERT_TRUE(WaitForBlocksCompleted(2, 15000))
      << "Both blocks must eventually complete";

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  EXPECT_GT(m.fence_pad_frames_total, 0)
      << "Fence pad must be non-zero when preload is delayed beyond fence";
}

// =============================================================================
// SEAM-PROOF-003: FingerprintCallbackFiresEveryFrame
// Run 150ms pad-only with on_frame_emitted. Assert:
// fps.size() == metrics.continuous_frames_emitted_total; all is_pad; all y_crc32 == 0.
// =============================================================================
TEST_F(SeamProofContractTest, FingerprintCallbackFiresEveryFrame) {
  engine_ = MakeEngine();
  engine_->Start();

  // Run pad-only for ~150ms
  std::this_thread::sleep_for(std::chrono::milliseconds(150));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  std::lock_guard<std::mutex> lock(fp_mutex_);

  EXPECT_EQ(static_cast<int64_t>(fingerprints_.size()),
            m.continuous_frames_emitted_total)
      << "on_frame_emitted must fire for every frame emitted";

  for (const auto& fp : fingerprints_) {
    EXPECT_TRUE(fp.is_pad) << "All frames must be pad in zero-block mode";
    EXPECT_EQ(fp.y_crc32, 0u) << "Pad frames have no Y data, CRC must be 0";
  }
}

// =============================================================================
// SEAM-PROOF-004: FrameDataCarriesMetadata
// Producer unit test. AssignBlock with synthetic. TryGetFrame returns
// nullopt (no decoder). Compile-time proof that FrameData has new fields.
// Verify FramesPerBlock matches ceil formula.
// =============================================================================
TEST_F(SeamProofContractTest, FrameDataCarriesMetadata) {
  TickProducer source(640, 480, 30.0);

  // AssignBlock with synthetic (probe fails, no decoder)
  FedBlock block = MakeSyntheticBlock("sp004", 5000);
  source.AssignBlock(block);
  EXPECT_EQ(source.GetState(), TickProducer::State::kReady);
  EXPECT_FALSE(source.HasDecoder());

  // FramesPerBlock = ceil(5000 / 33) = 152
  int64_t expected_fpb = static_cast<int64_t>(
      std::ceil(5000.0 / 33.0));
  EXPECT_EQ(source.FramesPerBlock(), expected_fpb)
      << "FramesPerBlock must match ceil formula";

  // TryGetFrame returns nullopt (no decoder), but FrameData has new fields
  auto frame = source.TryGetFrame();
  EXPECT_FALSE(frame.has_value())
      << "TryGetFrame must return nullopt when decoder is not ok";

  // Compile-time proof: FrameData has asset_uri and block_ct_ms fields
  FrameData fd;
  fd.asset_uri = "test";
  fd.block_ct_ms = 42;
  EXPECT_EQ(fd.asset_uri, "test");
  EXPECT_EQ(fd.block_ct_ms, 42);

  source.Reset();
}

// =============================================================================
// SEAM-PROOF-005: RealMediaBoundarySeamless
// GTEST_SKIP if sample assets missing. Queue block A + block B with real media.
// Collect fingerprints. Build boundary report. Assert: pad_frames_in_window == 0,
// first frame of B has correct asset_uri and block_ct_ms == 0.
// =============================================================================
TEST_F(SeamProofContractTest, RealMediaBoundarySeamless) {
  const std::string path_a = "/opt/retrovue/assets/SampleA.mp4";
  const std::string path_b = "/opt/retrovue/assets/SampleB.mp4";

  if (!FileExists(path_a) || !FileExists(path_b)) {
    GTEST_SKIP() << "Real media assets not found: " << path_a << ", " << path_b
                 << ". Place SampleA.mp4 and SampleB.mp4 in /opt/retrovue/assets/";
  }

  FedBlock block_a = MakeSyntheticBlock("sp005-a", 5000, path_a);
  FedBlock block_b = MakeSyntheticBlock("sp005-b", 5000, path_b);
  block_b.segments[0].asset_start_offset_ms = 12000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  ASSERT_TRUE(WaitForBlocksCompleted(2, 20000))
      << "Both real-media blocks must complete";

  engine_->Stop();

  // Build boundary report using fence frame index from first block completion
  std::vector<FrameFingerprint> fps;
  {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    fps = fingerprints_;
  }

  int64_t fence_idx;
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(fence_frame_indices_.size(), 1u);
    // fence_frame_index is the session_frame_index at block A completion.
    // The next frame (fence_idx + 1) is the first of block B.
    fence_idx = fence_frame_indices_[0] + 1;
  }

  auto report = BuildBoundaryReport(fps, fence_idx, "sp005-a", "sp005-b");
  PrintBoundaryReport(std::cout, report);

  EXPECT_EQ(report.pad_frames_in_window, 0)
      << "Real media boundary must have zero pad frames in window";

  // Verify first frame of block B has correct asset_uri
  ASSERT_FALSE(report.head_b.empty()) << "Head B must have frames";
  EXPECT_EQ(report.head_b[0].asset_uri, path_b)
      << "First frame of block B must reference SampleB asset";
  EXPECT_EQ(report.head_b[0].asset_offset_ms, 0)
      << "First frame of block B must have block_ct_ms == 0 (start of block)";
}

// =============================================================================
// SEAM-PROOF-006: BoundaryReportGeneration
// Unit test on BuildBoundaryReport(). Feed 20 fps with block "A", then 20 with
// block "B", fence at index 20. Verify: tail_a.size() == 5, head_b.size() == 5,
// correct block IDs.
// =============================================================================
TEST_F(SeamProofContractTest, BoundaryReportGeneration) {
  std::vector<FrameFingerprint> all_fps;

  // 20 frames from block A
  for (int i = 0; i < 20; i++) {
    FrameFingerprint fp;
    fp.session_frame_index = i;
    fp.is_pad = false;
    fp.active_block_id = "A";
    fp.asset_uri = "/test/a.mp4";
    fp.asset_offset_ms = i * 33;
    fp.y_crc32 = static_cast<uint32_t>(i + 100);
    all_fps.push_back(fp);
  }

  // 20 frames from block B
  for (int i = 0; i < 20; i++) {
    FrameFingerprint fp;
    fp.session_frame_index = 20 + i;
    fp.is_pad = false;
    fp.active_block_id = "B";
    fp.asset_uri = "/test/b.mp4";
    fp.asset_offset_ms = i * 33;
    fp.y_crc32 = static_cast<uint32_t>(i + 200);
    all_fps.push_back(fp);
  }

  auto report = BuildBoundaryReport(all_fps, 20, "A", "B");

  EXPECT_EQ(report.block_a_id, "A");
  EXPECT_EQ(report.block_b_id, "B");
  EXPECT_EQ(report.fence_frame_index, 20);

  EXPECT_EQ(static_cast<int>(report.tail_a.size()), BoundaryReport::kWindow)
      << "Tail A must have kWindow frames";
  EXPECT_EQ(static_cast<int>(report.head_b.size()), BoundaryReport::kWindow)
      << "Head B must have kWindow frames";

  // Verify tail_a contains frames 15-19 (block A)
  for (int i = 0; i < BoundaryReport::kWindow; i++) {
    EXPECT_EQ(report.tail_a[i].session_frame_index, 15 + i);
    EXPECT_EQ(report.tail_a[i].active_block_id, "A");
  }

  // Verify head_b contains frames 20-24 (block B)
  for (int i = 0; i < BoundaryReport::kWindow; i++) {
    EXPECT_EQ(report.head_b[i].session_frame_index, 20 + i);
    EXPECT_EQ(report.head_b[i].active_block_id, "B");
  }

  // No pad frames in these synthetic fingerprints
  EXPECT_EQ(report.pad_frames_in_window, 0);

  // Print for visual inspection
  PrintBoundaryReport(std::cout, report);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
