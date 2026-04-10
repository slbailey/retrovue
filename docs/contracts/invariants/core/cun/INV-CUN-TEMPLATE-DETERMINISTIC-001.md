# INV-CUN-TEMPLATE-DETERMINISTIC-001 — Deterministic Template Selection

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` (schedule reproducibility). Template selection from a pool MUST be deterministic so that recompiling the same schedule produces the same CUN segments.

## Guarantee

Template selection from the pool MUST be deterministic, using SHA256-seeded selection. Given the same inputs (channel_id, broadcast_day, segment context), the same template MUST be selected.

## Preconditions

Channel has multiple CUN templates configured.

## Observability

Recompiling the same schedule with the same inputs produces a different template selection.

## Deterministic Testability

Select a template twice with identical inputs. Verify the same template is chosen. Change one input. Verify a different template may be chosen.

## Failure Semantics

Planning fault — schedule non-reproducibility; violates `LAW-DERIVATION`.

## Required Tests

- `pkg/core/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
