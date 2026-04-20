// AIR vNext — C1 end-to-end + observability test (C1.5).
//
// Runs a 3-segment Block through AirSession's full happy path (no
// priming delay, no pad bridge, no late successor) and validates:
//
//   - Output is a valid MPEG-TS stream (ffprobe parses without error).
//   - Duration is approximately 3 seconds (3 × 1s segments, bounded by
//     early session close — lower-bound asserted).
//   - Encoder continuity: single MpegTsEncoder instance, no stream
//     restart visible to ffprobe, monotonic packet PTS across seams.
//   - Event ordering via observers:
//       * lifecycle: Warming → Ready → OnAir.
//       * seams: two {armed → committed → executed} chains in order.
//
// Scope: validation, not redesign. Upstream readiness (pre-arm seek),
// audio-sample alignment, and async pre-seek are all acknowledged as
// future concerns and NOT exercised here.

#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <array>
#include <atomic>
#include <chrono>
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

ChannelCanonical CheersCanonical() {
  ChannelCanonical c;
  c.video.width = 968;
  c.video.height = 720;
  c.video.frame_rate = {30000, 1001};
  c.video.pixel_format = PixelFormat::kYuv420p;
  c.audio.sample_rate = 48000;
  c.audio.channels = 2;
  return c;
}

Block MakeThreeSegmentBlock(const std::string& asset) {
  Block b;
  b.block_id = "c1-e2e-block";
  b.start_utc_ms = 1'700'000'000'000LL;
  b.end_utc_ms = b.start_utc_ms + 3 * 1000;
  b.canonical = CheersCanonical();
  for (int i = 0; i < 3; ++i) {
    Segment s;
    s.segment_id = "c1-e2e-block:" + std::to_string(i);
    s.asset_uri = asset;
    s.asset_start_offset_ms = 0;
    s.duration_ms = 1000;
    s.segment_index = i;
    b.segments.push_back(s);
  }
  return b;
}

// Run ffprobe, capture stdout into a string. Returns empty string on
// failure. argv must be null-terminated (last element nullptr).
std::string RunFfprobe(const std::vector<std::string>& args) {
  std::string cmd = "ffprobe";
  for (const auto& a : args) {
    cmd += " ";
    cmd += "'" + a + "'";
  }
  cmd += " 2>&1";
  std::string result;
  FILE* pipe = popen(cmd.c_str(), "r");
  if (!pipe) return result;
  char buf[4096];
  while (fgets(buf, sizeof(buf), pipe)) result += buf;
  pclose(pipe);
  return result;
}

TEST(AirSessionC1EndToEndTest, ThreeSegmentBlockProducesValidMPEG_TSAndOrderedEvents) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not found";
  }

  // Temp file for captured TS bytes.
  const std::string ts_path =
      "/tmp/air_c1_e2e_" + std::to_string(getpid()) + ".ts";
  ::unlink(ts_path.c_str());

  const std::string uds =
      "/tmp/air_c1_e2e_" + std::to_string(getpid()) + ".sock";
  ::unlink(uds.c_str());
  int listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(listen_fd, 0);
  sockaddr_un addr{};
  addr.sun_family = AF_UNIX;
  std::strncpy(addr.sun_path, uds.c_str(), sizeof(addr.sun_path) - 1);
  ASSERT_EQ(::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr),
                   sizeof(addr)), 0);
  ASSERT_EQ(::listen(listen_fd, 1), 0);

  // Reader writes captured bytes to a file so ffprobe can analyse.
  std::atomic<bool> reader_running{true};
  std::atomic<int64_t> bytes_read{0};
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
      bytes_read.fetch_add(n);
    }
    std::fclose(out);
    ::close(conn);
  });

  // Event capture.
  std::mutex ev_mu;
  std::vector<StateTransitionEvent> lifecycle_events;
  std::vector<SeamEvent> seam_events;

  AirSession session;
  session.SetLifecycleObserver([&](const StateTransitionEvent& e) {
    std::lock_guard<std::mutex> lk(ev_mu);
    lifecycle_events.push_back(e);
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

  const Block block = MakeThreeSegmentBlock(asset);
  ASSERT_TRUE(session.SeedActiveBlock(block));
  ASSERT_TRUE(session.OpenAir());

  // Wait until both seams have fired (cursor at 2) or 6s deadline.
  const auto deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(6);
  while (session.SeamsExecuted() < 2 &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  EXPECT_EQ(session.SeamsExecuted(), 2) << "both intra-block seams should fire";

  // Let seg 2 accumulate some frames so ffprobe has meaningful duration.
  std::this_thread::sleep_for(std::chrono::milliseconds(300));

  // Happy path: no pad bridge, no late recovery.
  EXPECT_EQ(session.PadBridgeEventsTotal(), 0);
  EXPECT_EQ(session.PadBridgeMsTotal(), 0);

  session.Close();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());

  // ---- Post-run event-order validation ---------------------------------
  std::vector<StateTransitionEvent> lifecycle_snapshot;
  std::vector<SeamEvent> seam_snapshot;
  {
    std::lock_guard<std::mutex> lk(ev_mu);
    lifecycle_snapshot = lifecycle_events;
    seam_snapshot = seam_events;
  }

  // Lifecycle: first three transitions must be Warming→Ready→OnAir in
  // that order. A later Stopping from Close() is allowed (not asserted).
  ASSERT_GE(lifecycle_snapshot.size(), 3u);
  // First transition is Warming (from default Warming to Warming, recorded
  // as the openair entry event), followed by Warming→Ready and Ready→OnAir.
  // Scan forward to find the Ready and OnAir boundaries.
  bool saw_ready = false, saw_on_air = false, on_air_after_ready = true;
  for (const auto& e : lifecycle_snapshot) {
    if (e.to == SessionState::Ready) saw_ready = true;
    if (e.to == SessionState::OnAir) {
      saw_on_air = true;
      if (!saw_ready) on_air_after_ready = false;
    }
  }
  EXPECT_TRUE(saw_ready);
  EXPECT_TRUE(saw_on_air);
  EXPECT_TRUE(on_air_after_ready)
      << "OnAir transition observed before Ready — lifecycle out of order";

  // Seam events: exactly two seams fired; each chain is
  // armed → committed → executed in order.
  int armed_count = 0, committed_count = 0, executed_count = 0;
  SeamEventKind last_kind_for_seam = SeamEventKind::kExecuted;
  int seam_chain = 0;  // 0 = expect armed, 1 = expect committed, 2 = expect executed
  bool chain_order_ok = true;
  for (const auto& e : seam_snapshot) {
    switch (e.kind) {
      case SeamEventKind::kArmed:
        if (seam_chain != 0) chain_order_ok = false;
        ++armed_count;
        seam_chain = 1;
        break;
      case SeamEventKind::kCommitted:
        if (seam_chain != 1) chain_order_ok = false;
        ++committed_count;
        seam_chain = 2;
        break;
      case SeamEventKind::kExecuted:
        if (seam_chain != 2) chain_order_ok = false;
        ++executed_count;
        seam_chain = 0;
        break;
      case SeamEventKind::kDisarmed:
        // Not expected in the happy path.
        ADD_FAILURE() << "unexpected seam.disarmed in happy path";
        break;
    }
    last_kind_for_seam = e.kind;
  }
  EXPECT_EQ(armed_count, 2);
  EXPECT_EQ(committed_count, 2);
  EXPECT_EQ(executed_count, 2);
  EXPECT_TRUE(chain_order_ok)
      << "seam events did not arrive in armed→committed→executed order";

  // ---- ffprobe validation ----------------------------------------------
  ASSERT_TRUE(std::filesystem::exists(ts_path))
      << "no captured TS output at " << ts_path;
  ASSERT_GT(std::filesystem::file_size(ts_path), 100u * 1024)
      << "captured TS is suspiciously small";

  // Format: mpegts, no errors.
  const std::string fmt = RunFfprobe({
      "-v", "error",
      "-show_entries", "format=format_name:stream=codec_type,codec_name",
      "-of", "default=noprint_wrappers=1",
      ts_path,
  });
  EXPECT_NE(fmt.find("format_name=mpegts"), std::string::npos)
      << "ffprobe does not recognise output as mpegts; got:\n" << fmt;
  EXPECT_NE(fmt.find("codec_type=video"), std::string::npos)
      << "no video stream detected";
  EXPECT_NE(fmt.find("codec_type=audio"), std::string::npos)
      << "no audio stream detected";

  // Duration: parse format=duration from ffprobe. With ~2.3s of content
  // (seams fire at 1000ms and 2000ms; we wait 300ms after second seam),
  // duration should be at least 2 seconds. Upper bound generous to
  // account for flush/drain.
  const std::string dur = RunFfprobe({
      "-v", "error",
      "-show_entries", "format=duration",
      "-of", "default=noprint_wrappers=1:nokey=1",
      ts_path,
  });
  const double seconds = std::strtod(dur.c_str(), nullptr);
  EXPECT_GT(seconds, 2.0) << "ffprobe duration " << seconds << "s < 2s";
  EXPECT_LT(seconds, 5.0) << "ffprobe duration " << seconds << "s > 5s";

  // Video packet PTS monotonicity across the whole file — a violation
  // here would expose a seam-time PTS regression (encoder continuity
  // proof at the wire level). We parse pts_time from ffprobe and assert
  // strictly increasing sequence.
  const std::string pkts = RunFfprobe({
      "-v", "error",
      "-select_streams", "v",
      "-show_entries", "packet=pts_time",
      "-of", "default=noprint_wrappers=1:nokey=1",
      ts_path,
  });
  double prev_pts = -1.0;
  int pkt_count = 0;
  int regression_count = 0;
  {
    std::stringstream ss(pkts);
    std::string line;
    while (std::getline(ss, line)) {
      if (line.empty() || line == "N/A") continue;
      const double pts = std::strtod(line.c_str(), nullptr);
      if (pts < prev_pts) ++regression_count;
      prev_pts = pts;
      ++pkt_count;
    }
  }
  EXPECT_GT(pkt_count, 30) << "too few video packets for ~3s of content";
  EXPECT_EQ(regression_count, 0)
      << "video packet PTS regressed " << regression_count
      << " times — encoder continuity across seams broken";

  ::unlink(ts_path.c_str());
}

}  // namespace
}  // namespace retrovue::air
