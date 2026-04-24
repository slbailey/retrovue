# RetroVue Invariants Index

**Status:** Index — canonical sources are the individual invariant files below.

Each invariant is defined in its own file under `invariants/`. Laws are defined in `laws/`. This document is a quick index only.

---

## Laws

| Law | File | Domain |
|-----|------|--------|
| LAW-CLOCK | [laws/LAW-CLOCK.md](laws/LAW-CLOCK.md) | Playout — single time authority |
| LAW-LIVENESS | [laws/LAW-LIVENESS.md](laws/LAW-LIVENESS.md) | Playout — continuous emission |
| LAW-SWITCHING | [laws/LAW-SWITCHING.md](laws/LAW-SWITCHING.md) | Playout — deadline-authoritative switches |
| LAW-TIMELINE | [laws/LAW-TIMELINE.md](laws/LAW-TIMELINE.md) | Playout — schedule defines boundaries |
| LAW-DECODABILITY | [laws/LAW-DECODABILITY.md](laws/LAW-DECODABILITY.md) | Playout — output decodability |
| LAW-ELIGIBILITY | [laws/LAW-ELIGIBILITY.md](laws/LAW-ELIGIBILITY.md) | Scheduling — eligible assets only |
| LAW-GRID | [laws/LAW-GRID.md](laws/LAW-GRID.md) | Scheduling — grid-aligned boundaries |
| LAW-CONTENT-AUTHORITY | [laws/LAW-CONTENT-AUTHORITY.md](laws/LAW-CONTENT-AUTHORITY.md) | Scheduling — DSL is sole editorial authority (was SchedulePlan, retired RETA-88) |
| LAW-DERIVATION | [laws/LAW-DERIVATION.md](laws/LAW-DERIVATION.md) | Scheduling — artifact chain traceability |
| LAW-RUNTIME-AUTHORITY | [laws/LAW-RUNTIME-AUTHORITY.md](laws/LAW-RUNTIME-AUTHORITY.md) | Scheduling — ExecutionEntry is sole runtime authority |
| LAW-IMMUTABILITY | [laws/LAW-IMMUTABILITY.md](laws/LAW-IMMUTABILITY.md) | Scheduling — published artifacts are immutable |

---

## Core

### Scheduling — SchedulePlan (DEPRECATED — RETA-88)

> **Retired:** SchedulePlan CRUD island retired per RETA-88 Option B. DSL + ScheduleRevision/ScheduleItem is the sole scheduling authority. These invariants are retained for historical reference only and are not enforced.

| Invariant | File | Derived From | Status |
|-----------|------|--------------|--------|
| INV-PLAN-FULL-COVERAGE-001 | [invariants/core/schedule-plan/INV-PLAN-FULL-COVERAGE-001.md](invariants/core/schedule-plan/INV-PLAN-FULL-COVERAGE-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID | DEPRECATED |
| INV-PLAN-NO-ZONE-OVERLAP-001 | [invariants/core/schedule-plan/INV-PLAN-NO-ZONE-OVERLAP-001.md](invariants/core/schedule-plan/INV-PLAN-NO-ZONE-OVERLAP-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID | DEPRECATED |
| INV-PLAN-GRID-ALIGNMENT-001 | [invariants/core/schedule-plan/INV-PLAN-GRID-ALIGNMENT-001.md](invariants/core/schedule-plan/INV-PLAN-GRID-ALIGNMENT-001.md) | LAW-GRID | DEPRECATED |
| INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 | [invariants/core/schedule-plan/INV-PLAN-ELIGIBLE-ASSETS-ONLY-001.md](invariants/core/schedule-plan/INV-PLAN-ELIGIBLE-ASSETS-ONLY-001.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY | DEPRECATED |

### Scheduling — CRUD Island Retirement

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CRUD-ISLAND-RETIRED-001 | [invariants/core/scheduling/INV-CRUD-ISLAND-RETIRED-001.md](invariants/core/scheduling/INV-CRUD-ISLAND-RETIRED-001.md) | LAW-CONTENT-AUTHORITY |

### Scheduling — ScheduleDay

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-SCHEDULEDAY-ONE-PER-DATE-001 | [invariants/core/schedule-day/INV-SCHEDULEDAY-ONE-PER-DATE-001.md](invariants/core/schedule-day/INV-SCHEDULEDAY-ONE-PER-DATE-001.md) | LAW-DERIVATION, LAW-IMMUTABILITY |
| INV-SCHEDULEDAY-IMMUTABLE-001 | [invariants/core/schedule-day/INV-SCHEDULEDAY-IMMUTABLE-001.md](invariants/core/schedule-day/INV-SCHEDULEDAY-IMMUTABLE-001.md) | LAW-IMMUTABILITY, LAW-DERIVATION |
| INV-SCHEDULEDAY-NO-GAPS-001 | [invariants/core/schedule-day/INV-SCHEDULEDAY-NO-GAPS-001.md](invariants/core/schedule-day/INV-SCHEDULEDAY-NO-GAPS-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS |
| INV-SCHEDULEDAY-LEAD-TIME-001 | [invariants/core/schedule-day/INV-SCHEDULEDAY-LEAD-TIME-001.md](invariants/core/schedule-day/INV-SCHEDULEDAY-LEAD-TIME-001.md) | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY | `min_schedule_day_lead_days` (default: 3) |
| INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | [invariants/core/schedule-day/INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001.md](invariants/core/schedule-day/INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 | [invariants/core/schedule-day/INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001.md](invariants/core/schedule-day/INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001.md) | LAW-GRID, LAW-DERIVATION |

### Scheduling — ExecutionEntry

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-EXECUTIONENTRY-ELIGIBLE-CONTENT-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-ELIGIBLE-CONTENT-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-ELIGIBLE-CONTENT-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |
| INV-EXECUTIONENTRY-MASTERCLOCK-ALIGNED-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-MASTERCLOCK-ALIGNED-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-MASTERCLOCK-ALIGNED-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CLOCK |
| INV-EXECUTIONENTRY-LOOKAHEAD-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-LOOKAHEAD-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-LOOKAHEAD-001.md) | LAW-RUNTIME-AUTHORITY, LAW-LIVENESS |
| INV-EXECUTIONENTRY-NO-GAPS-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-NO-GAPS-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-NO-GAPS-001.md) | LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001.md) | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-EXECUTIONENTRY-LOCKED-IMMUTABLE-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-LOCKED-IMMUTABLE-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-LOCKED-IMMUTABLE-001.md) | LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY |
| INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001.md) | LAW-RUNTIME-AUTHORITY |
| INV-EXECUTIONENTRY-CROSSDAY-NOT-SPLIT-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-CROSSDAY-NOT-SPLIT-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-CROSSDAY-NOT-SPLIT-001.md) | LAW-RUNTIME-AUTHORITY, LAW-IMMUTABILITY |
| INV-EXECUTIONENTRY-SINGLE-AUTHORITY-AT-TIME-001 | [invariants/core/execution-entry/INV-EXECUTIONENTRY-SINGLE-AUTHORITY-AT-TIME-001.md](invariants/core/execution-entry/INV-EXECUTIONENTRY-SINGLE-AUTHORITY-AT-TIME-001.md) | LAW-RUNTIME-AUTHORITY |

### Scheduling — TransmissionLog

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001 | [invariants/core/transmission-log/INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001.md](invariants/core/transmission-log/INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001.md) | LAW-GRID |

### Scheduling — Cross-cutting

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 | [invariants/core/cross-cutting/INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001.md](invariants/core/cross-cutting/INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-DERIVATION-ANCHOR-PROTECTED-001 | [invariants/core/cross-cutting/INV-DERIVATION-ANCHOR-PROTECTED-001.md](invariants/core/cross-cutting/INV-DERIVATION-ANCHOR-PROTECTED-001.md) | LAW-DERIVATION, LAW-IMMUTABILITY |
| INV-ASRUN-IMMUTABLE-001 | [invariants/core/cross-cutting/INV-ASRUN-IMMUTABLE-001.md](invariants/core/cross-cutting/INV-ASRUN-IMMUTABLE-001.md) | LAW-IMMUTABILITY |
| INV-NO-MID-PROGRAM-CUT-001 | [invariants/core/cross-cutting/INV-NO-MID-PROGRAM-CUT-001.md](invariants/core/cross-cutting/INV-NO-MID-PROGRAM-CUT-001.md) | LAW-DERIVATION, LAW-GRID |
| INV-ASRUN-TRACEABILITY-001 | [invariants/core/cross-cutting/INV-ASRUN-TRACEABILITY-001.md](invariants/core/cross-cutting/INV-ASRUN-TRACEABILITY-001.md) | LAW-DERIVATION |
| INV-NO-FOREIGN-CONTENT-001 | [invariants/core/cross-cutting/INV-NO-FOREIGN-CONTENT-001.md](invariants/core/cross-cutting/INV-NO-FOREIGN-CONTENT-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CHANNEL-TIMELINE-CONTINUITY-001 | [invariants/core/cross-cutting/INV-CHANNEL-TIMELINE-CONTINUITY-001.md](invariants/core/cross-cutting/INV-CHANNEL-TIMELINE-CONTINUITY-001.md) | LAW-CLOCK, LAW-TIMELINE |
| INV-BROADCASTDAY-PROJECTION-TRACEABLE-001 | [invariants/core/cross-cutting/INV-BROADCASTDAY-PROJECTION-TRACEABLE-001.md](invariants/core/cross-cutting/INV-BROADCASTDAY-PROJECTION-TRACEABLE-001.md) | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY |
| INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 | [invariants/core/cross-cutting/INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001.md](invariants/core/cross-cutting/INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001.md) | LAW-IMMUTABILITY, LAW-DERIVATION |
| INV-PLAYLOG-NO-RETROACTIVE-FILL-001 | [invariants/core/cross-cutting/INV-PLAYLOG-NO-RETROACTIVE-FILL-001.md](invariants/core/cross-cutting/INV-PLAYLOG-NO-RETROACTIVE-FILL-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CLOCK |

### Scheduling — Multi-channel

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-MULTICHANNEL-ISOLATION-001 | [invariants/core/scheduling/INV-MULTICHANNEL-ISOLATION-001.md](invariants/core/scheduling/INV-MULTICHANNEL-ISOLATION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-MULTICHANNEL-SEED-INDEPENDENCE-001 | [invariants/core/scheduling/INV-MULTICHANNEL-SEED-INDEPENDENCE-001.md](invariants/core/scheduling/INV-MULTICHANNEL-SEED-INDEPENDENCE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

### Scheduling — Compilation & Restart

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-STARTUP-POISON-DETECTION-001 | [invariants/core/scheduling/INV-STARTUP-POISON-DETECTION-001.md](invariants/core/scheduling/INV-STARTUP-POISON-DETECTION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-REVISION-NONEMPTY-PROGRAMMED-001 | [invariants/core/scheduling/INV-REVISION-NONEMPTY-PROGRAMMED-001.md](invariants/core/scheduling/INV-REVISION-NONEMPTY-PROGRAMMED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-SCHEDULEREVISION-IMMUTABLE-001 | [invariants/core/schedule-revision/INV-SCHEDULEREVISION-IMMUTABLE-001.md](invariants/core/schedule-revision/INV-SCHEDULEREVISION-IMMUTABLE-001.md) | LAW-IMMUTABILITY, LAW-DERIVATION |
| INV-COMPILE-NO-FUTURE-INFLUENCE-001 | [invariants/core/scheduling/INV-COMPILE-NO-FUTURE-INFLUENCE-001.md](invariants/core/scheduling/INV-COMPILE-NO-FUTURE-INFLUENCE-001.md) | LAW-DERIVATION, LAW-IMMUTABILITY |
| INV-COMPILE-CHRONOLOGICAL-ORDER-001 | [invariants/core/scheduling/INV-COMPILE-CHRONOLOGICAL-ORDER-001.md](invariants/core/scheduling/INV-COMPILE-CHRONOLOGICAL-ORDER-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-COMPILE-NO-HORIZON-GLOBAL-001 | [invariants/core/scheduling/INV-COMPILE-NO-HORIZON-GLOBAL-001.md](invariants/core/scheduling/INV-COMPILE-NO-HORIZON-GLOBAL-001.md) | LAW-DERIVATION, LAW-IMMUTABILITY |
| INV-COMPILE-DETERMINISTIC-001 | [invariants/core/scheduling/INV-COMPILE-DETERMINISTIC-001.md](invariants/core/scheduling/INV-COMPILE-DETERMINISTIC-001.md) | LAW-IMMUTABILITY, LAW-CONTENT-AUTHORITY |
| INV-RUNTIME-CACHE-DERIVED-001 | [invariants/core/scheduling/INV-RUNTIME-CACHE-DERIVED-001.md](invariants/core/scheduling/INV-RUNTIME-CACHE-DERIVED-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-CARRY-IN-DAY-MINUS-ONE-ONLY-001 | [invariants/core/scheduling/INV-CARRY-IN-DAY-MINUS-ONE-ONLY-001.md](invariants/core/scheduling/INV-CARRY-IN-DAY-MINUS-ONE-ONLY-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |

### Scheduling — Execution Boundary

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CHANNELMANAGER-NO-PLANNING-001 | [invariants/core/execution-boundary/INV-CHANNELMANAGER-NO-PLANNING-001.md](invariants/core/execution-boundary/INV-CHANNELMANAGER-NO-PLANNING-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001 | [invariants/core/execution-boundary/INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001.md](invariants/core/execution-boundary/INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001.md) | LAW-RUNTIME-AUTHORITY, LAW-DERIVATION |
| INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001 | [invariants/core/execution-boundary/INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001.md](invariants/core/execution-boundary/INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-FUTURE-WINDOW-MUTABLE-001 | [invariants/core/execution-boundary/INV-FUTURE-WINDOW-MUTABLE-001.md](invariants/core/execution-boundary/INV-FUTURE-WINDOW-MUTABLE-001.md) | LAW-IMMUTABILITY, LAW-CONTENT-AUTHORITY |
| INV-MATERIAL-RESOLVED-BEFORE-HORIZON-ENTRY-001 | [invariants/core/execution-boundary/INV-MATERIAL-RESOLVED-BEFORE-HORIZON-ENTRY-001.md](invariants/core/execution-boundary/INV-MATERIAL-RESOLVED-BEFORE-HORIZON-ENTRY-001.md) | LAW-ELIGIBILITY, LAW-RUNTIME-AUTHORITY |
| INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001 | [invariants/core/execution-boundary/INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001.md](invariants/core/execution-boundary/INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-SWITCH-BOUNDARY-TIMING | [invariants/core/execution-boundary/INV-SWITCH-BOUNDARY-TIMING.md](invariants/core/execution-boundary/INV-SWITCH-BOUNDARY-TIMING.md) | — |

### Scheduling — Break Detection

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-BREAK-001 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAK-002 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY |
| INV-BREAK-003 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-BREAK-004 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAK-005 | [break_detection.md](break_detection.md) | LAW-GRID, LAW-DERIVATION |
| INV-BREAK-006 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAK-007 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY |
| INV-BREAK-008 | [break_detection.md](break_detection.md) | LAW-DERIVATION |
| INV-BREAK-009 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY |
| INV-BREAK-010 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY |
| INV-BREAK-011 | [break_detection.md](break_detection.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-BREAK-012 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY |
| INV-BREAK-PLACEMENT-FALLBACK-001 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY |
| INV-BREAK-BUDGET-EQUAL-001 | [break_detection.md](break_detection.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-PLACEMENT-STRUCTURE-001 | [placement_dsl.md](placement_dsl.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-PLACEMENT-COUNT-001 | [placement_dsl.md](placement_dsl.md) | LAW-CONTENT-AUTHORITY |
| INV-PLACEMENT-BOUNDS-001 | [placement_dsl.md](placement_dsl.md) | LAW-CONTENT-AUTHORITY |

### Scheduling — BreakPlan

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-BREAKPLAN-ORDERED-001 | [break_plan.md](break_plan.md) | LAW-DERIVATION, LAW-GRID |
| INV-BREAKPLAN-POSITIONS-BOUNDED-001 | [break_plan.md](break_plan.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-BREAKPLAN-BUDGET-DERIVED-001 | [break_plan.md](break_plan.md) | LAW-GRID, LAW-DERIVATION |
| INV-BREAKPLAN-ALLOCATION-BOUNDED-001 | [break_plan.md](break_plan.md) | LAW-GRID |
| INV-BREAKPLAN-IMMUTABLE-001 | [break_plan.md](break_plan.md) | LAW-IMMUTABILITY, LAW-DERIVATION |
| INV-BREAKPLAN-SOLE-AUTHORITY-001 | [break_plan.md](break_plan.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAKPLAN-EMPTY-VALID-001 | [break_plan.md](break_plan.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |

### Scheduling — BreakStructure

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-BREAKSTRUCTURE-ORDERED-001 | [break_structure.md](break_structure.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAKSTRUCTURE-BUDGET-EXACT-001 | [break_structure.md](break_structure.md) | LAW-GRID |
| INV-BREAKSTRUCTURE-INTERSTITIAL-REQUIRED-001 | [break_structure.md](break_structure.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-BREAKSTRUCTURE-TRAFFIC-SCOPE-001 | [break_structure.md](break_structure.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAKSTRUCTURE-DETERMINISTIC-001 | [break_structure.md](break_structure.md) | LAW-DERIVATION |
| INV-BREAKSTRUCTURE-NO-INVENT-001 | [break_structure.md](break_structure.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

### Scheduling — Traffic Policy

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TRAFFIC-ALLOWED-TYPE-001 | [traffic_policy.md](traffic_policy.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |
| INV-TRAFFIC-COOLDOWN-001 | [traffic_policy.md](traffic_policy.md) | LAW-ELIGIBILITY |
| INV-TRAFFIC-DAILY-CAP-001 | [traffic_policy.md](traffic_policy.md) | LAW-ELIGIBILITY |
| INV-TRAFFIC-ROTATION-001 | [traffic_policy.md](traffic_policy.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TRAFFIC-FILTER-ORDER-001 | [traffic_policy.md](traffic_policy.md) | LAW-DERIVATION |
| INV-TRAFFIC-PURE-001 | [traffic_policy.md](traffic_policy.md) | LAW-DERIVATION |
| INV-TRAFFIC-EMPTY-001 | [traffic_policy.md](traffic_policy.md) | LAW-ELIGIBILITY |
| INV-TRAFFIC-NONE-001 | [traffic_policy.md](traffic_policy.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |

### Scheduling — Scheduling Policies

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-POLICY-PURE-001 | [invariants/core/scheduling-policy/INV-POLICY-PURE-001.md](invariants/core/scheduling-policy/INV-POLICY-PURE-001.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |
| INV-POLICY-LAYERED-001 | [invariants/core/scheduling-policy/INV-POLICY-LAYERED-001.md](invariants/core/scheduling-policy/INV-POLICY-LAYERED-001.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |
| INV-POLICY-IDEMPOTENT-001 | [invariants/core/scheduling-policy/INV-POLICY-IDEMPOTENT-001.md](invariants/core/scheduling-policy/INV-POLICY-IDEMPOTENT-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-POLICY-DSL-DECLARED-001 | [invariants/core/scheduling-policy/INV-POLICY-DSL-DECLARED-001.md](invariants/core/scheduling-policy/INV-POLICY-DSL-DECLARED-001.md) | LAW-CONTENT-AUTHORITY |
| INV-POLICY-VIOLATION-STRUCTURED-001 | [invariants/core/scheduling-policy/INV-POLICY-VIOLATION-STRUCTURED-001.md](invariants/core/scheduling-policy/INV-POLICY-VIOLATION-STRUCTURED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

Canonical contract: [scheduling_policies.md](scheduling_policies.md)

### Scheduling — DSL Vocabulary

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-DSL-VOCABULARY-001 | [dsl_vocabulary.md](dsl_vocabulary.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

Canonical contract: [dsl_vocabulary.md](dsl_vocabulary.md)

### Scheduling — Traffic DSL

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001 | [traffic_dsl.md](traffic_dsl.md) | LAW-CONTENT-AUTHORITY, LAW-ELIGIBILITY |
| INV-TRAFFIC-DSL-POOL-REF-VALID-001 | [traffic_dsl.md](traffic_dsl.md) | LAW-DERIVATION, LAW-ELIGIBILITY |
| INV-TRAFFIC-DSL-PROFILE-REF-VALID-001 | [traffic_dsl.md](traffic_dsl.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001 | [traffic_dsl.md](traffic_dsl.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001 | [traffic_dsl.md](traffic_dsl.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TRAFFIC-DSL-BREAK-CONFIG-001 | [traffic_dsl.md](traffic_dsl.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

### Scheduling — Traffic Manager

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TRAFFIC-FILL-STRUCTURED-001 | [traffic_manager.md](traffic_manager.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TRAFFIC-FILL-BUMPER-DEGRADE-001 | [traffic_manager.md](traffic_manager.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-TRAFFIC-FILL-EXACT-001 | [traffic_manager.md](traffic_manager.md) | LAW-GRID |
| INV-TRAFFIC-FILL-PAD-DISTRIBUTED-001 | [traffic_manager.md](traffic_manager.md) | LAW-GRID |
| INV-TRAFFIC-FILL-ORDER-001 | [traffic_manager.md](traffic_manager.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-TRAFFIC-FILL-NO-INVENT-001 | [traffic_manager.md](traffic_manager.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TRAFFIC-FILL-ROTATION-ADVANCES-001 | [traffic_manager.md](traffic_manager.md) | LAW-ELIGIBILITY, LAW-DERIVATION |
| INV-TRAFFIC-FILL-LATE-BIND-001 | [traffic_manager.md](traffic_manager.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |
| INV-TRAFFIC-FILL-FALLBACK-001 | [traffic_manager.md](traffic_manager.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-TRAFFIC-FILL-BUDGET-001 | [traffic_manager.md](traffic_manager.md) | LAW-GRID, LAW-DERIVATION |
| INV-TRAFFIC-FILL-CACHED-QUERY-001 | [traffic_manager.md](traffic_manager.md) | LAW-GRID, LAW-DERIVATION |

### Scheduling — Episode Progression

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-EPISODE-PROGRESSION-001 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-001.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-EPISODE-PROGRESSION-002 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-002.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-002.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-EPISODE-PROGRESSION-003 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-003.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-003.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-EPISODE-PROGRESSION-004 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-004.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-004.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-EPISODE-PROGRESSION-005 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-005.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-005.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-EPISODE-PROGRESSION-006 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-006.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-006.md) | LAW-CONTENT-AUTHORITY |
| INV-EPISODE-PROGRESSION-009 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-009.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-009.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-EPISODE-PROGRESSION-010 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-010.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-010.md) | LAW-CONTENT-AUTHORITY, LAW-IMMUTABILITY |
| INV-EPISODE-PROGRESSION-011 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-011.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-011.md) | LAW-CONTENT-AUTHORITY |
| INV-EPISODE-PROGRESSION-012 | [invariants/core/episode-progression/INV-EPISODE-PROGRESSION-012.md](invariants/core/episode-progression/INV-EPISODE-PROGRESSION-012.md) | LAW-DERIVATION |

Canonical contract: [episode_progression.md](episode_progression.md)

### Scheduling — Program Presentation

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-PRESENTATION-SINGLE-PRIMARY-001 | [invariants/core/program-presentation/INV-PRESENTATION-SINGLE-PRIMARY-001.md](invariants/core/program-presentation/INV-PRESENTATION-SINGLE-PRIMARY-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PRESENTATION-PRECEDES-PRIMARY-001 | [invariants/core/program-presentation/INV-PRESENTATION-PRECEDES-PRIMARY-001.md](invariants/core/program-presentation/INV-PRESENTATION-PRECEDES-PRIMARY-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001 | [invariants/core/program-presentation/INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001.md](invariants/core/program-presentation/INV-PRESENTATION-FIRST-CONTENT-IDENTITY-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PRESENTATION-GRID-BUDGET-001 | [invariants/core/program-presentation/INV-PRESENTATION-GRID-BUDGET-001.md](invariants/core/program-presentation/INV-PRESENTATION-GRID-BUDGET-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-PRESENTATION-NOT-FILLER-001 | [invariants/core/program-presentation/INV-PRESENTATION-NOT-FILLER-001.md](invariants/core/program-presentation/INV-PRESENTATION-NOT-FILLER-001.md) | LAW-CONTENT-AUTHORITY, LAW-ELIGIBILITY |
| INV-PRESENTATION-BREAK-INVISIBLE-001 | [invariants/core/program-presentation/INV-PRESENTATION-BREAK-INVISIBLE-001.md](invariants/core/program-presentation/INV-PRESENTATION-BREAK-INVISIBLE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PRESENTATION-CONTEXTUAL-SELECT-001 | [invariants/core/program-presentation/INV-PRESENTATION-CONTEXTUAL-SELECT-001.md](invariants/core/program-presentation/INV-PRESENTATION-CONTEXTUAL-SELECT-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

Canonical contract: [program_presentation.md](program_presentation.md)

### Scheduling — Block Assembly Tiers

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TIER-DISPLACEMENT-001 | [block_assembly_tiers.md](block_assembly_tiers.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-TIER2-OBLIGATION-YAML-ONLY-001 | [block_assembly_tiers.md](block_assembly_tiers.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CLOCK-OBLIGATIONS-OVERRIDE-001 | [invariants/core/block-assembly-tiers/INV-CLOCK-OBLIGATIONS-OVERRIDE-001.md](invariants/core/block-assembly-tiers/INV-CLOCK-OBLIGATIONS-OVERRIDE-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-CLOCK |
| INV-MIDROLL-INTERLEAVE-001 | [invariants/core/block-assembly-tiers/INV-MIDROLL-INTERLEAVE-001.md](invariants/core/block-assembly-tiers/INV-MIDROLL-INTERLEAVE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-STRUCTURAL-RESOLUTION-001 | [invariants/core/block-assembly-tiers/INV-STRUCTURAL-RESOLUTION-001.md](invariants/core/block-assembly-tiers/INV-STRUCTURAL-RESOLUTION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-GRID-SIZING-STRUCTURAL-001 | [invariants/core/block-assembly-tiers/INV-GRID-SIZING-STRUCTURAL-001.md](invariants/core/block-assembly-tiers/INV-GRID-SIZING-STRUCTURAL-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-EXPANSION-NON-MUTATION-001 | [invariants/core/block-assembly-tiers/INV-EXPANSION-NON-MUTATION-001.md](invariants/core/block-assembly-tiers/INV-EXPANSION-NON-MUTATION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TIER3-COMPILE-RESOLUTION-001 | [invariants/core/block-assembly-tiers/INV-TIER3-COMPILE-RESOLUTION-001.md](invariants/core/block-assembly-tiers/INV-TIER3-COMPILE-RESOLUTION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TIER3-NEXT-BLOCK-IDENTITY-001 | [invariants/core/block-assembly-tiers/INV-TIER3-NEXT-BLOCK-IDENTITY-001.md](invariants/core/block-assembly-tiers/INV-TIER3-NEXT-BLOCK-IDENTITY-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TIER3-POOL-DETERMINISTIC-001 | [invariants/core/block-assembly-tiers/INV-TIER3-POOL-DETERMINISTIC-001.md](invariants/core/block-assembly-tiers/INV-TIER3-POOL-DETERMINISTIC-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TIER3-BUDGET-BEFORE-FILL-001 | [invariants/core/block-assembly-tiers/INV-TIER3-BUDGET-BEFORE-FILL-001.md](invariants/core/block-assembly-tiers/INV-TIER3-BUDGET-BEFORE-FILL-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-TIER3-TEMPLATE-DECLARED-001 | [invariants/core/block-assembly-tiers/INV-TIER3-TEMPLATE-DECLARED-001.md](invariants/core/block-assembly-tiers/INV-TIER3-TEMPLATE-DECLARED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TIER3-SUBTYPE-ORDER-001 | [invariants/core/block-assembly-tiers/INV-TIER3-SUBTYPE-ORDER-001.md](invariants/core/block-assembly-tiers/INV-TIER3-SUBTYPE-ORDER-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-STRUCTURAL-TIER-UNIFICATION-001 | [invariants/core/block-assembly-tiers/INV-STRUCTURAL-TIER-UNIFICATION-001.md](invariants/core/block-assembly-tiers/INV-STRUCTURAL-TIER-UNIFICATION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PRIMARY-CONTENT-UNINTERRUPTIBLE-001 | [invariants/core/block-assembly-tiers/INV-PRIMARY-CONTENT-UNINTERRUPTIBLE-001.md](invariants/core/block-assembly-tiers/INV-PRIMARY-CONTENT-UNINTERRUPTIBLE-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-ASSEMBLY-SEQUENCE-001 | [block_assembly_tiers.md](block_assembly_tiers.md) | LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-DERIVATION |

Canonical contract: [block_assembly_tiers.md](block_assembly_tiers.md)

### Scheduling — Coming Up Next (CUN)

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CUN-FEATURE-FLAG-001 | [invariants/core/cun/INV-CUN-FEATURE-FLAG-001.md](invariants/core/cun/INV-CUN-FEATURE-FLAG-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CUN-SCHEDULE-SCOPED-001 | [invariants/core/cun/INV-CUN-SCHEDULE-SCOPED-001.md](invariants/core/cun/INV-CUN-SCHEDULE-SCOPED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CUN-RENDER-IDLE-001 | [invariants/core/cun/INV-CUN-RENDER-IDLE-001.md](invariants/core/cun/INV-CUN-RENDER-IDLE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CUN-RENDER-DEADLINE-001 | [invariants/core/cun/INV-CUN-RENDER-DEADLINE-001.md](invariants/core/cun/INV-CUN-RENDER-DEADLINE-001.md) | LAW-CONTENT-AUTHORITY, LAW-CLOCK |
| INV-CUN-SKIP-IF-UNREADY-001 | [invariants/core/cun/INV-CUN-SKIP-IF-UNREADY-001.md](invariants/core/cun/INV-CUN-SKIP-IF-UNREADY-001.md) | LAW-LIVENESS, LAW-CONTENT-AUTHORITY |
| INV-CUN-PRIORITY-PLAYOUT-001 | [invariants/core/cun/INV-CUN-PRIORITY-PLAYOUT-001.md](invariants/core/cun/INV-CUN-PRIORITY-PLAYOUT-001.md) | LAW-CONTENT-AUTHORITY, LAW-CLOCK |
| INV-CUN-CACHE-UNTIL-USED-001 | [invariants/core/cun/INV-CUN-CACHE-UNTIL-USED-001.md](invariants/core/cun/INV-CUN-CACHE-UNTIL-USED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CUN-CACHE-SAFE-CLEANUP-001 | [invariants/core/cun/INV-CUN-CACHE-SAFE-CLEANUP-001.md](invariants/core/cun/INV-CUN-CACHE-SAFE-CLEANUP-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CUN-DEDUP-BEFORE-RENDER-001 | [invariants/core/cun/INV-CUN-DEDUP-BEFORE-RENDER-001.md](invariants/core/cun/INV-CUN-DEDUP-BEFORE-RENDER-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CUN-CACHE-DEDUP-001 | [invariants/core/cun/INV-CUN-CACHE-DEDUP-001.md](invariants/core/cun/INV-CUN-CACHE-DEDUP-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CUN-TEMPLATE-DETERMINISTIC-001 | [invariants/core/cun/INV-CUN-TEMPLATE-DETERMINISTIC-001.md](invariants/core/cun/INV-CUN-TEMPLATE-DETERMINISTIC-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

Canonical contract: [cun_synthesis_contract.md](cun_synthesis_contract.md)

### Scheduling — Template Compilation

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001 | [invariants/core/template-compilation/INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001.md](invariants/core/template-compilation/INV-TEMPLATE-BEHAVIOR-NOT-DURATION-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAK-BUDGET-DERIVED-001 | [invariants/core/template-compilation/INV-BREAK-BUDGET-DERIVED-001.md](invariants/core/template-compilation/INV-BREAK-BUDGET-DERIVED-001.md) | LAW-GRID, LAW-DERIVATION |
| INV-BREAK-COUNT-DURATION-SEPARATED-001 | [invariants/core/template-compilation/INV-BREAK-COUNT-DURATION-SEPARATED-001.md](invariants/core/template-compilation/INV-BREAK-COUNT-DURATION-SEPARATED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAK-DENSITY-SCALES-001 | [invariants/core/template-compilation/INV-BREAK-DENSITY-SCALES-001.md](invariants/core/template-compilation/INV-BREAK-DENSITY-SCALES-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-BREAK-EXPAND-TO-FILL-001 | [invariants/core/template-compilation/INV-BREAK-EXPAND-TO-FILL-001.md](invariants/core/template-compilation/INV-BREAK-EXPAND-TO-FILL-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-CONFORMANCE-MANDATORY-001 | [invariants/core/template-compilation/INV-CONFORMANCE-MANDATORY-001.md](invariants/core/template-compilation/INV-CONFORMANCE-MANDATORY-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-CONTINUITY-DURATION-FILTER-001 | [invariants/core/template-compilation/INV-CONTINUITY-DURATION-FILTER-001.md](invariants/core/template-compilation/INV-CONTINUITY-DURATION-FILTER-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-BREAK-PLACEMENT-PRIORITY-001 | [invariants/core/template-compilation/INV-BREAK-PLACEMENT-PRIORITY-001.md](invariants/core/template-compilation/INV-BREAK-PLACEMENT-PRIORITY-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

Canonical contracts: [timeline_compilation_templates.md](timeline_compilation_templates.md), [chapter_marker_break_placement.md](chapter_marker_break_placement.md)

### Scheduling — Traffic Profiles & Conformance

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-OVERCONSTRAINED-POLICY-001 | [invariants/core/traffic-conformance/INV-OVERCONSTRAINED-POLICY-001.md](invariants/core/traffic-conformance/INV-OVERCONSTRAINED-POLICY-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-TRAFFIC-PROFILE-RESOLVED-001 | [invariants/core/traffic-conformance/INV-TRAFFIC-PROFILE-RESOLVED-001.md](invariants/core/traffic-conformance/INV-TRAFFIC-PROFILE-RESOLVED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-UNDERRUN-WARNING-001 | [invariants/core/traffic-conformance/INV-UNDERRUN-WARNING-001.md](invariants/core/traffic-conformance/INV-UNDERRUN-WARNING-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |

Canonical contract: [traffic_profiles_conformance.md](traffic_profiles_conformance.md)

### Scheduling — Programming Pools

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-POOL-RATING-NORMALIZE-001 | [invariants/core/programming-pools/INV-POOL-RATING-NORMALIZE-001.md](invariants/core/programming-pools/INV-POOL-RATING-NORMALIZE-001.md) | LAW-DERIVATION |
| INV-POOL-TAGS-FILTER-001 | [invariants/core/programming-pools/INV-POOL-TAGS-FILTER-001.md](invariants/core/programming-pools/INV-POOL-TAGS-FILTER-001.md) | LAW-DERIVATION |
| INV-POOL-RESOLUTION-VISIBILITY-001 | [invariants/core/programming-pools/INV-POOL-RESOLUTION-VISIBILITY-001.md](invariants/core/programming-pools/INV-POOL-RESOLUTION-VISIBILITY-001.md) | LAW-DERIVATION |
| INV-POOL-NAME-UNIQUE-001 | [invariants/core/programming-pools/INV-POOL-NAME-UNIQUE-001.md](invariants/core/programming-pools/INV-POOL-NAME-UNIQUE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-POOL-CLI-DELEGATES-001 | [invariants/core/programming-pools/INV-POOL-CLI-DELEGATES-001.md](invariants/core/programming-pools/INV-POOL-CLI-DELEGATES-001.md) | LAW-CONTENT-AUTHORITY |

Canonical contracts: [core/programming_pools.md](core/programming_pools.md), [pool_management.md](pool_management.md)

### Ingest — Validation & Enrichment Pipeline

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001 | [invariants/core/ingest/INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001.md](invariants/core/ingest/INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001 | [invariants/core/ingest/INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001.md](invariants/core/ingest/INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-ASSET-TAGS-PERSISTED-CORRECTLY-001 | [invariants/core/ingest/INV-ASSET-TAGS-PERSISTED-CORRECTLY-001.md](invariants/core/ingest/INV-ASSET-TAGS-PERSISTED-CORRECTLY-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-ASSET-LIFECYCLE-COMPLETION-001 | [invariants/core/ingest/INV-ASSET-LIFECYCLE-COMPLETION-001.md](invariants/core/ingest/INV-ASSET-LIFECYCLE-COMPLETION-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-VALIDATOR-OUTPUT-SHAPE-001 | [invariants/core/ingest/INV-VALIDATOR-OUTPUT-SHAPE-001.md](invariants/core/ingest/INV-VALIDATOR-OUTPUT-SHAPE-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-ENRICHER-IDEMPOTENT-001 | [invariants/core/ingest/INV-ENRICHER-IDEMPOTENT-001.md](invariants/core/ingest/INV-ENRICHER-IDEMPOTENT-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-CATALOG-READY-SCHEDULABLE-001 | [invariants/core/ingest/INV-CATALOG-READY-SCHEDULABLE-001.md](invariants/core/ingest/INV-CATALOG-READY-SCHEDULABLE-001.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |
| INV-ENRICHER-EXECUTION-MODE-001 | [invariants/core/ingest/INV-ENRICHER-EXECUTION-MODE-001.md](invariants/core/ingest/INV-ENRICHER-EXECUTION-MODE-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-ENRICHER-OBSERVABILITY-001 | [invariants/core/ingest/INV-ENRICHER-OBSERVABILITY-001.md](invariants/core/ingest/INV-ENRICHER-OBSERVABILITY-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-ENRICHER-RESULT-VERSIONED-001 | [invariants/core/ingest/INV-ENRICHER-RESULT-VERSIONED-001.md](invariants/core/ingest/INV-ENRICHER-RESULT-VERSIONED-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-PATH-MAPPING-SOURCE-SCOPED-001 | [invariants/core/ingest/INV-PATH-MAPPING-SOURCE-SCOPED-001.md](invariants/core/ingest/INV-PATH-MAPPING-SOURCE-SCOPED-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PATH-VALIDATION-ON-IMPORT-001 | [invariants/core/ingest/INV-PATH-VALIDATION-ON-IMPORT-001.md](invariants/core/ingest/INV-PATH-VALIDATION-ON-IMPORT-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-SOURCE-TYPE-REGISTRY-001 | [invariants/core/ingest/INV-SOURCE-TYPE-REGISTRY-001.md](invariants/core/ingest/INV-SOURCE-TYPE-REGISTRY-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-VALIDATOR-RESULT-PERSISTENCE-001 | [invariants/core/ingest/INV-VALIDATOR-RESULT-PERSISTENCE-001.md](invariants/core/ingest/INV-VALIDATOR-RESULT-PERSISTENCE-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-TAG-CANONICAL-FORM-001 | [invariants/core/ingest/INV-TAG-CANONICAL-FORM-001.md](invariants/core/ingest/INV-TAG-CANONICAL-FORM-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-TAG-MIGRATION-IDEMPOTENT-001 | [invariants/core/ingest/INV-TAG-MIGRATION-IDEMPOTENT-001.md](invariants/core/ingest/INV-TAG-MIGRATION-IDEMPOTENT-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-CHAPTER-MARKER-SHAPE-001 | [invariants/core/ingest/INV-CHAPTER-MARKER-SHAPE-001.md](invariants/core/ingest/INV-CHAPTER-MARKER-SHAPE-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-PROCESSOR-READINESS-GATE-001 | [invariants/core/ingest/INV-PROCESSOR-READINESS-GATE-001.md](invariants/core/ingest/INV-PROCESSOR-READINESS-GATE-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |

Canonical contracts: [tag_canonical_form.md](tag_canonical_form.md), [core/ProcessorCapabilityContract_v0.1.md](core/ProcessorCapabilityContract_v0.1.md)

### Ingest — Source Watch Mode

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-WATCH-DELEGATES-001 | [invariants/core/ingest/INV-WATCH-DELEGATES-001.md](invariants/core/ingest/INV-WATCH-DELEGATES-001.md) | LAW-CONTENT-AUTHORITY |
| INV-WATCH-DEBOUNCE-001 | [invariants/core/ingest/INV-WATCH-DEBOUNCE-001.md](invariants/core/ingest/INV-WATCH-DEBOUNCE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

Canonical contract: [source_watch_mode.md](source_watch_mode.md)

### Interaction Boundary

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CLI-NO-BUSINESS-LOGIC-001 | [invariants/core/interaction-boundary/INV-CLI-NO-BUSINESS-LOGIC-001.md](invariants/core/interaction-boundary/INV-CLI-NO-BUSINESS-LOGIC-001.md) | LAW-CONTENT-AUTHORITY |
| INV-API-NO-BUSINESS-LOGIC-001 | [invariants/core/interaction-boundary/INV-API-NO-BUSINESS-LOGIC-001.md](invariants/core/interaction-boundary/INV-API-NO-BUSINESS-LOGIC-001.md) | LAW-CONTENT-AUTHORITY |
| INV-WORKFLOW-FLAT-NESTING-001 | [invariants/core/interaction-boundary/INV-WORKFLOW-FLAT-NESTING-001.md](invariants/core/interaction-boundary/INV-WORKFLOW-FLAT-NESTING-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

### Scheduling — Schedule Block Program Reference

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-SBLOCK-PROGRAM-001 | [schedule_block_program_reference.md](schedule_block_program_reference.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-SBLOCK-PROGRAM-002 | [schedule_block_program_reference.md](schedule_block_program_reference.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-SBLOCK-PROGRAM-003 | [schedule_block_program_reference.md](schedule_block_program_reference.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |
| INV-SBLOCK-PROGRAM-004 | [schedule_block_program_reference.md](schedule_block_program_reference.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-SBLOCK-PROGRAM-005 | [schedule_block_program_reference.md](schedule_block_program_reference.md) | LAW-CONTENT-AUTHORITY |
| INV-SBLOCK-PROGRAM-006 | [schedule_block_program_reference.md](schedule_block_program_reference.md) | LAW-GRID, LAW-CONTENT-AUTHORITY |

Canonical contract: [schedule_block_program_reference.md](schedule_block_program_reference.md)

### Scheduling — Schedule Lifecycle

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-SCHEDULE-PREWARM-001 | [invariants/core/scheduling/INV-SCHEDULE-PREWARM-001.md](invariants/core/scheduling/INV-SCHEDULE-PREWARM-001.md) | LAW-LIVENESS, INV-CHANNEL-STARTUP-NONBLOCKING-001 |
| INV-TIER2-COMPILATION-CONSISTENCY-001 | [invariants/core/scheduling/INV-TIER2-COMPILATION-CONSISTENCY-001.md](invariants/core/scheduling/INV-TIER2-COMPILATION-CONSISTENCY-001.md) | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY |
| INV-RESCHEDULE-FUTURE-GUARD-001 | [invariants/core/scheduling/INV-RESCHEDULE-FUTURE-GUARD-001.md](invariants/core/scheduling/INV-RESCHEDULE-FUTURE-GUARD-001.md) | LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY |
| INV-RESCHEDULE-CASCADE-TIER2-001 | [invariants/core/scheduling/INV-RESCHEDULE-CASCADE-TIER2-001.md](invariants/core/scheduling/INV-RESCHEDULE-CASCADE-TIER2-001.md) | LAW-DERIVATION, LAW-IMMUTABILITY |
| INV-CROSS-DAY-CARRY-IN-001 | [invariants/core/scheduling/INV-CROSS-DAY-CARRY-IN-001.md](invariants/core/scheduling/INV-CROSS-DAY-CARRY-IN-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY, LAW-LIVENESS |
| INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001 | [invariants/core/scheduling/INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001.md](invariants/core/scheduling/INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-TIMELINE-SINGLE-AUTHORITY-001 | [invariants/core/scheduling/INV-TIMELINE-SINGLE-AUTHORITY-001.md](invariants/core/scheduling/INV-TIMELINE-SINGLE-AUTHORITY-001.md) | LAW-CONTENT-AUTHORITY, LAW-CLOCK, LAW-DERIVATION |
| INV-TIMELINE-RESTART-IDENTICAL-001 | [invariants/core/scheduling/INV-TIMELINE-RESTART-IDENTICAL-001.md](invariants/core/scheduling/INV-TIMELINE-RESTART-IDENTICAL-001.md) | LAW-IMMUTABILITY, LAW-CONTENT-AUTHORITY |
| INV-TIMELINE-APPEND-ONLY-001 | [invariants/core/scheduling/INV-TIMELINE-APPEND-ONLY-001.md](invariants/core/scheduling/INV-TIMELINE-APPEND-ONLY-001.md) | LAW-IMMUTABILITY, LAW-CONTENT-AUTHORITY |
| INV-TIMELINE-LONGFORM-INVIOLATE-001 | [invariants/core/scheduling/INV-TIMELINE-LONGFORM-INVIOLATE-001.md](invariants/core/scheduling/INV-TIMELINE-LONGFORM-INVIOLATE-001.md) | LAW-CONTENT-AUTHORITY, LAW-TIMELINE, LAW-GRID |
| INV-TIMELINE-CARRY-IN-PRESERVED-001 | [invariants/core/scheduling/INV-TIMELINE-CARRY-IN-PRESERVED-001.md](invariants/core/scheduling/INV-TIMELINE-CARRY-IN-PRESERVED-001.md) | LAW-GRID, LAW-CONTENT-AUTHORITY, LAW-TIMELINE |
| INV-TIMELINE-CONTINUITY-001 | [invariants/core/scheduling/INV-TIMELINE-CONTINUITY-001.md](invariants/core/scheduling/INV-TIMELINE-CONTINUITY-001.md) | LAW-GRID, LAW-LIVENESS, LAW-TIMELINE |
| INV-TIMELINE-EPG-PLAYOUT-AGREE-001 | [invariants/core/scheduling/INV-TIMELINE-EPG-PLAYOUT-AGREE-001.md](invariants/core/scheduling/INV-TIMELINE-EPG-PLAYOUT-AGREE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TIMELINE-BOUNDARY-IMMUTABLE-001 | [invariants/core/scheduling/INV-TIMELINE-BOUNDARY-IMMUTABLE-001.md](invariants/core/scheduling/INV-TIMELINE-BOUNDARY-IMMUTABLE-001.md) | LAW-IMMUTABILITY, LAW-CONTENT-AUTHORITY, LAW-TIMELINE |
| INV-SCHEDULE-REVISION-MONOTONICITY-001 | [invariants/core/scheduling/INV-SCHEDULE-REVISION-MONOTONICITY-001.md](invariants/core/scheduling/INV-SCHEDULE-REVISION-MONOTONICITY-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |

### Scheduling — Schedule Constraints

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CONSTRAINT-BLACKOUT-001 | [invariants/core/schedule-constraints/INV-CONSTRAINT-BLACKOUT-001.md](invariants/core/schedule-constraints/INV-CONSTRAINT-BLACKOUT-001.md) | LAW-CONTENT-AUTHORITY, LAW-ELIGIBILITY |
| INV-CONSTRAINT-ADJACENCY-001 | [invariants/core/schedule-constraints/INV-CONSTRAINT-ADJACENCY-001.md](invariants/core/schedule-constraints/INV-CONSTRAINT-ADJACENCY-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-CONSTRAINT-CONTENT-RESTRICTION-001 | [invariants/core/schedule-constraints/INV-CONSTRAINT-CONTENT-RESTRICTION-001.md](invariants/core/schedule-constraints/INV-CONSTRAINT-CONTENT-RESTRICTION-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001 | [invariants/core/schedule-constraints/INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001.md](invariants/core/schedule-constraints/INV-CONSTRAINT-EVALUATION-IDEMPOTENT-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |

Canonical contract: [schedule_constraints.md](schedule_constraints.md)

### EPG

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-EPG-NO-OVERLAP-001 | [invariants/core/epg/INV-EPG-NO-OVERLAP-001.md](invariants/core/epg/INV-EPG-NO-OVERLAP-001.md) | LAW-GRID, LAW-DERIVATION |
| INV-EPG-NO-GAP-001 | [invariants/core/epg/INV-EPG-NO-GAP-001.md](invariants/core/epg/INV-EPG-NO-GAP-001.md) | LAW-GRID, LAW-LIVENESS |
| INV-EPG-BROADCAST-DAY-BOUNDED-001 | [invariants/core/epg/INV-EPG-BROADCAST-DAY-BOUNDED-001.md](invariants/core/epg/INV-EPG-BROADCAST-DAY-BOUNDED-001.md) | LAW-GRID, LAW-DERIVATION |
| INV-EPG-FILLER-INVISIBLE-001 | [invariants/core/epg/INV-EPG-FILLER-INVISIBLE-001.md](invariants/core/epg/INV-EPG-FILLER-INVISIBLE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-EPG-IDENTITY-STABLE-001 | [invariants/core/epg/INV-EPG-IDENTITY-STABLE-001.md](invariants/core/epg/INV-EPG-IDENTITY-STABLE-001.md) | LAW-IMMUTABILITY, LAW-DERIVATION |
| INV-EPG-DERIVATION-TRACEABLE-001 | [invariants/core/epg/INV-EPG-DERIVATION-TRACEABLE-001.md](invariants/core/epg/INV-EPG-DERIVATION-TRACEABLE-001.md) | LAW-DERIVATION |
| INV-EPG-VIEWER-INDEPENDENT-001 | [invariants/core/epg/INV-EPG-VIEWER-INDEPENDENT-001.md](invariants/core/epg/INV-EPG-VIEWER-INDEPENDENT-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-EPG-PROGRAM-CONTINUITY-001 | [invariants/core/epg/INV-EPG-PROGRAM-CONTINUITY-001.md](invariants/core/epg/INV-EPG-PROGRAM-CONTINUITY-001.md) | LAW-GRID, LAW-DERIVATION |
| INV-EPG-DURATION-VISIBILITY-001 | [invariants/core/epg/INV-EPG-DURATION-VISIBILITY-001.md](invariants/core/epg/INV-EPG-DURATION-VISIBILITY-001.md) | LAW-GRID, LAW-DERIVATION |
| INV-EPG-HORIZON-COVERAGE-001 | [invariants/core/epg/INV-EPG-HORIZON-COVERAGE-001.md](invariants/core/epg/INV-EPG-HORIZON-COVERAGE-001.md) | LAW-DERIVATION, LAW-LIVENESS |

### Asset — Entity Integrity

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-ASSET-MEDIA-IDENTITY | [invariants/core/asset/INV-ASSET-MEDIA-IDENTITY.md](invariants/core/asset/INV-ASSET-MEDIA-IDENTITY.md) | LAW-CONTENT-AUTHORITY, LAW-ELIGIBILITY |
| INV-ASSET-APPROVED-IMPLIES-READY-001 | [invariants/core/asset/INV-ASSET-APPROVED-IMPLIES-READY-001.md](invariants/core/asset/INV-ASSET-APPROVED-IMPLIES-READY-001.md) | LAW-ELIGIBILITY |
| INV-ASSET-SOFTDELETE-SYNC-001 | [invariants/core/asset/INV-ASSET-SOFTDELETE-SYNC-001.md](invariants/core/asset/INV-ASSET-SOFTDELETE-SYNC-001.md) | — |
| INV-ASSET-CANONICAL-KEY-FORMAT-001 | [invariants/core/asset/INV-ASSET-CANONICAL-KEY-FORMAT-001.md](invariants/core/asset/INV-ASSET-CANONICAL-KEY-FORMAT-001.md) | — |
| INV-ASSET-STATE-MACHINE-001 | [invariants/core/asset/INV-ASSET-STATE-MACHINE-001.md](invariants/core/asset/INV-ASSET-STATE-MACHINE-001.md) | LAW-ELIGIBILITY |

### Asset — Enrichment Pipeline

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-ASSET-DURATION-REQUIRED-FOR-READY-001 | [invariants/core/asset/INV-ASSET-DURATION-REQUIRED-FOR-READY-001.md](invariants/core/asset/INV-ASSET-DURATION-REQUIRED-FOR-READY-001.md) | LAW-ELIGIBILITY |
| INV-ASSET-APPROVAL-OPERATOR-ONLY-001 | [invariants/core/asset/INV-ASSET-APPROVAL-OPERATOR-ONLY-001.md](invariants/core/asset/INV-ASSET-APPROVAL-OPERATOR-ONLY-001.md) | LAW-ELIGIBILITY |
| INV-ASSET-REPROBE-RESETS-APPROVAL-001 | [invariants/core/asset/INV-ASSET-REPROBE-RESETS-APPROVAL-001.md](invariants/core/asset/INV-ASSET-REPROBE-RESETS-APPROVAL-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |
| INV-ASSET-REENRICH-RESETS-STALE-001 | [invariants/core/asset/INV-ASSET-REENRICH-RESETS-STALE-001.md](invariants/core/asset/INV-ASSET-REENRICH-RESETS-STALE-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |

### Asset — Metadata Integrity

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 | [invariants/core/asset/INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001.md](invariants/core/asset/INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001.md) | LAW-DERIVATION |
| INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001 | [invariants/core/asset/INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001.md](invariants/core/asset/INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |
| INV-DURATION-EXTRACTION-NORMALIZATION-001 | [invariants/core/asset/INV-DURATION-EXTRACTION-NORMALIZATION-001.md](invariants/core/asset/INV-DURATION-EXTRACTION-NORMALIZATION-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |
| INV-ASSET-MARKER-BOUNDS-001 | [invariants/core/asset/INV-ASSET-MARKER-BOUNDS-001.md](invariants/core/asset/INV-ASSET-MARKER-BOUNDS-001.md) | — |

### Asset — Tag Management

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TAG-RENAME-ATOMIC-001 | [invariants/core/asset/INV-TAG-RENAME-ATOMIC-001.md](invariants/core/asset/INV-TAG-RENAME-ATOMIC-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TAG-MERGE-DEDUP-001 | [invariants/core/asset/INV-TAG-MERGE-DEDUP-001.md](invariants/core/asset/INV-TAG-MERGE-DEDUP-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TAG-BULK-REMOVE-001 | [invariants/core/asset/INV-TAG-BULK-REMOVE-001.md](invariants/core/asset/INV-TAG-BULK-REMOVE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-TAG-SCOPE-ALL-001 | [invariants/core/asset/INV-TAG-SCOPE-ALL-001.md](invariants/core/asset/INV-TAG-SCOPE-ALL-001.md) | LAW-CONTENT-AUTHORITY |
| INV-TAG-SUMMARY-COMPLETE-001 | [invariants/core/asset/INV-TAG-SUMMARY-COMPLETE-001.md](invariants/core/asset/INV-TAG-SUMMARY-COMPLETE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

### Asset — Schedulability & Library Boundary

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001 | [invariants/core/asset/INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001.md](invariants/core/asset/INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001.md) | LAW-ELIGIBILITY |
| INV-ASSET-LIBRARY-PLANNING-ONLY-001 | [invariants/core/asset/INV-ASSET-LIBRARY-PLANNING-ONLY-001.md](invariants/core/asset/INV-ASSET-LIBRARY-PLANNING-ONLY-001.md) | LAW-RUNTIME-AUTHORITY |

### Scheduling — Horizon Management

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HORIZON-PROACTIVE-EXTEND-001 | [invariants/core/horizon/INV-HORIZON-PROACTIVE-EXTEND-001.md](invariants/core/horizon/INV-HORIZON-PROACTIVE-EXTEND-001.md) | LAW-RUNTIME-AUTHORITY, LAW-DERIVATION |
| INV-HORIZON-EXECUTION-MIN-001 | [invariants/core/horizon/INV-HORIZON-EXECUTION-MIN-001.md](invariants/core/horizon/INV-HORIZON-EXECUTION-MIN-001.md) | — |
| INV-HORIZON-NEXT-BLOCK-READY-001 | [invariants/core/horizon/INV-HORIZON-NEXT-BLOCK-READY-001.md](invariants/core/horizon/INV-HORIZON-NEXT-BLOCK-READY-001.md) | LAW-TIMELINE |
| INV-HORIZON-CONTINUOUS-COVERAGE-001 | [invariants/core/horizon/INV-HORIZON-CONTINUOUS-COVERAGE-001.md](invariants/core/horizon/INV-HORIZON-CONTINUOUS-COVERAGE-001.md) | — |
| INV-HORIZON-ATOMIC-PUBLISH-001 | [invariants/core/horizon/INV-HORIZON-ATOMIC-PUBLISH-001.md](invariants/core/horizon/INV-HORIZON-ATOMIC-PUBLISH-001.md) | — |
| INV-HORIZON-LOCKED-IMMUTABLE-001 | [invariants/core/horizon/INV-HORIZON-LOCKED-IMMUTABLE-001.md](invariants/core/horizon/INV-HORIZON-LOCKED-IMMUTABLE-001.md) | — |

### Infrastructure — Channel Purge

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CHANNEL-PURGE-001 | [channel_purge.md](channel_purge.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CHANNEL-PURGE-002 | [channel_purge.md](channel_purge.md) | LAW-CONTENT-AUTHORITY |
| INV-CHANNEL-PURGE-003 | [channel_purge.md](channel_purge.md) | LAW-DERIVATION |

### Infrastructure — Channel Reconciliation

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH | [channel_reconciliation.md](channel_reconciliation.md) | LAW-CONTENT-AUTHORITY |
| INV-CHANNEL-RECONCILE-DELETE | [channel_reconciliation.md](channel_reconciliation.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-CHANNEL-RECONCILE-IDEMPOTENT | [channel_reconciliation.md](channel_reconciliation.md) | LAW-CONTENT-AUTHORITY |
| INV-CHANNEL-RECONCILE-EMPTY-GUARD | [channel_reconciliation.md](channel_reconciliation.md) | LAW-CONTENT-AUTHORITY |

### Infrastructure — Test Isolation

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-TEST-DB-ISOLATION-001 | [invariants/core/cross-cutting/INV-TEST-DB-ISOLATION-001.md](invariants/core/cross-cutting/INV-TEST-DB-ISOLATION-001.md) | — |

### Runtime

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-ASPECT-PRESERVE-001 | [invariants/core/runtime/INV-ASPECT-PRESERVE-001.md](invariants/core/runtime/INV-ASPECT-PRESERVE-001.md) | LAW-RUNTIME-AUTHORITY |
| INV-NO-GHOST-METHODS-001 | [invariants/core/runtime/INV-NO-GHOST-METHODS-001.md](invariants/core/runtime/INV-NO-GHOST-METHODS-001.md) | LAW-SIMPLICITY |
| INV-PRODUCTION-BOUNDARY-001 | [invariants/core/runtime/INV-PRODUCTION-BOUNDARY-001.md](invariants/core/runtime/INV-PRODUCTION-BOUNDARY-001.md) | LAW-SIMPLICITY |
| INV-LIFECYCLE-OBSERVABILITY-001 | [invariants/core/runtime/INV-LIFECYCLE-OBSERVABILITY-001.md](invariants/core/runtime/INV-LIFECYCLE-OBSERVABILITY-001.md) | LAW-SIMPLICITY, LAW-LIVENESS |
| INV-HLS-NO-DISK-IO-001 | [invariants/core/runtime/INV-HLS-NO-DISK-IO-001.md](invariants/core/runtime/INV-HLS-NO-DISK-IO-001.md) | LAW-LIVENESS |
| INV-HLS-QUIET-POLLING-001 | [invariants/core/runtime/INV-HLS-QUIET-POLLING-001.md](invariants/core/runtime/INV-HLS-QUIET-POLLING-001.md) | LAW-LIVENESS |
| INV-BLEED-NO-GAP-001 | [invariants/core/runtime/INV-BLEED-NO-GAP-001.md](invariants/core/runtime/INV-BLEED-NO-GAP-001.md) | LAW-LIVENESS, LAW-GRID |
| INV-SCHEDULE-SEED-DETERMINISTIC-001 | [invariants/core/runtime/INV-SCHEDULE-SEED-DETERMINISTIC-001.md](invariants/core/runtime/INV-SCHEDULE-SEED-DETERMINISTIC-001.md) | LAW-LIVENESS, LAW-CONTENT-AUTHORITY |
| INV-EPG-READS-CANONICAL-SCHEDULE-001 | [invariants/core/runtime/INV-EPG-READS-CANONICAL-SCHEDULE-001.md](invariants/core/runtime/INV-EPG-READS-CANONICAL-SCHEDULE-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-MARATHON-CROSSMIDNIGHT-001 | [invariants/core/runtime/INV-MARATHON-CROSSMIDNIGHT-001.md](invariants/core/runtime/INV-MARATHON-CROSSMIDNIGHT-001.md) | LAW-GRID, LAW-LIVENESS |
| INV-CHANNEL-STARTUP-NONBLOCKING-001 | [invariants/core/runtime/INV-CHANNEL-STARTUP-NONBLOCKING-001.md](invariants/core/runtime/INV-CHANNEL-STARTUP-NONBLOCKING-001.md) | LAW-LIVENESS |
| INV-CHANNEL-STARTUP-CONCURRENCY-001 | [invariants/core/runtime/INV-CHANNEL-STARTUP-CONCURRENCY-001.md](invariants/core/runtime/INV-CHANNEL-STARTUP-CONCURRENCY-001.md) | LAW-LIVENESS, INV-CHANNEL-STARTUP-NONBLOCKING-001 |
| INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001 | [invariants/core/runtime/INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001.md](invariants/core/runtime/INV-PLAYLOG-DAEMON-BATCHED-TXCHECK-001.md) | LAW-LIVENESS |
| INV-PLAYLOG-PLAN-VS-RUNTIME-001 | [invariants/core/runtime/INV-PLAYLOG-PLAN-VS-RUNTIME-001.md](invariants/core/runtime/INV-PLAYLOG-PLAN-VS-RUNTIME-001.md) | LAW-RUNTIME-AUTHORITY, LAW-DERIVATION |
| INV-HLS-PHANTOM-CLEANUP-001 | [invariants/core/runtime/INV-HLS-PHANTOM-CLEANUP-001.md](invariants/core/runtime/INV-HLS-PHANTOM-CLEANUP-001.md) | LAW-LIVENESS |
| INV-HLS-DISCONTINUITY-MARKER-001 | [invariants/core/runtime/INV-HLS-DISCONTINUITY-MARKER-001.md](invariants/core/runtime/INV-HLS-DISCONTINUITY-MARKER-001.md) | LAW-DECODABILITY, LAW-LIVENESS |
| INV-CHANNEL-LIVENESS-RECOVERY-001 | [invariants/core/runtime/INV-CHANNEL-LIVENESS-RECOVERY-001.md](invariants/core/runtime/INV-CHANNEL-LIVENESS-RECOVERY-001.md) | LAW-LIVENESS |
| INV-FEED-MISS-POLICY-001 | [invariants/core/runtime/INV-FEED-MISS-POLICY-001.md](invariants/core/runtime/INV-FEED-MISS-POLICY-001.md) | LAW-LIVENESS, LAW-CLOCK |
| INV-DAEMON-SESSION-SCOPE-001 | [invariants/core/runtime/INV-DAEMON-SESSION-SCOPE-001.md](invariants/core/runtime/INV-DAEMON-SESSION-SCOPE-001.md) | LAW-LIVENESS |
| INV-BLOCKFILL-SUBPROCESS-ISOLATION-001 | [invariants/core/runtime/INV-BLOCKFILL-SUBPROCESS-ISOLATION-001.md](invariants/core/runtime/INV-BLOCKFILL-SUBPROCESS-ISOLATION-001.md) | LAW-LIVENESS |
| INV-BREAK-V2-SINGLE-CHAPTER-001 | [invariants/core/runtime/INV-BREAK-V2-SINGLE-CHAPTER-001.md](invariants/core/runtime/INV-BREAK-V2-SINGLE-CHAPTER-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-AUTHORITY-SINGLE-OWNER-001 | [invariants/core/runtime/INV-AUTHORITY-SINGLE-OWNER-001.md](invariants/core/runtime/INV-AUTHORITY-SINGLE-OWNER-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CLOCK |
| INV-SINGLE-ACTIVATION-PATH-001 | [invariants/core/runtime/INV-SINGLE-ACTIVATION-PATH-001.md](invariants/core/runtime/INV-SINGLE-ACTIVATION-PATH-001.md) | LAW-RUNTIME-AUTHORITY, LAW-LIVENESS |
| INV-SLOW-CONSUMER-DISCONNECT-001 | [invariants/core/runtime/INV-SLOW-CONSUMER-DISCONNECT-001.md](invariants/core/runtime/INV-SLOW-CONSUMER-DISCONNECT-001.md) | LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-PLAYOUT-MODULE-EXTRACTION-001 | [invariants/core/INV-PLAYOUT-MODULE-EXTRACTION-001.md](invariants/core/INV-PLAYOUT-MODULE-EXTRACTION-001.md) | LAW-SIMPLICITY |
| INV-SCHEDULE-COMPILER-MODULE-SPLIT-001 | [invariants/core/runtime/INV-SCHEDULE-COMPILER-MODULE-SPLIT-001.md](invariants/core/runtime/INV-SCHEDULE-COMPILER-MODULE-SPLIT-001.md) | LAW-SIMPLICITY |
| INV-CUN-SCHEDULE-SCOPED-001 | [invariants/core/runtime/INV-CUN-SCHEDULE-SCOPED-001.md](invariants/core/runtime/INV-CUN-SCHEDULE-SCOPED-001.md) | LAW-CONTENT-AUTHORITY |

### Delivery — HLS Segment Production

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HLS-SEGMENT-IDENTITY-001 | [invariants/core/runtime/INV-HLS-SEGMENT-IDENTITY-001.md](invariants/core/runtime/INV-HLS-SEGMENT-IDENTITY-001.md) | LAW-CLOCK, LAW-DERIVATION |
| INV-HLS-SEGMENT-KEYFRAME-001 | [invariants/core/runtime/INV-HLS-SEGMENT-KEYFRAME-001.md](invariants/core/runtime/INV-HLS-SEGMENT-KEYFRAME-001.md) | LAW-DECODABILITY |
| INV-HLS-SEGMENT-IMMUTABLE-001 | [invariants/core/runtime/INV-HLS-SEGMENT-IMMUTABLE-001.md](invariants/core/runtime/INV-HLS-SEGMENT-IMMUTABLE-001.md) | LAW-IMMUTABILITY |
| INV-HLS-SEGMENT-WALLCLOCK-001 | [invariants/core/runtime/INV-HLS-SEGMENT-WALLCLOCK-001.md](invariants/core/runtime/INV-HLS-SEGMENT-WALLCLOCK-001.md) | LAW-CLOCK, LAW-DERIVATION |
| INV-HLS-SEGMENT-SELFCONTAINED-001 | [invariants/core/runtime/INV-HLS-SEGMENT-SELFCONTAINED-001.md](invariants/core/runtime/INV-HLS-SEGMENT-SELFCONTAINED-001.md) | LAW-DECODABILITY |
| INV-HLS-SEGMENT-PTS-CONTINUITY-001 | [invariants/core/runtime/INV-HLS-SEGMENT-PTS-CONTINUITY-001.md](invariants/core/runtime/INV-HLS-SEGMENT-PTS-CONTINUITY-001.md) | INV-HLS-SEGMENT-IDENTITY-001, INV-HLS-DISCONTINUITY-MARKER-001, LAW-DECODABILITY |
| INV-HLS-SEGMENT-INDEX-GUARD-001 | [invariants/core/runtime/INV-HLS-SEGMENT-INDEX-GUARD-001.md](invariants/core/runtime/INV-HLS-SEGMENT-INDEX-GUARD-001.md) | INV-HLS-SEGMENT-IDENTITY-001, LAW-CLOCK |
| INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001 | [invariants/core/runtime/INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001.md](invariants/core/runtime/INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001.md) | INV-HLS-SEGMENT-WALLCLOCK-001, LAW-CLOCK, LAW-DERIVATION |
| INV-HLS-SEGMENT-DURATION-BOUNDS-001 | [invariants/core/runtime/INV-HLS-SEGMENT-DURATION-BOUNDS-001.md](invariants/core/runtime/INV-HLS-SEGMENT-DURATION-BOUNDS-001.md) | INV-HLS-SEGMENT-KEYFRAME-001, LAW-DECODABILITY |

### Delivery — HLS Segment Ring

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HLS-RING-BOUNDED-001 | [invariants/core/runtime/INV-HLS-RING-BOUNDED-001.md](invariants/core/runtime/INV-HLS-RING-BOUNDED-001.md) | LAW-LIVENESS |
| INV-HLS-RING-OBSERVATION-001 | [invariants/core/runtime/INV-HLS-RING-OBSERVATION-001.md](invariants/core/runtime/INV-HLS-RING-OBSERVATION-001.md) | LAW-LIVENESS, LAW-IMMUTABILITY |
| INV-HLS-RING-WINDOW-VALID-001 | [invariants/core/runtime/INV-HLS-RING-WINDOW-VALID-001.md](invariants/core/runtime/INV-HLS-RING-WINDOW-VALID-001.md) | INV-HLS-RING-BOUNDED-001, INV-HLS-RING-OBSERVATION-001, LAW-LIVENESS |
| INV-HLS-RING-PUSH-ATOMIC-001 | [invariants/core/runtime/INV-HLS-RING-PUSH-ATOMIC-001.md](invariants/core/runtime/INV-HLS-RING-PUSH-ATOMIC-001.md) | INV-HLS-RING-OBSERVATION-001, LAW-LIVENESS |
| INV-HLS-RING-EVICTION-GRACE-001 | [invariants/core/runtime/INV-HLS-RING-EVICTION-GRACE-001.md](invariants/core/runtime/INV-HLS-RING-EVICTION-GRACE-001.md) | INV-HLS-MANIFEST-CHANNEL-SCOPED-001, INV-HLS-RING-BOUNDED-001, LAW-LIVENESS |

### Delivery — HLS Manifest Publication

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HLS-MANIFEST-LIVE-001 | [invariants/core/runtime/INV-HLS-MANIFEST-LIVE-001.md](invariants/core/runtime/INV-HLS-MANIFEST-LIVE-001.md) | LAW-LIVENESS |
| INV-HLS-MANIFEST-SEQUENCE-001 | [invariants/core/runtime/INV-HLS-MANIFEST-SEQUENCE-001.md](invariants/core/runtime/INV-HLS-MANIFEST-SEQUENCE-001.md) | LAW-CLOCK, LAW-DERIVATION |
| INV-HLS-MANIFEST-PDT-001 | [invariants/core/runtime/INV-HLS-MANIFEST-PDT-001.md](invariants/core/runtime/INV-HLS-MANIFEST-PDT-001.md) | LAW-CLOCK, LAW-DERIVATION |
| INV-HLS-MANIFEST-CHANNEL-SCOPED-001 | [invariants/core/runtime/INV-HLS-MANIFEST-CHANNEL-SCOPED-001.md](invariants/core/runtime/INV-HLS-MANIFEST-CHANNEL-SCOPED-001.md) | LAW-CLOCK, LAW-DERIVATION |
| INV-HLS-MANIFEST-VALID-PLAYLIST-001 | [invariants/core/runtime/INV-HLS-MANIFEST-VALID-PLAYLIST-001.md](invariants/core/runtime/INV-HLS-MANIFEST-VALID-PLAYLIST-001.md) | INV-HLS-MANIFEST-LIVE-001, INV-HLS-MANIFEST-SEQUENCE-001, LAW-DECODABILITY |
| INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 | [invariants/core/runtime/INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001.md](invariants/core/runtime/INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001.md) | INV-HLS-MANIFEST-SEQUENCE-001, LAW-CLOCK |
| INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 | [invariants/core/runtime/INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001.md](invariants/core/runtime/INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001.md) | INV-HLS-MANIFEST-PDT-001, INV-HLS-SEGMENT-WALLCLOCK-001, LAW-CLOCK |
| INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 | [invariants/core/runtime/INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001.md](invariants/core/runtime/INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001.md) | INV-HLS-MANIFEST-CHANNEL-SCOPED-001, INV-HLS-RING-OBSERVATION-001, LAW-LIVENESS |

### Delivery — HLS Viewer Presence

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HLS-VIEWER-PRESENCE-001 | [invariants/core/runtime/INV-HLS-VIEWER-PRESENCE-001.md](invariants/core/runtime/INV-HLS-VIEWER-PRESENCE-001.md) | LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-HLS-VIEWER-COUNT-ACCURATE-001 | [invariants/core/runtime/INV-HLS-VIEWER-COUNT-ACCURATE-001.md](invariants/core/runtime/INV-HLS-VIEWER-COUNT-ACCURATE-001.md) | INV-HLS-VIEWER-PRESENCE-001, LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-HLS-SESSION-REAP-BOUNDED-001 | [invariants/core/runtime/INV-HLS-SESSION-REAP-BOUNDED-001.md](invariants/core/runtime/INV-HLS-SESSION-REAP-BOUNDED-001.md) | INV-HLS-VIEWER-PRESENCE-001, LAW-LIVENESS |
| INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 | [invariants/core/runtime/INV-HLS-SESSION-FIRST-VIEWER-ONCE-001.md](invariants/core/runtime/INV-HLS-SESSION-FIRST-VIEWER-ONCE-001.md) | INV-HLS-VIEWER-PRESENCE-001, INV-HLS-LIFECYCLE-SEGMENT-READY-001, LAW-LIVENESS |

### Delivery — HLS Channel Lifecycle

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HLS-LIFECYCLE-SEGMENT-READY-001 | [invariants/core/runtime/INV-HLS-LIFECYCLE-SEGMENT-READY-001.md](invariants/core/runtime/INV-HLS-LIFECYCLE-SEGMENT-READY-001.md) | LAW-LIVENESS |
| INV-HLS-PRODUCER-SEGMENT-FLOW-001 | [invariants/core/runtime/INV-HLS-PRODUCER-SEGMENT-FLOW-001.md](invariants/core/runtime/INV-HLS-PRODUCER-SEGMENT-FLOW-001.md) | INV-HLS-LIFECYCLE-SEGMENT-READY-001, INV-CHANNEL-LIVENESS-RECOVERY-001, LAW-LIVENESS |
| INV-HLS-NO-ORPHAN-PRODUCER-001 | [invariants/core/runtime/INV-HLS-NO-ORPHAN-PRODUCER-001.md](invariants/core/runtime/INV-HLS-NO-ORPHAN-PRODUCER-001.md) | INV-HLS-VIEWER-PRESENCE-001, INV-HLS-ENDPOINT-COEXIST-001, LAW-LIVENESS |
| INV-HLS-RESTART-DISCONTINUITY-001 | [invariants/core/runtime/INV-HLS-RESTART-DISCONTINUITY-001.md](invariants/core/runtime/INV-HLS-RESTART-DISCONTINUITY-001.md) | INV-HLS-SEGMENT-PTS-CONTINUITY-001, INV-HLS-SEGMENT-IDENTITY-001, INV-HLS-DISCONTINUITY-MARKER-001, LAW-DECODABILITY |
| INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001 | [invariants/core/runtime/INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001.md](invariants/core/runtime/INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001.md) | LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001 | [invariants/core/runtime/INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001.md](invariants/core/runtime/INV-HLS-PHANTOM-DRAIN-KEEPS-CHANNEL-ALIVE-001.md) | INV-HLS-FIRST-VIEWER-ACTIVATES-CHANNEL-001, LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001 | [invariants/core/runtime/INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001.md](invariants/core/runtime/INV-AIR-SOCKET-BUFFER-STARTUP-HEADROOM-001.md) | LAW-LIVENESS |
| INV-AIR-SESSION-CLEANUP-ON-END-001 | [invariants/core/runtime/INV-AIR-SESSION-CLEANUP-ON-END-001.md](invariants/core/runtime/INV-AIR-SESSION-CLEANUP-ON-END-001.md) | LAW-LIVENESS |
| INV-HLS-RING-STALENESS-RECOVERY-001 | [invariants/core/runtime/INV-HLS-RING-STALENESS-RECOVERY-001.md](invariants/core/runtime/INV-HLS-RING-STALENESS-RECOVERY-001.md) | INV-HLS-LIFECYCLE-SEGMENT-READY-001, INV-HLS-PRODUCER-SEGMENT-FLOW-001, LAW-LIVENESS |
| INV-HLS-READINESS-001 | [invariants/core/runtime/INV-HLS-READINESS-001.md](invariants/core/runtime/INV-HLS-READINESS-001.md) | INV-HLS-COLD-START-CONNECT-GUARANTEED-001, INV-HLS-LIFECYCLE-SEGMENT-READY-001, LAW-LIVENESS |

### Delivery — HLS Endpoint Coexistence

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HLS-ENDPOINT-COEXIST-001 | [invariants/core/runtime/INV-HLS-ENDPOINT-COEXIST-001.md](invariants/core/runtime/INV-HLS-ENDPOINT-COEXIST-001.md) | LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-HLS-SERVE-BYTE-IDENTITY-001 | [invariants/core/runtime/INV-HLS-SERVE-BYTE-IDENTITY-001.md](invariants/core/runtime/INV-HLS-SERVE-BYTE-IDENTITY-001.md) | INV-HLS-SEGMENT-IMMUTABLE-001, INV-HLS-ENDPOINT-COEXIST-001, LAW-IMMUTABILITY |
| INV-HLS-MANIFEST-DETERMINISTIC-001 | [invariants/core/runtime/INV-HLS-MANIFEST-DETERMINISTIC-001.md](invariants/core/runtime/INV-HLS-MANIFEST-DETERMINISTIC-001.md) | INV-HLS-MANIFEST-CHANNEL-SCOPED-001, LAW-CLOCK, LAW-DERIVATION |
| INV-HLS-ENDPOINT-SESSION-TOUCH-001 | [invariants/core/runtime/INV-HLS-ENDPOINT-SESSION-TOUCH-001.md](invariants/core/runtime/INV-HLS-ENDPOINT-SESSION-TOUCH-001.md) | INV-HLS-VIEWER-PRESENCE-001, INV-HLS-PHANTOM-CLEANUP-001, LAW-LIVENESS |

Canonical contract: [delivery_hls.md](delivery_hls.md)

### Playout — ScheduledBlock Pipeline

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-PLAYLIST-TIMELINE-CONTINUITY-001 | [invariants/core/playout/INV-PLAYLIST-TIMELINE-CONTINUITY-001.md](invariants/core/playout/INV-PLAYLIST-TIMELINE-CONTINUITY-001.md) | LAW-TIMELINE |
| INV-PLAYLIST-SEMANTIC-SPLIT-002 | [invariants/core/playout/INV-PLAYLIST-SEMANTIC-SPLIT-002.md](invariants/core/playout/INV-PLAYLIST-SEMANTIC-SPLIT-002.md) | LAW-DERIVATION |
| INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002 | [invariants/core/playout/INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002.md](invariants/core/playout/INV-PLAYLIST-EVENT-SEGMENT-COVERAGE-002.md) | LAW-TIMELINE |
| INV-PLAYLIST-EVENT-SEGMENT-ORDER-003 | [invariants/core/playout/INV-PLAYLIST-EVENT-SEGMENT-ORDER-003.md](invariants/core/playout/INV-PLAYLIST-EVENT-SEGMENT-ORDER-003.md) | LAW-DERIVATION |
| INV-PLAYLIST-DURATION-COVERAGE-004 | [invariants/core/playout/INV-PLAYLIST-DURATION-COVERAGE-004.md](invariants/core/playout/INV-PLAYLIST-DURATION-COVERAGE-004.md) | LAW-GRID, LAW-TIMELINE |
| INV-PLAYLIST-EVENT-SINGLE-PARENT-004 | [invariants/core/playout/INV-PLAYLIST-EVENT-SINGLE-PARENT-004.md](invariants/core/playout/INV-PLAYLIST-EVENT-SINGLE-PARENT-004.md) | LAW-DERIVATION |
| INV-PLAYLIST-CONTENT-IDENTITY-005 | [invariants/core/playout/INV-PLAYLIST-CONTENT-IDENTITY-005.md](invariants/core/playout/INV-PLAYLIST-CONTENT-IDENTITY-005.md) | LAW-CONTENT-AUTHORITY |
| INV-PLAYLIST-TIME-ANCHOR-006 | [invariants/core/playout/INV-PLAYLIST-TIME-ANCHOR-006.md](invariants/core/playout/INV-PLAYLIST-TIME-ANCHOR-006.md) | LAW-CLOCK |
| INV-PLAYLIST-HORIZON-DETERMINISM-007 | [invariants/core/playout/INV-PLAYLIST-HORIZON-DETERMINISM-007.md](invariants/core/playout/INV-PLAYLIST-HORIZON-DETERMINISM-007.md) | LAW-DERIVATION |
| INV-PLAYLIST-CONTENT-OFFSET-003 | [invariants/core/playout/INV-PLAYLIST-CONTENT-OFFSET-003.md](invariants/core/playout/INV-PLAYLIST-CONTENT-OFFSET-003.md) | LAW-TIMELINE |
| INV-PLAYLIST-EVENT-TIMELINE-001 | [invariants/core/playout/INV-PLAYLIST-EVENT-TIMELINE-001.md](invariants/core/playout/INV-PLAYLIST-EVENT-TIMELINE-001.md) | LAW-TIMELINE |
| INV-BLOCK-SEGMENT-CONSERVATION-001 | [invariants/core/playout/INV-BLOCK-SEGMENT-CONSERVATION-001.md](invariants/core/playout/INV-BLOCK-SEGMENT-CONSERVATION-001.md) | LAW-GRID, LAW-TIMELINE |
| INV-DAEMON-FRONTIER-ACTUAL-001 | [invariants/core/playout/INV-DAEMON-FRONTIER-ACTUAL-001.md](invariants/core/playout/INV-DAEMON-FRONTIER-ACTUAL-001.md) | LAW-TIMELINE |

---

## AIR

| Invariant | File | Classification |
|-----------|------|----------------|
| INV-BACKPRESSURE-SYMMETRIC | [invariants/air/INV-BACKPRESSURE-SYMMETRIC.md](invariants/air/INV-BACKPRESSURE-SYMMETRIC.md) | Primary |
| INV-PACING-SINGLE-AUTHORITY-001 | [invariants/air/INV-PACING-SINGLE-AUTHORITY-001.md](invariants/air/INV-PACING-SINGLE-AUTHORITY-001.md) | Primary — derives LAW-CLOCK, LAW-RUNTIME-AUTHORITY |
| INV-BOOTSTRAP-AV-PHASE-001 | [invariants/air/INV-BOOTSTRAP-AV-PHASE-001.md](invariants/air/INV-BOOTSTRAP-AV-PHASE-001.md) | Primary — derives LAW-CLOCK, LAW-LIVENESS |
| INV-FILL-AV-LEAD-CLAMP-001 | [invariants/air/INV-FILL-AV-LEAD-CLAMP-001.md](invariants/air/INV-FILL-AV-LEAD-CLAMP-001.md) | Primary — derives LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-BUFFER-EQUILIBRIUM | [invariants/air/INV-BUFFER-EQUILIBRIUM.md](invariants/air/INV-BUFFER-EQUILIBRIUM.md) | Primary |
| INV-DECODE-GATE | [invariants/air/INV-DECODE-GATE.md](invariants/air/INV-DECODE-GATE.md) | Primary |
| INV-NO-SILENCE-INJECTION | [invariants/air/INV-NO-SILENCE-INJECTION.md](invariants/air/INV-NO-SILENCE-INJECTION.md) | Primary |
| INV-PAD-PRODUCER | [invariants/air/INV-PAD-PRODUCER.md](invariants/air/INV-PAD-PRODUCER.md) | Primary |
| INV-PRODUCER-THROTTLE | [invariants/air/INV-PRODUCER-THROTTLE.md](invariants/air/INV-PRODUCER-THROTTLE.md) | Primary |
| INV-CONTINUOUS-FRAME-AUTHORITY-001 | [invariants/air/INV-CONTINUOUS-FRAME-AUTHORITY-001.md](invariants/air/INV-CONTINUOUS-FRAME-AUTHORITY-001.md) | Primary |
| INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 | [invariants/air/INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001.md](invariants/air/INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001.md) | Primary |
| INV-NO-FRAME-AUTHORITY-VACUUM-001 | [invariants/air/INV-NO-FRAME-AUTHORITY-VACUUM-001.md](invariants/air/INV-NO-FRAME-AUTHORITY-VACUUM-001.md) | Enforcement evidence (derived) — parent: INV-CONTINUOUS-FRAME-AUTHORITY-001 |
| INV-PAD-VIDEO-READINESS-001 | [invariants/air/INV-PAD-VIDEO-READINESS-001.md](invariants/air/INV-PAD-VIDEO-READINESS-001.md) | Enforcement evidence (derived) — parents: INV-CONTINUOUS-FRAME-AUTHORITY-001, INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 |
| INV-LAST-SEGMENT-BLOCK-BOUNDARY-001 | [invariants/air/INV-LAST-SEGMENT-BLOCK-BOUNDARY-001.md](invariants/air/INV-LAST-SEGMENT-BLOCK-BOUNDARY-001.md) | Primary — ADR-013 seam classification upstream |
| INV-CADENCE-SEAM-ADVANCE-001 | [invariants/air/INV-CADENCE-SEAM-ADVANCE-001.md](invariants/air/INV-CADENCE-SEAM-ADVANCE-001.md) | Derived — parent: INV-AUTHORITY-ATOMIC-FRAME-TRANSFER-001 |
| INV-SEAM-SEGMENT-PREFILL-001 | [invariants/air/INV-SEAM-SEGMENT-PREFILL-001.md](invariants/air/INV-SEAM-SEGMENT-PREFILL-001.md) | Primary — derives from INV-SEAM-006, INV-SEAM-SEG-003 |
| INV-SEAM-SWAP-READINESS-001 | [invariants/air/INV-SEAM-SWAP-READINESS-001.md](invariants/air/INV-SEAM-SWAP-READINESS-001.md) | Primary — derives from INV-SEAM-002, INV-VIDEO-LOOKAHEAD-001 |
| INV-TIME-MODE-EQUIVALENCE-001 | [invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md](invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md) | Primary |
| INV-VFR-DROP-GUARD-001 | [invariants/air/INV-VFR-DROP-GUARD-001.md](invariants/air/INV-VFR-DROP-GUARD-001.md) | Primary — derives from INV-FPS-RESAMPLE, LAW-LIVENESS |
| INV-CADENCE-SOURCE-SYNC-001 | [CadenceSourceSyncContract.md](../../runtime/docs/contracts/semantics/CadenceSourceSyncContract.md) | Semantic — cadence must reflect live source FPS at all output ticks |
| INV-CADENCE-SOURCE-SYNC-002 | [CadenceSourceSyncContract.md](../../runtime/docs/contracts/semantics/CadenceSourceSyncContract.md) | Semantic — producer transition must reinitialize cadence (all paths) |
| INV-CADENCE-SOURCE-SYNC-003 | [CadenceSourceSyncContract.md](../../runtime/docs/contracts/semantics/CadenceSourceSyncContract.md) | Semantic — segment swap must refresh cadence |
| INV-CADENCE-SOURCE-SYNC-004 | [CadenceSourceSyncContract.md](../../runtime/docs/contracts/semantics/CadenceSourceSyncContract.md) | Semantic — stale cadence causes observable speed error (always a defect) |
| INV-SEAM-BOUNDARY-COUNT-MATCH-001 | [invariants/air/INV-SEAM-BOUNDARY-COUNT-MATCH-001.md](invariants/air/INV-SEAM-BOUNDARY-COUNT-MATCH-001.md) | Primary — boundary count must match segment count at block activation |
| INV-PRODUCER-DEMAND-DRIVEN-001 | [invariants/air/INV-PRODUCER-DEMAND-DRIVEN-001.md](invariants/air/INV-PRODUCER-DEMAND-DRIVEN-001.md) | Primary — decode must not advance without tick consumption |
| INV-SEAM-CONTINUITY-GUARANTEED-001 | [invariants/air/INV-SEAM-CONTINUITY-GUARANTEED-001.md](invariants/air/INV-SEAM-CONTINUITY-GUARANTEED-001.md) | Primary — scheduled segment transitions must succeed with valid A/V |
| INV-SEAM-ELIGIBILITY-BOUNDED-BY-SEGMENT-001 | [invariants/air/INV-SEAM-ELIGIBILITY-BOUNDED-BY-SEGMENT-001.md](invariants/air/INV-SEAM-ELIGIBILITY-BOUNDED-BY-SEGMENT-001.md) | Derived — eligibility threshold capped by segment capacity |
| INV-SEAM-TAKEOVER-COMMITMENT-001 | [invariants/air/INV-SEAM-TAKEOVER-COMMITMENT-001.md](invariants/air/INV-SEAM-TAKEOVER-COMMITMENT-001.md) | Primary — post-swap commit, no re-evaluation of eligibility |
| INV-SEAM-PREP-DEADLINE-SAFE-001 | [invariants/air/INV-SEAM-PREP-DEADLINE-SAFE-001.md](invariants/air/INV-SEAM-PREP-DEADLINE-SAFE-001.md) | Derived — async prep must complete before seam consumption |
| INV-AIR-PRODUCER-INTERFACE-001 | [air/PRODUCER_INTERFACE.md](air/PRODUCER_INTERFACE.md) | Primary — PipelineManager must not downcast factory-produced producers |
| INV-AIR-PRODUCER-PRIME-001 | [air/PRODUCER_INTERFACE.md](air/PRODUCER_INTERFACE.md) | Primary — PrimeFirstTick must be on ITickProducer interface |
| INV-AIR-PRODUCER-ASPECT-001 | [air/PRODUCER_INTERFACE.md](air/PRODUCER_INTERFACE.md) | Primary — SetAspectPolicy must be on ITickProducer interface |
| INV-AIR-DECODE-RESULT-EXPLICIT-001 | [air/DECODE_RESULT_MODEL.md](air/DECODE_RESULT_MODEL.md) | Primary — TryGetFrame returns explicit DecodeResult |
| INV-AIR-EOF-NON-REPEATABLE-001 | [air/DECODE_RESULT_MODEL.md](air/DECODE_RESULT_MODEL.md) | Primary — kEof must produce pad, not repeat |
| INV-AIR-UNDERRUN-REPEATABLE-001 | [air/DECODE_RESULT_MODEL.md](air/DECODE_RESULT_MODEL.md) | Primary — kUnderrun may hold last frame |
| INV-AIR-ERROR-FAILSAFE-001 | [air/DECODE_RESULT_MODEL.md](air/DECODE_RESULT_MODEL.md) | Primary — kError falls back to pad |
| INV-AIR-DECODE-RESULT-SCOPE-001 | [air/DECODE_RESULT_MODEL.md](air/DECODE_RESULT_MODEL.md) | Primary — DecodeStatus is per-call, stateless, no persistent EOF flag |
| INV-AIR-EOF-PAD-TRANSITION-001 | [air/EOF_PAD_TRANSITION.md](air/EOF_PAD_TRANSITION.md) | Primary — pad after decoder EOF, not repeat |
| INV-AIR-EOF-VS-UNDERRUN-001 | [air/EOF_PAD_TRANSITION.md](air/EOF_PAD_TRANSITION.md) | Primary — EOF and underrun are distinct conditions |
| INV-AIR-EOF-IMMEDIATE-001 | [air/EOF_PAD_TRANSITION.md](air/EOF_PAD_TRANSITION.md) | Primary — pad begins on first tick after EOF |
| INV-AIR-TAKE-PAD-CLASSIFICATION-EXPLICIT-001 | [air/TAKE_PAD_CLASSIFICATION.md](air/TAKE_PAD_CLASSIFICATION.md) | Primary — classification reflects frame source, not slot |
| INV-AIR-TAKE-DEAD-PRODUCER-IS-PAD-001 | [air/TAKE_PAD_CLASSIFICATION.md](air/TAKE_PAD_CLASSIFICATION.md) | Primary — dead producers must classify as pad |
| INV-AIR-TAKE-PAD-METRICS-CONSISTENT-001 | [air/TAKE_PAD_CLASSIFICATION.md](air/TAKE_PAD_CLASSIFICATION.md) | Primary — metric counter matches fingerprint is_pad |
| INV-READINESS-SINGLE-OWNER-001 | [invariants/air/INV-READINESS-SINGLE-OWNER-001.md](invariants/air/INV-READINESS-SINGLE-OWNER-001.md) | Primary — derives LAW-RUNTIME-AUTHORITY, LAW-LIVENESS |
| INV-READINESS-NOT-BYTE-INFERRED-001 | [invariants/air/INV-READINESS-NOT-BYTE-INFERRED-001.md](invariants/air/INV-READINESS-NOT-BYTE-INFERRED-001.md) | Derived — enforces INV-READINESS-SINGLE-OWNER-001 at the signal level; derives LAW-LIVENESS |
| INV-READINESS-OBSERVABLE-001 | [invariants/air/INV-READINESS-OBSERVABLE-001.md](invariants/air/INV-READINESS-OBSERVABLE-001.md) | Primary — derives LAW-LIVENESS |
| INV-READINESS-SCOPE-INDEPENDENCE-001 | [invariants/air/INV-READINESS-SCOPE-INDEPENDENCE-001.md](invariants/air/INV-READINESS-SCOPE-INDEPENDENCE-001.md) | Primary — derives LAW-RUNTIME-AUTHORITY, LAW-LIVENESS |
| INV-VERDICT-BOUNDED-STATES-001 | [invariants/air/INV-VERDICT-BOUNDED-STATES-001.md](invariants/air/INV-VERDICT-BOUNDED-STATES-001.md) | Primary — derives LAW-LIVENESS |
| INV-VERDICT-REASON-CLASS-BOUNDED-001 | [invariants/air/INV-VERDICT-REASON-CLASS-BOUNDED-001.md](invariants/air/INV-VERDICT-REASON-CLASS-BOUNDED-001.md) | Derived — enforces INV-VERDICT-BOUNDED-STATES-001 at the reason-class level; derives LAW-LIVENESS |
| INV-FATAL-UNDERFLOW-VISIBILITY-001 | [invariants/air/INV-FATAL-UNDERFLOW-VISIBILITY-001.md](invariants/air/INV-FATAL-UNDERFLOW-VISIBILITY-001.md) | Primary — derives LAW-LIVENESS |
| INV-SEAM-SINGLE-AUTHORITY-001 | [invariants/air/INV-SEAM-SINGLE-AUTHORITY-001.md](invariants/air/INV-SEAM-SINGLE-AUTHORITY-001.md) | Primary — derives LAW-SWITCHING, LAW-LIVENESS |
| INV-SEAM-SINGLE-EXECUTION-001 | [invariants/air/INV-SEAM-SINGLE-EXECUTION-001.md](invariants/air/INV-SEAM-SINGLE-EXECUTION-001.md) | Primary — derives LAW-SWITCHING, INV-SEAM-BOUNDARY-COUNT-MATCH-001 |
| INV-SEAM-MISSED-RESOLUTION-001 | [invariants/air/INV-SEAM-MISSED-RESOLUTION-001.md](invariants/air/INV-SEAM-MISSED-RESOLUTION-001.md) | Derived — enforces INV-CONTINUOUS-FRAME-AUTHORITY-001 at missed-seam disposition; derives LAW-LIVENESS |
| INV-SEAM-EDITORIAL-EXTERNAL-001 | [invariants/air/INV-SEAM-EDITORIAL-EXTERNAL-001.md](invariants/air/INV-SEAM-EDITORIAL-EXTERNAL-001.md) | Primary — derives LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-SEAM-OBSERVABLE-001 | [invariants/air/INV-SEAM-OBSERVABLE-001.md](invariants/air/INV-SEAM-OBSERVABLE-001.md) | Primary — derives LAW-LIVENESS |
| INV-BOOTSTRAP-CONTINUITY-001 | [invariants/air/INV-BOOTSTRAP-CONTINUITY-001.md](invariants/air/INV-BOOTSTRAP-CONTINUITY-001.md) | Primary — derives LAW-LIVENESS |
| INV-BOOTSTRAP-CONTENT-PARKED-001 | [invariants/air/INV-BOOTSTRAP-CONTENT-PARKED-001.md](invariants/air/INV-BOOTSTRAP-CONTENT-PARKED-001.md) | Primary — derives LAW-LIVENESS, LAW-SWITCHING |
| INV-BOOTSTRAP-CONTENT-ORIGIN-001 | [invariants/air/INV-BOOTSTRAP-CONTENT-ORIGIN-001.md](invariants/air/INV-BOOTSTRAP-CONTENT-ORIGIN-001.md) | Primary — derives LAW-CLOCK, LAW-LIVENESS |
| INV-BOOTSTRAP-KICKOFF-ATOMIC-001 | [invariants/air/INV-BOOTSTRAP-KICKOFF-ATOMIC-001.md](invariants/air/INV-BOOTSTRAP-KICKOFF-ATOMIC-001.md) | Primary — derives LAW-SWITCHING, LAW-LIVENESS |
| INV-BOOTSTRAP-PTS-CONTINUOUS-001 | [invariants/air/INV-BOOTSTRAP-PTS-CONTINUOUS-001.md](invariants/air/INV-BOOTSTRAP-PTS-CONTINUOUS-001.md) | Primary — derives LAW-CLOCK, LAW-LIVENESS |

---

## Sink

| Invariant | File |
|-----------|------|
| INV-PCR-PACED-MUX | [invariants/sink/INV-PCR-PACED-MUX.md](invariants/sink/INV-PCR-PACED-MUX.md) |
| INV-SINK-NO-DEADLOCK | [invariants/sink/INV-SINK-NO-DEADLOCK.md](invariants/sink/INV-SINK-NO-DEADLOCK.md) |
| INV-TS-EMISSION-LIVENESS | [invariants/sink/INV-TS-EMISSION-LIVENESS.md](invariants/sink/INV-TS-EMISSION-LIVENESS.md) |

---

## Shared

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-AUDIO-CONTINUITY-NO-DROP | [invariants/shared/INV-AUDIO-CONTINUITY-NO-DROP.md](invariants/shared/INV-AUDIO-CONTINUITY-NO-DROP.md) | LAW-LIVENESS |
| INV-CONTENT-DEFICIT-FILL | [invariants/shared/INV-CONTENT-DEFICIT-FILL.md](invariants/shared/INV-CONTENT-DEFICIT-FILL.md) | LAW-LIVENESS |
| INV-CONTROL-PLANE-CADENCE | [invariants/shared/INV-CONTROL-PLANE-CADENCE.md](invariants/shared/INV-CONTROL-PLANE-CADENCE.md) | LAW-LIVENESS |
| INV-LOUDNESS-NORMALIZED-001 | [invariants/shared/INV-LOUDNESS-NORMALIZED-001.md](invariants/shared/INV-LOUDNESS-NORMALIZED-001.md) | LAW-LIVENESS |
| INV-TIME-AUTHORITY-SINGLE-SOURCE | [invariants/shared/INV-TIME-AUTHORITY-SINGLE-SOURCE.md](invariants/shared/INV-TIME-AUTHORITY-SINGLE-SOURCE.md) | LAW-CLOCK |
| INV-GRPC-DEADLINE-POLICY-001 | [invariants/shared/INV-GRPC-DEADLINE-POLICY-001.md](invariants/shared/INV-GRPC-DEADLINE-POLICY-001.md) | LAW-LIVENESS, LAW-CLOCK |
| INV-GRPC-FEED-BACKPRESSURE-001 | [invariants/shared/INV-GRPC-FEED-BACKPRESSURE-001.md](invariants/shared/INV-GRPC-FEED-BACKPRESSURE-001.md) | LAW-LIVENESS |
| INV-GRPC-GRACEFUL-DRAIN-001 | [invariants/shared/INV-GRPC-GRACEFUL-DRAIN-001.md](invariants/shared/INV-GRPC-GRACEFUL-DRAIN-001.md) | LAW-LIVENESS, LAW-CLOCK |
| INV-GRPC-HEALTH-CHECK-001 | [invariants/shared/INV-GRPC-HEALTH-CHECK-001.md](invariants/shared/INV-GRPC-HEALTH-CHECK-001.md) | LAW-LIVENESS |

---

## Plex Integration (HDHomeRun Virtual Tuner)

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-PLEX-DISCOVERY-001 | [plex/INV-PLEX-DISCOVERY-001.md](plex/INV-PLEX-DISCOVERY-001.md) | LAW-CONTENT-AUTHORITY |
| INV-PLEX-LINEUP-001 | [plex/INV-PLEX-LINEUP-001.md](plex/INV-PLEX-LINEUP-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PLEX-TUNER-STATUS-001 | [plex/INV-PLEX-TUNER-STATUS-001.md](plex/INV-PLEX-TUNER-STATUS-001.md) | LAW-LIVENESS |
| INV-PLEX-XMLTV-001 | [plex/INV-PLEX-XMLTV-001.md](plex/INV-PLEX-XMLTV-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |
| INV-PLEX-STREAM-START-001 | [plex/INV-PLEX-STREAM-START-001.md](plex/INV-PLEX-STREAM-START-001.md) | LAW-RUNTIME-AUTHORITY, LAW-LIVENESS |
| INV-PLEX-STREAM-DISCONNECT-001 | [plex/INV-PLEX-STREAM-DISCONNECT-001.md](plex/INV-PLEX-STREAM-DISCONNECT-001.md) | LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-PLEX-FANOUT-001 | [plex/INV-PLEX-FANOUT-001.md](plex/INV-PLEX-FANOUT-001.md) | LAW-LIVENESS, LAW-RUNTIME-AUTHORITY |
| INV-PLEX-ARTWORK-001 | [plex/INV-PLEX-ARTWORK-001.md](plex/INV-PLEX-ARTWORK-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

---

## Governance Pass Notes (2025-07-14)

The following invariants lack test matrix entries and are flagged for follow-up:

| Invariant | Gap |
|-----------|-----|
| INV-CADENCE-SOURCE-SYNC-001–004 | No test matrix entry; see TEST_ANCHOR_BACKLOG.md §P3 |
| INV-SEAM-BOUNDARY-COUNT-MATCH-001 | No test matrix entry |
| INV-PRODUCER-DEMAND-DRIVEN-001 | No test matrix entry |
| INV-SEAM-CONTINUITY-GUARANTEED-001 | No test matrix entry |
| INV-SEAM-TAKEOVER-COMMITMENT-001 | No test matrix entry |
| INV-TIME-MODE-EQUIVALENCE-001 | No test matrix entry |
| INV-PCR-PACED-MUX | Sink invariant; no test matrix |
| INV-SINK-NO-DEADLOCK | Sink invariant; no test matrix |
| INV-TS-EMISSION-LIVENESS | Sink invariant; no test matrix |
| INV-AUDIO-CONTINUITY-NO-DROP | Shared invariant; no test matrix |
| INV-CONTENT-DEFICIT-FILL | Shared invariant; no test matrix |
| INV-LOUDNESS-NORMALIZED-001 | Shared invariant; no test matrix |
| INV-TIME-AUTHORITY-SINGLE-SOURCE | Shared; overlaps LAW-CLOCK; no test mapping |
| INV-SWITCH-BOUNDARY-TIMING | No Derived From law cited; enforcement unclear |
| INV-PACING-001, INV-PACING-ENFORCEMENT-002, INV-DECODE-RATE-001, INV-SEGMENT-CONTENT-001 | **INV-PACING-001 (single authority slice)** superseded by indexed **INV-PACING-SINGLE-AUTHORITY-001**; remainder still doc-only / P4 backlog |
| INV-READINESS-SINGLE-OWNER-001 | AIR readiness invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp` (file to be created; RED contract test is the next turn in the ReadinessController extraction path) |
| INV-READINESS-NOT-BYTE-INFERRED-001 | AIR readiness invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp` (file to be created) |
| INV-READINESS-OBSERVABLE-001 | AIR readiness invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp` (file to be created) |
| INV-READINESS-SCOPE-INDEPENDENCE-001 | AIR readiness invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp` (file to be created) |
| INV-VERDICT-BOUNDED-STATES-001 | AIR readiness invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp` (file to be created) |
| INV-VERDICT-REASON-CLASS-BOUNDED-001 | AIR readiness invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/readiness/ReadinessInvariantTests.cpp` (file to be created) |
| INV-FATAL-UNDERFLOW-VISIBILITY-001 | AIR observability invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/readiness/FatalUnderflowVisibilityTests.cpp` (file to be created); code implementation also pending — AIR currently detects underflow via counter increments (`VideoLookaheadBuffer::UnderflowCount()`, `AudioLookaheadBuffer::UnderflowCount()`) without structured event emission |
| INV-SEAM-SINGLE-AUTHORITY-001 | AIR seam authority invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp` (file to be created; RED contract test is Turn B of the SeamController extraction path per ADR-006 step 2) |
| INV-SEAM-SINGLE-EXECUTION-001 | AIR seam authority invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp` (file to be created) |
| INV-SEAM-MISSED-RESOLUTION-001 | AIR seam authority invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp` (file to be created) |
| INV-SEAM-EDITORIAL-EXTERNAL-001 | AIR seam authority invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp` (file to be created) |
| INV-SEAM-OBSERVABLE-001 | AIR seam authority invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/seam/SeamAuthorityInvariantTests.cpp` (file to be created) |
| INV-BOOTSTRAP-CONTINUITY-001 | AIR bootstrap content-gate invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp` (file to be created; RED contract test is Turn B of the bootstrap content-gate path) |
| INV-BOOTSTRAP-CONTENT-PARKED-001 | AIR bootstrap content-gate invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp` (file to be created) |
| INV-BOOTSTRAP-CONTENT-ORIGIN-001 | AIR bootstrap content-gate invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp` (file to be created) |
| INV-BOOTSTRAP-KICKOFF-ATOMIC-001 | AIR bootstrap content-gate invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp` (file to be created) |
| INV-BOOTSTRAP-PTS-CONTINUOUS-001 | AIR bootstrap content-gate invariant; no test matrix entry; Required Tests cite `runtime/tests/contracts/bootstrap/BootstrapContentGateInvariantTests.cpp` (file to be created) |

See [audit/TEST_ANCHOR_BACKLOG.md](audit/TEST_ANCHOR_BACKLOG.md) for prioritized action.

**LAW-RUNTIME-AUDIO-AUTHORITY** is listed as an Air law but does not appear in `docs/contracts/laws/` alongside the other 11 laws. It resides in `runtime/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md`. Its downstream INV-* entries are not indexed here. TODO: add index entry and law file, or document as intentionally Air-domain-only.

**Migrated in this pass:**
- AIR-012, AIR-015 → `runtime/docs/contracts/coordination/OutputBusAndOutputSinkContract.md` §11–12
- AIR-016 → `runtime/docs/contracts/coordination/OrchestrationLoopContract.md`
- CORE-002, CORE-003 → `server/docs/contracts/resources/ChannelManagerContract.md`
