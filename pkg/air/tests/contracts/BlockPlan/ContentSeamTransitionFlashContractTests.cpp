// Repository: Retrovue-playout
// Component: INV-TRANSITION-005 Contract Test (Content Seam Transition Flash)
// Purpose: Prove that the frame emitted at a PAD→CONTENT seam tick with
//          transition_in=kFade respects ADR-014's first-frame obligation:
//          alpha(0) = 0, meaning the emitted frame must be black.
//
// Defect under test:
//   When SeamPreparer has not finished preparing segment B by the time the
//   PAD→CONTENT seam tick arrives, the frame-selection cascade falls to the
//   `take_segment && has_last_good_video_frame_` branch, emitting a stale
//   full-brightness frame from the pre-PAD content segment. This violates
//   ADR-014: at seg_ct=0 with fade-in, alpha must be 0 (fully attenuated).
//
// Test method:
//   Build a [CONTENT, PAD, CONTENT(fade_in=1000ms)] block. In FAST_TEST mode,
//   the tick loop advances virtual time without sleeping, while SeamPreparer
//   requires real wall time for file I/O. This creates a deterministic race:
//   at the PAD→CONTENT seam tick, SeamPreparer has not finished, segment B
//   does not exist, and the cascade falls through to the stale frame.
//
//   Capture SEAM_TICK_EMISSION_AUDIT log at the PAD→CONTENT seam tick.
//   Assert: y_plane_mean <= BLACK_THRESHOLD (consistent with alpha=0).
//
// Before fix: RED (y_plane_mean >> BLACK_THRESHOLD — stale full-brightness frame)
// After fix:  GREEN (y_plane_mean <= BLACK_THRESHOLD — pad or properly faded frame)
//
// Contract: ADR-014 (Transition Application Model), Section "First-Frame Obligation"
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

// Y-plane mean threshold for "black". Content frames have Y_mean >> 40.
// Pad frames use MPEG-range black (Y=16 in BT.601/BT.709), not full-range (Y=0).
// Faded frames at alpha=0 also produce Y=16 (or near it after scaling).
// Threshold of 20 accepts broadcast black but rejects any visible content.
static constexpr int64_t kBlackThreshold = 20;

// Build a [CONTENT, PAD, CONTENT(fade_in)] block.
// Simulates a commercial break (content → pad → return with fade-in).
static FedBlock MakeContentPadContentFadeBlock(const std::string& block_id,
                                                int64_t start_utc_ms,
                                                int64_t seg0_content_ms,
                                                int64_t seg1_pad_ms,
                                                int64_t seg2_content_ms,
                                                uint32_t seg2_fade_in_ms) {
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
  s2.transition_in = TransitionType::kFade;
  s2.transition_in_duration_ms = seg2_fade_in_ms;
  block.segments.push_back(s2);

  return block;
}

class ContentSeamTransitionFlashTest : public ::testing::Test {
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

    // Capture ALL log lines for instrumentation analysis.
    captured_logs_.clear();
    captured_errors_.clear();
    Logger::SetInfoSink([this](const std::string& line) {
      std::lock_guard<std::mutex> lock(log_mutex_);
      captured_logs_.push_back(line);
    });
    Logger::SetErrorSink([this](const std::string& line) {
      std::lock_guard<std::mutex> lock(log_mutex_);
      captured_errors_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetInfoSink(nullptr);
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

  // Wait until segment 2 starts (on_segment_start callback fires for to_seg=2).
  // Returns true if segment 2 started; false if max_frames exceeded or timeout.
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

  // Find log lines matching a substring.
  std::vector<std::string> FindLogs(const std::string& pattern) const {
    std::lock_guard<std::mutex> lock(log_mutex_);
    std::vector<std::string> results;
    for (const auto& line : captured_logs_) {
      if (line.find(pattern) != std::string::npos) {
        results.push_back(line);
      }
    }
    return results;
  }

  // Extract a numeric value from a log line of form "key=value".
  static int64_t ExtractField(const std::string& line, const std::string& key) {
    auto pos = line.find(key + "=");
    if (pos == std::string::npos) return -999;
    pos += key.size() + 1;
    return std::stoll(line.substr(pos));
  }

  // Extract a boolean field (0/1 or true/false).
  static bool ExtractBoolField(const std::string& line, const std::string& key) {
    auto pos = line.find(key + "=");
    if (pos == std::string::npos) return false;
    pos += key.size() + 1;
    char c = line[pos];
    return (c == '1' || c == 't');
  }

  std::shared_ptr<test_infra::TestTimeSourceType> test_ts_;
  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  mutable std::mutex log_mutex_;
  std::vector<std::string> captured_logs_;
  std::vector<std::string> captured_errors_;

  mutable std::mutex seg_mutex_;
  std::vector<std::pair<int32_t, int64_t>> segment_start_ticks_;
};

// ===========================================================================
// INV-TRANSITION-005: PAD→CONTENT seam tick must emit black when fade-in
//
// Block: [CONTENT(1500ms), PAD(500ms), CONTENT(1500ms, fade_in=1000ms)]
//
// ADR-014 first-frame obligation: at seg_ct=0 with transition_in=Fade(D>0),
// alpha(0) = 0. The emitted frame must be fully attenuated (black video).
//
// To reproduce the defect deterministically, we inject a delay into
// SeamPreparer via SetPreloaderDelayHook. This ensures SeamPreparer has
// NOT finished by the time the PAD→CONTENT seam tick arrives. At that tick:
//   - content_seam_override is attempted (active segment is PAD, a_depth=0)
//   - EnsureIncomingBReadyForSeam finds SeamPreparer not ready
//   - segment_b_video_buffer_ remains null
//   - Cascade falls to: take_segment && has_last_good_video_frame_
//   - Emits last_good_video_frame_ = stale pre-PAD content (full brightness)
//
// This violates ADR-014. The emitted frame has y_plane_mean >> 0.
//
// The SEAM_TICK_EMISSION_AUDIT log captures the chosen frame's y_plane_mean
// at the seam tick. The test asserts this value is within black threshold.
//
// Before fix: RED  (y_plane_mean >> kBlackThreshold — stale bright content)
// After fix:  GREEN (y_plane_mean <= kBlackThreshold — pad/attenuated frame)
// ===========================================================================

TEST_F(ContentSeamTransitionFlashTest,
       PadToContentSeamTickMustEmitBlackWhenFadeInDeclared) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 1500;   // CONTENT (pre-commercial)
  const int64_t seg1_ms = 500;    // PAD (commercial break)
  const int64_t seg2_ms = 1500;   // CONTENT with fade-in (return from break)
  const uint32_t fade_in_ms = 1000;
  int64_t now = NowMs();

  FedBlock block = MakeContentPadContentFadeBlock(
      "seam-flash-test", now, seg0_ms, seg1_ms, seg2_ms, fade_in_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();

  // Inject SeamPreparer delay gated on the tick loop having already passed the
  // seam tick. A fixed-duration delay is unreliable because encoding overhead
  // means the tick loop takes ~2s of real wall time to reach tick 60.
  // Instead, the hook polls engine metrics until continuous_frames_emitted >= 65
  // (past the seam at frame 60), THEN releases.  This guarantees the seam tick
  // arrives while SeamPreparer is still blocked, forcing the cascade fallback.
  auto* engine_ptr = engine_.get();
  auto release_flag = std::make_shared<std::atomic<bool>>(false);
  engine_->SetPreloaderDelayHook(
      [engine_ptr, release_flag](const std::atomic<bool>& cancel) {
    constexpr int64_t kPastSeamFrame = 65;
    while (!cancel.load(std::memory_order_relaxed) &&
           !release_flag->load(std::memory_order_relaxed)) {
      int64_t emitted = engine_ptr->SnapshotMetrics().continuous_frames_emitted_total;
      if (emitted >= kPastSeamFrame) return;
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  });

  engine_->Start();

  // Wait until the tick loop has passed the seam tick (frame 65+).
  // The tick loop runs independently of SeamPreparer — no deadlock risk.
  test_utils::WaitForBounded(
      [&] {
        return engine_->SnapshotMetrics().continuous_frames_emitted_total >= 70;
      },
      100000, 10000);

  // Release the SeamPreparer delay so it can finish and segment 2 can start.
  release_flag->store(true);

  // Wait until segment 2 starts (SeamPreparer finishes, swap completes).
  const int64_t kMaxFrames = 500;
  bool seg2_started = WaitForSegment2Start(kMaxFrames);
  ASSERT_TRUE(seg2_started)
      << "Segment 2 never started within frame ceiling. "
      << "SeamPreparer may have failed or assets may be unreadable.";

  // Let a few more frames run for log flush.
  {
    int64_t cur = engine_->SnapshotMetrics().continuous_frames_emitted_total;
    test_utils::AdvanceUntilFence(engine_.get(), cur + 15);
  }

  engine_->Stop();

  // ===== ANALYSIS: Extract SEAM_TICK_EMISSION_AUDIT logs =====
  auto seam_audits = FindLogs("SEAM_TICK_EMISSION_AUDIT");
  ASSERT_FALSE(seam_audits.empty())
      << "No SEAM_TICK_EMISSION_AUDIT logs found — instrumentation not reached.\n"
      << "This means no segment seam tick occurred, which is unexpected for a "
      << "3-segment block.";

  // Find the audit log(s) where active_is_pad=1 (PAD→CONTENT transition).
  std::vector<std::string> pad_to_content_audits;
  for (const auto& line : seam_audits) {
    if (ExtractBoolField(line, "active_is_pad")) {
      pad_to_content_audits.push_back(line);
    }
  }
  ASSERT_FALSE(pad_to_content_audits.empty())
      << "No SEAM_TICK_EMISSION_AUDIT with active_is_pad=1 found.\n"
      << "The PAD→CONTENT seam tick was not instrumented.\n"
      << "All SEAM_TICK_EMISSION_AUDIT lines:\n"
      << [&] {
           std::string s;
           for (const auto& l : seam_audits) s += "  " + l + "\n";
           return s;
         }();

  // Use the FIRST PAD→CONTENT seam audit (the first tick at the seam boundary).
  const std::string& flash_tick_line = pad_to_content_audits[0];

  // Extract key fields for diagnosis.
  int64_t tick = ExtractField(flash_tick_line, "tick");
  int64_t y_plane_mean = ExtractField(flash_tick_line, "y_plane_mean");
  int64_t content_seam_override_fired = ExtractField(flash_tick_line, "content_seam_override_fired");
  int64_t segb_available = ExtractField(flash_tick_line, "segb_available");
  int64_t seam_preparer_has_result = ExtractField(flash_tick_line, "seam_preparer_has_result");
  int64_t transition_in_type = ExtractField(flash_tick_line, "transition_in_type");
  int64_t transition_in_duration_ms = ExtractField(flash_tick_line, "transition_in_duration_ms");
  char decision_char = 'X';
  {
    auto dpos = flash_tick_line.find("decision=");
    if (dpos != std::string::npos) decision_char = flash_tick_line[dpos + 9];
  }

  // ===== DIAGNOSTIC OUTPUT =====
  std::cout << "\n===== CONTENT SEAM TRANSITION FLASH AUDIT =====\n";
  std::cout << "Seam tick: " << tick << "\n";
  std::cout << "Decision: " << decision_char << "\n";
  std::cout << "y_plane_mean: " << y_plane_mean << "\n";
  std::cout << "content_seam_override_fired: " << content_seam_override_fired << "\n";
  std::cout << "segb_available: " << segb_available << "\n";
  std::cout << "seam_preparer_has_result: " << seam_preparer_has_result << "\n";
  std::cout << "transition_in_type: " << transition_in_type << "\n";
  std::cout << "transition_in_duration_ms: " << transition_in_duration_ms << "\n";
  std::cout << "Total PAD→CONTENT audit ticks: " << pad_to_content_audits.size() << "\n";
  for (size_t i = 0; i < std::min(pad_to_content_audits.size(), static_cast<size_t>(5)); i++) {
    std::cout << "  [" << i << "] " << pad_to_content_audits[i] << "\n";
  }
  std::cout << "================================================\n\n";

  // ===== KEY ASSERTION =====
  // ADR-014 first-frame obligation: alpha(0) = 0 for fade-in segments.
  // The emitted frame at the PAD→CONTENT seam tick MUST be black.
  //
  // If this assertion fails (y_plane_mean > kBlackThreshold), the cascade
  // emitted a stale full-brightness content frame instead of a black frame.
  // This is the visual flash defect described in ADR-014.
  //
  // Expected RED diagnosis:
  //   decision=H (Hold — last_good_video_frame_)
  //   content_seam_override_fired=0 (segment B not ready)
  //   y_plane_mean >> 5 (full-brightness stale content)
  //
  // Expected GREEN after fix:
  //   decision=P (Pad) or decision=A/B (from properly faded segment B)
  //   y_plane_mean <= 5 (black or near-black)
  EXPECT_LE(y_plane_mean, kBlackThreshold)
      << "INV-TRANSITION-005 VIOLATED: First frame at PAD→CONTENT seam is not black.\n"
      << "ADR-014 requires alpha(0) = 0 for fade-in segments, but the emitted\n"
      << "frame has y_plane_mean=" << y_plane_mean << " (threshold=" << kBlackThreshold << ").\n"
      << "decision=" << decision_char
      << " content_seam_override_fired=" << content_seam_override_fired
      << " segb_available=" << segb_available << "\n"
      << "This is the full-brightness flash defect at return-from-commercial.\n"
      << "SEAM_TICK_EMISSION_AUDIT: " << flash_tick_line;

  // Supporting assertion: verify the transition spec was correctly propagated.
  // transition_in_type=1 (kFade) and transition_in_duration_ms=1000.
  // If these are wrong, the defect is in Core's plan generation, not AIR's cascade.
  EXPECT_EQ(transition_in_type, static_cast<int64_t>(TransitionType::kFade))
      << "Transition spec not propagated: expected kFade, got " << transition_in_type;
  EXPECT_EQ(transition_in_duration_ms, static_cast<int64_t>(fade_in_ms))
      << "Transition duration not propagated: expected " << fade_in_ms
      << ", got " << transition_in_duration_ms;
}

}  // namespace
}  // namespace retrovue::blockplan::testing
