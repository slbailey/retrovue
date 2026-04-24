#include "block_validation.hpp"

#include <cstdint>

namespace retrovue::air {

bool ValidateBlockStructure(const Block& block, std::string* reason_out) {
  auto reject = [&](const char* r) {
    if (reason_out) *reason_out = r;
    return false;
  };

  if (block.segments.empty()) return reject("EMPTY_SEGMENTS");

  if (block.start_utc_ms <= 0 || block.end_utc_ms <= block.start_utc_ms) {
    return reject("INVALID_TIME_WINDOW");
  }

  int64_t sum_ms = 0;
  for (std::size_t i = 0; i < block.segments.size(); ++i) {
    const auto& s = block.segments[i];
    if (s.asset_uri.empty()) return reject("MALFORMED_SEGMENT");
    if (s.duration_ms <= 0) return reject("MALFORMED_SEGMENT");
    if (s.asset_start_offset_ms < 0) return reject("MALFORMED_SEGMENT");
    if (s.segment_index != static_cast<int32_t>(i)) {
      return reject("MALFORMED_SEGMENT");
    }
    sum_ms += s.duration_ms;
  }

  if (sum_ms != block.end_utc_ms - block.start_utc_ms) {
    return reject("DURATION_MISMATCH");
  }

  return true;
}

}  // namespace retrovue::air
