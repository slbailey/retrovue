# Channel

**Domain:** scheduling  
**Slug:** `channel`

## What it represents

A **persistent logical channel**: identity, grid parameters (e.g. block size, programming day start), and configuration that scheduling and playout both refer to—each for different purposes.

## Lifecycle phase

**Persisted** configuration + long-lived identity; runtime **state** (active session) is playout’s concern.

## Owning domain

scheduling (canonical **catalog/config** truth); playout **references** the same id for sessions.

## What depends on it

SchedulePlan, ScheduleDay, EPG, execution plans, and all per-channel runtime orchestration.

## What produces it

Operators / Core persistence (not AIR).

## What must NOT be assumed

- That “channel” in logs means only scheduling or only runtime—disambiguate by **context** (grid vs active playout session).
- That channel configuration implies AIR is running (compute-on-viewers model).
