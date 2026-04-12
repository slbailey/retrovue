# Scheduling Policies — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

---

## Overview

Scheduling policies are operator-defined eligibility rules that gate which assets may be scheduled in specific contexts. They layer on top of core eligibility (`LAW-ELIGIBILITY`: `state=ready` AND `approved_for_broadcast=true`) and add further restrictions — they never relax the core gate.

Policies are declared in channel DSL YAML and evaluated during schedule compilation, after asset resolution and before block assembly. Policy evaluation is pure: no I/O, no database access, no mutation. All state needed for evaluation is passed as arguments.

Policies are distinct from constraints. Constraints are hard broadcast rules defined by Core (blackout windows, adjacency, watershed). Policies are operator-configurable scheduling eligibility rules defined in the DSL. Both are pure evaluation layers, but they operate at different points in the pipeline with different authority sources.

This contract does not define YAML structure, policy declaration syntax, or DSL compilation rules. Those concerns are governed by the scheduling DSL contract. This contract defines only the runtime evaluation semantics applied after configuration has been resolved.

### Authority Boundary

This contract owns:
- Runtime policy evaluation: repeat window, frequency cap, tag eligibility, duration gate
- Evaluation order and composition semantics
- Purity guarantee (no I/O, no mutation)
- Violation structure and classification
- Edge case behavior (empty inputs, no violations)

This contract does NOT own:
- YAML structure or policy declarations (scheduling DSL contract)
- Asset resolution or candidate pool construction (asset resolution)
- Core eligibility gate (`LAW-ELIGIBILITY` — evaluated before policies)
- Constraint evaluation: blackout, adjacency, watershed (schedule constraints)
- Block assembly or traffic fill (block assembly, traffic manager)

---

## Domain Objects

### SchedulingPolicy

Runtime evaluation object containing resolved policy rules. A SchedulingPolicy is the runtime form of policy declarations in the channel DSL YAML. Declaration syntax, defaults, and resolution order are governed by the scheduling DSL contract — this object receives the resolved result.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `repeat_window_rules` | list[RepeatWindowRule] | `[]` | Repeat window restrictions. |
| `frequency_cap_rules` | list[FrequencyCapRule] | `[]` | Frequency cap restrictions. |
| `tag_eligibility_rules` | list[TagEligibilityRule] | `[]` | Tag-based eligibility restrictions. |
| `duration_gate_rules` | list[DurationGateRule] | `[]` | Duration-based slot restrictions. |

### RepeatWindowRule

Prevents re-airing the same episode within a configurable time window.

| Field | Type | Description |
|-------|------|-------------|
| `window_days` | int | Minimum days between re-airs of the same episode. |
| `scope` | str | Scope of the check: `"channel"` or `"network"`. |

### FrequencyCapRule

Limits the number of episodes from the same show within a scheduling period.

| Field | Type | Description |
|-------|------|-------------|
| `max_per_day` | int | Maximum episodes of the same show per scheduling day. `0` = unlimited. |
| `show_id_field` | str | Field on the asset used to group by show. Default: `"series_id"`. |

### TagEligibilityRule

Requires or excludes assets based on tag membership for a specific scheduling context.

| Field | Type | Description |
|-------|------|-------------|
| `require_tags` | list[str] | Asset MUST have all of these tags to be eligible. |
| `exclude_tags` | list[str] | Asset MUST NOT have any of these tags to be eligible. |
| `context` | str | Scheduling context this rule applies to (e.g. `"primetime"`, `"daytime"`, `"overnight"`). |

### DurationGateRule

Enforces minimum and/or maximum duration constraints for specific slot types.

| Field | Type | Description |
|-------|------|-------------|
| `min_duration_ms` | int | Minimum asset duration in ms. `0` = no minimum. |
| `max_duration_ms` | int | Maximum asset duration in ms. `0` = no maximum. |
| `slot_type` | str | Slot type this rule applies to (e.g. `"30min"`, `"60min"`, `"filler"`). |

### PolicyViolation

Structured output from policy evaluation. Every violation carries enough context to identify the rule that was violated and the asset that failed.

| Field | Type | Description |
|-------|------|-------------|
| `invariant_id` | str | The invariant ID governing this rule type (e.g. `"INV-POLICY-PURE-001"`). |
| `rule_type` | str | One of: `"repeat_window"`, `"frequency_cap"`, `"tag_eligibility"`, `"duration_gate"`. |
| `message` | str | Human-readable violation description. |
| `details` | dict | Machine-readable context: asset_id, rule parameters, observed values. |

### SchedulingContext

Contextual state passed to policy evaluation. Contains the information policies need to make decisions without performing I/O.

| Field | Type | Description |
|-------|------|-------------|
| `schedule_date` | date | The broadcast day being compiled. |
| `channel_id` | str | Channel identifier. |
| `air_history` | list[AirHistoryRecord] | Recent air history for repeat window and frequency cap evaluation. |
| `slot_type` | str | The slot type being filled (for duration gate evaluation). |
| `scheduling_context_name` | str | Named context (for tag eligibility evaluation, e.g. `"primetime"`). |

### AirHistoryRecord

A record of a past airing used for repeat window and frequency cap evaluation.

| Field | Type | Description |
|-------|------|-------------|
| `asset_id` | str | Asset identifier. |
| `series_id` | str | Series/show identifier. |
| `aired_date` | date | The broadcast day the asset aired. |
| `channel_id` | str | Channel the asset aired on. |

---

## Public API

### `evaluate_scheduling_policies`

```
evaluate_scheduling_policies(
    candidate_assets: list[Asset],
    policy: SchedulingPolicy,
    context: SchedulingContext,
) -> tuple[list[Asset], list[PolicyViolation]]
```

Evaluates all policy rules against the candidate asset list. Returns a tuple of (eligible assets, violations). Eligible assets are those that passed all policy rules. Violations list every rule failure across all candidates.

### `evaluate_repeat_window`

```
evaluate_repeat_window(
    asset: Asset,
    rules: list[RepeatWindowRule],
    context: SchedulingContext,
) -> list[PolicyViolation]
```

Checks a single asset against repeat window rules. Returns violations if the asset aired within the configured window.

### `evaluate_frequency_cap`

```
evaluate_frequency_cap(
    asset: Asset,
    rules: list[FrequencyCapRule],
    context: SchedulingContext,
) -> list[PolicyViolation]
```

Checks a single asset against frequency cap rules. Returns violations if the show has reached its daily cap.

### `evaluate_tag_eligibility`

```
evaluate_tag_eligibility(
    asset: Asset,
    rules: list[TagEligibilityRule],
    context: SchedulingContext,
) -> list[PolicyViolation]
```

Checks a single asset against tag eligibility rules applicable to the current scheduling context. Returns violations if tag requirements are not met.

### `evaluate_duration_gate`

```
evaluate_duration_gate(
    asset: Asset,
    rules: list[DurationGateRule],
    context: SchedulingContext,
) -> list[PolicyViolation]
```

Checks a single asset against duration gate rules applicable to the current slot type. Returns violations if the asset duration falls outside permitted bounds.

---

## Evaluation Semantics

### Evaluation Order

Policy rules MUST be evaluated in this order: (1) repeat window, (2) frequency cap, (3) tag eligibility, (4) duration gate. An asset excluded by an earlier rule type MUST still be evaluated by later rule types — all violations are collected, not short-circuited. This ensures complete violation reporting for operator diagnostics.

### Composition

All policy rule types are conjunctive: an asset MUST pass every applicable rule to remain eligible. Within a rule type, multiple rules are also conjunctive — an asset must satisfy all repeat window rules, all frequency cap rules, etc.

### Layering

Policy evaluation occurs after `LAW-ELIGIBILITY` gating. Policies MUST NOT re-check or override core eligibility. An asset that reaches policy evaluation has already been confirmed as `state=ready` and `approved_for_broadcast=true`. Policies add restrictions on top — they never relax them.

### Empty Policies

If a SchedulingPolicy has no rules (all rule lists are empty), all candidate assets pass and no violations are produced. An empty policy is valid and represents "no additional restrictions beyond core eligibility."

---

## Invariants

### INV-POLICY-PURE-001 — Policy evaluation is pure

`evaluate_scheduling_policies` and all per-rule evaluation functions MUST NOT mutate any input. They MUST NOT perform I/O, database queries, or filesystem access. All state needed for evaluation is passed as arguments.

### INV-POLICY-LAYERED-001 — Policies layer on top of LAW-ELIGIBILITY

Policies MUST NOT override, relax, or re-evaluate the core eligibility gate (`state=ready` AND `approved_for_broadcast=true`). Policies add restrictions; they do not grant eligibility.

### INV-POLICY-IDEMPOTENT-001 — Same inputs produce same violations

Given identical `candidate_assets`, `policy`, and `context`, `evaluate_scheduling_policies` MUST return identical eligible assets and identical violations. Evaluation MUST NOT depend on call order, global state, or non-deterministic sources.

### INV-POLICY-DSL-DECLARED-001 — Policies are declared in DSL YAML

All scheduling policies MUST originate from channel DSL YAML declarations compiled via DslScheduleService. No component may introduce, modify, or override scheduling policies outside of DSL compilation. Runtime code MUST NOT construct SchedulingPolicy objects from non-DSL sources.

### INV-POLICY-VIOLATION-STRUCTURED-001 — Violations carry structured context

Every PolicyViolation MUST carry: `invariant_id` (string, non-empty), `rule_type` (one of the four defined types), `message` (human-readable, non-empty), and `details` (dict with at minimum `asset_id`). Violations MUST NOT be bare strings, exceptions, or unstructured log messages.

---

## Edge Cases

| Condition | Result |
|-----------|--------|
| No candidate assets | Empty eligible list, no violations. |
| No policy rules (empty policy) | All candidates eligible, no violations. |
| All candidates violate repeat window | Empty eligible list, violations for each. |
| Asset has no tags, tag rule requires tags | Violation: missing required tags. |
| Asset duration exactly at min or max boundary | Eligible (boundaries are inclusive). |
| Multiple rule types violated by same asset | All violations reported, not just the first. |
| Air history is empty | Repeat window and frequency cap rules pass (no prior airings). |
| `max_per_day = 0` on frequency cap | Cap is unlimited; rule is skipped. |
| `min_duration_ms = 0` and `max_duration_ms = 0` | No duration constraint; rule is skipped. |

---

## Required Tests

- `server/tests/contracts/test_scheduling_policies.py`

---

## Enforcement Evidence

TODO
