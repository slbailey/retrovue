// AIR vNext — C1.Ops1 soak test.
//
// Long-duration intra-block stability test exercising the post-H1b
// pipeline: SeedActiveBlock → many-segment block → async priming with
// pre-positioning at prime completion → seam fires that are pointer
// swaps (no encode-thread seek stalls) → pad bridge NOT engaged on
// happy path.
//
// Gated behind AIR_VNEXT_OPS_SOAK=1 because it takes ~60 seconds to
// run. Default test-suite behaviour is SKIP. Enable explicitly when
// validating a change to the hot path:
//   AIR_VNEXT_OPS_SOAK=1 ctest --test-dir air/build -R OpsSoak \
//     --timeout 120 --output-on-failure

#include <grpcpp/grpcpp.h>
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
#include <string>
#include <thread>
#include <vector>

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

// Build a Block of `count` segments, each `segment_ms` long, all
// playing offset=0 into `asset`. Block timing is synthetic but
// internally consistent.
Block MakeSoakBlock(const std::string& asset, int count,
                    int64_t segment_ms) {
  Block b;
  b.block_id = "ops1-soak-block";
  b.start_utc_ms = 1'700'000'000'000LL;
  b.end_utc_ms = b.start_utc_ms + count * segment_ms;
  b.canonical = CheersCanonical();
  for (int i = 0; i < count; ++i) {
    Segment s;
    s.segment_id = "ops1-soak:" + std::to_string(i);
    s.asset_uri = asset;
    s.asset_start_offset_ms = 0;
    s.duration_ms = segment_ms;
    s.segment_index = i;
    b.segments.push_back(s);
  }
  return b;
}

TEST(AirSessionOpsSoakTest, SixtySecondIntraBlockStability) {
  if (const char* env = std::getenv("AIR_VNEXT_OPS_SOAK"); !env || env[0] != '1') {
    GTEST_SKIP() << "Soak disabled (set AIR_VNEXT_OPS_SOAK=1 to enable; "
                    "takes ~60s).";
  }

  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not found";
  }

  const std::string uds =
      "/tmp/air_ops1_soak_" + std::to_string(getpid()) + ".sock";
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

  // Observers for structured-event coverage.
  std::mutex ev_mu;
  std::vector<SeamEventKind> seam_kinds;
  std::vector<SegmentFailedEvent> failed_events;
  std::vector<StateTransitionEvent> lifecycle;

  AirSession session;
  session.SetLifecycleObserver([&](const StateTransitionEvent& e) {
    std::lock_guard<std::mutex> lk(ev_mu);
    lifecycle.push_back(e);
  });
  session.SetSeamEventObserver([&](const SeamEvent& e) {
    std::lock_guard<std::mutex> lk(ev_mu);
    seam_kinds.push_back(e.kind);
  });
  session.SetSegmentFailedObserver([&](const SegmentFailedEvent& e) {
    std::lock_guard<std::mutex> lk(ev_mu);
    failed_events.push_back(e);
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

  // 60 segments × 1 second = 60 seconds of channel content. Each seam
  // exercises pre-position-at-prime-completion → pointer-swap-at-fire.
  // Every prime is a real FFmpeg open + SeekFrameAccurate(0).
  constexpr int kSegCount = 60;
  constexpr int64_t kSegMs = 1000;
  const Block block = MakeSoakBlock(asset, kSegCount, kSegMs);
  ASSERT_TRUE(session.SeedActiveBlock(block));
  const auto soak_start = std::chrono::steady_clock::now();
  ASSERT_TRUE(session.OpenAir());

  // Wait until OnAir, then observe for the full span. Natural EOF at
  // segment 59's fence; give generous headroom for scheduler variance
  // and the post-last-segment drain.
  const auto deadline = soak_start + std::chrono::seconds(75);
  while (std::chrono::steady_clock::now() < deadline) {
    if (session.SeamsExecuted() >= kSegCount - 1 &&
        session.ActiveSegmentIndex() >= kSegCount - 1) {
      // All seams fired and cursor reached the final segment. Let the
      // final segment play its duration before shutting down.
      std::this_thread::sleep_for(std::chrono::milliseconds(1200));
      break;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }

  const int64_t frames_at_close = session.FramesEncoded();
  const int64_t bytes_at_close = session.BytesWritten();
  const int64_t seams = session.SeamsExecuted();
  const int64_t pad_events = session.PadBridgeEventsTotal();
  const int64_t pad_ms = session.PadBridgeMsTotal();
  const int32_t cursor = session.ActiveSegmentIndex();
  const int64_t late_releases = session.PacerLateReleases();

  session.Close();
  reader_running.store(false);
  reader.join();
  ::close(listen_fd);
  ::unlink(uds.c_str());

  const auto soak_elapsed =
      std::chrono::duration_cast<std::chrono::seconds>(
          std::chrono::steady_clock::now() - soak_start).count();

  // Observability dump — on failure (and for operator visibility),
  // gtest prints FAIL messages below with full context.
  std::printf("\n[Ops1 soak] elapsed=%lds seams=%ld cursor=%d\n",
              static_cast<long>(soak_elapsed), static_cast<long>(seams),
              cursor);
  std::printf("[Ops1 soak] frames=%ld bytes=%ld pad_events=%ld pad_ms=%ld "
              "pacer_late=%ld\n",
              static_cast<long>(frames_at_close),
              static_cast<long>(bytes_at_close),
              static_cast<long>(pad_events), static_cast<long>(pad_ms),
              static_cast<long>(late_releases));

  // Primary assertions.
  EXPECT_EQ(seams, kSegCount - 1)
      << "expected 59 seams for 60 segments; actual=" << seams;
  EXPECT_EQ(cursor, kSegCount - 1) << "cursor should reach final segment";
  EXPECT_EQ(pad_events, 0)
      << "no pad bridge should engage on happy-path soak; saw "
      << pad_events << " engagements";
  EXPECT_EQ(pad_ms, 0);

  // No segment failures during happy-path soak.
  {
    std::lock_guard<std::mutex> lk(ev_mu);
    EXPECT_EQ(failed_events.size(), 0u)
        << "unexpected segment failures during soak";
  }

  // Encoder continuity signal: frames + bytes strictly increased to
  // non-trivial magnitudes. 60s at 30fps ≈ 1800 frames minimum.
  EXPECT_GT(frames_at_close, 1500)
      << "frames_encoded too low for ~60s of content";
  EXPECT_GT(bytes_at_close, 1'000'000)
      << "bytes_written suspiciously low";

  // Seam-event surface coverage: 59 × {armed, committed, executed}.
  // Not asserting exact counts to avoid flakiness on extra events; just
  // the rough magnitude.
  int armed = 0, committed = 0, executed = 0;
  {
    std::lock_guard<std::mutex> lk(ev_mu);
    for (auto k : seam_kinds) {
      if (k == SeamEventKind::kArmed) ++armed;
      else if (k == SeamEventKind::kCommitted) ++committed;
      else if (k == SeamEventKind::kExecuted) ++executed;
    }
  }
  EXPECT_GE(armed, kSegCount - 1);
  EXPECT_GE(committed, kSegCount - 1);
  EXPECT_EQ(executed, kSegCount - 1);
}

}  // namespace
}  // namespace retrovue::air
