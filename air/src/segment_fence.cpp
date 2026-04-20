// AIR vNext — Segment fence-tick arithmetic implementation.

#include "segment_fence.hpp"

namespace retrovue::air {

std::optional<int64_t> SegmentEndUtcMs(const Block& block,
                                       int32_t segment_index) {
  if (segment_index < 0) return std::nullopt;
  if (static_cast<size_t>(segment_index) >= block.segments.size()) {
    return std::nullopt;
  }
  // Sum durations [0..segment_index] inclusive per INV-SEAM-FENCE-ARITHMETIC-001.
  int64_t cumulative_ms = 0;
  for (int32_t i = 0; i <= segment_index; ++i) {
    cumulative_ms += block.segments[i].duration_ms;
  }
  return block.start_utc_ms + cumulative_ms;
}

std::optional<int64_t> SegmentFenceMonotonicUs(const Block& block,
                                               int32_t segment_index,
                                               const SessionAnchor& anchor) {
  const auto end_utc_ms = SegmentEndUtcMs(block, segment_index);
  if (!end_utc_ms.has_value()) return std::nullopt;
  // anchor_monotonic_us + (segment_end_utc_ms - anchor_utc_ms) * 1000
  // per INV-SEAM-FENCE-ARITHMETIC-001.
  return anchor.anchor_monotonic_us +
         (*end_utc_ms - anchor.anchor_utc_ms) * 1000;
}

std::optional<int64_t> BlockFinalFenceMonotonicUs(const Block& block,
                                                  const SessionAnchor& anchor) {
  if (block.segments.empty()) return std::nullopt;
  return SegmentFenceMonotonicUs(
      block, static_cast<int32_t>(block.segments.size()) - 1, anchor);
}

int64_t TotalSegmentDurationMs(const Block& block) {
  int64_t total = 0;
  for (const auto& s : block.segments) {
    total += s.duration_ms;
  }
  return total;
}

}  // namespace retrovue::air
