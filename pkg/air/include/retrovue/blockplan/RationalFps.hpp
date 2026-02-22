#ifndef RETROVUE_BLOCKPLAN_RATIONAL_FPS_HPP_
#define RETROVUE_BLOCKPLAN_RATIONAL_FPS_HPP_

#include <cstdint>

namespace retrovue::blockplan {

constexpr int64_t FpsAbs64(int64_t v) { return v < 0 ? -v : v; }

constexpr int64_t FpsGcd64(int64_t a, int64_t b) {
  a = FpsAbs64(a);
  b = FpsAbs64(b);
  while (b != 0) {
    const int64_t t = a % b;
    a = b;
    b = t;
  }
  return a == 0 ? 1 : a;
}

struct RationalFps {
  int64_t num;
  int64_t den;

  constexpr RationalFps(int64_t n = 0, int64_t d = 1) : num(n), den(d) {
    NormalizeInPlace();
  }

  constexpr bool IsValid() const { return num > 0 && den > 0; }

  constexpr void NormalizeInPlace() {
    if (den == 0) {
      num = 0;
      den = 1;
      return;
    }
    if (den < 0) {
      den = -den;
      num = -num;
    }
    if (num <= 0 || den <= 0) {
      num = 0;
      den = 1;
      return;
    }
    const int64_t g = FpsGcd64(num, den);
    num /= g;
    den /= g;
  }

  constexpr double ToDouble() const { return static_cast<double>(num) / static_cast<double>(den); }

  constexpr int64_t FrameDurationUs() const {
    return IsValid() ? ((1000000LL * den) / num) : 0;
  }
  constexpr int64_t FrameDurationNs() const {
    return IsValid() ? ((1000000000LL * den) / num) : 0;
  }
  constexpr int64_t FrameDurationMs() const {
    return IsValid() ? ((1000LL * den) / num) : 0;
  }

  constexpr double FrameDurationSec() const {
    return IsValid() ? (static_cast<double>(den) / static_cast<double>(num)) : 0.0;
  }

  constexpr bool MatchesWithinTolerance(const RationalFps& other, double tolerance) const {
    if (!IsValid() || !other.IsValid()) return false;
    const double ratio = ToDouble() / other.ToDouble();
    return (ratio >= (1.0 - tolerance)) && (ratio <= (1.0 + tolerance));
  }

  constexpr int64_t DurationFromFramesUs(int64_t frames) const {
    return IsValid() ? ((frames * 1000000LL * den) / num) : 0;
  }
  constexpr int64_t DurationFromFramesNs(int64_t frames) const {
    return IsValid() ? ((frames * 1000000000LL * den) / num) : 0;
  }

  constexpr int64_t FramesFromDurationFloorUs(int64_t delta_us) const {
    return IsValid() ? ((delta_us * num) / (den * 1000000LL)) : 0;
  }
  constexpr int64_t FramesFromDurationCeilUs(int64_t delta_us) const {
    if (!IsValid()) return 0;
    const int64_t numer = delta_us * num;
    const int64_t denom = den * 1000000LL;
    return (numer + denom - 1) / denom;
  }
  constexpr int64_t FramesFromDurationFloorMs(int64_t delta_ms) const {
    return IsValid() ? ((delta_ms * num) / (den * 1000LL)) : 0;
  }
  constexpr int64_t FramesFromDurationCeilMs(int64_t delta_ms) const {
    if (!IsValid()) return 0;
    const int64_t numer = delta_ms * num;
    const int64_t denom = den * 1000LL;
    return (numer + denom - 1) / denom;
  }

  constexpr bool operator==(const RationalFps& other) const {
    return num == other.num && den == other.den;
  }
  constexpr bool operator!=(const RationalFps& other) const {
    return !(*this == other);
  }
};

constexpr RationalFps FPS_23976{24000, 1001};
constexpr RationalFps FPS_2997{30000, 1001};
constexpr RationalFps FPS_5994{60000, 1001};
constexpr RationalFps FPS_30{30, 1};
constexpr RationalFps FPS_60{60, 1};
constexpr RationalFps FPS_24{24, 1};
constexpr RationalFps FPS_25{25, 1};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_RATIONAL_FPS_HPP_
