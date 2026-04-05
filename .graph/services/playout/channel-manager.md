# ChannelManager

**Domain:** playout  
**Slug:** `channel-manager`

## Responsibility

**Per-channel runtime owner**: supervises AIR process, gRPC session (BlockPlan / attach stream), consumes **prefetched playlog / execution events** (from the execution plan horizon), turns that stream into live playout for that channel.

## Owns vs reads

- **Owns:** process/session lifecycle for the channel instance it holds, feeding AIR, TS socket/source wiring as designed.
- **Reads:** **Playlog / execution window store** as given—no repair via planning APIs. A **playlist-shaped** view may appear in some implementations but is **not** the authority root.

## Upstream inputs

**`playlog` (event stream / automation log)** from scheduling’s execution horizon, wall clock via orchestration, `program-director` activation.

## Downstream outputs

Byte stream to HTTP sink, AIR commands, structured logs with `session_id` where applicable.

## Must NOT do

- **Scheduling or planning at runtime:** no asset-library queries for playback decisions, no extending execution entries or playlog on demand, no schedule math, no EPG-driven playback (`INV-CHANNELMANAGER-NO-PLANNING-001`, `INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001`).
- Treat **playlist** as something to **re-author** or **repair** at runtime—it is at best a convenience view over the execution spine.
- Talk to scheduling as a **peer** to fix gaps; horizon exhaustion must surface as a **planning fault**, not runtime improvisation (see execution-boundary contracts in RetroVue).

## Note

Mediates **all** planning→AIR influence: scheduling never talks to AIR directly (`INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001`).
