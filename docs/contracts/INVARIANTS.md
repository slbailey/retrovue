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
| LAW-RUNTIME-AUTHORITY | [laws/LAW-RUNTIME-AUTHORITY.md](laws/LAW-RUNTIME-AUTHORITY.md) | Scheduling — PlaylogEvent is sole runtime authority |
| LAW-IMMUTABILITY | [laws/LAW-IMMUTABILITY.md](laws/LAW-IMMUTABILITY.md) | Scheduling — published artifacts are immutable |

---

## Core

### Scheduling — SchedulePlan

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-PLAN-FULL-COVERAGE-001 | [invariants/core/INV-PLAN-FULL-COVERAGE-001.md](invariants/core/INV-PLAN-FULL-COVERAGE-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-PLAN-NO-ZONE-OVERLAP-001 | [invariants/core/INV-PLAN-NO-ZONE-OVERLAP-001.md](invariants/core/INV-PLAN-NO-ZONE-OVERLAP-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID |
| INV-PLAN-GRID-ALIGNMENT-001 | [invariants/core/INV-PLAN-GRID-ALIGNMENT-001.md](invariants/core/INV-PLAN-GRID-ALIGNMENT-001.md) | LAW-GRID |
| INV-PLAN-ELIGIBLE-ASSETS-ONLY-001 | [invariants/core/INV-PLAN-ELIGIBLE-ASSETS-ONLY-001.md](invariants/core/INV-PLAN-ELIGIBLE-ASSETS-ONLY-001.md) | LAW-ELIGIBILITY, LAW-CONTENT-AUTHORITY |

### Scheduling — ScheduleDay

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-SCHEDULEDAY-ONE-PER-DATE-001 | [invariants/core/INV-SCHEDULEDAY-ONE-PER-DATE-001.md](invariants/core/INV-SCHEDULEDAY-ONE-PER-DATE-001.md) | LAW-DERIVATION, LAW-IMMUTABILITY |
| INV-SCHEDULEDAY-IMMUTABLE-001 | [invariants/core/INV-SCHEDULEDAY-IMMUTABLE-001.md](invariants/core/INV-SCHEDULEDAY-IMMUTABLE-001.md) | LAW-IMMUTABILITY, LAW-DERIVATION |
| INV-SCHEDULEDAY-NO-GAPS-001 | [invariants/core/INV-SCHEDULEDAY-NO-GAPS-001.md](invariants/core/INV-SCHEDULEDAY-NO-GAPS-001.md) | LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS |
| INV-SCHEDULEDAY-LEAD-TIME-001 | [invariants/core/INV-SCHEDULEDAY-LEAD-TIME-001.md](invariants/core/INV-SCHEDULEDAY-LEAD-TIME-001.md) | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY | `min_schedule_day_lead_days` (default: 3) |
| INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 | [invariants/core/INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001.md](invariants/core/INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |

### Scheduling — PlaylogEvent

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-PLAYLOG-ELIGIBLE-CONTENT-001 | [invariants/core/INV-PLAYLOG-ELIGIBLE-CONTENT-001.md](invariants/core/INV-PLAYLOG-ELIGIBLE-CONTENT-001.md) | LAW-ELIGIBILITY, LAW-DERIVATION |
| INV-PLAYLOG-MASTERCLOCK-ALIGNED-001 | [invariants/core/INV-PLAYLOG-MASTERCLOCK-ALIGNED-001.md](invariants/core/INV-PLAYLOG-MASTERCLOCK-ALIGNED-001.md) | LAW-RUNTIME-AUTHORITY |
| INV-PLAYLOG-LOOKAHEAD-001 | [invariants/core/INV-PLAYLOG-LOOKAHEAD-001.md](invariants/core/INV-PLAYLOG-LOOKAHEAD-001.md) | LAW-RUNTIME-AUTHORITY |
| INV-PLAYLOG-NO-GAPS-001 | [invariants/core/INV-PLAYLOG-NO-GAPS-001.md](invariants/core/INV-PLAYLOG-NO-GAPS-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 | [invariants/core/INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001.md](invariants/core/INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001.md) | LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-PLAYLOG-LOCKED-IMMUTABLE-001 | [invariants/core/INV-PLAYLOG-LOCKED-IMMUTABLE-001.md](invariants/core/INV-PLAYLOG-LOCKED-IMMUTABLE-001.md) | LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY |
| INV-PLAYLOG-LOOKAHEAD-ENFORCED-001 | [invariants/core/INV-PLAYLOG-LOOKAHEAD-ENFORCED-001.md](invariants/core/INV-PLAYLOG-LOOKAHEAD-ENFORCED-001.md) | LAW-RUNTIME-AUTHORITY |

### Scheduling — Playlist

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-PLAYLIST-GRID-ALIGNMENT-001 | [invariants/core/INV-PLAYLIST-GRID-ALIGNMENT-001.md](invariants/core/INV-PLAYLIST-GRID-ALIGNMENT-001.md) | LAW-GRID |

### Scheduling — Execution Lineage

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 | [invariants/core/INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001.md](invariants/core/INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001.md) | LAW-DERIVATION, LAW-CONTENT-AUTHORITY |
| INV-DERIVATION-ANCHOR-PROTECTED-001 | *(code-enforced)* | LAW-DERIVATION, LAW-IMMUTABILITY |
| INV-ASRUN-IMMUTABLE-001 | *(code-enforced)* | LAW-IMMUTABILITY |

### Scheduling — Cross-cutting

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-NO-MID-PROGRAM-CUT-001 | [invariants/core/INV-NO-MID-PROGRAM-CUT-001.md](invariants/core/INV-NO-MID-PROGRAM-CUT-001.md) | LAW-DERIVATION, LAW-GRID |
| INV-ASRUN-TRACEABILITY-001 | [invariants/core/INV-ASRUN-TRACEABILITY-001.md](invariants/core/INV-ASRUN-TRACEABILITY-001.md) | LAW-DERIVATION |
| INV-NO-FOREIGN-CONTENT-001 | [invariants/core/INV-NO-FOREIGN-CONTENT-001.md](invariants/core/INV-NO-FOREIGN-CONTENT-001.md) | LAW-CONTENT-AUTHORITY, LAW-DERIVATION |

### Scheduling — Execution Boundary

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CHANNELMANAGER-NO-PLANNING-001 | [invariants/core/INV-CHANNELMANAGER-NO-PLANNING-001.md](invariants/core/INV-CHANNELMANAGER-NO-PLANNING-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001 | [invariants/core/INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001.md](invariants/core/INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001.md) | LAW-RUNTIME-AUTHORITY, LAW-DERIVATION |
| INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001 | [invariants/core/INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001.md](invariants/core/INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |
| INV-FUTURE-WINDOW-MUTABLE-001 | [invariants/core/INV-FUTURE-WINDOW-MUTABLE-001.md](invariants/core/INV-FUTURE-WINDOW-MUTABLE-001.md) | LAW-IMMUTABILITY, LAW-CONTENT-AUTHORITY |
| INV-MATERIAL-RESOLVED-BEFORE-HORIZON-ENTRY-001 | [invariants/core/INV-MATERIAL-RESOLVED-BEFORE-HORIZON-ENTRY-001.md](invariants/core/INV-MATERIAL-RESOLVED-BEFORE-HORIZON-ENTRY-001.md) | LAW-ELIGIBILITY, LAW-RUNTIME-AUTHORITY |
| INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001 | [invariants/core/INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001.md](invariants/core/INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001.md) | LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY |

### Scheduling — Horizon Management

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-HORIZON-PROACTIVE-EXTEND-001 | [invariants/core/INV-HORIZON-PROACTIVE-EXTEND-001.md](invariants/core/INV-HORIZON-PROACTIVE-EXTEND-001.md) | LAW-CLOCK |
| INV-HORIZON-EXECUTION-MIN-001 | [invariants/core/INV-HORIZON-EXECUTION-MIN-001.md](invariants/core/INV-HORIZON-EXECUTION-MIN-001.md) | — |
| INV-HORIZON-NEXT-BLOCK-READY-001 | [invariants/core/INV-HORIZON-NEXT-BLOCK-READY-001.md](invariants/core/INV-HORIZON-NEXT-BLOCK-READY-001.md) | LAW-TIMELINE |
| INV-HORIZON-CONTINUOUS-COVERAGE-001 | [invariants/core/INV-HORIZON-CONTINUOUS-COVERAGE-001.md](invariants/core/INV-HORIZON-CONTINUOUS-COVERAGE-001.md) | — |
| INV-HORIZON-ATOMIC-PUBLISH-001 | [invariants/core/INV-HORIZON-ATOMIC-PUBLISH-001.md](invariants/core/INV-HORIZON-ATOMIC-PUBLISH-001.md) | — |
| INV-HORIZON-LOCKED-IMMUTABLE-001 | [invariants/core/INV-HORIZON-LOCKED-IMMUTABLE-001.md](invariants/core/INV-HORIZON-LOCKED-IMMUTABLE-001.md) | — |

### Scheduling — Channel Runtime

| Invariant | File | Derived From |
|-----------|------|--------------|
| INV-CHANNEL-TIMELINE-CONTINUITY-001 | [invariants/core/INV-CHANNEL-TIMELINE-CONTINUITY-001.md](invariants/core/INV-CHANNEL-TIMELINE-CONTINUITY-001.md) | LAW-CLOCK, LAW-TIMELINE |

### Playout — Cross-component

| Invariant | File |
|-----------|------|
| INV-SWITCH-BOUNDARY-TIMING | [invariants/core/INV-SWITCH-BOUNDARY-TIMING.md](invariants/core/INV-SWITCH-BOUNDARY-TIMING.md) |

---

## AIR

| Invariant | File |
|-----------|------|
| INV-BACKPRESSURE-SYMMETRIC | [invariants/air/INV-BACKPRESSURE-SYMMETRIC.md](invariants/air/INV-BACKPRESSURE-SYMMETRIC.md) |
| INV-BUFFER-EQUILIBRIUM | [invariants/air/INV-BUFFER-EQUILIBRIUM.md](invariants/air/INV-BUFFER-EQUILIBRIUM.md) |
| INV-DECODE-GATE | [invariants/air/INV-DECODE-GATE.md](invariants/air/INV-DECODE-GATE.md) |
| INV-NO-SILENCE-INJECTION | [invariants/air/INV-NO-SILENCE-INJECTION.md](invariants/air/INV-NO-SILENCE-INJECTION.md) |
| INV-PAD-PRODUCER | [invariants/air/INV-PAD-PRODUCER.md](invariants/air/INV-PAD-PRODUCER.md) |
| INV-PRODUCER-THROTTLE | [invariants/air/INV-PRODUCER-THROTTLE.md](invariants/air/INV-PRODUCER-THROTTLE.md) |
| INV-TIME-MODE-EQUIVALENCE-001 | [invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md](invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md) |

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
