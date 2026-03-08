# Progression Cursor — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`, `LAW-IMMUTABILITY`

---

## Overview

A ProgressionCursor tracks which asset a schedule block will select next from its program's pool. Cursor state persists across scheduler restarts, recompilation, and multi-day schedules. Without persistent cursors, sequential and shuffle progressions produce non-deterministic content selection — violating `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION`.

This contract defines the cursor model, its lifecycle, and the behavioral guarantees for each progression mode.

---

## Domain Objects

### ScheduleBlockIdentity

A ScheduleBlockIdentity uniquely identifies a schedule block within a channel configuration. It is the key under which cursor state is stored and retrieved.

| Field | Type | Description |
|-------|------|-------------|
| `channel_id` | string | Channel owning this schedule block. |
| `schedule_layer` | string | Layer name (`all_day`, `weekday`, `thursday`, `dates:10-31`, etc.). |
| `start_time` | time string | Grid-aligned start time of the block. |
| `program_ref` | string | ProgramDefinition name referenced by the block. |

The tuple `(channel_id, schedule_layer, start_time, program_ref)` MUST be unique within a channel configuration. Two schedule blocks with the same identity are a validation fault.

### ProgressionCursor

A ProgressionCursor holds the state needed to deterministically select the next asset from a pool for a given schedule block.

| Field | Type | Description |
|-------|------|-------------|
| `identity` | ScheduleBlockIdentity | The schedule block this cursor belongs to. |
| `position` | non-negative integer | Index into the asset ordering (pool order or shuffle order). |
| `cycle` | non-negative integer | Number of complete passes through the pool. |
| `shuffle_seed` | integer or null | RNG seed for the current shuffle cycle. Null for non-shuffle modes. |

---

## Cursor Behavior by Progression Mode

### `sequential`

Assets are consumed in pool order. The cursor advances one position per execution.

- `position` starts at 0 on first use.
- Each program execution increments `position` by 1.
- When `position` reaches the pool size, it wraps to 0 and `cycle` increments by 1.
- Pool order is the canonical order defined by the pool's match criteria and sort rules.
- The cursor persists across days. It does not reset at broadcast day boundaries.

### `shuffle`

Assets are consumed in a shuffled order. The shuffled order is stable within a cycle.

- On cycle start (position 0, or after wrap), a shuffle order is generated from the pool using `shuffle_seed`.
- `shuffle_seed` is derived deterministically from the ScheduleBlockIdentity and the current `cycle` number.
- Each execution increments `position` by 1 within the shuffled order.
- When `position` reaches the pool size, it wraps to 0, `cycle` increments by 1, and a new shuffle order is generated with a new seed derived from the incremented cycle.
- The shuffled order MUST NOT be regenerated mid-cycle.
- Cooldown-excluded assets are skipped without advancing the cursor position. If all remaining assets in the cycle are cooldown-excluded, the cycle completes and a reshuffle occurs.

### `random`

An asset is chosen independently each execution. No persistent ordering exists.

- `position` is not meaningful for random progression.
- The RNG seed for each selection is derived deterministically from the ScheduleBlockIdentity and the execution timestamp, ensuring reproducibility when the global RNG seed is fixed.
- Cursor persistence is not required for random mode. A cursor MAY exist for audit purposes but MUST NOT influence selection.

---

## Persistence Rules

| Mode | Persistence Required | Persisted Fields |
|------|---------------------|-----------------|
| `sequential` | Yes | `position`, `cycle` |
| `shuffle` | Yes | `position`, `cycle`, `shuffle_seed` |
| `random` | No | None (selection derived from execution context) |

Cursor state MUST be persisted before the scheduling artifact that consumed it is published. A published ScheduleDay whose cursor advancement was not persisted is a derivation fault.

Cursor state MUST survive:
- Scheduler process restart
- Channel recompilation (unless the pool or program identity changes)
- Multi-day schedule generation

Cursor state MUST be reset when:
- The referenced pool's contents change (assets added or removed)
- The referenced ProgramDefinition is deleted or renamed
- An operator explicitly resets the cursor

---

## Cursor Initialization

When a schedule block is encountered for the first time (no persisted cursor exists):

- `position` = 0
- `cycle` = 0
- `shuffle_seed` = derived from ScheduleBlockIdentity and cycle 0

First-use initialization MUST be deterministic. Two schedulers with the same configuration and no prior state MUST produce the same initial cursor.

---

## Invariants

### INV-CURSOR-001 — Sequential cursor must exist before asset selection

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** A schedule block with `progression: sequential` MUST have a ProgressionCursor resolved (loaded or initialized) before asset selection begins. Asset selection without a cursor is a planning fault.

**Violation:** A sequential-mode schedule block that selects an asset without a resolved cursor.

---

### INV-CURSOR-002 — Cursor must advance exactly one position per execution

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Each program execution MUST advance the cursor `position` by exactly 1. No execution may skip positions, advance by more than 1, or leave the position unchanged.

**Violation:** A cursor whose `position` after an execution differs from `position_before + 1` (modulo pool size for wrap).

---

### INV-CURSOR-003 — Cursor must wrap at pool boundary

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** When `position` equals the pool size after advancement, the cursor MUST wrap to `position = 0` and increment `cycle` by 1. The wrap MUST be atomic — no intermediate state where position exceeds pool size is observable.

**Violation:** A cursor with `position >= pool_size` after advancement, or a cursor that wrapped without incrementing `cycle`.

---

### INV-CURSOR-004 — Shuffle order must remain stable within a cycle

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Within a single shuffle cycle (constant `cycle` value), the shuffled asset order MUST remain identical across all executions. The order is determined solely by `shuffle_seed` and pool contents. Regenerating the shuffle mid-cycle is prohibited.

**Violation:** Two executions within the same cycle that observe different shuffle orderings.

---

### INV-CURSOR-005 — Shuffle must reshuffle on cycle boundary

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** When a shuffle cursor wraps (position reaches pool size), a new cycle MUST begin with a new `shuffle_seed` derived from the ScheduleBlockIdentity and the new cycle number. The new seed MUST produce a different ordering from the previous cycle (except in degenerate cases where the pool has one element).

**Violation:** A shuffle cursor that begins a new cycle with the same ordering as the previous cycle (for pools with more than one element), or that retains the previous cycle's seed.

---

### INV-CURSOR-006 — Cursor state must persist across scheduler restarts

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

**Guarantee:** For sequential and shuffle modes, the cursor state (position, cycle, shuffle_seed) MUST be recoverable after a scheduler process restart. A restarted scheduler MUST resume from the persisted cursor position, not from position 0.

**Violation:** A scheduler restart that causes a sequential or shuffle cursor to reset to position 0 without an explicit operator reset.

---

### INV-CURSOR-007 — Random progression must not depend on cursor state

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** A schedule block with `progression: random` MUST select assets independently of any persisted cursor state. Selection is derived from the execution context (ScheduleBlockIdentity, execution timestamp, global RNG seed). A stale or absent cursor MUST NOT alter random selection behavior.

**Violation:** A random-mode schedule block whose selection changes based on the presence or absence of a persisted cursor.

---

### INV-CURSOR-008 — Cursor initialization must be deterministic

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** When no persisted cursor exists for a schedule block, initialization MUST produce `position = 0`, `cycle = 0`. Two schedulers with identical configuration and no prior state MUST produce identical initial cursors.

**Violation:** Non-deterministic cursor initialization, or initial position != 0, or initial cycle != 0.

---

## Required Tests

All tests live under:

```
pkg/core/tests/contracts/test_progression_cursor.py
```

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_sequential_cursor_required_before_selection` | INV-CURSOR-001 | Sequential block without cursor raises planning fault. |
| `test_sequential_cursor_loaded_before_selection` | INV-CURSOR-001 | Sequential block with loaded cursor proceeds. |
| `test_cursor_advances_one_position` | INV-CURSOR-002 | Single execution advances position from N to N+1. |
| `test_cursor_advances_once_per_execution` | INV-CURSOR-002 | Two executions advance position by exactly 2. |
| `test_cursor_does_not_skip` | INV-CURSOR-002 | Position after 3 executions from 0 is exactly 3. |
| `test_cursor_wraps_at_pool_size` | INV-CURSOR-003 | Position wraps to 0 when reaching pool size. |
| `test_cursor_increments_cycle_on_wrap` | INV-CURSOR-003 | Cycle increments by 1 on wrap. |
| `test_shuffle_order_stable_within_cycle` | INV-CURSOR-004 | Same seed and cycle produce same order across calls. |
| `test_shuffle_order_not_regenerated_mid_cycle` | INV-CURSOR-004 | Advancing within a cycle does not change order. |
| `test_shuffle_reshuffles_on_new_cycle` | INV-CURSOR-005 | New cycle produces different seed and ordering. |
| `test_shuffle_new_cycle_different_seed` | INV-CURSOR-005 | Consecutive cycle seeds differ. |
| `test_cursor_survives_restart` | INV-CURSOR-006 | Persisted cursor loaded after simulated restart. |
| `test_restart_does_not_reset_position` | INV-CURSOR-006 | Position after restart equals position before restart. |
| `test_random_ignores_cursor_state` | INV-CURSOR-007 | Random selection unchanged by cursor presence. |
| `test_random_selection_without_cursor` | INV-CURSOR-007 | Random selection succeeds with no persisted cursor. |
| `test_cursor_initializes_at_zero` | INV-CURSOR-008 | New cursor has position=0, cycle=0. |
| `test_cursor_initialization_deterministic` | INV-CURSOR-008 | Two independent initializations produce identical state. |
