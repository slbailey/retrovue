# INV-PRESENTATION-PRECEDES-PRIMARY-001 — Presentation precedes primary

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring presentation segments appear in their declared editorial order before the primary content segment. Misordered presentation segments violate the operator's declared intent and produce incorrect on-air sequencing.

## Guarantee

All presentation segments MUST appear before the primary content segment in the block's segment list. The declared order of presentation segments MUST be preserved. No content, filler, or pad segment may appear between presentation segments and the primary segment.

## Preconditions

- The ProgramDefinition declares a presentation stack with 1..n entries.

## Observability

A presentation segment appears after the primary content segment, or presentation segments appear in an order different from their declaration order.

## Deterministic Testability

Assemble a program with presentation stack [rating_card, feature_bumper, studio_logo]. Assert the segment list contains these three segments in exact declared order, immediately followed by the primary content segment. Assert no non-presentation segment appears between them.

## Failure Semantics

**Planning fault.** Misordered presentation produces incorrect on-air sequencing.

## Required Tests

- `pkg/core/tests/contracts/test_program_presentation.py`

## Enforcement Evidence

TODO
