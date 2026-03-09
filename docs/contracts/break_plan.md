# BreakPlan — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`, `LAW-IMMUTABILITY`

---

## Overview

BreakPlan is the authoritative break schedule produced by break detection and consumed by traffic fill. It is the sole boundary object that flows between the two stages. Break detection determines WHERE breaks occur. Traffic policy determines WHAT plays in those breaks. BreakPlan carries the former to the latter.

BreakPlan is produced exactly once per program execution. After creation, it is immutable. No downstream consumer may alter its opportunities, positions, weights, or budget.

This contract formalizes the structural guarantees of the BreakPlan object itself. It does not define how break opportunities are discovered (that is `break_detection.md`) or how traffic assets are selected to fill them (that is `traffic_policy.md`).

---

## Domain Object Definition

### BreakPlan

| Field | Type | Description |
|-------|------|-------------|
| `opportunities` | ordered list of BreakOpportunity | Break points in timeline order. May be empty. |
| `break_budget_ms` | non-negative integer | Total time available for breaks. May be zero or negative (bleed). |
| `program_runtime_ms` | positive integer | Assembled program runtime (from AssemblyResult). |
| `grid_duration_ms` | positive integer | Grid-allocated duration for this program. |

### BreakOpportunity (reference — defined in `break_detection.md`)

| Field | Type | Description |
|-------|------|-------------|
| `position_ms` | non-negative integer | Position in the program timeline where the break occurs. |
| `source` | `"chapter"` \| `"boundary"` \| `"algorithmic"` | How this break was identified. |
| `weight` | positive float | Relative share of the break budget this opportunity receives. |

This contract does not define or modify the BreakOpportunity schema. The authoritative definition is in `break_detection.md`.

### Budget Derivation

```
break_budget_ms = grid_duration_ms − program_runtime_ms
```

The budget is a derived value. It MUST equal the arithmetic difference between grid allocation and assembled runtime. It MUST NOT be computed from any other source.

### Budget Distribution

Each opportunity receives a share of the break budget proportional to its weight:

```
opportunity_budget_ms = floor(break_budget_ms * (opportunity.weight / sum_of_all_weights))
```

Rounding remainder is added to the last opportunity. The sum of all opportunity allocations MUST NOT exceed `break_budget_ms`.

---

## Relationship to Other Contracts

### `break_detection.md` — Producer

Break detection is the sole producer of BreakPlan. It discovers break opportunities, classifies them by source, assigns weights, computes the budget, and constructs the BreakPlan. All rules governing how opportunities are identified — priority model, protected zones, chapter markers, boundary seams, algorithmic placement — are defined in `break_detection.md`.

This contract does not redefine those rules. It governs the structural guarantees of the produced object.

### `traffic_policy.md` — Consumer (via traffic manager)

Traffic policy selects interstitial assets to fill each break opportunity. It receives the BreakPlan through the traffic manager and operates on one opportunity at a time. Traffic policy does not modify break positions, reorder opportunities, or alter the budget. It selects assets within the constraints already established by the BreakPlan.

### `traffic_dsl.md` — Configuration

Traffic DSL configures which assets are available and which policy rules apply. It does not interact with BreakPlan directly. The traffic manager bridges the BreakPlan (from break detection) and the TrafficPolicy (from DSL resolution).

---

## Invariants

### INV-BREAKPLAN-ORDERED-001 — Opportunities must be strictly ordered by position

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-GRID`

**Guarantee:** `opportunities` MUST be sorted in strictly ascending order by `position_ms`. No two opportunities MUST share the same `position_ms`.

**Violation:** A BreakPlan where `opportunities[i].position_ms >= opportunities[i+1].position_ms` for any valid index `i`.

---

### INV-BREAKPLAN-POSITIONS-BOUNDED-001 — Opportunity positions must fall within program runtime

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** Every opportunity MUST have `position_ms > 0` and `position_ms < program_runtime_ms`. Break positions at the program start (0) or at or beyond the program end are invalid.

**Violation:** A BreakOpportunity with `position_ms == 0`; a BreakOpportunity with `position_ms >= program_runtime_ms`.

---

### INV-BREAKPLAN-BUDGET-DERIVED-001 — Budget must equal grid minus runtime

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

**Guarantee:** `break_budget_ms` MUST equal `grid_duration_ms - program_runtime_ms`. The budget MUST NOT be set independently of these two fields.

**Violation:** A BreakPlan where `break_budget_ms != grid_duration_ms - program_runtime_ms`.

---

### INV-BREAKPLAN-ALLOCATION-BOUNDED-001 — Opportunity allocations must not exceed budget

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

**Guarantee:** The sum of all opportunity budget allocations (computed from weights) MUST NOT exceed `break_budget_ms`. Rounding remainder is added to the last opportunity only.

**Violation:** A weight-derived allocation that sums to more than `break_budget_ms`.

---

### INV-BREAKPLAN-IMMUTABLE-001 — BreakPlan is immutable after creation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

**Guarantee:** After break detection creates a BreakPlan, no downstream consumer MUST alter its fields. The `opportunities` list, each opportunity's `position_ms`, `source`, and `weight`, and the `break_budget_ms`, `program_runtime_ms`, and `grid_duration_ms` fields MUST remain unchanged throughout the pipeline.

**Violation:** Traffic fill that modifies `opportunities` in place; a consumer that appends, removes, or reorders opportunities; a consumer that adjusts `break_budget_ms`.

---

### INV-BREAKPLAN-SOLE-AUTHORITY-001 — BreakPlan is the sole authority for break placement

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Traffic fill MUST consume the BreakPlan to determine where breaks occur. Traffic fill MUST NOT compute break positions from episode duration, slot duration, grid parameters, or any other source. The BreakPlan is the only object that carries break placement authority between break detection and traffic fill.

**Violation:** A traffic fill function that computes break positions independently; a traffic fill that ignores the BreakPlan and creates its own break schedule; a traffic fill that reads break configuration from the channel DSL.

---

### INV-BREAKPLAN-EMPTY-VALID-001 — Empty opportunity list is a valid BreakPlan

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** A BreakPlan with an empty `opportunities` list is valid and MUST be accepted by all consumers without error. An empty plan occurs when the break budget is zero or negative, or when no valid break positions exist. Traffic fill MUST NOT treat an empty BreakPlan as an error condition.

**Violation:** A consumer that raises an exception or inserts fallback breaks when `opportunities` is empty.

---

## Pipeline Boundary

```
Program Assembly
       │
       ▼
  AssemblyResult
       │
       ▼
  Break Detection  ─────→  BreakPlan  ─────→  Traffic Manager
  (break_detection.md)     (this contract)     │
                                               ├── TrafficPolicy (traffic_policy.md)
                                               ├── Candidate list (traffic_dsl.md)
                                               │
                                               ▼
                                          Filled break segments
```

Break detection owns the left side of the boundary. It determines WHERE breaks occur, classifies them, assigns weights, and computes the budget.

Traffic fill owns the right side of the boundary. It determines WHAT plays in each break, using the policy rules and candidate lists.

BreakPlan is the boundary object. It carries authority from left to right. No authority flows in the reverse direction. Traffic fill MUST NOT feed information back to break detection or alter the BreakPlan to influence future break detection runs.

---

## Edge Cases

### Zero Break Budget

When `grid_duration_ms == program_runtime_ms`, `break_budget_ms` is zero. The `opportunities` list MUST be empty. Traffic fill receives an empty plan and inserts no traffic. This is normal for programs that exactly fill their grid allocation.

### Negative Break Budget (Bleed Programs)

When `program_runtime_ms > grid_duration_ms`, `break_budget_ms` is negative. The `opportunities` list MUST be empty. The program overruns its grid allocation. Traffic fill receives an empty plan and inserts no traffic. The negative budget value is informational — it records the overrun magnitude.

### Empty Opportunity List

A BreakPlan with an empty `opportunities` list and a positive `break_budget_ms` is valid. This occurs when no valid break positions exist (e.g., a short program where the protected zone eliminates all algorithmic candidates and no chapter markers or boundaries exist). The entire budget becomes post-content padding.

### Clustered Opportunities

Multiple opportunities may have positions within milliseconds of each other (e.g., clustered chapter markers). This is valid. Budget distribution via weights ensures that closely-spaced breaks receive proportionally small allocations. BreakPlan does not merge or deduplicate opportunities — that is break detection's responsibility (and break detection preserves all markers per `INV-BREAK-002`).

---

## Required Tests

- `pkg/core/tests/contracts/test_break_plan.py`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_break_plan_opportunities_ordered` | INV-BREAKPLAN-ORDERED-001 | Opportunities are in strictly ascending position_ms order. |
| `test_break_plan_no_duplicate_positions` | INV-BREAKPLAN-ORDERED-001 | No two opportunities share the same position_ms. |
| `test_break_plan_positions_within_runtime` | INV-BREAKPLAN-POSITIONS-BOUNDED-001 | All positions > 0 and < program_runtime_ms. |
| `test_break_plan_position_not_zero` | INV-BREAKPLAN-POSITIONS-BOUNDED-001 | No opportunity at position_ms == 0. |
| `test_break_plan_position_not_at_end` | INV-BREAKPLAN-POSITIONS-BOUNDED-001 | No opportunity at position_ms >= program_runtime_ms. |
| `test_break_budget_matches_runtime_difference` | INV-BREAKPLAN-BUDGET-DERIVED-001 | break_budget_ms == grid_duration_ms - program_runtime_ms. |
| `test_break_allocation_sum_within_budget` | INV-BREAKPLAN-ALLOCATION-BOUNDED-001 | Weight-derived allocations sum to <= break_budget_ms. |
| `test_break_plan_immutable_after_creation` | INV-BREAKPLAN-IMMUTABLE-001 | BreakPlan fields are unchanged after traffic fill consumes them. |
| `test_traffic_must_not_modify_break_positions` | INV-BREAKPLAN-IMMUTABLE-001 | Opportunity positions identical before and after traffic fill. |
| `test_break_plan_sole_authority_for_placement` | INV-BREAKPLAN-SOLE-AUTHORITY-001 | Traffic fill uses only BreakPlan opportunities, not independent computation. |
| `test_break_plan_allows_empty_opportunity_list` | INV-BREAKPLAN-EMPTY-VALID-001 | Empty BreakPlan accepted without error by traffic fill. |
| `test_break_plan_zero_budget_empty` | INV-BREAKPLAN-EMPTY-VALID-001 | Zero budget produces empty opportunities, accepted normally. |
| `test_break_plan_negative_budget_empty` | INV-BREAKPLAN-EMPTY-VALID-001 | Negative budget (bleed) produces empty opportunities, accepted normally. |

---

## Enforcement Evidence

TODO
