# XMLTV Export Contract

**Status:** Architectural Contract — normative for all XMLTV exports  
**Authority Level:** Integration adapter — external representation only  
**Version:** 1.0  
**Date:** 2026-03-14

---

## I. Purpose

This contract defines the **externally observable behavior** RetroVue must provide when exporting programme guide data in XMLTV format.

The XMLTV export provides a machine-readable programme guide that external systems such as Plex Live TV, IPTV clients, and EPG consumers can use to display channel schedules.

The export MUST accurately represent the RetroVue EPG horizon while preserving the invariants required by external guide consumers.

---

## II. Boundary

The XMLTV export layer is an **adapter**.

It MUST:

- Translate RetroVue EPG data into XMLTV format.
- Preserve timing and scheduling correctness.
- Maintain stable channel identities for the consumer.

It MUST NOT:

- Generate schedules independently.
- Modify scheduling decisions.
- Alter canonical channel identities.
- Influence playlog generation or scheduling logic.

**Authoritative data sources remain:**

- ScheduleService  
- EPG generation pipeline  
- RetroVue MasterClock  

---

## III. Source of Truth

XMLTV data MUST be derived from the RetroVue scheduling pipeline:

```
Schedule Templates
        ↓
SchedulePlan / ScheduleDay
        ↓
EPG Generation
        ↓
XMLTV Export Adapter
```

The XMLTV export MUST NOT generate programme data independently.

All programme entries MUST originate from the RetroVue EPG model.

---

## IV. Export Endpoint

Typical endpoint: `GET /iptv/guide.xml`

Alternative paths MAY be provided (e.g. `/epg.xml`) but MUST expose identical content.

The endpoint MUST return a valid XMLTV document.

---

## V. XMLTV Structure Requirements

The exported document MUST contain:

- `<tv>` — root
- `<channel>` — channel metadata
- `<programme>` — schedule entries

| Element      | Purpose                |
|-------------|------------------------|
| `<tv>`      | Root XMLTV document     |
| `<channel>` | Channel metadata        |
| `<programme>` | Programme schedule entries |

---

## VI. Channel Representation

Each channel exposed in the XMLTV MUST include a corresponding `<channel>` entry.

Example:

```xml
<channel id="101">
  <display-name>Cheers 24/7</display-name>
  <icon src="http://server/art/channel/cheers.jpg"/>
</channel>
```

### Channel ID rules

The `<channel id>` value MUST match the Plex-facing external channel number used in `/lineup.json` → `GuideNumber`.

Example mapping:

| Canonical channel ID | External guide ID |
|----------------------|--------------------|
| cheers-24-7          | 101                |
| hbo                  | 201                |

XMLTV MUST use the external guide ID.

---

## VII. Programme Representation

Each scheduled programme MUST be represented as a `<programme>` entry.

Example:

```xml
<programme start="20260314180000 -0400"
           stop="20260314183000 -0400"
           channel="101">
  <title>Cheers</title>
  <desc>Sam and Diane argue over a bar promotion.</desc>
  <icon src="http://server/art/program/cheers.jpg"/>
</programme>
```

| Attribute  | Description           |
|-----------|------------------------|
| `start`   | Programme start time   |
| `stop`    | Programme end time     |
| `channel` | Channel identifier     |

| Element   | Purpose      |
|-----------|--------------|
| `<title>` | Programme title |

Optional elements MAY include: `<desc>`, `<category>`, `<icon>`, `<episode-num>`. Additional XMLTV elements (e.g. `<rating>`, `<episode-num>`, `<date>`) MAY be included provided they do not violate the invariants of this contract.

---

## VIII. Time Representation

Programme timestamps MUST follow the XMLTV specification.

**Format:** `YYYYMMDDHHMMSS ±HHMM`

**Example:** `20260314183000 -0400`

### Time rules

- Time MUST be expressed in **local station time**.
- The **timezone offset** MUST be included.
- UTC timestamps without offset MUST NOT be used.

---

## IX. EPG Horizon

The XMLTV export MUST represent the **RetroVue EPG horizon** as defined by the scheduling subsystem.

- **Minimum:** The adapter MUST expose at least 48 hours of future programme data.
- **Preferred:** Typical deployments SHOULD expose approximately 72 hours.

The XMLTV horizon MUST extend to the current EPG horizon maintained by RetroVue scheduling services.

---

## X. Scheduling Integrity Rules

The XMLTV export MUST preserve scheduling correctness.

### Programme continuity invariant

For every channel, the XMLTV MUST contain **exactly one** programme covering the current time (as defined by RetroVue’s MasterClock, expressed in local timezone).

### No gaps invariant

Programme intervals MUST be **contiguous**. No gap between adjacent programmes.

Valid example:

- 18:00–18:30  
- 18:30–19:00  
- 19:00–19:30  

Invalid: 18:00–18:30 then 18:31–19:00 (gap).

### No overlap invariant

Two programme entries MUST NOT overlap.

Invalid: 18:00–18:30 and 18:20–18:50.

### Adjacent interval rule

Adjacent programme intervals MAY share boundaries (e.g. 18:00–18:30 and 18:30–19:00).

---

## XI. Lineup–Guide Consistency

The XMLTV export MUST remain consistent with the tuner lineup.

### Lineup–guide bijection invariant

- For every channel in `/lineup.json`, there MUST exist a corresponding `<channel>` entry in the XMLTV.
- Every `<channel>` entry intended for Plex (or the same consumer as the lineup) MUST correspond to a lineup channel.

---

## XII. Guide Refresh Behavior

When schedules change, the XMLTV export MUST expose an **observable freshness change**.

The adapter MUST:

- Regenerate XML content whenever the EPG horizon advances or when scheduled programme data within the horizon changes.
- Update cache validators (e.g. `ETag`, `Last-Modified`).

Guide updates MUST be visible to clients without requiring server restarts.

---

## XIII. Artwork Metadata

XMLTV MAY include artwork metadata (e.g. `<icon src="http://server/art/program/123.jpg"/>`).

**Artwork rules:**

- Artwork URLs MUST be accessible via HTTP without authentication.
- Artwork MAY appear at channel or programme level.
- Artwork URLs MUST remain valid for the lifetime of the programme entry.
- Redirects (e.g. HTTP 301/302) MAY be used provided the redirect target remains publicly accessible and stable.

---

## XIV. MasterClock Synchronization

XMLTV timing MUST align with the **RetroVue system clock authority** (MasterClock).

Programme intervals MUST be evaluated relative to MasterClock.

The export MUST NOT derive timing from independent system clock sources (e.g. `datetime.utcnow()` or a separate clock).

---

## XV. Failure Tolerance

Temporary internal failures (e.g. a channel cannot produce video) MUST NOT invalidate the XMLTV export.

- The XMLTV export MUST remain valid.
- Guide entries MUST still appear for that channel.

The guide represents **scheduled programming**, not stream health.

---

## XVI. Architectural Placement

The XMLTV export adapter belongs in the **integration layer**, not the domain. Implementation MUST live in that layer; see architecture documentation for suggested module paths (e.g. `retrovue/integrations/xmltv/`).

The adapter MUST: **EPG model → XMLTV document**.

It MUST NOT: schedule programmes, manage channels, or alter playout.

---

## XVII. Invariants

The following invariants MUST always hold.

| Invariant | Requirement |
|-----------|-------------|
| **XMLTV channel identity** | `<channel id>` values MUST match the Plex-facing external guide ID. |
| **XMLTV channel uniqueness** | Each `<channel id>` value MUST appear exactly once in the XMLTV document. No duplicate `<channel>` entries are permitted. |
| **XMLTV schedule continuity** | Every channel MUST have exactly one programme covering the current time. |
| **XMLTV gap** | Programme intervals MUST NOT contain gaps. |
| **XMLTV overlap** | Programme intervals MUST NOT overlap. |
| **XMLTV chronological ordering** | Programme entries for a given channel SHOULD appear in chronological order of their start times. |
| **XMLTV horizon** | The export MUST extend to the RetroVue EPG horizon and include at least 48 hours of future schedule data. |
| **XMLTV lineup consistency** | Every channel present in `/lineup.json` MUST appear in the XMLTV export. |
| **XMLTV time format** | Programme timestamps MUST include timezone offsets and MUST NOT be UTC-only. |

---

## XVIII. Contract Summary

The XMLTV export provides a **faithful external representation** of the RetroVue EPG horizon.

The adapter:

- Converts EPG data to XMLTV format.
- Preserves scheduling correctness (no gaps, no overlaps, continuity at “now”).
- Maintains channel identity mapping (external guide ID).
- Ensures continuous programme coverage.

The adapter does **not** generate schedules or alter scheduling logic. Scheduling authority remains within the RetroVue domain.

---

## XIX. Related Contracts

This contract complements:

- [EPG Generation Contract](../epg/EPG_GENERATION_CONTRACT.md) — defines the Schedule → EPG timeline this export consumes.
- [Plex Compatibility Interface](../plex/PLEX_COMPATIBILITY_INTERFACE.md)

Together they define the complete external interface required for Plex integration:

- HDHomeRun discovery  
- Lineup interface  
- Channel streams  
- XMLTV guide  
- Artwork endpoints  

EPG content correctness (schedule → EPG → XMLTV chain) is governed by this contract and the scheduling subsystem; the Plex contract governs how that XMLTV is exposed and consumed by Plex.
