# Overlay Compositor Stage

**Status: IDEA — not a contract, not an invariant, not approved for implementation.**

Captured from architectural discussion on 2026-03-24. Revised same day after design review that identified critical structural gaps in V1 sketch. This document preserves design knowledge for future implementation. It does not define required behavior.

---

## Problem

AIR has no mechanism to composite text or graphics onto video frames at runtime. Use cases that require visual enrichment — "Coming Up Next" title cards, lower third promos, channel watermarks, debug overlays, emergency crawls — cannot be implemented without pre-rendering assets offline.

## Core Insight

This is not a single overlay function. It is a **layered compositing engine with independently-controlled enrichers**. The V1 design ("apply one overlay config per segment") conflates three distinct overlay sources, ignores z-ordering, and ties overlay lifecycle to segment lifecycle — which is correct for some use cases and wrong for others.

The correct abstraction: **playout enrichers are behaviors applied to frames over time**, not one-shot transformations.

---

## Pipeline Insertion Point (confirmed, does not change)

```
decoded frame (YUV420P, output resolution)
    ↓
PipelineManager tick loop → chosen_video (content, pad, or held frame)
    ↓
PTS/DTS metadata applied (PipelineManager.cpp lines 2647–2656)
    ↓
[NEW] OverlayCompositor::Apply(frame, context)
    ↓
session_encoder->encodeFrame(frame, video_pts_90k)  (line 2657)
    ↓
MPEG-TS output
```

## Architecture: Layered Compositor

### The compositor is an orchestrator, not a renderer

```
OverlayCompositor::Apply(frame, context)
    for layer in active_layers (ordered by z_index):
        frame = layer.Process(frame, context)
```

### Three overlay sources (different lifecycles)

| Source | Lifecycle | Examples | Controlled by |
|---|---|---|---|
| **Segment overlays** | Active for one segment's duration | "Coming Up Next: A Haunting in Venice", promo lower third | Core (via BlockSegment proto) |
| **Channel overlays** | Active for entire session | Channel bug/watermark, network logo | Channel YAML config (via session init) |
| **Runtime overlays** | Toggled on/off dynamically | Debug overlay, emergency crawl | Runtime flag or gRPC command |

These are **not the same system wearing different configs**. They have different activation triggers, different lifetimes, and different control planes. The compositor must support all three independently.

### Layering (z-index)

Non-negotiable. Multiple overlays can be active simultaneously:

```
z=0  base video frame (from decoder)
z=1  channel bug (session-wide, always on)
z=2  lower third promo (segment-driven, timed)
z=3  "Coming Up Next" card (segment-driven, Tier 3)
z=4  debug overlay (runtime toggle)
z=5  emergency crawl (runtime, highest priority)
```

Without explicit z-ordering: overlapping issues, inconsistent visuals, ordering bugs.

### OverlayLayer interface

Each layer is an independent behavior:

```cpp
class IOverlayLayer {
public:
    virtual ~IOverlayLayer() = default;

    // Called per-frame. Returns true if the layer modified the frame.
    virtual bool Process(buffer::Frame& frame, const OverlayContext& ctx) = 0;

    // Lifecycle
    virtual void Activate(const OverlayLayerConfig& config) = 0;
    virtual void Deactivate() = 0;
    virtual bool IsActive() const = 0;

    // Identity
    virtual int ZIndex() const = 0;
    virtual OverlayType Type() const = 0;
};
```

Each layer:
- Knows when it is active (its own lifecycle, not just segment boundaries)
- Knows how to render (owns its filter graph or rendering state)
- Is independently controlled (can be activated/deactivated without affecting other layers)

### OverlayContext (per-frame state)

```cpp
struct OverlayContext {
    int64_t pts_90k;                    // Current presentation timestamp
    int64_t segment_elapsed_ms;         // Time since segment start (for fade timing)
    int64_t session_elapsed_ms;         // Time since session start
    int32_t segment_index;              // Current segment within block
    std::string block_id;               // Current block
    std::string segment_type;           // "content", "coming_up_next", etc.
    int width;                          // Output frame width
    int height;                         // Output frame height
};
```

This gives each layer enough context to make its own activation/rendering decisions without coupling to the compositor's internals.

### OverlayCompositor class

```cpp
class OverlayCompositor {
public:
    // Register a layer (compositor takes ownership, sorts by z-index)
    void AddLayer(std::unique_ptr<IOverlayLayer> layer);

    // Per-frame: iterate active layers in z-order
    void Apply(buffer::Frame& frame, const OverlayContext& ctx);

    // Segment lifecycle hooks (activate/deactivate segment-driven layers)
    void OnSegmentStart(const SegmentOverlayConfig& config);
    void OnSegmentEnd();

    // Session lifecycle hooks (activate/deactivate channel-driven layers)
    void OnSessionStart(const ChannelOverlayConfig& config);
    void OnSessionEnd();

    // Runtime control (activate/deactivate runtime-driven layers)
    void SetRuntimeOverlay(OverlayType type, bool active);
};
```

### Apply loop (the hot path)

```cpp
void OverlayCompositor::Apply(Frame& frame, const OverlayContext& ctx) {
    for (auto& layer : layers_) {  // pre-sorted by z_index
        if (layer->IsActive()) {
            layer->Process(frame, ctx);
        }
    }
}
```

When no layers are active: the loop body never executes. Zero overhead.

---

## Concrete Layer Implementations (proposed)

### TextOverlayLayer (drawtext)

Renders text onto frames using FFmpeg's drawtext avfilter.

- **Filter graph lifecycle**: Built once on `Activate()`, reused for all frames until `Deactivate()`. NOT rebuilt per segment — layers manage their own filter graph independently.
- **Supports**: Font, size, position, opacity, fade-in/out, background box
- **Used by**: "Coming Up Next", lower third promos, emergency crawl

### ImageOverlayLayer (channel bug)

Composites a PNG with alpha channel onto a fixed corner position.

- **Filter graph**: `overlay` avfilter with a static image source
- **Lifecycle**: Active for entire session
- **Used by**: Channel watermark/bug

### DebugOverlayLayer

Renders diagnostic text (block_id, segment_index, PTS, frame count).

- **No filter graph**: Direct pixel write (monospace bitmap font baked into binary)
- **Lifecycle**: Runtime toggle via flag or gRPC
- **Zero external dependencies**: No font files, no libavfilter

---

## Proto Extension (revised from V1)

### V1 (wrong — single overlay, tied to segment)

```protobuf
OverlayConfig overlay = 17;  // ONE overlay per segment
```

### Revised (correct — list of overlays with types)

```protobuf
message OverlayDirective {
    OverlayType type = 1;
    int32 z_index = 2;                // Layer ordering (higher = on top)
    string text = 3;                  // Display text
    string position = 4;             // "lower_third", "center", "top_right"
    float opacity = 5;               // 0.0–1.0
    int32 font_size = 6;             // Pixels
    int32 fade_in_ms = 7;
    int32 fade_out_ms = 8;
    string font_path = 9;           // Optional TrueType font
    string background_color = 10;   // e.g., "black@0.5"
    string image_uri = 11;          // For image/logo overlays
}

enum OverlayType {
    OVERLAY_NONE = 0;
    OVERLAY_COMING_UP_NEXT = 1;
    OVERLAY_LOWER_THIRD = 2;
    OVERLAY_BUG = 3;
    OVERLAY_DEBUG = 4;
    OVERLAY_EMERGENCY = 5;
}

// In BlockSegment:
repeated OverlayDirective overlays = 17;  // Zero or more overlays per segment
```

`repeated` instead of singular. Multiple overlays per segment from day one.

---

## Rendering Strategy Decision

### Path A: FFmpeg avfilter system

- Drawtext + overlay filters via `avfilter_graph`
- Fastest to ship
- Limited layout control, complex multi-overlay graphs

### Path B: Native compositor with direct pixel rendering

- Own layer system, own rendering (FreeType for text, stb_image for PNGs)
- More work upfront
- Total control over layout, performance, debugging

### Recommendation

**Start with Path A for text layers (drawtext).** The filter graph per-layer (not per-segment) approach avoids the churn problem. Each layer owns its filter graph for its entire active lifetime.

**Use Path B for the debug overlay.** A bitmap font baked into the binary with direct YUV pixel writes has zero dependencies and zero allocation — ideal for a diagnostic layer that might be active on every frame.

**Channel bug (image overlay) can use either path.** The `overlay` avfilter with a static PNG source is simple enough for Path A.

---

## Core Integration (unchanged from V1)

### Tier 3 "Coming Up Next" segment

Core's `compile_schedule()` second pass accesses `all_blocks[i+1]` for next-block identity. Injects a Tier 3 segment with:
- `segment_type: "coming_up_next"`
- `asset_uri`: background video bumper from pool
- `overlays[0].type: OVERLAY_COMING_UP_NEXT`
- `overlays[0].text: "A Haunting in Venice"`
- `overlays[0].position: "lower_third"`

### Channel bug from YAML

Channel YAML gains an optional `bug:` section:
```yaml
bug:
  image: /opt/retrovue/assets/bugs/hbo_corner.png
  position: top_right
  opacity: 0.8
```

Core passes this as session-level config when starting AIR. The compositor activates the bug layer on session start.

### Cross-day boundary

Last block of broadcast day: omit "Coming Up Next" (simplest). Post-merge pass is a future optimization.

---

## Component Ownership

| Concern | Owner |
|---|---|
| What text/image to display | Core |
| When segment overlays are active | Core (segment boundaries) |
| When channel overlays are active | AIR (session lifetime) |
| When runtime overlays are active | AIR (runtime control) |
| How to render any overlay | AIR (compositing engine) |
| Z-ordering | AIR (layer management) |
| Performance budget | AIR (frame timing authority) |

---

## Open Questions

1. **Font distribution**: Bundle a default TTF with AIR? Configurable per channel?
2. **Performance budget**: drawtext at 720p30 adds ~1ms/frame. With 3 active layers?
3. **Image format**: PNG with alpha for bugs? SVG? Pre-scaled to output resolution?
4. **Filter graph sharing**: Can two text layers share a single avfilter graph, or must each own its own?
5. **Emergency overlay protocol**: gRPC call to AIR? Or a signal from Core via block metadata?
6. **Crawl/scroll text**: Emergency crawl needs horizontal scrolling text. Drawtext supports this via `x` expression with `t` (time), but testing is needed.

## Existing Contract References

- `block_assembly_tiers.md` §Tier 3 — Optional Presentation
- `INV-TIER3-COMPILE-RESOLUTION-001` — Tier 3 resolved at compile time
- `INV-TIER3-NEXT-BLOCK-IDENTITY-001` — Next-block identity via second pass
- `INV-BLOCKPLAN-METADATA-IGNORED` — AIR must not alter execution based on metadata (overlay is rendering, not execution logic)

## What This Document Is NOT

- This is NOT an invariant. It defines no required behavior.
- This is NOT a contract. No test coverage is implied.
- This is NOT approved for implementation. It captures design intent only.
- When implementation begins, extract invariants and create proper contract documents per `HOUSE-STYLE.md`.
