// Repository: Retrovue-playout
// Component: Playback Trace Types
// Purpose: Header-only types for P3.3 execution trace logging.
//          Per-block playback summaries, seam transition records,
//          and segment-aware playback proofs derived from actual
//          execution, not scheduled intent.
// Contract Reference: PlayoutAuthorityContract.md (P3.3)
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_PLAYBACK_TRACE_TYPES_HPP_
#define RETROVUE_BLOCKPLAN_PLAYBACK_TRACE_TYPES_HPP_

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "retrovue/blockplan/BlockPlanTypes.hpp"

namespace retrovue::blockplan {

struct FedBlock;  // Forward declaration

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
// PlaybackProofVerdict — verdict comparing intent to actual.
// Placed before SegmentProofRecord / BlockAccumulator so both can reference it.
// =============================================================================

enum class PlaybackProofVerdict {
  kFaithful,      // Correct asset(s), zero pad
  kPartialPad,    // Correct asset(s), some pad frames
  kAllPad,        // No real frames at all
  kAssetMismatch, // Observed asset doesn't match expected
};

inline const char* PlaybackProofVerdictToString(PlaybackProofVerdict v) {
  switch (v) {
    case PlaybackProofVerdict::kFaithful:      return "FAITHFUL";
    case PlaybackProofVerdict::kPartialPad:    return "PARTIAL_PAD";
    case PlaybackProofVerdict::kAllPad:        return "ALL_PAD";
    case PlaybackProofVerdict::kAssetMismatch: return "ASSET_MISMATCH";
  }
  return "UNKNOWN";
}

// =============================================================================
// SegmentProofRecord — per-segment proof: expected vs actual execution
// =============================================================================

struct SegmentProofRecord {
  // Expected (from BlockPlan segments at block load time)
  int32_t segment_index = -1;
  std::string expected_asset_uri;
  int64_t expected_frame_count = 0;
  SegmentType expected_type = SegmentType::kContent;
  std::string event_id;

  // Actual (accumulated during emission)
  std::string actual_asset_uri;      // first observed URI (empty if all pad)
  int64_t actual_frame_count = 0;
  int64_t actual_pad_frames = 0;
  int64_t actual_start_frame = -1;   // session frame index
  int64_t actual_end_frame = -1;     // session frame index (inclusive)
  int64_t first_ct_ms = -1;
  int64_t last_ct_ms = -1;

  // Verdict (computed at finalization)
  PlaybackProofVerdict verdict = PlaybackProofVerdict::kFaithful;
};

// Determine per-segment verdict.
inline PlaybackProofVerdict DetermineSegmentVerdict(
    const SegmentProofRecord& rec) {
  // All pad — decoder never produced a frame for this segment
  if (rec.actual_frame_count > 0 &&
      rec.actual_pad_frames == rec.actual_frame_count) {
    return PlaybackProofVerdict::kAllPad;
  }

  // Asset mismatch — observed URI doesn't match expected
  if (!rec.actual_asset_uri.empty() && !rec.expected_asset_uri.empty() &&
      rec.actual_asset_uri != rec.expected_asset_uri) {
    return PlaybackProofVerdict::kAssetMismatch;
  }

  // Some pad frames but correct asset
  if (rec.actual_pad_frames > 0) {
    return PlaybackProofVerdict::kPartialPad;
  }

  return PlaybackProofVerdict::kFaithful;
}

// =============================================================================
// BlockAccumulator — per-block frame aggregation (engine-internal)
// Lives in the Run() loop.  Reset when a new block becomes active.
// Includes segment-level tracking for proof generation.
// =============================================================================

struct BlockAccumulator {
  // --- Block-level tracking ---
  std::string block_id;
  std::set<std::string> asset_uri_set;
  std::vector<std::string> asset_uri_order;  // insertion order, unique
  int64_t first_ct_ms = -1;
  int64_t last_ct_ms = -1;
  int64_t frames = 0;
  int64_t pad_frames = 0;
  int64_t first_session_frame = -1;
  int64_t last_session_frame = -1;

  // --- Segment-level tracking ---
  struct SegmentAccState {
    int32_t segment_index = -1;
    std::string expected_asset_uri;
    int64_t expected_frame_count = 0;
    SegmentType expected_type = SegmentType::kContent;
    std::string event_id;

    std::string actual_asset_uri;
    int64_t frame_count = 0;
    int64_t pad_frames = 0;
    int64_t start_frame = -1;
    int64_t end_frame = -1;
    int64_t first_ct_ms = -1;
    int64_t last_ct_ms = -1;
  };

  SegmentAccState current_segment_;
  std::vector<SegmentProofRecord> finalized_segments_;

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
    current_segment_ = {};
    finalized_segments_.clear();
  }

  // Begin tracking a new segment.  Auto-finalizes the previous segment.
  void BeginSegment(int32_t index, const std::string& expected_uri,
                    int64_t expected_frames, SegmentType type,
                    const std::string& event_id) {
    FinalizeCurrentSegment();
    current_segment_ = {};
    current_segment_.segment_index = index;
    current_segment_.expected_asset_uri = expected_uri;
    current_segment_.expected_frame_count = expected_frames;
    current_segment_.expected_type = type;
    current_segment_.event_id = event_id;
  }

  // Finalize the current segment and store its proof record.
  void FinalizeCurrentSegment() {
    if (current_segment_.segment_index < 0) return;
    SegmentProofRecord rec;
    rec.segment_index = current_segment_.segment_index;
    rec.expected_asset_uri = current_segment_.expected_asset_uri;
    rec.expected_frame_count = current_segment_.expected_frame_count;
    rec.expected_type = current_segment_.expected_type;
    rec.event_id = current_segment_.event_id;
    rec.actual_asset_uri = current_segment_.actual_asset_uri;
    rec.actual_frame_count = current_segment_.frame_count;
    rec.actual_pad_frames = current_segment_.pad_frames;
    rec.actual_start_frame = current_segment_.start_frame;
    rec.actual_end_frame = current_segment_.end_frame;
    rec.first_ct_ms = current_segment_.first_ct_ms;
    rec.last_ct_ms = current_segment_.last_ct_ms;
    rec.verdict = DetermineSegmentVerdict(rec);
    finalized_segments_.push_back(std::move(rec));
    current_segment_ = {};
  }

  void AccumulateFrame(int64_t session_idx, bool is_pad,
                       const std::string& uri, int64_t ct_ms) {
    // Block-level tracking
    frames++;
    if (first_session_frame < 0) first_session_frame = session_idx;
    last_session_frame = session_idx;

    if (is_pad) {
      pad_frames++;
    } else {
      if (!uri.empty() && asset_uri_set.insert(uri).second) {
        asset_uri_order.push_back(uri);
      }
      // Only update CT tracking when ct_ms is valid (>= 0).
      // Cadence repeat ticks and hold-last-frame ticks pass ct_ms = -1
      // because no frame_data is available; these must not clobber the
      // last known decoded position.
      if (ct_ms >= 0) {
        if (first_ct_ms < 0) first_ct_ms = ct_ms;
        last_ct_ms = ct_ms;
      }
    }

    // Segment-level tracking (O(1) per frame)
    if (current_segment_.segment_index >= 0) {
      current_segment_.frame_count++;
      if (current_segment_.start_frame < 0)
        current_segment_.start_frame = session_idx;
      current_segment_.end_frame = session_idx;
      if (is_pad) {
        current_segment_.pad_frames++;
      } else {
        if (!uri.empty() && current_segment_.actual_asset_uri.empty()) {
          current_segment_.actual_asset_uri = uri;
        }
        if (ct_ms >= 0) {
          if (current_segment_.first_ct_ms < 0)
            current_segment_.first_ct_ms = ct_ms;
          current_segment_.last_ct_ms = ct_ms;
        }
      }
    }
  }

  // Finalize block: finalize last segment, return block-level summary.
  BlockPlaybackSummary Finalize() {
    FinalizeCurrentSegment();

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

  // Access finalized segment proofs (valid after Finalize()).
  const std::vector<SegmentProofRecord>& GetSegmentProofs() const {
    return finalized_segments_;
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

// =============================================================================
// P3.3b: Playback Proof — wanted vs showed comparison (segment-aware)
// =============================================================================

// What Core told AIR to play (extracted from FedBlock at fence time).
struct BlockPlaybackIntent {
  std::string block_id;
  std::vector<std::string> expected_asset_uris;  // from segments
  int64_t expected_duration_ms = 0;               // end_utc_ms - start_utc_ms
  int64_t expected_frames = 0;                    // ceil(duration / frame_dur)
  int64_t expected_start_offset_ms = 0;           // first segment offset
};

// Full proof record: intent + actual + segment proofs + verdict.
struct BlockPlaybackProof {
  BlockPlaybackIntent wanted;
  BlockPlaybackSummary showed;
  std::vector<SegmentProofRecord> segment_proofs;
  PlaybackProofVerdict verdict = PlaybackProofVerdict::kFaithful;

  // Block-level integrity checks (valid when segment_proofs non-empty)
  bool frame_budget_match = true;
  bool no_gaps = true;
  bool no_overlaps = true;
};

// Build intent from a FedBlock.  frame_duration_ms comes from the engine's
// OutputClock (e.g., 33 for 30fps).
inline BlockPlaybackIntent BuildIntent(const FedBlock& block,
                                        int64_t frame_duration_ms) {
  BlockPlaybackIntent intent;
  intent.block_id = block.block_id;
  intent.expected_duration_ms = block.end_utc_ms - block.start_utc_ms;
  const RationalFps block_fps(frame_duration_ms > 0 ? 1000 : 0,
                              frame_duration_ms > 0 ? frame_duration_ms : 1);
  intent.expected_frames = block_fps.FramesFromDurationCeilMs(
      intent.expected_duration_ms);
  for (const auto& seg : block.segments) {
    intent.expected_asset_uris.push_back(seg.asset_uri);
  }
  if (!block.segments.empty()) {
    intent.expected_start_offset_ms = block.segments[0].asset_start_offset_ms;
  }
  return intent;
}

// Determine verdict by comparing intent to actual summary (block-level).
// Retained for backward compatibility and as fallback when no segment proofs.
inline PlaybackProofVerdict DetermineVerdict(
    const BlockPlaybackIntent& wanted,
    const BlockPlaybackSummary& showed) {
  // All pad — decoder never produced a frame
  if (showed.pad_frames == showed.frames_emitted) {
    return PlaybackProofVerdict::kAllPad;
  }

  // Check asset mismatch: every observed URI must appear in expected set
  bool asset_match = true;
  for (const auto& observed : showed.asset_uris) {
    bool found = false;
    for (const auto& expected : wanted.expected_asset_uris) {
      if (observed == expected) { found = true; break; }
    }
    if (!found) { asset_match = false; break; }
  }
  if (!asset_match) {
    return PlaybackProofVerdict::kAssetMismatch;
  }

  // Some pad frames but correct asset
  if (showed.pad_frames > 0) {
    return PlaybackProofVerdict::kPartialPad;
  }

  return PlaybackProofVerdict::kFaithful;
}

// Block-level verdict derived from segment proofs.
// Worst verdict across all segments wins.
inline PlaybackProofVerdict DetermineBlockVerdictFromSegments(
    const std::vector<SegmentProofRecord>& segment_proofs,
    const BlockPlaybackSummary& showed) {
  if (segment_proofs.empty()) {
    // No segment data — degenerate case
    if (showed.pad_frames == showed.frames_emitted)
      return PlaybackProofVerdict::kAllPad;
    return showed.pad_frames > 0
        ? PlaybackProofVerdict::kPartialPad
        : PlaybackProofVerdict::kFaithful;
  }

  PlaybackProofVerdict worst = PlaybackProofVerdict::kFaithful;
  for (const auto& sp : segment_proofs) {
    if (sp.verdict == PlaybackProofVerdict::kAssetMismatch) {
      return PlaybackProofVerdict::kAssetMismatch;
    }
    if (sp.verdict == PlaybackProofVerdict::kAllPad &&
        worst != PlaybackProofVerdict::kAssetMismatch) {
      worst = PlaybackProofVerdict::kAllPad;
    } else if (sp.verdict == PlaybackProofVerdict::kPartialPad &&
               worst == PlaybackProofVerdict::kFaithful) {
      worst = PlaybackProofVerdict::kPartialPad;
    }
  }
  return worst;
}

// Build a complete proof record (segment-aware).
inline BlockPlaybackProof BuildPlaybackProof(
    const FedBlock& block,
    const BlockPlaybackSummary& summary,
    int64_t frame_duration_ms,
    const std::vector<SegmentProofRecord>& segment_proofs = {}) {
  BlockPlaybackProof proof;
  proof.wanted = BuildIntent(block, frame_duration_ms);
  proof.showed = summary;
  proof.segment_proofs = segment_proofs;

  if (!segment_proofs.empty()) {
    proof.verdict = DetermineBlockVerdictFromSegments(segment_proofs, summary);

    // Integrity: sum of segment frames == block frames
    int64_t total_segment_frames = 0;
    for (const auto& sp : segment_proofs) {
      total_segment_frames += sp.actual_frame_count;
    }
    proof.frame_budget_match = (total_segment_frames == summary.frames_emitted);

    // Gap/overlap detection: contiguous session frame ranges
    for (size_t i = 1; i < segment_proofs.size(); ++i) {
      const auto& prev = segment_proofs[i - 1];
      const auto& curr = segment_proofs[i];
      if (prev.actual_end_frame >= 0 && curr.actual_start_frame >= 0) {
        if (curr.actual_start_frame > prev.actual_end_frame + 1) {
          proof.no_gaps = false;
        }
        if (curr.actual_start_frame <= prev.actual_end_frame) {
          proof.no_overlaps = false;
        }
      }
    }
  } else {
    proof.verdict = DetermineVerdict(proof.wanted, proof.showed);
  }

  return proof;
}

// Format segment proof as a human-readable log line.
inline std::string FormatSegmentProof(const SegmentProofRecord& rec) {
  std::ostringstream oss;
  oss << "[SEGMENT_PROOF]"
      << " segment_index=" << rec.segment_index
      << " type=" << SegmentTypeName(rec.expected_type)
      << " event_id=" << (rec.event_id.empty() ? "none" : rec.event_id)
      << " expected_asset="
      << (rec.expected_asset_uri.empty() ? "none" : rec.expected_asset_uri)
      << " actual_asset="
      << (rec.actual_asset_uri.empty() ? "none" : rec.actual_asset_uri)
      << " expected_frames=" << rec.expected_frame_count
      << " actual_frames=" << rec.actual_frame_count
      << " pad=" << rec.actual_pad_frames
      << " verdict=" << PlaybackProofVerdictToString(rec.verdict);
  return oss.str();
}

// Format the proof as a human-readable comparison log.
inline std::string FormatPlaybackProof(const BlockPlaybackProof& p) {
  std::ostringstream oss;

  // Segment proofs first
  for (const auto& sp : p.segment_proofs) {
    oss << FormatSegmentProof(sp) << "\n";
  }

  // Block proof
  oss << "[BLOCK_PROOF] block_id=" << p.wanted.block_id << "\n";

  // WANTED line
  oss << "  WANTED:";
  if (!p.wanted.expected_asset_uris.empty()) {
    oss << " asset=" << p.wanted.expected_asset_uris[0];
    if (p.wanted.expected_asset_uris.size() > 1) {
      oss << "(+" << (p.wanted.expected_asset_uris.size() - 1) << " more)";
    }
  } else {
    oss << " asset=none";
  }
  oss << " offset=" << p.wanted.expected_start_offset_ms << "ms"
      << " duration=" << p.wanted.expected_duration_ms << "ms"
      << " frames=" << p.wanted.expected_frames
      << " segments=" << p.segment_proofs.size()
      << "\n";

  // SHOWED line
  oss << "  SHOWED:";
  if (!p.showed.asset_uris.empty()) {
    oss << " asset=" << p.showed.asset_uris[0];
    if (p.showed.asset_uris.size() > 1) {
      oss << "(+" << (p.showed.asset_uris.size() - 1) << " more)";
    }
  } else {
    oss << " asset=none";
  }
  if (p.showed.first_block_ct_ms >= 0 && p.showed.last_block_ct_ms >= 0) {
    oss << " range=" << p.showed.first_block_ct_ms
        << "-" << p.showed.last_block_ct_ms << "ms";
  } else {
    oss << " range=none";
  }
  oss << " frames=" << p.showed.frames_emitted
      << " pad=" << p.showed.pad_frames
      << "\n";

  // VERDICT line
  oss << "  VERDICT: " << PlaybackProofVerdictToString(p.verdict);
  if (!p.segment_proofs.empty()) {
    if (!p.frame_budget_match) oss << " FRAME_BUDGET_MISMATCH";
    if (!p.no_gaps) oss << " GAPS_DETECTED";
    if (!p.no_overlaps) oss << " OVERLAPS_DETECTED";
  }

  return oss.str();
}

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PLAYBACK_TRACE_TYPES_HPP_
