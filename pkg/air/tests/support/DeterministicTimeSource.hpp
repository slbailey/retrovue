#pragma once
#include "time/ITimeSource.hpp"

class DeterministicTimeSource : public ITimeSource {
public:
  explicit DeterministicTimeSource(int64_t start_ms = 0)
      : now_ns_(start_ms * 1'000'000) {}

  int64_t NowUtcMs() const override {
    return now_ns_ / 1'000'000;
  }

  void AdvanceNs(int64_t delta_ns) {
    now_ns_ += delta_ns;
  }

  // Legacy ms APIs (preserved for existing callers)
  void AdvanceMs(int64_t delta) {
    now_ns_ += delta * 1'000'000;
  }

  void SetMs(int64_t value) {
    now_ns_ = value * 1'000'000;
  }

private:
  int64_t now_ns_;
};
