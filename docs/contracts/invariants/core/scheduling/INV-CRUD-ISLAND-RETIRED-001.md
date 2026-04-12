# INV-CRUD-ISLAND-RETIRED-001

## Behavioral Guarantee

No production module imports or references the retired CRUD island entities: `SchedulePlan`, `Zone`, `Program`, `SchedulePlanLabel`. These entities, their use cases, CLI commands, and API routes have been removed per RETA-88 Option B. The DSL + ScheduleRevision/ScheduleItem path is the sole scheduling authority.

## Authority Model

Core scheduling domain owns this invariant. LAW-CONTENT-AUTHORITY establishes DSL as sole editorial authority; this invariant enforces that the superseded CRUD island code does not re-enter the codebase.

## Boundary / Constraint

- No production module under `server/src/` MUST import `SchedulePlan`, `Zone` (scheduling entity), `Program` (scheduling entity), or `SchedulePlanLabel` from `domain.entities`.
- No CLI command MUST reference plan CRUD or zone CRUD use cases.
- No API route MUST expose Plan or Zone CRUD endpoints.
- The database tables `schedule_plans`, `zones`, `programs`, `schedule_plan_labels` MUST NOT exist after migration.

## Violation

- A production module imports any of the four retired entity classes.
- A CLI command or API route provides CRUD operations for retired entities.
- The four database tables exist after running all migrations.

## Derives From

LAW-CONTENT-AUTHORITY

## Required Tests

- `server/tests/contracts/scheduling/test_crud_island_retired_contract.py`

## Enforcement Evidence

TODO
