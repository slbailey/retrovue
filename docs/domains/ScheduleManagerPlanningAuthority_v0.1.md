# Schedule Manager Planning Authority — v0.1

**Status:** Contract  
**Version:** 0.1

---

## Purpose

This contract establishes the **Schedule Manager** as the sole **planning authority** for broadcast scheduling in RetroVue. It defines what the Schedule Manager owns (editorial and traffic planning, horizon policy, material resolution), what it delivers to playout (execution-ready data), and what it does not do. Channel Manager is **execution authority only** and consumes pre-built execution data; it does not resolve episodes or query the asset library.

---

## Scope

- **In scope:** Planning pipeline from editorial plan to execution-ready playout instructions; two-horizon policy (EPG vs execution); material association and Asset Library interface; interfaces supplied to Channel Manager; operator workflows; naming and versioning of planning artifacts.
- **Out of scope:** Real-time playout execution, encoding, muxing, and transport (owned by playout engine and Channel Manager).

---

## Broadcast Entities and Glossary

| Term | Definition |
|------|------------|
| **Schedule Plan** | Editorial template: channel, date rules, zones (time windows), and schedulable content (programs, assets, placeholders). Defines *what* can air and *when* it is allowed. |
| **Schedule Day** | Resolved schedule for one channel and one broadcast date. Built from active Schedule Plans; frozen once generated. Source of truth for “what will air when” for that day. |
| **EPG (Electronic Program Guide)** | Viewer-facing guide derived from Schedule Day. Read-only; never a source of truth for planning or playout. |
| **Playlist** | Ordered list of playable items (resolved physical assets, timecodes, segments) derived from Schedule Day. Bridges editorial schedule to execution. |
| **Playlog / execution plan** | Time-aligned, execution-ready instructions: segments, in/out points, filler/padding rules. Consumed by Channel Manager for playout. Synonymous with **Transmission Log** in broadcast ops; operators and auditing refer to this log. |
| **Block** | Execution unit: a contiguous span of playout (content + optional filler/padding) bounded by schedule or grid. |
| **Zone** | Time window within a Schedule Plan (e.g. 06:00–12:00) holding schedulable content. |
| **Schedulable asset** | Program, single asset, virtual asset, or synthetic asset that can be placed in a zone. |
| **Asset Library** | Catalog of approved, broadcast-ready assets. Planning resolves references (e.g. program → episode) against the library; execution receives only resolved references. |
| **Traffic** | Function that turns plans into resolved schedules and execution data (Schedule Manager in this system). |
| **Automation** | Execution of the playlog (Channel Manager + playout engine). |

---

## Planning Pipeline

1. **Plan** — Operator defines Schedule Plans (zones, schedulable content, date/cron rules).
2. **Resolve to Schedule Day** — Traffic resolves active plans for a channel/date into a Schedule Day (frozen, immutable).
3. **EPG** — EPG is generated from Schedule Day for viewer display.
4. **Playlist** — From Schedule Day, traffic builds Playlist (resolved assets, timecodes, segment boundaries).
5. **Execution plan (playlog)** — From Playlist, traffic builds the execution plan: blocks, segments, frame-accurate or time-accurate instructions, filler/padding rules.
6. **Playout** — Channel Manager runs automation against the execution plan only.

All planning (steps 1–5) happens **ahead of real time**. No planning step is performed on-demand at playout time.

---

## Horizon Policy (EPG vs Execution)

Two distinct horizons are defined and enforced.

### EPG horizon

- **Definition:** The window of Schedule Day data maintained for EPG and editorial visibility (e.g. multiple days ahead).
- **Purpose:** Stable “what will air when” for guides and operators. Schedule Days are built and frozen within this horizon.
- **Characteristic:** Coarse, day-level or slot-level; sufficient for EPG and planning visibility.

### Execution horizon

- **Definition:** The window of execution-ready data (playlog / block plan) built ahead of real time for actual playout.
- **Purpose:** Automation runs from this data only. No resolution of episodes, no Asset Library lookups, no schedule math at playout time.
- **Guarantee:** Execution-horizon data is **pre-built**. Every segment and block that playout will use is produced by the planning pipeline before the playout engine is asked to run it. There is **no on-demand planning at playout time**: Channel Manager never triggers episode resolution, playlist build, or asset resolution; it only consumes already-built execution instructions.
- **Immutability:** Once execution data enters the execution horizon, it is immutable except by explicit operator override that regenerates the affected window.

---

## Material Association and Asset Library Interface

- **Schedule Manager (traffic)** is responsible for resolving all material references before execution data is handed off. This includes: resolving programs to episodes, resolving virtual/synthetic assets to physical assets or rules, and validating that referenced assets exist and are approved in the Asset Library.
- **Asset Library** is queried only by the planning side (Schedule Manager / traffic). Queries happen when building Schedule Day, Playlist, or execution plan — never when serving playout.
- **Execution data** passed to Channel Manager contains only resolved references (e.g. asset identifiers, paths, or stable URIs). Channel Manager does not perform resolution or Asset Library lookups.

---

## Interfaces Provided to Channel Manager

Schedule Manager provides to Channel Manager:

- **Execution plan (playlog)** for the channel: ordered blocks/segments, with start/end times or frame counts, resolved asset references, and filler/padding rules as applicable.
- **Updates** to that plan within the execution horizon (e.g. next block or extended window), as defined by the planning pipeline — still pre-built, not computed on demand by Channel Manager.
- **No** raw Schedule Plans, Schedule Days, or EPG data as inputs to playout logic. Channel Manager may receive EPG or schedule metadata for display or logging only; playout behavior is driven solely by the execution plan.

Channel Manager does **not** receive:

- Authority to resolve episodes or programs.
- Authority to query the Asset Library.
- Authority to build or extend the playlog; it only consumes what is supplied.

---

## Operator Workflows

- **Plan authoring:** Create and edit Schedule Plans (zones, content, date rules). No direct effect on playout until plans are resolved into Schedule Days and execution data.
- **Schedule Day generation:** Trigger resolution of plans for a channel/date to produce a Schedule Day (and thus feed EPG and downstream playlist/playlog build).
- **Override / exception:** Replace or override Schedule Day for a channel/date (e.g. special event); re-run playlist/playlog build for affected window. Execution horizon is repopulated from the planning pipeline, not by Channel Manager.
- **Validation:** Validate plans, Schedule Days, or execution data for consistency and completeness before playout uses them.

---

## Naming, Identifiers, Versioning

- **Channels** are identified by stable channel identifiers (e.g. UUID or slug). All planning and execution data is keyed by channel and, where applicable, date and time.
- **Schedule Day** is identified by channel and broadcast date. Versioning of a Schedule Day is implicit: once frozen, it is immutable; a new generation replaces it (e.g. override or regenerate).
- **Execution plan (playlog)** is identified by channel and time window. Versions are implied by “current window supplied by Schedule Manager”; Channel Manager does not version plans internally beyond what is needed to apply the next block or segment.
- **Assets** are identified by Asset Library identifiers or stable paths in execution data; no ad-hoc naming is introduced at the Channel Manager boundary.

---

## Non-Goals

- **On-demand planning at playout:** The system does not perform schedule resolution, episode selection, or Asset Library queries when a viewer tunes in or when a block starts. All such work is done in the planning pipeline and reflected in pre-built execution data.
- **Channel Manager as planner:** Channel Manager does not resolve episodes, build playlists, or query the Asset Library. It is execution authority only.
- **EPG as playout source:** EPG is derived from Schedule Day for display only. Playout is driven by the execution plan, not by EPG.
- **Real-time schedule math in the playout path:** Fence times, block boundaries, and segment lengths are fixed in the execution plan. The playout engine executes them; it does not recompute them from Schedule Day or Plan.
- **As-run:** As-run logging is produced by automation based on execution of the playlog and is not a planning artifact.

---

**Document version:** 0.1  
**Planning authority:** Schedule Manager (traffic)  
**Execution authority:** Channel Manager (automation)
