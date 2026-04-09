# SchedulingPolicy

**Domain:** scheduling
**Slug:** `scheduling-policy`

## What it represents

**Operator-defined scheduling eligibility rules** that gate which assets may be scheduled in specific contexts. Policies layer on top of core eligibility (`LAW-ELIGIBILITY`) and add restrictions — they never relax the core gate.

## Rule types

- **Repeat window** — prevents re-airing the same episode within N days
- **Frequency cap** — limits episodes of the same show per scheduling day
- **Tag eligibility** — requires or excludes tags for specific scheduling contexts
- **Duration gate** — enforces min/max duration for specific slot types

## Lifecycle phase

**Declared** in channel DSL YAML, **compiled** via DslScheduleService into runtime SchedulingPolicy objects, **evaluated** during schedule compilation after asset resolution and before block assembly.

## Owning domain

scheduling

## What depends on it

Block assembly (receives the filtered candidate list after policy evaluation).

## What produces it

DSL compilation via DslScheduleService. Policies MUST NOT originate from any other source (`INV-POLICY-DSL-DECLARED-001`).

## Key invariants

`INV-POLICY-PURE-001`, `INV-POLICY-LAYERED-001`, `INV-POLICY-IDEMPOTENT-001`, `INV-POLICY-DSL-DECLARED-001`, `INV-POLICY-VIOLATION-STRUCTURED-001`

## Canonical contract

`docs/contracts/scheduling_policies.md`

## What must NOT be assumed

- That policies can override or relax `LAW-ELIGIBILITY`.
- That policies perform I/O or mutate state during evaluation.
- That policies are the same as constraints (constraints are hard broadcast rules; policies are operator-configurable eligibility rules).
