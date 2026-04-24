// AIR vNext — IR2.1 wiring tests.
//
// Proves ValidateBlockStructure is actually invoked from each of the
// three AirSession entry points, and that PutBlockRevision routes
// structural rejections through the revisions_rejected_total counter.
// The pure-function logic is exhaustively covered by
// block_validation_test.cpp; these tests exist to catch future
// regressions in the wiring itself.

#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <thread>

#include "air_session.hpp"
#include "block.hpp"
#include "channel_canonical.hpp"

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

Block MakeBlock(const std::string& id, const std::string& asset, int seg_count,
                int64_t start_utc_ms, int64_t seg_ms = 1000) {
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

// Lightweight byte-path fixture. Needed only for the AddQueuedBlock and
// PutBlockRevision tests, which require a seeded active session before
// the reject path can be exercised.
struct UdsFixture {
  std::string uds_path;
  int listen_fd = -1;
  int client_fd = -1;
  std::atomic<bool> reader_running{true};
  std::thread reader;

  void Setup(const std::string& tag) {
    uds_path = "/tmp/air_ir21_" + tag + "_" + std::to_string(getpid()) + ".sock";
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
      }
      ::close(conn);
    });
    client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un caddr{};
    caddr.sun_family = AF_UNIX;
    std::strncpy(caddr.sun_path, uds_path.c_str(), sizeof(caddr.sun_path) - 1);
    ::connect(client_fd, reinterpret_cast<sockaddr*>(&caddr), sizeof(caddr));
  }

  void Teardown() {
    reader_running.store(false);
    if (listen_fd >= 0) ::shutdown(listen_fd, SHUT_RDWR);
    if (reader.joinable()) reader.join();
    if (listen_fd >= 0) ::close(listen_fd);
    ::unlink(uds_path.c_str());
  }
};

// --- SeedActiveBlock ---------------------------------------------------

// Structural validation runs before the emitter-attached precondition,
// so this reject path needs no UDS/output setup.
TEST(AirSessionAdmissionTest, SeedActiveBlockRejectsMalformedSegment) {
  AirSession session;
  Block b = MakeBlock("A", "/tmp/asset.mp4", 2, 1'700'000'000'000LL);
  b.segments[1].asset_uri.clear();  // MALFORMED_SEGMENT

  std::string reason;
  EXPECT_FALSE(session.SeedActiveBlock(b, &reason));
  EXPECT_EQ(reason, "MALFORMED_SEGMENT");
}

TEST(AirSessionAdmissionTest, SeedActiveBlockRejectsDurationMismatch) {
  AirSession session;
  Block b = MakeBlock("A", "/tmp/asset.mp4", 2, 1'700'000'000'000LL);
  b.end_utc_ms += 500;  // DURATION_MISMATCH (window 2500, sum 2000)

  std::string reason;
  EXPECT_FALSE(session.SeedActiveBlock(b, &reason));
  EXPECT_EQ(reason, "DURATION_MISMATCH");
}

// --- AddQueuedBlock ----------------------------------------------------

TEST(AirSessionAdmissionTest, AddQueuedBlockRejectsInvalidTimeWindow) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("queue_window");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(MakeBlock("A", asset, 2, 1'700'000'000'000LL)));

  Block bad = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000);
  bad.end_utc_ms = bad.start_utc_ms;  // INVALID_TIME_WINDOW

  std::string reason;
  EXPECT_FALSE(session.AddQueuedBlock(bad, "A", &reason));
  EXPECT_EQ(reason, "INVALID_TIME_WINDOW");

  session.Close();
  uds.Teardown();
}

TEST(AirSessionAdmissionTest, AddQueuedBlockRejectsEmptySegments) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("queue_empty");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(MakeBlock("A", asset, 2, 1'700'000'000'000LL)));

  Block bad;
  bad.block_id = "B";
  bad.start_utc_ms = 1'700'000'000'000LL + 2000;
  bad.end_utc_ms = 1'700'000'000'000LL + 4000;
  bad.canonical = TestCanonical();
  // segments deliberately empty

  std::string reason;
  EXPECT_FALSE(session.AddQueuedBlock(bad, "A", &reason));
  EXPECT_EQ(reason, "EMPTY_SEGMENTS");

  session.Close();
  uds.Teardown();
}

// --- PutBlockRevision --------------------------------------------------

// Proves (a) the validator is wired, (b) structural rejects still bump
// revisions_rejected_total — the IR1a.5 observability contract.
TEST(AirSessionAdmissionTest,
     PutBlockRevisionStructuralRejectIncrementsRejectedCounter) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("revise_counter");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(MakeBlock("A", asset, 2, 1'700'000'000'000LL)));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(
      MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000), "A", &r));

  const int64_t before = session.RevisionsRejectedTotal();

  Block bad = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000);
  bad.segments[0].duration_ms = 3000;  // sum = 4000, window = 2000

  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(bad, &reason));
  EXPECT_EQ(reason, "DURATION_MISMATCH");
  EXPECT_EQ(session.RevisionsRejectedTotal(), before + 1);

  session.Close();
  uds.Teardown();
}

// --- IR2.2: canonical inheritance + CANONICAL_MISMATCH -----------------

// Seed has no prior session canonical to inherit from, so an absent
// canonical on the seed block collapses to CANONICAL_MISMATCH.
TEST(AirSessionAdmissionTest, SeedActiveBlockRejectsInvalidCanonical) {
  AirSession session;
  Block b = MakeBlock("A", "/tmp/asset.mp4", 2, 1'700'000'000'000LL);
  b.canonical = ChannelCanonical{};  // default/invalid — must reject

  std::string reason;
  EXPECT_FALSE(session.SeedActiveBlock(b, &reason));
  EXPECT_EQ(reason, "CANONICAL_MISMATCH");
}

// Happy-path inheritance: a queued block with absent canonical is
// accepted and inherits the session canonical silently.
TEST(AirSessionAdmissionTest, AddQueuedBlockInheritsAbsentCanonical) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("queue_inherit");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));
  ASSERT_EQ(session.QueueDepth(), 1);

  Block b = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000);
  b.canonical = ChannelCanonical{};  // absent — inheritance branch

  std::string reason;
  EXPECT_TRUE(session.AddQueuedBlock(b, "A", &reason));
  EXPECT_TRUE(reason.empty()) << "accept path must not set a reason";
  EXPECT_EQ(session.QueueDepth(), 2) << "block was enqueued";

  session.Close();
  uds.Teardown();
}

// Present-but-different canonical → CANONICAL_MISMATCH, not enqueued.
TEST(AirSessionAdmissionTest, AddQueuedBlockRejectsMismatchedCanonical) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("queue_mismatch");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));

  Block b = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000);
  b.canonical.audio.sample_rate = 44100;  // was 48000 in TestCanonical()

  std::string reason;
  EXPECT_FALSE(session.AddQueuedBlock(b, "A", &reason));
  EXPECT_EQ(reason, "CANONICAL_MISMATCH");
  EXPECT_EQ(session.QueueDepth(), 1) << "rejected block must not enqueue";

  session.Close();
  uds.Teardown();
}

// Revision with mismatched canonical → CANONICAL_MISMATCH and the
// rejected counter increments (observability contract still holds).
TEST(AirSessionAdmissionTest, PutBlockRevisionRejectsMismatchedCanonical) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("revise_mismatch");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(
      MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000), "A", &r));

  const int64_t before = session.RevisionsRejectedTotal();

  Block b_rev = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000);
  b_rev.canonical.video.width = 1280;  // was 968 in TestCanonical()

  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(b_rev, &reason));
  EXPECT_EQ(reason, "CANONICAL_MISMATCH");
  EXPECT_EQ(session.RevisionsRejectedTotal(), before + 1);

  session.Close();
  uds.Teardown();
}

// --- IR2.3: predecessor continuity -------------------------------------

// predecessor_id must name the current queue tail. Queue empty beyond
// active → tail is active; here predecessor="Z" names neither.
TEST(AirSessionAdmissionTest, AddQueuedBlockRejectsPredecessorMismatch) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("pred_mismatch");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));

  Block b = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000);

  std::string reason;
  EXPECT_FALSE(session.AddQueuedBlock(b, "Z", &reason));
  EXPECT_EQ(reason, "PREDECESSOR_MISMATCH");
  EXPECT_EQ(session.QueueDepth(), 1);

  session.Close();
  uds.Teardown();
}

// Gap: supplied block starts after tail.end_utc_ms.
TEST(AirSessionAdmissionTest, AddQueuedBlockRejectsGap) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("gap");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));  // A.end = a+2000

  // B starts 500ms after A ends → gap.
  Block b = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2500);

  std::string reason;
  EXPECT_FALSE(session.AddQueuedBlock(b, "A", &reason));
  EXPECT_EQ(reason, "GAP_OR_OVERLAP");
  EXPECT_EQ(session.QueueDepth(), 1);

  session.Close();
  uds.Teardown();
}

// Overlap: supplied block starts before tail.end_utc_ms.
TEST(AirSessionAdmissionTest, AddQueuedBlockRejectsOverlap) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("overlap");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));  // A.end = a+2000

  // B starts 500ms before A ends → overlap.
  Block b = MakeBlock("B", asset, 2, 1'700'000'000'000LL + 1500);

  std::string reason;
  EXPECT_FALSE(session.AddQueuedBlock(b, "A", &reason));
  EXPECT_EQ(reason, "GAP_OR_OVERLAP");
  EXPECT_EQ(session.QueueDepth(), 1);

  session.Close();
  uds.Teardown();
}

// Predecessor must be the queue TAIL, not just any block. With A active
// and B queued, supplying C with predecessor="A" is a mismatch — the
// tail is B, and Core's view of the editorial chain is broken if it
// thinks C follows A.
TEST(AirSessionAdmissionTest, AddQueuedBlockRejectsTailShadowedByQueued) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("tail_is_queued");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(
      MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000), "A", &r));
  // Queue state: A active, B queued. Tail is B.

  Block c = MakeBlock("C", asset, 2, 1'700'000'000'000LL + 4000);

  std::string reason;
  EXPECT_FALSE(session.AddQueuedBlock(c, "A", &reason));
  EXPECT_EQ(reason, "PREDECESSOR_MISMATCH")
      << "predecessor must name the queue tail, not the active block";
  EXPECT_EQ(session.QueueDepth(), 2);  // C was not enqueued

  // Supplying C with correct predecessor="B" accepts.
  ASSERT_TRUE(session.AddQueuedBlock(c, "B", &reason));
  EXPECT_EQ(session.QueueDepth(), 3);

  session.Close();
  uds.Teardown();
}

// --- IR2.4: PutBlockRevision window-lock --------------------------------

// A revision whose window differs from the queued block's current
// window is rejected with WINDOW_CHANGED; the rejection bumps the
// revisions_rejected_total_ counter per the IR1a.5 contract.
TEST(AirSessionAdmissionTest, PutBlockRevisionRejectsWindowChanged) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) GTEST_SKIP() << "SampleA not found";

  UdsFixture uds;
  uds.Setup("window_lock");

  AirSession session;
  ASSERT_TRUE(session.AttachOutput(uds.client_fd));
  ASSERT_TRUE(session.SeedActiveBlock(
      MakeBlock("A", asset, 2, 1'700'000'000'000LL)));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(
      MakeBlock("B", asset, 2, 1'700'000'000'000LL + 2000), "A", &r));

  const int64_t before = session.RevisionsRejectedTotal();

  // Structurally valid block, same block_id, but a 4000ms window
  // instead of 2000ms (4 segs x 1000ms). Window-changed.
  Block b_rev = MakeBlock("B", asset, 4, 1'700'000'000'000LL + 2000);

  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(b_rev, &reason));
  EXPECT_EQ(reason, "WINDOW_CHANGED");
  EXPECT_EQ(session.RevisionsRejectedTotal(), before + 1);

  session.Close();
  uds.Teardown();
}

}  // namespace
}  // namespace retrovue::air
