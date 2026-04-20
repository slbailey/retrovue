// AIR vNext — PlaybackDirector.
//
// Per the vault, PlaybackDirector is the sole runtime authority for active
// playout state: current live segment truth, active producer assignment,
// next queued segment truth, pending successor-plan truth, and coordination
// of controller outputs. This file contains a MINIMAL slice-3 / slice-5
// implementation that covers only the active-assignment ownership —
// specifically "which per-source Normalizer + preview-buffer pair is the
// live segment right now." Full orchestration surface (producer
// `prepare` / `activate` / `retire` intents, seam/readiness/runway
// coordination, successor-plan state, etc.) is deferred to future slices.
//
// Why a first-party owner: the vault requires every authority domain to
// have a sole owner. Active-assignment truth must live in a named
// first-party component; it cannot live in a standalone "pointer" that
// owns its own truth independently of the vault authority model.
//
// Vault references:
//   - PlaybackDirector (component spec; this file implements a subset)
//   - Truth - Authority Domains Have Sole Owners
//   - BufferStore (preview/live role distinction)
//   - Truth - Source Time Is Producer-Local, Channel Time Is Canonical

#ifndef AIR_PLAYBACK_DIRECTOR_HPP_
#define AIR_PLAYBACK_DIRECTOR_HPP_

#include <cstdint>

#include "frame_types.hpp"
#include "normalizer.hpp"
#include "preview_buffer.hpp"

namespace retrovue::air {

// LiveSegment bundles the references that identify one segment's live
// assignment: the per-source Normalizer (owner of the channel origin) plus
// the preview-buffer pair that Normalizer writes into. This is the value
// type PlaybackDirector publishes as its active-assignment truth.
struct LiveSegment {
  VideoPreviewBuffer* video_preview = nullptr;
  AudioPreviewBuffer* audio_preview = nullptr;
  INormalizer* normalizer = nullptr;
  // Opaque identifier for observability (e.g., "pad", "content:cheers-ep001").
  const char* segment_id = "";

  bool IsValid() const {
    return video_preview != nullptr && audio_preview != nullptr &&
           normalizer != nullptr;
  }

  // Channel-time PTS anchor for this segment, read from the segment's
  // Normalizer. Re-anchor on the Normalizer is immediately visible here.
  int64_t ChannelPtsAnchorUs() const {
    return normalizer->Origin().channel_pts_anchor_us;
  }

  // Compute absolute channel PTS for a frame / block popped from this
  // segment's preview. Pure helper: anchor + relative.
  int64_t AbsoluteVideoPtsUs(const VideoFrame& f) const {
    return ChannelPtsAnchorUs() + f.pts_us_relative;
  }
  int64_t AbsoluteAudioPtsUs(const AudioBlock& b) const {
    return ChannelPtsAnchorUs() + b.pts_us_relative;
  }
};

class PlaybackDirector {
 public:
  PlaybackDirector() = default;

  // Owned truth: is there an active assignment, and what is it.
  bool HasActiveAssignment() const { return current_.IsValid(); }
  const LiveSegment& ActiveAssignment() const { return current_; }
  const LiveSegment& PreviousAssignment() const { return previous_; }

  // Observability: how many promotions have happened this session.
  int64_t promotion_count() const { return promotion_count_; }

  // PromoteToAssignment: atomic swap of the active-assignment pointer.
  //
  // Slice-scope note: in the target state, promotion is triggered by a
  // directive from BootstrapContentGate (at kickoff) or SeamController
  // (at a seam firing). Those directive paths are not yet implemented;
  // tests call this method directly to exercise promotion behaviour.
  // Full directive-path wiring is future work.
  void PromoteToAssignment(LiveSegment next) {
    previous_ = current_;
    current_ = next;
    ++promotion_count_;
  }

 private:
  LiveSegment current_{};
  LiveSegment previous_{};
  int64_t promotion_count_ = 0;
};

}  // namespace retrovue::air

#endif  // AIR_PLAYBACK_DIRECTOR_HPP_
