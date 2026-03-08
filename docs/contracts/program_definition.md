# ProgramDefinition — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-ELIGIBILITY`, `LAW-DERIVATION`

---

## Overview

A ProgramDefinition is the editorial unit that a schedule block references. It describes how content is assembled from a pool into a grid-aligned block of programming. ProgramDefinitions are reusable, named, declarative recipes. They define assembly rules — not timing, not progression, not specific asset selections.

Schedule blocks reference ProgramDefinitions. ProgramDefinitions reference pools. This separation ensures that editorial intent (what airs) is decoupled from scheduling mechanics (when and in what order).

---

## Domain Object

ProgramDefinition is a first-class domain entity owned by Core. It exists within the SchedulePlan namespace and is resolved during schedule compilation.

A ProgramDefinition MUST be defined before any schedule block may reference it. A ProgramDefinition that is referenced by at least one schedule block MUST NOT be deleted or redefined in a way that invalidates the referencing block.

---

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier within the channel configuration. |
| `pool` | pool reference | Yes | The content pool from which assets are drawn. |
| `grid_blocks` | positive integer | Yes | Number of grid slots this program targets per execution. |
| `fill_mode` | `single` \| `accumulate` | Yes | How assets are assembled to fill the grid target. |
| `bleed` | boolean | Yes | Whether the program may overrun its grid allocation. |
| `intro` | asset reference | No | Segment prepended before content. |
| `outro` | asset reference | No | Segment appended after content. |

### Field Constraints

- `name` MUST be non-empty and unique within the channel's program namespace.
- `pool` MUST reference a defined pool. A ProgramDefinition referencing an undefined pool is invalid.
- `grid_blocks` MUST be a positive integer (>= 1).
- `fill_mode` MUST be exactly `single` or `accumulate`. No other values are permitted.
- `bleed` MUST be explicitly set. There is no default.
- `intro` and `outro`, when present, MUST reference assets that satisfy `LAW-ELIGIBILITY` at assembly time.

---

## Assembly Model

When a schedule block executes, it resolves its referenced ProgramDefinition and assembles content according to the program's rules. Assembly is the process of selecting assets from the pool and arranging them to satisfy the program's `grid_blocks` target.

Assembly produces an ordered list of content segments. The intro segment (if defined) is prepended. The outro segment (if defined) is appended. Intro and outro durations are included in the program's total runtime for grid and bleed calculations.

Assembly MUST NOT select assets that violate `LAW-ELIGIBILITY`. Assembly MUST NOT reinterpret the pool reference — the pool is the sole source of candidate assets.

The assembled output is passed to break detection. Assembly does not place breaks; it produces content and identifies boundaries where breaks may occur.

---

## Fill Modes

### `single`

A single asset is selected from the pool per program execution.

- Exactly one asset is drawn from the pool.
- If `bleed: false`, the asset's total runtime (including intro/outro) MUST NOT exceed `grid_blocks * grid_minutes`. An asset that exceeds the grid allocation MUST be rejected. The next eligible asset is tried.
- If `bleed: true`, the asset may exceed the grid allocation. The overrun is absorbed by the schedule — subsequent blocks start after the bleed completes.
- No break opportunities exist within the single asset's content body (break detection uses chapter markers or algorithmic placement).

### `accumulate`

Assets are appended sequentially until the program's grid target is reached or slightly exceeded.

- Assets are drawn from the pool one at a time, in the order determined by the schedule block's progression mode.
- Each asset is appended to the running total.
- Accumulation stops when the running total meets or exceeds `grid_blocks * grid_minutes`.
- The seam between consecutive accumulated assets is a natural break opportunity.
- If `bleed: false`, the accumulated total MUST NOT exceed the grid allocation. If the last asset would cause the total to exceed the grid allocation, it MUST NOT be added. Remaining time is absorbed by break padding.
- If `bleed: true`, the accumulated total may slightly exceed the grid allocation due to the final asset's length. The overrun is absorbed by the schedule.
- Intro is prepended once at the start of the accumulated block. Outro is appended once at the end.

---

## Grid Behavior

A ProgramDefinition's `grid_blocks` defines the number of grid slots the program targets per execution. Grid behavior is governed by three invariants.

When a schedule block allocates more slots than the program's `grid_blocks`, the program executes repeatedly. The schedule block's `slots` MUST be an exact integer multiple of the program's `grid_blocks`. A non-multiple is a planning fault.

Each execution is independent: asset selection, intro/outro insertion, and break detection are performed per execution.

```
executions = schedule_block.slots / program.grid_blocks
```

Each execution targets exactly `grid_blocks * grid_minutes` of wall-clock time (before bleed).

---

## Bleed Rules

Bleed determines whether a program's actual runtime may exceed its grid allocation.

- `bleed: true` — The program's assembled content may exceed `grid_blocks * grid_minutes`. The overrun shifts all subsequent schedule blocks forward by the bleed amount. No content is truncated.
- `bleed: false` — The program's assembled content MUST NOT exceed `grid_blocks * grid_minutes`. Content that would cause an overrun MUST be rejected during assembly (`single` mode) or excluded from accumulation (`accumulate` mode). Remaining time within the grid allocation is filled by break budget.

Bleed is a property of the ProgramDefinition, not of the asset, pool, or schedule block. The schedule block does not override bleed.

A program with `bleed: true` and `fill_mode: accumulate` — the final accumulated asset may cause the total to exceed the grid. This is the only permitted overrun path for accumulate mode.

---

## Program Identity

A ProgramDefinition is identified by its `name` within the channel configuration. The name is the stable key used by schedule blocks, derivation tracing, and debugging.

Two ProgramDefinitions with the same name in the same channel configuration is a validation error. ProgramDefinition names MUST NOT collide with pool names within the same channel configuration.

---

## Interaction With Schedule Blocks

Schedule blocks reference ProgramDefinitions by name. The schedule block provides:

- `start` — when the program begins (grid-aligned, per `LAW-GRID`)
- `slots` — total grid slots allocated
- `progression` — how assets are selected from the pool (`sequential`, `random`, `shuffle`)
- `cooldown_hours` — optional cooldown constraint on asset reuse

The ProgramDefinition provides:

- `pool` — which assets are candidates
- `grid_blocks` — per-execution grid target
- `fill_mode` — how assets fill the target
- `bleed` — whether overrun is permitted
- `intro` / `outro` — wrapper segments

The schedule block owns timing and progression. The ProgramDefinition owns assembly and fill behavior. Neither may encroach on the other's domain.

A schedule block MUST NOT embed assembly logic (fill mode, bleed, pool selection). A ProgramDefinition MUST NOT encode timing, progression, or cooldown rules.

---

## Invariants

### INV-PROGRAM-GRID-001 — Schedule block slots must be a multiple of program grid_blocks

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** A schedule block's `slots` MUST be an exact positive integer multiple of its referenced ProgramDefinition's `grid_blocks`.

**Violation:** A schedule block where `slots % program.grid_blocks != 0`. This is a planning fault. The schedule configuration MUST be rejected.

---

### INV-PROGRAM-FILL-001 — Single fill mode selects exactly one asset per execution

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** When `fill_mode` is `single`, each program execution MUST select exactly one asset from the pool. No execution may select zero or more than one content asset (intro/outro are not counted as content assets).

**Violation:** A `single`-mode program execution that produces zero content assets or more than one content asset.

---

### INV-PROGRAM-FILL-002 — Accumulate fill mode stops at or just past grid target

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** When `fill_mode` is `accumulate`, assets MUST be appended until the running total meets or first exceeds `grid_blocks * grid_minutes`. Accumulation MUST NOT continue past the first asset that causes the total to meet or exceed the target.

**Violation:** An `accumulate`-mode program execution that adds assets beyond the first one to meet the target, or that stops accumulation before the target is reachable with available assets.

---

### INV-PROGRAM-BLEED-001 — Non-bleeding programs must not exceed grid allocation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

**Guarantee:** A ProgramDefinition with `bleed: false` MUST NOT produce assembled content whose total runtime (including intro/outro) exceeds `grid_blocks * grid_minutes`.

**Violation:** A non-bleeding program execution whose total assembled runtime exceeds its grid allocation. This is an assembly fault.

---

### INV-PROGRAM-BLEED-002 — Bleeding programs may exceed grid allocation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** A ProgramDefinition with `bleed: true` MUST permit assembled content whose total runtime (including intro/outro) exceeds `grid_blocks * grid_minutes`. No content is truncated. The overrun amount is the difference between the assembled runtime and the grid allocation.

**Violation:** A bleeding program execution that truncates or rejects content solely because it exceeds the grid allocation.

---

### INV-PROGRAM-BLEED-003 — Bleed seam continuity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

**Guarantee:** When a program with `bleed: true` overruns its grid allocation, the next schedule block's actual start time MUST equal the bleeding program's actual end time. No gap or overlap is permitted at the bleed seam.

**Violation:** A gap or overlap between a bleeding program's end and the next block's actual start.

---

### INV-PROGRAM-POOL-001 — Program pool reference must resolve to a defined pool

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** A ProgramDefinition's `pool` field MUST reference a pool that exists in the channel configuration. Pool resolution is validated at configuration load time.

**Violation:** A ProgramDefinition whose `pool` reference does not resolve to a defined pool. This is a validation fault.

---

### INV-PROGRAM-POOL-002 — Assembly must fail when resolved pool has zero eligible assets

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** When a resolved pool contains zero assets satisfying `LAW-ELIGIBILITY` at assembly time, assembly MUST raise an assembly fault. Assembly MUST NOT produce an empty program or silently skip the block.

**Violation:** A program execution that produces zero content segments without raising an assembly fault, or that silently omits the block from the schedule.

---

### INV-PROGRAM-IDENTITY-001 — Program names must be unique within channel configuration

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** Each ProgramDefinition `name` MUST be unique within the channel configuration. No two ProgramDefinitions may share the same name.

**Violation:** A channel configuration containing two or more ProgramDefinitions with identical `name` values. This is a validation fault.

---

### INV-PROGRAM-INTRO-OUTRO-001 — Intro and outro durations are included in runtime calculations

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

**Guarantee:** When a ProgramDefinition specifies `intro` and/or `outro`, their durations MUST be included in the program's total runtime for all grid, bleed, and break budget calculations.

**Violation:** A program execution that excludes intro or outro duration from its total runtime, causing incorrect grid fit or break budget computation.

---

### INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 — Assembly must only select eligible assets

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** Program assembly MUST NOT select any asset that does not satisfy `LAW-ELIGIBILITY` (`state=ready`, `approved_for_broadcast=true`). Intro and outro assets MUST also satisfy eligibility.

**Violation:** Any assembled program output containing a reference to an ineligible asset.

---

### INV-PROGRAM-SEPARATION-001 — Schedule blocks must not embed assembly logic

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Schedule blocks MUST reference a ProgramDefinition by name. Schedule blocks MUST NOT contain inline fill_mode, bleed, pool, intro, or outro fields. All assembly logic MUST reside in the ProgramDefinition.

**Violation:** A schedule block that specifies assembly-level fields (fill_mode, bleed, pool, intro, outro) instead of referencing a ProgramDefinition.

---

## Required Tests

All tests live under:

```
pkg/core/tests/contracts/test_program_definition.py
```

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_schedule_slots_must_be_multiple_of_grid_blocks` | INV-PROGRAM-GRID-001 | Reject schedule block where `slots % grid_blocks != 0`. |
| `test_schedule_slots_exact_multiple_accepted` | INV-PROGRAM-GRID-001 | Accept schedule block where `slots` is exact multiple. |
| `test_single_fill_selects_one_asset` | INV-PROGRAM-FILL-001 | Single-mode execution produces exactly one content asset. |
| `test_single_fill_rejects_zero_assets` | INV-PROGRAM-FILL-001 | Single-mode with empty pool raises assembly fault. |
| `test_accumulate_stops_at_grid_target` | INV-PROGRAM-FILL-002 | Accumulate-mode stops at first asset meeting target. |
| `test_accumulate_does_not_overshoot` | INV-PROGRAM-FILL-002 | Accumulate-mode does not add assets past the crossing point. |
| `test_no_bleed_rejects_overlong_single` | INV-PROGRAM-BLEED-001 | `bleed: false` + `single` rejects asset exceeding grid. |
| `test_no_bleed_accumulate_excludes_overflow` | INV-PROGRAM-BLEED-001 | `bleed: false` + `accumulate` excludes asset that would overflow. |
| `test_bleed_allows_overrun` | INV-PROGRAM-BLEED-002 | `bleed: true` permits runtime exceeding grid allocation. |
| `test_bleed_shifts_next_block_start` | INV-PROGRAM-BLEED-003 | Next block starts at bleeding program's actual end. |
| `test_bleed_seam_no_gap_no_overlap` | INV-PROGRAM-BLEED-003 | No temporal gap or overlap at bleed boundary. |
| `test_undefined_pool_rejected` | INV-PROGRAM-POOL-001 | Program referencing nonexistent pool fails validation. |
| `test_empty_pool_raises_assembly_fault` | INV-PROGRAM-POOL-002 | Pool with zero eligible assets raises assembly fault. |
| `test_duplicate_program_name_rejected` | INV-PROGRAM-IDENTITY-001 | Two programs with same name fail validation. |
| `test_intro_duration_included_in_grid_calc` | INV-PROGRAM-INTRO-OUTRO-001 | Intro duration counts toward grid fit. |
| `test_outro_duration_included_in_grid_calc` | INV-PROGRAM-INTRO-OUTRO-001 | Outro duration counts toward grid fit. |
| `test_intro_outro_included_in_bleed_calc` | INV-PROGRAM-INTRO-OUTRO-001 | Intro + outro included in bleed threshold. |
| `test_assembly_rejects_ineligible_asset` | INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 | Asset with `state != ready` excluded from assembly. |
| `test_assembly_rejects_unapproved_asset` | INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 | Asset with `approved_for_broadcast=false` excluded. |
| `test_ineligible_intro_rejected` | INV-PROGRAM-ASSEMBLY-ELIGIBLE-001 | Ineligible intro asset fails assembly. |
| `test_schedule_block_must_reference_program` | INV-PROGRAM-SEPARATION-001 | Schedule block without program reference rejected. |
| `test_schedule_block_rejects_inline_fill_mode` | INV-PROGRAM-SEPARATION-001 | Schedule block with inline `fill_mode` rejected. |
| `test_schedule_block_rejects_inline_bleed` | INV-PROGRAM-SEPARATION-001 | Schedule block with inline `bleed` rejected. |
