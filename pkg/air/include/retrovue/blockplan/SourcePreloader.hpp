// Repository: Retrovue-playout
// Component: Source Preloader
// Purpose: Background preparation of a BlockSource for ContinuousOutput A/B swap.
//          Runs AssignBlock (probe + open + seek) off the tick thread so the
//          engine can swap sources at the fence without stalling.
// Contract Reference: PlayoutAuthorityContract.md (P3.1b)
// Copyright (c) 2025 RetroVue
//
// SourcePreloader is distinct from the P2 BlockPreloader (which serves
// SerialBlockExecutionEngine).  SourcePreloader produces a fully READY
// BlockSource that the engine can adopt via pointer swap.

#ifndef RETROVUE_BLOCKPLAN_SOURCE_PRELOADER_HPP_
#define RETROVUE_BLOCKPLAN_SOURCE_PRELOADER_HPP_

#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"

namespace retrovue::blockplan {

class BlockSource;

class SourcePreloader {
 public:
  // Optional test hook: injected delay (milliseconds) before AssignBlock.
  // Production code leaves this null.  Tests set it to simulate slow preloads.
  using DelayHookFn = std::function<void()>;

  SourcePreloader() = default;
  ~SourcePreloader();

  SourcePreloader(const SourcePreloader&) = delete;
  SourcePreloader& operator=(const SourcePreloader&) = delete;

  // Start preloading a block into a new BlockSource on a background thread.
  // Cancels any in-progress preload first.
  // Parameters:
  //   block: the FedBlock to assign (copied for thread safety)
  //   width, height: output dimensions for the BlockSource
  //   fps: frame rate for the BlockSource
  void StartPreload(const FedBlock& block, int width, int height, double fps);

  // Non-blocking: true if the background work has finished.
  bool IsReady() const;

  // Non-blocking: returns the preloaded BlockSource if ready, nullptr otherwise.
  // Ownership transfers to caller.  After this call, the preloader is idle.
  std::unique_ptr<BlockSource> TakeSource();

  // Cancel any in-progress preload and join the worker thread.
  // Idempotent and safe to call even if no preload is active.
  void Cancel();

  // Test-only: install a delay hook called before AssignBlock in the worker.
  void SetDelayHook(DelayHookFn hook);

 private:
  void Worker(FedBlock block, int width, int height, double fps);
  void JoinThread();

  std::thread thread_;
  mutable std::mutex mutex_;
  std::atomic<bool> cancel_requested_{false};
  std::unique_ptr<BlockSource> result_;  // Guarded by mutex_
  bool in_progress_ = false;

  DelayHookFn delay_hook_;  // Test-only
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_SOURCE_PRELOADER_HPP_
