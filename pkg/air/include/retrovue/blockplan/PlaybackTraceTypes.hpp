// Repository: Retrovue-playout
// Component: Playback Trace Types
// Purpose: Header-only types for P3.3 execution trace logging.
//          Per-block playback summaries and seam transition records
//          derived from actual execution, not scheduled intent.
// Contract Reference: PlayoutAuthorityContract.md (P3.3)
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_PLAYBACK_TRACE_TYPES_HPP_
#define RETROVUE_BLOCKPLAN_PLAYBACK_TRACE_TYPES_HPP_

#include <algorithm>
#include <cstdint>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace retrovue::blockplan {

// =============================================================================
// BlockPlaybackSummary — aggregated per-block execution record
// Finalized when on_block_completed fires at the fence.
// =============================================================================

struct BlockPlaybackSummary {
  std::string block_id;
  std::vector<std::string> asset_uris;  // unique URIs observed, in order
  int64_t first_block_ct_ms = -1;       // CT of first real frame
  int64_t last_block_ct_ms = -1;        // CT of last real frame
  int64_t frames_emitted = 0;           // total frames (real + pad)
  int64_t pad_frames = 0;
  int64_t first_session_frame_index = -1;
  int64_t last_session_frame_index = -1;
};

// =============================================================================
// SeamTransitionLog — record of a block-to-block transition
// Emitted when a source swap or new block load follows a completed block.
// =============================================================================

struct SeamTransitionLog {
  std::string from_block_id;
  std::string to_block_id;
  int64_t fence_frame = 0;        // session_frame_index at fence
  int64_t pad_frames_at_fence = 0;
  bool seamless = true;           // pad_frames_at_fence == 0
};

// =============================================================================
// BlockAccumulator — per-block frame aggregation (engine-internal)
// Lives in the Run() loop.  Reset when a new block becomes active.
// =============================================================================

struct BlockAccumulator {
  std::string block_id;
  std::set<std::string> asset_uri_set;
  std::vector<std::string> asset_uri_order;  // insertion order, unique
  int64_t first_ct_ms = -1;
  int64_t last_ct_ms = -1;
  int64_t frames = 0;
  int64_t pad_frames = 0;
  int64_t first_session_frame = -1;
  int64_t last_session_frame = -1;

  void Reset(const std::string& id) {
    block_id = id;
    asset_uri_set.clear();
    asset_uri_order.clear();
    first_ct_ms = -1;
    last_ct_ms = -1;
    frames = 0;
    pad_frames = 0;
    first_session_frame = -1;
    last_session_frame = -1;
  }

  void AccumulateFrame(int64_t session_idx, bool is_pad,
                       const std::string& uri, int64_t ct_ms) {
    frames++;
    if (first_session_frame < 0) first_session_frame = session_idx;
    last_session_frame = session_idx;

    if (is_pad) {
      pad_frames++;
    } else {
      if (!uri.empty() && asset_uri_set.insert(uri).second) {
        asset_uri_order.push_back(uri);
      }
      if (first_ct_ms < 0) first_ct_ms = ct_ms;
      last_ct_ms = ct_ms;
    }
  }

  BlockPlaybackSummary Finalize() const {
    BlockPlaybackSummary s;
    s.block_id = block_id;
    s.asset_uris = asset_uri_order;
    s.first_block_ct_ms = first_ct_ms;
    s.last_block_ct_ms = last_ct_ms;
    s.frames_emitted = frames;
    s.pad_frames = pad_frames;
    s.first_session_frame_index = first_session_frame;
    s.last_session_frame_index = last_session_frame;
    return s;
  }
};

// =============================================================================
// Formatting — human-readable log lines
// =============================================================================

inline std::string FormatPlaybackSummary(const BlockPlaybackSummary& s) {
  std::ostringstream oss;
  oss << "[CONTINUOUS-PLAYBACK-SUMMARY]"
      << " block_id=" << s.block_id;

  if (!s.asset_uris.empty()) {
    oss << " asset=" << s.asset_uris[0];
    if (s.asset_uris.size() > 1) {
      oss << "(+" << (s.asset_uris.size() - 1) << " more)";
    }
  } else {
    oss << " asset=none";
  }

  if (s.first_block_ct_ms >= 0 && s.last_block_ct_ms >= 0) {
    oss << " asset_range=" << s.first_block_ct_ms
        << "-" << s.last_block_ct_ms << "ms";
  } else {
    oss << " asset_range=none";
  }

  oss << " frames=" << s.frames_emitted
      << " pad_frames=" << s.pad_frames;

  if (s.first_session_frame_index >= 0 && s.last_session_frame_index >= 0) {
    oss << " session_frames=" << s.first_session_frame_index
        << "-" << s.last_session_frame_index;
  }

  return oss.str();
}

inline std::string FormatSeamTransition(const SeamTransitionLog& t) {
  std::ostringstream oss;
  oss << "[CONTINUOUS-SEAM]"
      << " from=" << t.from_block_id
      << " to=" << t.to_block_id
      << " fence_frame=" << t.fence_frame
      << " pad_frames_at_fence=" << t.pad_frames_at_fence
      << " status=" << (t.seamless ? "SEAMLESS" : "PADDED");
  return oss.str();
}

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PLAYBACK_TRACE_TYPES_HPP_
