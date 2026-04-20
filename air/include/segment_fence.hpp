// AIR vNext — Segment fence-tick arithmetic.
//
// Pure-function helpers for computing segment end times in UTC ms and
// monotonic us, per INV-SEAM-FENCE-ARITHMETIC-001:
//
//   segment_end_utc_ms = block.start_utc_ms + sum(segments[0..N].duration_ms)
//                        (inclusive of segment N)
//   segment_fence_monotonic_us =
//       anchor_monotonic_us + (segment_end_utc_ms - anchor_utc_ms) * 1000
//
// No drift compensation, no mid-session clock re-anchoring, no alternative
// formulas. These are the canonical computations that SeamController will
// consume when arming seams (C1.3+).
//
// Pure arithmetic. No I/O, no state. Scope strictly C1.1 — arithmetic only.

#ifndef AIR_SEGMENT_FENCE_HPP_
#define AIR_SEGMENT_FENCE_HPP_

#include <cstdint>
#include <optional>

#include "block.hpp"

namespace retrovue::air {

// Session anchor: the mapping between monotonic time and wall-clock UTC
// at which AIR's timeline begins. Established at OnAir entry (future work);
// passed into fence computation as a pure input.
struct SessionAnchor {
  int64_t anchor_monotonic_us = 0;
  int64_t anchor_utc_ms = 0;
};

// Compute the UTC end time of a specific segment within a block.
// Returns nullopt if segment_index is out of bounds or the block has no
// segments. Non-negative segment_index required (int32_t; negative returns
// nullopt).
std::optional<int64_t> SegmentEndUtcMs(const Block& block,
                                       int32_t segment_index);

// Compute the fence tick (monotonic microseconds) of a specific segment.
// Returns nullopt if segment_index is out of bounds. Per
// INV-SEAM-FENCE-ARITHMETIC-001.
std::optional<int64_t> SegmentFenceMonotonicUs(const Block& block,
                                               int32_t segment_index,
                                               const SessionAnchor& anchor);

// Convenience: the final-segment fence of a block. Equivalent to
// SegmentFenceMonotonicUs(block, block.segments.size() - 1, anchor).
// Returns nullopt if the block has no segments.
std::optional<int64_t> BlockFinalFenceMonotonicUs(const Block& block,
                                                  const SessionAnchor& anchor);

// Sanity helper: sum of all segment durations in the block. Does not
// validate against block.end_utc_ms; caller may compare to detect malformed
// blocks (sum != end - start).
int64_t TotalSegmentDurationMs(const Block& block);

}  // namespace retrovue::air

#endif  // AIR_SEGMENT_FENCE_HPP_
