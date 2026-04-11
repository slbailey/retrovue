#pragma once
#include "time/ITimeSource.hpp"
#include <chrono>

class SystemTimeSource : public ITimeSource {
public:
  int64_t NowUtcMs() const override {
    using namespace std::chrono;
    return duration_cast<milliseconds>(
        system_clock::now().time_since_epoch()).count();
  }
};
