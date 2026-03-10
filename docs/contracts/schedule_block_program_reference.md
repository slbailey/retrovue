# Schedule Block Program Reference — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Overview

Schedule blocks define when and how programs are deployed onto the channel timeline. ProgramDefinitions define how content is assembled from pools. These are separate concerns with a strict boundary.

A schedule block references a ProgramDefinition by name. The scheduler resolves that reference at compilation time. The schedule block MUST NOT embed any assembly logic — it owns timing and progression only.

This contract governs the reference relationship between schedule blocks and ProgramDefinitions, the resolution process, and the validation rules that enforce separation.

---

## Domain Objects

### ScheduleBlock

A ScheduleBlock is a time-positioned instruction within a schedule layer. It specifies when a program runs, how many grid slots it occupies, and how assets are selected from the program's pool.

### ProgramReference

A ProgramReference is the `program` field on a ScheduleBlock. It is a string matching a ProgramDefinition's `name` within the same channel configuration. The reference is resolved during schedule compilation.

### Grid Sizing Modes

A ProgramDefinition declares one of two mutually exclusive grid sizing modes:

- **`grid_blocks`** (fixed): The program occupies exactly this many grid slots per execution. Slots MUST be an exact multiple of `grid_blocks`.
- **`grid_blocks_max`** (dynamic): Each execution takes `ceil(actual_content_duration / grid_slot)` blocks, capped at `grid_blocks_max`. Slots is a budget consumed greedily — no modulus constraint. Remaining slots after the last full execution may be consumed by a final execution that bleeds past the budget (governed by `bleed`).

A ProgramDefinition MUST NOT declare both `grid_blocks > 0` and `grid_blocks_max`.

---

## ScheduleBlock Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start` | time string | Yes | Grid-aligned start time for this block. |
| `slots` | positive integer | Yes | Number of grid slots allocated. |
| `program` | string \| string[] | Yes | ProgramDefinition name reference, or list of names (one selected per execution via seeded RNG). |
| `progression` | `sequential` \| `random` \| `shuffle` | Yes | How assets are selected from the program's pool. |
| `cooldown_hours` | positive number | No | Minimum hours before an asset may repeat in this block. |

### Prohibited Fields

The following fields MUST NOT appear on a ScheduleBlock. They are assembly concerns owned exclusively by ProgramDefinition.

| Prohibited Field | Owner |
|------------------|-------|
| `pool` | ProgramDefinition |
| `fill_mode` | ProgramDefinition |
| `bleed` | ProgramDefinition |
| `intro` | ProgramDefinition |
| `outro` | ProgramDefinition |

---

## ProgramReference

The `program` field is either a non-empty string or a non-empty list of strings. Each string MUST match the `name` field of exactly one ProgramDefinition in the channel configuration.

When `program` is a list, the scheduler selects one ProgramDefinition per execution using the block's seeded RNG. All ProgramDefinitions referenced in the list MUST have the same `grid_blocks` value so that slot validation is uniform.

A ProgramReference is opaque — it carries no assembly semantics. The schedule block does not know or control what the referenced program does internally. It only knows the program's `grid_blocks` value for slot validation.

---

## Resolution Process

Resolution occurs during schedule compilation, before any assembly takes place.

1. The scheduler reads the schedule block's `program` field.
2. If `program` is a string, it is treated as a single-element list.
3. The scheduler looks up each ProgramDefinition by name in the channel's program namespace. If any name does not resolve, resolution fails with a validation fault.
4. All resolved ProgramDefinitions MUST have the same `grid_blocks` value. Mismatched `grid_blocks` is a validation fault.
5. The scheduler validates slot compatibility (`slots % grid_blocks == 0`).
6. For each execution, the scheduler selects one ProgramDefinition from the list using the block's seeded RNG. The selected program is passed to assembly.

Resolution MUST be deterministic. The same channel configuration and seed MUST produce the same resolution and selection results.

---

## Validation Rules

Validation occurs at schedule compilation time. All rules MUST be enforced before assembly begins.

1. The `program` field MUST be a non-empty string.
2. The `program` field MUST resolve to a defined ProgramDefinition.
3. The `slots` field MUST be an exact positive integer multiple of the resolved ProgramDefinition's `grid_blocks`.
4. The schedule block MUST NOT contain any prohibited assembly fields (`pool`, `fill_mode`, `bleed`, `intro`, `outro`).
5. The `progression` field MUST be one of: `sequential`, `random`, `shuffle`.

A violation of any rule is a planning fault. The schedule configuration MUST be rejected.

---

## Interaction With ProgramDefinition

The schedule block and ProgramDefinition have complementary, non-overlapping responsibilities.

| Concern | Owner |
|---------|-------|
| Start time | ScheduleBlock |
| Slot allocation | ScheduleBlock |
| Progression mode | ScheduleBlock |
| Cooldown rules | ScheduleBlock |
| Pool selection | ProgramDefinition |
| Fill mode | ProgramDefinition |
| Bleed behavior | ProgramDefinition |
| Intro / outro | ProgramDefinition |
| Grid blocks per execution | ProgramDefinition |

The schedule block determines *when* and *how many times* a program executes. The ProgramDefinition determines *what* is assembled and *how* it fills its grid target. Neither may encroach on the other's domain.

When `slots > program.grid_blocks`, the program executes `slots / program.grid_blocks` times. Each execution is independent — asset selection, intro/outro insertion, and break detection are performed per execution. The progression cursor advances once per execution.

---

## Invariants

### INV-SBLOCK-PROGRAM-001 — Schedule block must contain a program reference

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Every ScheduleBlock MUST contain a non-empty `program` field. The field is either a non-empty string or a non-empty list of strings, each referencing a ProgramDefinition by name. A schedule block with an empty, null, or absent program reference is invalid.

**Violation:** A ScheduleBlock where the `program` field is empty, null, absent, or an empty list. This is a planning fault.

---

### INV-SBLOCK-PROGRAM-002 — Program reference must resolve to a defined ProgramDefinition

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Every program name in the `program` field MUST resolve to a ProgramDefinition in the channel configuration. Resolution failure is a planning fault.

**Violation:** A ScheduleBlock whose `program` field contains any name that does not match a ProgramDefinition in the channel configuration.

---

### INV-SBLOCK-PROGRAM-003 — Slots must be a multiple of program grid_blocks

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** When the resolved ProgramDefinition uses fixed grid sizing (`grid_blocks`), the ScheduleBlock's `slots` MUST be an exact positive integer multiple of `grid_blocks`. This ensures the program executes a whole number of times within the allocated slots.

When the ProgramDefinition uses dynamic grid sizing (`grid_blocks_max`), `slots` is a budget consumed greedily. No modulus constraint applies. `slots` MUST be a positive integer.

**Violation:** A ScheduleBlock where `grid_blocks` is set and `slots % program.grid_blocks != 0`. This is a planning fault.

---

### INV-SBLOCK-PROGRAM-004 — Schedule block must not contain assembly fields

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** A ScheduleBlock MUST NOT contain any of the following fields: `pool`, `fill_mode`, `bleed`, `intro`, `outro`. These are assembly concerns owned exclusively by ProgramDefinition.

**Violation:** A ScheduleBlock that specifies any assembly-level field. This is a planning fault.

---

### INV-SBLOCK-PROGRAM-006 — Program list must have uniform grid_blocks

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** When the `program` field is a list, all referenced ProgramDefinitions MUST use the same grid sizing mode and value. If all use `grid_blocks`, the values MUST be identical. If all use `grid_blocks_max`, the values MUST be identical. Mixing `grid_blocks` and `grid_blocks_max` within a program list is not permitted.

**Violation:** A ScheduleBlock whose `program` list references ProgramDefinitions with differing grid sizing values, or that mixes `grid_blocks` and `grid_blocks_max` programs. This is a planning fault.

---

### INV-SBLOCK-PROGRAM-005 — Progression mode must be valid

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** A ScheduleBlock's `progression` field MUST be exactly one of: `sequential`, `random`, `shuffle`. No other values are permitted.

**Violation:** A ScheduleBlock with a `progression` value not in the allowed set. This is a planning fault.

---

## Required Tests

All tests live under:

```
pkg/core/tests/contracts/test_schedule_block_program_reference.py
```

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_empty_program_reference_rejected` | INV-SBLOCK-PROGRAM-001 | Schedule block with empty `program` field rejected. |
| `test_missing_program_reference_rejected` | INV-SBLOCK-PROGRAM-001 | Schedule block with null `program` field rejected. |
| `test_valid_program_reference_accepted` | INV-SBLOCK-PROGRAM-001 | Schedule block with valid non-empty `program` field accepted. |
| `test_undefined_program_rejected` | INV-SBLOCK-PROGRAM-002 | Program name not matching any ProgramDefinition rejected. |
| `test_defined_program_resolves` | INV-SBLOCK-PROGRAM-002 | Program name matching a ProgramDefinition resolves without error. |
| `test_slots_not_multiple_rejected` | INV-SBLOCK-PROGRAM-003 | `slots=5`, `grid_blocks=2` rejected. |
| `test_slots_exact_multiple_accepted` | INV-SBLOCK-PROGRAM-003 | `slots=4`, `grid_blocks=2` accepted. |
| `test_slots_equal_grid_blocks_accepted` | INV-SBLOCK-PROGRAM-003 | `slots=2`, `grid_blocks=2` accepted (single execution). |
| `test_inline_pool_rejected` | INV-SBLOCK-PROGRAM-004 | Schedule block with `pool` field rejected. |
| `test_inline_fill_mode_rejected` | INV-SBLOCK-PROGRAM-004 | Schedule block with `fill_mode` field rejected. |
| `test_inline_bleed_rejected` | INV-SBLOCK-PROGRAM-004 | Schedule block with `bleed` field rejected. |
| `test_inline_intro_rejected` | INV-SBLOCK-PROGRAM-004 | Schedule block with `intro` field rejected. |
| `test_inline_outro_rejected` | INV-SBLOCK-PROGRAM-004 | Schedule block with `outro` field rejected. |
| `test_valid_progression_sequential` | INV-SBLOCK-PROGRAM-005 | `progression: sequential` accepted. |
| `test_valid_progression_random` | INV-SBLOCK-PROGRAM-005 | `progression: random` accepted. |
| `test_valid_progression_shuffle` | INV-SBLOCK-PROGRAM-005 | `progression: shuffle` accepted. |
| `test_invalid_progression_rejected` | INV-SBLOCK-PROGRAM-005 | `progression: alphabetical` rejected. |
| `test_program_list_accepted` | INV-SBLOCK-PROGRAM-001 | `program: [prog_a, prog_b]` accepted when both programs are defined. |
| `test_program_list_empty_rejected` | INV-SBLOCK-PROGRAM-001 | `program: []` rejected as empty. |
| `test_program_list_undefined_member_rejected` | INV-SBLOCK-PROGRAM-002 | One member of the list not matching a ProgramDefinition rejected. |
| `test_program_list_mismatched_grid_blocks_rejected` | INV-SBLOCK-PROGRAM-006 | Programs in list with different `grid_blocks` rejected. |
| `test_program_list_selects_per_execution` | INV-SBLOCK-PROGRAM-002 | Each execution in a multi-execution block selects from the list. |
| `test_program_list_selection_is_seeded` | INV-SBLOCK-PROGRAM-002 | Same seed produces same program selections across executions. |
