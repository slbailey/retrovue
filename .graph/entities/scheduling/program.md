# Program

**Domain:** scheduling
**Slug:** `program`
**Status:** RETIRED (2026-04-09, RETA-88 Option B)

## Retirement notice

Program (as a CRUD entity within the SchedulePlan island) has been retired. Content references in the scheduling domain now flow through DSL schedule definitions → ScheduleRevision/ScheduleItem.

Note: "program" as a general broadcast concept (what fills a time slot) remains valid terminology. This retirement applies to the `Program` entity class and its CRUD surface, not to the concept of scheduled programming.

## What it represented (historical)

An editorial program unit in the schedule: what filled zones or blocks, including virtual/synthetic program concepts as used in contracts.

## What replaced it

- **DSL schedule blocks** — content references are expressed in DSL syntax
- **ScheduleItem** — persisted content assignments within a ScheduleRevision
- **Programming pools** — content selection from eligible asset pools (unchanged)

## What must NOT be assumed

- That "program" equals a single file on disk (may map through pools, bumpers, traffic).
- That program titles in EPG are authoritative for segment boundaries at runtime.
- That new Program CRUD should be built (DSL is the sole content assignment path).
