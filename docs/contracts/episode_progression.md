# Episode Progression — Canonical Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`, `LAW-IMMUTABILITY`

---

## Overview

Episode progression governs which episode airs for a given program placement on a given broadcast day. This is the sole contract for sequential episode selection in RetroVue. All sequential episode identity is derived from the model defined here.

This contract replaces:

- `pkg/core/docs/contracts/runtime/INV-SERIAL-EPISODE-PROGRESSION.md`
- `docs/contracts/progression_cursor.md` (sequential sections)
- `docs/contracts/scheduler_cursor_integration.md`
- `docs/contracts/invariants/core/runtime/INV-SCHEDULE-SEQUENTIAL-ADVANCE-001.md`

Shuffle and random asset selection are not episode progression. They are governed by the Rotation and Asset Selection domain.

### Scope

These invariants govern the episode selection function: given a run record, a target date, and a catalog size, which episode index is returned. They do NOT govern scheduling topology, compilation pipeline ordering, or where in the system the function is called. The schedule compiler, program assembly, and EPG layers are all consumers of this function — enforcement lives in the function itself, not in its call sites.

---

## Terminology

### Progression Run

A persistent record binding a recurring program placement to an anchor point, a day-of-week pattern, and an exhaustion policy. Episode selection is a pure computation over the run record, the target broadcast day, and the episode catalog size. No mutable cursor, counter, or runtime state participates in the computation.

### Run Identity

A stable string identifier for a Progression Run. Either assigned explicitly by the operator (`run_id` in the DSL) or derived deterministically from the schedule block's position in the channel configuration.

### Derived Placement Identity

When no explicit `run_id` is provided, the identity is derived as:

    (channel_id, schedule_layer, start_time, program_ref)

This tuple is serialized into a string and used as the run identity. Two schedule blocks with identical derived identity share progression. Two blocks differing in any component have independent progression.

### Anchor

A `(date, episode_index)` pair marking the origin of a Progression Run. The anchor date is the earliest broadcast day that matches the run's day-of-week pattern. The anchor episode airs on the anchor date. All subsequent episode indices are offsets from this point.

### Occurrence

A calendar date where the run's day-of-week pattern matches. A date is an occurrence if and only if the day-of-week bit for that date is set in `placement_days`.

### Occurrence Count

The number of occurrences in the half-open interval `[anchor_date, target_date)`.

    occurrence_count = count of dates d in [anchor_date, target_date)
                       where d.weekday() matches placement_days

The anchor date yields occurrence_count = 0. The next matching day yields 1.

### Episode List

An ordered sequence of episodes belonging to the content source. Ordering is determined by the content catalog (season number, episode number). The list is flat — season boundaries are positions within the list, not structural divisions.

### Exhaustion Policy

Defines behavior when the computed episode index exceeds the episode list length:

- **wrap** — modulo back to the beginning.
- **hold_last** — repeat the final episode indefinitely.
- **stop** — emit no content (filler) after the last episode.

---

## Progression Run Model

### State

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | string | Stable identifier. Explicit or derived. |
| `channel_id` | string | Channel this run belongs to. |
| `content_source_id` | string | Pool or program providing episodes. |
| `anchor_date` | date | Calendar origin. MUST match `placement_days`. |
| `anchor_episode_index` | int | Episode index on anchor date. Non-negative. |
| `placement_days` | int | 7-bit DOW bitmask. Bit 0 = Monday, bit 6 = Sunday. Range: 1–127. |
| `exhaustion_policy` | string | `wrap`, `hold_last`, or `stop`. |

### Episode Selection

Given a Progression Run, a target broadcast day, and the emission context:

    occurrence_count = count_occurrences(
        run.anchor_date,
        target_broadcast_day,
        run.placement_days,
    )

    raw_index = run.anchor_episode_index
              + (occurrence_count × emissions_per_occurrence)
              + prior_same_day_emissions
              + execution_index

    episode_index = apply_exhaustion_policy(
        raw_index,
        episode_count,
        run.exhaustion_policy,
    )

Where:

- **`emissions_per_occurrence`**: Total number of program executions across ALL schedule blocks sharing this `run_id` on a single matching day. Computed by pre-scanning the resolved block list.
- **`prior_same_day_emissions`**: Cumulative executions from earlier blocks (in schedule order) sharing this `run_id` on the SAME broadcast day. Zero for the first block.
- **`execution_index`**: This block's execution offset within its own slot allocation (`0..slots/grid_blocks - 1`).

For a single block with `slots=1`, the formula reduces to `anchor_episode_index + occurrence_count` (the single-emission case).

This computation is the sole authority for sequential episode identity.

### Occurrence Counting

Occurrences are counted in the half-open interval `[anchor_date, target_date)`.

    count_occurrences(anchor, target, mask) =
        number of dates d where anchor <= d < target
        and d.weekday() bit is set in mask

The computation MUST use arithmetic (full weeks × bits-per-week plus partial-week remainder). The computation MUST be bounded regardless of the distance between anchor and target.

### Exhaustion Policies

**wrap:**

    effective_index = raw_index % episode_count

**hold_last:**

    effective_index = min(raw_index, episode_count - 1)

**stop:**

    if raw_index >= episode_count: return FILLER
    effective_index = raw_index

---

## Identity Rules

### Explicit Identity

When a DSL schedule block declares `run_id`, that string is the run identity. Two blocks with the same `run_id` share a single Progression Run and therefore share episode progression.

### Derived Identity

When `run_id` is omitted, the identity is derived as:

    f"{channel_id}:{schedule_layer}:{start_time}:{program_ref}"

This derivation is deterministic. The same DSL produces the same derived identity.

### Identity Stability

A Progression Run's identity MUST NOT change unless the operator explicitly changes the `run_id` or modifies a component of the derived identity (schedule layer, start time, program reference). Process restarts, schedule recompilation, and plan transitions MUST NOT alter the identity.

### Shared Progression

Two schedule blocks sharing a `run_id` MUST resolve the same episode for the same broadcast day. The `placement_days` and `exhaustion_policy` on a shared run are defined by the run record, not by individual schedule blocks. If two blocks referencing the same `run_id` appear in different schedule layers with different day patterns, the run record's `placement_days` governs.

---

## Anchor Rules

### Anchor Determination

When a Progression Run is created for the first time:

1. The `anchor_date` MUST be the earliest broadcast day being compiled that matches the `placement_days` pattern.
2. The `anchor_episode_index` MUST be 0 unless explicitly set by the operator.
3. The `exhaustion_policy` MUST be set from the DSL `exhaustion` field, defaulting to `wrap`.

### Anchor Stability

Once a Progression Run is created, its `anchor_date` and `anchor_episode_index` MUST NOT change unless the operator explicitly modifies the run record. Schedule recompilation, plan transitions, and process restarts MUST NOT alter the anchor.

### Anchor Validity

The anchor date's day-of-week MUST have its bit set in the run's `placement_days` bitmask.

    assert (1 << anchor_date.weekday()) & placement_days != 0

An anchor that does not match the placement pattern is a validation fault.

### Anchor Independence from Compile Time

The anchor date MUST NOT depend on when the scheduler first runs. It is determined by the channel's schedule configuration (earliest matching broadcast day), not by the wall clock at compilation time. Two schedulers compiling the same channel configuration at different times MUST produce the same anchor date.

---

## Multi-Execution Sequencing

When a schedule block produces multiple program executions:

    executions = slots // program.grid_blocks

Each execution selects an episode at a consecutive index within the block's allocation:

    execution_0: raw_index with execution_index=0
    execution_1: raw_index with execution_index=1
    execution_2: raw_index with execution_index=2
    ...

### Stride Across Days

The total daily stride for a run_id equals `emissions_per_occurrence` — the sum of all executions across all blocks sharing that run_id on a matching day. The next matching day's base index advances by exactly `emissions_per_occurrence`, ensuring zero overlap between days.

Example: Two blocks sharing `run_id`, each with `slots=3`:
- `emissions_per_occurrence = 6`
- Day 1 Block A (prior=0): episodes 0,1,2
- Day 1 Block B (prior=3): episodes 3,4,5
- Day 2 Block A (prior=0): episodes 6,7,8
- Day 2 Block B (prior=3): episodes 9,10,11

### Emission Counting

The schedule compiler pre-scans the resolved block list to compute `emissions_per_occurrence` and `prior_same_day_emissions` for each block before compilation. These values are passed to the episode selection function. No mutable counter or cursor is involved — the values are derived from the static schedule structure.

The execution offset (`execution_index`) is derived from the block definition (`slots / grid_blocks`) and is ephemeral. It is never persisted and does not create additional calendar occurrences.

---

## Schedule Edit Continuity

### run_id Preserved

If an operator edits a schedule block's time, day pattern, or slot count but the `run_id` (explicit or derived) remains the same, episode progression MUST continue from the existing anchor. The edit MUST NOT reset progression.

### run_id Changed

If a schedule edit changes the `run_id` (or changes a derived-identity component such that the derived identity changes), a new Progression Run is created with a fresh anchor. The old run becomes inactive.

### Day Pattern Change with Stable run_id

If the `placement_days` changes but `run_id` stays the same, the run record's `placement_days` is updated. The anchor date MUST still match the new pattern. If the anchor date no longer matches the new pattern, the anchor MUST be recomputed as the earliest matching date on or after the original anchor date. The `anchor_episode_index` is preserved — this is a pattern change, not a progression reset.

---

## DSL Integration

### Schedule Block Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `progression` | Yes | — | `sequential`, `random`, or `shuffle`. |
| `run_id` | No | derived | Progression Run identity. |
| `exhaustion` | No | `wrap` | `wrap`, `hold_last`, or `stop`. |

### Layer Key to Placement Days

The schedule layer key determines `placement_days`:

| Layer Key | Bitmask | Decimal |
|-----------|---------|---------|
| `all_day` | 1111111 | 127 |
| `weekdays` | 0011111 | 31 |
| `weekends` | 1100000 | 96 |
| `monday` | 0000001 | 1 |
| `tuesday` | 0000010 | 2 |
| `wednesday` | 0000100 | 4 |
| `thursday` | 0001000 | 8 |
| `friday` | 0010000 | 16 |
| `saturday` | 0100000 | 32 |
| `sunday` | 1000000 | 64 |

### Compilation Protocol

Before compiling individual blocks, the schedule compiler pre-scans the resolved block list:

1. For each sequential block, resolve its effective `run_id` (explicit or derived).
2. Compute `emissions_per_occurrence` per `run_id`: sum of `slots / grid_blocks` across all blocks sharing that `run_id`.
3. Compute `prior_same_day_emissions` per block: cumulative executions from earlier blocks (in schedule order) sharing the same `run_id`.

Then, for each sequential schedule block during compilation:

4. Load Progression Run from persistence (or create if first encounter).
5. Call episode selection with `(run, target_broadcast_day, episode_count, emissions_per_occurrence, prior_same_day_emissions, execution_index)`.
6. Use resulting episode indices for asset selection.

No cursor advancement step exists. No cursor persistence step exists. Episode selection is a pure function of the run record, the target date, and the schedule structure.

---

## Invariants

### INV-EPISODE-PROGRESSION-001 — Deterministic episode selection

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Given the same Progression Run record, target broadcast day, and episode catalog size, episode selection MUST always produce the same result. No runtime state, resolution history, scheduler uptime, or compilation order may influence the result.

**Violation:** Two compilations with identical inputs produce different episode indices.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-002 — Restart invariance

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Scheduler process restarts MUST NOT alter episode selection. If the scheduler is offline for N calendar days, the next compilation MUST select the episode corresponding to the correct occurrence count from the anchor — not the episode that would follow the last compiled episode.

**Violation:** A scheduler restart or multi-day downtime causes a different episode to be selected for a broadcast day than would have been selected without the restart.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-003 — Monotonic ordered advancement

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** For each broadcast day where the placement pattern matches, episodes MUST advance by exactly `emissions_per_occurrence` positions. The Nth matching day after the anchor MUST select base episode at `anchor_episode_index + (N × emissions_per_occurrence)` (subject to exhaustion policy). For single-emission runs (`emissions_per_occurrence=1`), this reduces to advancing by exactly one position per matching day.

**Violation:** An episode is skipped, repeated (except under `hold_last` after exhaustion), or selected out of catalog order.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-004 — Placement isolation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Two Progression Runs with different run identities MUST NOT influence each other. Episode selection for one run MUST NOT read or modify state belonging to another run.

**Violation:** Advancing or compiling one run alters the episode selected by a different run.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-005 — Day-pattern fidelity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Occurrence counting MUST be computed from the calendar and the `placement_days` bitmask only. Days outside the placement pattern MUST NOT advance the episode index. A weekday-only placement MUST NOT consume episodes on weekends.

**Violation:** An episode is consumed on a day whose day-of-week bit is not set in `placement_days`.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-006 — Exhaustion policy correctness

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** When the computed raw episode index reaches or exceeds the episode catalog size, behavior MUST follow the run's declared exhaustion policy:

- `wrap`: `raw_index % episode_count`
- `hold_last`: `min(raw_index, episode_count - 1)`
- `stop`: return FILLER when `raw_index >= episode_count`

The three policies are mutually exclusive and exhaustive.

**Violation:** An exhausted catalog produces behavior inconsistent with the declared policy.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-009 — Multi-execution sequencing

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** When a schedule block triggers N program executions (`slots / grid_blocks`), the executions MUST select episodes at consecutive indices starting from the block's base episode for that broadcast day. Execution offsets MUST NOT create additional calendar occurrences or persist any state. When multiple blocks share a `run_id`, the daily stride (`emissions_per_occurrence`) MUST equal the total executions across all sharing blocks, and each block's `prior_same_day_emissions` MUST account for earlier blocks' contributions.

**Violation:** A multi-execution block produces non-consecutive episode indices, overlapping episodes appear between blocks sharing a run_id on the same day, or a day transition produces overlapping episodes with the previous day.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-010 — Schedule edit continuity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-IMMUTABILITY`

**Guarantee:** If a schedule edit preserves the run identity (explicit `run_id` unchanged, or derived identity components unchanged), episode progression MUST continue from the existing anchor. Schedule time changes, day-pattern changes, and slot count changes MUST NOT reset progression when the run identity is stable.

**Violation:** A schedule edit that preserves run identity causes the episode index to reset to the anchor episode.

**Failure Semantics:** Planning fault.

---

### INV-EPISODE-PROGRESSION-011 — Anchor validity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

**Guarantee:** The anchor date's day-of-week MUST have its bit set in the run's `placement_days` bitmask. An anchor on a non-matching day is a validation fault.

    (1 << anchor_date.weekday()) & placement_days != 0

**Violation:** A Progression Run exists with an anchor date that does not match its placement pattern.

**Failure Semantics:** Validation fault at run creation or update time.

---

### INV-EPISODE-PROGRESSION-012 — Calendar-only computation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

**Guarantee:** `count_occurrences(anchor, target, mask)` MUST be a pure function. Same inputs MUST always produce the same output. The function MUST NOT access system time, mutable state, playlog records, as-run logs, resolution history, or external services.

**Violation:** The occurrence count for a given (anchor, target, mask) triple changes between invocations.

**Failure Semantics:** Planning fault.

---

## Derived Properties

The following properties hold as consequences of the invariants above. They are not independent invariants because they have no failure mode that is not already a violation of another invariant.

### Season boundary transparency

The episode list is a flat ordered sequence (see Terminology → Episode List). Season numbers are editorial metadata only. Progression walks the list by index without regard to season boundaries. No special logic fires at season transitions.

This is a direct consequence of the flat-index model. Any violation would be a violation of INV-EPISODE-PROGRESSION-003 (monotonic ordered advancement).

### EPG identity stability

Recompiling the same channel configuration for the same broadcast day produces the same episode selection. Published EPG entries do not change on recomputation (absent operator override).

This is a direct consequence of INV-EPISODE-PROGRESSION-001 (determinism) and INV-EPISODE-PROGRESSION-012 (calendar-only computation). Any violation would be a violation of one of those invariants.

---

## Retired Contracts

### INV-SERIAL-EPISODE-PROGRESSION (pkg/core/docs/contracts/runtime/)

Superseded by this contract. The calendar model, occurrence counting, and wrap policies defined there are preserved here as the canonical model. The placement identity tuple is replaced by run_id. Phase 3 scheduling model references are removed.

### progression_cursor.md — sequential sections (docs/contracts/)

The ProgressionCursor contract's sequential progression guarantees (INV-CURSOR-001, INV-CURSOR-002, INV-CURSOR-003, INV-CURSOR-006, INV-CURSOR-008) are superseded by this contract. Shuffle guarantees (INV-CURSOR-004, INV-CURSOR-005) and random guarantees (INV-CURSOR-007) remain valid under the Rotation and Asset Selection domain.

### scheduler_cursor_integration.md (docs/contracts/)

The 6-step compilation protocol (load → select → advance → persist → publish) is superseded. Episode selection is now a pure function call with no advance or persist steps. INV-SCHED-CURSOR-001 through INV-SCHED-CURSOR-005 are retired.

### INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 (docs/contracts/invariants/core/runtime/)

The `day_offset * slots_per_day` counter-seeding mechanism is superseded by calendar occurrence counting. The guarantee that consecutive days produce different episodes is inherent in INV-EPISODE-PROGRESSION-003.

---

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_anchor_date_selects_anchor_episode` | 001, 003 | Anchor date resolves to anchor episode index. |
| `test_daily_sequential_progression` | 001, 003 | Mon→E0, Tue→E1, Wed→E2, ... for daily placement. |
| `test_second_week_continues` | 001, 003 | Progression crosses week boundary without reset. |
| `test_weekly_progression` | 001, 005 | Weekly placement advances once per week. |
| `test_weekday_only_skips_weekends` | 005 | Weekday placement: Fri→E4, next Mon→E5 (not E7). |
| `test_mwf_progression` | 001, 005 | Mon/Wed/Fri placement skips Tue/Thu/Sat/Sun. |
| `test_scheduler_downtime_daily` | 002 | Offline Tue–Thu, Friday still selects correct episode. |
| `test_scheduler_downtime_full_week` | 002 | Offline for entire week, next compilation correct. |
| `test_out_of_order_resolution` | 001, 012 | Resolving Friday before Tuesday produces same results as chronological order. |
| `test_repeated_resolution_identical` | 001, 012 | Same date resolved twice yields same result. |
| `test_season_boundary_rollover` | 003 | Episode index crosses S01→S02 without special handling (derived: season transparency). |
| `test_wrap_cycles_back` | 006 | `wrap`: returns to episode 0 after catalog exhaustion. |
| `test_hold_last_repeats_final` | 006 | `hold_last`: repeats final episode indefinitely. |
| `test_stop_returns_filler` | 006 | `stop`: returns FILLER after last episode. |
| `test_all_policies_agree_before_exhaustion` | 006 | Last valid episode is the same under all three policies. |
| `test_anchor_on_non_matching_day_rejected` | 011 | Anchor on Saturday for weekday mask is invalid. |
| `test_same_show_different_times_independent` | 004 | Bonanza at 10:00 and 23:00 are separate runs. |
| `test_same_show_different_days_independent` | 004 | Weekday Bonanza and weekend Movies are separate runs. |
| `test_three_strips_no_interference` | 004 | Three concurrent runs on same channel progress independently. |
| `test_shared_run_id_same_episode` | 004 | Two blocks with same `run_id` resolve same episode. |
| `test_occurrence_counter_anchor_equals_target` | 012 | `[anchor, anchor)` returns 0. |
| `test_occurrence_counter_single_day` | 012 | `[Mon, Tue)` with daily mask returns 1. |
| `test_occurrence_counter_full_week` | 012 | 7 days with daily mask returns 7. |
| `test_occurrence_counter_large_range` | 012 | 10-year range computed efficiently. |
| `test_multi_execution_consecutive_episodes` | 009 | Block with 3 executions selects E_n, E_n+1, E_n+2. |
| `test_multi_execution_does_not_affect_next_day` | 009 | Next day's base episode is from calendar, not previous day's offset. |
| `test_non_zero_anchor_index` | 003 | anchor_episode_index=10 → anchor date selects E10. |
| `test_schedule_edit_preserves_progression` | 010 | Changing start time with same run_id continues from same anchor. |
| `test_run_id_change_resets_progression` | 010 | Changing run_id creates new run with fresh anchor. |
| `test_shared_run_same_day_same_episode` | 004 | Two blocks at different times sharing `run_id` resolve identical episode for same broadcast day. |
| `test_shared_run_time_shifted_same_episode` | 004, 012 | 06:00 and 18:00 blocks sharing `run_id` resolve identical episode; block start time does not influence selection. |

- `pkg/core/tests/contracts/test_progression_run_store.py`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_multi_execution_daily_stride` | 009 | Block with 4 executions per day: day D+1 starts where day D left off, zero overlap. |
| `test_shared_run_id_same_day_blocks` | 009 | Two blocks sharing run_id (3 executions each): day 1 emits 0–5, day 2 emits 6–11, zero overlap. |
| `test_derived_run_id_uses_start_time` | 004 | Blocks at different start times without explicit run_id create distinct derived run_ids. |
| `test_explicit_shared_run_id_shares_progression` | 004 | Two blocks with same explicit run_id and emissions_per_occurrence=2 pick consecutive episodes. |
| `test_shared_run_id_via_compile_schedule` | 009 | Full compile_schedule pipeline with shared run_id: pre-scan computes correct emissions_per_occurrence and prior_same_day_emissions. |

---

## Enforcement Evidence

TODO
