// =============================================================================
// Contract Tests: OutputBusAndOutputSinkContract [AIR-012, AIR-015]
// =============================================================================
// Tests all sink invariants defined in:
//   docs/contracts/coordination/OutputBusAndOutputSinkContract.md
//
// Invariants covered:
//   OSINK-OB-001: OutputBus enforces single-sink policy (§3.2 / §9 inv.1)
//   OSINK-OB-002: OutputBus discard telemetry pre-attach (§9 inv.2)
//   OSINK-OB-003: Detach leaves bus valid — silent discard resumes (§3.2)
//   AIR-012-001:  Sink Start is idempotent — repeated Start is safe (§11.1)
//   AIR-012-002:  Sink Stop is idempotent — repeated Stop is safe (§11.1)
//   AIR-015-001:  Queue overflow drops frames; counters increment (§12.1)
//   AIR-015-002:  Bounded queue — overfill never causes unbounded growth (§12.2)
//   AIR-015-003:  Invalid fd → kError fault; state persists (§12.4)
//   AIR-015-004:  Client disconnect → kDetached gracefully, no crash (§12.3)
//
// Contract home: docs/contracts/coordination/OutputBusAndOutputSinkContract.md
// Ledger IDs:    AIR-012, AIR-015
// Governance:    2025-07-14
// =============================================================================

#include "../BaseContractTest.h"
#include "ContractRegistryEnvironment.h"

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <gtest/gtest.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/output/IOutputSink.h"
#include "retrovue/output/OutputBus.h"
#include "retrovue/output/MpegTSOutputSink.h"
#include "retrovue/output/SinkDiagnostics.h"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"

using namespace std::chrono_literals;

namespace retrovue::tests {
namespace {

using retrovue::tests::RegisterExpectedDomainCoverage;

// Register expected coverage for this domain
const bool kRegisterSinkContractCoverage = []() {
  RegisterExpectedDomainCoverage("OutputBusAndOutputSink",
                                 {"OSINK-OB-001",
                                  "OSINK-OB-002",
                                  "OSINK-OB-003",
                                  "AIR-012-001",
                                  "AIR-012-002",
                                  "AIR-015-001",
                                  "AIR-015-002",
                                  "AIR-015-003",
                                  "AIR-015-004"});
  return true;
}();

// =============================================================================
// Minimal CountingSink for OutputBus invariant testing
// =============================================================================
class CountingSink : public output::IOutputSink {
 public:
  explicit CountingSink(const std::string& name = "CountingSink") : name_(name) {}
  ~CountingSink() override = default;

  bool Start() override {
    std::lock_guard<std::mutex> lk(mu_);
    if (status_ != output::SinkStatus::kIdle) return false;
    status_ = output::SinkStatus::kRunning;
    return true;
  }
  void Stop() override {
    std::lock_guard<std::mutex> lk(mu_);
    status_ = output::SinkStatus::kStopped;
  }
  bool IsRunning() const override {
    std::lock_guard<std::mutex> lk(mu_);
    return status_ == output::SinkStatus::kRunning;
  }
  output::SinkStatus GetStatus() const override {
    std::lock_guard<std::mutex> lk(mu_);
    return status_;
  }
  void ConsumeVideo(const buffer::Frame&) override {
    video_count_.fetch_add(1, std::memory_order_relaxed);
  }
  void ConsumeAudio(const buffer::AudioFrame&) override {
    audio_count_.fetch_add(1, std::memory_order_relaxed);
  }
  void SetStatusCallback(output::SinkStatusCallback cb) override {
    std::lock_guard<std::mutex> lk(mu_);
    cb_ = std::move(cb);
  }
  std::string GetName() const override { return name_; }

  uint64_t VideoCount() const { return video_count_.load(std::memory_order_relaxed); }
  uint64_t AudioCount() const { return audio_count_.load(std::memory_order_relaxed); }

 private:
  mutable std::mutex mu_;
  output::SinkStatus status_{output::SinkStatus::kIdle};
  output::SinkStatusCallback cb_;
  std::string name_;
  std::atomic<uint64_t> video_count_{0};
  std::atomic<uint64_t> audio_count_{0};
};

// Helper to build a minimal video frame
static buffer::Frame MakeVideoFrame(int64_t pts_us, int w = 320, int h = 240) {
  buffer::Frame f;
  f.width = w;
  f.height = h;
  f.metadata.pts = pts_us;
  f.metadata.dts = pts_us;
  f.metadata.duration = 1.0 / 30.0;
  f.metadata.has_ct = true;
  f.metadata.asset_uri = "test://frame";
  f.data.resize(static_cast<size_t>(w * h * 3 / 2), 128);
  return f;
}

// Helper to build a minimal audio frame
static buffer::AudioFrame MakeAudioFrame(int64_t pts_us) {
  buffer::AudioFrame a;
  a.pts_us = pts_us;
  a.sample_rate = 48000;
  a.channels = 2;
  a.nb_samples = 1024;
  a.data.resize(1024 * 2 * sizeof(int16_t), 0);
  return a;
}

// Helper: make a sink config
static playout_sinks::mpegts::MpegTSPlayoutSinkConfig MakeSinkConfig() {
  playout_sinks::mpegts::MpegTSPlayoutSinkConfig cfg;
  cfg.target_width = 320;
  cfg.target_height = 240;
  cfg.bitrate = 500000;
  cfg.target_fps = 30.0;
  cfg.gop_size = 30;
  cfg.stub_mode = false;
  return cfg;
}

// =============================================================================
// Test fixture
// =============================================================================
class OutputBusAndOutputSinkContractTest : public BaseContractTest {
 protected:
  [[nodiscard]] std::string DomainName() const override {
    return "OutputBusAndOutputSink";
  }
  [[nodiscard]] std::vector<std::string> CoveredRuleIds() const override {
    return {"OSINK-OB-001", "OSINK-OB-002", "OSINK-OB-003",
            "AIR-012-001",  "AIR-012-002",
            "AIR-015-001",  "AIR-015-002",
            "AIR-015-003",  "AIR-015-004"};
  }
};

// =============================================================================
// OSINK-OB-001: OutputBus enforces single-sink policy
// =============================================================================
// Contract §3.2: If a sink is already attached, a second AttachSink call
// (without replace_existing) MUST return failure.
// The bus must not silently displace the existing sink.
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       OSINK_OB_001_SingleSinkPolicyEnforced) {
  SCOPED_TRACE("OSINK-OB-001: OutputBus must reject double-attach");

  output::OutputBus bus;

  // Attach first sink — must succeed
  auto result1 = bus.AttachSink(std::make_unique<CountingSink>("sink-a"));
  ASSERT_TRUE(result1.success)
      << "First AttachSink must succeed; got: " << result1.message;
  ASSERT_TRUE(bus.HasSink());

  // Attempt second attach without detaching — MUST fail (protocol error)
  auto result2 = bus.AttachSink(std::make_unique<CountingSink>("sink-b"));
  EXPECT_FALSE(result2.success)
      << "OSINK-OB-001 VIOLATION: second AttachSink must be rejected while "
         "sink is already attached. message='" << result2.message << "'";

  // Bus must still have original sink (first sink was not displaced)
  EXPECT_TRUE(bus.HasSink());

  // Frames must still route to the original (first) sink — no discards
  bus.RouteVideo(MakeVideoFrame(0));
  EXPECT_EQ(bus.GetVideoDiscards(), 0u)
      << "No discards expected — original sink is still attached";

  std::cout << "[OSINK-OB-001] Single-sink policy enforced: "
            << "second attach rejected ('" << result2.message << "')" << std::endl;
}

// =============================================================================
// OSINK-OB-001 (attach to empty bus): baseline positive case
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       OSINK_OB_001_AttachToEmptyBusSucceeds) {
  SCOPED_TRACE("OSINK-OB-001: Attach to empty bus must succeed");

  output::OutputBus bus;
  EXPECT_FALSE(bus.HasSink());

  auto result = bus.AttachSink(std::make_unique<CountingSink>("only-sink"));
  EXPECT_TRUE(result.success)
      << "AttachSink to empty bus must succeed; got: " << result.message;
  EXPECT_TRUE(bus.HasSink());

  std::cout << "[OSINK-OB-001] Attach to empty bus: OK" << std::endl;
}

// =============================================================================
// OSINK-OB-002: Discard telemetry before attach
// =============================================================================
// Contract §9 inv.2: OutputBus exists independent of attachment.
// Pre-attach frames are silently discarded; discard counters MUST increment.
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       OSINK_OB_002_DiscardTelemetryPreAttach) {
  SCOPED_TRACE("OSINK-OB-002: Discard counters must increment pre-attach");

  output::OutputBus bus;
  ASSERT_EQ(bus.GetVideoDiscards(), 0u);
  ASSERT_EQ(bus.GetAudioDiscards(), 0u);

  constexpr int kVideoCount = 20;
  constexpr int kAudioCount = 10;

  for (int i = 0; i < kVideoCount; ++i) {
    bus.RouteVideo(MakeVideoFrame(i * 33333));
  }
  for (int i = 0; i < kAudioCount; ++i) {
    bus.RouteAudio(MakeAudioFrame(i * 21333));
  }

  EXPECT_EQ(bus.GetVideoDiscards(), static_cast<uint64_t>(kVideoCount))
      << "OSINK-OB-002 VIOLATION: Video discard counter must equal frames sent "
         "pre-attach. got=" << bus.GetVideoDiscards()
      << " expected=" << kVideoCount;

  EXPECT_EQ(bus.GetAudioDiscards(), static_cast<uint64_t>(kAudioCount))
      << "OSINK-OB-002 VIOLATION: Audio discard counter must equal frames sent "
         "pre-attach. got=" << bus.GetAudioDiscards()
      << " expected=" << kAudioCount;

  std::cout << "[OSINK-OB-002] Discard telemetry: "
            << bus.GetVideoDiscards() << " video, "
            << bus.GetAudioDiscards() << " audio discards recorded" << std::endl;
}

// =============================================================================
// OSINK-OB-003: Detach leaves bus valid — silent discard resumes
// =============================================================================
// Contract §3.2: "Detaching a sink leaves OutputBus valid but silent."
// Post-detach frames must be discarded (not crash), discard counters resume.
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       OSINK_OB_003_DetachLeavesBusValidAndSilent) {
  SCOPED_TRACE("OSINK-OB-003: Post-detach bus must discard silently");

  output::OutputBus bus;

  auto result = bus.AttachSink(std::make_unique<CountingSink>("detach-test-sink"));
  ASSERT_TRUE(result.success);

  // Route some frames — must reach sink (no discards)
  for (int i = 0; i < 5; ++i) bus.RouteVideo(MakeVideoFrame(i * 33333));
  EXPECT_EQ(bus.GetVideoDiscards(), 0u);

  // Detach
  auto dr = bus.DetachSink();
  EXPECT_TRUE(dr.success)
      << "OSINK-OB-003: DetachSink must succeed; got: " << dr.message;
  EXPECT_FALSE(bus.HasSink());

  // Post-detach: route 10 more frames — must be discarded
  uint64_t discards_before = bus.GetVideoDiscards();
  for (int i = 5; i < 15; ++i) bus.RouteVideo(MakeVideoFrame(i * 33333));

  EXPECT_EQ(bus.GetVideoDiscards(), discards_before + 10)
      << "OSINK-OB-003 VIOLATION: post-detach frames must increment discard counter";

  // Bus must remain usable — re-attach must succeed
  auto re_attach = bus.AttachSink(std::make_unique<CountingSink>("re-attach-sink"));
  EXPECT_TRUE(re_attach.success)
      << "OSINK-OB-003: Bus must accept re-attach after detach";

  std::cout << "[OSINK-OB-003] Post-detach discard: "
            << (bus.GetVideoDiscards() - discards_before)
            << " discards recorded, bus re-attachment OK" << std::endl;
}

// =============================================================================
// AIR-012-001: Sink Start is idempotent
// =============================================================================
// Contract §11.1: "Start is idempotent: calling Start on an already-running
// sink MUST NOT cause error or duplicate initialization."
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       AIR_012_001_SinkStartIsIdempotent) {
  SCOPED_TRACE("AIR-012-001: Repeated Start must be safe and not cause kError");

  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
  int read_fd = fds[0], write_fd = fds[1];

  auto cfg = MakeSinkConfig();
  output::MpegTSOutputSink sink(write_fd, cfg, "test-air012-001-idempotent-start");

  // First Start — must succeed
  ASSERT_TRUE(sink.Start())
      << "AIR-012-001: First Start() must return true from kIdle";
  EXPECT_EQ(sink.GetStatus(), output::SinkStatus::kRunning);

  // Second Start — must NOT crash. Must return false (already running).
  bool second_start = sink.Start();
  EXPECT_FALSE(second_start)
      << "AIR-012-001: Start on already-running sink must return false "
         "(must not double-initialize)";

  // Critically: status must NOT be kError after the redundant Start
  auto status = sink.GetStatus();
  EXPECT_NE(status, output::SinkStatus::kError)
      << "AIR-012-001 VIOLATION: Redundant Start must not put sink into kError. "
         "status=" << static_cast<int>(status);

  sink.Stop();
  close(read_fd);
  close(write_fd);

  std::cout << "[AIR-012-001] Start idempotency: second Start()="
            << (second_start ? "true (VIOLATION)" : "false (correct)")
            << ", status remained non-error" << std::endl;
}

// =============================================================================
// AIR-012-002: Sink Stop is idempotent
// =============================================================================
// Contract §11.1: "Stop is idempotent: calling Stop on an already-stopped
// sink MUST NOT cause error."
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       AIR_012_002_SinkStopIsIdempotent) {
  SCOPED_TRACE("AIR-012-002: Repeated Stop must be safe");

  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
  int read_fd = fds[0], write_fd = fds[1];

  auto cfg = MakeSinkConfig();
  output::MpegTSOutputSink sink(write_fd, cfg, "test-air012-002-idempotent-stop");

  ASSERT_TRUE(sink.Start());

  // First Stop
  sink.Stop();
  EXPECT_EQ(sink.GetStatus(), output::SinkStatus::kStopped);

  // Second Stop — must NOT crash or enter error state
  sink.Stop();
  auto status = sink.GetStatus();
  EXPECT_NE(status, output::SinkStatus::kError)
      << "AIR-012-002 VIOLATION: Second Stop() must not produce kError. "
         "status=" << static_cast<int>(status);

  // Third Stop — same guarantee
  sink.Stop();

  close(read_fd);
  close(write_fd);

  // Stop before Start (different sink instance) — must be safe
  int fds2[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds2), 0);
  output::MpegTSOutputSink sink2(fds2[1], cfg, "test-air012-002-stop-before-start");
  sink2.Stop();  // Must not crash
  auto status2 = sink2.GetStatus();
  EXPECT_NE(status2, output::SinkStatus::kError)
      << "AIR-012-002 VIOLATION: Stop before Start must not produce kError";
  close(fds2[0]);
  close(fds2[1]);

  std::cout << "[AIR-012-002] Stop idempotency: "
            << "repeated Stop and stop-before-start are safe" << std::endl;
}

// =============================================================================
// AIR-015-001: Queue overflow drops frames; counters increment
// =============================================================================
// Contract §12.1: Frames arriving beyond queue capacity MUST be dropped.
// Counters video_frames_dropped / audio_frames_dropped MUST increment.
//
// We close the reader fd to stall the MuxLoop, then flood beyond
// kMaxVideoQueueSize (30) / kMaxAudioQueueSize (30).
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       AIR_015_001_QueueOverflowDropsFramesAndIncrementsCounters) {
  SCOPED_TRACE("AIR-015-001: Queue overflow must drop frames and increment counters");

  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
  int read_fd = fds[0], write_fd = fds[1];

  auto cfg = MakeSinkConfig();
  output::MpegTSOutputSink sink(write_fd, cfg, "test-air015-001-overflow");

  ASSERT_TRUE(sink.Start());

  // Close the reader to create backpressure (write side stalls)
  close(read_fd);
  read_fd = -1;

  // Allow mux loop time to detect disconnect / stall
  std::this_thread::sleep_for(50ms);

  // Enqueue well beyond kMaxVideoQueueSize (30) to trigger overflow drops
  constexpr int kFloodFrames = 80;
  for (int i = 0; i < kFloodFrames; ++i) {
    sink.ConsumeVideo(MakeVideoFrame(i * 33333));
    sink.ConsumeAudio(MakeAudioFrame(i * 21333));
  }

  std::this_thread::sleep_for(50ms);

  uint64_t video_dropped = sink.GetVideoFramesDropped();
  uint64_t audio_dropped = sink.GetAudioFramesDropped();

  EXPECT_GT(video_dropped, 0u)
      << "AIR-015-001 VIOLATION: video_frames_dropped must be > 0 after "
         "queue overflow. flooded=" << kFloodFrames;

  EXPECT_GT(audio_dropped, 0u)
      << "AIR-015-001 VIOLATION: audio_frames_dropped must be > 0 after "
         "queue overflow. flooded=" << kFloodFrames;

  // Sink must still be in a defined (non-crashed) state
  auto status = sink.GetStatus();
  EXPECT_NE(status, output::SinkStatus::kIdle)
      << "AIR-015-001: Sink should not be kIdle after Start + flood";

  sink.Stop();
  close(write_fd);

  std::cout << "[AIR-015-001] Queue overflow: "
            << "video_dropped=" << video_dropped
            << " audio_dropped=" << audio_dropped
            << " (flooded " << kFloodFrames << " of each)" << std::endl;
}

// =============================================================================
// AIR-015-002: Bounded queue — no unbounded memory growth under overflow
// =============================================================================
// Contract §12.2: Queue MUST be bounded; no deadlock, no crash,
// no unbounded memory growth.
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       AIR_015_002_BoundedQueueNoCrashUnderOverflow) {
  SCOPED_TRACE("AIR-015-002: Bounded queue must not grow unbounded");

  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
  int read_fd = fds[0], write_fd = fds[1];

  // Drain thread to avoid socket buffer backpressure from masking queue behavior
  std::atomic<bool> drain_stop{false};
  std::thread drain([&] {
    char buf[8192];
    while (!drain_stop.load(std::memory_order_relaxed)) {
      ssize_t n = read(read_fd, buf, sizeof(buf));
      if (n <= 0) break;
    }
  });

  auto cfg = MakeSinkConfig();
  output::MpegTSOutputSink sink(write_fd, cfg, "test-air015-002-bounded");

  ASSERT_TRUE(sink.Start());

  // Flood with 500 video + audio frames (>> kMaxVideoQueueSize=30)
  // ConsumeVideo/Audio must return quickly (non-blocking drop or enqueue)
  auto start = std::chrono::steady_clock::now();
  constexpr int kFloodCount = 500;
  for (int i = 0; i < kFloodCount; ++i) {
    sink.ConsumeVideo(MakeVideoFrame(i * 33333));
    sink.ConsumeAudio(MakeAudioFrame(i * 21333));
  }
  auto elapsed = std::chrono::steady_clock::now() - start;

  EXPECT_LT(std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count(), 2000)
      << "AIR-015-002 VIOLATION: ConsumeVideo/ConsumeAudio blocked > 2 seconds "
         "— possible deadlock or blocking overflow handling";

  sink.Stop();

  drain_stop.store(true);
  shutdown(read_fd, SHUT_RDWR);
  if (drain.joinable()) drain.join();
  close(read_fd);
  close(write_fd);

  std::cout << "[AIR-015-002] Bounded queue flood: "
            << kFloodCount << " frames * 2 enqueued in "
            << std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count()
            << "ms (no deadlock/crash)" << std::endl;
}

// =============================================================================
// AIR-015-003: Invalid fd → kError fault; fault state persists
// =============================================================================
// Contract §12.4: "Once a sink enters a fault state, it MUST remain in that
// state until an explicit reset is issued."
//
// Starting with fd=-1 triggers kError on Start. That state must persist.
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       AIR_015_003_InvalidFdProducesFaultState) {
  SCOPED_TRACE("AIR-015-003: Invalid fd must produce kError; fault persists");

  auto cfg = MakeSinkConfig();
  // fd=-1 is always invalid — guarantees Start failure path
  output::MpegTSOutputSink sink(-1, cfg, "test-air015-003-fault");

  // Start must fail
  bool started = sink.Start();
  EXPECT_FALSE(started)
      << "AIR-015-003: Start with invalid fd must return false";

  auto status = sink.GetStatus();
  EXPECT_EQ(status, output::SinkStatus::kError)
      << "AIR-015-003 VIOLATION: Start with invalid fd must set kError. "
         "Got status=" << static_cast<int>(status);

  // Fault state must persist — retry Start must still return false and stay kError
  bool started_again = sink.Start();
  EXPECT_FALSE(started_again)
      << "AIR-015-003: Retry Start on fault sink must return false";

  auto status_after_retry = sink.GetStatus();
  EXPECT_EQ(status_after_retry, output::SinkStatus::kError)
      << "AIR-015-003 VIOLATION: Fault state must persist after retry Start. "
         "Got status=" << static_cast<int>(status_after_retry);

  // Stop on fault state must be safe (no crash)
  sink.Stop();

  std::cout << "[AIR-015-003] Fault state: "
            << "Start(fd=-1)=" << (started ? "true(VIOLATION)" : "false(OK)")
            << " → kError persisted, Stop safe" << std::endl;
}

// =============================================================================
// AIR-015-004: Client disconnect → detected gracefully; reconnect succeeds
// =============================================================================
// Contract §12.3: "Client disconnect MUST be detected within a bounded time.
// All resources ... MUST be released. After disconnect and cleanup,
// reconnection MUST succeed without requiring a full restart."
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       AIR_015_004_ClientDisconnectHandledGracefully) {
  SCOPED_TRACE("AIR-015-004: Disconnect must be detected and handled without crash");

  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
  int read_fd = fds[0], write_fd = fds[1];

  auto cfg = MakeSinkConfig();
  output::MpegTSOutputSink sink(write_fd, cfg, "test-air015-004-disconnect");

  // Close read end BEFORE Start so the very first write from MuxLoop gets EPIPE.
  // This is the fastest path to EPIPE detection per contract §12.3.
  close(read_fd);
  read_fd = -1;

  ASSERT_TRUE(sink.Start());

  // Flood frames to trigger MuxLoop encoding + write attempts -> EPIPE on closed peer
  for (int i = 0; i < 60; ++i) {
    sink.ConsumeVideo(MakeVideoFrame(i * 33333));
    sink.ConsumeAudio(MakeAudioFrame(i * 21333));
  }

  // Wait up to 5s for disconnect to be detected via AIR_SHUTDOWN
  // Contract §12.3: disconnect MUST be detected within a bounded time.
  // Observable: output::AirShutdownFired() transitions to true when EPIPE/POLLHUP fires.
  auto deadline = std::chrono::steady_clock::now() + 5s;
  while (!output::AirShutdownFired() &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(20ms);
  }

  // Disconnect MUST have been detected (AIR_SHUTDOWN emitted for output_write_failure)
  EXPECT_TRUE(output::AirShutdownFired())
      << "AIR-015-004 VIOLATION: Disconnect (EPIPE/POLLHUP on closed peer) "
         "must be detected and logged within 5s.";

  // Stop must be safe regardless of current state
  sink.Stop();
  close(write_fd);

  // After Stop(), status must not be kRunning
  auto status_after_stop = sink.GetStatus();
  EXPECT_NE(status_after_stop, output::SinkStatus::kRunning)
      << "AIR-015-004: After Stop(), sink must not be in kRunning state";

  // Reconnect: create new sink with fresh socket — must succeed without restart
  int fds2[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds2), 0);
  output::MpegTSOutputSink sink2(fds2[1], cfg, "test-air015-004-reconnect");
  bool reconnected = sink2.Start();
  EXPECT_TRUE(reconnected)
      << "AIR-015-004 VIOLATION: Reconnect (new sink, new socket) must succeed";

  sink2.Stop();
  close(fds2[0]);
  close(fds2[1]);

  std::cout << "[AIR-015-004] Disconnect: "
            << "AirShutdownFired=" << output::AirShutdownFired()
            << " reconnect=" << (reconnected ? "OK" : "FAILED") << std::endl;
}

// =============================================================================
// OSINK-OB-001 (integration): Real sink double-attach via OutputBus
// =============================================================================
TEST_F(OutputBusAndOutputSinkContractTest,
       OSINK_OB_001_RealSinkDoubleAttachRejected) {
  SCOPED_TRACE("OSINK-OB-001 (integration): Double-attach with real sinks rejected");

  int fds1[2], fds2[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds1), 0);
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds2), 0);

  // Drain thread for fds1 to prevent socket backpressure
  std::atomic<bool> drain_stop{false};
  std::thread drain([&] {
    char buf[4096];
    while (!drain_stop.load(std::memory_order_relaxed)) {
      ssize_t n = read(fds1[0], buf, sizeof(buf));
      if (n <= 0) break;
    }
  });

  auto cfg = MakeSinkConfig();
  output::OutputBus bus;

  auto result1 = bus.AttachSink(
      std::make_unique<output::MpegTSOutputSink>(fds1[1], cfg, "real-sink-1"));
  ASSERT_TRUE(result1.success) << "First attach must succeed";

  auto result2 = bus.AttachSink(
      std::make_unique<output::MpegTSOutputSink>(fds2[1], cfg, "real-sink-2"));
  EXPECT_FALSE(result2.success)
      << "OSINK-OB-001 VIOLATION: Double-attach with real sinks must be rejected";

  bus.DetachSink();

  drain_stop.store(true);
  shutdown(fds1[0], SHUT_RDWR);
  if (drain.joinable()) drain.join();

  close(fds1[0]);
  close(fds1[1]);
  close(fds2[0]);
  close(fds2[1]);

  std::cout << "[OSINK-OB-001 real] Double-attach rejected: '"
            << result2.message << "'" << std::endl;
}

}  // namespace
}  // namespace retrovue::tests
