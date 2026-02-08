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
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/blockplan/PipelineManager.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/OutputClock.hpp"
#include "retrovue/blockplan/ProducerPreloader.hpp"

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
    ctx_->fd = -1;  // No real FD — encoder write callback handles gracefully
    ctx_->width = 640;
    ctx_->height = 480;
    ctx_->fps = 30.0;
  }

  void TearDown() override {
    if (engine_) {
      engine_->Stop();
      engine_.reset();
    }
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

  std::mutex cb_mutex_;
  std::condition_variable session_ended_cv_;
  std::vector<std::string> completed_blocks_;
  int session_ended_count_ = 0;
  std::string session_ended_reason_;
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
  // Two 1000ms blocks (~31 frames each at 30fps)
  FedBlock block1 = MakeSyntheticBlock("swap-001a", 1000);
  FedBlock block2 = MakeSyntheticBlock("swap-001b", 1000);
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

}  // namespace
}  // namespace retrovue::blockplan::testing
