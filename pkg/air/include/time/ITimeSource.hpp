#pragma once
#include <cstdint>

class ITimeSource {
public:
  virtual ~ITimeSource() = default;
  virtual int64_t NowUtcMs() const = 0;
};
