# Scheduler Cursor Integration — Domain Contract

**Status: RETIRED**

Superseded by `docs/contracts/episode_progression.md`.

The 6-step compilation protocol (load → select → advance → persist → publish) is superseded by pure-function episode selection via calendar-based occurrence counting. INV-SCHED-CURSOR-001 through INV-SCHED-CURSOR-005 are retired.

Cursor integration remains relevant for **shuffle** progression only, which is governed by `docs/contracts/progression_cursor.md`.

See: [episode_progression.md](episode_progression.md) § Retired Contracts

---

## Historical Content (retained for reference)

The following content describes the retired sequential cursor protocol.

---

~~Status: Contract~~
~~Authority Level: Planning~~
~~Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`, `LAW-IMMUTABILITY`~~

---

## Overview (RETIRED)

The scheduler compiler must use ProgressionCursors — not in-memory counters — to select assets during schedule compilation. Cursor state is the authoritative record of where a schedule block is in its progression sequence. This contract defines the exact interaction protocol between the scheduler compiler and the cursor system.

In-memory progression counters (`sequential_counters: dict[str, int]`) violate `LAW-DERIVATION` because they are lost on restart, producing different asset selections for the same schedule block across compilations. The cursor system replaces them with persistent, deterministic state.

---

## Scheduler Compilation Protocol

For each program execution within a schedule block, the scheduler MUST perform the following steps in order. No step may be reordered or omitted.

```
1. Resolve ScheduleBlockIdentity
2. Load cursor state (or initialize if absent)
3. Select asset using cursor and progression mode
4. Advance cursor
5. Persist cursor state
6. Publish schedule artifact
```

### Step 1 — Resolve ScheduleBlockIdentity

The scheduler constructs a ScheduleBlockIdentity from the schedule block's position in the configuration:

```
(channel_id, schedule_layer, start_time, program_ref)
```

This identity is deterministic and stable across compilations for the same channel configuration.

### Step 2 — Load Cursor State

The scheduler loads the ProgressionCursor for the resolved identity from the cursor store.

- If a cursor exists, it is used as-is.
- If no cursor exists, the scheduler initializes a new cursor at `position=0`, `cycle=0` per `INV-CURSOR-008`.
- For `random` progression, this step MAY be skipped. Random selection does not depend on cursor state per `INV-CURSOR-007`.

### Step 3 — Select Asset

The scheduler uses the loaded cursor and the progression mode to determine which asset to select from the pool.

- `sequential`: asset at `pool_assets[cursor.position]`.
- `shuffle`: asset at `get_shuffle_order(pool_assets, cursor.shuffle_seed)[cursor.position]`.
- `random`: asset from `select_random_asset(identity, pool_assets, execution_ts_ms)`.

The selected asset MUST satisfy `LAW-ELIGIBILITY`. If the asset at the cursor position is ineligible, the scheduler MUST skip it and advance the cursor without producing a segment, then retry from Step 3.

### Step 4 — Advance Cursor

After selection, the cursor position advances by 1. If position reaches the pool size, the cursor wraps to 0 and cycle increments. For shuffle mode, a new shuffle seed is derived on wrap.

For `random` progression, no cursor advancement occurs.

### Step 5 — Persist Cursor State

The scheduler MUST persist the advanced cursor state to the cursor store. Persistence MUST complete successfully before Step 6.

- For `sequential`: position and cycle are persisted.
- For `shuffle`: position, cycle, and shuffle_seed are persisted.
- For `random`: no persistence required.

If persistence fails, the scheduler MUST NOT publish the artifact. This is a compilation fault.

### Step 6 — Publish Schedule Artifact

The scheduler publishes the schedule artifact (ScheduleDay, ScheduleItem, etc.) containing the cursor-selected asset. The artifact is now immutable per `LAW-IMMUTABILITY`.

The artifact MUST reference the asset selected in Step 3. No post-publication substitution of the asset is permitted without an explicit operator override.

---

## Repeat Execution

When a schedule block's `slots > program.grid_blocks`, the program executes multiple times. Each execution is an independent pass through Steps 1–6. The cursor advances once per execution. The ScheduleBlockIdentity remains the same across all executions within a single block — the cursor's position differentiates each execution.

```
slots=6, grid_blocks=2 → 3 executions
  execution 1: load cursor(pos=0), select, advance(pos=1), persist, publish
  execution 2: load cursor(pos=1), select, advance(pos=2), persist, publish
  execution 3: load cursor(pos=2), select, advance(pos=3), persist, publish
```

---

## Prohibited Patterns

The following patterns are prohibited in the scheduler compiler:

1. **In-memory counters.** `sequential_counters: dict[str, int]` or equivalent ephemeral state MUST NOT be used for progression tracking. All progression state MUST flow through the cursor system.

2. **Counter initialization from zero on each compilation.** The scheduler MUST NOT assume position=0 if a persisted cursor exists. It MUST load before selecting.

3. **Deferred persistence.** Cursor state MUST NOT be batched and persisted after all artifacts are published. Each cursor advancement MUST be persisted before its consuming artifact is published.

4. **Cursor bypass.** The scheduler MUST NOT select assets through any path that does not involve the cursor system for sequential and shuffle modes.

---

## Failure Conditions

The scheduler MUST fail compilation (not silently degrade) when:

| Condition | Fault Type |
|-----------|-----------|
| Sequential/shuffle block has no cursor and initialization fails | Planning fault |
| Cursor store is unreachable or write fails | Compilation fault |
| Pool size is zero after eligibility filtering | Assembly fault |
| Persisted cursor position exceeds current pool size | Cursor invalidation — reset to position=0, cycle=0, log warning |

Cursor invalidation (position exceeds pool size) occurs when the pool's contents have changed since the cursor was last persisted. The scheduler MUST reset the cursor and log the invalidation. This is not a fatal error — it is a recovery path.

---

## Invariants

### INV-SCHED-CURSOR-001 — Cursor must be loaded before asset selection

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** For sequential and shuffle progression, the scheduler MUST load (or initialize) a ProgressionCursor before selecting any asset. Asset selection without a resolved cursor is a planning fault.

**Violation:** A schedule compilation that selects an asset for a sequential or shuffle block without first loading or initializing a cursor.

---

### INV-SCHED-CURSOR-002 — Cursor must be persisted after advancement

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-IMMUTABILITY`

**Guarantee:** After each cursor advancement, the scheduler MUST persist the updated cursor state to the cursor store. The persist operation MUST succeed before the schedule artifact is published.

**Violation:** A cursor that was advanced in memory but not persisted to the store, or a persist that occurs after the artifact is already published.

---

### INV-SCHED-CURSOR-003 — Scheduler must not use in-memory progression counters

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** The scheduler compiler MUST NOT maintain ephemeral in-memory progression counters (`sequential_counters`, index variables, or equivalent). All progression state for sequential and shuffle modes MUST be sourced from and written to the cursor store.

**Violation:** Any code path in the scheduler compiler that tracks progression position in a local variable or dict rather than through the ProgressionCursor system.

---

### INV-SCHED-CURSOR-004 — Schedule artifact must reflect cursor-selected asset

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** The asset referenced in a published schedule artifact MUST be the asset that was selected by the cursor at the cursor's position at the time of selection. No post-selection substitution is permitted without an explicit operator override.

**Violation:** A schedule artifact whose asset_id does not match the asset the cursor selected, absent a recorded operator override.

---

### INV-SCHED-CURSOR-005 — Cursor persistence must precede artifact publication

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

**Guarantee:** The cursor store MUST contain the advanced cursor state before the schedule artifact that consumed it is published. If cursor persistence fails, the artifact MUST NOT be published.

**Violation:** A published schedule artifact whose cursor advancement was not persisted at the time of publication, or an artifact published after a cursor persistence failure.

---

## Required Tests

All tests live under:

```
pkg/core/tests/contracts/test_scheduler_cursor_integration.py
```

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_cursor_loaded_before_sequential_selection` | INV-SCHED-CURSOR-001 | Sequential compilation loads cursor before selecting asset. |
| `test_cursor_loaded_before_shuffle_selection` | INV-SCHED-CURSOR-001 | Shuffle compilation loads cursor before selecting asset. |
| `test_cursor_initialized_when_absent` | INV-SCHED-CURSOR-001 | First compilation for a block initializes cursor at position=0. |
| `test_cursor_persisted_after_advance` | INV-SCHED-CURSOR-002 | Cursor store contains updated position after compilation. |
| `test_cursor_persisted_before_artifact_exists` | INV-SCHED-CURSOR-002 | Cursor is in store before artifact is returned. |
| `test_persist_failure_blocks_artifact` | INV-SCHED-CURSOR-002 | Cursor store write failure prevents artifact publication. |
| `test_no_in_memory_counters` | INV-SCHED-CURSOR-003 | Compilation uses cursor store, not a local dict counter. |
| `test_restart_continues_from_persisted_position` | INV-SCHED-CURSOR-003 | After simulated restart, compilation resumes from stored position. |
| `test_artifact_contains_cursor_selected_asset` | INV-SCHED-CURSOR-004 | Published artifact's asset_id matches cursor-selected asset. |
| `test_multi_execution_artifacts_match_cursor_sequence` | INV-SCHED-CURSOR-004 | Repeated executions produce artifacts matching sequential cursor positions. |
| `test_persist_precedes_publish` | INV-SCHED-CURSOR-005 | Cursor store write happens before artifact is emitted. |
| `test_failed_persist_no_artifact` | INV-SCHED-CURSOR-005 | Store write failure means zero artifacts produced. |
