# INV-POLICY-DSL-DECLARED-001 — Policies are declared in DSL YAML

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring all scheduling policies originate from the sole editorial authority — channel DSL YAML compiled via DslScheduleService. No component may introduce policies from non-DSL sources.

## Guarantee

All scheduling policies MUST originate from channel DSL YAML declarations compiled via DslScheduleService. No component MUST introduce, modify, or override scheduling policies outside of DSL compilation. Runtime code MUST NOT construct SchedulingPolicy objects from non-DSL sources.

## Preconditions

DslScheduleService is the sole compilation path for channel schedules.

## Observability

AST inspection or import analysis of all SchedulingPolicy construction call sites confirms they occur only within the DSL compilation path. Any SchedulingPolicy instantiation outside DslScheduleService is a violation.

## Deterministic Testability

Scan all Python source files for SchedulingPolicy construction calls. Verify that every construction call site is within the DSL compilation module or test fixtures. Verify that no runtime module, CLI command, or API handler constructs SchedulingPolicy objects.

## Failure Semantics

Planning fault. Policies from non-DSL sources violate `LAW-CONTENT-AUTHORITY` — editorial decisions would exist outside the contracted authority chain.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_policies.py`

## Enforcement Evidence

TODO
