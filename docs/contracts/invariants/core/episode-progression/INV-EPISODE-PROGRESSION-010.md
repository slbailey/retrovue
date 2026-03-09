# INV-EPISODE-PROGRESSION-010 — Schedule edit continuity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-IMMUTABILITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that routine schedule edits (time changes, slot adjustments) do not destroy episode progression state. An operator moving a strip from 10:00 to 10:30 expects the series to continue from where it left off, not restart from E0.

## Guarantee

If a schedule edit preserves the run identity (explicit `run_id` unchanged, or derived identity components unchanged), episode progression MUST continue from the existing anchor. Schedule time changes, day-pattern changes, and slot count changes MUST NOT reset progression when the run identity is stable.

## Preconditions

- A Progression Run exists.
- An operator edits the schedule block without changing the run identity.

## Observability

After an edit that preserves run identity, the next compilation produces a different episode than would have been selected without the edit.

## Deterministic Testability

Create a run with explicit `run_id="cheers_strip"` anchored on Monday at E0. Compile 5 days (Mon–Fri, E0–E4). Change the block's start time from 10:00 to 10:30 while keeping `run_id="cheers_strip"`. Compile Saturday. Assert E5 (not E0).

## Failure Semantics

**Planning fault.** Edit-triggered progression reset forces operators to manually track and restore episode positions after any schedule change.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
