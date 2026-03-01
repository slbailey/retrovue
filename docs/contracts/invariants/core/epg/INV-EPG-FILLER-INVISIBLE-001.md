# INV-EPG-FILLER-INVISIBLE-001 — Filler invisible in EPG

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Filler and padding segments are scheduling artifacts used to fill grid time when content underruns a block. They are not editorial content and MUST NOT appear as distinct EPG entries. Exposing filler in the EPG misrepresents the broadcast schedule to viewers and violates `LAW-CONTENT-AUTHORITY` — the SchedulePlan defines editorial intent, and filler is not editorial.

## Guarantee

No `EPGEvent` MUST have a `title` or `resolved_asset` that identifies it as filler content. EPG derivation produces one event per `ProgramEvent`; filler segments within blocks are subsumed into the program's grid occupancy and do not generate separate EPG entries.

## Observability

Inspect EPG events for any entry whose `resolved_asset.file_path` matches the configured filler path. Any such entry is a violation.

## Deterministic Testability

Build a `ResolvedScheduleDay` with `ProgramEvent` entries that have content shorter than grid occupancy (triggering filler in playout). Derive EPG events. Assert no EPG event references the filler asset. No real-time waits required.

## Failure Semantics

**Planning fault.** Filler appearing in EPG indicates the derivation logic is emitting per-slot entries instead of per-ProgramEvent entries, or is failing to filter filler-only slots.

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgFillerInvisible001`

## Enforcement Evidence

TODO
