// Repository: Retrovue-playout
// Component: Pipeline Manager
// Purpose: IPlayoutExecutionEngine that emits a continuous frame stream,
//          falling back to pad frames when no block content is available.
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// P3.0: Pad-only skeleton — session-long encoder, OutputClock at fixed
// cadence, pad frames when no block content is available.
// P3.1a: Active Producer — real decoded frames from blocks with pad
// fallback.  Single active source only (no A/B switching).
// P3.1b: TAKE-at-commit with background preloading — preview_ is
// preloaded off-thread; source selection happens at pop→encode.

#ifndef RETROVUE_BLOCKPLAN_PIPELINE_MANAGER_HPP_
#define RETROVUE_BLOCKPLAN_PIPELINE_MANAGER_HPP_

#include <atomic>
#include <cassert>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"
#include "retrovue/blockplan/SeamPreparer.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"
#include "time/ITimeSource.hpp"

// Forward declarations
namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
}  // namespace retrovue::playout_sinks::mpegts

namespace retrovue::blockplan {

class PadProducer;
struct FrameData;
struct FrameFingerprint;
struct BlockPlaybackSummary;
struct BlockPlaybackProof;
struct SeamTransitionLog;

// Context passed to on_block_started with channel-monotonic timeline info.
struct BlockActivationContext {
  int64_t timeline_frame_index;  // channel-monotonic tick at block activation
  int64_t block_fence_tick;      // precomputed fence tick (channel-monotonic)
  int64_t utc_ms;                // wall clock at activation
};

class PipelineManager : public IPlayoutExecutionEngine {
 public:
  struct Callbacks {
    // Called when a block completes its allocated frame count.
    // Parameters: block, final_ct_ms, session_frame_index at fence.
    std::function<void(const FedBlock&, int64_t, int64_t)> on_block_completed;

    // Called when a block is popped from the queue and begins execution/preload.
    // Signals queue slot consumption — Core uses this as the preferred credit signal.
    std::function<void(const FedBlock&, const BlockActivationContext&)> on_block_started;

    // Called when the session ends (stop requested, error, etc.).
    // Parameters: reason, final session_frame_index for offset accumulation.
    std::function<void(const std::string&, int64_t)> on_session_ended;

    // Called when a new segment becomes live within a block.
    // from_segment_index: -1 on first segment of block (no predecessor).
    // to_segment_index: index of the segment now live.
    // block: the parent FedBlock (segments carry event_id).
    // session_frame_index: frame index at the transition point.
    std::function<void(int32_t, int32_t, const FedBlock&, int64_t)> on_segment_start;

    // P3.2: Per-frame fingerprint (optional — test/verify only).
    // Zero cost when not wired.
    std::function<void(const FrameFingerprint&)> on_frame_emitted;

    // P3.3: Per-block playback summary (optional — test/diagnostics).
    // Fired when a block completes its fence, before on_block_completed.
    std::function<void(const BlockPlaybackSummary&)> on_block_summary;

    // P3.3: Seam transition log (optional — test/diagnostics).
    // Fired at fence TAKE (post-TAKE B→A rotation) or new block load.
    std::function<void(const SeamTransitionLog&)> on_seam_transition;

    // P3.3b: Playback proof — wanted vs showed comparison.
    // Fired at fence, after on_block_summary.
    std::function<void(const BlockPlaybackProof&)> on_playback_proof;
  };

  PipelineManager(BlockPlanSessionContext* ctx,
                  Callbacks callbacks,
                  std::shared_ptr<ITimeSource> time_source = nullptr);
  ~PipelineManager() override;

  // IPlayoutExecutionEngine
  void Start() override;
  void Stop() override;

  // Thread-safe snapshot of accumulated session metrics.
  PipelineMetrics SnapshotMetrics() const;

  // Generate Prometheus text exposition.  Thread-safe.
  std::string GenerateMetricsText() const;

  // P3.2: Test-only — forward delay hook to internal ProducerPreloader.
  void SetPreloaderDelayHook(std::function<void()> hook);

 private:
  std::shared_ptr<ITimeSource> time_source_;

  void Run();

  // Dequeue next block from ctx_->block_queue and assign to live_.
  // Called ONLY when live_ is EMPTY — outside the timed tick window.
  void TryLoadLiveProducer();

  // P3.1b: If SeamPreparer is idle and queue has a block, kick off block preload.
  // Called outside the tick window only.  Now allows preloading the
  // next-next block while preview_ holds the current-next block.
  void TryKickoffBlockPreload(int64_t tick = -1);

  // P3.1b: Pop the preloaded preview_ if ready.  Returns non-null if
  // a fully READY IProducer was obtained.  Non-blocking.
  std::unique_ptr<producers::IProducer> TryTakePreviewProducer();

  // --- ITickProducer access helpers ---
  // All tick-method calls on IProducer pointers go through these.
  // Hard assert: the IProducer must be a TickProducer (implements ITickProducer).
  static ITickProducer* AsTickProducer(producers::IProducer* p) {
    auto* tp = dynamic_cast<ITickProducer*>(p);
    assert(tp && "IProducer must implement ITickProducer");
    return tp;
  }

  static const ITickProducer* AsTickProducer(const producers::IProducer* p) {
    auto* tp = dynamic_cast<const ITickProducer*>(p);
    assert(tp && "IProducer must implement ITickProducer");
    return tp;
  }

  BlockPlanSessionContext* ctx_;
  Callbacks callbacks_;
  std::thread thread_;
  bool started_ = false;

  mutable std::mutex metrics_mutex_;
  PipelineMetrics metrics_;

  // Guard against on_session_ended firing more than once.
  bool session_ended_fired_ = false;

  // P3.1a: Live producer for real-frame decoding (Input Bus A).
  std::unique_ptr<producers::IProducer> live_;

  // INV-BLOCK-WALLFENCE-001: Rational-timebase authoritative block fence.
  // block_fence_frame_ = ceil(delta_ms * fps_num / (fps_den * 1000))
  // where delta_ms = block.end_utc_ms - fence_epoch_utc_ms_.
  // The fence tick is the first session frame owned by the NEXT block.
  // TAKE selects B's buffers when session_frame_index >= block_fence_frame_.
  // INT64_MAX = no block loaded.
  int64_t block_fence_frame_ = INT64_MAX;

  // INV-JIP-ANCHOR-001: Core-authoritative epoch.  Set once from
  // ctx_->join_utc_ms (or system_clock fallback).  NEVER mutated after
  // initial capture.  Used for logging/diagnostics only.
  int64_t session_epoch_utc_ms_ = 0;

  // INV-FENCE-WALLCLOCK-ANCHOR: Fence-specific epoch.  Set to
  // system_clock::now() at clock.Start() (after bootstrap completes).
  // Used ONLY by compute_fence_frame.  Decoupled from session_epoch_utc_ms_
  // so fence math tracks actual emission start without mutating the
  // Core-authoritative epoch.
  int64_t fence_epoch_utc_ms_ = 0;

  // INV-FRAME-BUDGET-002: Remaining output frames for the current block.
  // Initialized to (block_fence_frame_ - session_frame_index) — derived
  // from fence, NOT from FramesPerBlock().
  // Decremented by exactly 1 per emitted frame (real, freeze, or pad).
  // Reaches 0 on the fence tick as a verification (not a trigger).
  // Accessed only from the Run() thread — no mutex required.
  int64_t remaining_block_frames_ = 0;

  // P3.1b: Preview producer (preloaded in background, Input Bus B).
  std::unique_ptr<producers::IProducer> preview_;
  std::unique_ptr<SeamPreparer> seam_preparer_;

  // Policy B observability: audio prime depth (ms) captured from preloader
  // BEFORE TakeSource(), so we know the headroom at TAKE time.
  int preview_audio_prime_depth_ms_ = 0;

  // Deferred fill thread and producer from async stop at fence.
  // The old fill thread may still be decoding when B rotates into A.
  // The old producer must stay alive until the old fill thread exits.
  // Threads are handed to the reaper for non-blocking join (never block tick loop).
  std::thread deferred_fill_thread_;
  std::unique_ptr<producers::IProducer> deferred_producer_;
  std::unique_ptr<VideoLookaheadBuffer> deferred_video_buffer_;
  std::unique_ptr<AudioLookaheadBuffer> deferred_audio_buffer_;
  void CleanupDeferredFill();  // Non-blocking: hands off to reaper

  // Reaper thread: joins deferred fill threads off the tick loop.
  // ReapJob holds thread + owners so objects stay alive until join completes.
  struct ReapJob {
    int64_t job_id = 0;
    std::string block_id;  // Diagnostic: block at handoff
    std::thread thread;
    std::unique_ptr<producers::IProducer> producer;
    std::unique_ptr<VideoLookaheadBuffer> video_buffer;
    std::unique_ptr<AudioLookaheadBuffer> audio_buffer;
  };
  std::atomic<int64_t> reap_job_id_{0};
  std::thread reaper_thread_;
  std::mutex reaper_mutex_;
  std::condition_variable reaper_cv_;
  std::queue<ReapJob> reaper_queue_;
  std::atomic<bool> reaper_shutdown_{false};
  void ReaperLoop();
  void HandOffToReaper(ReapJob job);
  static std::string GetBlockIdFromProducer(producers::IProducer* p);

  // --- VideoLookaheadBuffer: non-blocking video frame buffer ---
  // Decoded video frames are pushed by a background fill thread;
  // the tick loop pops one frame per tick.  Underflow = hard fault.
  // Cadence (decode vs repeat) is resolved in the fill thread.
  std::unique_ptr<VideoLookaheadBuffer> video_buffer_;

  // --- AudioLookaheadBuffer: broadcast-grade audio buffering ---
  // Audio frames from decode are pushed here; the tick loop pops
  // exact per-tick sample counts.  Underflow = hard fault.
  std::unique_ptr<AudioLookaheadBuffer> audio_buffer_;

  // --- Preroll B buffers: filled by preview producer BEFORE fence ---
  // The preview producer's fill thread writes decoded frames here while
  // producer A is still live.  At the commitment point (TryPopFrame),
  // the tick loop selects A or B based on session_frame_index vs fence.
  // After the TAKE (first tick >= fence_tick), B rotates into A.
  std::unique_ptr<VideoLookaheadBuffer> preview_video_buffer_;
  std::unique_ptr<AudioLookaheadBuffer> preview_audio_buffer_;

  // --- Segment seam tracking (INV-SEAM-SEG) ---
  // Original multi-segment FedBlock, stored at block activation so that
  // ArmSegmentPrep can build synthetic blocks for ANY segment index (not
  // just the one currently live).  After segment swap, live_->GetBlock()
  // returns the synthetic single-segment block — not the original.
  FedBlock live_parent_block_;
  std::vector<SegmentBoundary> live_boundaries_;
  int32_t current_segment_index_ = 0;
  std::vector<int64_t> segment_seam_frames_;  // One per segment boundary

  // Block activation frame — session_frame_index at the moment the block became active.
  // All segment seam frames are computed relative to this anchor.  No UTC math.
  int64_t block_activation_frame_ = 0;

  // Unified seam frame — min(next segment seam, block fence).
  int64_t next_seam_frame_ = INT64_MAX;
  enum class SeamType { kSegment, kBlock, kNone };
  SeamType next_seam_type_ = SeamType::kNone;

  // Segment preview (mirrors preview_ / preview_video_buffer_ / preview_audio_buffer_)
  std::unique_ptr<producers::IProducer> segment_preview_;
  std::unique_ptr<VideoLookaheadBuffer> segment_preview_video_buffer_;
  std::unique_ptr<AudioLookaheadBuffer> segment_preview_audio_buffer_;

  // Segment seam private methods
  void ComputeSegmentSeamFrames();
  void UpdateNextSeamFrame();
  void ArmSegmentPrep(int64_t session_frame_index);
  void PerformSegmentSwap(int64_t session_frame_index);

  // Static helper: build synthetic single-segment FedBlock for segment prep.
  static FedBlock MakeSyntheticSegmentBlock(
      const FedBlock& parent, int32_t seg_idx,
      const std::vector<SegmentBoundary>& boundaries);

  // INV-PAD-PRODUCER: Session-lifetime pad source. Created once in Run().
  std::unique_ptr<PadProducer> pad_producer_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PIPELINE_MANAGER_HPP_
