# DslScheduleService

**Domain:** scheduling
**Slug:** `dsl-schedule-service`

## What it does

The **sole editorial compilation path** for channel schedules. Compiles operator-authored DSL schedule definitions into ScheduleRevision + ScheduleItem persistence rows.

Replaces the retired SchedulePlan → Zone → Program CRUD island (RETA-88 Option B).

## Lifecycle phase

**Runtime service** — invoked when schedules are compiled or recompiled from DSL definitions.

## Owning domain

scheduling

## What depends on it

ScheduleDay derivation, ScheduleRevision persistence, and ultimately all downstream execution artifacts (TransmissionLog, ExecutionEntry, playlog horizon).

## What it produces

- **ScheduleRevision** rows — immutable published schedule snapshots
- **ScheduleItem** rows — individual content assignments within a revision

## What it consumes

- DSL schedule definition files (operator-authored)
- Eligible asset catalog (for content resolution)
- Channel configuration

## Key invariants

- `INV-TIMELINE-SINGLE-AUTHORITY-001` — ScheduleRevision is the sole timeline authority
- `INV-COMPILED-BLOCK-CONTIGUITY-001` — compiled blocks must be contiguous
- `INV-COMPILED-GRID-ALIGNMENT-001` — compiled blocks must align to grid

## What must NOT be assumed

- That there is a CRUD alternative to DSL compilation (there is not).
- That DslScheduleService talks to AIR (prohibited by INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001).
