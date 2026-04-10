# INV-SCHEDULE-COMPILER-MODULE-SPLIT-001 — Schedule compiler module boundaries

Status: Invariant
Authority Level: Planning
Derived From: `LAW-SIMPLICITY`

## Purpose

Protects module cohesion within the schedule compilation pipeline. Without explicit boundaries, validation, resolution, and compilation logic collapse into a single monolith that resists independent testing, review, and change. `LAW-SIMPLICITY` requires each concern to live in exactly one place.

## Guarantee

The schedule compilation pipeline MUST be organized into three modules with non-overlapping responsibilities:

1. **`template_resolution.py`** — Template extends chains, presentation reference resolution, DOW schedule layering, traffic profile resolution, channel template helpers, and scheduling policy DSL resolution. No compilation. No validation.
2. **`schedule_validation.py`** — DSL validation, grid alignment validation, traffic profile reference validation, and post-compile block validation. No compilation. No resolution.
3. **`schedule_compiler.py`** — Program block compilation, break expansion, compiled segment serialization, seed helpers, time parsing, grid slot math, and the top-level `compile_schedule` entry point. Imports from the other two modules.

All public symbols previously importable from `schedule_compiler` MUST remain importable from `schedule_compiler` via re-exports.

## Preconditions

All three modules reside in `pkg/core/src/retrovue/runtime/`.

## Observability

An import of any public symbol from `retrovue.runtime.schedule_compiler` that previously succeeded MUST continue to succeed after the split.

## Deterministic Testability

Import-verification tests assert that each public symbol resolves from both its canonical new module and the backward-compatible re-export path.

## Failure Semantics

Planning fault. A symbol that cannot be imported breaks downstream compilation at import time, not at runtime.

## Required Tests
- `pkg/core/tests/contracts/test_schedule_compiler_module_split.py`

## Enforcement Evidence
TODO
