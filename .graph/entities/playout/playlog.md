# Playlog

**Domain:** playout  
**Slug:** `playlog`

## What it represents

The **broadcast-accurate execution event stream** (automation log): ordered events with resolved material and timing, within a **prefetched horizon**, that **`channel-manager` walks** to drive AIR. This is the primary **consumable** execution artifact between planning and runtime—not an optional label.

## Lifecycle phase

**Derived** in Core from the **execution plan** (`execution-entry` / locked execution window and horizon pipeline); **not** AIR-internal state.

## Owning domain

playout (consumption artifact); **authority** originates in scheduling’s execution plan, materialized as this stream.

## What depends on it

`channel-manager`, `block-plan-producer` / session feeding, horizon sufficiency checks.

## What produces it

**Two layers** (RetroVue `docs/core/GLOSSARY.md` — do not collapse):

1. **Playlog plan (persisted)** — scheduling-side ahead-of-air materialization from **ScheduleItem** / execution chain into stored **PlaylistEvent**-style rows (`playlog_plan`). This is **not** the runtime executable timeline by itself (`INV-PLAYLOG-PLAN-VS-RUNTIME-001` in contracts index). No single graph service node names the whole pipeline; it spans scheduling modules that derive from **`execution-entry`** and related day/plan entities.

2. **Runtime playlog (ephemeral)** — **`channel-manager`** (and its execution path) reads the persisted plan and constructs the **join-aware, wall-clock-now** sequence fed toward BlockPlan / AIR. That transform is **consumption**, not a second editorial root (`INV-CHANNELMANAGER-NO-PLANNING-001`).

There is **no** dedicated `playlog-builder` service stub in this graph: the name would imply one class owns both layers, which the contracts split. Use YAML `playlog` → `execution-entry` plus this section when an agent asks **who builds playlog?**

## What must NOT be assumed

- That it is safe to extend on demand from ChannelManager mid-session (boundary invariants forbid compensating planning there).
- That **`playlist`** is a substitute for this spine; playlist may **mirror** playlog for convenience but does not replace it as the center of truth.
