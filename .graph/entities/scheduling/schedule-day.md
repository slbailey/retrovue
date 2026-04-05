# ScheduleDay

**Domain:** scheduling  
**Slug:** `schedule-day`

## What it represents

**Immutable daily truth** for a channel’s programming day: resolved structure for that date, subject to derivation and grid laws.

## Lifecycle phase

**Derived** then **locked/published** per immutability rules; not a runtime control loop.

## Owning domain

scheduling

## What depends on it

TransmissionLog, EPG, execution horizon generation, and other derived artifacts.

## What produces it

Scheduling derivation from SchedulePlan (and related inputs)—not playout.

## What must NOT be assumed

- That viewers or AIR consume it directly for playback decisions.
- That it can be silently rewritten for “now” without following reschedule / immutability contracts.
