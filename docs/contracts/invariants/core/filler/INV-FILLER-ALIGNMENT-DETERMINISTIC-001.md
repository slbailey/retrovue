# INV-FILLER-ALIGNMENT-DETERMINISTIC-001 — Same inputs produce identical filler segments

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

## Purpose

Filler segment construction MUST be a pure function of its inputs. Non-deterministic filler computation would violate `LAW-DERIVATION` — downstream artifacts (playlog, as-run log) would diverge from the schedule on repeated derivation.

## Guarantee

Given identical `gap_ms`, `filler_duration_ms`, `alignment`, and (for `"start"` mode) `wrapping_offset_ms`, the filler construction logic MUST produce identical output: same number of segments, same `asset_start_offset_ms` values, same `segment_duration_ms` values, in the same order. No randomness, wall-clock reads, or external state may influence the computation.

## Observability

Invoke filler construction twice with identical inputs. Compare output segment lists field-by-field.

## Deterministic Testability

Call the filler construction function twice with the same parameters. Assert output equality. No real-time waits required.

## Failure Semantics

**Planning fault.** Non-deterministic filler output indicates use of randomness or external state in the construction path.

## Required Tests

- `pkg/core/tests/contracts/test_filler_alignment.py`

## Enforcement Evidence

TODO
