// Repository: Retrovue-playout
// Component: INV-CADENCE-SOURCE-SYNC-002 Contract Test
// Purpose: Prove that the frame selection cadence is reinitialized after a
//          seamless B→A block fence rotation.
//
//          TRIGGER: Block A ends with a 60fps segment.  Cadence is ACTIVE
//          (60→30 mode: always advance, never repeat).  Seamless fence
//          rotation moves preview_ → live_ for block B (30fps asset).
//          Cadence MUST be reinitialized: 30fps source == 30fps output →
//          DISABLED.
//
//          BUG (before fix): The seamless B→A rotation path in
//          PipelineManager::Run() does not call
//          InitFrameSelectionCadenceForLiveBlock().  The fallback and
//          padded-gap-exit paths do, but the normal seamless path skips it.
//          Result: cadence stays in 60→30 ACTIVE mode.  On 24fps content
//          this causes 1.25× playback speed.
//
// Contract: docs/contracts/semantics/CadenceSourceSyncContract.md
//           Rule INV-CADENCE-SOURCE-SYNC-002
// Copyright (c) 2026 RetroVue

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
#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/util/Logger.hpp"
#include "deterministic_tick_driver.hpp"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"

using retrovue::util::Logger;

namespace retrovue::blockplan::testing {
namespace {

static const std::string kPath60fps = "/opt/retrovue/assets/Sample60fps.mp4";
static const std::string kPath30fps = "/opt/retrovue/assets/SampleA.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

static FedBlock MakeSingleSegmentBlock(const std::string& block_id,
                                       int64_t start_utc_ms,
                                       int64_t duration_ms,
                                       const std::string& uri) {
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
  seg.segment_type = SegmentType::kContent;
  block.segments.push_back(seg);

  return block;
}

// =========================================================================
// Fixture: two-block seamless fence transition with log capture.
// =========================================================================
class CadenceSourceSyncTest : public ::testing::Test {
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

    captured_logs_.clear();
    Logger::SetInfoSink([this](const std::string& line) {
      std::lock_guard<std::mutex> lock(log_mutex_);
      captured_logs_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetInfoSink(nullptr);
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
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
      blocks_completed_cv_.notify_all();
    };
    callbacks.on_block_started = [this](const FedBlock& block,
                                        const BlockActivationContext& actx) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      started_blocks_.push_back(block.block_id);
      blocks_started_cv_.notify_all();
    };
    callbacks.on_session_ended = [](const std::string&, int64_t) {};
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0},
        std::make_shared<test_infra::TestProducerFactory>());
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  bool WaitForBlockStarted(const std::string& block_id, int timeout_ms) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return blocks_started_cv_.wait_for(lock,
        std::chrono::milliseconds(timeout_ms), [&] {
          for (const auto& id : started_blocks_) {
            if (id == block_id) return true;
          }
          return false;
        });
  }

  bool WaitForBlockCompleted(const std::string& block_id, int timeout_ms) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return blocks_completed_cv_.wait_for(lock,
        std::chrono::milliseconds(timeout_ms), [&] {
          for (const auto& id : completed_blocks_) {
            if (id == block_id) return true;
          }
          return false;
        });
  }

  // Search captured logs for a log line containing `needle` that appears
  // AFTER the first line containing `after_needle`.
  bool HasLogLineAfter(const std::string& after_needle,
                       const std::string& needle) const {
    std::lock_guard<std::mutex> lock(log_mutex_);
    bool seen_after = false;
    for (const auto& line : captured_logs_) {
      if (!seen_after && line.find(after_needle) != std::string::npos) {
        seen_after = true;
        continue;
      }
      if (seen_after && line.find(needle) != std::string::npos) {
        return true;
      }
    }
    return false;
  }

  // Return all captured log lines containing `needle`.
  std::vector<std::string> FilterLogs(const std::string& needle) const {
    std::lock_guard<std::mutex> lock(log_mutex_);
    std::vector<std::string> result;
    for (const auto& line : captured_logs_) {
      if (line.find(needle) != std::string::npos) {
        result.push_back(line);
      }
    }
    return result;
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  mutable std::mutex log_mutex_;
  std::vector<std::string> captured_logs_;

  std::mutex cb_mutex_;
  std::condition_variable blocks_completed_cv_;
  std::condition_variable blocks_started_cv_;
  std::vector<std::string> completed_blocks_;
  std::vector<std::string> started_blocks_;
};

// ===========================================================================
// INV-CADENCE-SOURCE-SYNC-002 — Rule: Producer transition resets cadence
//
// Setup:
//   Block A: Sample60fps.mp4 (60/1 fps) → cadence ACTIVE (60→30)
//   Block B: SampleA.mp4 (30000/1001 fps) → cadence SHOULD be DISABLED
//
// Both blocks are fed before engine start so block B is prerolled during
// block A execution, triggering the seamless B→A rotation path.
//
// Assertion:
//   After FENCE_TRANSITION, a CADENCE_INIT or CADENCE_DISABLED log line
//   MUST appear before any subsequent TAKE_COMMIT.  This confirms
//   InitFrameSelectionCadenceForLiveBlock() was called.
//
// Current impl failure:
//   The seamless B→A rotation path (PipelineManager.cpp ~line 2239-2255)
//   does not call InitFrameSelectionCadenceForLiveBlock().  No CADENCE_INIT
//   log appears after the fence transition.  The 60→30 cadence persists.
// ===========================================================================

TEST_F(CadenceSourceSyncTest,
       SeamlessFenceRotation_MustReinitializeCadence_Rule002) {
  if (!FileExists(kPath60fps) || !FileExists(kPath30fps)) {
    GTEST_SKIP() << "Assets not found: " << kPath60fps << ", " << kPath30fps;
  }

  const int64_t block_a_ms = test_infra::kStdBlockMs;
  const int64_t block_b_ms = test_infra::kStdBlockMs;
  int64_t now = NowMs();

  FedBlock block_a = MakeSingleSegmentBlock(
      "cadence-sync-60fps", now, block_a_ms, kPath60fps);
  FedBlock block_b = MakeSingleSegmentBlock(
      "cadence-sync-30fps", now + block_a_ms, block_b_ms, kPath30fps);

  // Feed both blocks so block B is available for preroll → seamless fence.
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait for block A to complete (fence fires, B→A rotation happens).
  const int timeout_ms = 15000;
  bool a_completed = WaitForBlockCompleted("cadence-sync-60fps", timeout_ms);
  ASSERT_TRUE(a_completed)
      << "Block A did not complete within " << timeout_ms << "ms";

  // Give block B a few ticks to start emitting.
  std::this_thread::sleep_for(std::chrono::milliseconds(500));

  engine_->Stop();

  // -----------------------------------------------------------------------
  // Precondition: verify a seamless fence transition occurred.
  // FENCE_TRANSITION in the log confirms we exercised the seamless path
  // (not fallback or padded-gap).
  // -----------------------------------------------------------------------
  auto fence_lines = FilterLogs("FENCE_TRANSITION");
  ASSERT_FALSE(fence_lines.empty())
      << "No FENCE_TRANSITION logged — test did not exercise fence rotation";

  // Precondition: block A started with cadence ACTIVE (60→30).
  auto init_lines = FilterLogs("CADENCE_INIT");
  ASSERT_FALSE(init_lines.empty())
      << "No CADENCE_INIT at session start — cannot verify cadence was active";
  EXPECT_NE(init_lines[0].find("60"), std::string::npos)
      << "First CADENCE_INIT should reflect 60fps source: " << init_lines[0];

  // -----------------------------------------------------------------------
  // Primary assertion (INV-CADENCE-SOURCE-SYNC-002):
  // After FENCE_TRANSITION, a CADENCE_INIT or CADENCE_DISABLED must appear.
  // -----------------------------------------------------------------------
  bool has_cadence_reset_after_fence =
      HasLogLineAfter("FENCE_TRANSITION", "CADENCE_INIT") ||
      HasLogLineAfter("FENCE_TRANSITION", "CADENCE_DISABLED");

  // Diagnostic: dump relevant log lines on failure.
  if (!has_cadence_reset_after_fence) {
    std::ostringstream diag;
    diag << "INV-CADENCE-SOURCE-SYNC-002 VIOLATED.\n"
         << "No CADENCE_INIT or CADENCE_DISABLED after FENCE_TRANSITION.\n"
         << "The cadence from block A (60→30 ACTIVE) persists into block B.\n\n"
         << "Fence lines:\n";
    for (const auto& l : fence_lines) diag << "  " << l << "\n";
    diag << "\nAll CADENCE lines:\n";
    for (const auto& l : FilterLogs("CADENCE")) diag << "  " << l << "\n";
    diag << "\nBLOCK_START lines:\n";
    for (const auto& l : FilterLogs("BLOCK_START")) diag << "  " << l << "\n";
    ADD_FAILURE() << diag.str();
  }

  EXPECT_TRUE(has_cadence_reset_after_fence)
      << "Seamless fence rotation must reinitialize cadence "
      << "(INV-CADENCE-SOURCE-SYNC-002)";
}

// ===========================================================================
// INV-CADENCE-SOURCE-SYNC-002 — Verify ALL fence paths reinitialize cadence.
//
// This test verifies the count: every FENCE_TRANSITION must be paired with
// a subsequent CADENCE_INIT or CADENCE_DISABLED, with no unpaired fences.
//
// Three blocks are fed: A (60fps) → B (30fps) → C (30fps).
// Two fence transitions should each produce a cadence reinitialization.
// ===========================================================================

TEST_F(CadenceSourceSyncTest,
       EveryFenceTransition_PairedWithCadenceReset_Rule002) {
  if (!FileExists(kPath60fps) || !FileExists(kPath30fps)) {
    GTEST_SKIP() << "Assets not found: " << kPath60fps << ", " << kPath30fps;
  }

  const int64_t block_ms = test_infra::kStdBlockMs;
  int64_t now = NowMs();

  FedBlock block_a = MakeSingleSegmentBlock(
      "sync-fence-a", now, block_ms, kPath60fps);
  FedBlock block_b = MakeSingleSegmentBlock(
      "sync-fence-b", now + block_ms, block_ms, kPath30fps);
  FedBlock block_c = MakeSingleSegmentBlock(
      "sync-fence-c", now + 2 * block_ms, block_ms, kPath30fps);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
    ctx_->block_queue.push_back(block_c);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait for block B to complete (two fence transitions have occurred).
  // Three blocks with encoder init overhead — 60s is conservative.
  const int timeout_ms = 60000;
  bool b_completed = WaitForBlockCompleted("sync-fence-b", timeout_ms);
  ASSERT_TRUE(b_completed)
      << "Block B did not complete within " << timeout_ms << "ms";

  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  engine_->Stop();

  // Count FENCE_TRANSITION and post-fence CADENCE resets.
  auto all_logs = [this]() {
    std::lock_guard<std::mutex> lock(log_mutex_);
    return captured_logs_;
  }();

  int fence_count = 0;
  int cadence_reset_after_fence_count = 0;
  bool awaiting_cadence_reset = false;

  for (const auto& line : all_logs) {
    if (line.find("FENCE_TRANSITION") != std::string::npos) {
      fence_count++;
      awaiting_cadence_reset = true;
    }
    if (awaiting_cadence_reset &&
        (line.find("CADENCE_INIT") != std::string::npos ||
         line.find("CADENCE_DISABLED") != std::string::npos)) {
      cadence_reset_after_fence_count++;
      awaiting_cadence_reset = false;
    }
  }

  ASSERT_GE(fence_count, 2)
      << "Expected at least 2 fence transitions (A→B, B→C)";

  EXPECT_EQ(cadence_reset_after_fence_count, fence_count)
      << "Every FENCE_TRANSITION must be followed by CADENCE_INIT or "
      << "CADENCE_DISABLED (INV-CADENCE-SOURCE-SYNC-002). "
      << "Fences=" << fence_count
      << " CadenceResets=" << cadence_reset_after_fence_count;
}

}  // namespace
}  // namespace retrovue::blockplan::testing
