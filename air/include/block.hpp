// AIR vNext — Block record.
//
// Per Truth - Block Is Handoff Unit and Segment Is Playback Unit: Block
// is the smallest unit of work transferred from Core to AIR. Every Block
// contains 1..N Segments (a Block with zero Segments is malformed).
//
// Block boundaries are editorial; Segment boundaries are runtime. Runtime
// transitions land on Segment boundaries. Block boundaries coincide with
// a runtime seam only because one Block's final Segment is followed by
// another Block's first Segment.
//
// Mirrors the retrovue.air.v1.Block proto message; conversion helpers
// live in grpc_service.cpp.

#ifndef AIR_BLOCK_HPP_
#define AIR_BLOCK_HPP_

#include <cstdint>
#include <string>
#include <vector>

#include "channel_canonical.hpp"
#include "segment.hpp"

namespace retrovue::air {

struct Block {
  // Stable editorial identity chosen by Core. Revisions and retirements
  // key on this field. Opaque to AIR.
  std::string block_id;

  // Editorial airing window in wall-clock UTC ms. end_utc_ms is the
  // outer fence; AIR MUST NOT overrun.
  int64_t start_utc_ms = 0;
  int64_t end_utc_ms = 0;

  // Channel canonical parameters for this Block. For v1, all Blocks in
  // a session are expected to share canonical.
  ChannelCanonical canonical{};

  // Ordered list of Segments (1..N). MUST contain at least one Segment.
  // Segments are executed in order; seams fire at every boundary.
  std::vector<Segment> segments;
};

}  // namespace retrovue::air

#endif  // AIR_BLOCK_HPP_
