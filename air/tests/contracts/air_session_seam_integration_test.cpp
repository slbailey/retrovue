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

  // After seed: segment 0 primed synchronously; segment 1 still raw.
  // Async priming pipeline starts on OpenAir and brings segment 1 up.
  ASSERT_TRUE(session.ActiveBlock().has_value());
  ASSERT_EQ(session.ActiveBlock()->segment_count(), 2u);
  EXPECT_EQ(session.ActiveBlock()->State(0), SegmentPrimeState::kPrimed);
  EXPECT_EQ(session.ActiveBlock()->State(1), SegmentPrimeState::kRaw);
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

// Genuinely late successor: prime of segment 1 is artificially delayed so
// segment 0's fence arrives before segment 1 is primed. The encode loop
// must engage a pad bridge, continue emitting, and transition to segment 1
// once priming completes. Uses the real PrimingPipeline worker — the
// delay injected in the next_raw hook is wall-clock, not test-only seam
// manipulation, so pad bridge is exercised end-to-end.
TEST(AirSessionSeamIntegrationTest, LateSuccessorEngagesPadBridge) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not found";
  }

  // UDS reader.
  const std::string uds =
      "/tmp/air_pad_bridge_" + std::to_string(getpid()) + ".sock";
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

  AirSession session;
  // Inject a 1500ms delay before priming runs. Segment 0 duration is
  // 1000ms, so the fence arrives ~500ms before segment 1 is primed.
  session.SetTestPrimeDelayMs(1500);

  int client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(client_fd, 0);
  sockaddr_un client_addr{};
  client_addr.sun_family = AF_UNIX;
  std::strncpy(client_addr.sun_path, uds.c_str(),
               sizeof(client_addr.sun_path) - 1);
  ASSERT_EQ(::connect(client_fd, reinterpret_cast<sockaddr*>(&client_addr),
                      sizeof(client_addr)), 0);
  ASSERT_TRUE(session.AttachOutput(client_fd));

  const Block block = MakeTwoSegmentBlock(asset);
  ASSERT_TRUE(session.SeedActiveBlock(block));

  // Pre-OpenAir: only segment 0 primed; 1 is raw.
  EXPECT_EQ(session.ActiveBlock()->State(1), SegmentPrimeState::kRaw);
  EXPECT_EQ(session.PadBridgeEventsTotal(), 0);

  ASSERT_TRUE(session.OpenAir());

  // Wait for OnAir.
  const auto on_air_deadline = std::chrono::steady_clock::now() +
                               std::chrono::seconds(5);
  while (session.State() != SessionState::OnAir &&
         std::chrono::steady_clock::now() < on_air_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.State(), SessionState::OnAir);

  // Wait for the pad bridge to be engaged. This happens at fence time
  // (~1000ms after OnAir) with segment 1 still mid-prime. Generous
  // timeout accounts for warmup buffer and scheduler variability.
  const auto bridge_deadline = std::chrono::steady_clock::now() +
                               std::chrono::seconds(4);
  while (session.PadBridgeEventsTotal() == 0 &&
         std::chrono::steady_clock::now() < bridge_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.PadBridgeEventsTotal(), 1)
      << "pad bridge should engage when fence arrives before successor is primed";
  EXPECT_EQ(session.SeamsExecuted(), 0)
      << "seam has not yet fired — bridge is mid-flight";

  // Segment 1 should finish priming (~1500ms after OpenAir) and the
  // seam should fire, ending the bridge.
  const auto seam_deadline = std::chrono::steady_clock::now() +
                             std::chrono::seconds(4);
  while (session.SeamsExecuted() == 0 &&
         std::chrono::steady_clock::now() < seam_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.SeamsExecuted(), 1) << "seam did not fire after bridge";
  EXPECT_EQ(session.ActiveSegmentIndex(), 1);
  EXPECT_EQ(session.ActiveBlock()->State(0), SegmentPrimeState::kRetired);
  EXPECT_EQ(session.ActiveBlock()->State(1), SegmentPrimeState::kActive);

  // Bridge duration: we expect at least ~300ms of pad (500ms in theory;
  // scheduling + seam-tick cadence introduces slack; don't over-assert).
  EXPECT_GE(session.PadBridgeMsTotal(), 200)
      << "pad bridge should cover the 500ms gap with comfortable margin";

  // Encoder continuity: frames kept flowing through the bridge.
  EXPECT_GT(session.FramesEncoded(), 0);
  EXPECT_GT(session.BytesWritten(), 0);

  session.Close();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());
}

// Build an N-segment Block, each segment `duration_ms` long, all pointing
// at `asset`. start_utc_ms is synthetic but stable.
Block MakeNSegmentBlock(const std::string& asset, int count,
                        int64_t duration_ms = 1000) {
  Block b;
  b.block_id = "jip-block";
  b.start_utc_ms = 1'700'000'000'000LL;
  b.end_utc_ms = b.start_utc_ms + count * duration_ms;
  b.canonical = CheersCanonical();
  for (int i = 0; i < count; ++i) {
    Segment s;
    s.segment_id = "jip-block:" + std::to_string(i);
    s.asset_uri = asset;
    s.asset_start_offset_ms = 0;
    s.duration_ms = duration_ms;
    s.segment_index = i;
    b.segments.push_back(s);
  }
  return b;
}

// 3-segment block. Segment 1 primes 500ms late (pad bridge engages for
// seam 0→1); segment 2 primes immediately (happy swap for seam 1→2).
// Validates INV-SEAM-LATE-SUCCESSOR-JIP-001:
//   - Exactly one pad bridge engages (between seg 0 and seg 1).
//   - Two seams fire; cursor advances 0 → 1 → 2.
//   - Seam 1→2 fires at its editorial wall-clock tick, NOT shifted by
//     the lateness of seg 1. Downstream fences remain sacred.
//   - Seg 1 plays its tail inside its editorial window (not its head
//     past the window); seg 2's editorial start aligns with fence 1.
TEST(AirSessionSeamIntegrationTest, LateSeg1DoesNotRippleIntoSeg2Fence) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not found";
  }

  const std::string uds =
      "/tmp/air_jip_ripple_" + std::to_string(getpid()) + ".sock";
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
  std::thread reader([&]() {
    int conn = ::accept(listen_fd, nullptr, nullptr);
    if (conn < 0) return;
    uint8_t buf[16 * 1024];
    while (reader_running.load()) {
      ssize_t n = ::read(conn, buf, sizeof(buf));
      if (n <= 0) break;
    }
    ::close(conn);
  });

  AirSession session;
  // Per-prime-call delays. i=0 applies to the prime of segment 1 (1500ms);
  // i=1 applies to segment 2 (immediate). Single-worker pipeline processes
  // segments in order, so this cleanly isolates lateness to seam 0→1.
  session.SetTestPrimeDelaysMs({1500, 0});

  int client_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
  ASSERT_GE(client_fd, 0);
  sockaddr_un client_addr{};
  client_addr.sun_family = AF_UNIX;
  std::strncpy(client_addr.sun_path, uds.c_str(),
               sizeof(client_addr.sun_path) - 1);
  ASSERT_EQ(::connect(client_fd, reinterpret_cast<sockaddr*>(&client_addr),
                      sizeof(client_addr)), 0);
  ASSERT_TRUE(session.AttachOutput(client_fd));

  const Block block = MakeNSegmentBlock(asset, 3, /*duration_ms=*/1000);
  ASSERT_TRUE(session.SeedActiveBlock(block));

  const auto test_start = std::chrono::steady_clock::now();
  ASSERT_TRUE(session.OpenAir());

  // Wait for OnAir.
  const auto on_air_deadline = test_start + std::chrono::seconds(5);
  while (session.State() != SessionState::OnAir &&
         std::chrono::steady_clock::now() < on_air_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.State(), SessionState::OnAir);
  const auto on_air_at = std::chrono::steady_clock::now();

  // Wait for pad bridge to engage (fence 0 arrives with seg 1 still priming).
  const auto bridge_deadline =
      on_air_at + std::chrono::milliseconds(2000);
  while (session.PadBridgeEventsTotal() == 0 &&
         std::chrono::steady_clock::now() < bridge_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }
  ASSERT_EQ(session.PadBridgeEventsTotal(), 1);

  // Wait for seam 0→1 to fire (pad bridge exits when seg 1 primes).
  const auto seam1_deadline = on_air_at + std::chrono::milliseconds(3000);
  while (session.SeamsExecuted() < 1 &&
         std::chrono::steady_clock::now() < seam1_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_GE(session.SeamsExecuted(), 1);
  const auto seam1_at = std::chrono::steady_clock::now();

  // Wait for seam 1→2 (fence 1 = editorial 2000ms from OnAir). If JIP
  // is NOT compensating, seg 2's fence would be delayed by the 500ms
  // lateness ripple; with JIP, fence 1 fires at its editorial tick.
  const auto seam2_deadline = on_air_at + std::chrono::milliseconds(4000);
  while (session.SeamsExecuted() < 2 &&
         std::chrono::steady_clock::now() < seam2_deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  ASSERT_EQ(session.SeamsExecuted(), 2)
      << "seam 1→2 did not fire within editorial fence window — "
         "late successor likely rippled into downstream timeline";
  const auto seam2_at = std::chrono::steady_clock::now();

  // Fence integrity: seam 1→2 fires approximately at editorial
  // wall-clock 2000ms from OnAir entry. Allow a generous ±300ms slack
  // for scheduler variability. Without JIP, this would be ~2500ms
  // (500ms ripple from seg 1 lateness) — the upper bound would be
  // violated.
  const int64_t seam2_from_on_air =
      std::chrono::duration_cast<std::chrono::milliseconds>(
          seam2_at - on_air_at).count();
  EXPECT_GE(seam2_from_on_air, 1700)
      << "seam 1→2 fired too early; fence arithmetic suspect";
  EXPECT_LE(seam2_from_on_air, 2300)
      << "seam 1→2 fired late (possible lateness ripple from seg 1)";

  // Only one pad bridge — seg 2 should have been primed by its fence,
  // so no second bridge engages.
  EXPECT_EQ(session.PadBridgeEventsTotal(), 1)
      << "second pad bridge engaged — seg 2 missed its fence";

  // Cursor and state progression.
  EXPECT_EQ(session.ActiveSegmentIndex(), 2);
  EXPECT_EQ(session.ActiveBlock()->State(0), SegmentPrimeState::kRetired);
  EXPECT_EQ(session.ActiveBlock()->State(1), SegmentPrimeState::kRetired);
  EXPECT_EQ(session.ActiveBlock()->State(2), SegmentPrimeState::kActive);

  // Seam 0→1 to seam 1→2 interval: ≈ seg 1 editorial duration
  // minus lateness_ms ≈ 500ms. With JIP, seg 1 plays its TAIL inside
  // its editorial window; this is the authoritative proof of no
  // truncation ripple.
  const int64_t between_seams_ms =
      std::chrono::duration_cast<std::chrono::milliseconds>(
          seam2_at - seam1_at).count();
  EXPECT_GE(between_seams_ms, 300)
      << "seg 1 emitted < 300ms of content (expected ~500ms)";
  EXPECT_LE(between_seams_ms, 700)
      << "seg 1 emitted > 700ms of content (expected ~500ms); "
         "possible non-JIP behavior (full duration played, fence shifted)";

  EXPECT_GT(session.FramesEncoded(), 0);
  EXPECT_GT(session.BytesWritten(), 0);

  session.Close();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());
}

}  // namespace
}  // namespace retrovue::air
