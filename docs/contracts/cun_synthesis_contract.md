# CUN Synthesis — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`, `LAW-GRID`

---

## Purpose

CUN (Coming Up Next) synthesis produces short rendered video segments that announce the next scheduled program. CUN is **schedule-scoped content synthesis** — it takes a schedule segment (channel + time + next program identity) and produces a new rendered video. It is not an ingest enricher and does not use the ProcessorJob queue.

This contract defines the pipeline shape, authority boundaries, and behavioral guarantees for CUN synthesis from feature gating through render execution to playout resolution.

---

## Pipeline Shape

```
Schedule Compiler (DO phase)
  optional_presentation.py checks features.coming_up_next
  If enabled: places CUN segment with next_program_title metadata
  CUN segment initially has no rendered media — just editorial intent
         |
         v
CUN Render Request Enqueue
  PlaylistBuilderDaemon detects unresolved CUN segments during horizon scan
  Before enqueueing: checks for existing COMPLETED request with same content_hash
    → If found: reuses immediately (dedup-before-render)
    → If not found: enqueues new request with playout-time-based priority
         |
         v  (THINK phase — idle CPU time)
CUN Synthesis Worker
  Claims pending requests (soonest playout time first)
  Checks render deadline: if segment_start_utc - safety_margin < now → mark SKIPPED
  Resolves template from channel config → template pool
  ffmpeg composite: looping background + title text → .mp4
  Content-addressed cache: hash(template_id, title) deduplicates
  Marks request completed with rendered file path
         |
         v
PlaylistBuilderDaemon — ensure_cun_ready(segment)
  When expanding CUN segments for playlog:
  If rendered → use rendered file
  If not rendered → SKIP the segment entirely
         |
         v
AIR Playout (existing, unchanged)
  Plays resolved assets like any other segment
```

---

## Authority Domains

| Domain | Owner | Scope |
|--------|-------|-------|
| Schedule compilation | `optional_presentation.py` | What CUN segments exist in the compiled schedule |
| Render execution | `CunSynthesisWorker` | Producing the rendered video from template + title |
| Playout resolution | `PlaylistBuilderDaemon` via `ensure_cun_ready()` | Detect → enqueue → resolve/skip |
| Feature gating | Channel config `features.coming_up_next` | Whether CUN is enabled at all |
| AIR | None | Zero involvement — plays resolved assets like anything else |

---

## Channel Config Extension

```yaml
features:
  coming_up_next: true  # feature flag — false = no CUN at all

continuity:
  coming_up_next:
    duration_ms: 10000
    render_deadline_margin_ms: 30000  # must finish 30s before airtime
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

---

## Data Model

### cun_render_requests table

```sql
CREATE TABLE cun_render_requests (
  id UUID PRIMARY KEY,
  channel_id UUID NOT NULL REFERENCES channels(id),
  segment_start_utc TIMESTAMPTZ NOT NULL,
  next_program_title TEXT NOT NULL,
  template_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed|skipped
  rendered_asset_path TEXT,
  content_hash TEXT,  -- hash(template_id, title) for cache dedup
  priority INT NOT NULL DEFAULT 100,  -- lower = higher priority (playout-time ordered)
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  UNIQUE(channel_id, segment_start_utc)  -- one render per CUN slot
);

CREATE INDEX idx_cun_render_pending ON cun_render_requests(status, priority, created_at)
  WHERE status = 'pending';
CREATE INDEX idx_cun_render_content_hash ON cun_render_requests(content_hash, status)
  WHERE status = 'completed';
```

---

## Delegation Boundary: PlaylistBuilderDaemon

PlaylistBuilder's CUN role is scoped to **detect → enqueue → resolve/skip**. It MUST NOT perform rendering, make template decisions, or evolve into a broader orchestration layer. This is a delegation boundary, not ownership.

---

## Cache Lifecycle

- Rendered CUN files are content-addressed: `cun_cache/<content_hash>.mp4`
- After a CUN segment has aired, the next worker cycle marks it eligible for cleanup
- A cached file MUST NOT be deleted until ALL `cun_render_requests` referencing that `content_hash` have `segment_start_utc` in the past

---

## Invariants

| ID | Statement |
|----|-----------|
| `INV-CUN-FEATURE-FLAG-001` | CUN synthesis MUST be gated by channel-level `features.coming_up_next`. When false, no CUN segments placed, no render jobs created. |
| `INV-CUN-SCHEDULE-SCOPED-001` | CUN synthesis is schedule-scoped content synthesis. It MUST NOT be implemented as an ingest enricher or use the ProcessorJob queue. |
| `INV-CUN-RENDER-IDLE-001` | CUN segments MUST be rendered during idle processor time, never during schedule compilation. |
| `INV-CUN-RENDER-DEADLINE-001` | CUN renders MUST complete before `segment_start_utc` minus a configurable safety margin. Late renders MUST NOT be used for playout. |
| `INV-CUN-SKIP-IF-UNREADY-001` | If a CUN render is incomplete at playout time, the system MUST skip the segment — never block, never fall back to a generic bumper. |
| `INV-CUN-PRIORITY-PLAYOUT-001` | CUN render priority MUST be ordered by playout time — soonest-airing segments render first. |
| `INV-CUN-CACHE-UNTIL-USED-001` | Rendered CUN assets MUST be retained until after broadcast, then purged on the next cleanup cycle. |
| `INV-CUN-CACHE-SAFE-CLEANUP-001` | A cached CUN file MUST NOT be deleted until ALL render requests referencing its content_hash have `segment_start_utc` in the past. |
| `INV-CUN-DEDUP-BEFORE-RENDER-001` | Before enqueueing or starting a CUN render, the system MUST check for an existing completed render with the same content_hash and reuse it. |
| `INV-CUN-CACHE-DEDUP-001` | Rendered CUN assets MUST be content-addressed by hash(template_id, title) for deduplication. |
| `INV-CUN-TEMPLATE-DETERMINISTIC-001` | Template selection from pool MUST be deterministic (SHA256-seeded) for schedule reproducibility. |

---

## What Changes vs. What's Reused

| New | Reused |
|-----|--------|
| `cun_render_requests` table | Claim-with-SKIP-LOCKED pattern from processor_worker |
| `CunSynthesisWorker` (~150 lines) | PlaylistBuilderDaemon scan loop (detect unresolved CUN) |
| Channel config `features` block | Template pool selection (SHA256 deterministic seeding) |
| | ffmpeg drawtext / overlay compositing |
| | Existing optional_presentation.py Tier 3 placement |

~350 lines new code + 1 migration. Zero AIR changes. Zero existing enricher protocol changes.
