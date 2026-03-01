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
| LAW-CONTENT-AUTHORITY | [laws/LAW-CONTENT-AUTHORITY.md](laws/LAW-CONTENT-AUTHORITY.md) | Scheduling — SchedulePlan is sole editorial authority |
| LAW-DERIVATION | [laws/LAW-DERIVATION.md](laws/LAW-DERIVATION.md) | Scheduling — artifact chain traceability |
| LAW-RUNTIME-AUTHORITY | [laws/LAW-RUNTIME-AUTHORITY.md](laws/LAW-RUNTIME-AUTHORITY.md) | Scheduling — ExecutionEntry is sole runtime authority |
| LAW-IMMUTABILITY | [laws/LAW-IMMUTABILITY.md](laws/LAW-IMMUTABILITY.md) | Scheduling — published artifacts are immutable |

---

## Core

### Scheduling — SchedulePlan

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-PLAN-FULL-COVERAGE-001 | [invariants/core/schedule-plan/INV-PLAN-FULL-COVERAGE-001.md](invariants/core/schedule-plan/INV-PLAN-FULL-COVERAGE-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-PLAN-NO-ZONE-OVERLAP-001 | [invariants/core/schedule-plan/INV-PLAN-NO-ZONE-OVERLAP-001.md](invariants/core/schedule-plan/INV-PLAN-NO-ZONE-OVERLAP-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-PLAN-GRID-ALIGNMENT-001 | [invariants/core/schedule-plan/INV-PLAN-GRID-ALIGNMENT-001.md](invariants/core/schedule-plan/INV-PLAN-GRID-ALIGNMENT-001.md) | LAW-GRID |
| INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 | [invariants/core/schedule-plan/INV-PLAN-ELIGIBLE-ASSETS-ONLY-001.md](invariants/core/schedule-plan/INV-PLAN-ELIGIBLE-ASSETS-ONLY-001.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |

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

### Asset — Entity Integrity

| Invariant | File | Derived From |
|-----------|------|--------------|
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

### Asset — Metadata Integrity

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 | [invariants/core/asset/INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001.md](invariants/core/asset/INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001.md) | LAW-DERIVATION |
| INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001 | [invariants/core/asset/INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001.md](invariants/core/asset/INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |
| INV-ASSET-MARKER-BOUNDS-001 | [invariants/core/asset/INV-ASSET-MARKER-BOUNDS-001.md](invariants/core/asset/INV-ASSET-MARKER-BOUNDS-001.md) | — |

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

---

## AIR

| Invariant | File | Classification |
|-----------|------|----------------|
| INV-BACKPRESSURE-SYMMETRIC | [invariants/air/INV-BACKPRESSURE-SYMMETRIC.md](invariants/air/INV-BACKPRESSURE-SYMMETRIC.md) | Primary |
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
| INV-TIME-MODE-EQUIVALENCE-001 | [invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md](invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md) | Primary |

---

## Sink

| Invariant | File |
|-----------|------|
| INV-PCR-PACED-MUX | [invariants/sink/INV-PCR-PACED-MUX.md](invariants/sink/INV-PCR-PACED-MUX.md) |
| INV-SINK-NO-DEADLOCK | [invariants/sink/INV-SINK-NO-DEADLOCK.md](invariants/sink/INV-SINK-NO-DEADLOCK.md) |
| INV-TS-EMISSION-LIVENESS | [invariants/sink/INV-TS-EMISSION-LIVENESS.md](invariants/sink/INV-TS-EMISSION-LIVENESS.md) |

---

## Shared

| Invariant | File |
|-----------|------|
| INV-AUDIO-CONTINUITY-NO-DROP | [invariants/shared/INV-AUDIO-CONTINUITY-NO-DROP.md](invariants/shared/INV-AUDIO-CONTINUITY-NO-DROP.md) |
| INV-CONTENT-DEFICIT-FILL | [invariants/shared/INV-CONTENT-DEFICIT-FILL.md](invariants/shared/INV-CONTENT-DEFICIT-FILL.md) |
| INV-CONTROL-PLANE-CADENCE | [invariants/shared/INV-CONTROL-PLANE-CADENCE.md](invariants/shared/INV-CONTROL-PLANE-CADENCE.md) |
| INV-TIME-AUTHORITY-SINGLE-SOURCE | [invariants/shared/INV-TIME-AUTHORITY-SINGLE-SOURCE.md](invariants/shared/INV-TIME-AUTHORITY-SINGLE-SOURCE.md) |
