# Overlay Compositor Stage

**Status: IDEA — not a contract, not an invariant, not approved for implementation.**

Captured from architectural discussion on 2026-03-24. This document preserves design knowledge for future implementation. It does not define required behavior.

---

## Problem

AIR has no mechanism to composite text or graphics onto video frames at runtime. Use cases that require text over video — "Coming Up Next" title cards, lower third promos, channel watermarks, debug overlays — cannot be implemented without pre-rendering assets offline.

## Proposed Capability

An overlay compositor stage inserted into AIR's frame pipeline between frame selection (PipelineManager tick loop) and encoding (EncoderPipeline).

## Pipeline Insertion Point

```
decoded frame (YUV420P, output resolution)
    ↓
PipelineManager tick loop → chosen_video (content, pad, or held frame)
    ↓
PTS/DTS metadata applied (lines 2647–2656 of PipelineManager.cpp)
    ↓
[NEW] OverlayCompositor::Apply(frame, overlay_config)
    ↓
session_encoder->encodeFrame(frame, video_pts_90k)  (line 2657)
    ↓
MPEG-TS output
```

The compositor operates on the final selected frame after all timing metadata is applied but before encoding. Frames are `AV_PIX_FMT_YUV420P` at the channel's output resolution (e.g., 1280×720). The compositor modifies the frame in-place.

## Use Cases

| Use Case | Trigger | Text Source | Position | Lifetime |
|---|---|---|---|---|
| Coming Up Next | Tier 3 segment with `segment_type="coming_up_next"` | Next block's program title (resolved at compile time by Core) | Lower third or center | Full segment duration |
| Lower third promo | Segment overlay metadata | Promo text from DSL config | Lower third | Configurable (fade in/out) |
| Channel bug / watermark | Session-level config from channel YAML | Channel name or logo path | Corner (e.g., top-right) | Entire session |
| Debug overlay | Runtime flag (e.g., `--debug-overlay`) | Block ID, segment index, PTS, frame count | Top of frame | Always-on when enabled |

## Proposed Implementation Approach

### FFmpeg drawtext filter

AIR already links `libavcodec`, `libavformat`, and `libswscale`. Adding `libavfilter` enables the `drawtext` filter which:

- Renders TrueType font text with anti-aliasing
- Operates natively in YUV colorspace (no RGB conversion)
- Supports positioning, opacity, timing, font size
- Filter graph is built once per segment, applied per frame

### Compositor lifecycle

1. **Segment start:** If segment has overlay config, build `avfilter_graph` (buffersrc → drawtext → buffersink). Cache for segment duration.
2. **Per tick:** Push `chosen_video` frame through filter graph. Replace frame data with composited output.
3. **Segment end:** Tear down filter graph.
4. **No overlay active:** No-op. Zero overhead on the hot path when unused.

### OverlayCompositor class (proposed)

```
File: pkg/air/src/overlay/OverlayCompositor.hpp
      pkg/air/src/overlay/OverlayCompositor.cpp

class OverlayCompositor {
  // Build/tear down filter graph for current overlay config
  bool Activate(const OverlayConfig& config, int width, int height);
  void Deactivate();

  // Apply overlay to frame in-place. No-op if not active.
  bool Apply(buffer::Frame& frame);

  bool IsActive() const;
};
```

## Proto Extension (proposed)

```protobuf
// In BlockSegment (playout.proto):
message OverlayConfig {
  string text = 1;              // Display text (e.g., "A Haunting in Venice")
  string position = 2;          // "lower_third", "center", "top_right"
  float opacity = 3;            // 0.0–1.0 (default 1.0)
  int32 font_size = 4;          // Pixels (default 36)
  int32 fade_in_ms = 5;         // Fade-in duration (0 = instant)
  int32 fade_out_ms = 6;        // Fade-out duration (0 = instant)
  string font_path = 7;         // Optional TrueType font file path
  string background_color = 8;  // Optional background behind text (e.g., "black@0.5")
}

// Added to BlockSegment:
OverlayConfig overlay = 17;     // Optional overlay applied during this segment
```

## Core Integration (proposed)

### Tier 3 "Coming Up Next" segment

Core's `compile_schedule()` already has a second pass that accesses `all_blocks[i+1]` for next-block identity (documented in `block_assembly_tiers.md` line 230). The proposed flow:

1. Second pass in `compile_schedule()`: for each block, look at `all_blocks[i+1]` to get the next program title.
2. Inject a Tier 3 segment into `compiled_segments`:
   - `segment_type: "coming_up_next"`
   - `asset_uri`: path to background video bumper (from pool, e.g., `coming_up_next_bumpers`)
   - `overlay.text`: next block's program title
   - `overlay.position`: "lower_third" or "center"
3. Grid sizing includes the Tier 3 segment duration (per `INV-TIER3-COMPILE-RESOLUTION-001`).
4. `to_proto()` serializes the overlay config into the `BlockSegment.overlay` field.
5. AIR receives it, builds the drawtext filter graph, composites text onto the background video.

### Cross-day boundary

Last block of a broadcast day cannot see `all_blocks[i+1]` because the next day hasn't been compiled yet. Options documented in `block_assembly_tiers.md` line 233:
- Omit "Coming Up Next" for the last block (simplest)
- Post-merge pass across days in `_build_initial()`
- Query next day's first ScheduleItem from DB

## Component Ownership

| Concern | Owner | Notes |
|---|---|---|
| What text to display | Core | Resolved at compile time from next-block program identity |
| When to display it | Core | Tier 3 segment timing determined by compiler |
| How to render it | AIR | Font, anti-aliasing, colorspace, filter graph management |
| Overlay config schema | Shared (proto) | Core writes, AIR reads, neither interprets the other's domain |

This respects the Core/AIR boundary: Core owns editorial intent ("show the next movie title"), AIR owns execution correctness ("render this text at this position with anti-aliasing in YUV420P").

## Existing Contract References

- `block_assembly_tiers.md` §Tier 3 — Optional Presentation
- `INV-TIER3-COMPILE-RESOLUTION-001` — Tier 3 resolved at compile time
- `INV-TIER3-NEXT-BLOCK-IDENTITY-001` — Next-block identity via second pass
- `INV-BLOCKPLAN-METADATA-IGNORED` — AIR must not alter execution based on metadata (overlay is rendering, not execution)

## Open Questions

1. **Font distribution:** Where do TrueType font files live? Bundled with AIR? Configurable per channel?
2. **Logo/image overlays:** Should the compositor support image overlays (PNG with alpha) in addition to text? Needed for channel bugs.
3. **Performance budget:** drawtext filter adds ~1ms per frame at 720p. Acceptable for 30fps (33ms frame budget)?
4. **Multiple simultaneous overlays:** Can a segment have both a "Coming Up Next" text and a channel bug? If so, the proto needs a repeated field or a list of overlay configs.
5. **Fade timing:** Fade-in/out relative to segment start/end requires the compositor to know elapsed time within the segment. The tick loop already tracks this via frame count.

## What This Document Is NOT

- This is NOT an invariant. It defines no required behavior.
- This is NOT a contract. No test coverage is implied.
- This is NOT approved for implementation. It captures design intent only.
- When implementation begins, extract invariants and create proper contract documents per `HOUSE-STYLE.md`.
