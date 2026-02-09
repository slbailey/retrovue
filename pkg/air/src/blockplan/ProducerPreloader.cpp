// Repository: Retrovue-playout
// Component: Producer Preloader Implementation
// Purpose: Background TickProducer preparation for PipelineManager A/B swap
// Contract Reference: PlayoutAuthorityContract.md (P3.1b)
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/ProducerPreloader.hpp"

#include <iostream>

#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"

namespace retrovue::blockplan {

ProducerPreloader::~ProducerPreloader() {
  Cancel();
}

void ProducerPreloader::JoinThread() {
  if (thread_.joinable()) {
    thread_.join();
  }
  in_progress_ = false;
}

void ProducerPreloader::StartPreload(const FedBlock& block,
                                   int width, int height, double fps,
                                   int min_audio_prime_ms) {
  Cancel();

  cancel_requested_.store(false, std::memory_order_release);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_.reset();
  }
  in_progress_ = true;

  thread_ = std::thread(&ProducerPreloader::Worker, this,
                         block, width, height, fps, min_audio_prime_ms);
}

bool ProducerPreloader::IsReady() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return result_ != nullptr;
}

std::unique_ptr<producers::IProducer> ProducerPreloader::TakeSource() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!result_) return nullptr;

  auto src = std::move(result_);
  // Worker has already exited (it wrote result_ then returned).
  if (thread_.joinable()) {
    thread_.detach();
    in_progress_ = false;
  }
  return src;
}

void ProducerPreloader::Cancel() {
  cancel_requested_.store(true, std::memory_order_release);
  JoinThread();

  std::lock_guard<std::mutex> lock(mutex_);
  result_.reset();
}

void ProducerPreloader::SetDelayHook(DelayHookFn hook) {
  delay_hook_ = std::move(hook);
}

// =============================================================================
// Worker — runs on background thread
// Creates a TickProducer, calls AssignBlock + PrimeFirstTick.
// Always publishes the producer if AssignBlock succeeded (kReady state).
// Audio prime shortfall is telemetry — the tick loop's safety-net silence
// handles audio gaps.  No block that enters the system is ever silently lost.
// =============================================================================

void ProducerPreloader::Worker(FedBlock block, int width, int height,
                               double fps, int min_audio_prime_ms) {
  if (cancel_requested_.load(std::memory_order_acquire)) return;

  // Test hook: artificial delay before AssignBlock
  if (delay_hook_) {
    delay_hook_();
  }

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  auto source = std::make_unique<TickProducer>(width, height, fps);
  source->AssignBlock(block);

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  // INV-AUDIO-PRIME-001: PrimeFirstTick decodes video frame 0 plus enough
  // audio to cover min_audio_prime_ms.  All decode I/O happens here on the
  // worker thread — the fence path does zero decode.
  bool primed = source->PrimeFirstTick(min_audio_prime_ms);

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  if (!primed && min_audio_prime_ms > 0) {
    std::cerr << "[ProducerPreloader] AUDIO_PRIME_WARN: block=" << block.block_id
              << " wanted_ms=" << min_audio_prime_ms
              << " decoder_ok=" << source->HasDecoder()
              << " — safety-net silence will cover audio gap"
              << std::endl;
  }

  std::cout << "[ProducerPreloader] Preload complete: block=" << block.block_id
            << " state=" << (source->GetState() == ITickProducer::State::kReady
                                 ? "READY" : "EMPTY")
            << " decoder_ok=" << source->HasDecoder()
            << " has_primed=" << source->HasPrimedFrame()
            << " audio_primed=" << primed
            << std::endl;

  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_ = std::move(source);
  }
}

}  // namespace retrovue::blockplan
