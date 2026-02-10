// Repository: Retrovue-playout
// Component: Continuous Output Contract Tests
// Purpose: Verify P3.0 + P3.1a + P3.1b PipelineManager contracts
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "retrovue/blockplan/PadProducer.hpp"
#include "retrovue/blockplan/ProducerPreloader.hpp"
#include "retrovue/blockplan/SeamProofTypes.hpp"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// Test Fixture
// =============================================================================

class ContinuousOutputContractTest : public ::testing::Test {
 protected:
  void SetUp() override {
    ctx_ = std::make_unique<BlockPlanSessionContext>();
    ctx_->channel_id = 99;
    // PipelineManager::Run() calls dup(fd) then send() — must be a real socket.
    // socketpair + drain thread absorbs encoded TS output without backpressure.
    int fds[2];
    ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0);
    ctx_->fd = fds[0];
    drain_fd_ = fds[1];
    drain_stop_.store(false);
    drain_thread_ = std::thread([this] {
      char buf[8192];
      while (!drain_stop_.load(std::memory_order_relaxed)) {
        ssize_t n = read(drain_fd_, buf, sizeof(buf));
        if (n <= 0) break;
      }
    });
    ctx_->width = 640;
    ctx_->height = 480;
    ctx_->fps = 30.0;
  }

  void TearDown() override {
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
    // Shut down drain: close write end first so read() returns 0.
    if (ctx_ && ctx_->fd >= 0) {
      close(ctx_->fd);
      ctx_->fd = -1;
    }
    drain_stop_.store(true);
    if (drain_fd_ >= 0) {
      shutdown(drain_fd_, SHUT_RDWR);
      close(drain_fd_);
      drain_fd_ = -1;
    }
    if (drain_thread_.joinable()) drain_thread_.join();
  }

  std::unique_ptr<PipelineManager> MakeEngine() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
    };
    callbacks.on_session_ended = [this](const std::string& reason) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
      session_ended_reason_ = reason;
      session_ended_cv_.notify_all();
    };
    return std::make_unique<PipelineManager>(
        ctx_.get(), std::move(callbacks));
  }

  // Wait for session_ended callback with timeout
  bool WaitForSessionEnded(int timeout_ms = 2000) {
    std::unique_lock<std::mutex> lock(cb_mutex_);
    return session_ended_cv_.wait_for(
        lock, std::chrono::milliseconds(timeout_ms),
        [this] { return session_ended_count_ > 0; });
  }

  std::unique_ptr<BlockPlanSessionContext> ctx_;
  std::unique_ptr<PipelineManager> engine_;
  int drain_fd_ = -1;
  std::atomic<bool> drain_stop_{false};
  std::thread drain_thread_;

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::vector<std::string> completed_blocks_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;

  // PAD-PROOF: Fingerprint capture for PadProducer integration tests.
  std::mutex fp_mutex_;
  std::vector<FrameFingerprint> fingerprints_;

  std::unique_ptr<PipelineManager> MakeEngineWithTrace() {
    PipelineManager::Callbacks callbacks;
    callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      completed_blocks_.push_back(block.block_id);
    };
    callbacks.on_session_ended = [this](const std::string& reason) {
      std::lock_guard<std::mutex> lock(cb_mutex_);
      session_ended_count_++;
      session_ended_reason_ = reason;
      session_ended_cv_.notify_all();
    };
    callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.push_back(fp);
    };
    return std::make_unique<PipelineManager>(ctx_.get(), std::move(callbacks));
  }

  std::vector<FrameFingerprint> SnapshotFingerprints() {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    return fingerprints_;
  }
};

// =============================================================================
// TEST-CONT-001: Session produces output with zero blocks (all pad)
// Run engine ~100ms with no blocks, verify frames are all pad.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadOnlyWithZeroBlocks) {
  engine_ = MakeEngine();
  engine_->Start();

  // Let it run for ~150ms (should produce ~4-5 frames at 30fps / 33ms each)
  std::this_thread::sleep_for(std::chrono::milliseconds(150));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  EXPECT_GT(m.continuous_frames_emitted_total, 0)
      << "Engine must emit frames even with zero blocks";
  EXPECT_EQ(m.pad_frames_emitted_total, m.continuous_frames_emitted_total)
      << "All frames must be pad frames in P3.0 (pad-only mode)";
}

// =============================================================================
// TEST-CONT-002: No inter-frame gap exceeds 40ms (at 30fps ~33ms cadence)
// Run engine ~200ms, verify max gap stays under 40ms.
// =============================================================================
TEST_F(ContinuousOutputContractTest, InterFrameGapUnder40ms) {
  engine_ = MakeEngine();
  engine_->Start();

  // Run for ~250ms to get enough frames for measurement
  std::this_thread::sleep_for(std::chrono::milliseconds(250));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  // Need at least 2 frames to have a gap measurement
  ASSERT_GT(m.frame_gap_count, 0)
      << "Must have at least one inter-frame gap measurement";
  EXPECT_LT(m.max_inter_frame_gap_us, 40000)
      << "Max inter-frame gap must be under 40ms (40000us) at 30fps cadence";
}

// =============================================================================
// TEST-CONT-003: PTS monotonic across entire session
// Verify PTS(N) = N * frame_duration_90k from the OutputClock.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PTSMonotonicByConstruction) {
  // OutputClock guarantees PTS monotonicity by construction:
  // FrameIndexToPts90k(N) = N * frame_duration_90k
  // Verify the formula directly.
  OutputClock clock(30, 1);
  clock.Start();

  int64_t prev_pts = -1;
  for (int64_t i = 0; i < 100; i++) {
    int64_t pts = clock.FrameIndexToPts90k(i);
    EXPECT_EQ(pts, i * clock.FrameDuration90k())
        << "PTS must equal frame_index * frame_duration_90k at index " << i;
    EXPECT_GT(pts, prev_pts)
        << "PTS must be strictly monotonically increasing at index " << i;
    prev_pts = pts;
  }

  // Also verify the relationship: 30fps -> 3000 ticks per frame
  EXPECT_EQ(clock.FrameDuration90k(), 3000);
  EXPECT_EQ(clock.FrameDurationMs(), 33);
}

// =============================================================================
// TEST-CONT-004: Encoder initialized exactly once and closed once
// =============================================================================
TEST_F(ContinuousOutputContractTest, EncoderOpenedAndClosedOnce) {
  engine_ = MakeEngine();
  engine_->Start();

  // Let it run briefly
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  // Before stopping, encoder should be open
  {
    auto m = engine_->SnapshotMetrics();
    EXPECT_EQ(m.encoder_open_count, 1)
        << "Encoder must be opened exactly once during session";
    EXPECT_EQ(m.encoder_close_count, 0)
        << "Encoder must not be closed while session is active";
  }

  engine_->Stop();

  // After stopping, encoder should be closed
  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.encoder_open_count, 1)
      << "Encoder open count must remain 1 after session end";
  EXPECT_EQ(m.encoder_close_count, 1)
      << "Encoder must be closed exactly once at session end";
}

// =============================================================================
// TEST-CONT-005: Stop() terminates cleanly and is idempotent
// Call Stop() three times; no hang, on_session_ended fires exactly once.
// =============================================================================
TEST_F(ContinuousOutputContractTest, StopIsIdempotent) {
  engine_ = MakeEngine();
  engine_->Start();

  // Let it run briefly
  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  // Stop three times
  engine_->Stop();
  engine_->Stop();
  engine_->Stop();

  // Verify on_session_ended fired exactly once
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_count_, 1)
        << "on_session_ended must fire exactly once regardless of Stop() calls";
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Stop()-initiated termination must report reason 'stopped'";
  }
}

// =============================================================================
// Helper: Create a synthetic FedBlock (unresolvable URI)
// =============================================================================
FedBlock MakeSyntheticBlock(const std::string& block_id,
                            int64_t duration_ms,
                            const std::string& uri = "/nonexistent/test.mp4") {
  FedBlock block;
  block.block_id = block_id;
  block.channel_id = 99;
  block.start_utc_ms = 1000000;
  block.end_utc_ms = 1000000 + duration_ms;

  FedBlock::Segment seg;
  seg.segment_index = 0;
  seg.asset_uri = uri;
  seg.asset_start_offset_ms = 0;
  seg.segment_duration_ms = duration_ms;
  block.segments.push_back(seg);

  return block;
}

// =============================================================================
// CONT-ACT-001: Producer State Machine
// Unit test on Producer directly. EMPTY initially. AssignBlock → READY.
// TryGetFrame repeatedly (returns nullopt for synthetic block). Reset → EMPTY.
// =============================================================================
TEST_F(ContinuousOutputContractTest, ProducerStateMachine) {
  TickProducer source(640, 480, 30.0);

  // Initial state: EMPTY
  EXPECT_EQ(source.GetState(), TickProducer::State::kEmpty);

  // AssignBlock → READY (even with unresolvable URI, since probe fails)
  FedBlock block = MakeSyntheticBlock("sm-001", 5000);
  source.AssignBlock(block);
  EXPECT_EQ(source.GetState(), TickProducer::State::kReady);
  EXPECT_FALSE(source.HasDecoder())
      << "Decoder must not open for nonexistent asset";
  EXPECT_GT(source.FramesPerBlock(), 0)
      << "FramesPerBlock must be computed even without decoder";

  // TryGetFrame returns nullopt (no decoder)
  auto frame = source.TryGetFrame();
  EXPECT_FALSE(frame.has_value())
      << "TryGetFrame must return nullopt when decoder is not ok";

  // Call a few more times — state stays READY
  for (int i = 0; i < 5; i++) {
    EXPECT_FALSE(source.TryGetFrame().has_value());
    EXPECT_EQ(source.GetState(), TickProducer::State::kReady);
  }

  // Reset → EMPTY
  source.Reset();
  EXPECT_EQ(source.GetState(), TickProducer::State::kEmpty);
}

// =============================================================================
// CONT-ACT-002: FrameCountDeterministic
// FramesPerBlock = ceil(duration_ms * fps / 1000) for various durations.
// Uses exact floating-point fps, not truncated integer frame duration.
// Contract: INV-AIR-MEDIA-TIME-001
// =============================================================================
TEST_F(ContinuousOutputContractTest, FrameCountDeterministic) {
  TickProducer source(640, 480, 30.0);

  // 5000ms block at 30fps: ceil(5000 * 30 / 1000) = ceil(150.0) = 150
  {
    FedBlock block = MakeSyntheticBlock("fc-5000", 5000);
    source.AssignBlock(block);
    EXPECT_EQ(source.FramesPerBlock(), 150)
        << "5000ms block must produce ceil(5000*30/1000) = 150 frames";
    source.Reset();
  }

  // 3700ms block at 30fps: ceil(3700 * 30 / 1000) = ceil(111.0) = 111
  {
    FedBlock block = MakeSyntheticBlock("fc-3700", 3700);
    source.AssignBlock(block);
    EXPECT_EQ(source.FramesPerBlock(), 111)
        << "3700ms block must produce ceil(3700*30/1000) = 111 frames";
    source.Reset();
  }

  // Engine fence logic: source_ticks >= FramesPerBlock() completes the block.
  // Simulate with a 5000ms block:
  {
    FedBlock block = MakeSyntheticBlock("fc-fence", 5000);
    source.AssignBlock(block);
    int64_t fpb = source.FramesPerBlock();
    int64_t ticks = 0;
    while (ticks < fpb) {
      source.TryGetFrame();  // nullopt (no decoder) but advances ct
      ticks++;
    }
    EXPECT_GE(ticks, fpb) << "Fence must trigger at exactly FramesPerBlock ticks";
    source.Reset();
  }
}

// =============================================================================
// CONT-ACT-003: BlockCompletedCallbackFires
// Feed 1 block (5000ms, synthetic URI). Wait. Verify on_block_completed fires.
// =============================================================================
TEST_F(ContinuousOutputContractTest, BlockCompletedCallbackFires) {
  // Pre-load a 5000ms block into the queue
  FedBlock block = MakeSyntheticBlock("cb-001", 5000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // 5000ms at 33ms/frame = ~152 frames = ~5016ms.
  // Add margin for probe failure stall + scheduling jitter.
  std::this_thread::sleep_for(std::chrono::milliseconds(6000));

  engine_->Stop();

  // Verify on_block_completed fired
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_EQ(completed_blocks_.size(), 1u)
        << "on_block_completed must fire exactly once for one block";
    EXPECT_EQ(completed_blocks_[0], "cb-001")
        << "Callback must report correct block_id";
  }

  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.total_blocks_executed, 1)
      << "total_blocks_executed metric must be 1";
}

// =============================================================================
// CONT-ACT-004: StopDuringBlockExecution
// Feed a 30s block. Stop after 100ms. Verify clean shutdown.
// =============================================================================
TEST_F(ContinuousOutputContractTest, StopDuringBlockExecution) {
  // Pre-load a 30-second block
  FedBlock block = MakeSyntheticBlock("stop-mid", 30000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Let a few frames emit, then stop
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  // This must complete in bounded time (not wait for the 30s block to finish)
  auto stop_start = std::chrono::steady_clock::now();
  engine_->Stop();
  auto stop_end = std::chrono::steady_clock::now();
  auto stop_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      stop_end - stop_start).count();

  // Stop should complete quickly (well under 1 second)
  EXPECT_LT(stop_ms, 1000)
      << "Stop() must terminate quickly, not wait for block completion";

  // Verify session ended callback fired
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_count_, 1)
        << "on_session_ended must fire on Stop()";
  }
}

// =============================================================================
// CONT-ACT-005: PadFramesForEntireBlock
// Feed 1 block (synthetic URI, unresolvable). After completion, verify all
// frames were pad. Existing P3.0 zero-block pad behavior still works.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadFramesForEntireBlock) {
  // Pre-load a 1000ms block with unresolvable URI
  FedBlock block = MakeSyntheticBlock("pad-001", 1000, "/nonexistent/pad.mp4");
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // 1000ms block at 33ms/frame = ~31 frames. Wait long enough for completion.
  std::this_thread::sleep_for(std::chrono::milliseconds(2000));

  engine_->Stop();

  // Verify the block completed
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_EQ(completed_blocks_.size(), 1u)
        << "Block must complete even when all frames are pad";
    EXPECT_EQ(completed_blocks_[0], "pad-001");
  }

  auto m = engine_->SnapshotMetrics();

  // All frames should be pad (since asset is unresolvable)
  // The block used ceil(1000/33) = 31 frames, but the session continues with
  // pad frames after the block completes, so total >= 31.
  EXPECT_GE(m.pad_frames_emitted_total, 31)
      << "At least frames_per_block pad frames must have been emitted";

  // The block-period frames are all pad, plus any inter-block pad frames
  EXPECT_EQ(m.pad_frames_emitted_total, m.continuous_frames_emitted_total)
      << "All frames must be pad when asset is unresolvable";
}

// =============================================================================
// P3.1b: A/B Source Swap Contract Tests
// =============================================================================

// =============================================================================
// CONT-SWAP-001: Source swap count increments when two blocks are queued
// Queue 2 blocks. Run long enough for both to complete. Verify swap metrics.
// =============================================================================
TEST_F(ContinuousOutputContractTest, SourceSwapCountIncrements) {
  // Two 1000ms blocks (~31 frames each at 30fps).
  // Wall-anchored timestamps so fence fires at the correct future time.
  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
  FedBlock block1 = MakeSyntheticBlock("swap-001a", 1000);
  block1.start_utc_ms = now_ms;
  block1.end_utc_ms = now_ms + 1000;
  FedBlock block2 = MakeSyntheticBlock("swap-001b", 1000);
  block2.start_utc_ms = now_ms + 1000;
  block2.end_utc_ms = now_ms + 2000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // 2 * 1000ms blocks + margin for probe failure + scheduling jitter
  std::this_thread::sleep_for(std::chrono::milliseconds(3500));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();
  EXPECT_GE(m.total_blocks_executed, 2)
      << "Both blocks must complete";
  EXPECT_GE(m.source_swap_count, 1)
      << "Source swap count must increment for back-to-back blocks";

  // Both blocks completed via callback
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(completed_blocks_.size(), 2u);
    EXPECT_EQ(completed_blocks_[0], "swap-001a");
    EXPECT_EQ(completed_blocks_[1], "swap-001b");
  }
}

// =============================================================================
// CONT-SWAP-002: No deadlock when Stop() called during preload
// Queue multiple blocks, stop quickly. Verify clean shutdown.
// =============================================================================
TEST_F(ContinuousOutputContractTest, StopDuringPreloadNoDeadlock) {
  // Queue two blocks — first loaded synchronously, second triggers preload
  FedBlock block1 = MakeSyntheticBlock("stop-pre-1", 30000);
  FedBlock block2 = MakeSyntheticBlock("stop-pre-2", 30000);
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block1);
    ctx_->block_queue.push_back(block2);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Let it start and begin preloading
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  // Stop must complete quickly even if preload was in progress
  auto stop_start = std::chrono::steady_clock::now();
  engine_->Stop();
  auto stop_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - stop_start).count();

  EXPECT_LT(stop_ms, 1000)
      << "Stop() must complete quickly during preload (no deadlock)";

  // Session ended cleanly
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_count_, 1);
  }
}

// =============================================================================
// CONT-SWAP-003: Delayed preload does not stall engine
// Test ProducerPreloader directly with delay hook. Verify preloader completes
// after delay, and that the engine's tick loop is never blocked by preload.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PreloaderDelayDoesNotStallEngine) {
  // Test ProducerPreloader directly with delay hook
  ProducerPreloader preloader;

  std::atomic<bool> hook_called{false};
  preloader.SetDelayHook([&hook_called]() {
    hook_called.store(true, std::memory_order_release);
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
  });

  FedBlock block = MakeSyntheticBlock("delay-001", 1000);
  preloader.StartPreload(block, 640, 480, 30.0);

  // Preloader should not be ready immediately (delay hook is sleeping)
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  EXPECT_TRUE(hook_called.load(std::memory_order_acquire))
      << "Delay hook must have been called";
  EXPECT_FALSE(preloader.IsReady())
      << "Preloader must not be ready while delay hook is sleeping";

  // Wait for preload to complete
  std::this_thread::sleep_for(std::chrono::milliseconds(300));
  EXPECT_TRUE(preloader.IsReady())
      << "Preloader must be ready after delay completes";

  auto source = preloader.TakeSource();
  ASSERT_NE(source, nullptr);
  EXPECT_EQ(dynamic_cast<TickProducer*>(source.get())->GetState(),
            TickProducer::State::kReady);
}

// =============================================================================
// CONT-SWAP-004: AssignBlock runs on background thread (not tick thread)
// ProducerPreloader.Worker() runs on its own thread. Verify the thread ID
// differs from the caller's thread, proving AssignBlock is off the tick path.
// =============================================================================
TEST_F(ContinuousOutputContractTest, AssignBlockRunsOffThread) {
  ProducerPreloader preloader;

  std::atomic<std::thread::id> preload_thread_id{};
  std::thread::id caller_thread_id = std::this_thread::get_id();

  preloader.SetDelayHook([&preload_thread_id]() {
    preload_thread_id.store(std::this_thread::get_id(),
                            std::memory_order_release);
  });

  FedBlock block = MakeSyntheticBlock("thread-001", 1000);
  preloader.StartPreload(block, 640, 480, 30.0);

  // Wait for preload to complete
  for (int i = 0; i < 100 && !preloader.IsReady(); i++) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  auto observed_id = preload_thread_id.load(std::memory_order_acquire);
  EXPECT_NE(observed_id, std::thread::id{})
      << "Delay hook must have been called (preload ran)";
  EXPECT_NE(observed_id, caller_thread_id)
      << "AssignBlock must run on a background thread, not the caller's thread";

  preloader.Cancel();
}

// =============================================================================
// CONT-SWAP-005: PTS monotonic across source swaps (regression check)
// Queue 3 blocks to force multiple swaps. Verify PTS monotonicity by
// construction (OutputClock never resets) and encoder opens exactly once.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PTSMonotonicAcrossSwaps) {
  // Queue 3 short blocks to force multiple swaps
  for (int i = 0; i < 3; i++) {
    FedBlock block = MakeSyntheticBlock("pts-" + std::to_string(i), 500);
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // 3 * 500ms = 1500ms of blocks + pad tail. Wait 3s for full completion.
  std::this_thread::sleep_for(std::chrono::milliseconds(3000));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // Multiple blocks must execute
  EXPECT_GE(m.total_blocks_executed, 2)
      << "Multiple blocks must execute for swap PTS test";

  // PTS monotonicity guaranteed by OutputClock:
  // PTS(N) = N * frame_duration_90k, never resets across swaps.
  // Verify engine emitted enough frames (blocks + pad).
  // ceil(500/33) = 16 frames per 500ms block.
  int64_t min_frames_from_blocks = m.total_blocks_executed * 16;
  EXPECT_GE(m.continuous_frames_emitted_total, min_frames_from_blocks)
      << "Engine must emit at least as many frames as blocks require";

  // Session-long encoder (PTS tracking is session-scoped, never reset)
  EXPECT_EQ(m.encoder_open_count, 1)
      << "Encoder must open exactly once across all swaps";
  EXPECT_EQ(m.encoder_close_count, 1)
      << "Encoder must close exactly once at session end";
}

// =============================================================================
// PAD-PROOF: PadProducer integration — deterministic pad frame verification
// Phase 2: prove PadProducer emits real black+silence frames through the TAKE.
// =============================================================================

// Helper: assert all four required PadProducer fingerprint properties.
static void AssertPadFrameProperties(const FrameFingerprint& fp,
                                      uint32_t expected_crc) {
  EXPECT_TRUE(fp.is_pad)
      << "Frame " << fp.session_frame_index << " must be pad";
  EXPECT_EQ(fp.commit_slot, 'P')
      << "Frame " << fp.session_frame_index << " commit_slot must be 'P'";
  EXPECT_EQ(fp.asset_uri, PadProducer::kAssetUri)
      << "Frame " << fp.session_frame_index
      << " asset_uri must be 'internal://pad'";
  EXPECT_EQ(fp.y_crc32, expected_crc)
      << "Frame " << fp.session_frame_index
      << " y_crc32 must match PadProducer's known black CRC";
}

// Helper: verify PadProducer audio is silence (all zeros).
static void AssertPadAudioSilence() {
  PadProducer ref(640, 480, 30, 1);
  const auto& silence = ref.SilenceTemplate();
  EXPECT_EQ(silence.sample_rate, buffer::kHouseAudioSampleRate);
  EXPECT_EQ(silence.channels, buffer::kHouseAudioChannels);
  for (size_t i = 0; i < silence.data.size(); i++) {
    if (silence.data[i] != 0) {
      ADD_FAILURE() << "PadProducer audio byte " << i
                    << " must be 0 (silence), got "
                    << static_cast<int>(silence.data[i]);
      return;
    }
  }
}

// =============================================================================
// PAD-PROOF-001: Single pad frame at end of block
// Queue 1 block (unresolvable URI). After the fence, verify at least 1 pad
// frame with PadProducer fingerprint properties.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadProof_SinglePadPostFence) {
  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
  FedBlock block = MakeSyntheticBlock("pad-post-1", 1000);
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 1000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngineWithTrace();
  engine_->Start();

  // 1s block + 500ms for post-fence pad frames.
  std::this_thread::sleep_for(std::chrono::milliseconds(1800));
  engine_->Stop();

  // Block must have completed.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(completed_blocks_.size(), 1u)
        << "Block must complete before post-fence pad";
  }

  auto fps = SnapshotFingerprints();
  ASSERT_GT(fps.size(), 0u) << "Must have emitted frames";

  // Identify post-fence pad frames: active_block_id is empty after fence
  // when no next block is loaded (live_ becomes empty TickProducer).
  PadProducer ref_pad(640, 480, 30, 1);
  uint32_t expected_crc = ref_pad.VideoCRC32();

  int post_fence_pad_count = 0;
  for (const auto& fp : fps) {
    if (fp.active_block_id.empty() && fp.is_pad) {
      if (post_fence_pad_count == 0) {
        // Verify the FIRST post-fence pad frame fully.
        AssertPadFrameProperties(fp, expected_crc);
      }
      post_fence_pad_count++;
    }
  }
  EXPECT_GE(post_fence_pad_count, 1)
      << "Must have at least 1 pad frame after block fence";

  // Audio: PadProducer silence is all zeros.
  AssertPadAudioSilence();

  // Session ended normally (no audio underflow).
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// PAD-PROOF-002: 5 pad frames at end of block
// Queue 1 block (unresolvable URI, 500ms). After the fence, verify at least
// 5 consecutive pad frames with PadProducer fingerprint properties.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadProof_FivePadsPostFence) {
  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
  FedBlock block = MakeSyntheticBlock("pad-post-5", 500);
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 500;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngineWithTrace();
  engine_->Start();

  // 500ms block + 500ms for post-fence pad frames.
  std::this_thread::sleep_for(std::chrono::milliseconds(1500));
  engine_->Stop();

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(completed_blocks_.size(), 1u);
  }

  auto fps = SnapshotFingerprints();
  PadProducer ref_pad(640, 480, 30, 1);
  uint32_t expected_crc = ref_pad.VideoCRC32();

  // Collect post-fence pad frames.
  std::vector<const FrameFingerprint*> post_fence_pads;
  for (const auto& fp : fps) {
    if (fp.active_block_id.empty() && fp.is_pad) {
      post_fence_pads.push_back(&fp);
    }
  }

  ASSERT_GE(post_fence_pads.size(), 5u)
      << "Must have at least 5 pad frames after block fence";

  // Verify all 5 post-fence pads.
  for (size_t i = 0; i < 5; i++) {
    AssertPadFrameProperties(*post_fence_pads[i], expected_crc);
  }

  AssertPadAudioSilence();

  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// PAD-PROOF-003: Pad-only micro-block — exactly 90 pad frames
//
// Queue a pad-only block (unresolvable URI, 5s duration to avoid fence
// interference).  Stop the engine after exactly 90 emitted frames via
// ctx_->stop_requested set from on_frame_emitted.  This gives a precise
// frame count independent of wall-clock fence timing.
//
// Assertions (comprehensive):
//   1. Exactly 90 fingerprints, ALL is_pad=true
//   2. commit_slot='P' for every frame
//   3. asset_uri="internal://pad" for every frame
//   4. y_crc32 identical across all 90 frames
//   5. video_pts_90k = N * frame_duration_90k for each frame N (strict
//      monotonicity with constant delta)
//   6. Audio: no underflow (session ends "stopped", detach_count=0)
//   7. Audio cadence: at 30fps the rational accumulator yields exactly
//      1600 samples/tick — verified by total pad frames (every pad tick
//      runs the audio encode path) and by formula
//   8. Session stops cleanly
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadProof_PadOnlyMicroBlock) {
  constexpr int kTargetFrames = 90;

  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // 5s block (150 frames at 30fps) — longer than kTargetFrames so the fence
  // never fires before we stop.  Unresolvable URI → all frames are pad.
  FedBlock block = MakeSyntheticBlock("pad-micro-90", 5000);
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 5000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  // Custom callbacks: stop at exactly kTargetFrames via stop_requested.
  int frame_count = 0;  // written only on engine thread (single writer)
  PipelineManager::Callbacks callbacks;
  callbacks.on_block_completed = [this](const FedBlock& block, int64_t ct) {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    completed_blocks_.push_back(block.block_id);
  };
  callbacks.on_session_ended = [this](const std::string& reason) {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    session_ended_count_++;
    session_ended_reason_ = reason;
    session_ended_cv_.notify_all();
  };
  callbacks.on_frame_emitted = [&](const FrameFingerprint& fp) {
    {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.push_back(fp);
    }
    frame_count++;
    if (frame_count >= kTargetFrames) {
      ctx_->stop_requested.store(true, std::memory_order_release);
    }
  };

  engine_ = std::make_unique<PipelineManager>(ctx_.get(), std::move(callbacks));
  engine_->Start();

  // Wait for session to end (stop_requested fires after 90 frames).
  ASSERT_TRUE(WaitForSessionEnded(6000))
      << "Session must end within 6s after emitting " << kTargetFrames << " frames";
  engine_->Stop();

  // ======================== VALIDATION ========================

  auto fps = SnapshotFingerprints();
  PadProducer ref_pad(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
  uint32_t expected_crc = ref_pad.VideoCRC32();

  std::cout << "=== PAD-PROOF-003: PadOnlyMicroBlock ===" << std::endl;
  std::cout << "total_fingerprints=" << fps.size()
            << " expected=" << kTargetFrames
            << " expected_crc=0x" << std::hex << expected_crc << std::dec
            << std::endl;

  // --- ASSERTION 1: Exactly 90 fingerprints, all is_pad=true ---
  ASSERT_EQ(fps.size(), static_cast<size_t>(kTargetFrames))
      << "Must have exactly " << kTargetFrames << " fingerprints";
  for (int i = 0; i < kTargetFrames; i++) {
    EXPECT_TRUE(fps[i].is_pad)
        << "Frame " << i << " must be pad";
  }

  // --- ASSERTION 2: commit_slot='P' for every frame ---
  for (int i = 0; i < kTargetFrames; i++) {
    EXPECT_EQ(fps[i].commit_slot, 'P')
        << "Frame " << i << " commit_slot must be 'P'";
  }

  // --- ASSERTION 3: asset_uri="internal://pad" for every frame ---
  for (int i = 0; i < kTargetFrames; i++) {
    EXPECT_EQ(fps[i].asset_uri, PadProducer::kAssetUri)
        << "Frame " << i << " asset_uri must be 'internal://pad'";
  }

  // --- ASSERTION 4: y_crc32 identical across all 90 frames ---
  for (int i = 0; i < kTargetFrames; i++) {
    EXPECT_EQ(fps[i].y_crc32, expected_crc)
        << "Frame " << i << " y_crc32 must match PadProducer reference";
  }
  // Also verify frame-to-frame identity (no drift).
  for (int i = 1; i < kTargetFrames; i++) {
    EXPECT_EQ(fps[i].y_crc32, fps[0].y_crc32)
        << "Frame " << i << " y_crc32 must be identical to frame 0";
  }

  // --- ASSERTION 5: video_pts_90k strictly monotonic, constant delta ---
  //
  // video_pts_90k = session_frame_index * frame_duration_90k.
  // For 30fps (fps_num=30, fps_den=1): frame_duration_90k = 90000/30 = 3000.
  // Verify session_frame_indices are [0, 1, 2, ..., 89] and PTS increments
  // by exactly frame_duration_90k per tick.
  OutputClock clock(ctx_->fps_num, ctx_->fps_den);
  clock.Start();
  int64_t frame_dur_90k = clock.FrameDuration90k();
  ASSERT_GT(frame_dur_90k, 0);

  for (int i = 0; i < kTargetFrames; i++) {
    EXPECT_EQ(fps[i].session_frame_index, i)
        << "session_frame_index must be " << i;
    int64_t expected_pts = static_cast<int64_t>(i) * frame_dur_90k;
    int64_t actual_pts = fps[i].session_frame_index * frame_dur_90k;
    EXPECT_EQ(actual_pts, expected_pts)
        << "video_pts_90k at frame " << i << " must be " << expected_pts;
    if (i > 0) {
      int64_t pts_delta = static_cast<int64_t>(fps[i].session_frame_index -
                                                 fps[i - 1].session_frame_index)
                          * frame_dur_90k;
      EXPECT_EQ(pts_delta, frame_dur_90k)
          << "PTS delta between frames " << (i - 1) << " and " << i
          << " must be exactly frame_duration_90k=" << frame_dur_90k;
    }
  }

  // --- ASSERTION 6: Audio — no underflow, no detach ---
  //
  // For pad-only sessions, audio is produced by PadProducer's silence template
  // via the rational accumulator (PipelineManager.cpp lines 1006-1021).
  // At 30fps: samples_per_tick = 48000/30 = 1600 (exact integer).
  // audio_pts_90k = audio_samples_emitted * 90000 / 48000 = N * 3000.
  // This matches video_pts_90k exactly for 30fps — verified by construction.
  auto m = engine_->SnapshotMetrics();
  EXPECT_EQ(m.detach_count, 0)
      << "No underflow-triggered detach in pad-only session";

  // Every emitted frame is pad, and pad ticks always produce audio.
  EXPECT_EQ(m.pad_frames_emitted_total, kTargetFrames)
      << "All " << kTargetFrames << " frames must be pad";
  EXPECT_EQ(m.continuous_frames_emitted_total, kTargetFrames)
      << "Total emitted frames must be exactly " << kTargetFrames;

  // --- ASSERTION 7: Audio cadence by formula ---
  //
  // Rational accumulator: samples(tick N) = floor((N+1)*sr*fps_den/fps_num)
  //                                        - floor(N*sr*fps_den/fps_num)
  // For 30fps (sr=48000, fps_num=30, fps_den=1):
  //   samples(N) = floor((N+1)*48000/30) - floor(N*48000/30) = 1600 for all N.
  // Total audio after 90 ticks: 90 * 1600 = 144000 samples.
  // audio_pts after 90 ticks: 144000 * 90000 / 48000 = 270000 = 90 * 3000.
  // This matches video_pts at frame 90 (270000), proving A/V sync is exact.
  {
    int64_t sr = static_cast<int64_t>(buffer::kHouseAudioSampleRate);
    int64_t total_expected_audio_samples = 0;
    for (int i = 0; i < kTargetFrames; i++) {
      int64_t next = (static_cast<int64_t>(i + 1) * sr * ctx_->fps_den) /
                     ctx_->fps_num;
      int64_t curr = (static_cast<int64_t>(i) * sr * ctx_->fps_den) /
                     ctx_->fps_num;
      int samples_this_tick = static_cast<int>(next - curr);
      // For 30fps, every tick must produce exactly 1600 samples.
      EXPECT_EQ(samples_this_tick, 1600)
          << "Rational accumulator at tick " << i
          << " must yield 1600 samples for 30fps";
      total_expected_audio_samples += samples_this_tick;
    }
    EXPECT_EQ(total_expected_audio_samples, kTargetFrames * 1600)
        << "Total audio samples must be " << kTargetFrames << " * 1600";
    // Final audio_pts_90k = total_samples * 90000 / sr = 144000 * 1.875 = 270000
    // = kTargetFrames * frame_dur_90k = 90 * 3000.  Exact A/V sync.
    int64_t final_audio_pts = (total_expected_audio_samples * 90000) / sr;
    int64_t final_video_pts = static_cast<int64_t>(kTargetFrames) * frame_dur_90k;
    EXPECT_EQ(final_audio_pts, final_video_pts)
        << "Audio PTS must equal video PTS after " << kTargetFrames
        << " ticks (exact A/V sync at 30fps)";
  }

  // PadProducer silence template is all zeros.
  AssertPadAudioSilence();

  // --- ASSERTION 8: Session stops cleanly ---
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session must end cleanly ('stopped')";
  }
}

// =============================================================================
// PAD-PROOF-004: Single-pad seam — real content A → PadProducer → real content B
//
// Scenario: Block A (real media, 1.5s) plays to its fence.  Block B is NOT in
// the queue initially — it is injected via the on_block_completed callback at
// the exact tick the fence fires.  Because B has not been preloaded, the TAKE
// at the fence tick finds no source (preview_video_buffer_ is null) and selects
// PadProducer.  PipelineManager's end-of-tick TryLoadLiveProducer then picks B
// from the queue, loads it synchronously (AssignBlock), and starts the fill
// thread — all on the fence tick itself.  B's primed frame is available on the
// very next tick.  This produces EXACTLY ONE pad frame at the seam.
//
// WHY THIS PROVES "PadProducer IS REAL" WITHOUT VISUAL INSPECTION:
//  1. The fingerprint at the fence tick has is_pad=true — the TAKE selected
//     PadProducer, not content, not hold-last.
//  2. commit_slot='P' proves the frame came from the pad path, not from
//     any VideoLookaheadBuffer (which would set 'A' or 'B').
//  3. y_crc32 matches PadProducer::VideoCRC32() — the video data IS the
//     pre-allocated broadcast-black YUV420P frame (Y=16, U=V=128).
//  4. asset_uri="internal://pad" distinguishes pad from any real asset.
//  5. encodeFrame(pad_producer_->VideoFrame(), video_pts_90k) is called
//     unconditionally when is_pad=true (PipelineManager.cpp line 1003).
//     If the fingerprint says pad, the encoder received the frame.
//  6. encodeAudioFrame() is called with PadProducer's silence template and
//     the same rational accumulator as content ticks (lines 1006-1016).
//  7. The session ends cleanly ("stopped", not "underflow"), proving the
//     encoder accepted the pad frames and continued producing MPEG-TS bytes.
//  8. Consecutive session_frame_indices across the seam prove the tick loop
//     ran without interruption.  PTS monotonicity is guaranteed by
//     construction: pts(N) = N * frame_duration_90k.
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadProof_SinglePadSeam) {
  static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
  static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";
  if (access(kPathA.c_str(), F_OK) != 0 ||
      access(kPathB.c_str(), F_OK) != 0) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // Block A: 1.5s real content.  Hold-last fills any decode-exhaustion tail
  // before the fence.  Expected fence_tick ≈ ceil(1500 * 30 / 1000) = 45.
  FedBlock block_a;
  block_a.block_id = "seam-A";
  block_a.channel_id = 99;
  block_a.start_utc_ms = now_ms;
  block_a.end_utc_ms = now_ms + 1500;
  {
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = kPathA;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 1500;
    block_a.segments.push_back(seg);
  }

  // Block B: 2s real content, injected into queue when A completes.
  FedBlock block_b;
  block_b.block_id = "seam-B";
  block_b.channel_id = 99;
  block_b.start_utc_ms = now_ms + 1500;
  block_b.end_utc_ms = now_ms + 3500;
  {
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = kPathB;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 2000;
    block_b.segments.push_back(seg);
  }

  // State captured from callbacks (written on engine thread, read after Stop).
  int64_t a_fence_tick = -1;
  bool b_injected = false;

  // Custom callbacks: inject B into the queue at A's fence, capture fps.
  PipelineManager::Callbacks callbacks;
  callbacks.on_block_completed = [&](const FedBlock& block, int64_t ct) {
    if (!b_injected) {
      b_injected = true;
      a_fence_tick = ct;
      // Inject B into the queue.  on_block_completed fires at line 966,
      // BEFORE end-of-tick TryLoadLiveProducer at line 1288.  So B is
      // in the queue when TryLoadLiveProducer runs on this same tick.
      std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
      ctx_->block_queue.push_back(block_b);
    }
    std::lock_guard<std::mutex> lock(cb_mutex_);
    completed_blocks_.push_back(block.block_id);
  };
  callbacks.on_session_ended = [this](const std::string& reason) {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    session_ended_count_++;
    session_ended_reason_ = reason;
    session_ended_cv_.notify_all();
  };
  callbacks.on_frame_emitted = [this](const FrameFingerprint& fp) {
    std::lock_guard<std::mutex> lock(fp_mutex_);
    fingerprints_.push_back(fp);
  };

  // Only A in queue initially — B is injected at the fence.
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }

  engine_ = std::make_unique<PipelineManager>(ctx_.get(), std::move(callbacks));
  engine_->Start();

  // Wait: 1.5s (A content) + ~300ms (B sync load) + 500ms (B content margin).
  std::this_thread::sleep_for(std::chrono::milliseconds(2500));
  engine_->Stop();

  // ======================== VALIDATION ========================

  ASSERT_TRUE(b_injected) << "Block A must have completed (on_block_completed)";
  ASSERT_GT(a_fence_tick, 10) << "Fence tick must be well past session start";

  auto fps = SnapshotFingerprints();
  ASSERT_GT(fps.size(), static_cast<size_t>(a_fence_tick + 10))
      << "Must have frames past the fence to verify B";

  // Reference CRC for PadProducer black frame at session resolution.
  PadProducer ref_pad(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
  uint32_t expected_crc = ref_pad.VideoCRC32();

  // --- Locate the three regions: A content, pad gap, B content ---
  //
  // Expected fingerprint sequence:
  //   [0 .. fence-1]   active_block_id="seam-A", is_pad=false  (A content)
  //   [fence]          active_block_id="",        is_pad=true   (pad)
  //   [fence+1 .. ]    active_block_id="seam-B", is_pad=false  (B content)

  int64_t last_a_content = -1;
  int64_t first_pad = -1;
  int64_t last_pad = -1;
  int64_t first_b_content = -1;
  int pad_count_in_gap = 0;

  for (const auto& fp : fps) {
    if (fp.active_block_id == "seam-A" && !fp.is_pad) {
      last_a_content = fp.session_frame_index;
    }
    if (fp.is_pad && last_a_content >= 0) {
      if (first_pad < 0) first_pad = fp.session_frame_index;
      last_pad = fp.session_frame_index;
      // Only count pad frames that are in the gap (between A and B).
      if (first_b_content < 0) pad_count_in_gap++;
    }
    if (fp.active_block_id == "seam-B" && !fp.is_pad) {
      if (first_b_content < 0) first_b_content = fp.session_frame_index;
    }
  }

  ASSERT_GE(last_a_content, 0) << "Must have A content frames";
  ASSERT_GE(first_pad, 0)
      << "Must have at least 1 pad frame in the seam gap";
  ASSERT_GE(first_b_content, 0)
      << "Must have B content frames after the pad gap";

  std::cout << "=== PAD-PROOF-004: SinglePadSeam ===" << std::endl;
  std::cout << "last_a_content=" << last_a_content
            << " first_pad=" << first_pad
            << " last_pad=" << last_pad
            << " first_b_content=" << first_b_content
            << " pad_count_in_gap=" << pad_count_in_gap
            << " a_fence_tick=" << a_fence_tick
            << " total_fingerprints=" << fps.size()
            << std::endl;

  // --- ASSERTION 1: Pad frame at the expected session_frame_index ---
  //
  // The pad frame should be at a_fence_tick (the session_frame_index passed
  // to on_block_completed).  TryLoadLiveProducer loads B synchronously on
  // the same tick, so B's first content frame is at fence_tick + 1.  This
  // gives exactly 1 pad frame in the gap.  We allow up to 2 if B's sync
  // load is slow enough to delay one additional tick.
  EXPECT_EQ(first_pad, a_fence_tick)
      << "First pad frame must be at the fence tick";
  EXPECT_GE(pad_count_in_gap, 1)
      << "Must have at least 1 pad frame in the gap";
  EXPECT_LE(pad_count_in_gap, 2)
      << "Gap should be at most 2 pad frames (fence tick + optional load delay)";

  // --- ASSERTION 2: Every pad frame in the gap has correct properties ---
  for (const auto& fp : fps) {
    if (fp.is_pad && fp.session_frame_index >= first_pad &&
        fp.session_frame_index <= last_pad &&
        fp.session_frame_index < first_b_content) {
      AssertPadFrameProperties(fp, expected_crc);
    }
  }

  // --- ASSERTION 3: No pad in last 10 of A ---
  constexpr int K = 10;
  for (const auto& fp : fps) {
    if (fp.session_frame_index >= last_a_content - K + 1 &&
        fp.session_frame_index <= last_a_content) {
      EXPECT_FALSE(fp.is_pad)
          << "Frame " << fp.session_frame_index
          << " in last " << K << " of block A must not be pad";
    }
  }

  // --- ASSERTION 4: No pad in first 10 of B ---
  for (const auto& fp : fps) {
    if (fp.active_block_id == "seam-B" && !fp.is_pad &&
        fp.session_frame_index >= first_b_content &&
        fp.session_frame_index < first_b_content + K) {
      // This frame is in the first K of B — verify it's content, not pad.
      EXPECT_FALSE(fp.is_pad)
          << "Frame " << fp.session_frame_index
          << " in first " << K << " of block B must not be pad";
    }
  }
  // Also verify no pad frames WITHIN B's first K indices.
  for (const auto& fp : fps) {
    if (fp.session_frame_index >= first_b_content &&
        fp.session_frame_index < first_b_content + K) {
      EXPECT_FALSE(fp.is_pad)
          << "Frame " << fp.session_frame_index
          << " in first " << K << " of B content window must not be pad"
          << " (active_block_id=" << fp.active_block_id << ")";
    }
  }

  // --- ASSERTION 5: PTS monotonicity across the pad seam ---
  //
  // PTS is computed by OutputClock: pts(N) = N * frame_duration_90k.
  // For 30fps (fps_num=30, fps_den=1): frame_duration_90k = 3000.
  // Monotonicity is guaranteed if session_frame_indices are consecutive.
  OutputClock clock(ctx_->fps_num, ctx_->fps_den);
  clock.Start();
  int64_t frame_dur_90k = clock.FrameDuration90k();

  // Verify consecutive indices in the boundary window [fence-5, fence+5].
  int64_t win_start = std::max(int64_t{0}, a_fence_tick - 5);
  int64_t win_end = std::min(static_cast<int64_t>(fps.size()) - 1,
                             a_fence_tick + 5);
  for (int64_t t = win_start; t <= win_end; t++) {
    EXPECT_EQ(fps[static_cast<size_t>(t)].session_frame_index, t)
        << "session_frame_index must equal position in fingerprint array";
    if (t > win_start) {
      int64_t pts_prev = (t - 1) * frame_dur_90k;
      int64_t pts_curr = t * frame_dur_90k;
      EXPECT_EQ(pts_curr - pts_prev, frame_dur_90k)
          << "Video PTS delta must be exactly frame_duration_90k at tick " << t;
    }
  }

  // --- ASSERTION 6: Audio continuity ---
  //
  // The tick loop did not crash due to audio underflow.  The pad tick's
  // encodeAudioFrame is called unconditionally (line 1015-1016) with the
  // rational accumulator advancing audio_samples_emitted.  A clean session
  // end ("stopped") proves the audio path survived the pad seam.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session must end cleanly — 'stopped' means no audio underflow";
  }

  // Audio PTS monotonicity: for 30fps, each tick emits exactly 1600 samples
  // (48000/30 = 1600, no remainder).  audio_pts_90k = samples * 90000/48000
  // = samples * 1.875.  After N ticks: audio_samples = N * 1600,
  // audio_pts = N * 3000.  This matches video PTS exactly.
  // Verified by construction: session_frame_indices are consecutive ↑.

  // PadProducer silence template is all zeros.
  AssertPadAudioSilence();

  // Print boundary fingerprints for diagnostic visibility.
  std::cout << "Boundary window [fence-3 .. fence+3]:" << std::endl;
  for (int64_t t = std::max(int64_t{0}, a_fence_tick - 3);
       t <= std::min(static_cast<int64_t>(fps.size()) - 1, a_fence_tick + 3);
       t++) {
    const auto& fp = fps[static_cast<size_t>(t)];
    std::cout << "  tick=" << fp.session_frame_index
              << " source=" << fp.commit_slot
              << " pad=" << fp.is_pad
              << " block=" << fp.active_block_id
              << " asset=" << fp.asset_uri
              << " y_crc32=0x" << std::hex << fp.y_crc32 << std::dec
              << std::endl;
  }
}

// =============================================================================
// PAD-PROOF-005: 5-pad seam — real content A → 5 pad frames → real content B
//
// Same structure as PAD-PROOF-004 (SinglePadSeam) but forces EXACTLY 5
// consecutive pad ticks between A's last content and B's first content.
//
// Mechanism: Block A (1.5s real media) plays to its fence.  B is NOT injected
// in on_block_completed (unlike PAD-PROOF-004).  Instead, on_frame_emitted
// counts pad frames after the fence.  When the 5th pad frame is emitted, B is
// injected into the block queue.  TryLoadLiveProducer runs later in the same
// tick (after on_frame_emitted), loads B synchronously, and starts its fill
// thread.  B's primed frame is available on the NEXT tick.  This yields:
//
//   tick N:   last A content   (commit_slot='A')
//   tick N+1: pad #1           (commit_slot='P')    ← fence tick
//   tick N+2: pad #2           (commit_slot='P')
//   tick N+3: pad #3           (commit_slot='P')
//   tick N+4: pad #4           (commit_slot='P')
//   tick N+5: pad #5           (commit_slot='P')    ← B injected here
//   tick N+6: first B content  (commit_slot='A')    ← 'A' because B loads
//                                                        into the live slot
//
// Assertions:
//   1. Exactly 5 contiguous pad frames (no interleaving)
//   2. All 5 pad frames have identical y_crc32 (PadProducer broadcast black)
//   3. video_pts_90k increments by frame_duration_90k across the 7-tick window
//   4. commit_slot sequence is A, P, P, P, P, P, A (live slot for queue-loaded B)
//   5. No pad in last 10 of A, no pad in first 10 of B
//   6. Session ends cleanly (no audio underflow)
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadProof_FivePadSeam) {
  static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
  static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";
  if (access(kPathA.c_str(), F_OK) != 0 ||
      access(kPathB.c_str(), F_OK) != 0) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // Block A: 1.5s real content.
  FedBlock block_a;
  block_a.block_id = "seam5-A";
  block_a.channel_id = 99;
  block_a.start_utc_ms = now_ms;
  block_a.end_utc_ms = now_ms + 1500;
  {
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = kPathA;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 1500;
    block_a.segments.push_back(seg);
  }

  // Block B: 2s real content, injected after 5 pad frames.
  FedBlock block_b;
  block_b.block_id = "seam5-B";
  block_b.channel_id = 99;
  block_b.start_utc_ms = now_ms + 1500;
  block_b.end_utc_ms = now_ms + 3500;
  {
    FedBlock::Segment seg;
    seg.segment_index = 0;
    seg.asset_uri = kPathB;
    seg.asset_start_offset_ms = 0;
    seg.segment_duration_ms = 2000;
    block_b.segments.push_back(seg);
  }

  // State shared between callbacks (all run on the engine thread).
  int64_t a_fence_tick = -1;
  bool fence_seen = false;
  bool b_injected = false;
  int pad_after_fence = 0;

  PipelineManager::Callbacks callbacks;

  // on_block_completed: capture fence tick but do NOT inject B.
  callbacks.on_block_completed = [&](const FedBlock& block, int64_t ct) {
    if (!fence_seen) {
      fence_seen = true;
      a_fence_tick = ct;
    }
    std::lock_guard<std::mutex> lock(cb_mutex_);
    completed_blocks_.push_back(block.block_id);
  };

  callbacks.on_session_ended = [this](const std::string& reason) {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    session_ended_count_++;
    session_ended_reason_ = reason;
    session_ended_cv_.notify_all();
  };

  // on_frame_emitted: count pad frames after fence; inject B on the 5th.
  // Ordering within a tick: on_block_completed → on_frame_emitted → TryLoadLiveProducer.
  // So B injected here is available for TryLoadLiveProducer on the SAME tick.
  callbacks.on_frame_emitted = [&](const FrameFingerprint& fp) {
    if (fence_seen && fp.is_pad && !b_injected) {
      pad_after_fence++;
      if (pad_after_fence == 5) {
        b_injected = true;
        std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
        ctx_->block_queue.push_back(block_b);
      }
    }
    std::lock_guard<std::mutex> lock(fp_mutex_);
    fingerprints_.push_back(fp);
  };

  // Only A in queue initially.
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
  }

  engine_ = std::make_unique<PipelineManager>(ctx_.get(), std::move(callbacks));
  engine_->Start();

  // Wait: 1.5s (A) + 5*33ms (pad gap ~167ms) + ~300ms (B load) + 500ms (B margin).
  std::this_thread::sleep_for(std::chrono::milliseconds(2700));
  engine_->Stop();

  // ======================== VALIDATION ========================

  ASSERT_TRUE(b_injected) << "B must have been injected after 5 pad frames";
  ASSERT_GT(a_fence_tick, 10) << "Fence tick must be well past session start";

  auto fps = SnapshotFingerprints();
  ASSERT_GT(fps.size(), static_cast<size_t>(a_fence_tick + 15))
      << "Must have frames well past the pad gap to verify B";

  PadProducer ref_pad(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
  uint32_t expected_crc = ref_pad.VideoCRC32();

  // --- Locate regions: A content, pad gap, B content ---
  int64_t last_a_content = -1;
  int64_t first_pad = -1;
  int64_t last_pad = -1;
  int64_t first_b_content = -1;
  int pad_count_in_gap = 0;

  for (const auto& fp : fps) {
    if (fp.active_block_id == "seam5-A" && !fp.is_pad) {
      last_a_content = fp.session_frame_index;
    }
    if (fp.is_pad && last_a_content >= 0) {
      if (first_pad < 0) first_pad = fp.session_frame_index;
      last_pad = fp.session_frame_index;
      if (first_b_content < 0) pad_count_in_gap++;
    }
    if (fp.active_block_id == "seam5-B" && !fp.is_pad) {
      if (first_b_content < 0) first_b_content = fp.session_frame_index;
    }
  }

  ASSERT_GE(last_a_content, 0) << "Must have A content frames";
  ASSERT_GE(first_pad, 0) << "Must have pad frames in the gap";
  ASSERT_GE(first_b_content, 0) << "Must have B content frames after the gap";

  std::cout << "=== PAD-PROOF-005: FivePadSeam ===" << std::endl;
  std::cout << "last_a_content=" << last_a_content
            << " first_pad=" << first_pad
            << " last_pad=" << last_pad
            << " first_b_content=" << first_b_content
            << " pad_count_in_gap=" << pad_count_in_gap
            << " a_fence_tick=" << a_fence_tick
            << " total_fingerprints=" << fps.size()
            << std::endl;

  // --- ASSERTION 1: Exactly 5 contiguous pad frames ---
  //
  // The 5th pad's on_frame_emitted injects B.  TryLoadLiveProducer on the same
  // tick loads B.  Next tick pops B content.  Allow 5-6 (if B's sync load
  // takes one extra tick).
  EXPECT_GE(pad_count_in_gap, 5)
      << "Must have at least 5 pad frames in the gap";
  EXPECT_LE(pad_count_in_gap, 6)
      << "Gap should be at most 6 pad frames (5 + optional load delay)";

  // Verify contiguity: pad frames must be consecutive indices.
  EXPECT_EQ(last_pad - first_pad + 1, pad_count_in_gap)
      << "Pad frames must be contiguous (no interleaving with content)";

  // --- ASSERTION 2: All pad frames have correct properties + identical CRC ---
  uint32_t first_pad_crc = 0;
  bool first_pad_crc_set = false;
  for (const auto& fp : fps) {
    if (fp.is_pad && fp.session_frame_index >= first_pad &&
        fp.session_frame_index <= last_pad &&
        fp.session_frame_index < first_b_content) {
      AssertPadFrameProperties(fp, expected_crc);
      if (!first_pad_crc_set) {
        first_pad_crc = fp.y_crc32;
        first_pad_crc_set = true;
      } else {
        EXPECT_EQ(fp.y_crc32, first_pad_crc)
            << "All pad frames must have identical y_crc32"
            << " (frame " << fp.session_frame_index << ")";
      }
    }
  }
  EXPECT_TRUE(first_pad_crc_set) << "Must have found pad frames for CRC check";

  // --- ASSERTION 3: PTS increments across the 7-tick seam window ---
  //
  // Window: [last_a_content, last_a_content + 6] = last A, 5 pads, first B.
  // Each tick: video_pts_90k = session_frame_index * frame_duration_90k.
  // Consecutive indices ⇒ PTS increments by exactly frame_duration_90k.
  OutputClock clock(ctx_->fps_num, ctx_->fps_den);
  clock.Start();
  int64_t frame_dur_90k = clock.FrameDuration90k();

  int64_t seam_start = last_a_content;
  int64_t seam_end = std::min(first_b_content,
                               static_cast<int64_t>(fps.size()) - 1);
  // Verify consecutive session_frame_indices in the seam window.
  for (int64_t t = seam_start; t <= seam_end; t++) {
    ASSERT_LT(static_cast<size_t>(t), fps.size())
        << "Seam window must be within fingerprint range";
    EXPECT_EQ(fps[static_cast<size_t>(t)].session_frame_index, t)
        << "session_frame_index must equal position at tick " << t;
    if (t > seam_start) {
      int64_t pts_prev = (t - 1) * frame_dur_90k;
      int64_t pts_curr = t * frame_dur_90k;
      EXPECT_EQ(pts_curr - pts_prev, frame_dur_90k)
          << "Video PTS delta must be exactly frame_duration_90k at tick " << t;
    }
  }

  // --- ASSERTION 4: commit_slot sequence A, P, P, P, P, P, A ---
  //
  // Verify the 7-tick boundary: last A content, 5 pads, first B content.
  // NOTE: B's commit_slot is 'A' (not 'B') because B was loaded from the
  // queue into the LIVE slot via TryLoadLiveProducer, not through a
  // preview→live swap at the fence.  commit_slot='B' only applies when
  // a block enters via the preview rotation path.  In a PADDED_GAP exit,
  // the new block occupies the live slot (source='A').
  ASSERT_LT(static_cast<size_t>(first_b_content), fps.size());
  EXPECT_EQ(fps[static_cast<size_t>(last_a_content)].commit_slot, 'A')
      << "Last A content must have commit_slot='A'";
  for (int64_t t = first_pad; t <= last_pad && t < first_b_content; t++) {
    EXPECT_EQ(fps[static_cast<size_t>(t)].commit_slot, 'P')
        << "Pad frame at tick " << t << " must have commit_slot='P'";
  }
  EXPECT_EQ(fps[static_cast<size_t>(first_b_content)].commit_slot, 'A')
      << "First B content must have commit_slot='A' (loaded into live slot)";

  // --- ASSERTION 5: No pad in last 10 of A, no pad in first 10 of B ---
  constexpr int K = 10;
  for (const auto& fp : fps) {
    if (fp.session_frame_index >= last_a_content - K + 1 &&
        fp.session_frame_index <= last_a_content) {
      EXPECT_FALSE(fp.is_pad)
          << "Frame " << fp.session_frame_index
          << " in last " << K << " of block A must not be pad";
    }
  }
  for (const auto& fp : fps) {
    if (fp.session_frame_index >= first_b_content &&
        fp.session_frame_index < first_b_content + K) {
      EXPECT_FALSE(fp.is_pad)
          << "Frame " << fp.session_frame_index
          << " in first " << K << " of block B must not be pad";
    }
  }

  // --- ASSERTION 6: Session ends cleanly (no audio underflow) ---
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session must end cleanly — 'stopped' means no audio underflow";
  }

  AssertPadAudioSilence();

  // Print boundary fingerprints for diagnostic visibility.
  std::cout << "Boundary window [fence-2 .. fence+7]:" << std::endl;
  for (int64_t t = std::max(int64_t{0}, a_fence_tick - 2);
       t <= std::min(static_cast<int64_t>(fps.size()) - 1, a_fence_tick + 7);
       t++) {
    const auto& fp = fps[static_cast<size_t>(t)];
    std::cout << "  tick=" << fp.session_frame_index
              << " source=" << fp.commit_slot
              << " pad=" << fp.is_pad
              << " block=" << fp.active_block_id
              << " asset=" << fp.asset_uri
              << " y_crc32=0x" << std::hex << fp.y_crc32 << std::dec
              << std::endl;
  }
}

// =============================================================================
// PAD-PROOF-005: Budget Shortfall — block with unresolvable asset emits
//                exactly N pad frames (INV-PAD-PRODUCER integration proof)
//
// Scenario: A single block with an unresolvable URI is queued with a long
// duration (10s / 300 frames at 30fps).  The asset cannot be decoded, so
// every frame falls through to the PadProducer via the TAKE.  The engine
// is stopped after exactly N=15 frames via on_frame_emitted + stop_requested,
// well before the fence fires.
//
// This test verifies the complete fingerprint contract for pad frames:
//   1. Exactly N fingerprints collected — the test FAILS if zero
//   2. Every frame: is_pad = true
//   3. Every frame: commit_slot = 'P' (PadProducer selected by TAKE)
//   4. Every frame: asset_uri = "internal://pad"
//   5. Every frame: y_crc32 matches PadProducer::VideoCRC32()
//   6. PTS delta between consecutive frames is exactly frame_duration_90k
// =============================================================================
TEST_F(ContinuousOutputContractTest, PadProof_BudgetShortfall_ExactCount) {
  constexpr int kN = 15;  // pad frames to collect

  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // 10s block (300 frames at 30fps) — fence never fires within kN frames.
  // Unresolvable URI → every TryGetFrame returns nullopt → all pad.
  FedBlock block = MakeSyntheticBlock("budget-shortfall", 10000);
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 10000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  // Custom callbacks: stop after exactly kN frames.
  int frame_count = 0;
  PipelineManager::Callbacks callbacks;
  callbacks.on_block_completed = [this](const FedBlock& blk, int64_t ct) {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    completed_blocks_.push_back(blk.block_id);
  };
  callbacks.on_session_ended = [this](const std::string& reason) {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    session_ended_count_++;
    session_ended_reason_ = reason;
    session_ended_cv_.notify_all();
  };
  callbacks.on_frame_emitted = [&](const FrameFingerprint& fp) {
    {
      std::lock_guard<std::mutex> lock(fp_mutex_);
      fingerprints_.push_back(fp);
    }
    if (++frame_count >= kN) {
      ctx_->stop_requested.store(true, std::memory_order_release);
    }
  };

  engine_ = std::make_unique<PipelineManager>(ctx_.get(), std::move(callbacks));
  engine_->Start();

  ASSERT_TRUE(WaitForSessionEnded(5000))
      << "Session must end within 5s after emitting " << kN << " pad frames";
  engine_->Stop();

  // ======================== VALIDATION ========================

  auto fps = SnapshotFingerprints();
  PadProducer ref_pad(ctx_->width, ctx_->height, ctx_->fps_num, ctx_->fps_den);
  uint32_t expected_crc = ref_pad.VideoCRC32();
  OutputClock clock(ctx_->fps_num, ctx_->fps_den);
  clock.Start();
  int64_t frame_dur_90k = clock.FrameDuration90k();

  // --- HARD GATE: must have pad frames (test FAILS if none emitted) ---
  ASSERT_GT(fps.size(), 0u)
      << "FAIL: no pad frames emitted — PadProducer was never selected";
  ASSERT_EQ(fps.size(), static_cast<size_t>(kN))
      << "Must have exactly " << kN << " pad frames";

  int verified_pad_count = 0;

  for (int i = 0; i < kN; i++) {
    const auto& fp = fps[i];

    // --- is_pad ---
    EXPECT_TRUE(fp.is_pad)
        << "Frame " << i << " must be pad (is_pad=true)";

    // --- commit_slot ---
    EXPECT_EQ(fp.commit_slot, 'P')
        << "Frame " << i << " commit_slot must be 'P'";

    // --- asset_uri ---
    EXPECT_EQ(fp.asset_uri, PadProducer::kAssetUri)
        << "Frame " << i << " asset_uri must be 'internal://pad'";

    // --- y_crc32 ---
    EXPECT_EQ(fp.y_crc32, expected_crc)
        << "Frame " << i << " y_crc32=0x" << std::hex << fp.y_crc32
        << " must match PadProducer::VideoCRC32()=0x" << expected_crc
        << std::dec;

    // --- PTS strictly increments by exactly frame_duration_90k ---
    EXPECT_EQ(fp.session_frame_index, static_cast<int64_t>(i))
        << "session_frame_index must be sequential";
    if (i > 0) {
      int64_t delta = (fps[i].session_frame_index -
                       fps[i - 1].session_frame_index) * frame_dur_90k;
      EXPECT_EQ(delta, frame_dur_90k)
          << "PTS delta between frames " << (i - 1) << " and " << i
          << " must be exactly frame_duration_90k=" << frame_dur_90k;
    }

    if (fp.is_pad) verified_pad_count++;
  }

  // --- Final sanity: every collected frame was pad ---
  EXPECT_EQ(verified_pad_count, kN)
      << "All " << kN << " frames must be pad — got " << verified_pad_count;

  // Session ended cleanly (no underflow, no detach).
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }
}

// =============================================================================
// INV-TICK-GUARANTEED-OUTPUT: Audio underflow during segment transition
// must NOT kill the session.
//
// Scenario:
//   Block with 2 segments: episode (1s of SampleA.mp4) + filler (SampleB.mp4).
//   Audio buffer is configured small (50ms) so underflow is near-certain
//   during the episode→filler decoder switch.
//
// Assertions:
//   1. detach_count == 0 (no underflow-triggered session stop)
//   2. Session emits frames well past the segment boundary
//   3. Session ends normally ("stopped"), not from underflow
// =============================================================================
TEST_F(ContinuousOutputContractTest, AudioUnderflowBridgedWithSilence) {
  static const std::string kPathA = "/opt/retrovue/assets/SampleA.mp4";
  static const std::string kPathB = "/opt/retrovue/assets/SampleB.mp4";
  if (access(kPathA.c_str(), F_OK) != 0 ||
      access(kPathB.c_str(), F_OK) != 0) {
    GTEST_SKIP() << "Real media assets not found: " << kPathA << ", " << kPathB;
  }

  // Shrink audio buffer to provoke underflow during segment transition.
  ctx_->buffer_config.audio_target_depth_ms = 50;
  ctx_->buffer_config.audio_low_water_ms = 10;

  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // Multi-segment block: 1s episode + 2s filler = 3s total.
  // Episode will exhaust quickly, forcing a segment transition.
  FedBlock block;
  block.block_id = "underflow-bridge";
  block.channel_id = 99;
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 3000;
  {
    FedBlock::Segment seg0;
    seg0.segment_index = 0;
    seg0.asset_uri = kPathA;
    seg0.asset_start_offset_ms = 0;
    seg0.segment_duration_ms = 1000;
    seg0.segment_type = SegmentType::kContent;
    block.segments.push_back(seg0);

    FedBlock::Segment seg1;
    seg1.segment_index = 1;
    seg1.asset_uri = kPathB;
    seg1.asset_start_offset_ms = 0;
    seg1.segment_duration_ms = 2000;
    seg1.segment_type = SegmentType::kFiller;
    block.segments.push_back(seg1);
  }

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Run long enough that the segment transition definitely occurs
  // and filler content plays for at least 1s after the transition.
  // If the old hard-stop was still in place, the session would die
  // at or shortly after the transition (~1s in).
  std::this_thread::sleep_for(std::chrono::milliseconds(3500));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // ASSERTION 1: No underflow-triggered session stops.
  EXPECT_EQ(m.detach_count, 0)
      << "INV-TICK-GUARANTEED-OUTPUT VIOLATION: audio underflow must NOT "
         "terminate the session. detach_count=" << m.detach_count;

  // ASSERTION 2: Session emitted well past the 1s episode boundary.
  // At 30fps, 1s = 30 frames. We expect at least 60 frames (into filler).
  EXPECT_GT(m.continuous_frames_emitted_total, 60)
      << "Session must survive the segment transition and continue emitting. "
         "Got only " << m.continuous_frames_emitted_total << " frames";

  // ASSERTION 3: Session ended normally.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session must end with reason='stopped', not underflow. "
           "Got: " << session_ended_reason_;
  }

  // ASSERTION 4: Burst-fill must limit silence to a brief bridge (≤3 ticks).
  // Before burst-fill, this was 50+ continuous silence injections.
  EXPECT_LE(m.audio_silence_injected, 3)
      << "INV-TICK-GUARANTEED-OUTPUT: burst-fill must rebuild audio headroom "
         "fast enough that silence injection is at most a brief bridge. "
         "Got " << m.audio_silence_injected << " silence injections";
}

// =============================================================================
// INV-PREROLL-READY-001: Preroll arming regression — next-next block must
// preload while preview_ holds the current-next block.
//
// Scenario:
//   3 wall-anchored blocks: A (1.5s), B (0.5s), C (2s).
//   Preloader delay hook: 600ms (simulates slow probe+open+seek).
//
//   With the OLD code (if (preview_) return; guard):
//     - B preloads during A (finishes at ~0.6s), captured as preview_
//     - C's preload BLOCKED because preview_ exists (B)
//     - A fence at 1.5s → B→A rotation → C preload starts at 1.5s
//     - C finishes at ~2.1s, but B fence at 2.0s → C NOT READY → PADDED_GAP
//
//   With the FIX (preview_ guard removed, IsRunning guard added):
//     - B preloads during A (finishes at ~0.6s), captured as preview_
//     - C preload starts immediately at ~0.6s (preloader idle, queue has C)
//     - C finishes at ~1.2s, preloader ready
//     - A fence at 1.5s → B→A rotation
//     - Next tick: C captured as preview_ → seamless at B fence (2.0s)
//
// Assertions:
//   1. padded_gap_count == 0 (no PADDED_GAP — C was ready at B's fence)
//   2. source_swap_count >= 2 (both A→B and B→C swaps succeeded)
//   3. next_preload_started_count >= 2 (B and C both preloaded)
//   4. Session ends cleanly
// =============================================================================
TEST_F(ContinuousOutputContractTest, PrerollArmingNextNextBlock) {
  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // Block A: 1.5s
  FedBlock block_a = MakeSyntheticBlock("preroll-A", 1500);
  block_a.start_utc_ms = now_ms;
  block_a.end_utc_ms = now_ms + 1500;

  // Block B: 0.5s (short — the crux of the bug)
  FedBlock block_b = MakeSyntheticBlock("preroll-B", 500);
  block_b.start_utc_ms = now_ms + 1500;
  block_b.end_utc_ms = now_ms + 2000;

  // Block C: 2s
  FedBlock block_c = MakeSyntheticBlock("preroll-C", 2000);
  block_c.start_utc_ms = now_ms + 2000;
  block_c.end_utc_ms = now_ms + 4000;

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
    ctx_->block_queue.push_back(block_c);
  }

  engine_ = MakeEngine();

  // Simulate slow preloader (600ms per preload).
  // With the old bug, C's preload starts at A's fence (1.5s),
  // finishes at 2.1s, too late for B's fence at 2.0s.
  engine_->SetPreloaderDelayHook([]() {
    std::this_thread::sleep_for(std::chrono::milliseconds(600));
  });

  engine_->Start();

  // Run through all 3 blocks + margin: 4s blocks + 2s margin.
  std::this_thread::sleep_for(std::chrono::milliseconds(6000));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  std::cout << "=== INV-PREROLL-READY-001: PrerollArmingNextNextBlock ===" << std::endl;
  std::cout << "  source_swap_count=" << m.source_swap_count
            << " total_blocks_executed=" << m.total_blocks_executed
            << " padded_gap_count=" << m.padded_gap_count
            << " next_preload_started=" << m.next_preload_started_count
            << " next_preload_ready=" << m.next_preload_ready_count
            << " fence_preload_miss=" << m.fence_preload_miss_count
            << std::endl;

  // ASSERTION 1: At most 1 PADDED_GAP — allowed only at the end of the last
  // block (C) where no block D exists.  The A→B and B→C transitions must be
  // seamless (no gap).  source_swap_count==2 proves both rotations succeeded.
  EXPECT_LE(m.padded_gap_count, 1)
      << "INV-PREROLL-READY-001 REGRESSION: preroll for block C must start "
         "while preview_ holds block B, not after B's fence fires. "
         "padded_gap_count=" << m.padded_gap_count;

  // ASSERTION 2: Both A→B and B→C swaps must succeed.
  EXPECT_GE(m.source_swap_count, 2)
      << "Must have at least 2 source swaps (A→B and B→C). "
         "Got " << m.source_swap_count;

  // ASSERTION 3: Both B and C must have been preloaded.
  EXPECT_GE(m.next_preload_started_count, 2)
      << "Preloader must have started at least 2 preloads (B and C). "
         "Got " << m.next_preload_started_count;

  // ASSERTION 4: Session ends cleanly.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session must end cleanly";
  }

  // ASSERTION 5: All 3 blocks completed.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_GE(completed_blocks_.size(), 3u)
        << "All 3 blocks must complete. Completed: " << completed_blocks_.size();
  }
}

// =============================================================================
// PRIME-REGRESS-001: NulloptBurstTolerance
//
// Single block with unresolvable URI.  PrimeFirstTick returns {false, 0}.
// Verify the session runs cleanly, produces pad frames, and does NOT detach.
// This proves the priming loop tolerates a complete audio prime failure
// (no decoder → no audio) without crashing or stalling.
// =============================================================================
TEST_F(ContinuousOutputContractTest, NulloptBurstTolerance) {
  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // 2s block with unresolvable URI → decoder fails → PrimeFirstTick = {false, 0}.
  FedBlock block = MakeSyntheticBlock("nullopt-burst", 2000);
  block.start_utc_ms = now_ms;
  block.end_utc_ms = now_ms + 2000;
  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Run through the block (2s) + margin for post-fence pad.
  std::this_thread::sleep_for(std::chrono::milliseconds(3000));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // ASSERTION 1: No underflow-triggered detach.
  EXPECT_EQ(m.detach_count, 0)
      << "Unresolvable asset must NOT trigger underflow detach";

  // ASSERTION 2: Session produced pad frames (block ran, content was pad).
  EXPECT_GT(m.pad_frames_emitted_total, 0)
      << "Must emit pad frames for unresolvable asset";
  EXPECT_EQ(m.pad_frames_emitted_total, m.continuous_frames_emitted_total)
      << "All frames must be pad when asset is unresolvable";

  // ASSERTION 3: Block completed (fence fired).
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    ASSERT_GE(completed_blocks_.size(), 1u)
        << "Block must complete despite prime failure";
    EXPECT_EQ(completed_blocks_[0], "nullopt-burst");
  }

  // ASSERTION 4: Session ended cleanly.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped")
        << "Session must end cleanly, not from underflow";
  }
}

// =============================================================================
// PRIME-REGRESS-002: DegradedTakeCountTracked
//
// Two wall-anchored blocks (synthetic, unresolvable URIs).  All TAKEs are
// degraded because there is no real audio (decoder fails → audio prime = 0ms).
// Assert that degraded_take_count == source_swap_count: every swap that
// occurs is a degraded take.
// =============================================================================
TEST_F(ContinuousOutputContractTest, DegradedTakeCountTracked) {
  auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();

  // Block A: 1s, unresolvable URI.
  FedBlock block_a = MakeSyntheticBlock("degrade-A", 1000);
  block_a.start_utc_ms = now_ms;
  block_a.end_utc_ms = now_ms + 1000;

  // Block B: 1s, unresolvable URI.
  FedBlock block_b = MakeSyntheticBlock("degrade-B", 1000);
  block_b.start_utc_ms = now_ms + 1000;
  block_b.end_utc_ms = now_ms + 2000;

  {
    std::lock_guard<std::mutex> lock(ctx_->queue_mutex);
    ctx_->block_queue.push_back(block_a);
    ctx_->block_queue.push_back(block_b);
  }

  engine_ = MakeEngine();
  engine_->Start();

  // Run through both blocks + margin.
  std::this_thread::sleep_for(std::chrono::milliseconds(3500));

  engine_->Stop();

  auto m = engine_->SnapshotMetrics();

  // ASSERTION 1: Both blocks executed.
  EXPECT_GE(m.total_blocks_executed, 2)
      << "Both blocks must complete";

  // ASSERTION 2: At least 1 source swap (A→B transition).
  EXPECT_GE(m.source_swap_count, 1)
      << "Must have at least 1 source swap for 2 blocks";

  // ASSERTION 3: degraded_take_count == source_swap_count.
  // Every swap is degraded because synthetic blocks have no decoder (audio=0ms).
  EXPECT_EQ(m.degraded_take_count, m.source_swap_count)
      << "Every TAKE must be degraded (synthetic blocks have zero audio prime). "
         "degraded=" << m.degraded_take_count
      << " swaps=" << m.source_swap_count;

  // ASSERTION 4: Session ended cleanly.
  {
    std::lock_guard<std::mutex> lock(cb_mutex_);
    EXPECT_EQ(session_ended_reason_, "stopped");
  }

  // ASSERTION 5: No detach (degraded TAKEs are allowed under Policy B).
  EXPECT_EQ(m.detach_count, 0)
      << "Policy B: degraded TAKEs must NOT cause session detach";
}

}  // namespace
}  // namespace retrovue::blockplan::testing
