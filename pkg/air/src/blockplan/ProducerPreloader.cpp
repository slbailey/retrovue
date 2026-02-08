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
                                   int width, int height, double fps) {
  Cancel();

  cancel_requested_.store(false, std::memory_order_release);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_.reset();
  }
  in_progress_ = true;

  thread_ = std::thread(&ProducerPreloader::Worker, this,
                         block, width, height, fps);
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
// Creates a TickProducer and calls AssignBlock (the heavy work).
// =============================================================================

void ProducerPreloader::Worker(FedBlock block, int width, int height, double fps) {
  if (cancel_requested_.load(std::memory_order_acquire)) return;

  // Test hook: artificial delay before AssignBlock
  if (delay_hook_) {
    delay_hook_();
  }

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  auto source = std::make_unique<TickProducer>(width, height, fps);
  source->AssignBlock(block);

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  // INV-BLOCK-PRIME-001/006: Decode first frame into held slot.
  // Direct continuation of AssignBlock on worker thread — no poll, no timer.
  source->PrimeFirstFrame();

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  std::cout << "[ProducerPreloader] Preload complete: block=" << block.block_id
            << " state=" << (source->GetState() == ITickProducer::State::kReady
                                 ? "READY" : "EMPTY")
            << " decoder_ok=" << source->HasDecoder()
            << std::endl;

  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_ = std::move(source);
  }
}

}  // namespace retrovue::blockplan
