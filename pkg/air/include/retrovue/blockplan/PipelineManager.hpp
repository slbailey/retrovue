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

#include <cassert>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/blockplan/AudioLookaheadBuffer.hpp"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"
#include "retrovue/blockplan/VideoLookaheadBuffer.hpp"
#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"

// Forward declarations
namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
}  // namespace retrovue::playout_sinks::mpegts

namespace retrovue::blockplan {

class PadProducer;
class ProducerPreloader;
struct FrameData;
struct FrameFingerprint;
struct BlockPlaybackSummary;
struct BlockPlaybackProof;
struct SeamTransitionLog;

class PipelineManager : public IPlayoutExecutionEngine {
 public:
  struct Callbacks {
    // Called when a block completes its allocated frame count.
    std::function<void(const FedBlock&, int64_t)> on_block_completed;

    // Called when the session ends (stop requested, error, etc.).
    std::function<void(const std::string&)> on_session_ended;

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
                  Callbacks callbacks);
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
  void Run();

  // Dequeue next block from ctx_->block_queue and assign to live_.
  // Called ONLY when live_ is EMPTY — outside the timed tick window.
  void TryLoadLiveProducer();

  // P3.1b: If preview_ is EMPTY and queue has a block, kick off preload.
  // Called outside the tick window only.
  void TryKickoffPreviewPreload();

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
  // where delta_ms = block.end_utc_ms - session_epoch_utc_ms_.
  // The fence tick is the first session frame owned by the NEXT block.
  // TAKE selects B's buffers when session_frame_index >= block_fence_frame_.
  // INT64_MAX = no block loaded.
  int64_t block_fence_frame_ = INT64_MAX;
  // UTC epoch (ms since Unix epoch) recorded at session start.  Used to map
  // FedBlock::end_utc_ms to a session frame index.
  int64_t session_epoch_utc_ms_ = 0;

  // INV-FRAME-BUDGET-002: Remaining output frames for the current block.
  // Initialized to (block_fence_frame_ - session_frame_index) — derived
  // from fence, NOT from FramesPerBlock().
  // Decremented by exactly 1 per emitted frame (real, freeze, or pad).
  // Reaches 0 on the fence tick as a verification (not a trigger).
  // Accessed only from the Run() thread — no mutex required.
  int64_t remaining_block_frames_ = 0;

  // P3.1b: Preview producer (preloaded in background, Input Bus B).
  std::unique_ptr<producers::IProducer> preview_;
  std::unique_ptr<ProducerPreloader> preloader_;

  // Deferred fill thread and producer from async stop at fence.
  // The old fill thread may still be decoding when B rotates into A.
  // The old producer must stay alive until the old fill thread exits.
  std::thread deferred_fill_thread_;
  std::unique_ptr<producers::IProducer> deferred_producer_;
  void CleanupDeferredFill();

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

  // INV-PAD-PRODUCER: Session-lifetime pad source. Created once in Run().
  std::unique_ptr<PadProducer> pad_producer_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PIPELINE_MANAGER_HPP_
