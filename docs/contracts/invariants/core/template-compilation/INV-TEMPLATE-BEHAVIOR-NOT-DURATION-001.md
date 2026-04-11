# INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001 — Templates are behavior, not duration

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring templates remain behavioral recipes that adapt to any content runtime. If templates specified fixed break counts or durations, every content-length variant would require its own template, creating template explosion and violating the principle that editorial intent is expressed once.

## Guarantee

Templates MUST define break *placement strategy* and *continuity element rules*. Templates MUST NOT contain `break_count`, `break_duration_sec`, or `grid_slots` fields. Break count and duration are derived by the compiler from content runtime and template parameters.

## Observability

YAML validation rejects any template containing prohibited fields. Compilation logs emit the derived break count and break budget for each block, demonstrating runtime adaptation.

## Deterministic Testability

Load a template with `target_segment_minutes: 11`. Compile against 22-minute content — expect ~2 breaks. Compile the same template against 44-minute content — expect ~4 breaks. The template is unchanged; only the derived values differ.

## Failure Semantics

**Planning fault.** A template with fixed break count or duration produces incorrect break structures for content runtimes it was not designed for.

## Required Tests

- `server/tests/contracts/test_timeline_compilation_templates.py`

## Enforcement Evidence

TODO
