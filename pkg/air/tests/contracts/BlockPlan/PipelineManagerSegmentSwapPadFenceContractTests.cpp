// Repository: Retrovue-playout
// Component: PipelineManager segment-swap-to-PAD fence contract tests
// Purpose: Enforce INV-PAD-SEAM-AUDIO-READY: when the active segment is PAD,
//          audio source must be non-null, routable to a concrete buffer, have
//          silence available before fence evaluation, and must never trigger
//          FENCE_AUDIO_PAD. Reproduces CONTENT → CONTENT → PAD segment swap path.
// Contract Reference: INV-PAD-SEAM-AUDIO-READY (docs/contracts/INVARIANTS.md);
//          INV-PAD-PRODUCER, FENCE_AUDIO_PAD semantics.
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cinttypes>
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
#include <unordered_map>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"
#include "retrovue/blockplan/RationalFps.hpp"
#include "deterministic_tick_driver.hpp"
#include "FastTestConfig.hpp"

namespace retrovue::blockplan::testing {
namespace {

static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";

static bool FileExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

static FedBlock MakeContentContentPadBlock(const std::string& block_id,
                                          int64_t start_utc_ms,
                                          int64_t seg0_ms,
                                          int64_t seg1_ms,
                                          int64_t seg2_pad_ms) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + seg0_ms + seg1_ms + seg2_pad_ms;

  FedBlock::Segment s0;
  s0.segment_index = 0;
  s0.asset_uri = kPathA;
  s0.asset_start_offset_ms = 0;
  s0.segment_duration_ms = seg0_ms;
  s0.segment_type = SegmentType::kContent;
  block.segments.push_back(s0);

  FedBlock::Segment s1;
  s1.segment_index = 1;
  s1.asset_uri = kPathB;
  s1.asset_start_offset_ms = 0;
  s1.segment_duration_ms = seg1_ms;
  s1.segment_type = SegmentType::kContent;
  block.segments.push_back(s1);

  FedBlock::Segment s2;
  s2.segment_index = 2;
  s2.asset_uri = "";
  s2.asset_start_offset_ms = 0;
  s2.segment_duration_ms = seg2_pad_ms;
  s2.segment_type = SegmentType::kPad;
  block.segments.push_back(s2);

  return block;
}

struct SegmentSwapTickRecord {
  int64_t tick_index = 0;
  std::string decision;
  char slot = '?';  // A/B/P from on_frame_emitted
  bool a_src_is_null = false;
  int fence_audio_pad_warning_delta = 0;
};

struct SegmentSeamTakeRecord {
  int64_t tick = 0;
  int64_t next_seam_frame = 0;
};

struct CadenceRefreshRecord {
  RationalFps old_fps{0, 1};
  RationalFps new_fps{0, 1};
  RationalFps output_fps{0, 1};
  std::string mode;
};

class PipelineManagerSegmentSwapPadFenceTest : public ::testing::Test {
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
    tick_records_.clear();
    segment_seam_take_records_.clear();
    slot_by_frame_.clear();
    pad_segment_start_tick_ = -1;
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

  std::unique_ptr<PipelineManager> MakeEngineWithObservability() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock&, int64_t, int64_t) {};
    callbacks.on_session_ended = [this](const std::string&, int64_t) {};
    callbacks.on_segment_start = [this](int32_t from_seg, int32_t to_seg,
                                        const FedBlock& block, int64_t session_frame_index) {
      if (to_seg == 2 && static_cast<size_t>(2) < block.segments.size() &&
          block.segments[2].segment_type == SegmentType::kPad) {
        std::lock_guard<std::mutex> lock(rec_mutex_);
        if (pad_segment_start_tick_ < 0) {
          pad_segment_start_tick_ = session_frame_index;
        }
      }
    };
    callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
      std::lock_guard<std::mutex> lock(rec_mutex_);
      slot_by_frame_[fp.session_frame_index] = fp.commit_slot;
    };
    callbacks.on_tick_pad_fence_observability =
        [this](int64_t session_frame_index, const char* decision,
               bool a_src_is_null, bool fence_audio_pad_warning_this_tick,
               bool pad_frame_emitted_this_tick) {
          std::lock_guard<std::mutex> lock(rec_mutex_);
          SegmentSwapTickRecord rec;
          rec.tick_index = session_frame_index;
          rec.decision = decision ? decision : "";
          rec.a_src_is_null = a_src_is_null;
          rec.fence_audio_pad_warning_delta = fence_audio_pad_warning_this_tick ? 1 : 0;
          auto it = slot_by_frame_.find(session_frame_index);
          rec.slot = (it != slot_by_frame_.end()) ? it->second : '?';
          tick_records_.push_back(rec);
        };
    callbacks.on_segment_seam_take = [this](int64_t session_frame_index, int64_t next_seam_frame) {
      std::lock_guard<std::mutex> lock(rec_mutex_);
      segment_seam_take_records_.push_back({session_frame_index, next_seam_frame});
    };
    callbacks.on_frame_selection_cadence_refresh =
        [this](RationalFps old_fps, RationalFps new_fps, RationalFps output_fps, const std::string& mode) {
          std::lock_guard<std::mutex> lock(rec_mutex_);
          cadence_refreshes_.push_back({old_fps, new_fps, output_fps, mode});
        };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0});
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  int64_t GetPadSegmentStartTick() const {
    std::lock_guard<std::mutex> lock(rec_mutex_);
    return pad_segment_start_tick_;
  }

  std::vector<SegmentSwapTickRecord> SnapshotTickRecords() {
    std::lock_guard<std::mutex> lock(rec_mutex_);
    return tick_records_;
  }

  std::vector<SegmentSeamTakeRecord> SnapshotSegmentSeamTakeRecords() {
    std::lock_guard<std::mutex> lock(rec_mutex_);
    return segment_seam_take_records_;
  }

  std::vector<CadenceRefreshRecord> SnapshotCadenceRefreshes() {
    std::lock_guard<std::mutex> lock(rec_mutex_);
    return cadence_refreshes_;
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  mutable std::mutex rec_mutex_;
  std::vector<SegmentSwapTickRecord> tick_records_;
  std::vector<SegmentSeamTakeRecord> segment_seam_take_records_;
  std::vector<CadenceRefreshRecord> cadence_refreshes_;
  std::unordered_map<int64_t, char> slot_by_frame_;
  int64_t pad_segment_start_tick_ = -1;
};

// Scenario: Block with Segment 0 = CONTENT, Segment 1 = CONTENT, Segment 2 = PAD.
// Force segment swap to PAD (not block end). Assert no FENCE_AUDIO_PAD and
// a_src never null during PAD segment ticks.
TEST_F(PipelineManagerSegmentSwapPadFenceTest, SegmentSwapToPad_NoFenceAudioPad) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 1500;
  const int64_t seg1_ms = 1500;
  const int64_t seg2_pad_ms = 3000;
  int64_t now = NowMs();

  FedBlock block = MakeContentContentPadBlock(
      "segswap-pad", now, seg0_ms, seg1_ms, seg2_pad_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngineWithObservability();
  engine_->Start();

  // At 30fps, seg0+seg1 = 3s ≈ 90 frames. Run until we're well into PAD segment
  // (segment 2 starts around frame 90) then 60 more ticks.
  const int64_t kMinFramesPastPadStart = 60;
  const int64_t kMaxWaitFrames = 250;
  int64_t pad_start = -1;
  for (int i = 0; i < 500; i++) {
    pad_start = GetPadSegmentStartTick();
    int64_t cur = engine_->SnapshotMetrics().continuous_frames_emitted_total;
    if (pad_start >= 0 && cur >= pad_start + kMinFramesPastPadStart) {
      break;
    }
    if (cur >= kMaxWaitFrames) {
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  int64_t target_frame = engine_->SnapshotMetrics().continuous_frames_emitted_total + 10;
  if (pad_start >= 0) {
    target_frame = std::max(target_frame, pad_start + kMinFramesPastPadStart);
  }
  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), target_frame);
  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  std::vector<SegmentSwapTickRecord> records = SnapshotTickRecords();

  ASSERT_GE(GetPadSegmentStartTick(), 0)
      << "Segment 2 (PAD) must have started (on_segment_start to_seg=2)";

  const int64_t pad_start_tick = GetPadSegmentStartTick();
  const int64_t pad_window_ticks = 60;
  std::vector<SegmentSwapTickRecord> pad_ticks;
  for (const auto& r : records) {
    if (r.tick_index >= pad_start_tick &&
        r.tick_index < pad_start_tick + pad_window_ticks) {
      pad_ticks.push_back(r);
    }
  }

  int warning_count = 0;
  int a_src_null_count = 0;
  size_t first_warning_idx = pad_ticks.size();
  for (size_t i = 0; i < pad_ticks.size(); i++) {
    if (pad_ticks[i].fence_audio_pad_warning_delta) {
      warning_count++;
      if (first_warning_idx > i) first_warning_idx = i;
    }
    if (pad_ticks[i].a_src_is_null) {
      a_src_null_count++;
      if (first_warning_idx > i) first_warning_idx = i;
    }
  }

  if (m.fence_audio_pad_warning_count != 0 || a_src_null_count != 0) {
    printf("\nSegmentSwapPadFence REPRODUCED: fence_audio_pad_warning_count=%" PRId64
           " a_src_null_during_pad_segment=%d\n",
           m.fence_audio_pad_warning_count, a_src_null_count);
    size_t start = (first_warning_idx >= 8) ? first_warning_idx - 8 : 0;
    int show = 15;
    for (size_t j = start; j < pad_ticks.size() && show > 0; j++, show--) {
      const auto& t = pad_ticks[j];
      printf("  tick=%" PRId64 " slot=%c decision=%s a_src_is_null=%d warning_delta=%d\n",
             t.tick_index, t.slot, t.decision.c_str(), t.a_src_is_null ? 1 : 0,
             t.fence_audio_pad_warning_delta);
    }
  }

  // INV-PAD-SEAM-AUDIO-READY: PAD segment must never hit FENCE_AUDIO_PAD and
  // a_src must never be null during the PAD segment window.
  EXPECT_EQ(m.fence_audio_pad_warning_count, 0)
      << "INV-PAD-SEAM-AUDIO-READY: No FENCE_AUDIO_PAD during segment-swap-to-PAD";
  EXPECT_EQ(a_src_null_count, 0)
      << "INV-PAD-SEAM-AUDIO-READY: a_src must never be null during PAD segment ticks";
}

// =============================================================================
// Cadence after PAD seam: RefreshFrameSelectionCadenceFromLiveSource must never
// report new_source_fps=1/1 for PAD/synthetic; we sanitize to output_fps so mode=DISABLED.
// =============================================================================
TEST_F(PipelineManagerSegmentSwapPadFenceTest, PadSeamCadenceRefresh_NewFpsEqualsOutput_ModeDisabled) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 1500;
  const int64_t seg1_ms = 1500;
  const int64_t seg2_pad_ms = 3000;
  int64_t now = NowMs();

  FedBlock block = MakeContentContentPadBlock(
      "segswap-cadence", now, seg0_ms, seg1_ms, seg2_pad_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngineWithObservability();
  engine_->Start();

  // Run until we have at least one cadence refresh (emitted when we sanitize at PAD seam)
  // and we're past the PAD segment start.
  const int64_t kMaxFrames = 200;
  for (int i = 0; i < 300; i++) {
    auto refreshes = SnapshotCadenceRefreshes();
    if (refreshes.size() >= 1u && GetPadSegmentStartTick() >= 0) break;
    if (engine_->SnapshotMetrics().continuous_frames_emitted_total >= kMaxFrames) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), kMaxFrames);
  engine_->Stop();

  std::vector<CadenceRefreshRecord> refreshes = SnapshotCadenceRefreshes();
  ASSERT_GE(GetPadSegmentStartTick(), 0) << "PAD segment must have started (segment 2)";
  ASSERT_GE(refreshes.size(), 1u)
      << "Need at least one cadence refresh (emitted at PAD seam when we sanitize 1/1 to output_fps)";

  const RationalFps output_fps = ctx_->fps;

  // No cadence refresh must report new_source_fps == 1/1 (bogus PAD/synthetic value).
  for (size_t i = 0; i < refreshes.size(); i++) {
    EXPECT_FALSE(refreshes[i].new_fps.num == 1 && refreshes[i].new_fps.den == 1)
        << "Cadence refresh " << i << " must not have new_source_fps=1/1 (PAD/synthetic sanitized)";
  }

  // The last refresh after we've entered PAD is the one for the PAD seam (sanitized to output_fps).
  const CadenceRefreshRecord& pad_seam_refresh = refreshes.back();
  EXPECT_EQ(pad_seam_refresh.new_fps.num, output_fps.num)
      << "After PAD seam, new_source_fps must equal output_fps (num)";
  EXPECT_EQ(pad_seam_refresh.new_fps.den, output_fps.den)
      << "After PAD seam, new_source_fps must equal output_fps (den)";
  EXPECT_EQ(pad_seam_refresh.mode, "DISABLED")
      << "After PAD seam, cadence mode must be DISABLED (PAD already in house timebase)";

  // old_source_fps at PAD seam must not be 1/1 (it should be the previous segment's rate or output).
  EXPECT_FALSE(pad_seam_refresh.old_fps.num == 1 && pad_seam_refresh.old_fps.den == 1)
      << "After PAD seam, old_source_fps must not be 1/1";
}

// =============================================================================
// Post-swap seam rebase contract: next_seam_frame_ must be strictly > swap tick.
// Reproduces the 60fps commercial black-frame bug: stale planned_segment_seam_frames_
// after swap caused immediate re-take and catch-up thrash. After rebase, the
// next seam is session_frame_index + seg_frames (capped by block fence), so
// the segment stays on air for its duration.
// =============================================================================
TEST_F(PipelineManagerSegmentSwapPadFenceTest, PostSwapNextSeamFrameStrictlyAfterTick) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 1500;
  const int64_t seg1_ms = 1500;
  const int64_t seg2_pad_ms = 3000;
  int64_t now = NowMs();

  FedBlock block = MakeContentContentPadBlock(
      "segswap-rebase", now, seg0_ms, seg1_ms, seg2_pad_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngineWithObservability();
  engine_->Start();

  // Run until we have at least two segment seam takes (0→1 and 1→2), or enough frames.
  const int64_t kMaxFrames = 200;
  for (int i = 0; i < 300; i++) {
    auto records = SnapshotSegmentSeamTakeRecords();
    if (records.size() >= 2u) break;
    if (engine_->SnapshotMetrics().continuous_frames_emitted_total >= kMaxFrames) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), kMaxFrames);
  engine_->Stop();

  std::vector<SegmentSeamTakeRecord> records = SnapshotSegmentSeamTakeRecords();

  // After every PerformSegmentSwap(), next_seam_frame_ must be strictly > session_frame_index.
  for (size_t i = 0; i < records.size(); i++) {
    EXPECT_GT(records[i].next_seam_frame, records[i].tick)
        << "Post-swap rebase: next_seam_frame must be > tick (record " << i
        << " tick=" << records[i].tick << " next_seam_frame=" << records[i].next_seam_frame << ")";
  }

  // No immediate re-take: consecutive segment seam take ticks must not be adjacent.
  for (size_t i = 1; i < records.size(); i++) {
    int64_t delta = records[i].tick - records[i - 1].tick;
    EXPECT_GE(delta, 2)
        << "No seam thrash: consecutive segment swaps at tick " << records[i - 1].tick
        << " and " << records[i].tick << " (delta=" << delta << ")";
  }
}

// =============================================================================
// Delayed swap: next seam must be derived from swap tick + segment duration,
// not from the original plan (planned_segment_seam_frames_). When the swap
// happens later than the planned boundary (e.g. B not ready), rebase ensures
// the segment stays on air for its full duration.
// =============================================================================
TEST_F(PipelineManagerSegmentSwapPadFenceTest, DelayedSwapSeamDerivedFromSwapTick) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 1500;
  const int64_t seg1_ms = 1500;
  const int64_t seg2_pad_ms = 3000;
  int64_t now = NowMs();

  FedBlock block = MakeContentContentPadBlock(
      "segswap-delayed", now, seg0_ms, seg1_ms, seg2_pad_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngineWithObservability();
  engine_->Start();

  const int64_t kMaxFrames = 200;
  for (int i = 0; i < 300; i++) {
    auto records = SnapshotSegmentSeamTakeRecords();
    if (records.size() >= 2u) break;
    if (engine_->SnapshotMetrics().continuous_frames_emitted_total >= kMaxFrames) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), kMaxFrames);
  engine_->Stop();

  std::vector<SegmentSeamTakeRecord> records = SnapshotSegmentSeamTakeRecords();
  ASSERT_GE(records.size(), 2u) << "Need at least two segment seam takes (0→1 and 1→2)";

  // Session FPS (same as block plan).
  const int64_t seg1_frames = ctx_->fps.FramesFromDurationCeilMs(seg1_ms);
  const int64_t seg2_frames = ctx_->fps.FramesFromDurationCeilMs(seg2_pad_ms);

  // First seam take: swapped to segment 1 (duration seg1_ms). Next seam must be swap_tick + seg1_frames, not the planned boundary.
  EXPECT_EQ(records[0].next_seam_frame, records[0].tick + seg1_frames)
      << "Seam after first swap must be derived from swap tick, not plan: "
      << "tick=" << records[0].tick << " next_seam_frame=" << records[0].next_seam_frame
      << " expected=" << (records[0].tick + seg1_frames);

  // Second seam take: swapped to segment 2 (duration seg2_pad_ms). Next seam must be derived from swap tick (tick + seg2_frames), possibly capped by block fence.
  EXPECT_GE(records[1].next_seam_frame, records[1].tick + 1)
      << "Seam after second swap must be strictly after tick";
  EXPECT_LE(records[1].next_seam_frame, records[1].tick + seg2_frames)
      << "Seam after second swap must be derived from swap tick + segment duration (or block fence), not plan";
}

// =============================================================================
// 0ms duration segment: next_seam_frame must still be > tick (dwell policy).
// Ensures we never allow tick+0 seams; MIN_DWELL or block fence applies.
// =============================================================================
TEST_F(PipelineManagerSegmentSwapPadFenceTest, ZeroMsSegmentNextSeamStrictlyAfterTick) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  // Block: content 1500ms, content 0ms (simulated missing duration), pad 3000ms.
  const int64_t seg0_ms = 1500;
  const int64_t seg1_ms = 0;   // 0ms duration — must not produce next_seam_frame <= tick
  const int64_t seg2_pad_ms = 3000;
  int64_t now = NowMs();

  FedBlock block = MakeContentContentPadBlock(
      "zero-ms-seg", now, seg0_ms, seg1_ms, seg2_pad_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngineWithObservability();
  engine_->Start();

  const int64_t kMaxFrames = 250;
  for (int i = 0; i < 350; i++) {
    auto records = SnapshotSegmentSeamTakeRecords();
    if (records.size() >= 2u) break;
    if (engine_->SnapshotMetrics().continuous_frames_emitted_total >= kMaxFrames) break;
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  retrovue::blockplan::test_utils::AdvanceUntilFenceOrFail(engine_.get(), kMaxFrames);
  engine_->Stop();

  std::vector<SegmentSeamTakeRecord> records = SnapshotSegmentSeamTakeRecords();

  // Every seam take: next_seam_frame must be strictly > tick (no past seam / no thrash).
  for (size_t i = 0; i < records.size(); i++) {
    EXPECT_GT(records[i].next_seam_frame, records[i].tick)
        << "0ms segment test: next_seam_frame must be > tick (record " << i
        << " tick=" << records[i].tick << " next_seam_frame=" << records[i].next_seam_frame << ")";
  }

  // No immediate re-take thrash: consecutive seam take ticks advance by >= 2 frames,
  // unless the block fence ends the block (last record may be block boundary).
  for (size_t i = 1; i < records.size(); i++) {
    int64_t delta = records[i].tick - records[i - 1].tick;
    EXPECT_GE(delta, 2)
        << "No seam thrash: consecutive segment swaps at tick " << records[i - 1].tick
        << " and " << records[i].tick << " (delta=" << delta << ")";
  }
}

}  // namespace
}  // namespace retrovue::blockplan::testing
