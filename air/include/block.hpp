// AIR vNext — Block record.
//
// The shared block record exchanged across the Core↔AIR boundary.
// Identity via block_id; asset referenced by URI; fence via end_utc_ms.
// Mirrors the retrovue.air.v1.Block proto message; conversion helpers
// live in grpc_service.cpp.
//
// See:
//   - protos/air_control.proto (Block message)
//   - BlockSupplyDemand.md §Vocabulary Doctrine (AIR vNext)
//   - EXECUTION_QUEUE_AND_SEAMS_DESIGN.md §1 Queue ownership model

#ifndef AIR_BLOCK_HPP_
#define AIR_BLOCK_HPP_

#include <cstdint>
#include <string>

#include "channel_canonical.hpp"

namespace retrovue::air {

struct Block {
  // Stable editorial identity (opaque to AIR — string chosen by Core).
  std::string block_id;

  // Asset location. v1: local file path. Future: may be a URL.
  std::string asset_uri;

  // Editorial airing window in wall-clock UTC ms. end_utc_ms is the fence;
  // per fence-sacred doctrine, AIR MUST NOT overrun this boundary.
  int64_t start_utc_ms = 0;
  int64_t end_utc_ms = 0;

  // Join-in-progress offset into the asset (0 = play from start).
  int64_t jip_offset_ms = 0;

  // Channel canonical parameters for this block. For v1, all blocks in a
  // session are expected to share canonical; cross-canonical transitions
  // are a future slice.
  ChannelCanonical canonical{};
};

}  // namespace retrovue::air

#endif  // AIR_BLOCK_HPP_
