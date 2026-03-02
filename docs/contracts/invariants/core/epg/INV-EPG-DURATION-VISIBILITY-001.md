# INV-EPG-DURATION-VISIBILITY-001 — Duration visibility and human formatting

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

## Purpose

A broadcast EPG grid communicates program durations implicitly through slot width. When a program aligns to the canonical 30-minute grid cadence, showing an explicit duration is redundant noise. When a program disrupts the grid cadence, the duration MUST be shown so viewers can anticipate when the next program starts. Formatting MUST match broadcast convention — whole minutes in hours-and-minutes notation. Violation produces either missing duration information (`LAW-DERIVATION`) or grid-incoherent presentation (`LAW-GRID`).

## Guarantee

EPG entries MUST include a `display_duration` field. The field MUST be `null` for TV episodes (entries with non-null `season`). The field MUST be `null` for movies whose content duration is grid-implicit. The field MUST contain a human-formatted duration string for movies whose content duration disrupts the grid cadence. Formatting MUST use whole minutes rounded to the nearest minute, in broadcast notation.

## Preconditions

- The EPG entry has `start_time`, `end_time`, and `slot_duration_sec` (or equivalent).
- Grid cadence is 30 minutes.

## Observability

For every EPG entry: parse `start_time` and `end_time`, compute rounded slot duration, evaluate grid alignment. If `display_duration` is `null` the item MUST be grid-implicit. If non-null the value MUST match the formatting rules below. Detectable by offline audit.

## Deterministic Testability

Construct EPG entries with known start/end times and slot durations. Assert `display_duration` is `null` for grid-aligned items and correctly formatted for grid-disrupting items. No real-time waits required.

Rules:

**Rounding.** Fractional durations MUST be rounded to the nearest whole minute (>= 0.5 rounds up) BEFORE evaluating grid alignment.

**Grid alignment.** A schedule item is grid-implicit if ALL of: `start.minute in {0, 30}`, `end.minute in {0, 30}`, `rounded_duration_minutes % 30 == 0`.

**Episode suppression.** TV episodes (entries where `season` is non-null) MUST have `display_duration` of `null`. TV episodes are assumed to align to grid always.

**Visibility.** For movies (entries where `season` is null): grid-implicit items MUST have `display_duration` of `null`. All other movies MUST have `display_duration` as a non-empty string.

**Formatting.** When shown:
- Duration < 60 minutes: `"{m}m"` (e.g. `"45m"`).
- Duration >= 60 minutes with nonzero remainder: `"{h}h {m}m"` (e.g. `"2h 5m"`).
- Duration >= 60 minutes with zero remainder: `"{h}h"` (e.g. `"2h"`).
- No decimals. No raw minute counts above 59. No fractional minutes.

## Failure Semantics

**Planning fault.** Incorrect `display_duration` in derived EPG data indicates a derivation logic error.

## Required Tests

- `pkg/core/tests/contracts/test_epg_duration_visibility.py`

## Enforcement Evidence

TODO
