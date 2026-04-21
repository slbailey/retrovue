// AIR vNext — C2 end-to-end integration.
//
// System-proof that the multi-block execution pipeline works
// end-to-end, including:
//
//   1. Multi-block session (two blocks seeded + queued).
//   2. Inter-block seam execution.
//   3. PromoteActiveBlock at seam fire: cursor reset, active_block
//      swap, block_transitions_total increment.
//   4. Output continuity across the block boundary — validated at
//      wire level by ffprobe (video PTS strictly monotonic through
//      the seam; no encoder reopen visible in the stream).
//   5. Queue depth and transition counters match expectations at
//      key points.
//
// Plus one optional integration: retirement of a queued successor
// before its seam arms, verifying C2.5 composes with C2.4 — the
// inter-block seam never fires, queue-empty pad engages at the
// active block's final fence, session stays OnAir indefinitely.

#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "air_session.hpp"
#include "block.hpp"
#include "channel_canonical.hpp"
#include "seam_controller.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) return env;
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return AIR_VNEXT_SAMPLE_A_PATH;
#else
  return "";
#endif
}

ChannelCanonical TestCanonical() {
  ChannelCanonical c;
  c.video.width = 968;
  c.video.height = 720;
  c.video.frame_rate = {30000, 1001};
  c.video.pixel_format = PixelFormat::kYuv420p;
  c.audio.sample_rate = 48000;
  c.audio.channels = 2;
  return c;
}

Block MakeBlock(const std::string& id, const std::string& asset,
                int seg_count, int64_t start_utc_ms,
                int64_t seg_ms = 1000) {
  Block b;
  b.block_id = id;
  b.start_utc_ms = start_utc_ms;
  b.end_utc_ms = start_utc_ms + seg_count * seg_ms;
  b.canonical = TestCanonical();
  for (int i = 0; i < seg_count; ++i) {
    Segment s;
    s.segment_id = id + ":" + std::to_string(i);
    s.asset_uri = asset;
    s.asset_start_offset_ms = 0;
    s.duration_ms = seg_ms;
    s.segment_index = i;
    b.segments.push_back(s);
  }
  return b;
}

std::string RunFfprobe(const std::vector<std::string>& args) {
  std::string cmd = "ffprobe";
  for (const auto& a : args) cmd += " '" + a + "'";
  cmd += " 2>&1";
  std::string result;
  FILE* pipe = popen(cmd.c_str(), "r");
  if (!pipe) return result;
  char buf[4096];
  while (fgets(buf, sizeof(buf), pipe)) result += buf;
  pclose(pipe);
  return result;
}

// --- Canonical A→B integration with wire-level continuity proof ---------

TEST(AirSessionC2EndToEndTest,
     TwoBlockSessionProducesContinuousMpegTsThroughBlockSeam) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  const std::string ts_path =
      "/tmp/air_c2_e2e_" + std::to_string(getpid()) + ".ts";
  ::unlink(ts_path.c_str());

  const std::string uds =
      "/tmp/air_c2_e2e_" + std::to_string(getpid()) + ".sock";
  ::unlink(uds.c_str());
  int listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(listen_fd, 0);
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  std::strncpy(addr.sun_path, uds.c_str(), sizeof(addr.sun_path) - 1);
  ASSERT_EQ(::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr),
                   sizeof(addr)), 0);
  ASSERT_EQ(::listen(listen_fd, 1), 0);

  std::atomic<bool> reader_running{true};
  std::atomic<int64_t> bytes_captured{0};
  std::thread reader([&]() {
    int conn = ::accept(listen_fd, nullptr, nullptr);
    if (conn < 0) return;
    FILE* out = std::fopen(ts_path.c_str(), "wb");
    if (!out) {
      ::close(conn);
      return;
    }
    uint8_t buf[16 * 1024];
    while (reader_running.load()) {
      ssize_t n = ::read(conn, buf, sizeof(buf));
      if (n <= 0) break;
      std::fwrite(buf, 1, static_cast<size_t>(n), out);
      bytes_captured.fetch_add(n);
    }
    std::fclose(out);
    ::close(conn);
  });

  std::mutex ev_mu;
  std::vector<SeamEvent> seam_events;
  std::vector<StateTransitionEvent> lifecycle;

  AirSession session;
  session.SetLifecycleObserver([&](const StateTransitionEvent& e) {
    std::lock_guard<std::mutex> lk(ev_mu);
    lifecycle.push_back(e);
  });
  session.SetSeamEventObserver([&](const SeamEvent& e) {
    std::lock_guard<std::mutex> lk(ev_mu);
    seam_events.push_back(e);
  });

  int client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(client_fd, 0);
  sockaddr_un client_addr{};
  client_addr.sun_family = AF_UNIX;
  std::strncpy(client_addr.sun_path, uds.c_str(),
               sizeof(client_addr.sun_path) - 1);
  ASSERT_EQ(::connect(client_fd, reinterpret_cast<sockaddr*>(&client_addr),
                      sizeof(client_addr)), 0);
  ASSERT_TRUE(session.AttachOutput(client_fd));

  // Block A (2 segs × 1s) and Block B (2 segs × 1s); B.start = A.end.
  const int64_t a_start = 1'700'000'000'000LL;
  const Block a = MakeBlock("A", asset, 2, a_start, 1000);
  const Block b = MakeBlock("B", asset, 2, a_start + 2000, 1000);
  ASSERT_TRUE(session.SeedActiveBlock(a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(b, "A", &r));

  // Pre-open snapshot: 2 blocks queued (active + 1), 4 segments total.
  EXPECT_EQ(session.QueueDepth(), 2);
  EXPECT_EQ(session.SegmentDepth(), 4);
  EXPECT_EQ(session.ActiveSegmentIndex(), 0);
  EXPECT_EQ(session.BlockTransitionsTotal(), 0);

  ASSERT_TRUE(session.OpenAir());

  // Wait for all three intra-session seams to fire:
  //   A.0 → A.1  (intra)
  //   A.1 → B.0  (inter; PromoteActiveBlock runs)
  //   B.0 → B.1  (intra)
  const auto deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(6);
  while (session.SeamsExecuted() < 3 &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.SeamsExecuted(), 3)
      << "expected 3 seams (2 intra + 1 inter); actual=" << session.SeamsExecuted();

  // Let B.1 accumulate frames so ffprobe has meaningful content past
  // the block boundary.
  std::this_thread::sleep_for(std::chrono::milliseconds(400));

  // Runtime counters post-promotion.
  EXPECT_EQ(session.BlockTransitionsTotal(), 1);
  EXPECT_EQ(session.PadBridgeEventsTotal(), 0)
      << "happy-path session: no pad bridge should engage";
  ASSERT_TRUE(session.ActiveBlock().has_value());
  EXPECT_EQ(session.ActiveBlock()->block_id(), "B");
  EXPECT_EQ(session.ActiveSegmentIndex(), 1);
  EXPECT_EQ(session.QueueDepth(), 1);  // B active, queue empty
  EXPECT_EQ(session.SegmentDepth(), 2);

  session.Close();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());

  // Post-run event validation.
  std::vector<SeamEvent> events_snap;
  {
    std::lock_guard<std::mutex> lk(ev_mu);
    events_snap = seam_events;
  }
  int intra_executed = 0;
  int inter_executed = 0;
  for (const auto& e : events_snap) {
    if (e.kind != SeamEventKind::kExecuted) continue;
    if (e.target.is_block_transition) {
      ++inter_executed;
      EXPECT_EQ(e.target.from_block_id, "A");
      EXPECT_EQ(e.target.from_segment_index, 1);
      EXPECT_EQ(e.target.to_block_id, "B");
      EXPECT_EQ(e.target.to_segment_index, 0);
    } else {
      ++intra_executed;
    }
  }
  EXPECT_EQ(intra_executed, 2);   // A.0→A.1, B.0→B.1
  EXPECT_EQ(inter_executed, 1);   // A.1→B.0

  // --- ffprobe validation ------------------------------------------------
  ASSERT_TRUE(std::filesystem::exists(ts_path));
  ASSERT_GT(std::filesystem::file_size(ts_path), 500u * 1024)
      << "captured TS too small";

  const std::string fmt = RunFfprobe({
      "-v", "error",
      "-show_entries", "format=format_name:stream=codec_type",
      "-of", "default=noprint_wrappers=1",
      ts_path,
  });
  EXPECT_NE(fmt.find("format_name=mpegts"), std::string::npos);
  EXPECT_NE(fmt.find("codec_type=video"), std::string::npos);
  EXPECT_NE(fmt.find("codec_type=audio"), std::string::npos);

  // Duration: expect at least the 3 played segments × 1s = ~3s (allow
  // for scheduler slack + slight accumulation past the third seam).
  const std::string dur = RunFfprobe({
      "-v", "error",
      "-show_entries", "format=duration",
      "-of", "default=noprint_wrappers=1:nokey=1",
      ts_path,
  });
  const double seconds = std::strtod(dur.c_str(), nullptr);
  EXPECT_GT(seconds, 2.5) << "ffprobe duration " << seconds << "s < 2.5s";
  EXPECT_LT(seconds, 6.0) << "ffprobe duration " << seconds << "s > 6s";

  // Video PTS strict monotonicity across ALL seams (including the
  // inter-block seam). A regression here would mean encoder continuity
  // broke at the block boundary — e.g., an accidental encoder reopen
  // or PTS-offset miscalculation during PromoteActiveBlock.
  const std::string pkts = RunFfprobe({
      "-v", "error",
      "-select_streams", "v",
      "-show_entries", "packet=pts_time",
      "-of", "default=noprint_wrappers=1:nokey=1",
      ts_path,
  });
  double prev = -1.0;
  int pkt_count = 0;
  int regressions = 0;
  {
    std::stringstream ss(pkts);
    std::string line;
    while (std::getline(ss, line)) {
      if (line.empty() || line == "N/A") continue;
      const double pts = std::strtod(line.c_str(), nullptr);
      if (pts < prev) ++regressions;
      prev = pts;
      ++pkt_count;
    }
  }
  EXPECT_GT(pkt_count, 50) << "too few video packets for ~3s of content";
  EXPECT_EQ(regressions, 0)
      << "video PTS regressed " << regressions
      << " times — encoder continuity broken across the block boundary";

  ::unlink(ts_path.c_str());
}

// --- Retirement of queued successor before armed seam --------------------

TEST(AirSessionC2EndToEndTest,
     RetiringQueuedSuccessorBeforeSeamEngagesQueueEmptyPad) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  const std::string uds =
      "/tmp/air_c2_retire_" + std::to_string(getpid()) + ".sock";
  ::unlink(uds.c_str());
  int listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(listen_fd, 0);
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  std::strncpy(addr.sun_path, uds.c_str(), sizeof(addr.sun_path) - 1);
  ASSERT_EQ(::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr),
                   sizeof(addr)), 0);
  ASSERT_EQ(::listen(listen_fd, 1), 0);

  std::atomic<bool> reader_running{true};
  std::atomic<int64_t> bytes_captured{0};
  std::thread reader([&]() {
    int conn = ::accept(listen_fd, nullptr, nullptr);
    if (conn < 0) return;
    uint8_t buf[16 * 1024];
    while (reader_running.load()) {
      ssize_t n = ::read(conn, buf, sizeof(buf));
      if (n <= 0) break;
      bytes_captured.fetch_add(n);
    }
    ::close(conn);
  });

  AirSession session;

  int client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(client_fd, 0);
  sockaddr_un client_addr{};
  client_addr.sun_family = AF_UNIX;
  std::strncpy(client_addr.sun_path, uds.c_str(),
               sizeof(client_addr.sun_path) - 1);
  ASSERT_EQ(::connect(client_fd, reinterpret_cast<sockaddr*>(&client_addr),
                      sizeof(client_addr)), 0);
  ASSERT_TRUE(session.AttachOutput(client_fd));

  const int64_t a_start = 1'700'000'000'000LL;
  const Block a = MakeBlock("A", asset, 2, a_start, 1000);
  const Block b = MakeBlock("B", asset, 2, a_start + 2000, 1000);
  ASSERT_TRUE(session.SeedActiveBlock(a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(b, "A", &r));
  EXPECT_EQ(session.QueueDepth(), 2);

  ASSERT_TRUE(session.OpenAir());

  // Wait for OnAir, then retire B well before the A.1→B.0 seam arms.
  // The safe window is during A.0's play (roughly 0–900ms from OnAir).
  const auto on_air_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (session.State() != SessionState::OnAir &&
         std::chrono::steady_clock::now() < on_air_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_EQ(session.State(), SessionState::OnAir);

  // Retire B immediately. At this moment the A.0→A.1 seam is observed
  // (intra-block, targets A.1 not B.0), and B is still queued but not
  // yet the target of any arm. RetireBlock removes B; no Retract is
  // needed on SeamController because its target is intra-A.
  std::this_thread::sleep_for(std::chrono::milliseconds(100));
  std::string reason;
  ASSERT_TRUE(session.RetireBlock("B", &reason))
      << "retire failed: " << reason;
  EXPECT_TRUE(reason.empty());
  EXPECT_EQ(session.QueueDepth(), 1);  // A alone

  // Wait for A.0→A.1 seam to fire, then for A.1's fence to pass. With
  // queue empty, C2.4's queue-empty pad trigger engages.
  const auto pad_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(4);
  while (session.PadBridgeEventsTotal() == 0 &&
         std::chrono::steady_clock::now() < pad_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.PadBridgeEventsTotal(), 1)
      << "queue-empty pad MUST engage at A.1 fence after B is retired";

  // Exactly one intra-block seam fired; no block transition.
  EXPECT_EQ(session.SeamsExecuted(), 1);
  EXPECT_EQ(session.BlockTransitionsTotal(), 0);
  EXPECT_EQ(session.ActiveBlock()->block_id(), "A");
  EXPECT_EQ(session.ActiveSegmentIndex(), 1);

  // Pad continues indefinitely; verify bytes keep flowing.
  const int64_t bytes_mid = bytes_captured.load();
  EXPECT_GT(bytes_mid, 0);
  std::this_thread::sleep_for(std::chrono::milliseconds(400));
  EXPECT_GT(bytes_captured.load(), bytes_mid)
      << "pad MUST continue emitting indefinitely after retire-to-empty";

  // Session remains OnAir.
  EXPECT_EQ(session.State(), SessionState::OnAir);

  session.Close();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());
}

}  // namespace
}  // namespace retrovue::air
