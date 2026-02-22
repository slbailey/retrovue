#ifndef RETROVUE_BLOCKPLAN_RATIONAL_FPS_HPP_
#define RETROVUE_BLOCKPLAN_RATIONAL_FPS_HPP_

#include <cstdint>

namespace retrovue::blockplan {

struct RationalFps {
  int64_t num;
  int64_t den;

  constexpr double ToDouble() const { return static_cast<double>(num) / static_cast<double>(den); }
  constexpr int64_t FrameDurationUs() const { return (1000000LL * den) / num; }
  constexpr int64_t FrameDurationMs() const { return (1000LL * den) / num; }

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
