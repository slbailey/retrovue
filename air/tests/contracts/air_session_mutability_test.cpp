// AIR vNext — C2.5 mutability contract tests.
//
// Validates PutBlockRevision and RetireBlock against
// INV-PLAYBACK-BLOCK-MUTABILITY-001. Reason codes exercised:
//   ACTIVE_BLOCK_IMMUTABLE, BLOCK_NOT_IN_QUEUE, BLOCK_PRIMING,
//   BLOCK_ARMED, EMPTY_SEGMENTS, NO_SESSION.
//
// Most tests operate BEFORE OpenAir to exercise mutability without
// timing flakiness. Priming/armed states are forced via the test
// helper ForceSetSegmentStateForTest to avoid reliance on pipeline
// timing.

#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "air_session.hpp"
#include "block.hpp"
#include "channel_canonical.hpp"
#include "priming_pipeline.hpp"
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

// Fixture: seed A, queue B, don't OpenAir yet — lets tests manipulate
// queued state deterministically without the encode thread moving.
struct SeedTwoBlocks {
  std::string asset;
  int uds_client_fd = -1;
  std::string uds_path;
  int listen_fd = -1;
  std::atomic<bool> reader_running{true};
  std::thread reader;
  Block a;
  Block b;

  void Setup(const std::string& tag) {
    asset = ResolveSampleA();
    uds_path = "/tmp/air_mut_" + tag + "_" + std::to_string(getpid()) + ".sock";
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
    uds_client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un client_addr{};
    client_addr.sun_family = AF_UNIX;
    std::strncpy(client_addr.sun_path, uds_path.c_str(),
                 sizeof(client_addr.sun_path) - 1);
    ::connect(uds_client_fd, reinterpret_cast<sockaddr*>(&client_addr),
              sizeof(client_addr));
    const int64_t a_start = 1'700'000'000'000LL;
    a = MakeBlock("A", asset, 2, a_start, 1000);
    b = MakeBlock("B", asset, 2, a_start + 2000, 1000);
  }

  void Teardown() {
    reader_running.store(false);
    if (reader.joinable()) reader.join();
    if (listen_fd >= 0) ::close(listen_fd);
    ::unlink(uds_path.c_str());
  }
};

// --- PutBlockRevision: pre-OpenAir reason codes --------------------------

TEST(AirSessionMutabilityTest, RevisionRejectsEmptySegments) {
  SeedTwoBlocks f;
  f.Setup("rev_empty");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));

  Block empty;
  empty.block_id = "B";
  empty.canonical = TestCanonical();
  // segments deliberately empty

  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(empty, &reason));
  EXPECT_EQ(reason, "EMPTY_SEGMENTS");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RevisionRejectsActiveBlock) {
  SeedTwoBlocks f;
  f.Setup("rev_active");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));

  // Revision against block_id "A" — which IS active_block_.
  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(f.a, &reason));
  EXPECT_EQ(reason, "ACTIVE_BLOCK_IMMUTABLE");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RevisionRejectsBlockNotInQueue) {
  SeedTwoBlocks f;
  f.Setup("rev_notfound");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));

  Block c = MakeBlock("C", f.asset, 1, 1'700'000'000'005'000LL);
  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(c, &reason));
  EXPECT_EQ(reason, "BLOCK_NOT_IN_QUEUE");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RevisionRejectsPrimingSegment) {
  SeedTwoBlocks f;
  f.Setup("rev_priming");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));

  // Force segment 0 of B into kPriming.
  session.ForceSetSegmentStateForTest("B", 0, SegmentPrimeState::kPriming);

  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(f.b, &reason));
  EXPECT_EQ(reason, "BLOCK_PRIMING");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RevisionRejectsPrimedSegmentAsBlockArmed) {
  // Vault collapses kPrimed / kActive / kRetired / kFailed into
  // BLOCK_ARMED for the mutability-reject surface.
  SeedTwoBlocks f;
  f.Setup("rev_primed");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));

  session.ForceSetSegmentStateForTest("B", 1, SegmentPrimeState::kPrimed);

  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(f.b, &reason));
  EXPECT_EQ(reason, "BLOCK_ARMED");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RevisionRejectsFailedSegmentAsBlockArmed) {
  SeedTwoBlocks f;
  f.Setup("rev_failed");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));

  session.ForceSetSegmentStateForTest("B", 0, SegmentPrimeState::kFailed);

  std::string reason;
  EXPECT_FALSE(session.PutBlockRevision(f.b, &reason));
  EXPECT_EQ(reason, "BLOCK_ARMED");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RevisionAcceptsAllRawBlockAndReplacesContents) {
  SeedTwoBlocks f;
  f.Setup("rev_accept");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));

  // B has 2 segments; revision renames to a 3-segment variant.
  Block b_rev = MakeBlock("B", f.asset, 3, f.b.start_utc_ms, 1000);
  b_rev.end_utc_ms = f.b.start_utc_ms + 3000;
  std::string reason;
  ASSERT_TRUE(session.PutBlockRevision(b_rev, &reason));
  EXPECT_TRUE(reason.empty());

  // Segment count reflects the revision. Revised block replaces in-place.
  EXPECT_EQ(session.QueueDepth(), 2);   // A active + 1 queued
  EXPECT_EQ(session.SegmentDepth(), 2 + 3);  // A:2 + revised B:3

  session.Close();
  f.Teardown();
}

// --- RetireBlock ---------------------------------------------------------

TEST(AirSessionMutabilityTest, RetireRejectsActiveBlock) {
  SeedTwoBlocks f;
  f.Setup("ret_active");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string reason;
  EXPECT_FALSE(session.RetireBlock("A", &reason));
  EXPECT_EQ(reason, "ACTIVE_BLOCK_IMMUTABLE");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RetireRejectsBlockNotInQueue) {
  SeedTwoBlocks f;
  f.Setup("ret_notfound");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string reason;
  EXPECT_FALSE(session.RetireBlock("X", &reason));
  EXPECT_EQ(reason, "BLOCK_NOT_IN_QUEUE");

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RetireAcceptsQueuedBlockAndShrinksQueue) {
  SeedTwoBlocks f;
  f.Setup("ret_accept");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));
  EXPECT_EQ(session.QueueDepth(), 2);
  EXPECT_EQ(session.SegmentDepth(), 4);

  std::string reason;
  ASSERT_TRUE(session.RetireBlock("B", &reason));
  EXPECT_TRUE(reason.empty());
  EXPECT_EQ(session.QueueDepth(), 1);  // A alone
  EXPECT_EQ(session.SegmentDepth(), 2);

  session.Close();
  f.Teardown();
}

TEST(AirSessionMutabilityTest, RetireAcceptsBlockWithPrimedSegment) {
  // Retirement is accepted for any non-active block regardless of
  // segment state (vault: "accepted for any non-active block"). This
  // includes primed — the BlockRuntime destructor cleans up the
  // source and normalizer.
  SeedTwoBlocks f;
  f.Setup("ret_primed");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));
  session.ForceSetSegmentStateForTest("B", 0, SegmentPrimeState::kPrimed);

  std::string reason;
  ASSERT_TRUE(session.RetireBlock("B", &reason));
  EXPECT_TRUE(reason.empty());
  EXPECT_EQ(session.QueueDepth(), 1);

  session.Close();
  f.Teardown();
}

// --- Integration: revision after retirement re-primes cleanly ------------

TEST(AirSessionMutabilityTest,
     RevisionAfterRetireThenReAddProducesNewCandidate) {
  // Demonstrates the Pass-B "no in-place revival" decision end-to-end:
  // retire a block, add a fresh one with same id, verify it's a new
  // candidate (all raw).
  SeedTwoBlocks f;
  f.Setup("rev_reoad");
  if (!std::filesystem::exists(f.asset)) { f.Teardown(); GTEST_SKIP(); }

  AirSession session;
  session.AttachOutput(f.uds_client_fd);
  ASSERT_TRUE(session.SeedActiveBlock(f.a));
  std::string r;
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &r));
  session.ForceSetSegmentStateForTest("B", 0, SegmentPrimeState::kFailed);

  // Retire the failed-segment block.
  std::string reason;
  ASSERT_TRUE(session.RetireBlock("B", &reason));

  // Re-add a fresh B.
  ASSERT_TRUE(session.AddQueuedBlock(f.b, "A", &reason));

  // New candidate: all segments kRaw.
  ASSERT_TRUE(session.ActiveBlock().has_value());
  // Can't easily access queued[0] from here without exposing another
  // helper; instead test via PutBlockRevision acceptance. A fresh block
  // with all-raw segments accepts a revision.
  Block b_rev = MakeBlock("B", f.asset, 1, f.b.start_utc_ms, 500);
  b_rev.end_utc_ms = f.b.start_utc_ms + 500;
  ASSERT_TRUE(session.PutBlockRevision(b_rev, &reason));
  EXPECT_EQ(session.SegmentDepth(), 2 + 1);  // A:2 + new B:1

  session.Close();
  f.Teardown();
}

}  // namespace
}  // namespace retrovue::air
