# Scheduling Contract

**Status:** Architectural Contract
**Authority Level:** Constitutional — Planning Layer
**Version:** 1.0
**Date:** 2026-03-03

---

## I. Purpose

The scheduling layer is the editorial authority of RetroVue. It answers one question: **what should air, and when?**

Scheduling transforms operator intent (SchedulePlans, zones, templates, pools) into deterministic, immutable, auditable ScheduleRevisions containing ScheduleItems. ScheduleDay is a derived grouping of ScheduleItems by broadcast_day for operational convenience. Every downstream artifact — EPG events, PlaylistEvents, ExecutionSegments, and ultimately the bytes emitted by AIR — traces its editorial authority back to the ScheduleRevision that owns the originating ScheduleItems.

The scheduling contract defines the minimum set of rules that must hold for the planning layer to produce correct output. If these 13 invariants hold, the scheduling system is sound. If any one is violated, downstream layers cannot be trusted.

---

## II. Architectural Scope

### What scheduling governs

- Schedule generation (SchedulePlan → ScheduleRevision → ScheduleItem → ScheduleDay)
- Schedule compilation (DSL/template YAML → program blocks)
- Schedule coverage (every moment of the broadcast day has editorial authority)
- Schedule determinism (same inputs always produce the same schedule)
- Schedule mutation rules (what may be changed, and when)
- Schedule materialization (when ScheduleDays are produced and how they are stored)

### What scheduling does NOT govern

The scheduling layer has no authority over the following concerns. Each belongs to a different architectural layer with its own contract:

| Concern | Owner | Why not scheduling |
|---|---|---|
| Execution horizon depth | Horizon Manager | Runtime coordination, not editorial |
| PlaylistEvent generation | Tier 2 / PlaylistBuilderDaemon | Execution intent derived from schedule output |
| Block feeding and queue management | ChannelManager | Runtime playout orchestration |
| Frame timing and pacing | AIR | Real-time execution |
| HLS segment emission | Transport / Sink | Output format |
| Viewer lifecycle | ChannelManager / ProgramDirector | Runtime session management |
| As-run reconciliation | Evidence Server | Historical recording |
| Asset eligibility definitions | Asset layer | Scheduling enforces the gate but does not define eligible states |

The boundary is strict: scheduling produces ScheduleRevisions containing ScheduleItems. ScheduleDay is a derived grouping for operational convenience. Scheduling does not consume its own output.

---

## III. Derivation Model

```
    SchedulePlan
    (zones, templates, pools, day-of-week rules)
         │
         │  compile
         │  ── INV-PLAN-FULL-COVERAGE-001
         │  ── INV-PLAN-NO-ZONE-OVERLAP-001
         │  ── INV-PLAN-GRID-ALIGNMENT-001
         │  ── INV-PLAN-ELIGIBLE-ASSETS-ONLY-001
         │  ── INV-SCHEDULE-SEED-DETERMINISTIC-001
         │  ── INV-SCHEDULE-SEED-DAY-VARIANCE-001
         │  ── INV-P3-001
         │  ── INV-SCHED-WINDOW-ITERATION-001
         ▼
    ScheduleRevision
    (immutable editorial snapshot, owns ScheduleItems)
         │  ── INV-SCHEDULEREVISION-IMMUTABLE-001
         │
         ▼
    ScheduleItem
    (canonical editorial unit, owned by ScheduleRevision)
         │
         ▼
    ScheduleDay
    (derived grouping of ScheduleItems by broadcast_day)
         │  ── INV-SCHEDULEDAY-ONE-PER-DATE-001
         │  ── INV-SCHEDULEDAY-IMMUTABLE-001
         │  ── INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001
         │  ── INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001
         │  ── INV-RESCHEDULE-FUTURE-GUARD-001
         │
         ▼
    ── scheduling boundary ──────────────────────
         │
         ▼
    Execution intent (PlaylistEvent, Tier 2)
         │
         ▼
    ExecutionSegment
         │
         ▼
    AIR playout → MPEG-TS bytes → viewers
```

Authority flows downward. Each layer consumes the output of the layer above it. No layer reaches upward.

---

## IV. Canonical Invariants

### IV.1 — Plan Structure

These three invariants constrain the SchedulePlan, the operator's declaration of editorial intent. They are checked at zone creation and modification time, before any compilation occurs.

---

#### INV-PLAN-FULL-COVERAGE-001

**Zones must tile the full broadcast day.**

An active SchedulePlan's zones MUST collectively cover the full broadcast day (00:00–24:00 relative to `programming_day_start`) with no temporal gaps.

A gap in zone coverage means ScheduleDay generation has no editorial mandate for that window. Content introduced to fill such a gap would be constitutionally unanchored, violating LAW-CONTENT-AUTHORITY.

*Violation example:* A plan has zones covering [00:00, 18:00] and [20:00, 24:00]. The two-hour window [18:00, 20:00] has no zone. ScheduleDay generation for this period has no authority. The plan is rejected.

*Derives from:* LAW-CONTENT-AUTHORITY, LAW-GRID

---

#### INV-PLAN-NO-ZONE-OVERLAP-001

**No two active zones may claim the same time interval.**

No two enabled zones within the same SchedulePlan may have overlapping time windows, after normalization to broadcast-day-relative coordinates and application of day-of-week filters.

Overlapping zones create ambiguous editorial authority: two sources simultaneously claim ownership of the same time. This is unresolvable.

*Violation example:* Zone A covers [06:00, 18:00] and Zone B covers [16:00, 24:00], both active Monday–Sunday. The [16:00, 18:00] interval has two competing authorities. The configuration is rejected.

*Non-violation:* Zone A is Monday–Friday, Zone B is Saturday–Sunday. Their time windows overlap but they never apply on the same day.

*Derives from:* LAW-CONTENT-AUTHORITY, LAW-GRID

---

#### INV-PLAN-GRID-ALIGNMENT-001

**All zone boundaries must be multiples of the channel grid.**

All zone `start_time` and `end_time` values MUST be multiples of `grid_block_minutes`. Zone duration MUST also be a multiple of `grid_block_minutes`.

Off-grid boundaries cascade through the entire derivation chain. A zone boundary at 17:59 on a 30-minute grid produces a ScheduleDay slot that starts at 17:59, which produces a PlaylistEvent at 17:59, which produces an ExecutionSegment at 17:59. Every downstream artifact inherits the misalignment.

*Violation example:* Channel has `grid_block_minutes=30`. An operator creates a zone with `end_time=17:45`. The zone duration is not a multiple of 30 minutes. The configuration is rejected.

*Derives from:* LAW-GRID

---

### IV.2 — Asset Gate

---

#### INV-PLAN-ELIGIBLE-ASSETS-ONLY-001

**Only eligible assets may enter the schedule.**

All assets resolved from an active SchedulePlan's zones must be eligible (`state=ready` and `approved_for_broadcast=true`) at ScheduleDay generation time.

This is the gate between the asset lifecycle and the scheduling derivation chain. Once an ineligible asset propagates into a ScheduleDay, it contaminates every downstream artifact. The gate must be at the earliest resolution point: schedule generation.

*Violation example:* A zone references a pool containing an asset with `state=enriching`. ScheduleDay generation resolves this asset into a slot. The slot now references content that cannot be played. The generation is rejected.

*Derives from:* LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY

---

### IV.3 — ScheduleDay Authority

These four invariants constrain the ScheduleDay, the materialized artifact that is the scheduling layer's sole output. They define its identity, immutability, provenance, and boundary behavior.

**ScheduleDay is a derived artifact.** The authoritative editorial schedule is defined by the active ScheduleRevision and its ScheduleItems. ScheduleDay invariants apply to the materialized grouping of ScheduleItems for operational purposes, not to editorial authority.

---

#### INV-SCHEDULEDAY-ONE-PER-DATE-001

**Exactly one ScheduleDay per channel per broadcast date.**

At any point in time, at most one ScheduleDay MUST exist for a given `(channel_id, programming_day_date)` pair. Duplicate insertion MUST be rejected. Replacement MUST be atomic via force-replace (delete + insert in a single critical section).

Two ScheduleDays for the same channel-date create ambiguous provenance: downstream artifacts cannot determine which is canonical. The derivation chain fractures.

*Violation example:* The generation service creates a ScheduleDay for (channel=retrovue-classic, date=2026-03-05). A second generation runs and creates another ScheduleDay for the same pair without force-replacing the first. Two records now exist. The system cannot determine which is authoritative.

*Derives from:* LAW-DERIVATION, LAW-IMMUTABILITY

---

#### INV-SCHEDULEDAY-IMMUTABLE-001

**ScheduleDay is immutable after materialization.**

A ScheduleDay's slot assignments, asset placements, and wall-clock times MUST NOT be mutated after materialization. The only permitted modifications are:

1. **Atomic force-regeneration** — the existing record is replaced atomically.
2. **Operator manual override** — a new record is created with `is_manual_override=true`, referencing the superseded record.

In-place field updates are unconditionally prohibited.

A mutable ScheduleDay means downstream artifacts derived from it may silently diverge from its current state. EPG shows one thing, playout emits another. The derivation chain is meaningless if its root can change after derivation.

*Violation example:* After a ScheduleDay is materialized and EPG events are derived from it, a background process modifies a slot's asset_id in place. The EPG now shows the old content, but playout resolves the new content. Viewers see a mismatch.

*Derives from:* LAW-IMMUTABILITY, LAW-DERIVATION

---

#### INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001

**Every ScheduleDay must trace to its generating SchedulePlan.**

Every ScheduleDay must satisfy one of:

1. `plan_id` references the active SchedulePlan that generated it, **or**
2. `is_manual_override=true` with a reference to the superseded ScheduleDay.

A ScheduleDay with `plan_id=NULL` and `is_manual_override=false` MUST NOT exist.

Without this link, the audit chain is broken. A ScheduleDay that cannot be traced to a plan is content without editorial authority — it exists, but nobody authorized it.

*Violation example:* A code path generates a ScheduleDay directly from a hardcoded asset list, bypassing the SchedulePlan resolution pipeline. The record has no `plan_id`. An operator asks "why did this air?" and there is no answer.

*Derives from:* LAW-DERIVATION, LAW-CONTENT-AUTHORITY

---

#### INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001

**Carry-in across day boundaries must not produce overlap.**

If a ScheduleDay contains a slot whose `end_utc` extends past the broadcast-day boundary, then the next ScheduleDay MUST NOT schedule any slot whose `start_utc` is earlier than that carry-in slot's `end_utc`. Content MUST NOT be duplicated across the seam.

This is the only case where two ScheduleDays interact. A 90-minute movie starting at 05:00 on a 06:00 broadcast-day boundary carries 30 minutes into the next day. The next day's generation must start at 05:30 (the carry-in's end), not at 06:00 (the nominal boundary). Scheduling at 06:00 produces overlapping authorities for the [05:30, 06:00] window.

*Violation example:* Monday's final slot runs [05:00, 06:30]. Tuesday's generation starts at 06:00 (the nominal day start). Tuesday's first slot covers [06:00, 06:30]. Now both Monday and Tuesday claim authority over [06:00, 06:30]. Playout cannot resolve which to play.

*Derives from:* LAW-GRID, LAW-DERIVATION

---

### IV.4 — Compilation

---

#### INV-SCHED-WINDOW-ITERATION-001

**Windows iterate with capacity gating, optional bleed, and mandatory timeline continuity.**

A scheduled window may emit multiple sequential iterations of its content entry. The iteration model is governed by six rules:

1. **Multiple iterations permitted.** A window may emit any number of iterations. The count is determined at resolution time by available capacity and resolved duration.

2. **Independent resolution.** Each iteration resolves independently. No carry-forward of selection state between iterations unless the source enforces deduplication internally.

3. **Timeline continuity.** No temporal gap between consecutive iterations within a window, or between the final iteration of one window and the start of the next.

4. **Capacity gating (`allow_bleed: false`).** An iteration MUST NOT begin if its minimum possible duration exceeds remaining window capacity.

5. **Final iteration bleed (`allow_bleed: true`).** The final iteration MAY exceed remaining capacity. The next window begins where the bleed ends, not at the nominal boundary.

6. **Window boundary authority.** Declared boundaries are authoritative as start conditions and capacity limits. They never truncate in-progress iterations.

*Violation example (capacity overrun):* A window has 10 minutes remaining with `allow_bleed: false`. The shortest eligible asset in the pool is 11 minutes. The system starts a new iteration anyway. The iteration overruns the window boundary.

*Violation example (gap):* A window produces three iterations: [00:00, 22:00], [22:00, 44:00], [45:00, 67:00]. There is a 1-minute gap between the second and third iterations.

*Derives from:* LAW-TIMELINE, LAW-CONTENT-AUTHORITY

---

### IV.5 — Determinism

These three invariants collectively guarantee that schedule compilation is a pure function. Given the same inputs, it produces the same output, across process restarts, across machines, across time.

---

#### INV-SCHEDULE-SEED-DETERMINISTIC-001

**Channel seeds are deterministic and stable across process lifetimes.**

`channel_seed(channel_id)` MUST always return the same value for the same input. Seeds MUST use `hashlib.sha256`, never Python's `hash()` (which is randomized per process via `PYTHONHASHSEED`). A single shared `channel_seed()` function MUST be the sole source.

If seeds change between restarts, the compiled schedule changes. EPG shows the old schedule, playout compiles the new one. Viewers see a mismatch.

*Violation example:* A developer uses `hash("showtime-cinema")` to seed movie selection. On restart, `PYTHONHASHSEED` changes, producing a different hash, a different seed, and a different movie order. The EPG shows "Casablanca" at 20:00 but playout compiles "The Maltese Falcon."

*Derives from:* LAW-LIVENESS, LAW-CONTENT-AUTHORITY

---

#### INV-SCHEDULE-SEED-DAY-VARIANCE-001

**Compilation seeds incorporate broadcast day for day-to-day variety.**

`compilation_seed(channel_id, broadcast_day)` MUST incorporate both arguments. Same pair → same seed. Different days → different seeds. Within a single compilation, each window derives a window-specific seed by mixing the window's start time into the compilation seed. All seed derivation uses `hashlib.sha256`.

Without day incorporation, `Random(seed).choice(sorted_candidates)` produces identical selections every day. Viewers see the same schedule repeating. Day variance ensures variety while preserving deterministic rebuild.

*Violation example:* A channel compiles Monday and Tuesday using only `channel_seed(channel_id)`. Both days receive identical seeds. Both days compile the same movie order. Viewers see the same lineup two days in a row.

*Derives from:* LAW-LIVENESS, LAW-CONTENT-AUTHORITY

---

#### INV-P3-001

**Episode selection is deterministic: same inputs always produce the same episode.**

For any selection mode (sequential, random, manual), the same editorial inputs (`channel_id`, `program_id`, `programming_day_date`, `slot_time`, episode list) MUST produce the same selected episode. For random mode, selection uses `hashlib.sha256` over a deterministic seed string. No call site may introduce non-determinism (wall-clock reads, random.random(), database-dependent ordering).

This invariant covers the ScheduleManager resolution path. INV-SCHEDULE-SEED-DETERMINISTIC-001 and INV-SCHEDULE-SEED-DAY-VARIANCE-001 cover the DSL compilation path. Together, they guarantee all schedule compilation paths are pure functions.

*Violation example:* The episode selector for random mode calls `random.choice(episodes)` without seeding. Two compilations of the same day produce different episode assignments. EPG and playout diverge.

*Derives from:* LAW-CONTENT-AUTHORITY

---

### IV.6 — Mutation Rules

---

#### INV-RESCHEDULE-FUTURE-GUARD-001

**Reschedule must reject artifacts whose coverage window has begun or is in the past.**

A reschedule operation (deletion-for-regeneration) on a Tier 1 `ProgramLogDay` or Tier 2 `PlaylistEvent` MUST be rejected when:

- Tier 1: `range_start` is not strictly greater than `now()`
- Tier 2: `start_utc_ms` is not strictly greater than `now_utc_ms`
- Tier 1: `range_start IS NULL` (temporal eligibility cannot be determined)

An operator reschedule that deletes an actively-airing block disrupts viewers mid-program. The temporal guard ensures mutations can only affect the future.

*Violation example:* A block is currently airing (its `range_start` is 30 minutes ago). An operator triggers a reschedule for that day. The system deletes the block. AIR's current playout session loses its upstream authority. The channel goes dark.

*Derives from:* LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY

---

## V. Derived Invariants

The following invariants are **intentionally excluded** from the canonical contract. They are implied by the invariants above. They remain valuable as test assertions and defense-in-depth checks, but they are not independent architectural rules.

---

#### INV-SCHEDULEDAY-NO-GAPS-001 — Implied by INV-PLAN-FULL-COVERAGE-001

**Rule:** A materialized ScheduleDay must have no temporal gaps across the full broadcast day.

**Why it is derived:** INV-PLAN-FULL-COVERAGE-001 requires that plan zones tile the entire broadcast day. If the input has full coverage and the compilation is correct, the output (ScheduleDay) is automatically gap-free. A gap in the ScheduleDay when the plan has full coverage indicates a compiler bug, not a missing architectural rule.

**Relationship:** INV-PLAN-FULL-COVERAGE-001 constrains the input. INV-SCHEDULEDAY-NO-GAPS-001 verifies the output. The output property follows from the input property under correct compilation.

**Disposition:** Retained as a test assertion in `test_scheduling_constitution.py`. Retained as a runtime validation check in `validate_scheduleday_contiguity()`. Not part of the architectural contract because it adds no rule that INV-PLAN-FULL-COVERAGE-001 does not already imply.

---

#### INV-BLEED-NO-GAP-001 — Implied by INV-SCHED-WINDOW-ITERATION-001 + INV-PLAN-FULL-COVERAGE-001

**Rule:** The schedule compiler must emit a strictly contiguous, non-overlapping, grid-aligned sequence of program blocks. Bleed overlaps are resolved by compaction (push-forward), not by pruning.

**Why it is derived:** INV-SCHED-WINDOW-ITERATION-001 defines timeline continuity as mandatory (rule 3), defines bleed semantics (rule 5: next window starts where bleed ends), and defines capacity gating (rule 4). INV-PLAN-FULL-COVERAGE-001 ensures the input covers the full day. Under these two invariants, the compiler's output is necessarily contiguous and gap-free. The compaction strategy (push-forward vs. pruning) is an implementation choice, not an architectural rule.

**Disposition:** Retained as a compiler output validation in `test_inv_bleed_no_gap.py`. Not part of the architectural contract because it restates the consequences of INV-SCHED-WINDOW-ITERATION-001 at a lower abstraction level.

---

## VI. Removed Invariants

The following invariants were evaluated during the audit and excluded from the canonical contract. They remain in their respective locations (code, tests, schema docs) but are not architectural scheduling rules.

### Implementation Invariants

These govern specific compiler or resolver behaviors. They belong in code and tests, not in the architectural contract.

| Invariant ID | What it governs | Why excluded |
|---|---|---|
| INV-SCHEDULEDAY-LEAD-TIME-001 | ScheduleDay must be materialized N days ahead | Operational timing policy with a configurable parameter (`min_schedule_day_lead_days`), not a structural scheduling rule. Belongs in deployment configuration. |
| INV-TEMPLATE-GRAFT-DUAL-YAML-001 | Legacy and new template YAML both accepted | YAML parser backward compatibility. Important operationally but not an architectural property of the scheduling system. |
| INV-TEMPLATE-PRIMARY-SEGMENT-001 | Templates resolve to exactly one primary segment | Template disambiguation logic (explicit flag vs. convention fallback). Compiler internal. |
| INV-MARATHON-CROSSMIDNIGHT-001 | Marathon blocks crossing midnight resolve correctly | DSL time-parser edge case for one specific block type. Bug prevention, not architecture. |
| INV-SCHEDULE-SEQUENTIAL-ADVANCE-001 | ~~Sequential counter advances across broadcast days~~ **RETIRED** — superseded by INV-EPISODE-PROGRESSION-003. See `episode_progression.md`. | Counter initialization for `mode: sequential`. Retired: replaced by calendar-based occurrence counting. |
| INV-P3-009 | Asset duration is authoritative over slot duration | Duration resolution rule within ScheduleManager. Governs how the resolver handles mismatches, not how schedules are structured. |
| INV-P5-001 | `schedule_source: "phase3"` activates dynamic mode | Configuration routing between code paths. Internal wiring. |

### Naming / Storage Invariants

These govern internal representation details. They belong in schema documentation.

| Invariant ID | What it governs | Why excluded |
|---|---|---|
| INV-WINDOW-UUID-EMBEDDED-001 | Window UUID stored in JSON blob, not as a column | Storage format for window identity. The architectural concern is "windows have stable identity" — how the UUID is serialized is a schema detail. |
| INV-PROGRAM-LOG-COLUMN-NAME-001 | Tier 1 column named `program_log_json` | Column rename from `compiled_json`. Schema naming with no architectural significance. |

### Phantom Invariants

These IDs were referenced in a previous inventory but **do not exist in the codebase**. The actual invariants at the PlaylistScheduleManager level use `INV-PSM-*` IDs, which govern frame-level playlist generation — an execution concern, not scheduling.

| Invariant ID | Described concept | Actual status |
|---|---|---|
| INV-SM-001 | Main show starts at grid boundaries | ID does not exist. Concept is derived from INV-PLAN-GRID-ALIGNMENT-001. |
| INV-SM-002 | Same inputs produce same outputs | ID does not exist. Concept duplicates INV-SCHEDULE-SEED-DETERMINISTIC-001. |
| INV-SM-003 | Every moment covered by one segment | ID does not exist. Concept duplicates INV-PLAN-FULL-COVERAGE-001. |
| INV-SM-004 | Filler truncated at grid boundary | ID does not exist. Concept is derived from INV-PLAN-GRID-ALIGNMENT-001. |
| INV-SM-006 | Wall-clock maps to file + offset | ID does not exist. Concept belongs to execution layer, not scheduling. |
| INV-SM-007 | No system time access | ID does not exist. Concept is an implementation mechanism for determinism. |

---

## VII. Law Traceability

Every canonical invariant traces to one or more constitutional laws.

| Law | Invariants derived |
|---|---|
| LAW-CONTENT-AUTHORITY | INV-PLAN-FULL-COVERAGE-001, INV-PLAN-NO-ZONE-OVERLAP-001, INV-PLAN-ELIGIBLE-ASSETS-ONLY-001, INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001, INV-SCHED-WINDOW-ITERATION-001, INV-SCHEDULE-SEED-DETERMINISTIC-001, INV-SCHEDULE-SEED-DAY-VARIANCE-001, INV-P3-001 |
| LAW-GRID | INV-PLAN-FULL-COVERAGE-001, INV-PLAN-NO-ZONE-OVERLAP-001, INV-PLAN-GRID-ALIGNMENT-001, INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 |
| LAW-DERIVATION | INV-SCHEDULEDAY-ONE-PER-DATE-001, INV-SCHEDULEDAY-IMMUTABLE-001, INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001, INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 |
| LAW-IMMUTABILITY | INV-SCHEDULEDAY-ONE-PER-DATE-001, INV-SCHEDULEDAY-IMMUTABLE-001, INV-RESCHEDULE-FUTURE-GUARD-001 |
| LAW-LIVENESS | INV-SCHEDULE-SEED-DETERMINISTIC-001, INV-SCHEDULE-SEED-DAY-VARIANCE-001 |
| LAW-TIMELINE | INV-SCHED-WINDOW-ITERATION-001 |
| LAW-ELIGIBILITY | INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 |
| LAW-RUNTIME-AUTHORITY | INV-RESCHEDULE-FUTURE-GUARD-001 |

---

## VIII. Test Evidence

| Invariant ID | Test location |
|---|---|
| INV-PLAN-FULL-COVERAGE-001 | `pkg/core/tests/contracts/test_scheduling_constitution.py` |
| INV-PLAN-NO-ZONE-OVERLAP-001 | `pkg/core/tests/contracts/test_scheduling_constitution.py` |
| INV-PLAN-GRID-ALIGNMENT-001 | `pkg/core/tests/contracts/test_scheduling_constitution.py` |
| INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 | `pkg/core/tests/contracts/test_inv_plan_eligible_assets_only.py` |
| INV-SCHEDULEDAY-ONE-PER-DATE-001 | `pkg/core/tests/contracts/test_scheduling_constitution.py` |
| INV-SCHEDULEDAY-IMMUTABLE-001 | `pkg/core/tests/contracts/test_scheduling_constitution.py` |
| INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | `pkg/core/tests/contracts/test_scheduling_constitution.py` |
| INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | `pkg/core/tests/contracts/test_scheduling_constitution.py` |
| INV-SCHED-WINDOW-ITERATION-001 | `pkg/core/tests/contracts/test_inv_sched_window_iteration_001.py` |
| INV-SCHEDULE-SEED-DETERMINISTIC-001 | `pkg/core/tests/contracts/runtime/test_inv_schedule_seed_deterministic.py` |
| INV-SCHEDULE-SEED-DAY-VARIANCE-001 | `pkg/core/tests/contracts/runtime/test_inv_schedule_seed_day_variance.py` |
| INV-P3-001 | `pkg/core/tests/contracts/test_schedule_manager_phase3_contract.py` |
| INV-RESCHEDULE-FUTURE-GUARD-001 | `pkg/core/tests/contracts/scheduling/test_inv_reschedule_future_guard.py` |

---

**Document version:** 1.0
**Governs:** Schedule generation, compilation, coverage, determinism, mutation, materialization
**Does not govern:** Execution horizon, playout runtime, AIR, transport, viewer lifecycle
**Canonical invariant count:** 13
