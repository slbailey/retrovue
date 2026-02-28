// Repository: Retrovue-playout
// Component: INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 Contract Test (PAD→CONTENT)
// Purpose: Prove that a PAD→CONTENT transition via FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY
//          does not emit a frame with stale PAD origin after authority transfers to CONTENT.
// Contract: docs/contracts/invariants/air/INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
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
#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/util/Logger.hpp"
#include "deterministic_tick_driver.hpp"
#include "FastTestConfig.hpp"

using retrovue::util::Logger;

namespace retrovue::blockplan::testing {
namespace {

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

// Build a [CONTENT, PAD, CONTENT] block.  The PAD segment sits between two
// content segments so the tick loop must execute both CONTENT→PAD and
// PAD→CONTENT transitions within a single block.
static FedBlock MakeContentPadContentBlock(const std::string& block_id,
                                           int64_t start_utc_ms,
                                           int64_t seg0_content_ms,
                                           int64_t seg1_pad_ms,
                                           int64_t seg2_content_ms) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + seg0_content_ms + seg1_pad_ms + seg2_content_ms;

  FedBlock::Segment s0;
  s0.segment_index = 0;
  s0.asset_uri = kPathA;
  s0.asset_start_offset_ms = 0;
  s0.segment_duration_ms = seg0_content_ms;
  s0.segment_type = SegmentType::kContent;
  block.segments.push_back(s0);

  FedBlock::Segment s1;
  s1.segment_index = 1;
  s1.asset_uri = "";
  s1.asset_start_offset_ms = 0;
  s1.segment_duration_ms = seg1_pad_ms;
  s1.segment_type = SegmentType::kPad;
  block.segments.push_back(s1);

  FedBlock::Segment s2;
  s2.segment_index = 2;
  s2.asset_uri = kPathB;
  s2.asset_start_offset_ms = 0;
  s2.segment_duration_ms = seg2_content_ms;
  s2.segment_type = SegmentType::kContent;
  block.segments.push_back(s2);

  return block;
}

class ForceExecutePadToContentBleedTest : public ::testing::Test {
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

    // Capture error log lines for violation detection.
    captured_errors_.clear();
    Logger::SetErrorSink([this](const std::string& line) {
      std::lock_guard<std::mutex> lock(err_mutex_);
      captured_errors_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetErrorSink(nullptr);
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
    callbacks.on_block_completed = [](const FedBlock&, int64_t, int64_t) {};
    callbacks.on_session_ended = [](const std::string&, int64_t) {};
    callbacks.on_segment_start = [this](int32_t, int32_t to_seg,
                                        const FedBlock& block, int64_t tick) {
      std::lock_guard<std::mutex> lock(seg_mutex_);
      segment_start_ticks_.push_back({to_seg, tick});
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0});
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  // Check captured error lines for authority violation.
  bool HasAtomicAuthorityViolation() const {
    std::lock_guard<std::mutex> lock(err_mutex_);
    for (const auto& line : captured_errors_) {
      if (line.find("INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED") != std::string::npos &&
          line.find("reason=stale_frame_bleed") != std::string::npos) {
        return true;
      }
    }
    return false;
  }

  // Return all stale_frame_bleed violation lines for diagnostics.
  std::vector<std::string> GetStaleFrameBleedViolations() const {
    std::lock_guard<std::mutex> lock(err_mutex_);
    std::vector<std::string> violations;
    for (const auto& line : captured_errors_) {
      if (line.find("INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED") != std::string::npos &&
          line.find("reason=stale_frame_bleed") != std::string::npos) {
        violations.push_back(line);
      }
    }
    return violations;
  }

  // Wait until segment 2 (second CONTENT) has started or max frames reached.
  bool WaitForSegment2Start(int64_t max_frames) {
    for (int i = 0; i < 600; i++) {
      {
        std::lock_guard<std::mutex> lock(seg_mutex_);
        for (const auto& [seg, tick] : segment_start_ticks_) {
          if (seg == 2) return true;
        }
      }
      int64_t cur = engine_->SnapshotMetrics().continuous_frames_emitted_total;
      if (cur >= max_frames) return false;
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    return false;
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  mutable std::mutex err_mutex_;
  std::vector<std::string> captured_errors_;

  mutable std::mutex seg_mutex_;
  std::vector<std::pair<int32_t, int64_t>> segment_start_ticks_;
};

// ===========================================================================
// INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001: PAD→CONTENT force-execute bleed
//
// Block: [CONTENT(1500ms), PAD(500ms), CONTENT(1500ms)]
//
// At the PAD→CONTENT boundary, the active segment (PAD) has 0 buffered video
// frames (PAD_B_VIDEO_BUFFER first_frame_fail — PAD has no decoder).  The
// frame cascade selects kHold with frame_origin_segment_id = PAD segment.
// FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY fires (active_video_depth=0,
// successor has frames), PerformSegmentSwap advances current_segment_index_
// to CONTENT.  The post-swap authority check finds origin=PAD ≠ active=CONTENT
// → INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001-VIOLATED reason=stale_frame_bleed.
//
// This test asserts NO stale_frame_bleed violations occur.
// Before fix: FAILS (violations fire at PAD→CONTENT boundary).
// After fix:  PASSES (origin re-stamped after force-execute swap).
// ===========================================================================

TEST_F(ForceExecutePadToContentBleedTest, PadToContentSeamMustNotEmitStaleFrame) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 1500;   // CONTENT
  const int64_t seg1_ms = 500;    // PAD
  const int64_t seg2_ms = 1500;   // CONTENT
  int64_t now = NowMs();

  FedBlock block = MakeContentPadContentBlock(
      "cpc-authority", now, seg0_ms, seg1_ms, seg2_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait until segment 2 (second CONTENT) has started — this means the
  // PAD→CONTENT transition has completed.  Total block ≈ 3500ms ≈ 105 frames
  // at 30fps.  Allow generous ceiling.
  const int64_t kMaxFrames = 200;
  bool seg2_started = WaitForSegment2Start(kMaxFrames);

  // Advance a few more frames past segment 2 start to capture any lagging violations.
  if (seg2_started) {
    int64_t cur = engine_->SnapshotMetrics().continuous_frames_emitted_total;
    test_utils::AdvanceUntilFence(engine_.get(), cur + 30);
  }

  engine_->Stop();

  // ASSERTION: No stale_frame_bleed violations.
  auto violations = GetStaleFrameBleedViolations();
  EXPECT_TRUE(violations.empty())
      << "INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 violated at PAD→CONTENT seam.\n"
      << "FORCE_EXECUTE_DUE_TO_FRAME_AUTHORITY must re-stamp frame_origin_segment_id "
      << "after swap so origin(T) = active(T).\n"
      << "Violation count: " << violations.size() << "\n"
      << "First violation: " << (violations.empty() ? "(none)" : violations[0]);
}

}  // namespace
}  // namespace retrovue::blockplan::testing
