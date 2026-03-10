# INV-PRESENTATION-GRID-BUDGET-001 — Presentation durations deducted from grid budget

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-GRID` by ensuring presentation segment durations are accounted for in grid budget calculations. If presentation durations are excluded, assembled content may exceed the grid allocation, violating block boundary alignment.

## Guarantee

The total duration of all presentation segments MUST be deducted from the available grid budget before primary content selection. Content selection MUST be constrained by the sum of presentation durations plus content duration against the grid allocation. A presentation stack whose total duration plus content duration exceeds the grid allocation MUST be rejected when `bleed: false`.

## Preconditions

- The ProgramDefinition declares a presentation stack with 1..n entries.
- `bleed: false` on the ProgramDefinition (when `bleed: true`, overrun is permitted).

## Observability

An assembled block with `bleed: false` has total segment duration (presentation + content) exceeding `grid_blocks * grid_minutes`.

## Deterministic Testability

Create a 30-minute grid block. Add a 5-minute presentation segment. Assert that a 28-minute content asset is rejected (5 + 28 = 33 > 30). Assert that a 24-minute content asset is accepted (5 + 24 = 29 <= 30).

## Failure Semantics

**Planning fault.** Grid overrun causes block boundary misalignment.

## Required Tests

- `pkg/core/tests/contracts/test_program_presentation.py`

## Enforcement Evidence

TODO
