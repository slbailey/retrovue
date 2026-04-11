# INV-POLICY-VIOLATION-STRUCTURED-001 — Violations carry structured context

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring policy violations are traceable and machine-parseable. Unstructured violations (bare strings, exceptions) break auditability and prevent automated diagnostics from reasoning about scheduling decisions.

## Guarantee

Every PolicyViolation MUST carry: `invariant_id` (string, non-empty), `rule_type` (one of `"repeat_window"`, `"frequency_cap"`, `"tag_eligibility"`, `"duration_gate"`), `message` (human-readable, non-empty), and `details` (dict with at minimum `asset_id`). Violations MUST NOT be bare strings, exceptions, or unstructured log messages.

## Preconditions

Policy evaluation functions return PolicyViolation objects, not exceptions.

## Observability

Every PolicyViolation returned by evaluation functions can be validated against the required field schema. Missing or empty required fields are a violation of this invariant.

## Deterministic Testability

Construct inputs that trigger each rule type. For each resulting PolicyViolation, assert: `invariant_id` is a non-empty string, `rule_type` is one of the four permitted values, `message` is a non-empty string, and `details` is a dict containing at minimum `"asset_id"`.

## Failure Semantics

Planning fault. Unstructured violations are untraceable — operators cannot determine why an asset was excluded, and automated systems cannot act on the violation.

## Required Tests

- `server/tests/contracts/test_scheduling_policies.py`

## Enforcement Evidence

TODO
