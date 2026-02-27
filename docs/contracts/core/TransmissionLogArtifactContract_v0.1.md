# TransmissionLogArtifactContract_v0.1

**Classification:** Contract (Core Artifact)  
**Owner:** Core Planning / HorizonManager  
**Enforcement:** Schedule Lock  
**Created:** 2026-02-13  
**Status:** Proposed

---

## 1. Purpose

The Transmission Log is the authoritative, persisted record of scheduled playout intent for a channel and broadcast day.

**It documents:**
- The locked playout plan
- Wall-clock-aligned block intervals
- Ordered list of all scheduled events
- Deterministic filler resolutions
- Immutable statement of execution intent

This log is an operational artifact intended for broadcast engineers.

**Explicitly NOT:**
- A debug or diagnostic dump
- An internal data serialization (e.g., JSON)
- Regenerated or altered during execution

**Time basis:** UTC truth for reconciliation is carried in the JSONL sidecar; human log is display-time.

---

## 2. Storage Location

Transmission logs MUST be written to:
```
/opt/retrovue/data/logs/transmission/{channel_id}/{YYYY-MM-DD}.tlog
```

A machine-readable sidecar MUST be written to:
```
/opt/retrovue/data/logs/transmission/{channel_id}/{YYYY-MM-DD}.tlog.jsonl
```

---

## 3. Fixed-Width Format Specification

### File Format
The `.tlog` file is plain text, fixed-width columns.

#### Header (required, each line prefixed with `#`)
```
# RETROVUE TRANSMISSION LOG
# CHANNEL: <channel_id>
# DATE: <YYYY-MM-DD>
# TIMEZONE_DISPLAY: <tz>
# GENERATED_UTC: <ISO8601>
# TRANSMISSION_LOG_ID: <unique_id>
# VERSION: 1
```

#### Body Columns (fixed width)

| Column      | Width   | Description                                  |
|-------------|---------|----------------------------------------------|
| TIME        | 8       | HH:MM:SS (display timezone)                  |
| DUR         | 8       | HH:MM:SS                                     |
| TYPE        | 8       | BLOCK / PROGRAM / AD / PROMO / FENCE         |
| EVENT_ID    | 32      | Stable unique event identifier               |
| TITLE_ASSET | rem.    | Title and optionally asset URI               |

#### Example

```
TIME     DUR      TYPE     EVENT_ID                            TITLE / ASSET
-------- -------- -------- ------------------------------------ --------------------------------------------
09:00:00 00:30:00 BLOCK    BLK-001                             Weekday Morning Block UTC_START=2026-02-13T14:00:00Z UTC_END=2026-02-13T14:30:00Z
09:00:00 00:22:30 PROGRAM  EVT-0001                             Cheers S01E01
09:22:30 00:00:30 AD       EVT-0002                             ACME AUTO :30
09:30:00 00:00:00 FENCE    BLK-001-FENCE                       UTC_END=2026-02-13T14:30:00Z
```

---

## 4. Invariants

- **TL-ART-001 — Immutability After Lock**  
  Once written, a `.tlog` file MUST NOT be modified.  
  The `.tlog` is write-once per TL ID; the same TL ID cannot be overwritten.  
  If you regenerate, the TL ID changes and the old file remains.  
  *To regenerate, create a new `TRANSMISSION_LOG_ID`.*

- **TL-ART-002 — Deterministic Ordering**  
  Events MUST appear in execution order.  
  Block fences MUST appear at block boundaries.

- **TL-ART-003 — Stable Event IDs**  
  Every event MUST have a stable `EVENT_ID`.  
  *These IDs MUST be reused in the As-Run Log.*

- **TL-ART-004 — Wall-Clock Fidelity**  
  Block boundaries MUST reflect UTC start and end times.  
  A `TYPE=BLOCK` line MUST include `UTC_START=<iso8601>` and `UTC_END=<iso8601>` in the TITLE_ASSET column (or NOTES portion).  
  A fence line MUST include `UTC_END=<iso8601>` in the TITLE_ASSET column.

- **TL-ART-005 — No Execution Data**  
  The Transmission Log MUST NOT contain:  
  - Actual start times  
  - Truncation markers  
  - Fallback indicators  
  - Priming indicators  
  - Swap ticks  
  *It represents scheduled plan only.*

- **TL-ART-006 — Sidecar Consistency**  
  Every `EVENT_ID` in `.tlog` MUST appear exactly once in `.tlog.jsonl` with matching type and scheduled timing fields, and vice versa.

---

## 5. Sidecar JSONL Specification

Each line in the `.tlog.jsonl` sidecar MUST contain the following fields:

- `event_id`
- `block_id`
- `scheduled_start_utc`
- `scheduled_duration_ms`
- `type`
- `asset_uri` (if applicable)

*This file is required for reconciliation.*

---

## 6. Required Tests

- Fixed-width format validation
- Deterministic regeneration check
- Block fence presence validation
- Event ID uniqueness enforcement
- Immutability enforcement

