# Traffic Manager — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Overview

The traffic manager is the orchestrator that fills break opportunities with interstitial assets. It sits between break detection and playout, consuming a BreakPlan and producing filled break segments.

The traffic manager does not decide WHERE breaks occur — that authority belongs to break detection (`break_detection.md`) via the BreakPlan (`break_plan.md`). The traffic manager does not decide HOW candidates are filtered — that authority belongs to the traffic policy engine (`traffic_policy.md`). The traffic manager does not decide WHAT assets are available — that authority belongs to the resolved inventory (`traffic_dsl.md`).

The traffic manager's sole responsibility is orchestrating the fill loop: iterating over break opportunities in order, passing the full candidate pool and remaining duration to the traffic policy for selection, packing selected assets into each break, distributing leftover time as inter-spot pad, and recording play history for rotation advancement.

The traffic manager trusts that the BreakPlan never places breaks inside primary content — that guarantee is enforced upstream by break detection (`INV-BREAK-012`).

### Authority Boundary

This contract owns:
- Break fill orchestration: iterating opportunities, packing assets, advancing rotation
- Pad distribution between spots within filled breaks
- Filler fallback when no interstitials are available
- Play history accumulation across breaks within a block
- Exact duration accounting per break and across all breaks
- Late-bind timing (fill at feed time, not compile time)

This contract does NOT own:
- Break opportunity identification or placement (`break_detection.md`, `break_plan.md`)
- Candidate filtering, cooldown, cap, or rotation logic (`traffic_policy.md`)
- Inventory resolution or profile selection (`traffic_dsl.md`)
- BreakPlan structure or immutability guarantees (`break_plan.md`)

---

## Inputs and Outputs

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| BreakPlan | `break_detection.detect_breaks()` | Ordered break opportunities with budget. Immutable. |
| TrafficPolicy | Resolved from `traffic_dsl.md` profile | Filtering and rotation rules. |
| Candidate list | Resolved from `traffic_dsl.md` inventories | Materialized interstitial assets available for selection. |
| Play history | `traffic_play_log` table | Historical plays for cooldown and cap evaluation. |
| Filler URI + duration | Channel configuration | Static fallback filler file. |

### Outputs

| Output | Description |
|--------|-------------|
| Filled segments | Ordered list of `ScheduledSegment` replacing each filler placeholder. |
| Updated play history | New `PlayRecord` entries appended for selected assets. |

---

## Fill Algorithm

### Structure Expansion

When a `BreakConfig` is provided (resolved from `traffic.break_config` in the channel YAML by `traffic_dsl.resolve_break_config()`), the traffic manager calls `build_break_structure()` from `break_structure.md` to expand each filler placeholder into typed slots. The BreakStructure determines the break's internal shape: optional bumpers, a time-based interstitial pool, and an optional station ID. When no `BreakConfig` is provided, the traffic manager uses legacy flat-fill behavior (all filler duration goes to the interstitial fill loop directly).

Each slot is then filled according to its `fill_rule`:
- `"bumper"` — a bumper asset is selected from the asset library filtered to `interstitial_type="bumper"`. If no bumper is available, the slot's duration is added to the interstitial pool.
- `"traffic"` — the existing interstitial fill loop runs against the slot's duration budget.

### Bumper Selection

Bumper assets are queried from the asset library with a type filter restricting candidates to `interstitial_type="bumper"`. The first eligible bumper whose duration does not exceed the slot budget is selected. If no eligible bumper exists, the bumper slot degrades: its duration is merged into the adjacent interstitial pool. This degradation is not an error.

Bumper selection does not use the traffic policy engine. Bumpers are not subject to cooldown, daily caps, or rotation rules.

### Per-Break Fill Loop

For each break opportunity (processed in BreakPlan order):

1. Compute the break's allocated duration from the BreakPlan budget and opportunity weight.
2. Call `build_break_structure()` to produce typed slots from the allocated duration.
3. For each slot in the BreakStructure:
   - If `fill_rule == "bumper"`: select a bumper asset. On failure, merge duration into interstitial pool.
   - If `fill_rule == "traffic"`: run the interstitial fill loop (steps 4–6).
4. Pass the full candidate pool, the TrafficPolicy, the current play history, and the remaining duration to `select_next()` from `traffic_policy.md`. Duration eligibility (candidate must fit within remaining time) is a policy concern, not a traffic manager concern.
5. If `select_next()` returns a candidate:
   - Append the asset to the break's pick list.
   - Record a `PlayRecord` so rotation advances within the block.
   - Subtract the asset's duration from remaining time.
   - Repeat from step 4 until the pool is full or no candidate is selected.
6. If `select_next()` returns `None`: stop filling this pool.

### Pad Distribution

Pad is a timing correction mechanism, not a content strategy. After packing spots into the interstitial pool, leftover time is distributed as evenly-spaced pad segments between spots.

```
gap_ms    = allocated_ms - filled_ms
base_pad  = gap_ms // num_items
extra     = gap_ms % num_items
```

Extra milliseconds are distributed one per item, applied to the last items first. The resulting segment sequence is: `[spot, pad, spot, pad, ..., spot, pad]`.

Pad is only emitted when at least one spot was selected. It fills the sub-second to few-second gaps between spots that arise from imperfect duration matching.

### Filler Fallback

When no spots were selected for the interstitial pool (no asset library, empty candidate list, or all candidates excluded by policy), the traffic manager falls back to the static filler file. The pool is filled by sequentially playing through the filler file, wrapping at the end when the filler is shorter than the pool.

Filler fallback produces content (the filler video loop), not pad. This is the distinction:

- **Spots selected, leftover time** → pad (timing correction between spots)
- **No spots selected** → filler file loop (content fallback)

Filler fallback is a degraded mode. It MUST NOT be treated as an error. It MUST produce segments that exactly fill the pool duration.

### Play History Accumulation

Play history is accumulated across breaks within a single block. When a candidate is selected for break N, its `PlayRecord` is visible during selection for break N+1. This ensures rotation advances within a block and the same asset is not repeated in consecutive breaks (subject to cooldown rules).

The traffic manager copies the caller's play history before mutation. It MUST NOT mutate the caller's original list.

---

## Invariants

### INV-TRAFFIC-FILL-STRUCTURED-001 — Filler placeholders must be expanded through BreakStructure

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** When `fill_ad_blocks()` encounters a filler placeholder, it MUST call `build_break_structure()` to obtain typed slots before filling. The traffic manager MUST NOT fill the placeholder as a flat time budget. Bumper slots MUST be filled with bumper assets (or degraded to interstitial pool on failure). Interstitial slots MUST be filled via the traffic policy engine. The final segment sequence MUST reflect the BreakStructure slot ordering.

**Violation:** A traffic manager that fills a filler placeholder without consulting BreakStructure; a traffic manager that places interstitial assets in bumper slot positions; a filled break whose segment order does not correspond to the BreakStructure slot sequence.

---

### INV-TRAFFIC-FILL-BUMPER-DEGRADE-001 — Unfilled bumper slots degrade to interstitial pool

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** When no eligible bumper asset is available for a bumper slot, the slot's duration MUST be added to the interstitial pool. The bumper slot MUST NOT be left empty, padded, or filled with the static filler file. Budget is conserved: the total break duration is unchanged.

**Violation:** A bumper slot that produces a zero-duration gap; a bumper slot filled with a non-bumper asset without merging into the interstitial pool; a break whose total filled duration changes due to bumper unavailability.

---

### INV-TRAFFIC-FILL-EXACT-001 — Break fill must produce exact duration

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

**Guarantee:** The sum of all segment durations (assets + pads) produced for a single break MUST exactly equal the break's allocated duration. No frames may be unaccounted for. No frames may overflow the allocation.

**Violation:** A filled break where `sum(segment.duration_ms) != allocated_ms`.

---

### INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001 — Leftover time distributed as inter-spot pads

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

**Guarantee:** When assets do not exactly fill a break, leftover time MUST be distributed as pad segments interleaved between spots. Pad distribution MUST be even: `base_pad = gap // N`, with remainder applied one millisecond per item to the last items. All leftover time MUST NOT be lumped at the end of the break.

**Violation:** A break with 3 spots and 2000ms leftover that produces one 2000ms pad at the end instead of three ~667ms pads between spots.

---

### INV-TRAFFIC-FILL-ORDER-001 — Opportunities must be filled in BreakPlan order

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** The traffic manager MUST process break opportunities in the order they appear in `BreakPlan.opportunities`. It MUST NOT reorder, skip, or selectively fill opportunities. Every opportunity receives a fill attempt, even if the result is pad-only.

**Violation:** A traffic manager that fills the last break before the first; a traffic manager that skips an opportunity because it has a small weight.

---

### INV-TRAFFIC-FILL-NO-INVENT-001 — Traffic fill must not invent break positions

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** The traffic manager MUST only fill breaks at positions defined in the BreakPlan. It MUST NOT create additional break positions, insert interstitials between content segments at positions not in the BreakPlan, or split content segments to create ad insertion points.

**Violation:** A traffic fill that inserts a commercial at a position not present in `BreakPlan.opportunities`; a traffic fill that creates a break between two content segments when no boundary opportunity exists.

---

### INV-TRAFFIC-FILL-ROTATION-ADVANCES-001 — Rotation advances across breaks within a block

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

**Guarantee:** When an asset is selected for a break, a `PlayRecord` MUST be appended to the working history before the next break is filled. This ensures `select_next()` sees the selection and advances rotation. The same asset MUST NOT be selected for consecutive breaks unless it is the only eligible candidate.

**Violation:** A block with 3 breaks that plays the same promo in all 3 breaks when other eligible promos exist; a traffic manager that resets play history between breaks.

---

### INV-TRAFFIC-FILL-LATE-BIND-001 — Traffic fill occurs at feed time

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** Traffic fill MUST occur at feed time (~30 minutes before air), not at schedule compile time. The schedule compiler MUST produce blocks with empty filler placeholders. The traffic manager fills those placeholders against current play history when the block is queued for playout.

**Violation:** A schedule compiler that selects concrete interstitial assets at compile time; a traffic fill that evaluates cooldowns hours before air.

---

### INV-TRAFFIC-FILL-FALLBACK-001 — Fallback produces valid segments

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** When no interstitials are available (no asset library, empty candidate list, or all candidates excluded by policy), the traffic manager MUST fall back to the static filler file. The fallback MUST produce segments that exactly fill the break duration. Fallback MUST NOT produce an error, skip the break, or leave the break empty.

**Violation:** A break that produces zero segments when no interstitials are available; an exception raised during fallback; a fallback that does not account for the full break duration.

---

### INV-TRAFFIC-FILL-BUDGET-001 — Total filled duration must not exceed break budget

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`, `LAW-DERIVATION`

**Guarantee:** The sum of all filled durations across all breaks in a single BreakPlan MUST NOT exceed `BreakPlan.break_budget_ms`. Per-break allocations are derived from weights and may accumulate rounding error. The traffic manager MUST verify that the aggregate does not overshoot the budget. Overshoot violates grid alignment.

**Violation:** A block where `sum(allocated_ms for all breaks) > break_budget_ms`; a rounding strategy that distributes more total time than the budget allows.

---

## Pipeline Position

```
Break Detection
       │
       ▼
  BreakPlan (break_plan.md)
       │
       ▼
┌──────────────────────────────────┐
│     TRAFFIC MANAGER              │
│     (this contract)              │
│                                  │
│  Inputs:                         │
│   ├── BreakPlan                  │
│   ├── BreakConfig                │
│   ├── TrafficPolicy              │
│   ├── Candidate list             │
│   ├── Play history               │
│   └── Fallback filler            │
│                                  │
│  For each filler placeholder:    │
│   1. build_break_structure()     │
│   2. Fill bumper slots           │
│   3. Fill interstitial pool      │
│   4. Distribute pad in pool      │
│   5. Record play history         │
│                                  │
│  Output:                         │
│   └── Filled segments            │
│       [bumper?][spots+pad]       │
│       [bumper?]                  │
└──────────────────────────────────┘
       │
       ▼
  ScheduledBlock (filled)
       │
       ▼
  AIR (playout)
```

---

## Edge Cases

### No Asset Library

When `asset_library` is `None`, all breaks fall back to the static filler file. This is valid for channels that have not configured traffic inventories.

### All Candidates Excluded

When every candidate is excluded by policy (type filter, cooldown, or daily cap), `select_next()` returns `None`. The traffic manager stops filling the current break. If at least one spot was already selected, remaining time becomes inter-spot pad. If no spots were selected at all, the break falls back to the static filler file loop.

### Zero-Duration Break

A break with zero allocated duration (from a zero-weight opportunity) produces no segments. This is valid.

### Single Asset Exceeds Break

When the only available candidate is longer than the remaining break time, it is excluded by the policy layer's duration constraint. If no spots were selected, the break falls back to the filler file loop.

### Filler File Wrapping

When the static filler file is shorter than the break, the traffic manager wraps around and replays from the beginning. The fill loop continues until the break is exactly filled.

---

## Relationship to Existing Invariants

This contract consolidates and supersedes traffic manager invariants previously scattered across:
- `INV-BREAK-PAD-EXACT-001` in `pkg/core/docs/contracts/runtime/` — now `INV-TRAFFIC-FILL-EXACT-001`
- `INV-BREAK-PAD-DISTRIBUTED-001` in `pkg/core/docs/contracts/runtime/` — now `INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001`
- `INV-TRAFFIC-LATE-BIND-001` in `pkg/core/docs/contracts/runtime/` — now `INV-TRAFFIC-FILL-LATE-BIND-001`
- Behavioral rules B-1 through B-6 in `TrafficManagementContract.md` — selection behavior now delegated to `traffic_policy.md`; data contract rules remain in `TrafficManagementContract.md`

`INV-MOVIE-PRIMARY-ATOMIC` (primary content protection) has been moved to `break_detection.md` as `INV-BREAK-012`, where it belongs architecturally. Break detection prevents break placement inside primary content; the traffic manager trusts this guarantee.

---

## Required Tests

- `pkg/core/tests/contracts/test_traffic_manager.py`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_structured_fill_produces_bumper_then_spots` | INV-TRAFFIC-FILL-STRUCTURED-001 | With bumper config, output begins with bumper segment. |
| `test_structured_fill_interstitial_pool_only` | INV-TRAFFIC-FILL-STRUCTURED-001 | Without bumper config, output is interstitial spots only. |
| `test_structured_fill_slot_order_preserved` | INV-TRAFFIC-FILL-STRUCTURED-001 | Output segment order matches BreakStructure slot order. |
| `test_bumper_degrade_merges_to_pool` | INV-TRAFFIC-FILL-BUMPER-DEGRADE-001 | No bumper available: bumper duration added to interstitial pool. |
| `test_bumper_degrade_budget_conserved` | INV-TRAFFIC-FILL-BUMPER-DEGRADE-001 | Total duration unchanged when bumper degrades. |
| `test_fill_exact_duration` | INV-TRAFFIC-FILL-EXACT-001 | Assets + pad sum to allocated break duration. |
| `test_partial_fill_pad_exact` | INV-TRAFFIC-FILL-EXACT-001 | Partial fill: assets + pad = allocated. |
| `test_empty_fill_filler_exact` | INV-TRAFFIC-FILL-EXACT-001 | No assets: filler loop fills break exactly. |
| `test_pad_distributed_evenly` | INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001 | 3 spots, 2000ms gap: ~667ms pads between spots. |
| `test_pad_remainder_to_last` | INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001 | Indivisible gap: remainder applied to last items. |
| `test_opportunities_filled_in_order` | INV-TRAFFIC-FILL-ORDER-001 | Multi-break plan: fills in position_ms order. |
| `test_no_invented_break_positions` | INV-TRAFFIC-FILL-NO-INVENT-001 | Filled segments only at BreakPlan positions. |
| `test_rotation_advances_across_breaks` | INV-TRAFFIC-FILL-ROTATION-ADVANCES-001 | Different asset selected in consecutive breaks. |
| `test_play_history_not_mutated` | INV-TRAFFIC-FILL-ROTATION-ADVANCES-001 | Caller's original history list unchanged. |
| `test_late_bind_empty_placeholders` | INV-TRAFFIC-FILL-LATE-BIND-001 | Compiler produces empty filler; fill at feed time. |
| `test_fallback_fills_exactly` | INV-TRAFFIC-FILL-FALLBACK-001 | No library: static filler fills break exactly. |
| `test_fallback_wraps_filler` | INV-TRAFFIC-FILL-FALLBACK-001 | Filler shorter than break: wraps and fills exactly. |
| `test_fallback_no_error` | INV-TRAFFIC-FILL-FALLBACK-001 | No candidates: no exception, produces valid segments. |
| `test_total_fill_within_budget` | INV-TRAFFIC-FILL-BUDGET-001 | Sum of all break allocations <= break_budget_ms. |
| `test_rounding_does_not_overshoot` | INV-TRAFFIC-FILL-BUDGET-001 | Weight rounding across 5 breaks stays within budget. |

---

## Enforcement Evidence

TODO
