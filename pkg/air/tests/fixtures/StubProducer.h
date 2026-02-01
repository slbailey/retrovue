// Phase 6A.1 — Stub producer for ExecutionProducer lifecycle and slot contract tests.
// Records start/stop and segment params; no decode, no threads.

#ifndef RETROVUE_TESTS_FIXTURES_STUB_PRODUCER_H_
#define RETROVUE_TESTS_FIXTURES_STUB_PRODUCER_H_

#include "retrovue/producers/IProducer.h"
#include <atomic>
#include <cstdint>
#include <string>

namespace retrovue::tests::fixtures {

class StubProducer : public retrovue::producers::IProducer {
 public:
  struct SegmentParams {
    std::string asset_path;
    std::string asset_id;
    int64_t start_offset_ms = 0;
    int64_t hard_stop_time_ms = 0;
  };

  explicit StubProducer(SegmentParams params)
      : params_(std::move(params)), running_(false), start_count_(0), stop_count_(0) {}

  bool start() override {
    if (running_.load()) return false;
    running_.store(true);
    start_count_.fetch_add(1);
    return true;
  }

  void stop() override {
    if (!running_.load()) return;
    running_.store(false);
    stop_count_.fetch_add(1);
  }

  bool isRunning() const override { return running_.load(); }

  void RequestStop() override { running_.store(false); }
  bool IsStopped() const override { return !running_.load(); }

  const SegmentParams& segmentParams() const { return params_; }
  int startCount() const { return start_count_.load(); }
  int stopCount() const { return stop_count_.load(); }

 private:
  SegmentParams params_;
  std::atomic<bool> running_;
  std::atomic<int> start_count_;
  std::atomic<int> stop_count_;
};

}  // namespace retrovue::tests::fixtures

#endif  // RETROVUE_TESTS_FIXTURES_STUB_PRODUCER_H_
