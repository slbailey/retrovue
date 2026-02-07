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
// P3.1b: A/B source swap with background preloading — preview_ is
// preloaded off-thread so the fence swap is instant.

#ifndef RETROVUE_BLOCKPLAN_PIPELINE_MANAGER_HPP_
#define RETROVUE_BLOCKPLAN_PIPELINE_MANAGER_HPP_

#include <cassert>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/PipelineMetrics.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"
#include "retrovue/producers/IProducer.h"

// Forward declarations
namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
}  // namespace retrovue::playout_sinks::mpegts

namespace retrovue::blockplan {

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
    // Fired at source swap or new block load after fence.
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

  // Emit one pad video frame + one silence audio frame at the given PTS.
  void EmitPadFrame(playout_sinks::mpegts::EncoderPipeline* encoder,
                    int64_t video_pts_90k, int64_t audio_pts_90k);

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
  int64_t live_ticks_ = 0;  // Engine-owned tick counter for live bus

  // P3.1b: Preview producer (preloaded in background, Input Bus B).
  std::unique_ptr<producers::IProducer> preview_;
  std::unique_ptr<ProducerPreloader> preloader_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PIPELINE_MANAGER_HPP_
