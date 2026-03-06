# Movie Channel Scheduling Invariants

**Status:** Authoritative
**Authority Level:** Planning (Tier 1) / Execution (Tier 2)
**Derived From:** `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`, `LAW-GRID`
**Governs:** Primary segment atomicity, traffic insertion boundaries, expansion pipeline equivalence for `channel_type: movie` channels

---

## Domain — Movie Channel Scheduling

### Purpose

Movie channels (`channel_type: movie`) simulate premium linear television services where primary content plays uninterrupted. This document codifies the invariants that protect primary content atomicity, constrain traffic insertion, and enforce expansion pipeline equivalence across all code paths that produce PlaylistEvents for movie channels.

These invariants exist to protect `LAW-CONTENT-AUTHORITY` (editorial intent is authoritative) and `LAW-DERIVATION` (each artifact derives exclusively from its upstream authority). A movie-channel program event is an atomic editorial unit. No downstream stage may fragment it.

---

### Primary segment definition

A **primary segment** is a template segment marked `primary: true`. It represents the atomic editorial content of a program event — the feature film.

Per `INV-TEMPLATE-PRIMARY-SEGMENT-001`, every template MUST resolve to exactly one primary content segment. The primary segment's resolved asset provides the editorial identity (EPG title, asset_id) for the program block.

Primary segment identification follows the rules in `INV-TEMPLATE-PRIMARY-SEGMENT-001`:

1. Explicit `primary: true` flag on exactly one segment.
2. Convention fallback: exactly one `source.type == "pool"` segment when no explicit flag.
3. Ambiguous cases (zero pools, multiple pools, multiple explicit) are compile errors.

---

### Allowed template structures

A movie-channel template MUST contain:

- Exactly one segment with `primary: true` (explicit or by convention).
- Zero or more non-primary segments (`source.type: collection` or `source.type: pool`).

Non-primary segments (e.g., branded intros, bumpers) are auxiliary. They precede or follow the primary segment in declared order. Segment order is invariant — resolution MUST NOT reorder segments.

**Example — HBO Feature With Intro:**

```yaml
templates:
  hbo_feature_with_intro:
    segments:
      - source:
          type: collection
          name: Intros
        selection:
          - type: tags
            values: [hbo]
        mode: random
      - source:
          type: pool
          name: hbo_movies
        mode: random          # ← primary by convention (sole pool)
```

Segment 1 (Intro) is non-primary. Segment 2 (Movie) is primary by convention.

---

### Primary segment atomicity

**INV-MOVIE-PRIMARY-ATOMIC:** A segment marked `primary: true` on a `channel_type: movie` channel MUST NOT be split, interrupted, or internally segmented by any function in the system.

This is the central invariant. It means:

- No mid-content ad breaks within the primary segment.
- No filler insertion within the primary segment.
- No chapter-marker-based splitting of the primary segment.
- The primary segment resolves to a single, contiguous `ScheduledSegment` of type `"content"` in the expanded `ScheduledBlock`.

The existing `_expand_movie()` function in `playout_log_expander.py` enforces this by emitting a single content segment for the full episode duration with zero mid-content breaks.

---

### Traffic insertion rules

Traffic insertion on movie channels is constrained to positions that do not violate primary segment atomicity.

**Permitted insertion points:**

1. **Between blocks** — after one program event ends and before the next begins.
2. **After the primary segment completes** — in the post-content filler window within the same block.

**Prohibited insertion points:**

1. Inside the primary segment.
2. Between the primary segment and a preceding non-primary segment within the same template iteration (e.g., between the intro and the movie).

The `fill_ad_blocks()` function in `traffic_manager.py` operates on `segment_type="filler"` placeholders only. It MUST NOT create new segment boundaries within existing `segment_type="content"` segments. For movie channels, filler placeholders exist only after the primary content — never within it.

The channel-level `traffic` configuration (`allowed_types`, `default_cooldown_seconds`, `max_plays_per_day`) further constrains what content may fill these slots but does not affect where slots may exist.

---

### Expansion pipeline

The canonical expansion pipeline for movie-channel program blocks is:

```
Tier-1 ScheduleItem
  │
  │  ScheduleItem.metadata_ contains compiled_segments
  │  (populated by _compile_template_entry → _resolve_template_segments)
  │
  ▼
expand_editorial_block()
  │
  │  Gate: if compiled_segments present → _hydrate_compiled_segments()
  │        else → expand_program_block(channel_type="movie")
  │
  │  Both paths produce a ScheduledBlock with:
  │    - One or more content segments (template segments in order)
  │    - One post-content filler placeholder (if underfill)
  │    - Zero mid-content breaks
  │
  ▼
TrafficManager (fill_ad_blocks)
  │
  │  Fills segment_type="filler" placeholders with interstitials.
  │  MUST NOT split or create new content segments.
  │
  ▼
PlaylistEvent
```

**Key files:**

- `schedule_compiler.py` — `_compile_template_entry()`, `_resolve_template_segments()`
- `schedule_items_reader.py` — `load_segmented_blocks_from_active_revision()`, `_hydrate_compiled_segments()`
- `playout_log_expander.py` — `expand_program_block()`, `_expand_movie()`
- `traffic_manager.py` — `fill_ad_blocks()`
- `schedule_rebuild.py` — `rebuild_tier2()`

---

### Expansion path equivalence

**Two expansion paths exist:**

1. **Template path (preferred):** `compiled_segments` present in `ScheduleItem.metadata_` → `_hydrate_compiled_segments()` builds the `ScheduledBlock` directly from pre-compiled segment data.

2. **Legacy path:** `compiled_segments` absent → `expand_program_block(channel_type="movie")` builds a single-content-segment block.

Both paths MUST produce a `ScheduledBlock` with zero mid-content breaks for movie channels. The template path preserves additional structure (intro + movie as separate segments) while the legacy path emits a single content segment.

Neither path may introduce mid-content filler or ad break segments.

---

### Rebuild equivalence requirement

**INV-MOVIE-REBUILD-EQUIVALENCE:** `schedule rebuild --tier 2` MUST use the same editorial block expansion path as the horizon scheduler daemon.

The `rebuild_tier2()` function in `schedule_rebuild.py` calls `load_segmented_blocks_from_active_revision()` — the same function used by the horizon daemon. This ensures:

- The same `compiled_segments` gate logic applies.
- The same `_hydrate_compiled_segments()` or `expand_program_block()` path is taken.
- The same `fill_ad_blocks()` traffic insertion runs.

A Tier-2 rebuild MUST NOT use a different expansion function, bypass the compiled_segments gate, or apply different traffic insertion logic than the daemon. Divergence between rebuild and daemon output for identical Tier-1 inputs is a violation.

---

### Invariant summary

| ID | Guarantee |
|----|-----------|
| INV-MOVIE-PRIMARY-ATOMIC | Primary segment MUST NOT be split or interrupted on movie channels. |
| INV-MOVIE-TRAFFIC-POST-ONLY | Traffic insertion MUST occur only after the primary segment or between blocks. |
| INV-MOVIE-NO-MID-CONTENT-BREAK | No function may introduce mid-content breaks for `channel_type: movie`. |
| INV-MOVIE-REBUILD-EQUIVALENCE | Tier-2 rebuild MUST use the same expansion path as the horizon daemon. |
| INV-TEMPLATE-PRIMARY-SEGMENT-001 | Templates MUST resolve exactly one primary content segment. |

---

### Test enforcement

Tests enforcing these invariants:

- `pkg/core/tests/contracts/test_template_graft_contract.py` — Primary segment detection rules (`INV-TEMPLATE-PRIMARY-SEGMENT-001`).
- `pkg/core/tests/runtime/test_traffic_manager.py` — Traffic insertion operates only on filler placeholders; no content segment splitting.
- `tests/contracts/test_inv_template_segments_compiled.py` — Compiled segments structure, persistence, and hydration.
- `tests/contracts/test_schedule_rebuild.py` — Rebuild produces output equivalent to daemon path.

Future contract tests SHOULD validate:

- `_expand_movie()` produces exactly one content segment and zero mid-content filler segments.
- `_hydrate_compiled_segments()` for movie-channel templates produces zero mid-content breaks.
- `fill_ad_blocks()` never increases the count of `segment_type="content"` segments in a block.
- Rebuild and daemon produce identical `ScheduledBlock` output for the same Tier-1 input.

---

**Related:** [ProgramTemplateAssembly](ProgramTemplateAssembly.md) · [ExecutionPipeline](ExecutionPipeline.md) · [ScheduleItem](ScheduleItem.md) · `INV-TEMPLATE-PRIMARY-SEGMENT-001` · `INV-TIER2-COMPILATION-CONSISTENCY-001`
