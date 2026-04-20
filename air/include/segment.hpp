// AIR vNext — Segment record.
//
// Per Truth - Segment Is AIR's Runtime Unit: Segment is AIR's unit of
// playback execution. AIR performs decode, timing, seams, join-in-progress,
// pad insertion, pacing, and source transitions at Segment boundaries.
//
// Segments live inside a Block (every Block contains 1..N Segments).
// Segments are never top-level handoff objects — they arrive as part of
// a Block payload.
//
// Mirrors the retrovue.air.v1.Segment proto message; conversion helpers
// live in grpc_service.cpp.

#ifndef AIR_SEGMENT_HPP_
#define AIR_SEGMENT_HPP_

#include <cstdint>
#include <string>

namespace retrovue::air {

struct Segment {
  // Stable identity chosen by Core (opaque to AIR). For observability
  // and as-run traceability.
  std::string segment_id;

  // Asset location. v1: local file path.
  std::string asset_uri;

  // Offset into the asset at which this Segment's content begins.
  // 0 = play from start. Non-zero = enter mid-asset.
  int64_t asset_start_offset_ms = 0;

  // Segment duration. Sum of durations across a Block's Segments MUST
  // equal the Block's (end_utc_ms - start_utc_ms).
  int64_t duration_ms = 0;

  // Ordinal position within the parent Block's segments list (0-based).
  int32_t segment_index = 0;
};

}  // namespace retrovue::air

#endif  // AIR_SEGMENT_HPP_
