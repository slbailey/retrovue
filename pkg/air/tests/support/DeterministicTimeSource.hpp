#pragma once
#include "time/ITimeSource.hpp"

class DeterministicTimeSource : public ITimeSource {
public:
  explicit DeterministicTimeSource(int64_t start_ms = 0)
      : now_ms_(start_ms) {}

  int64_t NowUtcMs() const override {
    return now_ms_;
  }

  void AdvanceMs(int64_t delta) {
    now_ms_ += delta;
  }

  void SetMs(int64_t value) {
    now_ms_ = value;
  }

private:
  int64_t now_ms_;
};
