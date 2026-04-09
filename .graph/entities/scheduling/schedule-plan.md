# SchedulePlan

**Domain:** scheduling
**Slug:** `schedule-plan`
**Status:** RETIRED (2026-04-09, RETA-88 Option B)

## Retirement notice

SchedulePlan and its CRUD surface (SchedulePlan → Zone → Program) have been retired. The DSL + ScheduleRevision/ScheduleItem is now the sole scheduling authority path.

Board decision: RETA-88 Option B approved — DSL compilation produces ScheduleRevision rows directly; SchedulePlan is no longer the editorial authority.

## What it represented (historical)

The editorial authority for what programming structure was intended on a channel: schedulable regions, content choices, and rules that downstream artifacts were required to honor.

## What replaced it

- **DSL schedule definitions** — operators define schedules in DSL files
- **ScheduleRevision** — the persistence layer for compiled DSL output
- **ScheduleItem** — individual scheduled entries within a revision
- **DslScheduleService** — compiles DSL → ScheduleRevision/ScheduleItem

## Preserved concepts (future DSL promotion)

Zone-level concepts (DST policy, day filters, effective date ranges, coverage validation) are documented for future DSL enhancement. See `docs/architecture/decisions/ADR-016-Zone-Concepts-For-DSL-Promotion.md`.

## What must NOT be assumed

- That SchedulePlan is still the editorial authority (it is not — DSL is).
- That new CRUD endpoints should be built for scheduling (DSL is the sole input path).
