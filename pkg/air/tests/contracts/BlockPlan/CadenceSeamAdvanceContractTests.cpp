// Repository: Retrovue-playout
// Component: INV-CADENCE-SEAM-ADVANCE-001 Contract Test
// Purpose: Prove that cadence repeat does not override v_src=incoming when the
//          incoming segment is eligible for swap at a segment seam tick.
//
//          TRIGGER: When source_fps != output_fps, the frame-selection cadence
//          marks some ticks as "repeat" (re-encode last_good_video_frame_).
//          At a segment seam, the incoming segment may become eligible while the
//          cadence (still tuned to the OUTGOING segment's fps) says "repeat."
//          The repeat path uses last_good_video_frame_ from the outgoing segment
//          instead of popping from the incoming buffer — freezing on the outgoing
//          segment's last frame for one extra tick.
//
//          BUG (before fix): Cadence repeat fires BEFORE the advance path in the
//          cascade.  When is_cadence_repeat is true, chosen_video = last_good_
//          video_frame_ regardless of v_src.  The swap defers because the emitted
//          frame originates from the outgoing segment (frame_origin_gate).
//
//          FIX: When take_segment && v_src==incoming && eligible, suppress
//          cadence repeat for that tick.
//
// Contract: docs/contracts/invariants/air/INV-CADENCE-SEAM-ADVANCE-001.md
// Related:  INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001
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

// Build a two-CONTENT-segment block.  Both segments use 30fps assets.
// Output is 60fps (FPS_5994), so the frame-selection cadence is ACTIVE
// with increment = 30030000 and den = 60060000: every other tick is a
// repeat (50% repeat rate).  This guarantees at least one repeat tick
// during the segment swap deferral window.
static FedBlock MakeTwoSegmentBlock(const std::string& block_id,
                                    int64_t start_utc_ms,
                                    int64_t seg0_ms,
                                    int64_t seg1_ms) {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = start_utc_ms;
  block.end_utc_ms = start_utc_ms + seg0_ms + seg1_ms;

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

  return block;
}

// Parsed seam tick observation for a single tick.
struct SeamTickObs {
  int64_t tick = -1;
  bool v_src_incoming = false;
  bool eligible = false;
  bool cadence_repeat = false;
  char decision = '?';  // 'A'=advance, 'R'=repeat, 'H'=hold, 'P'=pad
};

class CadenceSeamAdvanceTest : public ::testing::Test {
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
    // 60fps output with 30fps assets → cadence ACTIVE, 50% repeat rate.
    ctx_->fps = FPS_5994;
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
    callbacks.on_block_completed = [](const FedBlock&, int64_t, int64_t) {};
    callbacks.on_session_ended = [](const std::string&, int64_t) {};
    callbacks.on_segment_start = [this](int32_t, int32_t to_seg,
                                        const FedBlock& block, int64_t tick) {
      std::lock_guard<std::mutex> lock(seg_mutex_);
      segment_starts_.push_back({to_seg, tick});
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks), test_ts_,
        test_infra::MakeTestOutputClock(ctx_->fps.num, ctx_->fps.den, test_ts_),
        PipelineManagerOptions{0});
  }

  int64_t NowMs() { return test_ts_->NowUtcMs(); }

  // Wait until segment 1 has started (on_segment_start fires with to_seg=1).
  bool WaitForSegment1Start(int timeout_ms) {
    auto deadline = std::chrono::steady_clock::now() +
                    std::chrono::milliseconds(timeout_ms);
    for (;;) {
      {
        std::lock_guard<std::mutex> lock(seg_mutex_);
        for (const auto& [seg, tick] : segment_starts_) {
          if (seg == 1) return true;
        }
      }
      if (std::chrono::steady_clock::now() >= deadline) return false;
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
  }

  // Extract per-tick seam observations by correlating SEAM_VSRC_GATE and
  // SEAM_TICK_EMISSION_AUDIT log lines.
  std::vector<SeamTickObs> ExtractSeamTickObservations() const {
    std::lock_guard<std::mutex> lock(log_mutex_);
    // Phase 1: collect VSRC_GATE data keyed by tick.
    struct VsrcData { bool incoming = false; bool eligible = false; };
    std::map<int64_t, VsrcData> vsrc_map;
    for (const auto& line : captured_logs_) {
      if (line.find("SEAM_VSRC_GATE") == std::string::npos) continue;
      auto extract_int = [&](const std::string& key) -> int64_t {
        auto pos = line.find(key);
        if (pos == std::string::npos) return -1;
        return std::stoll(line.substr(pos + key.size()));
      };
      int64_t tick = extract_int("tick=");
      VsrcData d;
      d.incoming = (line.find("v_src=incoming") != std::string::npos);
      d.eligible = (line.find("eligible=true") != std::string::npos);
      vsrc_map[tick] = d;
    }
    // Phase 2: collect EMISSION_AUDIT data and merge.
    std::vector<SeamTickObs> result;
    for (const auto& line : captured_logs_) {
      if (line.find("SEAM_TICK_EMISSION_AUDIT") == std::string::npos) continue;
      auto extract_int = [&](const std::string& key) -> int64_t {
        auto pos = line.find(key);
        if (pos == std::string::npos) return -1;
        return std::stoll(line.substr(pos + key.size()));
      };
      int64_t tick = extract_int("tick=");
      SeamTickObs obs;
      obs.tick = tick;
      // Parse decision character (single char after "decision=").
      auto dpos = line.find("decision=");
      if (dpos != std::string::npos && dpos + 9 < line.size()) {
        obs.decision = line[dpos + 9];
      }
      obs.cadence_repeat = (extract_int("cadence_repeat=") == 1);
      // Merge VSRC_GATE data.
      auto it = vsrc_map.find(tick);
      if (it != vsrc_map.end()) {
        obs.v_src_incoming = it->second.incoming;
        obs.eligible = it->second.eligible;
      }
      result.push_back(obs);
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

  mutable std::mutex seg_mutex_;
  std::vector<std::pair<int32_t, int64_t>> segment_starts_;
};

// ===========================================================================
// INV-CADENCE-SEAM-ADVANCE-001
//
// Block: [CONTENT(5000ms, SampleA 30fps), CONTENT(5000ms, SampleB 30fps)]
// Output: 60fps (FPS_5994) → cadence ACTIVE with 50% repeat rate.
//
// At the segment 0→1 seam tick:
//   Segment B is created and begins filling.
//   The 500ms audio threshold causes deferral for several ticks.
//   With 50% cadence repeat rate, at least one deferral tick where
//   B is eligible will coincide with a cadence repeat tick.
//
// BUG (before fix):
//   cadence_repeat=1 → decision=R → last_good_video_frame_ (outgoing)
//   v_src=incoming is ignored; swap defers (frame_origin_gate).
//
// FIX:
//   When take_segment && v_src==incoming && eligible, suppress cadence
//   repeat → decision=A → TryPopFrame from incoming → swap commits.
//
// Assertion: No tick has (v_src=incoming, eligible=true, cadence_repeat=1,
//            decision=R).
// ===========================================================================

TEST_F(CadenceSeamAdvanceTest, CadenceRepeatMustNotOverrideEligibleIncomingSource) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 5000;
  const int64_t seg1_ms = 5000;
  int64_t now = NowMs();

  FedBlock block = MakeTwoSegmentBlock(
      "cadence-seam-advance", now, seg0_ms, seg1_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait for segment 1 to start (swap committed).
  const int timeout_ms = 15000;
  bool seg1_started = WaitForSegment1Start(timeout_ms);
  ASSERT_TRUE(seg1_started) << "Segment 1 did not start within " << timeout_ms << "ms";

  engine_->Stop();

  // Extract seam tick observations and check the invariant.
  auto observations = ExtractSeamTickObservations();

  // Find any tick violating INV-CADENCE-SEAM-ADVANCE-001:
  // v_src=incoming AND eligible=true AND cadence_repeat=1 AND decision=R
  std::vector<SeamTickObs> violations;
  bool saw_eligible_incoming = false;
  for (const auto& obs : observations) {
    if (obs.v_src_incoming && obs.eligible) {
      saw_eligible_incoming = true;
      if (obs.cadence_repeat && obs.decision == 'R') {
        violations.push_back(obs);
      }
    }
  }

  // Diagnostic: must have seen at least one tick with v_src=incoming eligible=true
  // to confirm the test exercised the seam deferral path.
  if (!saw_eligible_incoming) {
    // If no eligible incoming tick was observed, the cadence may have been
    // disabled (fps match) or the deferral window was too short.
    // Log all observations for diagnosis.
    std::ostringstream diag;
    diag << "No eligible incoming tick observed. Observations:\n";
    for (const auto& obs : observations) {
      diag << "  tick=" << obs.tick
           << " v_src_incoming=" << obs.v_src_incoming
           << " eligible=" << obs.eligible
           << " cadence_repeat=" << obs.cadence_repeat
           << " decision=" << obs.decision << "\n";
    }
    ADD_FAILURE() << "Test precondition not met: no eligible incoming seam tick "
                  << "observed (cadence may not be active or deferral was skipped).\n"
                  << diag.str();
    return;
  }

  // Primary assertion: no cadence repeat on eligible incoming ticks.
  if (!violations.empty()) {
    std::ostringstream diag;
    diag << "INV-CADENCE-SEAM-ADVANCE-001 VIOLATED.\n"
         << violations.size() << " tick(s) where cadence repeat overrode "
         << "eligible incoming source:\n";
    for (const auto& v : violations) {
      diag << "  tick=" << v.tick
           << " v_src_incoming=" << v.v_src_incoming
           << " eligible=" << v.eligible
           << " cadence_repeat=" << v.cadence_repeat
           << " decision=" << v.decision << "\n";
    }
    diag << "Cadence repeat prevented TryPopFrame on incoming buffer.\n"
         << "The emitted frame originated from the outgoing segment.";
    ADD_FAILURE() << diag.str();
  }

  EXPECT_TRUE(violations.empty())
      << "Cadence repeat must not override eligible incoming source at seam.";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
