# INV-TIMELINE-LONGFORM-INVIOLATE-001 — In-flight program continuity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-TIMELINE`, `LAW-GRID`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-TIMELINE` by ensuring that a program occupying a scheduled time range is never truncated, replaced, or split within that range. Viewers expect continuous playback of committed content.

## Guarantee

A program occupying a time range [Tₛ, Tₑ) MUST remain intact for its full duration. No operation — process restart, schedule recompilation, horizon extension, or day-boundary crossing — MUST cause the program to be removed from the timeline, shortened, or replaced with different content for any time within [Tₛ, Tₑ).

## Observability

For any T where Tₛ < T < Tₑ, the same program MUST be returned with its original start time Tₛ and duration.

## Deterministic Testability

Schedule a program with duration D starting at time Tₛ. At any time T where Tₛ < T < Tₛ + D, query the timeline. The program MUST still be present at T with its original start time Tₛ and duration D. Verify after restart, after recompilation, and across broadcast day boundaries.

## Failure Semantics

**Planning fault.** A truncated or replaced in-flight program violates the viewer's expectation of continuous programming and contradicts "longform is never cut."

## Required Tests

- `server/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

TODO
