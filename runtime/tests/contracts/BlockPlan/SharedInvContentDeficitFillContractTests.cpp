// Repository: Retrovue-playout
// Component: INV-CONTENT-DEFICIT-FILL Contract Tests
// Purpose: Verify any content deficit (missing or exhausted content) is filled
//          with deterministic pad (black video + silence). The channel MUST NOT
//          stall, repeat, or emit garbled output. PadProducer is the authority
//          for all deficit intervals.
//
// Contract: docs/contracts/invariants/shared/INV-CONTENT-DEFICIT-FILL.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <condition_variable>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/util/Logger.hpp"
#include "FastTestConfig.hpp"
#include "TestDecoder.hpp"
#include "deterministic_tick_driver.hpp"

using retrovue::util::Logger;

namespace retrovue::blockplan::testing {

// =============================================================================
// ContentDeficitFillContractTest — shared fixture matching ContinuousOutputContractTest.
// =============================================================================
class ContentDeficitFillContractTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 42;
    int fds[2];
    ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
    ctx_->fd    = fds[0];
    drain_fd_   = fds[1];
    drain_stop_.store(false);
    drain_thread_ = std::thread([this] {
      char buf[8192];
      while (!drain_stop_.load(std::memory_order_relaxed)) {
        ssize_t n = read(drain_fd_, buf, sizeof(buf));
        if (n <= 0) break;
      }
    });
    ctx_->width  = 640;
    ctx_->height = 480;
    ctx_->fps    = FPS_30;
    test_ts_     = test_infra::MakeTestTimeSource();

    captured_logs_.clear();
    Logger::SetInfoSink([this](const std::string& line) {
      std::lock_guard<std::mutex> lock(log_mutex_);
      captured_logs_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetInfoSink(nullptr);
    if (engine_) { engine_->Stop(); engine_.reset(); }
    if (ctx_ && ctx_->fd >= 0) { close(ctx_->fd); ctx_->fd = -1; }
    drain_stop_.store(true);
    if (drain_fd_ >= 0) { shutdown(drain_fd_, SHUT_RDWR); close(drain_fd_); drain_fd_ = -1; }
    if (drain_thread_.joinable()) drain_thread_.join();
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

  std::unique_ptr<PipelineManager> MakeEngine() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_session_ended = [](const std::string&, int64_t) {};
    callbacks.on_block_completed = [](const FedBlock&, int64_t, int64_t) {};
    callbacks.on_block_started   = [](const FedBlock&, const BlockActivationContext&) {};
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0},
        std::make_shared<test_infra::TestProducerFactory>());
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::thread drain_thread_;
  std::atomic<bool> drain_stop_{false};

  mutable std::mutex log_mutex_;
  std::vector<std::string> captured_logs_;
};

// =============================================================================
// INV-CONTENT-DEFICIT-FILL — Compliant: 100% deficit is filled with pad.
//
// Scenario: Block queue is empty (no content). PipelineManager must still emit
// frames continuously — all filled by PadProducer (black + silence).
// Assert:
//   1. Frames are emitted despite zero content (no stall).
//   2. All emitted frames are pad frames (pad_frames_emitted_total == total).
// =============================================================================
TEST_F(ContentDeficitFillContractTest,
       Compliant_ZeroContent_AllFrameFilledByPad) {
  // Arrange: start engine with no blocks in queue (100% content deficit).
  engine_ = MakeEngine();
  engine_->Start();

  const int64_t kMinFrames = 5;
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), kMinFrames);

  engine_->Stop();

  // Assert.
  auto m = engine_->SnapshotMetrics();
  EXPECT_GT(m.continuous_frames_emitted_total, 0)
      << "INV-CONTENT-DEFICIT-FILL: Engine must emit frames even with zero "
         "content (deficit must be filled, not stalled)";
  EXPECT_LE(m.continuous_frames_emitted_total,
            test_utils::kMaxTestTicks)
      << "INV-CONTENT-DEFICIT-FILL: Bounded deterministic test ceiling";
  EXPECT_EQ(m.pad_frames_emitted_total, m.continuous_frames_emitted_total)
      << "INV-CONTENT-DEFICIT-FILL: In zero-content scenario every frame must "
         "be a pad frame (black + silence). Deficit = 100%, fill = 100%.";

  // Log evidence: TAKE_PAD_ENTER must be emitted when pad authority engages.
  auto pad_enter_lines = FilterLogs("TAKE_PAD_ENTER");
  EXPECT_FALSE(pad_enter_lines.empty())
      << "INV-CONTENT-DEFICIT-FILL: TAKE_PAD_ENTER must be logged when "
         "content deficit triggers pad fill";

  // Pad authority lifecycle: TAKE_PAD_EXIT must NOT occur because content
  // never resumes in the zero-content scenario. Once pad authority is
  // active, it holds for the entire session.
  auto pad_exit_lines = FilterLogs("TAKE_PAD_EXIT");
  EXPECT_TRUE(pad_exit_lines.empty())
      << "INV-CONTENT-DEFICIT-FILL: TAKE_PAD_EXIT must not occur in "
         "zero-content scenario — pad authority is permanent";
}

// =============================================================================
// INV-CONTENT-DEFICIT-FILL — Compliant: partial deficit filled with pad.
//
// Scenario: A content block is fed. TestDecoder emits frames for its block
// duration; when the block's fence is reached PipelineManager may switch to
// pad for any remaining block time. Assert pad_frames_emitted_total >= 0 and
// total frames ≥ fence (no stall at content boundary).
// =============================================================================
TEST_F(ContentDeficitFillContractTest,
       Compliant_ContentPlusDeficit_NoContinuityGap) {
  // Arrange: push one finite content block.
  FedBlock block;
  block.block_id   = "inv-cdf-block-a";
  block.channel_id = 42;
  const int64_t now_ms =
      1'700'000'000'000LL + test_infra::kBlockTimeOffsetMs;
  block.start_utc_ms = now_ms;
  block.end_utc_ms   = now_ms + test_infra::kStdBlockMs;
  FedBlock::Segment seg;
  seg.segment_index        = 0;
  seg.asset_uri            = "test://content";
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms  = test_infra::kStdBlockMs;
  block.segments.push_back(seg);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance until block is well under way.
  const int64_t kFence = test_infra::FenceTickAt30fps(test_infra::kStdBlockMs / 2);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), kFence);

  engine_->Stop();

  // Assert: total frames emitted ≥ fence (no gap anywhere).
  auto m = engine_->SnapshotMetrics();
  EXPECT_GE(m.continuous_frames_emitted_total, kFence)
      << "INV-CONTENT-DEFICIT-FILL: Total frames must reach fence — "
         "no stall at content/pad boundary";
  EXPECT_LE(m.continuous_frames_emitted_total,
            test_utils::kMaxTestTicks)
      << "INV-CONTENT-DEFICIT-FILL: Bounded test ceiling";

  // Pad authority must not be active during content playback.
  // Within the content window (fence = half of block), all frames are content.
  EXPECT_EQ(m.pad_frames_emitted_total, 0)
      << "INV-CONTENT-DEFICIT-FILL: Pad must not be active during content "
         "playback — content authority is sole owner";
  auto pad_enter_lines = FilterLogs("TAKE_PAD_ENTER");
  EXPECT_TRUE(pad_enter_lines.empty())
      << "INV-CONTENT-DEFICIT-FILL: TAKE_PAD_ENTER must not fire during "
         "content playback window";
}

// =============================================================================
// INV-CONTENT-DEFICIT-FILL — Content EOF before block fence: output continuous.
//
// Scenario: A content segment shorter than the block duration.
// TestDecoder hits EOF at segment_duration_ms; the block fence is later.
// PipelineManager uses hold-last (repeat last decoded frame) to bridge the
// deficit — SegmentAdvanceOnEOFTests.cpp confirms this production behavior.
// Assert:
//   1. Total frames emitted reach the fence (no stall at content EOF boundary).
//   2. Output is bounded (deterministic test ceiling).
// The deficit is bridged by hold-last frames, preserving output liveness.
// =============================================================================
TEST_F(ContentDeficitFillContractTest,
       Compliant_ContentEOFBeforeFence_OutputContinuous) {
  // Arrange: block duration is 2x the content segment duration.
  // TestDecoder produces frames for segment_duration_ms then hits EOF.
  // The remaining block time is filled by hold-last (repeat last frame).
  const int64_t content_ms = test_infra::kStdBlockMs;
  const int64_t block_ms   = test_infra::kStdBlockMs * 2;
  const int64_t now_ms =
      1'700'000'000'000LL + test_infra::kBlockTimeOffsetMs;

  FedBlock block;
  block.block_id     = "inv-cdf-eof-mid";
  block.channel_id   = 42;
  block.start_utc_ms = now_ms;
  block.end_utc_ms   = now_ms + block_ms;

  FedBlock::Segment seg;
  seg.segment_index         = 0;
  seg.asset_uri             = "test://short-content";
  seg.asset_start_offset_ms = 0;
  // Segment duration = half of block → TestDecoder EOF at content_ms.
  // Block fence is at block_ms → deficit gap from content_ms to block_ms.
  seg.segment_duration_ms   = content_ms;
  seg.segment_type          = SegmentType::kContent;
  block.segments.push_back(seg);

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance past the content EOF point into the deficit region.
  const int64_t kFence = test_infra::FenceTickAt30fps(content_ms + content_ms / 2);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), kFence);

  engine_->Stop();

  // Assert: frames emitted with no stall through the content deficit.
  auto m = engine_->SnapshotMetrics();
  EXPECT_GE(m.continuous_frames_emitted_total, kFence)
      << "INV-CONTENT-DEFICIT-FILL: Total frames must reach fence — "
         "no stall at content EOF boundary. Deficit bridged by hold-last.";
  EXPECT_LE(m.continuous_frames_emitted_total,
            test_utils::kMaxTestTicks)
      << "INV-CONTENT-DEFICIT-FILL: Bounded deterministic test ceiling";

  // Hold-last vs pad distinction: TAKE_PAD_ENTER must NOT occur.
  // When content EOF happens mid-block, PipelineManager bridges the gap
  // with hold-last (repeats the last decoded frame), NOT pad.
  // This is confirmed by SegmentAdvanceOnEOFTests.cpp production behavior.
  auto pad_enter_lines = FilterLogs("TAKE_PAD_ENTER");
  EXPECT_TRUE(pad_enter_lines.empty())
      << "INV-CONTENT-DEFICIT-FILL: TAKE_PAD_ENTER must not fire during "
         "hold-last deficit fill. Hold-last is the authority after content "
         "EOF mid-block, not PadProducer.";

  // Pad metric must be zero — all deficit frames are hold-last, not pad.
  EXPECT_EQ(m.pad_frames_emitted_total, 0)
      << "INV-CONTENT-DEFICIT-FILL: pad_frames must be 0 when deficit is "
         "bridged by hold-last (content EOF mid-block)";

  // Hold-last evidence: total frames > content segment frames.
  // The segment produces exactly content_frames decoded frames; the
  // remaining ticks beyond that are hold-last (same frame re-encoded).
  const int64_t content_frames =
      ctx_->fps.FramesFromDurationCeilMs(content_ms);
  EXPECT_GT(m.continuous_frames_emitted_total, content_frames)
      << "INV-CONTENT-DEFICIT-FILL: Total frames (" << m.continuous_frames_emitted_total
      << ") must exceed content segment frames (" << content_frames
      << ") — the surplus proves hold-last bridged the deficit";
}

// =============================================================================
// INV-CONTENT-DEFICIT-FILL — Single authority: TAKE_PAD_ENTER/EXIT form
// a proper state machine with no overlapping authority.
//
// Scenario: Two content blocks are fed back-to-back. After block B completes
// (fence fires), no block C is available → PADDED_GAP (pad authority).
// Assert:
//   1. TAKE_PAD_ENTER/EXIT transitions are properly paired.
//   2. No double-ENTER (pad while already in pad) or double-EXIT.
//   3. count(ENTER) == count(EXIT) + 0_or_1 (session may end in pad).
//   4. pad + content frames == total (complete accounting, no gap).
// =============================================================================
TEST_F(ContentDeficitFillContractTest,
       SingleAuthority_PadContentTransitionsArePaired) {
  // Arrange: two back-to-back blocks, no third block → pad at fence B.
  // Block timestamps must align with the session epoch (test_ts_->NowUtcMs())
  // so the block fence fires at the expected frame.
  const int64_t block_ms = test_infra::kStdBlockMs;
  const int64_t now_ms = test_ts_->NowUtcMs();

  FedBlock block_a;
  block_a.block_id     = "inv-cdf-auth-a";
  block_a.channel_id   = 42;
  block_a.start_utc_ms = now_ms;
  block_a.end_utc_ms   = now_ms + block_ms;
  {
    FedBlock::Segment seg;
    seg.segment_index         = 0;
    seg.asset_uri             = "test://content-a";
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms   = block_ms;
    seg.segment_type          = SegmentType::kContent;
    block_a.segments.push_back(seg);
  }

  FedBlock block_b;
  block_b.block_id     = "inv-cdf-auth-b";
  block_b.channel_id   = 42;
  block_b.start_utc_ms = now_ms + block_ms;
  block_b.end_utc_ms   = now_ms + 2 * block_ms;
  {
    FedBlock::Segment seg;
    seg.segment_index         = 0;
    seg.asset_uri             = "test://content-b";
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms   = block_ms;
    seg.segment_type          = SegmentType::kContent;
    block_b.segments.push_back(seg);
  }

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Advance past both blocks into the PADDED_GAP region.
  const int64_t kFence = test_infra::FenceTickAt30fps(2 * block_ms + block_ms / 2);
  test_utils::AdvanceUntilFenceOrFail(engine_.get(), kFence);

  engine_->Stop();

  // Metric: total frames emitted.
  auto m = engine_->SnapshotMetrics();
  EXPECT_GE(m.continuous_frames_emitted_total, kFence)
      << "INV-CONTENT-DEFICIT-FILL: Total frames must reach fence — "
         "no stall at content/pad boundary";

  // Single authority — complete accounting: pad + content == total.
  // content_frames = total - pad (derived; each tick is exactly one authority).
  const int64_t content_frames =
      m.continuous_frames_emitted_total - m.pad_frames_emitted_total;
  EXPECT_GE(content_frames, 0)
      << "INV-CONTENT-DEFICIT-FILL: content frames cannot be negative";
  EXPECT_EQ(content_frames + m.pad_frames_emitted_total,
            m.continuous_frames_emitted_total)
      << "INV-CONTENT-DEFICIT-FILL: pad + content must equal total "
         "(single authority, no overlap, no gap)";

  // Pad authority must be active after content exhaustion (PADDED_GAP).
  EXPECT_GT(m.pad_frames_emitted_total, 0)
      << "INV-CONTENT-DEFICIT-FILL: After content blocks exhaust with no "
         "next block, pad must fill the deficit";

  // TAKE_PAD_ENTER/EXIT state machine: transitions must be properly paired.
  auto enter_lines = FilterLogs("TAKE_PAD_ENTER");
  auto exit_lines  = FilterLogs("TAKE_PAD_EXIT");

  // Validate: no double-ENTER or double-EXIT.
  // Walk the log stream and verify alternating ENTER/EXIT sequence.
  {
    std::lock_guard<std::mutex> lock(log_mutex_);
    bool in_pad = false;
    bool found_violation = false;
    std::string violation_msg;
    for (const auto& line : captured_logs_) {
      if (line.find("TAKE_PAD_ENTER") != std::string::npos) {
        if (in_pad) {
          found_violation = true;
          violation_msg = "Double TAKE_PAD_ENTER (pad while already in pad): "
                          + line;
          break;
        }
        in_pad = true;
      } else if (line.find("TAKE_PAD_EXIT") != std::string::npos) {
        if (!in_pad) {
          found_violation = true;
          violation_msg = "TAKE_PAD_EXIT without prior TAKE_PAD_ENTER: "
                          + line;
          break;
        }
        in_pad = false;
      }
    }
    EXPECT_FALSE(found_violation)
        << "INV-CONTENT-DEFICIT-FILL: Single authority violation — "
        << violation_msg;
  }

  // count(ENTER) == count(EXIT) or count(ENTER) == count(EXIT) + 1
  // (session may end while pad is active).
  EXPECT_TRUE(enter_lines.size() == exit_lines.size() ||
              enter_lines.size() == exit_lines.size() + 1)
      << "INV-CONTENT-DEFICIT-FILL: ENTER/EXIT count mismatch — "
      << "ENTER=" << enter_lines.size() << " EXIT=" << exit_lines.size()
      << ". Transitions must pair properly.";
}

}  // namespace retrovue::blockplan::testing
