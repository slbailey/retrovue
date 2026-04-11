# INV-BREAK-COUNT-DURATION-SEPARATED-001 — Break count and break duration are independent

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that editorial decisions about break placement (count) and arithmetic decisions about break sizing (duration) are made by separate mechanisms. Conflating them produces breaks that are either too short to fill or too long for content pacing.

## Guarantee

Break count (placement) and break duration (budget distribution) MUST be determined independently. The template specifies placement strategy via `target_segment_minutes` and `strategy`. The compiler determines duration by distributing the derived break budget across placed breaks. No template field conflates count with duration.

## Observability

The compiler logs break count (from placement) and per-break duration (from budget distribution) separately. Changing `target_segment_minutes` alters count but not total budget. Changing grid slot size alters total budget but not count.

## Deterministic Testability

Hold content and grid slot constant. Change `target_segment_minutes` — break count changes but per-break duration adjusts inversely. Hold `target_segment_minutes` constant and change grid slot — per-break duration changes but count stays the same.

## Failure Semantics

**Planning fault.** Conflated count/duration produces breaks that violate `INV-BREAK-BUDGET-DERIVED-001` or `INV-BREAKPLAN-ALLOCATION-BOUNDED-001`.

## Required Tests

- `server/tests/contracts/test_timeline_compilation_templates.py`

## Enforcement Evidence

TODO
