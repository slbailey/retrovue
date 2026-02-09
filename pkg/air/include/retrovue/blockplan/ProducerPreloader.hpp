// Repository: Retrovue-playout
// Component: Producer Preloader
// Purpose: Background preparation of a TickProducer for PipelineManager A/B swap.
//          Runs AssignBlock (probe + open + seek) off the tick thread so the
//          engine can swap sources at the fence without stalling.
// Contract Reference: PlayoutAuthorityContract.md (P3.1b)
// Copyright (c) 2025 RetroVue
//
// ProducerPreloader produces a fully READY IProducer (backed by TickProducer)
// that PipelineManager can adopt via pointer swap at the fence boundary.

#ifndef RETROVUE_BLOCKPLAN_PRODUCER_PRELOADER_HPP_
#define RETROVUE_BLOCKPLAN_PRODUCER_PRELOADER_HPP_

#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/producers/IProducer.h"

namespace retrovue::blockplan {

class ITickProducer;

class ProducerPreloader {
 public:
  // Optional test hook: injected delay (milliseconds) before AssignBlock.
  // Production code leaves this null.  Tests set it to simulate slow preloads.
  using DelayHookFn = std::function<void()>;

  ProducerPreloader() = default;
  ~ProducerPreloader();

  ProducerPreloader(const ProducerPreloader&) = delete;
  ProducerPreloader& operator=(const ProducerPreloader&) = delete;

  // Start preloading a block into a new TickProducer on a background thread.
  // Cancels any in-progress preload first.
  // Parameters:
  //   block: the FedBlock to assign (copied for thread safety)
  //   width, height: output dimensions for the TickProducer
  //   fps: frame rate for the TickProducer
  //   min_audio_prime_ms: if > 0, PrimeFirstTick must reach this audio
  //     threshold for the preload to be considered READY.  If the threshold
  //     is not met, IsReady() stays false (preload failure).
  void StartPreload(const FedBlock& block, int width, int height, double fps,
                    int min_audio_prime_ms = 0);

  // Non-blocking: true if the background work has finished.
  bool IsReady() const;

  // Non-blocking: returns the preloaded IProducer if ready, nullptr otherwise.
  // Ownership transfers to caller.  After this call, the preloader is idle.
  std::unique_ptr<producers::IProducer> TakeSource();

  // Cancel any in-progress preload and join the worker thread.
  // Idempotent and safe to call even if no preload is active.
  void Cancel();

  // Test-only: install a delay hook called before AssignBlock in the worker.
  void SetDelayHook(DelayHookFn hook);

 private:
  void Worker(FedBlock block, int width, int height, double fps,
              int min_audio_prime_ms);
  void JoinThread();

  std::thread thread_;
  mutable std::mutex mutex_;
  std::atomic<bool> cancel_requested_{false};
  std::unique_ptr<producers::IProducer> result_;  // Guarded by mutex_
  bool in_progress_ = false;

  DelayHookFn delay_hook_;  // Test-only
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PRODUCER_PRELOADER_HPP_
