# INV-EPISODE-PROGRESSION-009 — Multi-execution sequencing

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that a schedule block with multiple program executions produces a consecutive run of episodes within a single broadcast day, without corrupting the calendar-based progression for subsequent days.

## Guarantee

When a schedule block triggers N program executions (`slots / grid_blocks`), the executions MUST select episodes at consecutive indices starting from the block's base episode for that broadcast day. Execution offsets MUST NOT create additional calendar occurrences or persist any state. When multiple blocks share a `run_id`, the daily stride (`emissions_per_occurrence`) MUST equal the total executions across all sharing blocks, and each block's `prior_same_day_emissions` MUST account for earlier blocks' contributions.

## Preconditions

- A schedule block exists with `slots > grid_blocks` and `progression: sequential`.
- The referenced Progression Run is valid.

## Observability

A multi-execution block produces non-consecutive episode indices, overlapping episodes appear between blocks sharing a run_id on the same day, or a day transition produces overlapping episodes with the previous day.

## Deterministic Testability

Create a daily run anchored at E0. Configure a block with `slots=3, grid_blocks=1` (3 executions, `emissions_per_occurrence=3`). Compile day 1: assert E0, E1, E2. Compile day 2: assert E3, E4, E5. Day 2 advances by `emissions_per_occurrence` (3) from day 1's base. For two blocks sharing `run_id` with 3 executions each (`emissions_per_occurrence=6`): day 1 block A emits E0,E1,E2; day 1 block B emits E3,E4,E5; day 2 block A emits E6,E7,E8.

## Failure Semantics

**Planning fault.** Persistent execution offsets would cause episode drift proportional to block size.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`
- `pkg/core/tests/contracts/test_progression_run_store.py`

## Enforcement Evidence

TODO
