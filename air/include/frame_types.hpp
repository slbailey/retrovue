// AIR vNext — frame types for channel-canonical scope.
//
// VideoFrame and AudioBlock are the data types that flow from Normalizer
// output into preview BufferStore instances and onward. They carry
// channel-time PTS as the decision-relevant timestamp, in relative form
// (offset from the segment's channel origin). Absolute channel PTS is
// computed at emission by `origin.channel_pts_anchor_us + pts_us_relative`.
//
// Source PTS MAY be tagged as opaque observability metadata (kSourcePtsUnknown
// sentinel when not set) but MUST NOT be consumed as a decision input.
//
// Vault references:
//   - Truth - Source Time Is Producer-Local, Channel Time Is Canonical
//   - Normalizer (output contract)
//   - BufferStore (preview role)

#ifndef RETROVUE_AIR_FRAME_TYPES_HPP_
#define RETROVUE_AIR_FRAME_TYPES_HPP_

#include <cstdint>
#include <limits>
#include <vector>

#include "channel_canonical.hpp"

namespace retrovue::air {

// Sentinel value for source PTS when not known / not applicable.
constexpr int64_t kSourcePtsUnknown = std::numeric_limits<int64_t>::min();

// A single channel-canonical video frame.
//
// Format MUST conform to the ChannelCanonical.video parameters the emitting
// Normalizer was constructed with. Width, height, and pixel format are not
// stored per-frame (they're ambient to the channel); the frame carries only
// the data buffer and PTS.
struct VideoFrame {
  // Channel-time PTS, relative to the segment's channel origin, in
  // microseconds. Absolute PTS is origin.channel_pts_anchor_us + pts_us_relative.
  int64_t pts_us_relative;

  // Opaque source PTS metadata. Observability only. MUST NOT be consumed
  // as a decision input downstream of the Normalizer.
  int64_t source_pts_us_opaque = kSourcePtsUnknown;

  // Raw pixel data, layout determined by ChannelCanonical.video.pixel_format.
  // For YUV420P: Y plane (w*h bytes) followed by U plane ((w/2)*(h/2)) then
  // V plane ((w/2)*(h/2)).
  std::vector<uint8_t> data;
};

// A block of channel-canonical audio samples.
//
// Interleaved PCM (int16). Sample rate and channel count MUST conform to the
// ChannelCanonical.audio parameters the emitting Normalizer was constructed
// with; they are not stored per-block.
struct AudioBlock {
  // Channel-time PTS of the first sample in the block, relative to the
  // segment's channel origin, in microseconds.
  int64_t pts_us_relative;

  // Opaque source PTS metadata. Observability only.
  int64_t source_pts_us_opaque = kSourcePtsUnknown;

  // Number of samples per channel in this block.
  int nb_samples;

  // Interleaved PCM int16 samples. Size = nb_samples * channels.
  std::vector<int16_t> data;
};

}  // namespace retrovue::air

#endif  // RETROVUE_AIR_FRAME_TYPES_HPP_
