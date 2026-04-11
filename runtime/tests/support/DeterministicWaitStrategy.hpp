// Repository: Retrovue-playout
// Component: Deterministic Wait Strategy (test only)
// Purpose: Delta-based virtual time advancement — advances DeterministicTimeSource
//          by exactly the frame delta on each tick. No sleep, no wall-clock drift.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_SUPPORT_DETERMINISTIC_WAIT_STRATEGY_HPP_
#define RETROVUE_TESTS_SUPPORT_DETERMINISTIC_WAIT_STRATEGY_HPP_

#include "retrovue/blockplan/IWaitStrategy.hpp"
#include "DeterministicTimeSource.hpp"
#include <chrono>
#include <memory>

namespace retrovue::blockplan {

class DeterministicWaitStrategy : public IWaitStrategy {
 public:
  explicit DeterministicWaitStrategy(std::shared_ptr<DeterministicTimeSource> ts)
      : ts_(std::move(ts)) {}

  void WaitUntil(std::chrono::steady_clock::time_point deadline) override {
    if (has_prev_) {
      auto delta = deadline - prev_deadline_;
      ts_->AdvanceNs(
          std::chrono::duration_cast<std::chrono::nanoseconds>(delta).count());
    }
    prev_deadline_ = deadline;
    has_prev_ = true;
  }

 private:
  std::shared_ptr<DeterministicTimeSource> ts_;
  std::chrono::steady_clock::time_point prev_deadline_{};
  bool has_prev_ = false;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_TESTS_SUPPORT_DETERMINISTIC_WAIT_STRATEGY_HPP_
