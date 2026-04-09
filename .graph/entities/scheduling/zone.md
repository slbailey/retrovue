# Zone

**Domain:** scheduling
**Slug:** `zone`
**Status:** RETIRED (2026-04-09, RETA-88 Option B)

## Retirement notice

Zone and the SchedulePlan CRUD island have been retired. The DSL + ScheduleRevision/ScheduleItem is now the sole scheduling authority path.

## What it represented (historical)

A time-bounded scheduling region within the grid that held schedulable content or avails, without cutting in-flight longform against contract rules.

## Preserved concepts (future DSL promotion)

The following Zone-level concepts are valuable and are preserved for future DSL enhancement:

- **DST policy** — reject, shrink_one_block, expand_one_block
- **Day filters** — restrict scheduling to specific days of week
- **Effective date ranges** — seasonal scheduling
- **Coverage validation** — overlap/tiling checks across time regions

These concepts will be promoted as DSL-native features when needed. See `docs/architecture/decisions/ADR-016-Zone-Concepts-For-DSL-Promotion.md`.

## What must NOT be assumed

- That Zone is a runtime object visible to AIR (never was).
- That new Zone CRUD endpoints should be built (DSL replaces Zone-level intent).
