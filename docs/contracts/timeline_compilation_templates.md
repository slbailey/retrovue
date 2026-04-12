# Timeline Compilation Templates — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Overview

Block templates are named, reusable compilation recipes defined in channel YAML. A template specifies break *behavior* and continuity element *rules* for a content type or daypart. Templates are DSL-level configuration interpreted by the existing compilation pipeline — not new code entities.

Templates encode behavior, not duration. A single `sitcom` template handles 22-minute, 44-minute, and 60-minute content identically. The compiler adapts break count and duration dynamically based on content runtime.

### Authority Boundary

This contract owns:
- Template DSL syntax and semantics (the `templates:` YAML section)
- Break budget derivation formula
- `target_segment_minutes` semantics and break count derivation
- `overconstrained` / `underconstrained` policy definitions
- Template composition via `extends`
- Backward compatibility rules between `presentation:` and `template:`
- `max_duration_sec` pool selection semantics

This contract does NOT own:
- Break opportunity discovery (`break_detection.md`)
- Break structure internals (`break_structure.md`)
- Traffic asset selection (`traffic_policy.md`, `traffic_manager.md`)
- BreakPlan object guarantees (`break_plan.md`)

---

## Template DSL Syntax

Templates are defined under a top-level `templates:` key in channel YAML.

```yaml
templates:
  <name>:
    description: <string>              # Human-readable description.
    extends: <template_name>           # Optional. Inherit from another template.
    continuity:
      presentation:                    # Tier 1 — mandatory presentation elements.
        - type: <element_type>
          pool: <pool_name>
          max_duration_sec: <int>      # Pool selection filter, not truncation.
          duration_sec: <int>          # Fixed duration (mutually exclusive with max_duration_sec).
      optional:                        # Tier 3 — optional presentation elements.
        - type: <element_type>
          pool: <pool_name>
          max_duration_sec: <int>
          position: <before_content|after_content>
    breaks:
      strategy: <chapter_markers_preferred|synthetic|none|fill_all>
      fallback: <synthetic>            # Used when strategy is chapter_markers_preferred.
      target_segment_minutes: <int>    # Desired content segment length between breaks.
      min_segment_minutes: <int>       # Optional minimum segment length.
      bumpers:
        to_break: { pool: <name>, duration_sec: <int> }
        from_break: { pool: <name>, duration_sec: <int> }
      station_id:
        pool: <name>
        duration_sec: <int>
      traffic_profile: <profile_name>
    overconstrained: <bleed|reject>    # Policy when content exceeds slot.
    underconstrained: <expand_breaks>  # Policy when content is shorter than slot.
    trailing:                          # Optional post-content interstitial block.
      - type: interstitial_block
        traffic_profile: <name>
```

### Template Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | No | Human-readable description. |
| `extends` | string | No | Parent template name. Inherits all fields; child overrides parent. |
| `continuity.presentation` | list | No | Tier 1 mandatory continuity elements. |
| `continuity.optional` | list | No | Tier 3 optional continuity elements. |
| `breaks.strategy` | string | Yes (if `breaks` present) | Break placement strategy. |
| `breaks.target_segment_minutes` | int | When strategy is `chapter_markers_preferred` or `synthetic` | Target content segment length for break count derivation. |
| `overconstrained` | string | No (default: `bleed`) | Policy for content longer than slot. |
| `underconstrained` | string | No (default: `expand_breaks`) | Policy for content shorter than slot. |

---

## Break Budget Derivation

The break budget is derived, not fixed:

```
break_budget = scheduled_duration - content_duration - presentation_duration
```

Where:
- `scheduled_duration` = grid slot allocation for this block
- `content_duration` = Tier 0 primary content runtime
- `presentation_duration` = sum of Tiers 1–3 continuity element durations

Break time expands to consume the full break budget. There is no "standard break length." The budget adapts to actual content runtime. This is compatible with and strengthens `INV-BREAKPLAN-BUDGET-DERIVED-001`, which defines the same derivation at the BreakPlan level.

---

## Break Count Derivation

Break count is derived from `target_segment_minutes` and content runtime:

```
break_count = floor(content_duration_minutes / target_segment_minutes)
```

The template specifies break *density* (via `target_segment_minutes`), not break *count*. The compiler derives the count. This separation ensures a single template handles variable content runtimes:

| Content Runtime | target_segment_minutes=11 | Expected Breaks |
|-----------------|---------------------------|-----------------|
| ~22 min         | 22/11 = 2                 | ~2              |
| ~42 min         | 42/11 ≈ 3.8              | ~4              |
| ~85 min         | 85/11 ≈ 7.7              | ~5 (capped)     |

Break count derivation is subject to chapter marker positions when available. Chapter markers take priority per the existing `INV-BREAK-002` priority model.

---

## Overconstrained / Underconstrained Policies

### Overconstrained (content longer than slot)

- **`bleed`** (default): Content extends into adjacent slots. No breaks injected. Adjacent blocks shift. Compatible with existing `INV-BLEED-NO-GAP-001`.
- **`reject`**: Compilation fails with a clear error. Operator must resize the slot or choose different content.

Mode is set per-template.

### Underconstrained (content shorter than slot)

Break budget absorbs the difference per `INV-BREAK-BUDGET-DERIVED-001`. If break budget exceeds maximum break density (more break time than content time), the compiler:
1. Inserts Tier 3 optional presentation elements first
2. Expands breaks
3. Inserts pad

**Extreme underrun** (content < 50% of slot): compiler emits a warning. Operator should review the slot allocation.

---

## Template Composition (`extends`)

Templates may inherit from a parent template using the `extends` keyword:

```yaml
templates:
  movie_broadcast:
    breaks:
      strategy: synthetic
      target_segment_minutes: 20

  creature_feature:
    extends: movie_broadcast
    continuity:
      presentation:
        - type: host_intro
          pool: creature_host_intros
          max_duration_sec: 120
```

Resolution rules:
- Child fields override parent fields at the same key path.
- List-type fields (`continuity.presentation`, `continuity.optional`) are replaced entirely, not merged.
- `extends` chains are resolved depth-first (grandparent → parent → child).
- Circular `extends` references MUST be rejected at YAML validation time.

---

## Backward Compatibility

The `presentation:` section (existing DSL) and `template:` reference (new) coexist in channel YAML:

- When a schedule block references a template via `template: <name>`, the template's continuity elements replace the program-level `presentation:` for that block.
- When both `presentation:` and `template:` are present on a block, `template:` wins.
- When neither is present, the block has no continuity elements (existing behavior for bare programs).
- Channels without a `templates:` section continue to work unchanged.

---

## Continuity Element `max_duration_sec` Semantics

`max_duration_sec` on a continuity element entry is a **pool selection filter**, not a truncation directive. The compiler selects assets from the referenced pool whose duration is ≤ `max_duration_sec`. Selected assets play at their full native duration.

An asset whose duration exceeds `max_duration_sec` is excluded from the candidate set. No asset is truncated to fit.

---

## Invariants

### INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001

Templates define break *placement strategy* and *continuity element rules* — not fixed break counts or durations. A template MUST NOT contain `break_count`, `break_duration_sec`, or `grid_slots` fields. Break count and duration are derived by the compiler from content runtime and template parameters.

### INV-BREAK-BUDGET-DERIVED-001

Break budget MUST equal `scheduled_duration - content_duration - presentation_duration`. The budget MUST NOT be set independently. This invariant strengthens `INV-BREAKPLAN-BUDGET-DERIVED-001` by making the derivation explicit at the template compilation entry point, before the BreakPlan object is constructed.

### INV-BREAK-COUNT-DURATION-SEPARATED-001

Break count (placement) and break duration (budget distribution) MUST be determined independently. The template specifies placement strategy. The compiler determines duration by distributing the derived break budget across placed breaks. No template field conflates count with duration.

### INV-BREAK-DENSITY-SCALES-001

Break density MUST scale with content runtime via `target_segment_minutes`. A template with `target_segment_minutes: 11` applied to 22-minute content MUST produce approximately 2 breaks; applied to 44-minute content MUST produce approximately 4 breaks. The compiler derives `floor(content_duration / target_segment_minutes)` as the initial break count, subject to chapter marker positions.

### INV-BREAK-EXPAND-TO-FILL-001

Breaks MUST NOT be fixed-length. After break positions are determined, the break budget MUST be distributed across all breaks. Residual micro-gaps (< 1 segment) after traffic fill are handled by `INV-BREAK-PAD-DISTRIBUTED-001`.

### INV-CONFORMANCE-MANDATORY-001

The compiled playout plan MUST exactly match the scheduled block duration, within frame tolerance (40ms per `INV-BLOCK-SEGMENT-CONSERVATION-001`):

```
sum(all_segment_durations) == scheduled_block_duration ± 40ms
```

Conformance is verified at every pipeline stage.

### INV-CONTINUITY-DURATION-FILTER-001

`max_duration_sec` on a continuity element MUST be a pool selection filter, not a truncation directive. Assets with duration > `max_duration_sec` are excluded from the candidate set. Selected assets play at their full native duration. No asset is truncated.

---

## Relationship to Existing Contracts

### `break_detection.md`

Templates feed configuration into break detection. The `strategy` and `target_segment_minutes` fields parameterize how break detection discovers break opportunities. Templates do not bypass the break detection pipeline — they configure it.

### `break_plan.md`

The break budget derived by template compilation flows into the BreakPlan object. `INV-BREAK-BUDGET-DERIVED-001` (this contract) and `INV-BREAKPLAN-BUDGET-DERIVED-001` (`break_plan.md`) express the same derivation at different pipeline stages. They are complementary, not conflicting.

### `break_structure.md`

Template `bumpers` and `station_id` configuration flows into BreakStructure construction. The template defines the configuration; BreakStructure owns the internal slot ordering. No conflict.

### `channel_dsl.md`

Templates extend the channel DSL vocabulary. The `templates:` section is a new top-level key. All existing DSL invariants (`INV-DSL-*`) continue to apply. Template continuity elements map to the existing tier model (Tier 1 presentation, Tier 3 optional).

### `INV-BLOCK-SEGMENT-CONSERVATION-001`

`INV-CONFORMANCE-MANDATORY-001` strengthens segment conservation by making it explicit at the compilation entry point. The tolerance (40ms) is identical.

### `INV-SC-BBL-CUTOVER-001`

No conflict. Templates operate within the existing BBL/scheduling architecture. Template compilation is a configuration layer above the existing compilation pipeline.

---

## Required Tests

- `server/tests/contracts/test_timeline_compilation_templates.py`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_template_no_break_count_field` | INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001 | Template YAML with `break_count` field is rejected. |
| `test_template_no_break_duration_field` | INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001 | Template YAML with `break_duration_sec` field is rejected. |
| `test_template_no_grid_slots_field` | INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001 | Template YAML with `grid_slots` field is rejected. |
| `test_template_applies_to_varying_runtimes` | INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001 | Same template produces valid plans for 22-min, 44-min, and 60-min content. |
| `test_break_budget_equals_derived_formula` | INV-BREAK-BUDGET-DERIVED-001 | `break_budget == scheduled_duration - content_duration - presentation_duration`. |
| `test_break_budget_includes_presentation` | INV-BREAK-BUDGET-DERIVED-001 | Presentation element durations reduce the break budget. |
| `test_break_count_independent_of_duration` | INV-BREAK-COUNT-DURATION-SEPARATED-001 | Changing break budget does not change break count; changing `target_segment_minutes` does not change individual break duration. |
| `test_break_density_22min` | INV-BREAK-DENSITY-SCALES-001 | `target_segment_minutes=11` with 22-min content produces ~2 breaks. |
| `test_break_density_44min` | INV-BREAK-DENSITY-SCALES-001 | `target_segment_minutes=11` with 44-min content produces ~4 breaks. |
| `test_break_density_90min` | INV-BREAK-DENSITY-SCALES-001 | `target_segment_minutes=20` with 85-min content produces 4-5 breaks. |
| `test_breaks_expand_to_fill_budget` | INV-BREAK-EXPAND-TO-FILL-001 | Sum of break durations equals break budget (no leftover). |
| `test_breaks_not_fixed_length` | INV-BREAK-EXPAND-TO-FILL-001 | Different break budgets produce different break durations for the same break count. |
| `test_conformance_exact_match` | INV-CONFORMANCE-MANDATORY-001 | `sum(segments) == scheduled_duration ± 40ms` for a compiled block. |
| `test_conformance_rejects_drift` | INV-CONFORMANCE-MANDATORY-001 | Block where segments sum to > 40ms drift from scheduled duration is rejected. |
| `test_max_duration_sec_filters_pool` | INV-CONTINUITY-DURATION-FILTER-001 | Asset with duration > `max_duration_sec` excluded from candidates. |
| `test_max_duration_sec_no_truncation` | INV-CONTINUITY-DURATION-FILTER-001 | Selected asset plays at full native duration, not truncated to `max_duration_sec`. |
| `test_extends_inherits_parent` | Template composition | Child template inherits parent break strategy and bumper config. |
| `test_extends_child_overrides` | Template composition | Child field overrides parent at same key path. |
| `test_extends_circular_rejected` | Template composition | Circular `extends` reference rejected at validation. |
| `test_template_wins_over_presentation` | Backward compatibility | When both `presentation:` and `template:` present, template continuity is used. |
| `test_no_template_section_unchanged` | Backward compatibility | Channel without `templates:` section compiles identically to current behavior. |
| `test_overconstrained_bleed` | Overconstrained policy | Overconstrained block with `bleed` policy extends into adjacent slots. |
| `test_overconstrained_reject` | Overconstrained policy | Overconstrained block with `reject` policy fails compilation with error. |

---

## Enforcement Evidence

TODO
