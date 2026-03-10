# INV-PRESENTATION-SINGLE-PRIMARY-001 — Exactly one primary content segment

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring each assembled program block has a single, unambiguous editorial identity. If multiple segments are marked primary, or if presentation segments claim primary status, identity resolution and break protection (`INV-MOVIE-PRIMARY-ATOMIC`) become undefined.

## Guarantee

Each assembled program block MUST contain exactly one segment with `is_primary=True`. All presentation segments (`segment_type="presentation"`) MUST have `is_primary=False`.

## Preconditions

- The block is produced by program assembly (not a raw filler or pad block).

## Observability

An assembled block contains zero or more than one segment with `is_primary=True`, or a presentation segment has `is_primary=True`.

## Deterministic Testability

Assemble a program with 0, 1, and 3 presentation segments. Assert exactly one segment has `is_primary=True` in each case. Assert all presentation segments have `is_primary=False`.

## Failure Semantics

**Planning fault.** Multiple primary segments corrupt editorial identity and disable the `INV-MOVIE-PRIMARY-ATOMIC` filler guard.

## Required Tests

- `pkg/core/tests/contracts/test_program_presentation.py`

## Enforcement Evidence

TODO
