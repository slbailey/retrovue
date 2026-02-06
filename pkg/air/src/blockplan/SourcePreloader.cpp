// Repository: Retrovue-playout
// Component: Source Preloader Implementation
// Purpose: Background BlockSource preparation for ContinuousOutput A/B swap
// Contract Reference: PlayoutAuthorityContract.md (P3.1b)
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/SourcePreloader.hpp"

#include <iostream>

#include "retrovue/blockplan/BlockSource.hpp"

namespace retrovue::blockplan {

SourcePreloader::~SourcePreloader() {
  Cancel();
}

void SourcePreloader::JoinThread() {
  if (thread_.joinable()) {
    thread_.join();
  }
  in_progress_ = false;
}

void SourcePreloader::StartPreload(const FedBlock& block,
                                   int width, int height, double fps) {
  Cancel();

  cancel_requested_.store(false, std::memory_order_release);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_.reset();
  }
  in_progress_ = true;

  thread_ = std::thread(&SourcePreloader::Worker, this,
                         block, width, height, fps);
}

bool SourcePreloader::IsReady() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return result_ != nullptr;
}

std::unique_ptr<BlockSource> SourcePreloader::TakeSource() {
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

void SourcePreloader::Cancel() {
  cancel_requested_.store(true, std::memory_order_release);
  JoinThread();

  std::lock_guard<std::mutex> lock(mutex_);
  result_.reset();
}

void SourcePreloader::SetDelayHook(DelayHookFn hook) {
  delay_hook_ = std::move(hook);
}

// =============================================================================
// Worker — runs on background thread
// Creates a BlockSource and calls AssignBlock (the heavy work).
// =============================================================================

void SourcePreloader::Worker(FedBlock block, int width, int height, double fps) {
  if (cancel_requested_.load(std::memory_order_acquire)) return;

  // Test hook: artificial delay before AssignBlock
  if (delay_hook_) {
    delay_hook_();
  }

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  auto source = std::make_unique<BlockSource>(width, height, fps);
  source->AssignBlock(block);

  if (cancel_requested_.load(std::memory_order_acquire)) return;

  std::cout << "[SourcePreloader] Preload complete: block=" << block.block_id
            << " state=" << (source->GetState() == BlockSource::State::kReady
                                 ? "READY" : "EMPTY")
            << " decoder_ok=" << source->HasDecoder()
            << std::endl;

  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_ = std::move(source);
  }
}

}  // namespace retrovue::blockplan
