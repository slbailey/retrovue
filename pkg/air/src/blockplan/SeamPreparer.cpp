// Repository: Retrovue-playout
// Component: SeamPreparer Implementation
// Purpose: Background preparation for segment and block seam transitions.
// Contract Reference: INV-SEAM-SEG-001..007
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/SeamPreparer.hpp"

#include <algorithm>
#include <cassert>
#include <iostream>
#include <sstream>

#include "retrovue/blockplan/ITickProducer.hpp"
#include "retrovue/blockplan/TickProducer.hpp"
#include "retrovue/util/Logger.hpp"

namespace retrovue::blockplan {

using retrovue::util::Logger;

SeamPreparer::SeamPreparer() {
  worker_thread_ = std::thread(&SeamPreparer::WorkerLoop, this);
}

SeamPreparer::~SeamPreparer() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    shutdown_.store(true, std::memory_order_release);
    cancel_requested_.store(true, std::memory_order_release);
  }
  work_cv_.notify_all();
  if (worker_thread_.joinable()) {
    worker_thread_.join();
  }
}

// INV-SEAM-SUBMIT-SAFE: Submit() is thread-safe while the worker is running.
// The queue is sorted by seam_frame ascending — this defines execution priority.
// Callers must NOT gate submission on IsRunning(); doing so starves later
// requests (e.g., segment prep blocked behind block prep) and causes MISS
// at seam time.  The worker drains the queue in seam_frame order; a segment
// request at frame 30 will be processed before a block request at frame 60,
// even if both are submitted while the worker is busy with something else.
void SeamPreparer::Submit(SeamRequest request) {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    // Insert sorted by seam_frame ascending (earliest first).
    auto it = std::lower_bound(
        queue_.begin(), queue_.end(), request.seam_frame,
        [](const SeamRequest& a, int64_t frame) {
          return a.seam_frame < frame;
        });
    queue_.insert(it, std::move(request));
  }
  work_cv_.notify_one();
}

bool SeamPreparer::HasSegmentResult() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return segment_result_ != nullptr;
}

bool SeamPreparer::HasBlockResult() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return block_result_ != nullptr;
}

std::optional<SeamResultIdentity> SeamPreparer::PeekSegmentResult() const {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!segment_result_) return std::nullopt;
  SeamResultIdentity id;
  id.parent_block_id = segment_result_->parent_block_id;
  id.parent_segment_index = segment_result_->parent_segment_index;
  return id;
}

std::unique_ptr<SeamResult> SeamPreparer::TakeSegmentResult() {
  std::lock_guard<std::mutex> lock(mutex_);
  return std::move(segment_result_);
}

std::unique_ptr<SeamResult> SeamPreparer::TakeBlockResult() {
  std::lock_guard<std::mutex> lock(mutex_);
  return std::move(block_result_);
}

void SeamPreparer::Cancel() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    cancel_requested_.store(true, std::memory_order_release);
    queue_.clear();
  }
  work_cv_.notify_all();

  // Spin-wait for worker to finish current request.
  // The worker checks cancel_requested_ at multiple checkpoints.
  while (true) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!worker_active_) break;
  }

  {
    std::lock_guard<std::mutex> lock(mutex_);
    segment_result_.reset();
    block_result_.reset();
    cancel_requested_.store(false, std::memory_order_release);
  }
}

void SeamPreparer::CancelSegmentRequests() {
  std::lock_guard<std::mutex> lock(mutex_);
  // Remove all segment requests from queue.
  queue_.erase(
      std::remove_if(queue_.begin(), queue_.end(),
                     [](const SeamRequest& r) {
                       return r.type == SeamRequestType::kSegment;
                     }),
      queue_.end());
  // Clear segment result if any.
  segment_result_.reset();
}

bool SeamPreparer::IsRunning() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return worker_active_;
}

bool SeamPreparer::HasPending() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return !queue_.empty();
}

void SeamPreparer::SetDelayHook(DelayHookFn hook) {
  std::lock_guard<std::mutex> lock(mutex_);
  delay_hook_ = std::move(hook);
}

// =============================================================================
// WorkerLoop — persistent thread, waits for requests
// =============================================================================

void SeamPreparer::WorkerLoop() {
  while (true) {
    SeamRequest req;

    {
      std::unique_lock<std::mutex> lock(mutex_);
      work_cv_.wait(lock, [this] {
        return shutdown_.load(std::memory_order_acquire) ||
               cancel_requested_.load(std::memory_order_acquire) ||
               !queue_.empty();
      });

      if (shutdown_.load(std::memory_order_acquire)) return;

      if (cancel_requested_.load(std::memory_order_acquire)) {
        // Drain queue, reset cancel flag, loop back to wait.
        queue_.clear();
        cancel_requested_.store(false, std::memory_order_release);
        continue;
      }

      if (queue_.empty()) continue;

      req = std::move(queue_.front());
      queue_.erase(queue_.begin());
      worker_active_ = true;
    }

    ProcessRequest(req);

    {
      std::lock_guard<std::mutex> lock(mutex_);
      worker_active_ = false;
    }
    // Wake any thread waiting in Cancel().
    work_cv_.notify_all();
  }
}

// =============================================================================
// ProcessRequest — runs on worker thread, same cancel-check pattern as
// ProducerPreloader::Worker (4 checkpoints)
// =============================================================================

void SeamPreparer::ProcessRequest(const SeamRequest& req) {
  // Checkpoint 1
  if (cancel_requested_.load(std::memory_order_acquire)) return;

  if (req.type == SeamRequestType::kBlock) {
    std::ostringstream oss;
    oss << "[SeamPreparer] PREROLL_WORKER_START block_id=" << req.block.block_id
        << " seam_frame=" << req.seam_frame;
    Logger::Info(oss.str());
  }

  // Test hook: artificial delay
  {
    DelayHookFn hook;
    {
      std::lock_guard<std::mutex> lock(mutex_);
      hook = delay_hook_;
    }
    if (hook) hook();
  }

  // Checkpoint 2
  if (cancel_requested_.load(std::memory_order_acquire)) return;

  // INV-SEAM-SEG-PRIME-001: For segment requests, the block must be single-segment.
  if (req.type == SeamRequestType::kSegment) {
    assert(req.block.segments.size() == 1 &&
           "INV-SEAM-SEG-PRIME-001: Segment prep blocks must be single-segment");
  }

  auto source = std::make_unique<TickProducer>(req.width, req.height, req.fps);
  source->AssignBlock(req.block);
  source->SetLogicalSegmentIndex(req.segment_index);

  // Checkpoint 3
  if (cancel_requested_.load(std::memory_order_acquire)) return;

  // Extract segment type from the (single-segment) block for logging and result.
  SegmentType seg_type = SegmentType::kContent;
  if (!req.block.segments.empty()) {
    seg_type = req.block.segments[0].segment_type;
  }
  const bool is_pad = (seg_type == SegmentType::kPad);

  // First decode + audio prime loop (INV-AUDIO-PRIME-001)
  auto prime_result = source->PrimeFirstTick(req.min_audio_prime_ms);

  // Checkpoint 4
  if (cancel_requested_.load(std::memory_order_acquire)) return;

  if (req.type == SeamRequestType::kBlock && !is_pad) {
    std::ostringstream oss;
    oss << "[SeamPreparer] PREROLL_WORKER_PRIME block_id=" << req.block.block_id
        << " first_decode_ok=" << (source->HasDecoder() ? "Y" : "N")
        << " audio_depth_ms=" << prime_result.actual_depth_ms
        << " met_threshold=" << (prime_result.met_threshold ? "Y" : "N");
    Logger::Info(oss.str());
  }

  // Suppress AUDIO_PRIME_WARN for PAD segments: PAD has no decoder and no
  // audio to prime — wanted_ms is meaningless and the warning is misleading.
  if (!prime_result.met_threshold && req.min_audio_prime_ms > 0 && !is_pad) {
    std::ostringstream oss;
    oss << "[SeamPreparer] AUDIO_PRIME_WARN:"
        << " type=" << (req.type == SeamRequestType::kSegment ? "segment" : "block")
        << " block=" << req.block.block_id
        << " segment_index=" << req.segment_index
        << " segment_type=" << SegmentTypeName(seg_type)
        << " wanted_ms=" << req.min_audio_prime_ms
        << " got_ms=" << prime_result.actual_depth_ms;
    Logger::Warn(oss.str());
  }

  if (is_pad) {
    // PAD segments are synthetic — no decoder, no real audio/video.
    // Emit a distinct log that cannot be confused with decoder activity.
    std::ostringstream oss;
    oss << "[PadSource] PREROLL"
        << " block_id=" << req.block.block_id
        << " segment_index=" << req.segment_index
        << " seam_frame=" << req.seam_frame
        << " audio_synthetic=Y"
        << " video_synthetic=Y";
    Logger::Info(oss.str());
  } else {
    std::ostringstream oss;
    oss << "[SeamPreparer] PREP_COMPLETE"
        << " type=" << (req.type == SeamRequestType::kSegment ? "segment" : "block")
        << " block=" << req.block.block_id
        << " segment_index=" << req.segment_index
        << " segment_type=" << SegmentTypeName(seg_type)
        << " decoder_used=" << (source->HasDecoder() ? "true" : "false")
        << " audio_depth_ms=" << prime_result.actual_depth_ms;
    Logger::Info(oss.str());
    // Surface preroll failure: content block but decoder open/seek failed.
    if (req.type == SeamRequestType::kBlock && !source->HasDecoder()) {
      std::ostringstream fail_oss;
      fail_oss << "[SeamPreparer] PREROLL_DECODER_FAILED"
               << " block_id=" << req.block.block_id
               << " reason=content_block_no_decoder_in_worker";
      Logger::Warn(fail_oss.str());
    }
  }

  auto result = std::make_unique<SeamResult>();
  result->producer = std::move(source);
  result->audio_prime_depth_ms = prime_result.actual_depth_ms;
  result->type = req.type;
  result->block_id = req.block.block_id;
  result->segment_index = req.segment_index;
  result->segment_type = seg_type;
  result->parent_block_id = req.parent_block_id;
  result->parent_segment_index = req.segment_index;

  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (req.type == SeamRequestType::kSegment) {
      segment_result_ = std::move(result);
    } else {
      block_result_ = std::move(result);
    }
  }
  work_cv_.notify_all();
}

}  // namespace retrovue::blockplan
