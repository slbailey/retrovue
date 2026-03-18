// Repository: Retrovue-playout
// Component: INV-CONTROL-PLANE-CADENCE Contract Tests
// Purpose: Verify the mux never blocks indefinitely waiting for media frames.
//          The control plane (TS PAT/PMT/PCR emission) must maintain cadence
//          even when the media plane stalls or is absent.
//
//          Enforcement model (Phase 8+):
//          - 250ms boot window: immediate TS emission without waiting for media.
//          - After boot window: null TS packet loop maintains transport cadence.
//          - Stop() must complete in bounded time regardless of media queue state.
//
// Contract: docs/contracts/invariants/shared/INV-CONTROL-PLANE-CADENCE.md
// Violation condition: Mux blocks indefinitely waiting for media; control-plane
//                      emission stalls or Stop() deadlocks without media.
//
// Note: This is a liveness test. Bounded wall-clock assertions are required
//       because the invariant is fundamentally about bounded response time,
//       not a state that can be asserted without time passing.
//
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

#include "retrovue/output/MpegTSOutputSink.h"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

namespace retrovue::tests {

// =============================================================================
// INV-CONTROL-PLANE-CADENCE — Compliant: Stop() is not deadlocked by missing
// media. Starting the sink and immediately stopping must complete without
// blocking indefinitely. Asserts bounded Stop() latency < 3s.
// =============================================================================
TEST(InvControlPlaneCadence, Compliant_StopWithNoMedia_CompletesWithinBound) {
  // Set up a socketpair so MpegTSOutputSink has a connected fd.
  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);

  // Drain thread prevents socket send buffer from filling (backpressure
  // would block the mux loop, masking the invariant under test).
  std::atomic<bool> drain_stop{false};
  std::thread drain_thread([&] {
    char buf[8192];
    while (!drain_stop.load(std::memory_order_relaxed)) {
      ssize_t n = read(fds[1], buf, sizeof(buf));
      if (n <= 0) break;
    }
  });

  retrovue::playout_sinks::mpegts::MpegTSPlayoutSinkConfig config;
  config.target_fps    = 30.0;
  config.target_width  = 640;
  config.target_height = 480;
  config.bitrate       = 500'000;
  config.enable_audio  = false;
  config.prebuffer_seconds = 0.0;  // No prebuffer delay in tests.

  retrovue::output::MpegTSOutputSink sink(fds[0], config, "inv-cadence-test");

  const auto t0 = std::chrono::steady_clock::now();
  ASSERT_TRUE(sink.Start())
      << "INV-CONTROL-PLANE-CADENCE: Start() must succeed with connected fd";

  // No media fed. Boot window (250ms) runs without media.
  // After the boot window, the mux falls through to null-packet cadence.
  // Do NOT feed any media.

  // Allow boot window to expire (300ms > 250ms kBootFastEmitWindowMs).
  std::this_thread::sleep_for(std::chrono::milliseconds(300));

  sink.Stop();
  const auto t1 = std::chrono::steady_clock::now();
  const auto elapsed_ms =
      std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();

  // INV-CONTROL-PLANE-CADENCE: Stop() must complete within 3s.
  // A deadlocked mux (waiting forever for media) would exceed this bound.
  EXPECT_LE(elapsed_ms, 3000)
      << "INV-CONTROL-PLANE-CADENCE: Stop() must complete within 3s when no "
         "media is fed. Exceeded bound suggests mux is waiting indefinitely "
         "for media instead of maintaining null-packet cadence.";

  drain_stop.store(true);
  shutdown(fds[1], SHUT_RDWR);
  close(fds[1]);
  close(fds[0]);
  if (drain_thread.joinable()) drain_thread.join();
}

// =============================================================================
// INV-CONTROL-PLANE-CADENCE — Compliant: IsRunning() transitions correctly.
// After Start() with no media, the sink enters running state.
// After Stop(), it is no longer running.
// (State-based invariant: control plane is managed; not abandoned.)
// =============================================================================
TEST(InvControlPlaneCadence, Compliant_RunningStateManagedWithoutMedia) {
  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);

  std::atomic<bool> drain_stop{false};
  std::thread drain_thread([&] {
    char buf[8192];
    while (!drain_stop.load(std::memory_order_relaxed)) {
      ssize_t n = read(fds[1], buf, sizeof(buf));
      if (n <= 0) break;
    }
  });

  retrovue::playout_sinks::mpegts::MpegTSPlayoutSinkConfig config;
  config.target_fps    = 30.0;
  config.target_width  = 640;
  config.target_height = 480;
  config.enable_audio  = false;
  config.prebuffer_seconds = 0.0;

  retrovue::output::MpegTSOutputSink sink(fds[0], config, "inv-cadence-state-test");

  EXPECT_FALSE(sink.IsRunning())
      << "INV-CONTROL-PLANE-CADENCE: Before Start(), sink must not be running";

  ASSERT_TRUE(sink.Start());
  EXPECT_TRUE(sink.IsRunning())
      << "INV-CONTROL-PLANE-CADENCE: After Start(), sink must be running "
         "(control plane is active even with no media)";

  sink.Stop();
  EXPECT_FALSE(sink.IsRunning())
      << "INV-CONTROL-PLANE-CADENCE: After Stop(), sink must not be running";

  drain_stop.store(true);
  shutdown(fds[1], SHUT_RDWR);
  close(fds[1]);
  close(fds[0]);
  if (drain_thread.joinable()) drain_thread.join();
}

}  // namespace retrovue::tests
