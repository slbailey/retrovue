# Coming Up Next (CUN) — Operator Guide

This guide explains how to enable and configure CUN segments for your channels.

---

## What CUN Does

CUN automatically generates short video segments (default 10 seconds) that announce the next scheduled program. These appear at the end of a program block, after content but before filler — matching how real broadcast stations tease upcoming shows.

CUN segments are rendered in advance during idle CPU time and inserted into the playlog when ready. If a render is not ready at airtime, the segment is silently skipped — playout is never interrupted.

---

## Enabling CUN

Add the feature flag to your channel YAML:

```yaml
features:
  coming_up_next: true
```

When `false` or absent, CUN is completely disabled — no schedule segments placed, no render jobs created, zero overhead.

---

## Configuring Templates

CUN templates define the visual style of each segment. Configure them under `continuity.coming_up_next`:

```yaml
continuity:
  coming_up_next:
    duration_ms: 10000
    render_deadline_margin_ms: 30000
    templates:
      - id: default
        background: assets/templates/cun/retro_loop_01.mp4
        text_area:
          x: 120
          y: 680
          width: 1680
          height: 200
        font: assets/fonts/retro_display.ttf
        font_size: 64
        font_color: "white"
        fade_in_ms: 500
        fade_out_ms: 500
```

### Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `duration_ms` | Yes | Duration of the CUN segment in milliseconds |
| `render_deadline_margin_ms` | Yes | Safety margin before airtime — renders must complete this far in advance |
| `templates` | Yes | List of template definitions (at least one) |
| `templates[].id` | Yes | Unique identifier for the template |
| `templates[].background` | Yes | Path to looping background video (relative to media root) |
| `templates[].text_area` | Yes | Rectangle defining where title text is rendered |
| `templates[].font` | Yes | Path to font file |
| `templates[].font_size` | Yes | Font size in pixels |
| `templates[].font_color` | Yes | Text color (CSS color name or hex) |
| `templates[].fade_in_ms` | No | Fade-in duration (default: 0) |
| `templates[].fade_out_ms` | No | Fade-out duration (default: 0) |

---

## Preparing Background Assets

Background videos must be:

1. **Looping** — the video loops seamlessly for the configured `duration_ms`
2. **Pre-rendered** — typically After Effects compositions exported as .mp4
3. **Matching output format** — same resolution and frame rate as your channel output
4. **Text area reserved** — leave a defined region clear for title text overlay

Place background assets in `assets/templates/cun/` (or any path accessible to the render worker).

---

## How CUN Flows Through the System

1. **Schedule compilation** — `optional_presentation.py` places a CUN segment in each block where a next block exists, carrying the next program's title as metadata
2. **Render enqueue** — `PlaylistBuilderDaemon` detects unresolved CUN segments and enqueues render requests, ordered by airtime (soonest first)
3. **Render execution** — `CunSynthesisWorker` claims pending requests during idle time, composites the background video with title text via ffmpeg
4. **Playout resolution** — when building the playlog, resolved CUN segments use the rendered file; unresolved ones are skipped
5. **AIR playout** — plays the resolved CUN asset like any other segment (no AIR changes)

---

## Operational Behavior

### Deduplication

If the same program title appears with the same template across multiple time slots, the system reuses the existing render. Cache is content-addressed by `hash(template_id, title)`.

### Deadline Enforcement

Renders that cannot complete before `segment_start_utc - render_deadline_margin_ms` are marked SKIPPED. Increase `render_deadline_margin_ms` if you see frequent skips.

### Cache Cleanup

Rendered files are retained until all segments referencing them have aired. Cleanup runs automatically on the worker's next cycle after broadcast.

### Last Block

The final block in a broadcast day has no "next" program to announce. CUN is silently omitted for the last block.

---

## Troubleshooting

| Symptom | Likely Cause | Action |
|---------|-------------|--------|
| No CUN segments in schedule | `features.coming_up_next` is false or absent | Check channel YAML |
| CUN segments always skipped | Renders not completing in time | Increase `render_deadline_margin_ms` or check worker health |
| Missing background video | Path not accessible to render worker | Verify `background` path exists |
| Wrong font rendering | Font file not found or wrong format | Verify `font` path and format (.ttf/.otf) |
