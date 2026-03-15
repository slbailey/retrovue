# EPG Generation Contract

**Status:** Architectural Contract — normative for EPG generation  
**Authority Level:** Domain-level transformation contract  
**Version:** 1.0  
**Date:** 2026-03-14

---

## I. Purpose

This contract defines the required behavior and invariants of the **RetroVue EPG generation process**.

EPG generation transforms RetroVue scheduling data into a **continuous programme timeline** per channel. This timeline serves as the authoritative guide representation used by:

- XMLTV export  
- Guide channels  
- Schedule inspection  
- Operational monitoring  

The EPG model represents **programme-level scheduling**, not segment-level playout.

---

## II. Boundary

EPG generation sits **between** schedule planning and external guide export.

```
Schedule Templates
        ↓
SchedulePlan / ScheduleDay
        ↓
EPG Generation
        ↓
EPG Model
        ↓
XMLTV Export
```

EPG generation MUST:

- Convert schedule items into programme guide entries.  
- Maintain continuous programme timelines.  
- Preserve scheduling semantics.  

EPG generation MUST NOT:

- Alter schedules.  
- Generate programme segments (playlog).  
- Generate commercials or bumpers.  
- Influence playlog generation.  

Playlog generation is a separate downstream process.

---

## III. Source of Truth

EPG generation derives its input **exclusively** from the RetroVue scheduling system.

**Authoritative inputs include:**

- SchedulePlan  
- ScheduleDay  
- ScheduleItem  

Schedule definitions determine programme timing. EPG generation MUST NOT independently determine programme start times.

---

## IV. Time Authority

All EPG timing MUST be evaluated relative to the **RetroVue MasterClock**.

The EPG system MUST NOT rely on independent system clocks.

This guarantees that EPG, playlog, channel playout, and XMLTV export all share the same time authority.

---

## V. Channel Timeline Model

Each channel MUST maintain a **continuous programme timeline**.

Example:

- 18:00 – 18:30  Cheers  
- 18:30 – 19:00  Cheers  
- 19:00 – 19:30  Night Court  

This timeline represents the programme-level schedule.

It does **not** include:

- Commercials  
- Bumpers  
- Playout segments  

Those are handled by the playlog.

---

## VI. EPG Horizon

The EPG system MUST maintain a **rolling horizon** aligned with the scheduling subsystem.

- **Minimum:** Now → +48 hours of programme data.  
- **Preferred:** Now → approximately +72 hours.  

The scheduling subsystem is responsible for extending the horizon. EPG generation MUST reflect the current schedule horizon as defined by that subsystem.

---

## VII. Programme Identity

Each EPG entry represents a **programme airing**.

Example:

- Programme: Cheers  
- Start: 18:00  
- End: 18:30  
- Channel: cheers-24-7  

Programme entries MUST preserve the identity of the scheduled programme.

They MUST NOT introduce synthetic programme identifiers that do not correspond to a scheduled programme entity.

---

## VIII. Timeline Integrity Rules

The EPG model MUST maintain a **valid programme timeline**.

### Programme continuity invariant

Every channel MUST have **exactly one** programme covering the current time (as defined by MasterClock).

### No gaps invariant

Programme intervals MUST be **contiguous**. No gap between adjacent programmes.

Valid: 18:00–18:30, 18:30–19:00.  

Invalid: 18:00–18:30, 18:31–19:00 (gap).

### No overlap invariant

Programme intervals MUST NOT overlap.

Invalid: 18:00–18:30 and 18:20–18:50.

### Adjacent interval rule

Programme intervals MAY share boundaries (e.g. 18:00–18:30 and 18:30–19:00).

### Schedule boundary invariant

Programme intervals MUST remain continuous across schedule boundaries (e.g. midnight or ScheduleDay transitions). The transition between adjacent schedule days MUST NOT introduce gaps or overlaps.

---

## IX. Channel Timeline Determinism

For a given schedule state, EPG generation MUST produce the **same** programme timeline.

Repeated generation MUST produce identical results.

The EPG system MUST behave as a **pure transformation** from schedule data.

---

## X. Programme Ordering

Programme entries for each channel MUST be **ordered by start time**.

Example: 18:00, 18:30, 19:00.

This ordering MUST be deterministic.

---

## XI. Schedule Mutation Handling

When schedules change, the EPG timeline MUST update accordingly.

Examples: replace programme, insert special event, remove scheduled block.

EPG generation MUST produce a new timeline reflecting the updated schedule. After schedule mutation, EPG generation MUST restore all timeline invariants (continuity, no gaps, no overlaps) across the entire affected horizon.

Changes MUST propagate to downstream consumers: XMLTV export, guide channel, monitoring systems.

---

## XII. Relationship to Playlog

The EPG represents **programme-level** scheduling only.

The playlog represents **fine-grained playout execution**.

Example:

**EPG:** 18:00–18:30  Cheers  

**Playlog:** 18:00–18:22  Cheers segment; 18:22–18:25  Commercial pod; 18:25–18:30  Cheers segment  

The EPG MUST NOT include playlog segmentation.

---

## XIII. Failure Tolerance

Temporary failures (e.g. a channel cannot currently stream) MUST NOT invalidate the EPG model.

- The EPG timeline MUST remain valid.  
- Programme entries MUST still appear for that channel.  

The EPG represents **scheduled programming**, not runtime playback state.

---

## XIV. Architectural Placement

EPG generation belongs to the **domain scheduling layer**. Implementation MUST live in that layer; see architecture documentation for suggested module paths.

The EPG system operates on domain models: SchedulePlan, ScheduleDay, ScheduleItem.

It produces: **EPG entries** (continuous programme timeline per channel).

External adapters (XMLTV export, guide channel) consume the EPG model.

---

## XV. Invariants

The following invariants MUST always hold.

| Invariant | Requirement |
|-----------|-------------|
| **EPG continuity** | Every channel MUST have exactly one programme covering the current time. |
| **EPG gap** | Programme intervals MUST NOT contain gaps. |
| **EPG overlap** | Programme intervals MUST NOT overlap. |
| **EPG schedule boundary** | Programme intervals MUST remain continuous across schedule boundaries (e.g. midnight or ScheduleDay transitions); no gaps or overlaps at boundaries. |
| **EPG chronological ordering** | Programme entries MUST be ordered by start time. |
| **EPG determinism** | Identical schedule state MUST produce identical EPG timelines. |
| **EPG horizon** | The timeline MUST extend to the configured EPG horizon (≥48 hours; typical ~72 hours). |
| **EPG channel timeline uniqueness** | For each canonical channel ID, the EPG model MUST produce exactly one programme timeline. A channel MUST NOT have multiple independent timelines within the EPG model. |
| **EPG channel coverage** | Every channel defined in the scheduling system MUST have a corresponding EPG timeline covering the EPG horizon. |

---

## XVI. Contract Summary

The EPG generation system converts RetroVue scheduling data into a **continuous programme timeline** per channel.

The EPG:

- Reflects schedule decisions.  
- Maintains a valid timeline (no gaps, no overlaps, continuity at “now”).  
- Preserves programme identity.  
- Remains synchronized with MasterClock.  

It is the **authoritative guide representation** used by all downstream consumers. Guide correctness is guaranteed at the EPG layer before adapters (XMLTV, Plex) consume it; if an external guide consumer displays incorrect data, the defect cannot originate in the domain layer.

### Protected failure modes

Together with the XMLTV and Plex contracts, the guide pipeline protects against the following failure classes:

| Failure | Prevented by |
|---------|----------------|
| Guide gap | EPG gap invariant |
| Guide overlap | EPG overlap invariant |
| Wrong current show | Continuity invariant |
| Timezone drift | MasterClock rule |
| Missing channels | Channel coverage invariant |
| Duplicate channels | Lineup–guide bijection (XMLTV / Plex contracts) |

---

## XVII. Related Contracts

This contract underpins the following integration contracts:

| Contract | Role |
|----------|------|
| [XMLTV Export Contract](../xmltv/XMLTV_EXPORT_CONTRACT.md) | Defines how the EPG model is exported to XMLTV format. |
| [Plex Compatibility Interface](../plex/PLEX_COMPATIBILITY_INTERFACE.md) | Defines how the XMLTV guide and tuner interface are exposed to Plex. |

### Architectural relationship

Together these contracts define the guide pipeline:

```
Schedule Templates
        ↓
SchedulePlan
        ↓
EPG Generation Contract (this document)
        ↓
XMLTV Export Contract
        ↓
Plex Compatibility Contract
```

These contracts ensure that RetroVue always produces a valid, continuous programme guide suitable for external guide consumers.

A future **Playlog Generation Contract** (EPG → Playlog) would complete the broadcast simulation chain by governing the transformation from EPG programme timeline to segment-level playlog (programme + ads + bumpers) without drift or timing errors.
