# INV-EPISODE-PROGRESSION-001 — Deterministic episode selection

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION` by ensuring that episode selection is a pure function. If episode selection depends on runtime state, resolution order, or scheduler uptime, the derivation chain from SchedulePlan to EPG becomes non-reproducible and episode identity becomes unstable.

## Guarantee

Given the same Progression Run record, target broadcast day, and episode catalog size, episode selection MUST always produce the same result. No runtime state, resolution history, scheduler uptime, or compilation order may influence the result.

## Preconditions

- A Progression Run record exists for the schedule block's run identity.
- The episode catalog for the run's content source is available.

## Observability

Two compilations of the same channel configuration for the same broadcast day produce different episode indices for the same schedule block.

## Deterministic Testability

Compile a channel for broadcast day D. Record episode index E for a sequential block. Compile the same channel for the same day D again (simulating a restart). Assert episode index is E. Compile in reverse date order (Friday before Tuesday). Assert each day's episode index matches the chronological compilation.

## Failure Semantics

**Planning fault.** Non-deterministic episode selection corrupts EPG identity and breaks derivation traceability.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
