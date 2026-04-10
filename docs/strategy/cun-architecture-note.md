# Architecture Note: CUN as Schedule-Scoped Synthesis

---

## The Question

Why does CUN (Coming Up Next) have its own synthesis pipeline instead of using the existing ingest enricher or ProcessorJob infrastructure?

---

## The Answer: Domain Mismatch

RetroVue has two existing content-processing pipelines:

1. **Ingest enrichers** — take an existing asset UUID, produce metadata about it (duration, chapters, tags). The enricher protocol's domain entity is the **asset**.

2. **ProcessorJobs** — target `(ASSET|MEDIA, target_id)`. The queue operates on **existing assets** or media files. Every job has a target that already exists in the catalog.

CUN synthesis is fundamentally different:

- **Input:** a schedule segment (channel + time + "what airs next?")
- **Output:** a new rendered video that did not previously exist
- **Domain entity:** schedule segment, not asset

There is no target asset UUID at enqueue time. The asset is the *output* of the process, not the input. Forcing CUN through the enricher protocol would require inventing phantom assets — records in the asset table that represent "content that doesn't exist yet." This breaks the domain model: assets are discovered media with known file paths and probed metadata. A CUN segment is none of those things until after rendering.

---

## Schedule-Scoped vs. Asset-Scoped

| Dimension | Asset-scoped (enrichers, ProcessorJobs) | Schedule-scoped (CUN synthesis) |
|-----------|------------------------------------------|----------------------------------|
| Input | Existing asset UUID | Schedule segment (channel + time + title) |
| Output | Metadata about existing content | New rendered video |
| When it runs | After ingest discovery | After schedule compilation |
| Domain entity | Asset | Schedule segment |
| Target exists at enqueue? | Yes | No — created by the process |
| Lifecycle tied to | Asset catalog | Broadcast schedule |

---

## What CUN Reuses

CUN is a new *pipeline concept* but reuses proven *patterns*:

- **Claim-with-SKIP-LOCKED** — the same Postgres queue-claim pattern used by `processor_worker` for fair work distribution
- **Priority ordering** — playout-time ordering mirrors the existing priority semantics
- **Content-addressed caching** — SHA256 deterministic seeding matches `INV-TIER3-POOL-DETERMINISTIC-001` and `INV-SCHEDULE-SEED-DETERMINISTIC-001`
- **ffmpeg compositing** — drawtext/overlay, same toolchain as existing media processing

The boundary is clean: same tools, different domain entity.

---

## Why Not "Just Add a Column to ProcessorJobs"

Adding a `schedule_segment_id` column to `processor_jobs` would create a polymorphic queue where some jobs have `target_id` (asset-scoped) and others have `schedule_segment_id` (schedule-scoped). This creates:

- **Ambiguous domain boundaries** — the queue serves two unrelated domain concepts
- **Mixed lifecycle semantics** — asset jobs are tied to catalog state; CUN jobs are tied to broadcast schedule
- **Priority collision** — asset processing priorities and CUN playout-time priorities are on different scales
- **Cleanup confusion** — asset jobs expire with asset state; CUN jobs expire with broadcast time

A dedicated `cun_render_requests` table with ~350 lines of new code is simpler than retrofitting a polymorphic queue and maintaining two sets of lifecycle rules in one table.

---

## Authority Boundaries

CUN synthesis introduces no new authority domains. It maps cleanly onto existing ones:

| Concern | Existing authority | CUN's role |
|---------|--------------------|------------|
| What segments exist | Schedule compiler (`optional_presentation.py`) | Places CUN segments when `features.coming_up_next` is true |
| Producing rendered media | New: `CunSynthesisWorker` | Isolated render execution, no scheduling decisions |
| Playout resolution | `PlaylistBuilderDaemon` | Detect → enqueue → resolve/skip (delegation, not ownership) |
| Feature gating | Channel config | `features.coming_up_next` flag |
| Runtime execution | AIR | Zero involvement — plays resolved assets like anything else |

No existing authority boundary is crossed or shared.

---

## Impact Summary

- ~350 lines new code + 1 migration
- Zero AIR changes
- Zero enricher protocol changes
- Zero ProcessorJob changes
- New table: `cun_render_requests`
- New worker: `CunSynthesisWorker`
- Channel config extension: `features.coming_up_next` + `continuity.coming_up_next`
