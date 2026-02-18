# Two-Tier Horizon Architecture

## Decision Date: 2026-02-18

## Overview

Replace the current ad-hoc schedule compilation and late-bind ad fill
(`INV-TRAFFIC-LATE-BIND-001`) with a two-tier rolling horizon system.
Both tiers are Postgres-backed (canonical store), with optional in-memory
caching for the near-term window.

---

## Tier 1 — Schedule Store (2–3 days ahead)

**What it stores:** `ScheduleDay` / `ScheduleItems` with break opportunities
(positions + durations). No ad assignments. Enough metadata to derive EPG
and to feed Tier 2.

**Source:** DSL compiler (or any future schedule source) writes here.
DSL is a *source* that feeds Tier 1, not a special runtime path that
bypasses horizons.

**EPG:** Derived view from Tier 1. Not the stored artifact itself.

**Rolling policy:** When a day completes (falls off the trailing edge),
generate the next day at the leading edge. Maintain 2–3 days of coverage.

**Storage:** Postgres (source of truth). Enables restart safety, guide
rendering, introspection, debugging.

---

## Tier 2 — Playlog Store (2–3+ hours ahead)

**What it stores:** Fine-grained playout plan — concrete segments with
real asset URIs, timecodes, filled ad pods, bumpers. Everything AIR
needs to execute a block.

**Source:** Consumes Tier 1 schedule items. Runs `fill_ad_blocks()` /
traffic manager to select real interstitials at generation time.

**Ad selection timing:** "Late bind but not too late."
- NOT at Tier 1 time (too early → staleness, inventory changes, pacing)
- NOT at feed time (too late → time pressure, seam risk, inconsistent logs)
- YES at Tier 2 generation time (hours ahead: current enough, safe enough)

**Rolling policy:** When the earliest block is consumed, extend forward.
Maintain 2–3+ hours of coverage.

**Storage:** Postgres (source of truth). In-memory cache optional for
the immediate window.

---

## ChannelManager — Consumer, Not Compiler

**Reads from:** Tier 2 Playlog Store.

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

### Schedule Horizon Daemon
- Monitors Tier 1 depth
- When depth < 2 days, triggers DSL compiler for the next day
- Writes to Schedule Store (Postgres)

### Playlog Horizon Daemon
- Monitors Tier 2 depth
- When depth < 2–3 hours, reads next entries from Tier 1
- Runs traffic manager / `fill_ad_blocks` to fill break slots
- Writes to Playlog Store (Postgres)

---

## Migration Path

1. Define Postgres schema for Tier 1 (schedule_items) and Tier 2 (playlog_entries)
2. Build Schedule Horizon Daemon (DSL → Tier 1)
3. Build Playlog Horizon Daemon (Tier 1 → Tier 2 with ad fill)
4. Rewire ChannelManager to read from Tier 2
5. Remove `_fill_block_at_feed_time` and `INV-TRAFFIC-LATE-BIND-001`
6. Remove DslScheduleService's on-demand compilation path

## Contracts Retired
- `INV-TRAFFIC-LATE-BIND-001` — replaced by Tier 2 pre-fill

## Contracts Introduced
- `INV-SCHEDULE-HORIZON-001` — Tier 1 maintains ≥2 days coverage
- `INV-PLAYLOG-HORIZON-001` — Tier 2 maintains ≥2 hours coverage
- `INV-PLAYLOG-PREFILL-001` — Ad fill happens at Tier 2 generation, never at feed time
- `INV-CHANNEL-NO-COMPILE-001` — ChannelManager never compiles schedules or fills ads

## Implementation Status (2026-02-18)

### Completed
- [x] Tier 1: CompiledProgramLog stores segmented_blocks (content + break opportunities)
- [x] Tier 2: PlaylogHorizonDaemon fills ads and writes to TransmissionLog
- [x] Consumer: DslScheduleService.get_block_at reads Tier 2 first
- [x] Wiring: ProgramDirector starts PlaylogHorizonDaemon per DSL channel
- [x] INV-TRAFFIC-LATE-BIND-001 retired, replaced by INV-PLAYLOG-PREFILL-001
- [x] JIP ad continuity: re-join returns same ads from TransmissionLog

### Remaining
- [ ] Recompile all channels' CompiledProgramLog caches (only cheers-24-7 done)
- [ ] Schedule Horizon Daemon (Tier 1 rolling — currently manual/on-demand)
- [ ] Remove _fill_block_at_feed_time from ChannelManager (already absent post-revert)
- [ ] Eviction policy for old TransmissionLog entries
- [ ] Health endpoint exposing PlaylogHorizonDaemon status
