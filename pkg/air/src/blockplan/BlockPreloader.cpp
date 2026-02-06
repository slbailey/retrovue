// Repository: Retrovue-playout
// Component: Block Preloader Implementation
// Purpose: Background preloading of next block's heavy resources
// Contract Reference: P2 – Serial Block Preloading, PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/BlockPreloader.hpp"

#include <iostream>

namespace retrovue::blockplan {

BlockPreloader::~BlockPreloader() {
  Cancel();
}

void BlockPreloader::JoinThread() {
  if (thread_.joinable()) {
    thread_.join();
  }
  in_progress_ = false;
}

void BlockPreloader::StartPreload(const FedBlock& block, int width, int height) {
  // Cancel any in-progress preload first
  Cancel();

  // Reset state
  cancel_requested_.store(false, std::memory_order_release);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_.reset();
  }
  in_progress_ = true;

  // Copy block for thread safety (FedBlock contains strings)
  thread_ = std::thread(&BlockPreloader::PreloadWorker, this, block, width, height);
}

std::unique_ptr<BlockPreloadContext> BlockPreloader::TakeIfReady() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (result_) {
    // Transfer ownership to caller and join the completed thread
    auto ctx = std::move(result_);
    // Thread should be done if result is ready, but join safely
    if (thread_.joinable()) {
      // Use detach-then-null pattern to avoid blocking the engine thread.
      // The worker has already completed (it wrote result_ before exiting).
      thread_.detach();
      in_progress_ = false;
    }
    return ctx;
  }
  return nullptr;
}

void BlockPreloader::Cancel() {
  cancel_requested_.store(true, std::memory_order_release);
  JoinThread();

  // Discard any completed result
  std::lock_guard<std::mutex> lock(mutex_);
  result_.reset();
}

// =============================================================================
// PreloadWorker — runs on background thread
// Probes all assets, optionally opens decoder for first segment and seeks.
// Checks cancel_requested_ between heavy operations.
// =============================================================================

void BlockPreloader::PreloadWorker(FedBlock block, int width, int height) {
  auto ctx = std::make_unique<BlockPreloadContext>();
  ctx->block_id = block.block_id;

  // =========================================================================
  // Phase 1: Probe all assets
  // =========================================================================
  auto probe_start = std::chrono::steady_clock::now();

  for (const auto& seg : block.segments) {
    if (cancel_requested_.load(std::memory_order_acquire)) {
      return;  // Cancelled — discard partial work
    }

    if (!ctx->assets.ProbeAsset(seg.asset_uri)) {
      std::cerr << "[BlockPreloader] Failed to probe: " << seg.asset_uri
                << " (block=" << block.block_id << ")" << std::endl;
      // Partial probe is still useful — remaining assets fall back to sync probe
    }
  }

  auto probe_end = std::chrono::steady_clock::now();
  ctx->probe_us = std::chrono::duration_cast<std::chrono::microseconds>(
      probe_end - probe_start).count();

  // Mark assets ready if at least one segment was probed
  ctx->assets_ready = !block.segments.empty() &&
                      ctx->assets.HasAsset(block.segments[0].asset_uri);

  if (cancel_requested_.load(std::memory_order_acquire)) {
    return;
  }

  // =========================================================================
  // Phase 2: Open decoder for first segment and seek to offset
  // =========================================================================
  if (!block.segments.empty()) {
    const auto& first_seg = block.segments[0];

    decode::DecoderConfig dec_config;
    dec_config.input_uri = first_seg.asset_uri;
    dec_config.target_width = width;
    dec_config.target_height = height;

    auto decoder_open_start = std::chrono::steady_clock::now();
    auto decoder = std::make_unique<decode::FFmpegDecoder>(dec_config);

    if (decoder->Open()) {
      auto decoder_open_end = std::chrono::steady_clock::now();
      ctx->decoder_open_us = std::chrono::duration_cast<std::chrono::microseconds>(
          decoder_open_end - decoder_open_start).count();

      if (cancel_requested_.load(std::memory_order_acquire)) {
        return;
      }

      // Seek to segment offset
      auto seek_start = std::chrono::steady_clock::now();
      int preroll_count = decoder->SeekPreciseToMs(first_seg.asset_start_offset_ms);
      auto seek_end = std::chrono::steady_clock::now();
      ctx->seek_us = std::chrono::duration_cast<std::chrono::microseconds>(
          seek_end - seek_start).count();

      if (preroll_count >= 0) {
        ctx->decoder = std::move(decoder);
        ctx->decoder_asset_uri = first_seg.asset_uri;
        ctx->decoder_seek_target_ms = first_seg.asset_start_offset_ms;
        ctx->decoder_ready = true;
        ctx->preroll_frames = preroll_count;
      } else {
        std::cerr << "[BlockPreloader] Seek failed for: " << first_seg.asset_uri
                  << " at offset " << first_seg.asset_start_offset_ms << "ms"
                  << std::endl;
        // decoder_ready remains false — engine will open its own decoder
      }
    } else {
      auto decoder_open_end = std::chrono::steady_clock::now();
      ctx->decoder_open_us = std::chrono::duration_cast<std::chrono::microseconds>(
          decoder_open_end - decoder_open_start).count();
      std::cerr << "[BlockPreloader] Failed to open decoder for: "
                << first_seg.asset_uri << std::endl;
      // decoder_ready remains false — fallback to sync open
    }
  }

  if (cancel_requested_.load(std::memory_order_acquire)) {
    return;
  }

  // =========================================================================
  // Publish result
  // =========================================================================
  std::cout << "[BlockPreloader] Preload complete: block=" << block.block_id
            << " assets_ready=" << ctx->assets_ready
            << " decoder_ready=" << ctx->decoder_ready
            << " probe_us=" << ctx->probe_us
            << " decoder_open_us=" << ctx->decoder_open_us
            << " seek_us=" << ctx->seek_us
            << " preroll=" << ctx->preroll_frames
            << std::endl;

  {
    std::lock_guard<std::mutex> lock(mutex_);
    result_ = std::move(ctx);
  }
}

}  // namespace retrovue::blockplan
