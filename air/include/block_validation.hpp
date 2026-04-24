// AIR vNext — structural Block admission validation (IR2.1).
//
// Pure-function check on a Block's intrinsic well-formedness as it
// arrives from Core. Does NOT check:
//   - canonical compatibility with the session (IR2.2)
//   - predecessor/window continuity (IR2.3)
//   - window-lock for revisions (IR2.4)
//   - session state (NO_SESSION etc.)
// Those live in AirSession and are applied alongside this validator.

#ifndef AIR_BLOCK_VALIDATION_HPP_
#define AIR_BLOCK_VALIDATION_HPP_

#include <string>

#include "block.hpp"

namespace retrovue::air {

// Reason codes (precedence order, top to bottom):
//   "EMPTY_SEGMENTS"      — segments list is empty
//   "INVALID_TIME_WINDOW" — start_utc_ms <= 0, or end_utc_ms <= start_utc_ms
//   "MALFORMED_SEGMENT"   — any segment has an empty asset_uri,
//                           duration_ms <= 0, asset_start_offset_ms < 0,
//                           or segment_index != its position in the list
//   "DURATION_MISMATCH"   — sum(segment.duration_ms)
//                           != (end_utc_ms - start_utc_ms)
//
// On failure, writes the code to *reason_out (if non-null) and returns
// false. On success, returns true and leaves *reason_out untouched.
bool ValidateBlockStructure(const Block& block, std::string* reason_out);

}  // namespace retrovue::air

#endif  // AIR_BLOCK_VALIDATION_HPP_
