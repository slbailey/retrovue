// Repository: Retrovue-playout
// Component: VideoBufferFrame
// Purpose: Decoded video frame with metadata for the tick loop.
//          Extracted from VideoLookaheadBuffer.hpp to break circular dependency.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_VIDEO_BUFFER_FRAME_HPP_
#define RETROVUE_BLOCKPLAN_VIDEO_BUFFER_FRAME_HPP_

#include <cstdint>
#include <string>

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan {

// VideoBufferFrame carries a decoded (or repeated) video frame plus
// metadata needed by the tick loop for fingerprinting and accumulation.
struct VideoBufferFrame {
  buffer::Frame video;
  std::string asset_uri;
  int64_t block_ct_ms = -1;  // CT at decode time; -1 for repeats
  bool was_decoded = false;   // true = real decode, false = cadence repeat or hold-last
  int32_t segment_origin_id = -1;  // INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001: segment that produced this frame
  int64_t source_frame_index = -1;  // INV-HANDOFF-DIAG: 0-based source frame index (for frame_gap logging)
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_VIDEO_BUFFER_FRAME_HPP_
