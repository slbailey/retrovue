// Repository: Retrovue-playout
// Component: Block Preloader
// Purpose: Background preloading of next block's heavy resources (probe + decoder)
// Contract Reference: P2 – Serial Block Preloading, PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// Preloading is best-effort and advisory. If the preload is not ready when the
// engine needs it, execution falls back to the current synchronous behavior.
// Preloading does NOT change output semantics, frame count, CT behavior, or
// encoder lifecycle. It only reduces the stall at block boundaries.

#ifndef RETROVUE_BLOCKPLAN_BLOCK_PRELOADER_HPP_
#define RETROVUE_BLOCKPLAN_BLOCK_PRELOADER_HPP_

#include <atomic>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/RealTimeExecution.hpp"
#include "retrovue/decode/FFmpegDecoder.h"

namespace retrovue::blockplan {

// =============================================================================
// BlockPreloadContext
// Holds pre-loaded resources for the next block. Produced by BlockPreloader,
// consumed by SerialBlockExecutionEngine::Run().
//
// Ownership:
// - assets: value type, moved to executor
// - decoder: unique_ptr, moved to sink via InstallPreloadedDecoder()
// =============================================================================

struct BlockPreloadContext {
  // Identity: must match the block being executed, else discarded as stale
  std::string block_id;

  // Pre-probed asset source (durations cached via RealAssetSource::ProbeAsset)
  realtime::RealAssetSource assets;
  bool assets_ready = false;

  // Pre-opened decoder for first segment (optional)
  std::unique_ptr<decode::FFmpegDecoder> decoder;
  std::string decoder_asset_uri;        // Asset the decoder was opened for
  int64_t decoder_seek_target_ms = 0;   // Position it was seeked to
  bool decoder_ready = false;

  // Instrumentation (microseconds)
  int64_t probe_us = 0;          // Total time probing all assets
  int64_t decoder_open_us = 0;   // Time to open decoder
  int64_t seek_us = 0;           // Time for SeekPreciseToMs
  int32_t preroll_frames = 0;    // Frames discarded during seek
};

// =============================================================================
// BlockPreloader
// Runs a background thread that probes assets and optionally opens a decoder
// for the next block. Designed to run during the current block's execution
// (~5 seconds), so it has ample time to complete.
//
// Thread safety:
// - StartPreload / TakeIfReady / Cancel are called from the engine thread only
// - PreloadWorker runs on its own thread and writes result_ under mutex
// - cancel_requested_ is atomic for cross-thread signaling
//
// Lifecycle:
// - StartPreload() cancels any in-progress preload before starting a new one
// - Cancel() joins the thread (blocks until worker exits)
// - Destructor calls Cancel()
// =============================================================================

class BlockPreloader {
 public:
  BlockPreloader() = default;
  ~BlockPreloader();

  // Not copyable or movable (owns thread)
  BlockPreloader(const BlockPreloader&) = delete;
  BlockPreloader& operator=(const BlockPreloader&) = delete;

  // Start preloading resources for the given block.
  // Cancels any in-progress preload first (safe to call repeatedly).
  // Parameters:
  //   block: the FedBlock to preload (copied for thread safety)
  //   width, height: decoder target dimensions
  void StartPreload(const FedBlock& block, int width, int height);

  // Non-blocking check for completed preload result.
  // Returns the context if ready, nullptr otherwise.
  // Ownership transfers to the caller.
  std::unique_ptr<BlockPreloadContext> TakeIfReady();

  // Cancel any in-progress preload and join the worker thread.
  // Safe to call even if no preload is in progress. Idempotent.
  void Cancel();

 private:
  // Worker function (runs on background thread)
  void PreloadWorker(FedBlock block, int width, int height);

  // Join thread if joinable
  void JoinThread();

  std::thread thread_;
  std::mutex mutex_;
  std::atomic<bool> cancel_requested_{false};
  std::unique_ptr<BlockPreloadContext> result_;  // Guarded by mutex_
  bool in_progress_ = false;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_BLOCK_PRELOADER_HPP_
