// Repository: Retrovue-playout
// Component: Wait Strategy Interface
// Purpose: Decouple sleeping from deadline math in OutputClock.
//          Production: RealtimeWaitStrategy sleeps until deadline.
//          Tests: DeterministicWaitStrategy (advances virtual time, no sleep).
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_IWAIT_STRATEGY_HPP_
#define RETROVUE_BLOCKPLAN_IWAIT_STRATEGY_HPP_

#include <chrono>
#include <thread>

namespace retrovue::blockplan {

class IWaitStrategy {
 public:
  virtual void WaitUntil(std::chrono::steady_clock::time_point deadline) = 0;
  virtual ~IWaitStrategy() = default;
};

class RealtimeWaitStrategy : public IWaitStrategy {
 public:
  void WaitUntil(std::chrono::steady_clock::time_point deadline) override {
    std::this_thread::sleep_until(deadline);
  }
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_IWAIT_STRATEGY_HPP_
