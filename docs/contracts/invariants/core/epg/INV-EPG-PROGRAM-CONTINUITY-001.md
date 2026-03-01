# INV-EPG-PROGRAM-CONTINUITY-001 — Multi-block programs as single entry

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

## Purpose

A `ProgramEvent` that spans multiple grid blocks (e.g., a 90-minute movie in a 30-minute grid) represents a single editorial airing. The EPG MUST present this as one entry, not split into per-block fragments. Splitting a program into per-block EPG entries misrepresents the schedule to viewers and contradicts `LAW-GRID`'s model where `block_span_count` defines grid occupancy as a single editorial unit.

## Guarantee

A `ProgramEvent` with `block_span_count > 1` MUST produce exactly one `EPGEvent` whose `end_time - start_time` equals `block_span_count * grid_block_minutes * 60` seconds. The EPG MUST NOT produce multiple events for the same `ProgramEvent`.

## Observability

For each `ProgramEvent` with `block_span_count > 1`, count the number of EPG events that share the same `start_time` and `episode_id`. Exactly one event MUST exist. Its duration MUST equal `block_span_count * grid_block_seconds`.

## Deterministic Testability

Build a `ResolvedScheduleDay` with a `ProgramEvent` spanning 3 blocks (90 minutes in a 30-minute grid). Derive EPG events. Assert exactly one event exists for that program with duration equal to 90 minutes. No real-time waits required.

## Failure Semantics

**Planning fault.** Per-block splitting indicates the derivation logic is iterating `ResolvedSlot` entries instead of `ProgramEvent` entries.

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgProgramContinuity001`

## Enforcement Evidence

TODO
