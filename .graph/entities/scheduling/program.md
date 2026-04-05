# Program

**Domain:** scheduling  
**Slug:** `program`

## What it represents

An **editorial program unit** in the schedule: what fills zones or blocks (including virtual/synthetic program concepts as used in contracts).

## Lifecycle phase

**Planned** / **resolved** into concrete material during derivation—not executed directly as a runtime object.

## Owning domain

scheduling

## What depends on it

ScheduleDay composition, EPG rows, pool resolution, episode progression.

## What produces it

Editorial scheduling inputs and compilation tiers (per traffic/block contracts).

## What must NOT be assumed

- That “program” equals a single file on disk (may map through pools, bumpers, traffic).
- That program titles in EPG are authoritative for segment boundaries at runtime.
