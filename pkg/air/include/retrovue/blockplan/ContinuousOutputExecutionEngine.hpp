// Repository: Retrovue-playout
// Component: Continuous Output Execution Engine
// Purpose: IPlayoutExecutionEngine that emits a continuous frame stream,
//          falling back to pad frames when no block content is available.
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// P3.0: Pad-only skeleton — session-long encoder, OutputClock at fixed
// cadence, pad frames when no block content is available.
// P3.1a: Active BlockSource — real decoded frames from blocks with pad
// fallback.  Single active source only (no A/B switching).
// P3.1b: A/B source swap with background preloading — next_source_ is
// preloaded off-thread so the fence swap is instant.

#ifndef RETROVUE_BLOCKPLAN_CONTINUOUS_OUTPUT_EXECUTION_ENGINE_HPP_
#define RETROVUE_BLOCKPLAN_CONTINUOUS_OUTPUT_EXECUTION_ENGINE_HPP_

#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/ContinuousOutputMetrics.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"

// Forward declarations
namespace retrovue::playout_sinks::mpegts {
class EncoderPipeline;
}  // namespace retrovue::playout_sinks::mpegts

namespace retrovue::blockplan {

class BlockSource;
class SourcePreloader;
struct FrameFingerprint;
struct BlockPlaybackSummary;
struct SeamTransitionLog;

class ContinuousOutputExecutionEngine : public IPlayoutExecutionEngine {
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
  };

  ContinuousOutputExecutionEngine(BlockPlanSessionContext* ctx,
                                  Callbacks callbacks);
  ~ContinuousOutputExecutionEngine() override;

  // IPlayoutExecutionEngine
  void Start() override;
  void Stop() override;

  // Thread-safe snapshot of accumulated session metrics.
  ContinuousOutputMetrics SnapshotMetrics() const;

  // Generate Prometheus text exposition.  Thread-safe.
  std::string GenerateMetricsText() const;

  // P3.2: Test-only — forward delay hook to internal SourcePreloader.
  void SetPreloaderDelayHook(std::function<void()> hook);

 private:
  void Run();

  // Emit one pad video frame + one silence audio frame at the given PTS.
  void EmitPadFrame(playout_sinks::mpegts::EncoderPipeline* encoder,
                    int64_t video_pts_90k, int64_t audio_pts_90k);

  // Dequeue next block from ctx_->block_queue and assign to active_source_.
  // Called ONLY when active_source_ is EMPTY — outside the timed tick window.
  void TryLoadActiveBlock();

  // P3.1b: If next_source_ is EMPTY and queue has a block, kick off preload.
  // Called outside the tick window only.
  void TryKickoffNextPreload();

  // P3.1b: Pop the preloaded next_source_ if ready.  Returns non-null if
  // a fully READY BlockSource was obtained.  Non-blocking.
  std::unique_ptr<BlockSource> TryTakePreloadedNext();

  BlockPlanSessionContext* ctx_;
  Callbacks callbacks_;
  std::thread thread_;
  bool started_ = false;

  mutable std::mutex metrics_mutex_;
  ContinuousOutputMetrics metrics_;

  // Guard against on_session_ended firing more than once.
  bool session_ended_fired_ = false;

  // P3.1a: Active block source for real-frame decoding.
  std::unique_ptr<BlockSource> active_source_;
  int64_t source_ticks_ = 0;  // Engine-owned tick counter for active block

  // P3.1b: Next block source (preloaded in background).
  std::unique_ptr<BlockSource> next_source_;
  std::unique_ptr<SourcePreloader> preloader_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_CONTINUOUS_OUTPUT_EXECUTION_ENGINE_HPP_
