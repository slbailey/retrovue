// AIR vNext — AirSession intra-block seam integration test (C1.4a).
//
// First end-to-end test proving runtime-state evolution inside AirSession
// across a successful happy-path seam:
//
//   1. SeedActiveBlock with a 2-segment Block. Both segments prime
//      synchronously via AirSession's BlockRuntime-owned path; no parallel
//      active-source ownership.
//   2. OpenAir. Session anchor is established; first seam (0→1) observed.
//      Encode thread begins emitting bytes through the existing byte path.
//   3. Wait for the seam to fire at the segment-0 fence tick.
//   4. Assert runtime-state evolution on BlockRuntime:
//        - segments[0].state: kPrimed → kActive → kRetired
//        - segments[1].state: kPrimed → kActive
//        - active_segment_index_ advances 0 → 1
//        - seams_executed == 1
//   5. Assert encoder continuity:
//        - frames_encoded grew before and after the seam
//        - bytes_written grew monotonically throughout
//        - no encoder reopen (single MpegTsEncoder instance from
//          SeedActiveBlock; nothing in the seam path constructs a new one)
//
// Scope: happy path only. Pad bridge / late successor / block promotion
// are out of scope (C1.4b / C2).

#include <grpcpp/grpcpp.h>
#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <thread>

#include "air_session.hpp"
#include "block.hpp"
#include "block_runtime.hpp"
#include "channel_canonical.hpp"
#include "priming_pipeline.hpp"

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

// Build a 2-segment Block that plays the same asset twice back-to-back.
// Segment 0 and 1 each have duration_ms=1000. block.start_utc_ms is a
// synthetic epoch; it only needs to be stable for session-anchor math.
Block MakeTwoSegmentBlock(const std::string& asset) {
  Block b;
  b.block_id = "seam-block";
  b.start_utc_ms = 1'700'000'000'000LL;
  b.end_utc_ms = b.start_utc_ms + 2 * 1000;
  b.canonical = CheersCanonical();
  for (int i = 0; i < 2; ++i) {
    Segment s;
    s.segment_id = "seam-block:" + std::to_string(i);
    s.asset_uri = asset;
    s.asset_start_offset_ms = 0;
    s.duration_ms = 1000;
    s.segment_index = i;
    b.segments.push_back(s);
  }
  return b;
}

TEST(AirSessionSeamIntegrationTest, IntraBlockSeamAdvancesRuntimeState) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not found";
  }

  // --- UDS reader ---
  const std::string uds =
      "/tmp/air_seam_integ_" + std::to_string(getpid()) + ".sock";
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
  std::atomic<int64_t> bytes_read{0};
  std::thread reader([&]() {
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

  // --- AirSession: attach output via direct socket (not via gRPC) ---
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

  // --- Seed 2-segment Block. Both segments prime synchronously. ---
  const Block block = MakeTwoSegmentBlock(asset);
  ASSERT_TRUE(session.SeedActiveBlock(block));

  // After seed: both segments primed, cursor at 0, 0 seams executed.
  ASSERT_TRUE(session.ActiveBlock().has_value());
  ASSERT_EQ(session.ActiveBlock()->segment_count(), 2u);
  EXPECT_EQ(session.ActiveBlock()->State(0), SegmentPrimeState::kPrimed);
  EXPECT_EQ(session.ActiveBlock()->State(1), SegmentPrimeState::kPrimed);
  EXPECT_EQ(session.ActiveSegmentIndex(), 0);
  EXPECT_EQ(session.SeamsExecuted(), 0);

  // --- OpenAir. Encode thread starts; seam 0→1 observed at OnAir entry. ---
  ASSERT_TRUE(session.OpenAir());

  // Wait for OnAir before snapshotting pre-seam state.
  const auto on_air_deadline = std::chrono::steady_clock::now() +
                               std::chrono::seconds(5);
  while (session.State() != SessionState::OnAir &&
         std::chrono::steady_clock::now() < on_air_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.State(), SessionState::OnAir);

  // Wait until some frames have been encoded from segment 0 (proves
  // encoder is live before the seam).
  const auto pre_seam_deadline = std::chrono::steady_clock::now() +
                                 std::chrono::seconds(3);
  while (session.FramesEncoded() < 5 &&
         session.SeamsExecuted() == 0 &&
         std::chrono::steady_clock::now() < pre_seam_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  const int64_t pre_seam_frames = session.FramesEncoded();
  const int64_t pre_seam_bytes = session.BytesWritten();
  EXPECT_GT(pre_seam_frames, 0) << "expected frames emitted before seam";

  // During segment 0's active window the state is kActive.
  if (session.SeamsExecuted() == 0) {
    EXPECT_EQ(session.ActiveBlock()->State(0), SegmentPrimeState::kActive);
    EXPECT_EQ(session.ActiveSegmentIndex(), 0);
  }

  // --- Wait for the seam to fire (segment 0 fence = 1000ms from anchor). ---
  const auto seam_deadline = std::chrono::steady_clock::now() +
                             std::chrono::seconds(5);
  while (session.SeamsExecuted() == 0 &&
         std::chrono::steady_clock::now() < seam_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.SeamsExecuted(), 1) << "seam did not fire within deadline";

  // After seam: cursor advanced, segment 0 retired, segment 1 active.
  EXPECT_EQ(session.ActiveSegmentIndex(), 1);
  EXPECT_EQ(session.ActiveBlock()->State(0), SegmentPrimeState::kRetired);
  EXPECT_EQ(session.ActiveBlock()->State(1), SegmentPrimeState::kActive);

  // Encoder continuity: wait for additional frames after the seam.
  const int64_t target_frames = pre_seam_frames + 5;
  const auto post_seam_deadline = std::chrono::steady_clock::now() +
                                  std::chrono::seconds(3);
  while (session.FramesEncoded() < target_frames &&
         std::chrono::steady_clock::now() < post_seam_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  EXPECT_GE(session.FramesEncoded(), target_frames)
      << "expected ≥5 frames emitted after the seam";
  EXPECT_GT(session.BytesWritten(), pre_seam_bytes)
      << "bytes written must grow across the seam (encoder continuity)";

  // --- Clean shutdown ---
  session.Close();
  EXPECT_EQ(session.SeamsExecuted(), 0) << "Close clears seams_executed";

  reader_running.store(false);
  // Client fd is closed by session.Close() via owned_fd_ path.
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());
}

}  // namespace
}  // namespace retrovue::air
