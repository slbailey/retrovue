# SchedulePlan

**Domain:** scheduling  
**Slug:** `schedule-plan`

## What it represents

The **sole editorial authority** for what programming structure is intended on a channel: schedulable regions, content choices, and rules that downstream artifacts must honor.

## Lifecycle phase

**Persisted** editorial object; evolves under immutability and future-window rules (see contracts).

## Owning domain

scheduling

## What depends on it

ScheduleDay derivation, zone resolution, traffic/break structures, and ultimately execution artifacts—indirectly.

## What produces it

Human/operators and tooling via Core’s scheduling surface (not playout).

## What must NOT be assumed

- That it is the same as “what is playing right now” (runtime authority is ExecutionEntry / execution window).
- That AIR or ChannelManager reads or repairs it at runtime.
