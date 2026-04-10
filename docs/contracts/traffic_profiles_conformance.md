# Traffic Profiles & Conformance Policy — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Overview

Traffic profiles bind block-scoped traffic fill behavior to template configuration. Conformance policy governs how the compiler resolves the mismatch between content runtime and grid slot duration. Together they close the gap between template-declared structure and runtime fill.

This contract defines:
- Per-template `traffic_profile` reference semantics and resolution to TrafficManager
- Block-scoped traffic policy evaluation (content-type-aware fill)
- Overconstrained conformance policy (`bleed` vs `reject`)
- Underconstrained conformance policy (budget absorption cascade)

### Authority Boundary

This contract owns:
- `traffic_profile` field semantics on template `breaks` and `trailing` sections
- Conformance policy evaluation rules (overconstrained and underconstrained)
- Block-scoped traffic profile resolution order
- Underrun warning threshold and behavior

This contract does NOT own:
- TrafficProfile YAML schema or profile field definitions (`traffic_dsl.md`)
- TrafficPolicy runtime candidate evaluation (`traffic_policy.md`)
- Break budget derivation formula (`timeline_compilation_templates.md`, `INV-BREAK-BUDGET-DERIVED-001`)
- Break detection or placement (`break_detection.md`)
- Tier displacement rules (`block_assembly_tiers.md`, `INV-TIER-DISPLACEMENT-001`)
- Bleed compaction mechanics (`INV-BLEED-NO-GAP-001`)
- Tier 3 optional presentation budget interaction (`INV-TIER3-BUDGET-BEFORE-FILL-001`)

---

## Traffic Profile Reference Semantics

### Template-Level Declaration

A template MAY declare a `traffic_profile` field in its `breaks` section:

```yaml
templates:
  sitcom:
    breaks:
      strategy: chapter_markers_preferred
      target_segment_minutes: 11
      traffic_profile: sitcom_promos
    overconstrained: bleed
    underconstrained: expand_breaks

  movie_broadcast:
    breaks:
      strategy: synthetic
      target_segment_minutes: 20
      traffic_profile: movie_trailers
    trailing:
      - type: interstitial_block
        traffic_profile: movie_post_roll
```

### Resolution Order

Traffic profile resolution for a compiled block follows this precedence:

1. **Block-level override:** `traffic_profile` on the schedule block entry (per `traffic_dsl.md`).
2. **Template-level profile:** `breaks.traffic_profile` from the block's resolved template.
3. **Channel default:** `traffic.default` from the channel YAML (per `traffic_dsl.md`).

The first non-null value wins. If all three are null, compilation MUST fail with a clear error — every block that contains breaks MUST have a resolvable traffic profile.

### Reference Validation

The `traffic_profile` value MUST reference a named profile in `traffic.profiles`. An unresolvable reference MUST be rejected at YAML validation time, before compilation begins. This is consistent with `INV-TRAFFIC-DSL-PROFILE-REF-VALID-001`.

### Threading to TrafficManager

The resolved traffic profile name is carried on each break structure within the compiled block. When TrafficManager fills breaks, it MUST resolve the profile name to the corresponding `TrafficPolicy` object and apply that policy's candidate evaluation rules. TrafficManager MUST NOT infer traffic policy from content type, template name, or any other implicit signal.

---

## Block-Scoped Traffic Policy Evaluation

Traffic profiles enable content-type-aware fill without hardcoding rules in the traffic engine:

| Template | traffic_profile | Effect |
|----------|----------------|--------|
| `movie_broadcast` | `movie_trailers` | Breaks filled from trailer pools per the `movie_trailers` profile. |
| `sitcom` | `sitcom_promos` | Breaks filled from promo pools per the `sitcom_promos` profile. |
| `creature_feature` | `movie_trailers` | Inherits `movie_broadcast` profile via `extends`. |
| `late_night` | `late_night_mix` | Custom pool mix for late-night content. |

The profile determines which pools are eligible, their weights, rotation strategy, and cooldowns. The template does NOT contain traffic policy details — it contains a profile reference. All policy details live in `traffic.profiles` (governed by `traffic_dsl.md`).

### Trailing Interstitial Blocks

A template MAY declare a `trailing` section with interstitial blocks that appear after primary content and after all breaks. Each trailing entry MAY declare its own `traffic_profile`, independent of the `breaks.traffic_profile`. This allows post-content fill (e.g., post-roll promos) to use a different pool mix than mid-content breaks.

Trailing block traffic profile resolution:
1. `trailing[].traffic_profile` (entry-level override).
2. `breaks.traffic_profile` (template break profile as fallback).
3. `traffic.default` (channel default).

---

## Overconstrained Conformance Policy

An overconstrained block is one where `content_duration + presentation_duration > scheduled_duration`. The break budget would be negative.

### Policy Modes

| Mode | Behavior | Default |
|------|----------|---------|
| `bleed` | Content extends past the slot boundary. Adjacent blocks are compacted forward. No breaks are injected into the bleed region. | Yes |
| `reject` | Compilation fails with a structured error identifying the block, content duration, and slot duration. | No |

### `bleed` Mode

When `overconstrained: bleed` (the default):

1. The block's `slot_duration_sec` is extended to `content_duration + presentation_duration` (zero break budget).
2. Bleed compaction is handled by `INV-BLEED-NO-GAP-001` — subsequent blocks are pushed forward to maintain contiguity.
3. No break structures are generated for the overconstrained block. Break count is zero.
4. `INV-CONFORMANCE-MANDATORY-001` is satisfied because `sum(all_segment_durations) == extended_slot_duration`.
5. Tier 3 optional elements (if declared) are included in the extended duration. They are structural per `INV-TIER3-COMPILE-RESOLUTION-001`.
6. Tier 2 obligations that trigger within the block's time range are still honored per `INV-CLOCK-OBLIGATIONS-OVERRIDE-001`. Obligation duration is added to the extended slot.

### `reject` Mode

When `overconstrained: reject`:

1. The compiler MUST raise a `CompileError` before emitting any blocks for the affected broadcast day.
2. The error MUST include: block identifier, template name, content duration, presentation duration, scheduled slot duration, and the deficit.
3. No partial compilation output is produced. The operator MUST resize the slot or select shorter content.

### Per-Template Setting

`overconstrained` is a per-template field (default: `bleed`). Different templates within the same channel MAY have different overconstrained policies. A `movie_broadcast` template might use `bleed` (movies often exceed 2-hour slots), while an `infomercial` template might use `reject` (strict timekeeping required).

Template inheritance via `extends` applies: a child template inherits the parent's `overconstrained` unless overridden.

---

## Underconstrained Conformance Policy

An underconstrained block is one where `content_duration + presentation_duration < scheduled_duration`. The break budget is positive.

### Budget Absorption Cascade

The break budget absorbs the difference. When the break budget is larger than what traffic fill can consume, the compiler applies this cascade:

1. **Tier 3 optional elements first:** If the template declares `continuity.optional` elements, they are included and their duration is deducted from the break budget per `INV-TIER3-BUDGET-BEFORE-FILL-001`.
2. **Traffic fill:** Remaining break budget is distributed across placed breaks. TrafficManager fills breaks per the resolved traffic profile. Fill uses `duration_strategy: pack` by default — multiple assets per break to maximize budget utilization.
3. **Expand breaks:** If traffic fill does not consume the full break budget (insufficient eligible assets, cooldown constraints), the residual is distributed as pad across breaks per `INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001`.
4. **Pad:** Any remaining micro-gaps (< 1 segment duration) after traffic fill are filled with pad per `INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001`.

This cascade is the existing behavior formalized. `INV-BREAK-BUDGET-DERIVED-001` defines the budget derivation. `INV-BREAK-EXPAND-TO-FILL-001` defines that breaks expand to fill the budget. This contract clarifies the priority ordering when the budget is large.

### Extreme Underrun Warning

When `content_duration < 0.5 * scheduled_duration` (content occupies less than 50% of the slot), the compiler MUST emit a structured warning. The warning includes: block identifier, template name, content duration, slot duration, and utilization percentage.

The warning does NOT halt compilation. The block is still compiled with the full budget absorption cascade. The warning is informational — it indicates the operator should review the slot allocation.

### Per-Template Setting

`underconstrained` is a per-template field (default: `expand_breaks`). The value `expand_breaks` triggers the full cascade described above. No other values are currently defined.

Template inheritance via `extends` applies.

---

## Relationship to Existing Contracts

### `timeline_compilation_templates.md` (Phase A)

This contract extends the overconstrained/underconstrained policy definitions from `timeline_compilation_templates.md` with:
- Traffic profile threading semantics (how the profile reference flows to TrafficManager)
- Block-scoped policy evaluation details
- Trailing interstitial block profile resolution
- Extreme underrun warning threshold

The template DSL syntax (`overconstrained`, `underconstrained`, `traffic_profile` fields) is defined in `timeline_compilation_templates.md`. This contract defines the evaluation semantics.

### `block_assembly_tiers.md` (Phase D)

Tier 3 optional elements participate in the underconstrained cascade as the first absorption step. This is consistent with `INV-TIER3-BUDGET-BEFORE-FILL-001`: Tier 3 duration is deducted before Tier 4 traffic fill.

### `traffic_dsl.md`

TrafficProfile schema and channel-level default/override semantics are owned by `traffic_dsl.md`. This contract adds the template-level resolution step between block-level and channel-level.

### `INV-BLEED-NO-GAP-001`

Bleed compaction mechanics are unchanged. This contract's `bleed` mode triggers the existing compaction pipeline. No new compaction logic is introduced.

### `INV-CONFORMANCE-MANDATORY-001`

Conformance is always satisfied:
- Overconstrained `bleed`: slot is extended, sum matches extended slot.
- Overconstrained `reject`: no block emitted.
- Underconstrained: budget absorption cascade fills the slot.

### `INV-BREAK-BUDGET-DERIVED-001`

Budget derivation formula is unchanged: `break_budget = scheduled_duration - content_duration - presentation_duration`. This contract defines what happens when the budget is negative (overconstrained) or large (underconstrained).

---

## Invariants

### INV-OVERCONSTRAINED-POLICY-001 — Explicit per-template overconstrained conformance

Every template MUST declare or inherit an `overconstrained` policy (`bleed` or `reject`). When no explicit value is set, `bleed` is the default. The compiler MUST evaluate the declared policy when `content_duration + presentation_duration > scheduled_duration`. No silent truncation, no silent gap insertion, and no implicit fallback behavior is permitted.

### INV-TRAFFIC-PROFILE-RESOLVED-001 — Traffic profile resolution for every break-bearing block

Every compiled block that contains break structures MUST have a resolved traffic profile. Resolution follows the precedence: block-level override > template `breaks.traffic_profile` > channel `traffic.default`. An unresolvable profile MUST fail at validation time. TrafficManager MUST NOT infer traffic policy from content type or template name.

### INV-UNDERRUN-WARNING-001 — Extreme underrun emits structured warning

When `content_duration < 0.5 * scheduled_duration`, the compiler MUST emit a structured warning containing block identifier, template name, content duration, slot duration, and utilization percentage. The warning MUST NOT halt compilation.

---

## Required Tests

- `pkg/core/tests/contracts/test_traffic_profiles_conformance.py`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_overconstrained_bleed_extends_slot` | INV-OVERCONSTRAINED-POLICY-001 | Block with `bleed` policy and content > slot gets extended slot, zero breaks. |
| `test_overconstrained_reject_raises_error` | INV-OVERCONSTRAINED-POLICY-001 | Block with `reject` policy and content > slot raises `CompileError` with structured details. |
| `test_overconstrained_default_is_bleed` | INV-OVERCONSTRAINED-POLICY-001 | Template without explicit `overconstrained` defaults to `bleed`. |
| `test_overconstrained_per_template_independent` | INV-OVERCONSTRAINED-POLICY-001 | Two templates with different policies in same channel compile independently. |
| `test_overconstrained_inherits_via_extends` | INV-OVERCONSTRAINED-POLICY-001 | Child template inherits parent's `overconstrained` policy. |
| `test_overconstrained_child_overrides_parent` | INV-OVERCONSTRAINED-POLICY-001 | Child template overrides parent's `overconstrained` with `reject`. |
| `test_traffic_profile_resolved_from_template` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Block with template `traffic_profile` resolves to that profile. |
| `test_traffic_profile_block_override_wins` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Block-level `traffic_profile` overrides template-level. |
| `test_traffic_profile_falls_back_to_channel_default` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Block with no template or block-level profile uses channel default. |
| `test_traffic_profile_missing_fails_validation` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Block with breaks but no resolvable profile fails at validation. |
| `test_traffic_profile_invalid_reference_fails` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Template referencing nonexistent profile fails YAML validation. |
| `test_traffic_profile_carried_on_break_structure` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Resolved profile name is present on each break structure in compiled output. |
| `test_trailing_block_own_profile` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Trailing interstitial block uses its own `traffic_profile` when declared. |
| `test_trailing_block_fallback_to_breaks_profile` | INV-TRAFFIC-PROFILE-RESOLVED-001 | Trailing block without own profile falls back to `breaks.traffic_profile`. |
| `test_underrun_warning_below_50_pct` | INV-UNDERRUN-WARNING-001 | Content at 40% of slot emits structured warning with correct fields. |
| `test_underrun_no_warning_above_50_pct` | INV-UNDERRUN-WARNING-001 | Content at 60% of slot emits no warning. |
| `test_underrun_warning_does_not_halt` | INV-UNDERRUN-WARNING-001 | Block with extreme underrun still compiles successfully. |
| `test_underrun_budget_cascade_tier3_first` | INV-UNDERRUN-WARNING-001 | Underconstrained block with Tier 3 elements deducts them before traffic fill. |

---

## Enforcement Evidence

TODO
