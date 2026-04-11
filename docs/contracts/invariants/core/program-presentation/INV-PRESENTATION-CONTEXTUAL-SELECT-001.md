# INV-PRESENTATION-CONTEXTUAL-SELECT-001 — Contextual presentation pool filtering

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring presentation assets match the editorial properties of the primary content they accompany. A ratings card for a PG movie MUST display the PG rating, not a randomly selected rating from the pool.

## Guarantee

When a presentation pool entry declares a `select.where` clause containing `program.*` references, those references MUST be resolved against the selected primary content asset's metadata before pool filtering. The resulting presentation asset MUST satisfy the resolved filter criteria.

## Preconditions

- The presentation entry declares a `select.where` clause with one or more `program.*` references.
- The primary content asset has been selected from the program pool.

## Observability

A presentation asset is emitted whose metadata does not match the resolved `program.*` filter. For example, a "G" ratings card accompanies a "PG" movie when `rating: eq: program.rating` is declared.

## Deterministic Testability

Assemble a program block with a PG-rated movie and a presentation pool entry with `select.where.rating.eq: program.rating`. Assert the selected ratings card has `rating == "PG"`. Repeat with different ratings to confirm the filter resolves dynamically per content selection.

## Failure Semantics

**Planning fault.** Incorrect presentation selection produces misleading on-air content that misrepresents the program's rating.

## Required Tests

- `server/tests/contracts/test_inv_presentation_contextual_select.py`

## Enforcement Evidence

TODO
