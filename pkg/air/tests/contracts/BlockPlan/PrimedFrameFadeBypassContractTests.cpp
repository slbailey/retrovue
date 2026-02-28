// Repository: Retrovue-playout
// Component: INV-TRANSITION-004 Contract Test (Primed Frame Fade Bypass)
// Purpose: Prove that the first frame after a PAD→CONTENT seam with transition_in=kFade
//          respects the fade-in alpha. The primed frame (decoded in PrimeFirstFrame) must
//          go through the same fade/transition postprocessing as frames decoded via
//          DecodeNextFrameRaw. If it does not, the viewer sees a single full-brightness
//          frame followed by a fade-from-black — a visible anomaly.
//
// Hypothesis under test (Class 1):
//   PrimeFirstFrame() does not apply INV-TRANSITION-004 fade logic.
//   DecodeNextFrameRaw() does. The primed frame enters the buffer un-faded.
//   At the content seam override, the first popped frame is full-brightness.
//
// Test method:
//   Build a [CONTENT(1500ms), PAD(500ms), CONTENT(1500ms, fade_in=500ms)] block.
//   Capture PRIME_FADE_AUDIT and DECODE_FADE_AUDIT log lines from TickProducer.
//   Assert: for the segment-2 TickProducer, PRIME_FADE_AUDIT shows
//           fade_configured=1 AND fade_actually_applied=false.
//   Assert: DECODE_FADE_AUDIT for frame_index=1 shows alpha_q16 < 65536
//           AND fade_actually_applied=true.
//   This proves the primed frame bypasses fade while subsequent frames do not.
//
// Before fix: RED (primed frame has fade_actually_applied=false despite fade_configured=1)
// After fix:  GREEN (primed frame has fade_actually_applied=true)
//
// Contract: docs/contracts/invariants/air/INV-TRANSITION-004 (segment transition fade)
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

// Build a [CONTENT, PAD, CONTENT] block where the final CONTENT segment
// has transition_in = kFade.  This simulates a synthesized commercial
// breakpoint where the return-from-commercial uses a fade-in.
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

class PrimedFrameFadeBypassTest : public ::testing::Test {
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

    // Capture ALL log lines (info + error) for instrumentation analysis.
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

  // Find log lines matching a pattern.
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

  // Extract a boolean value from a log line of form "key=0" or "key=1" or "key=true/false".
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
// INV-TRANSITION-004: Primed frame must respect fade-in at PAD→CONTENT seam
//
// Block: [CONTENT(1500ms), PAD(500ms), CONTENT(1500ms, fade_in=500ms)]
//
// The second CONTENT segment (segment 2) has transition_in = kFade with 500ms
// duration. When SeamPreparer creates the TickProducer for segment 2 and calls
// PrimeFirstTick → PrimeFirstFrame, the primed frame should have fade applied
// (alpha_q16 = 0 at seg_ct = 0, i.e., fully black at the very start of the
// fade-in ramp).
//
// This test captures PRIME_FADE_AUDIT and DECODE_FADE_AUDIT log lines to
// determine whether the primed frame and subsequent frames are fade-processed.
//
// Before fix: RED (PRIME_FADE_AUDIT shows fade_actually_applied=false)
// After fix:  GREEN (PRIME_FADE_AUDIT shows fade_actually_applied=true)
// ===========================================================================

TEST_F(PrimedFrameFadeBypassTest,
       FirstFrameAfterPadToContentSeamMustRespectFadeIn) {
  if (!FileExists(kPathA) || !FileExists(kPathB)) {
    GTEST_SKIP() << "Assets not found: " << kPathA << ", " << kPathB;
  }

  const int64_t seg0_ms = 1500;   // CONTENT
  const int64_t seg1_ms = 500;    // PAD (commercial)
  const int64_t seg2_ms = 1500;   // CONTENT with fade-in
  const uint32_t fade_in_ms = 500;
  int64_t now = NowMs();

  FedBlock block = MakeContentPadContentFadeBlock(
      "primed-fade-bypass", now, seg0_ms, seg1_ms, seg2_ms, fade_in_ms);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Wait until segment 2 has started and run a few more frames.
  const int64_t kMaxFrames = 250;
  bool seg2_started = WaitForSegment2Start(kMaxFrames);
  ASSERT_TRUE(seg2_started)
      << "Segment 2 never started within frame ceiling.";

  // Advance past segment 2 start to let instrumentation logs flush.
  {
    int64_t cur = engine_->SnapshotMetrics().continuous_frames_emitted_total;
    test_utils::AdvanceUntilFence(engine_.get(), cur + 30);
  }

  engine_->Stop();

  // ===== ANALYSIS: Extract instrumentation logs =====

  // 1. Find PRIME_FADE_AUDIT lines — there should be at least one where
  //    fade_configured=1 (from the segment 2 TickProducer in SeamPreparer).
  auto prime_audits = FindLogs("PRIME_FADE_AUDIT");
  ASSERT_FALSE(prime_audits.empty())
      << "No PRIME_FADE_AUDIT logs found — instrumentation not reached.";

  // Find the one where fade_configured=1 (segment 2's primed frame).
  std::string fade_prime_line;
  for (const auto& line : prime_audits) {
    if (ExtractBoolField(line, "fade_configured")) {
      fade_prime_line = line;
      break;
    }
  }
  ASSERT_FALSE(fade_prime_line.empty())
      << "No PRIME_FADE_AUDIT with fade_configured=1 found.\n"
      << "This means segment 2 was not assigned transition_in=kFade.\n"
      << "All PRIME_FADE_AUDIT lines:\n"
      << [&] {
           std::string s;
           for (const auto& l : prime_audits) s += "  " + l + "\n";
           return s;
         }();

  // The primed frame's computed alpha should be 0 (fully transparent at seg_ct=0).
  int64_t prime_alpha = ExtractField(fade_prime_line, "computed_alpha_q16");
  bool prime_fade_applied = ExtractBoolField(fade_prime_line, "fade_actually_applied");

  // KEY ASSERTION: The primed frame should have fade ACTUALLY applied.
  // Before fix: fade_actually_applied=false (Class 1 confirmed — RED).
  // After fix:  fade_actually_applied=true (GREEN).
  EXPECT_TRUE(prime_fade_applied)
      << "INV-TRANSITION-004 VIOLATED: Primed frame bypasses fade-in.\n"
      << "fade_configured=true but fade_actually_applied=false.\n"
      << "computed_alpha_q16=" << prime_alpha << " (should be 0 at seg_ct=0).\n"
      << "This causes a single full-brightness frame before the fade-in ramp.\n"
      << "PRIME_FADE_AUDIT line: " << fade_prime_line;

  // 2. Find DECODE_FADE_AUDIT lines for frame_index=1 — these should show
  //    fade IS applied (proving DecodeNextFrameRaw has the logic).
  auto decode_audits = FindLogs("DECODE_FADE_AUDIT");
  // There should be at least one from the segment 2 fill thread.
  bool found_frame1_with_fade = false;
  for (const auto& line : decode_audits) {
    int64_t fidx = ExtractField(line, "frame_index");
    bool applied = ExtractBoolField(line, "fade_actually_applied");
    int64_t alpha = ExtractField(line, "alpha_q16");
    if (fidx >= 1 && applied && alpha < 65536) {
      found_frame1_with_fade = true;
      break;
    }
  }
  // This is a supporting assertion — if DecodeNextFrameRaw applies fade
  // but PrimeFirstFrame does not, Class 1 is proven.
  if (!decode_audits.empty()) {
    EXPECT_TRUE(found_frame1_with_fade)
        << "Expected at least one DECODE_FADE_AUDIT with fade applied.\n"
        << "If this fails, the fade transition may not be configured at all.";
  }

  // 3. Check CONTENT_SEAM_FRAME_FADE_AUDIT — the emitted frame at seam tick.
  auto seam_audits = FindLogs("CONTENT_SEAM_FRAME_FADE_AUDIT");
  if (!seam_audits.empty()) {
    // Log for diagnostics.
    std::cout << "[TEST] CONTENT_SEAM_FRAME_FADE_AUDIT: " << seam_audits[0] << std::endl;
  }

  // 4. Check PRIMED_FRAME_PUSH — provenance of the buffer's first frame.
  auto push_audits = FindLogs("PRIMED_FRAME_PUSH");
  for (const auto& line : push_audits) {
    if (line.find("SEGMENT_B_VIDEO_BUFFER") != std::string::npos) {
      std::cout << "[TEST] SEGMENT_B PRIMED_FRAME_PUSH: " << line << std::endl;
    }
  }

  // ===== DIAGNOSTIC OUTPUT =====
  std::cout << "\n===== INSTRUMENTATION LOG SUMMARY =====\n";
  std::cout << "PRIME_FADE_AUDIT lines: " << prime_audits.size() << "\n";
  for (const auto& l : prime_audits)
    std::cout << "  " << l << "\n";
  std::cout << "DECODE_FADE_AUDIT lines: " << decode_audits.size() << "\n";
  for (size_t i = 0; i < std::min(decode_audits.size(), static_cast<size_t>(10)); i++)
    std::cout << "  " << decode_audits[i] << "\n";
  std::cout << "CONTENT_SEAM_FRAME_FADE_AUDIT lines: " << seam_audits.size() << "\n";
  for (const auto& l : seam_audits)
    std::cout << "  " << l << "\n";
  std::cout << "PRIMED_FRAME_PUSH lines: " << push_audits.size() << "\n";
  for (const auto& l : push_audits)
    std::cout << "  " << l << "\n";
  std::cout << "========================================\n\n";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
