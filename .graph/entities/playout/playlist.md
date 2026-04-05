# Playlist

**Domain:** playout  
**Slug:** `playlist`

## What it represents

A **convenience or contract-shaped carrier** for ordered execution data—useful for APIs, burn-in tests, or locked interchange formats. It is **not** the authority spine for “what airs.”

## Lifecycle phase

**Derived** / materialized from the same facts as **playlog** (execution plan → events), or emitted directly by transitional producers (e.g. `playlist-schedule-manager`) **without** replacing `execution-entry` as authority.

## Owning domain

playout (as a **shape**, not as truth); semantic authority remains **scheduling execution plan → playlog**.

## What depends on it

Nothing **must** depend on it for correctness; consumers should prefer **`playlog` / execution window** as the broadcast-accurate path.

## What produces it

`playlist-schedule-manager` or any component that outputs playlist-shaped data—still obligated to stay **downstream of** execution planning, not a second editorial root.

## What must NOT be assumed

- **Critical:** that “playlist” is ChannelManager’s **source of truth** (correct chain: execution plan → playlog/events → ChannelManager).
- That ChannelManager may rebuild or patch it using Asset Library or EPG.
- That “playlist” means a user-curated music playlist; here it is **automation-list shape**, not authority.
