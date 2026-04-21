// AIR vNext — C2.4 contract tests.
//
// Two coupled behaviours:
//   1. Demand-driven pull: AirSession's pull worker calls the installed
//      responder when queue depth is below target and enqueues any
//      returned Block.
//   2. Queue-empty pad bridge (per INV-PLAYBACK-QUEUE-EMPTY-PAD-BRIDGE-001):
//      when the active block's final segment fence passes with queue
//      empty, AirSession engages pad emission (does NOT end the session)
//      and continues emitting indefinitely until a successor arrives.
//
// Both are tested via AirSession's direct C++ surface (AddQueuedBlock,
// SetPullResponder). Tests drive Core-side supply through the responder
// hook; real gRPC client wiring is out of scope for C2.4.

#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <optional>
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
                int seg_count, int64_t start_utc_ms, int64_t seg_ms = 1000) {
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

// Shared test harness: UDS listener + reader thread.
struct UdsFixture {
  std::string uds_path;
  int listen_fd = -1;
  int client_fd = -1;
  std::atomic<bool> reader_running{true};
  std::atomic<int64_t> bytes_read{0};
  std::thread reader;

  void Setup(const std::string& tag) {
    uds_path = "/tmp/air_c2_4_" + tag + "_" + std::to_string(getpid()) + ".sock";
    ::unlink(uds_path.c_str());
    listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, uds_path.c_str(), sizeof(addr.sun_path) - 1);
    ::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    ::listen(listen_fd, 1);
    reader = std::thread([this]() {
      int conn = ::accept(listen_fd, nullptr, nullptr);
      if (conn < 0) return;
      uint8_t buf[16 * 1024];
      while (reader_running.load()) {
        ssize_t n = ::read(conn, buf, sizeof(buf));
        if (n <= 0) break;
        bytes_read.fetch_add(n);
      }
      ::close(conn);
    });
    client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un client_addr{};
    client_addr.sun_family = AF_UNIX;
    std::strncpy(client_addr.sun_path, uds_path.c_str(),
                 sizeof(client_addr.sun_path) - 1);
    ::connect(client_fd, reinterpret_cast<sockaddr*>(&client_addr),
              sizeof(client_addr));
  }

  void Teardown() {
    reader_running.store(false);
    if (reader.joinable()) reader.join();
    if (listen_fd >= 0) ::close(listen_fd);
    ::unlink(uds_path.c_str());
  }
};

// --- Queue-empty pad bridge ---------------------------------------------

// INV-PLAYBACK-QUEUE-EMPTY-PAD-BRIDGE-001: when the active block's
// final segment fence passes with queued_blocks_ empty and no pull
// responder delivering, AirSession MUST engage pad emission and
// continue indefinitely — NOT end the session.
TEST(AirSessionPullTest, QueueEmptyAtLastFenceEngagesPadAndDoesNotEndSession) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("qe_pad");

  AirSession session;
  session.AttachOutput(uds.client_fd);

  // Single 1-second block; no queue refill available.
  Block a = MakeBlock("A", asset, 1, 1'700'000'000'000LL, 1000);
  ASSERT_TRUE(session.SeedActiveBlock(a));
  ASSERT_TRUE(session.OpenAir());

  // Wait for OnAir.
  const auto on_air_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (session.State() != SessionState::OnAir &&
         std::chrono::steady_clock::now() < on_air_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.State(), SessionState::OnAir);
  const auto on_air_at = std::chrono::steady_clock::now();

  // Wait for the pad bridge to engage at the 1-second fence.
  const auto bridge_deadline = on_air_at + std::chrono::milliseconds(3000);
  while (session.PadBridgeEventsTotal() == 0 &&
         std::chrono::steady_clock::now() < bridge_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.PadBridgeEventsTotal(), 1)
      << "queue-empty pad bridge MUST engage at fence per "
         "INV-PLAYBACK-QUEUE-EMPTY-PAD-BRIDGE-001";

  // Observe indefinite pad emission. Wait a couple seconds past fence;
  // session must stay OnAir and bytes must keep flowing.
  std::this_thread::sleep_for(std::chrono::milliseconds(1500));

  EXPECT_EQ(session.State(), SessionState::OnAir)
      << "session MUST NOT end while queue-empty pad is active";
  EXPECT_EQ(session.SeamsExecuted(), 0)
      << "no seam fires while queue stays empty";
  // PadBridgeMsTotal accumulates on pad-EXIT; for indefinite pad there
  // is no exit yet. Use byte-flow continuity as the indefinite-pad
  // witness: bytes must keep growing throughout.
  const int64_t bytes_mid = uds.bytes_read.load();
  EXPECT_GT(bytes_mid, 0);
  std::this_thread::sleep_for(std::chrono::milliseconds(500));
  const int64_t bytes_later = uds.bytes_read.load();
  EXPECT_GT(bytes_later, bytes_mid)
      << "bytes MUST continue growing throughout indefinite pad "
         "(INV-PLAYBACK-QUEUE-EMPTY-PAD-BRIDGE-001)";
  // Still only ONE engagement — no bounce.
  EXPECT_EQ(session.PadBridgeEventsTotal(), 1);

  session.Close();
  uds.Teardown();
}

// --- Pull-driven refill + pad exit --------------------------------------

// End-to-end: queue-empty pad engages; after a delay the pull responder
// delivers Block B; the worker enqueues it; priming + seam arming
// follows; pad exits at the (retroactive-fence) seam fire and B becomes
// active. Satisfies INV-PLAYBACK-QUEUE-EMPTY-PAD-BRIDGE-001 end-to-end
// and exercises the pull loop structurally.
TEST(AirSessionPullTest, PullLoopRefillsQueueAndExitsQueueEmptyPad) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("pull_refill");

  // Responder: first call returns empty (Core doesn't have it yet);
  // after a short delay, subsequent calls return Block B and then
  // nothing further.
  std::atomic<int> call_count{0};
  const int64_t a_start = 1'700'000'000'000LL;
  const Block block_b = MakeBlock("B", asset, 2, a_start + 1000, 1000);
  PullResponder responder =
      [&call_count, block_b](const std::string& /*predecessor*/)
      -> std::optional<Block> {
    const int n = call_count.fetch_add(1);
    // Delay B's arrival so pad has time to engage. 400ms lower bound.
    if (n < 4) return std::nullopt;
    return block_b;
  };

  AirSession session;
  session.AttachOutput(uds.client_fd);
  session.SetPullResponder(responder);
  session.SetPullTargetDepth(2);  // want at least 2 blocks: active + 1 queued

  // Seed with single-segment A so the last fence is at T=1s.
  Block a = MakeBlock("A", asset, 1, a_start, 1000);
  ASSERT_TRUE(session.SeedActiveBlock(a));
  ASSERT_TRUE(session.OpenAir());

  // Wait for OnAir.
  const auto on_air_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (session.State() != SessionState::OnAir &&
         std::chrono::steady_clock::now() < on_air_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.State(), SessionState::OnAir);

  // Wait for pad bridge to engage (seam should not fire while queue empty).
  const auto bridge_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(3);
  while (session.PadBridgeEventsTotal() == 0 &&
         std::chrono::steady_clock::now() < bridge_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.PadBridgeEventsTotal(), 1);
  EXPECT_EQ(session.SeamsExecuted(), 0)
      << "seam MUST NOT fire while queue is empty";

  // Wait for pull loop to deliver B, prime it, and fire the seam.
  // Empty backoff is ~50ms per call; we gated responder to require 4
  // empties before supplying, so ~200ms until supply, plus priming +
  // seam cycle.
  const auto seam_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (session.SeamsExecuted() < 1 &&
         std::chrono::steady_clock::now() < seam_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.SeamsExecuted(), 1)
      << "seam MUST fire once B arrives and primes";
  EXPECT_EQ(session.BlockTransitionsTotal(), 1);
  EXPECT_EQ(session.ActiveBlock()->block_id(), "B");
  EXPECT_EQ(session.ActiveSegmentIndex(), 0);
  EXPECT_EQ(session.PadBridgeEventsTotal(), 1) << "exactly one bridge engaged";

  // Counters reflect the pull activity.
  EXPECT_GE(session.PullResponsesSuppliedTotal(), 1);
  EXPECT_GE(session.PullResponsesEmptyTotal(), 1);
  EXPECT_EQ(session.PullRequestsIssuedTotal(),
            session.PullResponsesSuppliedTotal() +
                session.PullResponsesEmptyTotal());

  session.Close();
  uds.Teardown();
}

// --- Pull loop: respects target depth -----------------------------------

// Worker stops pulling once queue is at target depth. Verifies the worker
// doesn't hammer the responder indefinitely when queue is full.
TEST(AirSessionPullTest, PullLoopStopsWhenQueueAtTargetDepth) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("at_target");

  // Responder always delivers successive blocks B, C, D, ...
  std::atomic<int> call_count{0};
  const int64_t a_start = 1'700'000'000'000LL;
  PullResponder responder =
      [&call_count, asset, a_start](const std::string& /*predecessor*/)
      -> std::optional<Block> {
    const int n = call_count.fetch_add(1);
    if (n >= 5) return std::nullopt;  // cap so test doesn't run forever
    const std::string id(1, static_cast<char>('B' + n));
    const int64_t start = a_start + (n + 1) * 2000;
    return MakeBlock(id, asset, 2, start, 1000);
  };

  AirSession session;
  session.AttachOutput(uds.client_fd);
  session.SetPullResponder(responder);
  session.SetPullTargetDepth(2);  // active + 1 queued

  Block a = MakeBlock("A", asset, 2, a_start, 1000);
  ASSERT_TRUE(session.SeedActiveBlock(a));
  ASSERT_TRUE(session.OpenAir());

  // Wait for OnAir, then let the pull loop run briefly.
  const auto on_air_deadline =
      std::chrono::steady_clock::now() + std::chrono::seconds(5);
  while (session.State() != SessionState::OnAir &&
         std::chrono::steady_clock::now() < on_air_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.State(), SessionState::OnAir);

  // Brief settle; enough for pull worker to fetch at least one block
  // and then detect queue is at target depth.
  std::this_thread::sleep_for(std::chrono::milliseconds(300));

  // Target depth is 2, so worker should have fetched exactly one block
  // past the seed (A active, then one queued). With active progressing,
  // worker may fetch more as blocks get consumed, but at the moment of
  // snapshot, request count should be small (single digits), not
  // unbounded.
  const int64_t issued = session.PullRequestsIssuedTotal();
  EXPECT_GT(issued, 0) << "pull worker should have issued at least one request";
  EXPECT_LT(issued, 20)
      << "pull worker hammered the responder — target-depth throttling broken";

  session.Close();
  uds.Teardown();
}

}  // namespace
}  // namespace retrovue::air
