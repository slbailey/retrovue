# AsRunLogArtifactContract_v0.2

**Classification:** Contract (Core Artifact)
**Owner:** ChannelManager (Execution Recording)
**Enforcement Phase:** During Playout
**Created:** 2026-02-13
**Last Updated:** 2026-02-13
**Status:** Proposed
**VERSION:** 2

---

## 1. Purpose

The As-Run Log is the authoritative, persisted record of what actually occurred during playout execution for a channel and broadcast day.

**It documents:**
- Actual event start times
- Actual durations
- Execution status (SEG_START, AIRED, TRUNCATED, SKIPPED, etc.)
- Fence (block boundary) execution
- Execution anomalies and operational flags

This log is append-only and serves as both a legal and operational artifact.

---

## 2. Storage Location

As-run logs MUST be written to:
```
/opt/retrovue/data/logs/asrun/{channel_id}/{YYYY-MM-DD}.asrun
```

A machine-readable sidecar MUST be written to:
```
/opt/retrovue/data/logs/asrun/{channel_id}/{YYYY-MM-DD}.asrun.jsonl
```

---

## 3. Fixed-Width Format Specification

### File Format
The `.asrun` file is plain text, with fixed-width columns.

#### Header (required, each line prefixed with `#`)
```
# RETROVUE AS-RUN LOG
# CHANNEL: <channel_id>
# DATE: <YYYY-MM-DD>
# OPENED_UTC: <ISO8601>
# ASRUN_LOG_ID: <unique_id>
# VERSION: 2
```

#### Body Columns

| Column      | Width  | Description                                  |
|-------------|--------|----------------------------------------------|
| ACTUAL      | 8      | Actual start time (HH:MM:SS)                 |
| DUR         | 8      | Actual duration (HH:MM:SS)                   |
| STATUS      | 10     | START / SEG_START / AIRED / TRUNCATED / SHORT / SKIPPED / SUBSTITUTED / FENCE / ERROR |
| TYPE        | 8      | BLOCK / PROGRAM / AD / PROMO                 |
| EVENT_ID    | 32     | Execution event ID (matches Transmission Log) |
| NOTES       | Remainder | Structured key=value flags (see below)    |

`START` is only valid with `TYPE=BLOCK` and indicates block open.
`FENCE` is only valid with `TYPE=BLOCK` and indicates fence close.
`SEG_START` is only valid with `TYPE != BLOCK` and indicates the beginning of segment execution. It MUST precede exactly one terminal status for the same `EVENT_ID`.

**Terminal statuses:** AIRED, TRUNCATED, SHORT, SKIPPED, SUBSTITUTED, ERROR.

**Time basis:** The ACTUAL column is broadcast-day relative display time. UTC truth for reconciliation is carried in the JSONL sidecar.

### Midnight / Broadcast Day Handling

If execution crosses midnight within a broadcast day, ACTUAL values MAY exceed `23:59:59` (e.g., `24:30:00`). This preserves monotonic ordering within a single broadcast-day log file. UTC truth remains authoritative in the JSONL sidecar.

#### Example

```
ACTUAL   DUR      STATUS     TYPE     EVENT_ID                            NOTES
-------- -------- ---------- -------- ------------------------------------ -----------------------------
09:00:00 00:00:00 START      BLOCK    BLK-001                              (block open)
09:00:00 00:00:00 SEG_START  PROGRAM  EVT-0001                             (segment begin)
09:00:00 00:22:30 AIRED      PROGRAM  EVT-0001                             ontime=Y fallback=0
09:23:30 00:00:00 SEG_START  PROMO    EVT-0004                             (segment begin)
09:23:30 00:00:22 TRUNCATED  PROMO    EVT-0004                             truncated_by_fence=Y
09:30:00 00:00:00 FENCE      BLOCK    BLK-001-FENCE                        swap_tick=10800 fence_tick=10800 frames_emitted=10800 primed_success=Y truncated_by_fence=N early_exhaustion=N frame_budget_remaining=0
```

---

## 4. Invariants

- **AR-ART-001 -- Append Only**
  The `.asrun` file MUST be strictly append-only. Past entries MUST NOT be rewritten.

- **AR-ART-002 -- Event ID Fidelity**
  Every execution entry MUST reference the original `EVENT_ID` from the Transmission Log.

- **AR-ART-003 -- Fence Evidence Required**
  Each block MUST produce exactly two structural entries:
    - `STATUS=START`, `TYPE=BLOCK`, `EVENT_ID=<block_id>`
    - `STATUS=FENCE`, `TYPE=BLOCK`, `EVENT_ID=<block_id>-FENCE`
  The FENCE entry MUST include in NOTES:
    - `swap_tick` -- absolute `session_frame_index` at swap
    - `fence_tick` -- absolute `session_frame_index` at fence
    - `swap_tick` MUST equal `fence_tick`
    - `frames_emitted` -- total frames emitted during the block
    - `frame_budget_remaining` -- MUST be `0` at fence
    - `primed_success` (Y|N)
    - `truncated_by_fence` (Y|N)
    - `early_exhaustion` (Y|N)

- **AR-ART-004 -- Execution Truth Only**
  The `.asrun` text file MUST contain execution facts only.
  Scheduled or planned metadata (e.g., `scheduled_duration_ms`) MUST NOT appear in `.asrun`.
  Planned metadata MAY appear in the `.asrun.jsonl` sidecar for reconciliation purposes.

- **AR-ART-005 -- Crash Safety**
  Each write MUST be flushed to disk.
  Partial writes MUST NOT corrupt prior entries.

- **AR-ART-006 -- No Frame-Level Noise**
  No per-frame events are recorded.
  Only block, segment, and fence lifecycle.

- **AR-ART-007 -- Sidecar Consistency**
  Every `EVENT_ID` in `.asrun` MUST appear exactly once in `.asrun.jsonl` with matching status and actual timing fields, and vice versa.

- **AR-ART-008 -- Single Terminal Event**
  For each `EVENT_ID` of `TYPE != BLOCK`:
    - Exactly one terminal status MUST be emitted.
    - Terminal statuses: AIRED, TRUNCATED, SHORT, SKIPPED, SUBSTITUTED, ERROR.
    - `frames_aired` MUST be > 0 for AIRED and TRUNCATED.
    - Zero-frame terminal events are forbidden.

---

## 5. Sidecar JSONL Specification

Each line in the `.asrun.jsonl` sidecar MUST contain the following fields:

- `event_id`
- `actual_start_utc`
- `actual_duration_ms`
- `status`
- `reason`
- `block_id` (required for every line, including non-block events)
- `swap_tick` (for fence events)
- `fence_tick` (for fence events)
- `frames_emitted` (for fence events)
- `frame_budget_remaining` (for fence events)

Planned metadata fields (e.g., `scheduled_duration_ms`, `planned_start_utc`) MAY be included in JSONL lines for reconciliation. These fields MUST NOT appear in the `.asrun` text file.

*This file is required for downstream reconciliation and analysis.*

---

## 6. Required Tests

- Append-only enforcement test
- Event ID matching test
- Fence presence/structure validation
- Crash simulation durability test
- Reconciliation compatibility check
- SEG_START precedes terminal status test
- Single terminal event per EVENT_ID test
- Zero-frame terminal event rejection test
- Fence tick equality validation (swap_tick == fence_tick)
- frame_budget_remaining == 0 at fence test
- Broadcast-day midnight rollover test
