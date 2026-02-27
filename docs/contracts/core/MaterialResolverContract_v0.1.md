# Material Resolver Contract — v0.1

**Status:** Contract
**Version:** 0.1

**Classification:** Contract (Planning Semantics — Material)
**Authority Level:** Coordination (Pre-runtime)
**Governs:** Schedule Manager ↔ Asset Library boundary
**Out of Scope:** Runtime playout, decoder behavior, encoding, transport, ingest pipeline internals

---

## 1. Purpose

This contract defines the **material resolution boundary** between Schedule Manager (traffic) and Asset Library (catalog). It specifies what editorial and technical metadata Schedule Manager may request from the Asset Library, how that metadata is produced and maintained, and what material operations are **prohibited** during planning and execution.

Material resolution is the process by which abstract scheduling references (programs, episodes, virtual assets) are converted to concrete, broadcast-ready material with known technical properties. This contract governs the rules and boundaries of that conversion.

**Key principle:** All technical measurement of material occurs at ingest time. Planning consumes the results; it never performs measurement.

---

## 2. Definitions

| Term | Definition |
|------|------------|
| **Material** | A discrete media item (episode, movie, promo, bumper, ad, filler) registered in the Asset Library with known technical and editorial properties. Material is the broadcast-operations term for what the catalog stores as an asset. |
| **Material resolution** | The act of converting a scheduling reference (e.g. a program or episode identifier) to a concrete material record with a stable asset identifier, file path, and validated metadata. Performed by Schedule Manager against the Asset Library during planning. |
| **Schedulable material** | Material that satisfies all broadcast-readiness requirements: probed, editorially complete, operator-approved, and not retired or deleted. Only schedulable material may appear in a Schedule Day or execution plan. |
| **Unschedulable material** | Material that fails one or more broadcast-readiness requirements. Unschedulable material MUST NOT enter a Schedule Day or execution plan. |
| **Probed metadata** | Technical properties extracted by ffprobe (or equivalent measurement tool) at ingest time: duration, container, codecs, chapter markers, resolution, audio channel layout. Probed metadata is measurement, not editorial assertion. |
| **Editorial metadata** | Operator- or provider-supplied descriptive properties: title, episode identity, season/episode number, genre, content rating, description. Editorial metadata is assertion, not measurement. |
| **Station-operational metadata** | Properties governing how material behaves in a broadcast context: content class, daypart profile, ad avail model. Derived from editorial metadata and operator policy during or after ingest. |
| **Approval** | Operator or automated gate confirming material is broadcast-ready. Approval is a prerequisite for schedulability; it is not reversible by the planning pipeline. |
| **Ingest-time** | The period during which material is discovered, enriched, probed, scored, and registered in the Asset Library. All measurement and initial classification occur here. |

---

## 3. Authority Model

### Asset Library

- **Catalog authority.**
- Owns the authoritative record of all material: identity, technical properties, editorial metadata, approval state, and lifecycle.
- Serves metadata to planning consumers on request. Does not initiate planning or interpret scheduling intent.
- Accepts material only through the ingest pipeline; does not accept material from planning or execution paths.

### Schedule Manager

- **Planning authority.**
- Queries the Asset Library to resolve scheduling references to concrete material during planning.
- Consumes metadata as supplied by the catalog. Does not measure, probe, or independently derive technical properties.
- Determines schedulability based on catalog-supplied metadata and planning policy. Does not modify catalog state.

### Channel Manager

- **Execution authority.**
- Receives resolved material references (asset identifiers, file paths) in the execution plan. Does not query the Asset Library. Does not resolve material.

### No shared authority

- Schedule Manager does not write to or modify the Asset Library.
- Asset Library does not make scheduling decisions.
- Channel Manager does not participate in material resolution.

---

## 4. Metadata Available to Schedule Manager

Schedule Manager MAY request the following metadata from the Asset Library during planning. All metadata is read-only; Schedule Manager does not modify catalog records.

### Required technical metadata

The following technical properties MUST be available for every schedulable material item. Schedule Manager depends on these for correct planning.

| Property | Source | Use in planning |
|----------|--------|-----------------|
| **Duration** (milliseconds) | Probed at ingest | Block duration math, grid alignment, segment boundary computation, filler/pad calculation |
| **Chapter markers** (list of chapter boundaries with timestamps) | Probed at ingest (if present in material) | Break detection for program segmentation and ad avail placement (per Program Segmentation and Ad Avail Contract) |
| **Approval state** (schedulable flag) | Ingest scoring and operator action | Gate: only approved material enters Schedule Day or execution plan |
| **Lifecycle state** | Catalog-managed | Gate: only material in broadcast-ready state is eligible for resolution |

### Required editorial metadata

| Property | Source | Use in planning |
|----------|--------|-----------------|
| **Title** | Provider, sidecar, or operator | EPG, as-run logging, operator display |
| **Episode identity** (season, episode number, episode title) | Provider, sidecar, or operator | Episode selection and rotation logic; EPG display |
| **Content class** (episode, movie, promo, bumper, ad, filler) | Sidecar or operator classification | Zone placement rules, ad avail model selection |

### Optional metadata

Schedule Manager MAY use additional catalog metadata (genre, content rating, daypart profile, resolution, codec) for planning policy decisions. These are not required for basic scheduling correctness but may influence zone eligibility, content filtering, or quality-aware placement.

### Metadata not available to Schedule Manager

Schedule Manager MUST NOT request or depend on:

- Raw ffprobe output (JSON, stream descriptors, bitrate details beyond what is surfaced as catalog metadata).
- Filesystem paths for the purpose of probing, reading, or measuring material. File paths are consumed only as opaque references in the execution plan.
- Decoder state, frame counts, or GOP structure.

---

## 5. Prohibited Operations

### During planning

Schedule Manager MUST NOT:

- **Probe material.** No invocation of ffprobe, mediainfo, or any measurement tool against material files. Duration, chapters, and all technical properties are consumed from the Asset Library as pre-measured values.
- **Access the filesystem to inspect material.** No stat, open, read, or seek on material files. File paths are opaque identifiers, not handles for inspection.
- **Derive technical properties independently.** Schedule Manager does not calculate duration from frame count and frame rate, does not parse container headers, and does not infer chapter structure from content analysis.
- **Modify catalog records.** Schedule Manager does not update approval state, duration, or any other metadata in the Asset Library. Catalog mutations occur only through the ingest pipeline or operator action.

### During execution

Channel Manager MUST NOT:

- Query the Asset Library for any purpose.
- Probe, measure, or inspect material files for metadata. All required information is embedded in the execution plan by Schedule Manager.
- Trigger material resolution, episode selection, or approval checks.

### At all times

- ffprobe (or equivalent) MUST NOT be invoked outside the ingest pipeline. It is an **ingest-time measurement tool**, not a planning or execution utility.
- No component other than the ingest pipeline writes probed metadata to the Asset Library.

---

## 6. Schedulability Requirements

Material is **schedulable** if and only if all of the following conditions are met:

1. **Probed.** Technical metadata (at minimum: duration) has been extracted by the ingest pipeline and is present in the catalog.
2. **Duration known.** Duration in milliseconds is a non-null, positive value. Material with unknown or zero duration is unschedulable.
3. **Approved.** The material has been approved for broadcast, either by automated confidence scoring at ingest or by explicit operator action.
4. **Lifecycle state is broadcast-ready.** The material is in the catalog's broadcast-ready state and has not been retired or deleted.
5. **Editorially identified.** Sufficient editorial metadata exists for the material to be placed in a zone and displayed in an EPG (at minimum: title and content class).

Schedule Manager MUST verify these conditions when resolving material. Failure of any condition makes the material unschedulable.

---

## 7. Failure Semantics

### Unschedulable material encountered during resolution

When Schedule Manager encounters material that fails schedulability requirements:

- The material MUST NOT be placed in a Schedule Day or execution plan.
- The failure MUST be recorded as a **planning fault** with sufficient detail for operator diagnosis (material identifier, failed condition, channel, date).
- Schedule Manager MUST NOT substitute alternative material silently. If substitution policy exists (e.g. fallback to a different episode or filler), the substitution itself MUST be a documented, observable planning decision — not a hidden recovery.
- If no substitute is available and the zone cannot be filled, the resulting gap is a planning failure governed by Schedule Horizon Management Contract §7.

### Missing metadata

If required metadata (duration, approval state) is absent from the catalog for material that is otherwise expected to be schedulable:

- The material MUST be treated as unschedulable.
- The failure MUST be attributed to the ingest pipeline (metadata not extracted or not persisted), not to Schedule Manager.
- Schedule Manager MUST NOT attempt to derive the missing metadata independently (e.g. by probing the file).

### Stale or inconsistent metadata

- Schedule Manager consumes metadata as of the time of resolution. If metadata changes after resolution but before playout (e.g. an operator retires an asset), the execution plan reflects the state at resolution time.
- Execution plan immutability (per Schedule Horizon Management Contract §4) governs: locked execution data is not retroactively invalidated by catalog changes. Corrective action requires operator-initiated override and regeneration.

---

## 8. Duration as Contractual Truth

Duration deserves special treatment because it is the single most critical technical property for scheduling correctness.

- **Duration is measured once, at ingest, by ffprobe (or equivalent).** It is stored in the Asset Library as probed metadata.
- **Duration is consumed by Schedule Manager as a fact**, not recomputed or verified. Schedule Manager trusts the catalog value.
- **Duration drives:** block boundary computation, grid alignment, segment timing, filler and pad calculation, ad inventory math (per Program Segmentation and Ad Avail Contract §4).
- **Incorrect duration is an ingest fault.** If probed duration does not match actual material duration, the error propagates through planning and into execution. Corrective action is re-ingest or operator metadata correction, not planning-time measurement.
- **Duration MUST NOT be re-probed** during planning or execution. If duration is suspected incorrect, the resolution is to re-run the ingest enrichment pipeline and update the catalog — not to probe the file from the planning path.

---

## 9. Chapter Markers and Break Detection

Chapter markers, when present in material, inform the break detection process defined in the Program Segmentation and Ad Avail Contract.

- **Chapter markers are extracted at ingest** by ffprobe (or equivalent) and stored in the Asset Library as structured metadata (ordered list of chapter boundaries with timestamps).
- **Schedule Manager reads chapter markers from the catalog** during segmentation. It does not parse the material file to find them.
- **Absence of chapter markers** triggers synthetic break generation per Program Segmentation and Ad Avail Contract §3. Schedule Manager does not treat absent markers as an error; it applies policy.
- **Chapter markers are immutable after ingest.** They are not editable by Schedule Manager. If markers are incorrect, the resolution is re-ingest or operator correction in the catalog.

---

## 10. Non-Responsibilities

### Asset Library does not

- Make scheduling decisions.
- Determine what airs when.
- Evaluate zone eligibility or grid fit.
- Supply execution plans or playlists.
- Communicate with Channel Manager.

### Schedule Manager does not

- Ingest, discover, or register material.
- Run enrichers or measurement tools.
- Modify approval state, duration, or any catalog metadata.
- Access material files for any purpose other than passing opaque references into execution plans.
- Verify that file paths are valid at planning time (path validity is an ingest and infrastructure concern).

### Channel Manager does not

- Resolve material references.
- Query the Asset Library.
- Evaluate schedulability.
- Measure or probe material.
- Derive technical properties from material files.

---

## 11. Relationship to Other Contracts

- **Schedule Manager Planning Authority (v0.1):** Defines Schedule Manager as the sole planning authority and lists material resolution as a planning responsibility. **This contract specifies the rules and boundaries of that resolution** — what metadata is available, how it is produced, and what operations are forbidden.
- **Schedule Horizon Management (v0.1):** Defines when resolved material enters the locked execution horizon. Material resolution MUST succeed before execution data enters the execution horizon; resolution failure at horizon-entry time is a planning fault (§7 of both contracts).
- **Schedule Execution Interface (v0.1):** Defines what crosses the boundary to Channel Manager. Resolved material references (asset identifiers, file paths, durations) are embedded in execution plans by Schedule Manager. **This contract ensures those references are grounded in catalog-validated metadata, not in runtime measurement.**
- **Program Segmentation and Ad Avail (v0.1):** Consumes chapter markers and duration from material resolution to determine break structure and ad inventory. **This contract ensures those inputs are catalog-supplied, ingest-measured values.**

---

## 12. Non-Goals

- **Runtime material validation:** Verifying that a file exists, is readable, or matches its cataloged properties at playout time is a runtime concern, not a material resolution concern.
- **Transcoding or format normalization:** Material format suitability for playout is an ingest or infrastructure concern. Schedule Manager does not evaluate codec compatibility or trigger transcoding.
- **Dynamic material selection at playout time:** Material is resolved during planning and locked in the execution horizon. No viewer-driven or demand-driven material selection occurs.
- **Metadata enrichment during planning:** Schedule Manager consumes metadata; it does not enrich, correct, or supplement it. Enrichment is an ingest-pipeline responsibility.
- **As-run reconciliation:** Comparing what actually aired against what was planned is an audit function, not a material resolution function.

---

**Document version:** 0.1
**Related:** [Schedule Manager Planning Authority (v0.1)](ScheduleManagerPlanningAuthority_v0.1.md) · [Schedule Horizon Management (v0.1)](ScheduleHorizonManagementContract_v0.1.md) · [Schedule Execution Interface (v0.1)](ScheduleExecutionInterfaceContract_v0.1.md) · [Program Segmentation and Ad Avail (v0.1)](ProgramSegmentationAndAdAvailContract_v0.1.md)
**Governs:** Schedule Manager ↔ Asset Library material resolution boundary
