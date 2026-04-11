# INV-CONSTRAINT-ADJACENCY-001 — Adjacency content restrictions

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

Prevents jarring or harmful content transitions by enforcing back-to-back scheduling rules. Adjacency constraints protect viewer experience where specific content classifications MUST NOT follow each other in direct succession (e.g. horror followed by children's programming). Violation risks `LAW-CONTENT-AUTHORITY` by producing a schedule the operator has declared editorially unacceptable.

## Guarantee

Adjacent blocks in the compiled schedule MUST NOT violate declared adjacency restrictions. An adjacency restriction defines two content classifications and a direction (symmetric or directional) that MUST NOT appear in successive blocks.

## Preconditions

- At least one adjacency constraint is defined for the channel.
- The compiled schedule contains two or more consecutive blocks.
- Both blocks have content classifications assigned.

## Observability

At compilation time, each pair of adjacent blocks is checked against all active adjacency constraints. Any pair matching a restricted adjacency produces a structured violation identifying both blocks, their classifications, and the constraint reason.

## Deterministic Testability

Compile a schedule with Block A (classification "horror") followed by Block B (classification "children"). Define a symmetric adjacency constraint for ("horror", "children"). Assert that validation raises an adjacency violation. Verify that non-adjacent blocks or non-matching classifications pass. No real-time waits required.

## Failure Semantics

**Planning fault.** The schedule compilation produced a content transition the operator has prohibited. System MUST report the violation as a planning fault.

## Required Tests

- `server/tests/contracts/scheduling/test_schedule_constraints.py::TestInvConstraintAdjacency001`

## Enforcement Evidence

- `server/src/retrovue/scheduling/schedule_constraints.py` — `check_adjacency_constraints()`
- Error tag: `INV-CONSTRAINT-ADJACENCY-001-VIOLATED`
