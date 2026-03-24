# INV-TIMELINE-CARRY-IN-PRESERVED-001 — Cross-day continuity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`, `LAW-TIMELINE`

## Purpose

Protects `LAW-GRID` and `LAW-CONTENT-AUTHORITY` by ensuring that day boundaries — administrative constructs — do not break the continuous timeline. A program that extends past a day boundary has committed its time range at scheduling time; subsequent day compilation MUST respect that commitment.

## Guarantee

If a program extends across a day boundary, the subsequent day MUST respect the existing timeline and MUST NOT introduce any block that overlaps the carried-in program.

## Observability

If a program ends at time Tₑ, no block from the subsequent day may start before Tₑ.

## Deterministic Testability

On day D, schedule a program ending at time Tₑ where Tₑ is past day D+1's broadcast start. Compile day D+1 by any path (initial build, horizon extension, cold restart). Assert day D+1's first block has a start time ≥ Tₑ.

## Failure Semantics

**Planning fault.** Overlapping the carry-in window creates two programs claiming the same time range, violating timeline continuity.

## Required Tests

- `pkg/core/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

TODO
