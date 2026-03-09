# INV-EPISODE-PROGRESSION-002 — Restart invariance

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that scheduler downtime does not corrupt episode progression. A scheduler offline for multiple days MUST NOT cause episode indices to reset, skip, or repeat on resumption.

## Guarantee

Scheduler process restarts MUST NOT alter episode selection. If the scheduler is offline for N calendar days, the next compilation MUST select the episode corresponding to the correct occurrence count from the anchor — not the episode that would follow the last compiled episode.

## Preconditions

- A Progression Run record exists with a valid anchor.
- The scheduler was offline for one or more broadcast days.

## Observability

After a multi-day scheduler outage, the first compiled broadcast day selects an episode that does not match the expected occurrence count from the anchor date.

## Deterministic Testability

Create a Progression Run anchored on Monday. Compile Monday (E0). Skip Tuesday through Thursday (no compilation). Compile Friday directly. Assert Friday selects E4 (4 weekday occurrences from anchor for a daily strip). No intermediate compilations required.

## Failure Semantics

**Planning fault.** Downtime-dependent episode selection means the EPG cannot be reconstructed from the schedule configuration alone.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
