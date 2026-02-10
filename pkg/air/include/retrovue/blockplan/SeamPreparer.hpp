// Repository: Retrovue-playout
// Component: SeamPreparer
// Purpose: Background preparation thread for both segment and block seam
//          transitions.  Replaces ProducerPreloader as the single background
//          preparation mechanism.  Processes requests ordered by seam_frame
//          (earliest first) and publishes results to typed slots.
// Contract Reference: INV-SEAM-SEG-001..007
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_SEAM_PREPARER_HPP_
#define RETROVUE_BLOCKPLAN_SEAM_PREPARER_HPP_

#include <atomic>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/producers/IProducer.h"

namespace retrovue::blockplan {

class ITickProducer;

// Request types for SeamPreparer.
enum class SeamRequestType { kSegment, kBlock };

struct SeamRequest {
  SeamRequestType type;
  FedBlock block;            // Full block (kBlock) or synthetic single-segment (kSegment)
  int64_t seam_frame;        // Session frame where result is needed
  int width;
  int height;
  double fps;
  int min_audio_prime_ms;
  // Logging context
  std::string parent_block_id;
  int32_t segment_index = -1;
};

// Result from a completed seam preparation.
struct SeamResult {
  std::unique_ptr<producers::IProducer> producer;
  int audio_prime_depth_ms = 0;
  SeamRequestType type;
  std::string block_id;      // For logging correlation
  int32_t segment_index = -1;
  SegmentType segment_type = SegmentType::kContent;  // Type of the prepared segment
};

// SeamPreparer — persistent worker thread for seam transitions.
//
// Accepts segment and block prep requests, processes them in seam_frame order
// (earliest first), and publishes results to separate typed slots.
// The tick thread polls HasSegmentResult() / HasBlockResult() and takes
// results via TakeSegmentResult() / TakeBlockResult().
class SeamPreparer {
 public:
  using DelayHookFn = std::function<void()>;

  SeamPreparer();
  ~SeamPreparer();

  SeamPreparer(const SeamPreparer&) = delete;
  SeamPreparer& operator=(const SeamPreparer&) = delete;

  // Enqueue a prep request; wakes worker if idle.
  void Submit(SeamRequest request);

  // Non-blocking result checks.
  bool HasSegmentResult() const;
  bool HasBlockResult() const;

  // Move result out (ownership transfer).  Returns nullptr if no result.
  std::unique_ptr<SeamResult> TakeSegmentResult();
  std::unique_ptr<SeamResult> TakeBlockResult();

  // Cancel all pending + in-progress work; blocks until worker is idle.
  void Cancel();

  // Cancel segment-only requests (block prep preserved).
  void CancelSegmentRequests();

  // True if worker is currently processing a request.
  bool IsRunning() const;

  // True if queue is non-empty.
  bool HasPending() const;

  // Test-only: inject delay before AssignBlock in worker.
  void SetDelayHook(DelayHookFn hook);

 private:
  void WorkerLoop();
  void ProcessRequest(const SeamRequest& req);

  mutable std::mutex mutex_;
  std::condition_variable work_cv_;

  // Request queue, sorted by seam_frame ascending (earliest first).
  std::vector<SeamRequest> queue_;

  // Two result slots.
  std::unique_ptr<SeamResult> segment_result_;
  std::unique_ptr<SeamResult> block_result_;

  // Worker state.
  std::thread worker_thread_;
  std::atomic<bool> cancel_requested_{false};
  std::atomic<bool> shutdown_{false};
  bool worker_active_ = false;  // Guarded by mutex_

  DelayHookFn delay_hook_;  // Test-only
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_SEAM_PREPARER_HPP_
