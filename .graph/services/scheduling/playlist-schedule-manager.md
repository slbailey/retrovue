# PlaylistScheduleManager

**Domain:** scheduling  
**Slug:** `playlist-schedule-manager`

## Responsibility

Emit **playlist-shaped** data for phases that lock that interchange contract—**not** to establish a second source of truth. Architecturally stands in for part of the **traffic / schedule-manager** pipeline that must still ground out in **Schedule → execution plan → playlog/events**.

## Owns vs reads

- **Owns:** internal strategy for emitting the **shape** (phase-dependent).
- **Reads:** scheduling / **execution-entry** horizon inputs as required (must not bypass editorial or execution authority; see contracts).

## Upstream inputs

Schedule / resolution / **execution plan** artifacts as required by the concrete implementation (evolving toward full ScheduleDay-driven traffic).

## Downstream outputs

`playlist` entity as **convenience materialization**; the **authoritative consumable** for ChannelManager in the broadcast model remains **`playlog`** (execution events), whether or not it is byte-identical to a playlist file in a given phase.

## Must NOT do

- Talk to **AIR** or any playout engine API (`INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001`).
- Act as ChannelManager or perform HTTP delivery.
- Position **playlist** as **upstream of** or **replacing** `execution-entry` → `playlog`.

## Ambiguity

See `ambiguities/schedule-manager-vs-playlist-schedule-manager.md`.
