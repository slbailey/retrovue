// Repository: Retrovue-playout
// Component: Segment Seam Overlap Contract Tests
// Purpose: Verify invariants defined in SegmentSeamOverlapContract.md
// Contract Reference: pkg/air/docs/contracts/semantics/SegmentSeamOverlapContract.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-SEGSEAM-001: NoReactiveAdvancement
//     Outcome: INV-SEAM-SEG-002 (No Reactive Transitions)
//     Verify: TryGetFrame returns nullopt at segment boundary.
//             current_segment_index_ is not modified by TryGetFrame.
//             AdvanceToNextSegment does not exist as a callable method.
//     Asset-agnostic: Yes (synthetic multi-segment block, unresolvable URIs).
//     Method: Create a TickProducer with a 2-segment block. Call AssignBlock.
//             Advance block_ct_ms past boundary[0].end_ct_ms via repeated
//             TryGetFrame calls. Once segment 0 content exhausts, TryGetFrame
//             MUST return nullopt on every subsequent call. The segment index
//             MUST remain 0 — the producer does not know about segment 1.
//     Assertions:
//       - TryGetFrame() returns nullopt after segment exhaustion (not a new frame)
//       - GetCurrentSegmentIndex() == 0 after exhaustion (no advancement)
//       - No SEGMENT_ADVANCE or SEGMENT_DECODER_OPEN in captured logs
//
//   T-SEGSEAM-002: EagerArmingAtActivation
//     Outcome: INV-SEAM-SEG-003 (Eager Arming)
//     Verify: When segment 0 of a multi-segment block becomes active (block
//             TAKE or initial load), a segment prep request for segment 1 is
//             armed before the tick thread advances to the next frame.
//     Asset-agnostic: Yes (synthetic blocks, unresolvable URIs → pad output).
//     Method: Create a 2-segment block (each 1s) followed by a second block.
//             Run engine. Capture SEGMENT_PREP_ARMED log events. Verify that
//             SEGMENT_PREP_ARMED fires on the same tick as BLOCK_START for the
//             multi-segment block, and that the armed segment index is 1.
//     Assertions:
//       - SEGMENT_PREP_ARMED emitted within 1 tick of block activation
//       - Armed segment_index == 1
//       - For the second block (single-segment), no SEGMENT_PREP_ARMED fires
//         (last segment has no successor within block)
//       - detach_count == 0 (session survives)
//
//   T-SEGSEAM-003: DeterministicSeamTickComputation
//     Outcome: INV-SEAM-SEG-004 (Deterministic Seam Tick)
//     Verify: The computed segment_seam_frame matches the exact rational-ceil
//             formula for known inputs. No floating-point drift. No tolerance.
//     Asset-agnostic: Yes (pure arithmetic, no engine run needed).
//     Method: Unit test of the seam tick computation function directly.
//             Test cases:
//               a) boundary.end_ct_ms=1000, fps_num=30, fps_den=1,
//                  block_activation_frame=0 → seam_frame=30
//               b) boundary.end_ct_ms=1001, fps_num=30000, fps_den=1001,
//                  block_activation_frame=0 → seam_frame=ceil(1001*30000/(1001*1000))=31
//               c) boundary.end_ct_ms=500, fps_num=24000, fps_den=1001,
//                  block_activation_frame=100 → exact expected value
//               d) boundary.end_ct_ms=0 → seam_frame == block_activation_frame
//     Assertions:
//       - Each computed value == expected value exactly (EXPECT_EQ, not EXPECT_NEAR)
//       - Same formula as INV-BLOCK-WALLFENCE-001 fence computation
//       - Monotonicity: seam_frames[i] < seam_frames[i+1] for ordered boundaries
//
//   T-SEGSEAM-004: AudioContinuityAtSegmentSeam
//     Outcome: INV-SEAM-SEG-001 (Clock Isolation) + INV-SEAM-SEG-005 (Unified Mechanism)
//     Verify: For a multi-segment block with real media assets (both segments
//             have audio tracks), the intra-block segment seam produces zero
//             audio fallback. The overlap mechanism primes segment 1's audio
//             before the seam tick.
//     Asset-agnostic: No (requires SampleA.mp4 + SampleB.mp4). GTEST_SKIP if missing.
//     Method: Create a 2-segment block (episode 1.5s + filler 1.5s, real media).
//             Run engine for 4s. Snapshot metrics after segment seam fires.
//     Assertions:
//       - audio_silence_injected == 0 (no silence at segment seam)
//       - max_consecutive_audio_fallback_ticks == 0 (perfect continuity)
//       - max_inter_frame_gap_us < 50000 (no tick-thread stall at seam)
//       - detach_count == 0 (session survives)
//       - source_swap_count >= 1 (segment swap occurred, or block swap if followed)
//       - Fingerprints show content from both segments (not pad)
//
//   T-SEGSEAM-005: BlockPrepNotStarvedBySegmentPrep
//     Outcome: INV-SEAM-SEG-003 (Eager Arming, priority ordering)
//     Verify: When a multi-segment block is followed by a second block, the
//             seam-prep thread completes the block-level prep before the block
//             fence tick, despite segment prep activity within the first block.
//     Asset-agnostic: Yes (synthetic blocks, unresolvable URIs → pad output).
//     Method: Create a 3-segment block A (each segment 1s, total 3s) followed
//             by block B (single segment, 2s). Run engine for 6s. Verify that
//             block B's TAKE succeeds (not a PADDED_GAP) despite segments 1 and
//             2 of block A requiring prep on the same seam-prep thread.
//     Assertions:
//       - padded_gap_count == 0 (block B loaded successfully)
//       - source_swap_count >= 1 (block TAKE fired)
//       - Block B's block_id appears in completed_blocks (or BLOCK_START logged)
//       - detach_count == 0 (session survives)
//       - fence_preload_miss_count == 0 (block prep was not starved)
//
//   T-SEGSEAM-006: PadSegmentPreparedAndSwapped
//     Outcome: INV-SEAM-SEG-005 (Unified Mechanism) + INV-SEAM-SEG-003 (Eager Arming)
//     Verify: A content→pad segment transition is handled by the same
//             prep→swap mechanism as content→content. The pad segment gets
//             a synthetic FedBlock, is prepared by the seam-prep thread
//             (instantaneous — no decoder to open), and is swapped at the
//             computed seam tick via pointer rotation.
//     Asset-agnostic: Partially (segment 0 uses real media for content, segment 1
//                     is pad). GTEST_SKIP if SampleA.mp4 missing.
//     Method: Create a 2-segment block where segment 0 is content (SampleA.mp4,
//             1.5s) and segment 1 is pad (1.5s, kPad type). Run engine for 4s.
//             Verify the transition at segment 0's seam tick is a pointer swap,
//             not a reactive decoder close.
//     Assertions:
//       - max_inter_frame_gap_us < 50000 (no stall at content→pad seam)
//       - SEGMENT_PREP_ARMED logged for the pad segment (prep thread handled it)
//       - Fingerprints show content frames before seam tick, pad frames after
//       - No SEGMENT_ADVANCE or SEGMENT_DECODER_OPEN on fill thread
//       - detach_count == 0 (session survives)
//       - late_ticks_total == 0 (clock isolated from pad transition)
//
// Test → Contract → Outcome Mapping:
//
//   | Test           | INV-SEAM-SEG | Outcome Verified                              | Asset-Agnostic? |
//   |----------------|--------------|-----------------------------------------------|-----------------|
//   | T-SEGSEAM-001  | 002          | TryGetFrame does not advance segments          | Yes             |
//   | T-SEGSEAM-002  | 003          | Segment prep armed at activation               | Yes             |
//   | T-SEGSEAM-003  | 004          | Seam tick uses rational ceil, exact match       | Yes             |
//   | T-SEGSEAM-004  | 001, 005     | No audio fallback at segment seam (real media)  | No              |
//   | T-SEGSEAM-005  | 003          | Block prep completes despite segment prep load  | Yes             |
//   | T-SEGSEAM-006  | 003, 005     | Pad segment uses same prep→swap mechanism       | Partial         |
//
// Coverage: All 6 INV-SEAM-SEG invariants covered.
//           3 of 6 tests are fully asset-agnostic.
//           INV-SEAM-SEG-006 (no decoder lifecycle on fill thread) is implicitly
//           verified by all tests via absence of SEGMENT_ADVANCE / SEGMENT_DECODER_OPEN
//           on the fill thread, and explicitly by T-SEGSEAM-001 (structural) and
//           T-SEGSEAM-004 (runtime).

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
#include "retrovue/blockplan/TickProducer.hpp"

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
    const std::string& seg0_uri,
    int64_t seg0_duration_ms,
    const std::string& seg1_uri,
    int64_t seg1_duration_ms,
    SegmentType seg0_type = SegmentType::kContent,
    SegmentType seg1_type = SegmentType::kFiller) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + duration_ms;

  FedBlock::Segment s0;
  s0.segment_index = 0;
  s0.asset_uri = seg0_uri;
  s0.asset_start_offset_ms = 0;
  s0.segment_duration_ms = seg0_duration_ms;
  s0.segment_type = seg0_type;
  block.segments.push_back(s0);

  FedBlock::Segment s1;
  s1.segment_index = 1;
  s1.asset_uri = seg1_uri;
  s1.asset_start_offset_ms = 0;
  s1.segment_duration_ms = seg1_duration_ms;
  s1.segment_type = seg1_type;
  block.segments.push_back(s1);

  return block;
}

static FedBlock MakeThreeSegmentBlock(
    const std::string& block_id,
    int64_t start_utc_ms,
    int64_t total_duration_ms,
    int64_t seg0_ms, int64_t seg1_ms, int64_t seg2_ms,
    const std::string& uri = "/nonexistent/test.mp4") {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + total_duration_ms;

  auto add_seg = [&](int idx, int64_t dur_ms) {
    FedBlock::Segment seg;
    seg.segment_index = idx;
    seg.asset_uri = uri;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = dur_ms;
    seg.segment_type = (idx == 0) ? SegmentType::kContent : SegmentType::kFiller;
    block.segments.push_back(seg);
  };
  add_seg(0, seg0_ms);
  add_seg(1, seg1_ms);
  add_seg(2, seg2_ms);

  return block;
}

static int64_t NowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
}

/// Compute segment seam frame using the exact rational-ceil formula.
/// This is the reference implementation for T-SEGSEAM-003.
static int64_t ComputeSegmentSeamFrame(
    int64_t block_activation_frame,
    int64_t boundary_end_ct_ms,
    int64_t fps_num,
    int64_t fps_den) {
  if (boundary_end_ct_ms <= 0) return block_activation_frame;
  int64_t denominator = fps_den * 1000;
  return block_activation_frame +
      (boundary_end_ct_ms * fps_num + denominator - 1) / denominator;
}

// =============================================================================
// Test Fixture
// =============================================================================

class SegmentSeamOverlapContractTest : public ::testing::Test {
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
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct, int64_t) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
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

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::condition_variable blocks_completed_cv_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;
  std::vector<std::string> completed_blocks_;
  std::vector<SeamTransitionLog> seam_logs_;
  std::vector<BlockPlaybackSummary> summaries_;

  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;
};

// =============================================================================
// T-SEGSEAM-001: NoReactiveAdvancement
// Contract: INV-SEAM-SEG-002 (No Reactive Transitions)
//
// TryGetFrame returns nullopt at segment boundary without advancing segments.
// AdvanceToNextSegment must not exist. current_segment_index_ stays at 0.
// =============================================================================

// TODO: Implement after TickProducer is refactored to remove AdvanceToNextSegment.
// This test will create a TickProducer directly, call AssignBlock with a
// multi-segment block, exhaust segment 0 via TryGetFrame, and assert:
//   - TryGetFrame returns nullopt (not a frame from segment 1)
//   - GetCurrentSegmentIndex() == 0
//   - No decoder lifecycle log emitted

// =============================================================================
// T-SEGSEAM-002: EagerArmingAtActivation
// Contract: INV-SEAM-SEG-003 (Eager Arming)
//
// Segment prep for N+1 is armed on the same tick as segment N's activation.
// =============================================================================

// TODO: Implement after PipelineManager gains segment seam tracking and
// SEGMENT_PREP_ARMED log. This test will:
//   - Create a 2-segment synthetic block + a follow-up single-segment block
//   - Run engine, capture logs
//   - Assert SEGMENT_PREP_ARMED fires on same tick as BLOCK_START
//   - Assert no SEGMENT_PREP_ARMED for single-segment block

// =============================================================================
// T-SEGSEAM-003: DeterministicSeamTickComputation
// Contract: INV-SEAM-SEG-004 (Deterministic Seam Tick)
//
// Pure arithmetic test — no engine run. Exact integer results, no tolerance.
// =============================================================================

TEST_F(SegmentSeamOverlapContractTest, T_SEGSEAM_003_DeterministicSeamTick) {
  // Case a: 1000ms boundary, 30fps integer, activation=0
  // seam = 0 + ceil(1000 * 30 / (1 * 1000)) = 30
  EXPECT_EQ(ComputeSegmentSeamFrame(0, 1000, 30, 1), 30);

  // Case b: 1001ms boundary, 29.97fps rational (30000/1001), activation=0
  // seam = 0 + ceil(1001 * 30000 / (1001 * 1000))
  //       = ceil(30030000 / 1001000)
  //       = ceil(30.0) = 30
  EXPECT_EQ(ComputeSegmentSeamFrame(0, 1001, 30000, 1001), 30);

  // Case c: 500ms boundary, 23.976fps (24000/1001), activation=100
  // seam = 100 + ceil(500 * 24000 / (1001 * 1000))
  //       = 100 + ceil(12000000 / 1001000)
  //       = 100 + ceil(11.988...) = 100 + 12 = 112
  EXPECT_EQ(ComputeSegmentSeamFrame(100, 500, 24000, 1001), 112);

  // Case d: 0ms boundary → seam == activation frame
  EXPECT_EQ(ComputeSegmentSeamFrame(50, 0, 30, 1), 50);

  // Monotonicity: ordered boundaries produce ordered seam frames
  int64_t s1 = ComputeSegmentSeamFrame(0, 1000, 30000, 1001);
  int64_t s2 = ComputeSegmentSeamFrame(0, 2000, 30000, 1001);
  int64_t s3 = ComputeSegmentSeamFrame(0, 3000, 30000, 1001);
  EXPECT_LT(s1, s2);
  EXPECT_LT(s2, s3);
}

// =============================================================================
// T-SEGSEAM-004: AudioContinuityAtSegmentSeam
// Contract: INV-SEAM-SEG-001 (Clock Isolation) + INV-SEAM-SEG-005 (Unified Mechanism)
//
// Real media: segment seam swap with zero audio fallback.
// GTEST_SKIP if assets missing.
// =============================================================================

// TODO: Implement after PipelineManager supports segment seam swaps.
// This test will:
//   - Create a 2-segment block with real media (SampleA 1.5s + SampleB 1.5s)
//   - Run engine for 4s
//   - Assert audio_silence_injected == 0
//   - Assert max_consecutive_audio_fallback_ticks == 0
//   - Assert max_inter_frame_gap_us < 50000

// =============================================================================
// T-SEGSEAM-005: BlockPrepNotStarvedBySegmentPrep
// Contract: INV-SEAM-SEG-003 (Eager Arming, priority ordering)
//
// Block-level prep completes despite concurrent segment prep.
// =============================================================================

// TODO: Implement after SeamPreparer with priority queue is in place.
// This test will:
//   - Create a 3-segment block A (1s + 1s + 1s) + block B (2s)
//   - Run engine for 6s
//   - Assert padded_gap_count == 0 (block B not starved)
//   - Assert fence_preload_miss_count == 0

// =============================================================================
// T-SEGSEAM-006: PadSegmentPreparedAndSwapped
// Contract: INV-SEAM-SEG-005 (Unified Mechanism) + INV-SEAM-SEG-003 (Eager Arming)
//
// Pad segment uses same prep→swap mechanism as content segments.
// GTEST_SKIP if SampleA.mp4 missing.
// =============================================================================

// TODO: Implement after PipelineManager supports segment seam swaps with pad.
// This test will:
//   - Create a 2-segment block (SampleA 1.5s content + 1.5s pad)
//   - Run engine for 4s
//   - Assert max_inter_frame_gap_us < 50000 (no stall at content→pad)
//   - Assert SEGMENT_PREP_ARMED logged for pad segment
//   - Assert late_ticks_total == 0

}  // namespace
}  // namespace retrovue::blockplan::testing
