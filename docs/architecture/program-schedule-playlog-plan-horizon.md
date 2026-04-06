# Program Schedule & Playlog Plan Horizon

## Decision Date: 2026-02-18

## Overview

Replace the current ad-hoc schedule compilation and late-bind ad fill
(`INV-TRAFFIC-LATE-BIND-001`) with a rolling horizon built from two layers:
**program_schedule** (editorial grid and break opportunities) and **playlog_plan**
(the **Playlog Plan**: persisted `PlaylistEvent` horizon). ChannelManager consumes
the Playlog Plan and builds the **runtime playlog** (ephemeral, join-aware segment
sequence) that AIR actually decodes. Do not use bare **playlog** in prose or APIs;
use **Playlog Plan** / `playlog_plan` or **runtime playlog** / `runtime_playlog`.
See `INV-PLAYLOG-PLAN-VS-RUNTIME-001`. **As-run** (transmission log) is historical
ground truth after air.

Both layers are Postgres-backed (canonical store), with optional in-memory
caching for the near-term window.

---

## Program schedule — schedule store (2–3 days ahead)

**What it stores:** `ScheduleDay` / `ScheduleItems` with break opportunities
(positions + durations). No ad assignments. Enough metadata to derive EPG
and to feed playlog plan generation.

**Source:** DSL compiler (or any future schedule source) writes here.
DSL is a *source* that feeds the program schedule, not a special runtime path that
bypasses horizons.

**EPG:** Derived view from the program schedule. Not the stored artifact itself.

**Rolling policy:** When a day completes (falls off the trailing edge),
generate the next day at the leading edge. Maintain 2–3 days of coverage.

**Storage:** Postgres (source of truth). Enables restart safety, guide
rendering, introspection, debugging.

---

## Playlog Plan — playlog store (2–3+ hours ahead)

**What it stores:** Fine-grained playout plan — concrete segments with
real asset URIs, timecodes, filled ad pods, bumpers. Everything AIR
needs to execute a block.

**Source:** Consumes program schedule items. Runs `fill_ad_blocks()` /
traffic manager to select real interstitials at generation time.

**Ad selection timing:** "Late bind but not too late."
- NOT at program schedule compile time (too early → staleness, inventory changes, pacing)
- NOT at feed time (too late → time pressure, seam risk, inconsistent logs)
- YES at playlog plan generation time (hours ahead: current enough, safe enough)

**Rolling policy:** When the earliest block is consumed, extend forward.
Maintain 2–3+ hours of coverage.

**Storage:** Postgres (source of truth). In-memory cache optional for
the immediate window.

---

## ChannelManager — Consumer, Not Compiler

**Reads from:** playlog plan (`PlaylistEvent`).

**Still responsible for:**
- Wall-clock → current event lookup
- JIP offset computation (join mid-show/mid-segment)
- Producer seek/concat orchestration
- Feeding blocks to AIR

**No longer responsible for:**
- Ad selection (`_fill_block_at_feed_time` eliminated)
- Schedule compilation (no DSL parsing at runtime)
- `INV-TRAFFIC-LATE-BIND-001` is retired

---

## Background Daemons

### Schedule horizon (program schedule)
- Monitors program schedule depth
- When depth < 2 days, triggers DSL compiler for the next day
- Writes to schedule store (Postgres)

### Playlog horizon (playlog plan)
- Monitors playlog plan depth
- When depth < 2–3 hours, reads next entries from the program schedule
- Runs traffic manager / `fill_ad_blocks` to fill break slots
- Writes to playlog store (Postgres)

---

## Migration Path

1. Define Postgres schema for program schedule (`schedule_items`) and playlog plan (`playlog_entries`)
2. Build schedule horizon daemon (DSL → program schedule)
3. Build playlog horizon daemon (program schedule → playlog plan with ad fill)
4. Rewire ChannelManager to read playlog plan
5. Remove `_fill_block_at_feed_time` and `INV-TRAFFIC-LATE-BIND-001`
6. Remove DslScheduleService's on-demand compilation path

## Contracts Retired
- `INV-TRAFFIC-LATE-BIND-001` — replaced by playlog plan pre-fill

## Contracts Introduced
- `INV-SCHEDULE-HORIZON-001` — program schedule maintains ≥2 days coverage
- `INV-PLAYLOG-HORIZON-001` — playlog plan maintains ≥2 hours coverage
- `INV-PLAYLOG-PREFILL-001` — Ad fill happens at playlog plan generation, never at feed time
- `INV-CHANNEL-NO-COMPILE-001` — ChannelManager never compiles schedules or fills ads

## Implementation Notes

Core architectural elements are in place: `PlaylistBuilderDaemon` writes to
`PlaylistEvent`, `DslScheduleService` reads from the playlog plan,
`ProgramDirector` starts daemons per DSL channel, and
`_fill_block_at_feed_time` has been removed.

For current implementation status and remaining work, see the project task
tracker — not this document. Architecture docs describe *what* and *why*;
task trackers own *progress*.
