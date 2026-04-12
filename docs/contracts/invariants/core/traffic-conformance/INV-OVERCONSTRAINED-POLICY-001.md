# INV-OVERCONSTRAINED-POLICY-001 — Explicit per-template overconstrained conformance

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

## Purpose

When content runtime exceeds the grid slot, the compiler MUST apply the template's declared overconstrained policy. Without an explicit policy, the compiler could silently truncate content (violating `LAW-CONTENT-AUTHORITY`) or leave gaps (violating `LAW-GRID`).

## Guarantee

Every template MUST declare or inherit an `overconstrained` policy (`bleed` or `reject`). Default is `bleed`. The compiler MUST evaluate the declared policy when `content_duration + presentation_duration > scheduled_duration`.

## Preconditions

- Template is resolved (including `extends` inheritance).
- Content duration and presentation duration are known at compile time.
- Scheduled slot duration is grid-aligned per `INV-BLEED-NO-GAP-001` preconditions.

## Observability

- `bleed` mode: the compiled block's effective duration exceeds the original slot. Subsequent blocks are compacted. A structured log event records the bleed amount.
- `reject` mode: `CompileError` is raised with block identifier, template name, content duration, presentation duration, slot duration, and deficit.

## Deterministic Testability

Construct a template with `overconstrained: bleed` and content exceeding the slot by a known amount. Verify: (1) effective slot is extended, (2) break count is zero, (3) conformance holds against extended slot. Repeat with `overconstrained: reject` and verify `CompileError` is raised with correct fields.

## Failure Semantics

Planning fault. In `reject` mode, `CompileError` halts the broadcast day. In `bleed` mode, no fault — the slot extends.

## Required Tests

- `server/tests/contracts/test_traffic_profiles_conformance.py`

## Enforcement Evidence

TODO
