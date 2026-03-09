# BreakStructure — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-DERIVATION`

---

## Overview

BreakStructure defines the internal shape of a commercial break. It sits between break detection (which determines WHERE breaks occur via BreakPlan) and traffic fill (which selects WHAT interstitial assets play in each break). BreakStructure determines HOW the break is organized — the ordered sequence of typed slots that compose a single break.

A break is not a flat bag of interstitials. Real broadcast breaks have structure: a bumper transitions the viewer out of program content, interstitial spots fill the body of the break, a station ID provides legal identification, and a bumper transitions the viewer back into program content.

BreakStructure consumes a single break opportunity's allocated budget and produces an ordered sequence of typed slots. Each slot has a fixed type, a duration, and a fill rule. The traffic manager fills the interstitial slot with assets of any canonical interstitial type — commercials, promos, trailers, etc. Bumpers and station IDs are selected by dedicated mechanisms, not the traffic policy engine.

### Station ID Placement

Station IDs are structural elements with fixed placement — after the interstitial pool, before the from_break bumper. They are legal identifiers that real broadcasters place at specific structural positions within breaks. Station IDs are NOT traffic inventory. They are selected by a dedicated mechanism (similar to bumpers), not by the traffic policy engine. This ensures predictable, regulation-compliant placement regardless of traffic policy configuration.

### Authority Boundary

This contract owns:
- Break slot ordering and sequencing rules
- Budget allocation across slot types within a single break
- Slot type definitions and fill rule classification
- Structural determinism (same inputs → same structure)

This contract does NOT own:
- Break opportunity identification or placement (`break_detection.md`, `break_plan.md`)
- Interstitial asset selection within slots (`traffic_policy.md`, `traffic_manager.md`)
- Bumper asset selection (future: bumper policy)
- Station ID asset selection (future: station ID policy)
- BreakPlan structure or immutability guarantees (`break_plan.md`)

---

## Domain Object Definition

### BreakStructure

| Field | Type | Description |
|-------|------|-------------|
| `slots` | ordered list of BreakSlot | Typed slots in playback order. |
| `total_duration_ms` | positive integer | Sum of all slot durations. MUST equal the break opportunity's allocated budget. |

### BreakSlot

| Field | Type | Description |
|-------|------|-------------|
| `slot_type` | `"to_break_bumper"` \| `"interstitial"` \| `"station_id"` \| `"from_break_bumper"` | What kind of content fills this slot. |
| `duration_ms` | non-negative integer | Time allocated to this slot. |
| `fill_rule` | `"bumper"` \| `"traffic"` \| `"station_id"` | Which fill mechanism is responsible. |

### Slot Types

| Slot Type | Fill Rule | Position | Required |
|-----------|-----------|----------|----------|
| `to_break_bumper` | `bumper` | First | No |
| `interstitial` | `traffic` | Middle | Yes (at least one if budget permits) |
| `station_id` | `station_id` | After interstitial, before from_break bumper | No |
| `from_break_bumper` | `bumper` | Last | No |

### Slot Ordering

The canonical slot order within a break is:

```
[to_break_bumper?] → [interstitial] → [station_id?] → [from_break_bumper?]
```

Optional structural slots (bumpers, station ID) are omitted when the break budget is too small to accommodate them, or when the channel configuration does not include them. When budget is tight, slots are shed in reverse priority order: station_id first, then from_break_bumper, then to_break_bumper.

### Interstitial Pool (Time-Based)

The interstitial slot is a single time-based budget pool. The traffic manager fills it dynamically by packing variable-length assets until the budget is exhausted. Assets of any canonical interstitial type may be placed — commercials, promos, trailers, PSAs, teasers, shortform, and filler. Placement order and type mix are governed by the traffic policy, not by BreakStructure. Station IDs are NOT placed in the interstitial pool — they have their own dedicated structural slot.

### Budget Allocation

The break opportunity's allocated budget is distributed across slots:

1. Reserve `to_break_bumper` duration (if configured and budget permits).
2. Reserve `from_break_bumper` duration (if configured and budget permits).
3. Reserve `station_id` duration (if configured and budget permits).
4. Remaining budget becomes the interstitial pool.

If the remaining interstitial pool is zero or negative after reservations, optional structural slots are shed in reverse priority order: `station_id` first, then `from_break_bumper`, then `to_break_bumper`. The interstitial pool MUST receive the maximum possible share of the budget.

---

## Relationship to Other Contracts

### `break_plan.md` — Upstream

BreakPlan provides the allocated budget per opportunity. BreakStructure consumes this budget to produce typed slots. BreakStructure does not modify the BreakPlan. One BreakStructure is produced per BreakOpportunity.

### `traffic_manager.md` — Downstream

The traffic manager fills only slots with `fill_rule == "traffic"` (interstitial slots). It MUST NOT fill bumper or station_id slots. The traffic manager receives a BreakStructure and fills the interstitial pool using the existing fill loop (`select_next()`). Station IDs are filled by a dedicated selection mechanism, not the traffic policy engine.

### Station ID Selection — Dedicated Mechanism

Station ID slots are filled by a dedicated selection mechanism (similar to bumper selection). The traffic policy engine is NOT involved. When no station_id asset is available, the slot duration degrades into the interstitial pool, preserving budget conservation.

### `break_detection.md` — No direct relationship

BreakStructure does not interact with break detection. Break detection produces the BreakPlan; BreakStructure consumes the per-opportunity allocation derived from it.

---

## Invariants

### INV-BREAKSTRUCTURE-ORDERED-001 — Slots must follow canonical order

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Slots within a BreakStructure MUST follow the canonical order: `to_break_bumper` (if present) → one or more `interstitial` → `station_id` (if present) → `from_break_bumper` (if present). No slot type may appear out of order.

**Violation:** A BreakStructure where a `from_break_bumper` precedes an `interstitial`; a BreakStructure where `station_id` appears before `interstitial`; a BreakStructure where `to_break_bumper` appears after `interstitial`.

---

### INV-BREAKSTRUCTURE-BUDGET-EXACT-001 — Slot durations must sum to allocated budget

Status: Invariant
Authority Level: Planning
Derived From: `LAW-GRID`

**Guarantee:** The sum of all slot durations in a BreakStructure MUST exactly equal the break opportunity's allocated budget. No time is unaccounted for. No time overflows.

**Violation:** A BreakStructure where `sum(slot.duration_ms) != allocated_budget_ms`.

---

### INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001 — At least one interstitial slot must exist

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`

**Guarantee:** Every BreakStructure with a positive total duration MUST contain at least one interstitial slot. Optional structural slots (station_id, bumpers) MUST be shed before the interstitial pool is eliminated. Shedding order: station_id first, then from_break_bumper, then to_break_bumper. If the entire budget cannot accommodate even one interstitial slot after structural reservations, the break degenerates to a single interstitial slot spanning the full budget.

**Violation:** A BreakStructure with positive `total_duration_ms` and zero interstitial slots.

---

### INV-BREAKSTRUCTURE-TRAFFIC-SCOPE-001 — Traffic manager fills only interstitial slots

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** The traffic manager MUST only fill slots where `fill_rule == "traffic"`. Slots with `fill_rule == "bumper"` or `fill_rule == "station_id"` MUST NOT be passed to the traffic policy engine. Bumper and station_id slots are filled by dedicated mechanisms.

**Violation:** A traffic fill that selects a commercial for a bumper or station_id slot; a traffic fill that passes a bumper or station_id slot to `select_next()`.

---

### INV-BREAKSTRUCTURE-DETERMINISTIC-001 — Same inputs produce same structure

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

**Guarantee:** Given the same allocated budget and channel break configuration, BreakStructure generation MUST produce identical slot sequences. No randomness, no time-of-day variation, no external state dependency.

**Violation:** Two calls with identical inputs that produce different slot orderings or durations.

---

### INV-BREAKSTRUCTURE-NO-INVENT-001 — BreakStructure must not create breaks

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** BreakStructure MUST only structure breaks that exist in the BreakPlan. It MUST NOT create additional break opportunities, split content segments, or insert breaks at positions not present in the BreakPlan.

**Violation:** A BreakStructure generator that produces structure for a break not in `BreakPlan.opportunities`.

---

## Pipeline Position

```
Break Detection
       │
       ▼
  BreakPlan (break_plan.md)
       │
       ▼
  Budget Allocation (per opportunity)
       │
       ▼
┌──────────────────────────────────┐
│     BREAK STRUCTURE              │
│     (this contract)              │
│                                  │
│  Input:                          │
│   └── allocated_budget_ms        │
│   └── channel break config       │
│                                  │
│  Output:                         │
│   └── ordered BreakSlot list     │
│       [bumper?][interstitial     │
│        pool][station_id?]        │
│       [bumper?]                  │
└──────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────┐
│     TRAFFIC MANAGER              │
│     (traffic_manager.md)         │
│                                  │
│  Fills interstitial pool:        │
│  commercials, promos, trailers,  │
│  etc.                            │
│  Bumpers + station IDs filled    │
│  by dedicated mechanisms.        │
└──────────────────────────────────┘
       │
       ▼
  ScheduledBlock (filled)
```

---

## Edge Cases

### Budget Too Small for Bumpers

When the allocated budget is smaller than the combined bumper durations, bumper slots are shed. The entire budget becomes a single interstitial slot.

### Zero-Duration Break

A break with zero allocated duration produces an empty BreakStructure with no slots. This is valid. Downstream consumers MUST accept it without error.

### No Bumpers Configured

Channels may omit bumper configuration. The break structure contains interstitial and station_id slots only (if station_id is configured). The traffic manager fills the interstitial pool normally.

### No Station ID Configured

Channels may omit station_id configuration. The break structure contains bumpers and interstitial only. No station_id slot appears.

### Single Interstitial Slot Fills Entire Budget

When no bumpers and no station_id are configured, the entire budget is a single interstitial slot. The traffic manager fills it with any mix of canonical interstitial types as directed by policy.

---

## Required Tests

- `pkg/core/tests/contracts/test_break_structure.py`

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_slots_follow_canonical_order` | INV-BREAKSTRUCTURE-ORDERED-001 | Full config produces correct sequence: bumper → interstitial → station_id → bumper. |
| `test_station_id_after_interstitial_before_from_bumper` | INV-BREAKSTRUCTURE-ORDERED-001 | Station ID appears after interstitial pool, before from_break bumper. |
| `test_slot_durations_sum_to_budget` | INV-BREAKSTRUCTURE-BUDGET-EXACT-001 | Sum of slot durations equals allocated budget. |
| `test_zero_budget_empty_structure` | INV-BREAKSTRUCTURE-BUDGET-EXACT-001 | Zero budget produces empty slot list. |
| `test_various_budgets_conserved` | INV-BREAKSTRUCTURE-BUDGET-EXACT-001 | Budget conservation holds across a range of allocations. |
| `test_at_least_one_interstitial_slot` | INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001 | Positive budget always has interstitial slot. |
| `test_optional_slots_shed_before_interstitial` | INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001 | Small budget sheds station_id then bumpers, keeps interstitial. |
| `test_budget_too_small_for_structure` | INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001 | Tiny budget degenerates to single interstitial slot. |
| `test_station_id_shed_before_bumpers` | INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001 | Station ID is shed before bumpers when budget is tight. |
| `test_traffic_fills_only_interstitial_slots` | INV-BREAKSTRUCTURE-TRAFFIC-SCOPE-001 | Non-interstitial slots have non-traffic fill rules. |
| `test_fill_rules_match_slot_types` | INV-BREAKSTRUCTURE-TRAFFIC-SCOPE-001 | Every slot type maps to the correct fill rule across configs. |
| `test_bumpers_and_station_ids_not_traffic` | INV-BREAKSTRUCTURE-TRAFFIC-SCOPE-001 | Bumpers and station IDs must never have fill_rule='traffic'. |
| `test_deterministic_output` | INV-BREAKSTRUCTURE-DETERMINISTIC-001 | Same inputs produce identical structure. |
| `test_no_invented_breaks` | INV-BREAKSTRUCTURE-NO-INVENT-001 | Structure only for BreakPlan opportunities. |
| `test_zero_budget_no_slots` | INV-BREAKSTRUCTURE-NO-INVENT-001 | Zero-duration opportunity produces no structure at all. |
| `test_no_bumpers_configured` | INV-BREAKSTRUCTURE-ORDERED-001 | Without bumpers: interstitial + station_id only. |
| `test_no_station_id_configured` | INV-BREAKSTRUCTURE-ORDERED-001 | Without station_id: bumpers + interstitial only. |
| `test_bare_config` | INV-BREAKSTRUCTURE-ORDERED-001 | No structural elements: single interstitial slot. |

---

## Enforcement Evidence

TODO
