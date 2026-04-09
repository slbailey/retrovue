# INV-POLICY-LAYERED-001 — Policies layer on top of LAW-ELIGIBILITY

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-ELIGIBILITY` by ensuring operator-defined scheduling policies can only add restrictions on top of core eligibility — they MUST NOT override, relax, or bypass the `state=ready` AND `approved_for_broadcast=true` gate.

## Guarantee

Scheduling policies MUST NOT override, relax, or re-evaluate the core eligibility gate. An asset that does not satisfy `LAW-ELIGIBILITY` MUST NOT reach policy evaluation. An asset that satisfies `LAW-ELIGIBILITY` but fails a policy rule is ineligible for the specific scheduling context — it is not marked ineligible system-wide.

## Preconditions

All candidate assets passed to policy evaluation have already passed the `LAW-ELIGIBILITY` gate (`state=ready` AND `approved_for_broadcast=true`).

## Observability

If a policy evaluation function receives an asset with `state != ready` or `approved_for_broadcast != true`, this indicates a pipeline ordering violation upstream of policy evaluation, not a policy-layer failure.

## Deterministic Testability

Construct a candidate list containing both eligible and ineligible assets. Verify that the pipeline invokes `LAW-ELIGIBILITY` gating before policy evaluation and that policy evaluation does not re-check or alter core eligibility fields. Verify that a policy cannot mark an ineligible asset as eligible.

## Failure Semantics

Planning fault. If policies can relax core eligibility, non-ready or unapproved assets may enter scheduling artifacts, violating `LAW-ELIGIBILITY`.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_policies.py`

## Enforcement Evidence

TODO
