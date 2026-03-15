# Plex Compatibility Interface

**Status:** Architectural Contract — normative for all Plex integrations  
**Authority Level:** Integration adapter — external interface only  
**Version:** 1.0  
**Date:** 2026-03-14

---

## I. Purpose

This contract defines the **externally observable behavior** RetroVue must provide so that Plex Live TV & DVR can interact with the system as a stable HDHomeRun-compatible tuner with a continuously updating programme guide and artwork.

### Goals

- Plex discovers **exactly one tuner** (one HDHomeRun device).
- Channel numbers remain **stable** across restarts and guide refreshes.
- Programme guide data is **always valid** for the current time.
- Guide data **refreshes automatically** without Plex restarts.
- RetroVue consistently supplies **stable artwork metadata and accessible artwork URLs** for programmes and channels in the Plex-facing guide.

### Boundary

This interface exists **strictly as an integration adapter**. It must **not** influence RetroVue’s core scheduling or identity models. The domain model remains authoritative for channel identity, scheduling, playlog, and as-run logging.

---

## II. External Interfaces

RetroVue MUST expose the following HTTP endpoints.

### HDHomeRun discovery

**Endpoint:** `GET /discover.json`

Returns device metadata expected by HDHomeRun clients. Response MUST include:

| Field        | Description                                      |
|-------------|---------------------------------------------------|
| `FriendlyName` | Human-readable device name (operator-configurable). |
| `DeviceID`    | Stable hex identifier unique per RetroVue instance. |
| `BaseURL`     | Base URL for the adapter (scheme + host + port).   |
| `LineupURL`   | URL to the channel lineup (MUST point to `/lineup.json`). |
| `TunerCount`  | Number of simultaneous tuners exposed by the device. This value MUST remain stable unless tuner capacity is intentionally reconfigured. (e.g. one device with 2 concurrent streams: `TunerCount: 2` is correct even with 200 channels.) |

See: [INV-PLEX-DISCOVERY-001](INV-PLEX-DISCOVERY-001.md).

### Channel lineup

**Endpoint:** `GET /lineup.json`

Returns the channel lineup presented to Plex. Each entry MUST include:

| Field        | Description                                        |
|-------------|-----------------------------------------------------|
| `GuideNumber` | Numeric channel number (string), stable per channel. |
| `GuideName`   | Display name for the channel.                        |
| `URL`         | Absolute URL to the channel’s MPEG-TS stream.        |

See: [INV-PLEX-LINEUP-001](INV-PLEX-LINEUP-001.md).

### Lineup status

**Endpoint:** `GET /lineup_status.json`

Provides scan and source information expected by HDHomeRun clients (e.g. `ScanInProgress`, `ScanPossible`, `Source`). MUST indicate that no scan is in progress and the lineup is available.

See: [INV-PLEX-TUNER-STATUS-001](INV-PLEX-TUNER-STATUS-001.md).

### Channel streams

**Endpoint:** `GET /channel/{channel_id}.ts`

Returns an MPEG-TS stream representing the current playout position for the channel. The stream MUST be the same playout output as for direct tuner requests (one producer per channel; no separate fanout or re-encode). The URL MAY use the canonical RetroVue channel ID; resolution to the correct playout source is the adapter’s responsibility.

See: [INV-PLEX-STREAM-START-001](INV-PLEX-STREAM-START-001.md), [INV-PLEX-FANOUT-001](INV-PLEX-FANOUT-001.md).

### Guide feed

**Endpoint:** `GET /iptv/guide.xml` (or equivalent, e.g. `/epg.xml` — implementation may expose the same content under a path configured for Plex).

When Plex is configured to consume the RetroVue XMLTV feed, the guide feed served by RetroVue MUST satisfy the invariants in this contract. (HDHomeRun-only use without guide consumption is out of scope for the guide invariants.)

Returns an **XMLTV** document representing the RetroVue EPG horizon. The `<channel id>` and `<programme channel>` values in the XMLTV served to Plex MUST use the same **external channel number** (Plex-facing guide ID) as `GuideNumber` in `/lineup.json`. Programme data MUST be derived from the same EPG source as the rest of RetroVue (no independent guide generation in the adapter).

See: [INV-PLEX-XMLTV-001](INV-PLEX-XMLTV-001.md).

### Poster / artwork endpoints

**Endpoints:**

- `GET /art/program/{program_id}.jpg` — programme poster/artwork.
- `GET /art/channel/{channel_id}.jpg` — channel logo.

Return artwork used in the XMLTV feed. Artwork MUST be accessible via HTTP without authentication. URLs referenced in XMLTV (e.g. `<icon src="..."/>`) MUST remain valid for the lifetime of the programme or channel entry. Artwork endpoints MAY redirect (HTTP 301/302) to the canonical artwork location provided the redirect target remains publicly accessible and stable.

---

## III. Channel Identity Rules

### Canonical channel ID vs Plex-facing external guide ID

- **Canonical channel ID:** RetroVue internal identity. Used by domain, playlog, as-run, and playout. Examples: `cheers-24-7`, `hbo`. External systems MUST NOT dictate these identifiers; they are owned by the domain.

- **Plex channel number / external guide ID:** Synthesized numeric identity used only in Plex-facing lineup and XMLTV. Plex requires numeric channel numbers; the adapter produces them (e.g. `101`, `201`) and MUST NOT let them replace internal channel identifiers.

- **Stream URL identity:** Stream URLs MAY use the canonical RetroVue channel ID internally; that is independent from the Plex-facing guide ID used in lineup and XMLTV.

### Mapping and consistency

- The adapter MUST maintain a **stable mapping** between canonical RetroVue channel ID and Plex-facing external channel number.
- `/lineup.json` MUST expose the external channel number as `GuideNumber`.
- The XMLTV `<channel id>` and `<programme channel>` values served to Plex MUST use that same external channel number.
- The mapping MUST remain stable across restarts.

---

## IV. EPG Time Model

- The XMLTV guide MUST represent **local station time** (not UTC).
- Timestamps MUST include the **local timezone offset**.
- Example format: `20260314120000 -0400`.
- **UTC-only timestamps MUST NOT be used** for programme start/stop in the guide.

---

## V. EPG Horizon

- The guide MUST extend to the **full RetroVue EPG horizon** as defined by the scheduling subsystem. The adapter MUST expose at least 48 hours of future programme data; typical deployments SHOULD expose approximately 72 hours.
- The **current time** MUST always fall within a valid programme window for every active channel (no gaps at “now”).
- Guide data MUST be regenerated or updated when schedules change so that the served XMLTV reflects the current EPG horizon.

---

## VI. Guide Refresh Behavior

When guide content changes, the guide endpoint MUST expose an **observable freshness change** detectable by Plex, including regenerated XML content and at least one cache-validator change (`ETag` and/or `Last-Modified`). Guide updates MUST occur without requiring Plex restarts; the adapter MUST NOT rely on Plex restart to pick up new guide data.

---

## VII. Poster and Artwork Rules

RetroVue guarantees **stable artwork metadata and accessible artwork URLs** for programmes and channels in the Plex-facing guide; what Plex actually renders is outside this contract. Artwork metadata MAY appear at both channel and programme levels within the XMLTV document.

- Programmes in the XMLTV guide MAY include artwork metadata, e.g.  
  `<icon src="http://server/art/program/123.jpg"/>`
- Artwork MUST remain **stable** for the lifetime of the programme.
- Channel logos MAY be provided, e.g.  
  `<icon src="http://server/art/channel/hbo.jpg"/>`
- Artwork MUST be **accessible via HTTP without authentication**.

---

## VIII. Invariants

The following conditions MUST always hold. Where an existing invariant document applies, it is cited.

### Single tuner invariant

RetroVue MUST present **exactly one** discoverable HDHomeRun device on the network. Multiple devices MUST NOT appear to Plex. (One device; `TunerCount` may be greater than one.)

**Related:** [INV-PLEX-DISCOVERY-001](INV-PLEX-DISCOVERY-001.md).

### Plex discovery surface invariant

RetroVue MUST NOT expose additional tuner-like or playlist-based discovery surfaces on commonly scanned IPTV or playlist paths that would cause Plex to register a second device or phantom tuner.

### Stable device identity invariant

`DeviceID` returned by `/discover.json` MUST remain **constant** across server restarts and MUST be derived from a **persistent instance identity** rather than regenerated at runtime.

**Related:** [INV-PLEX-DISCOVERY-001](INV-PLEX-DISCOVERY-001.md).

### Channel number stability invariant

A channel’s `GuideNumber` MUST NOT change unless the channel itself is deleted. The same internal channel MUST always map to the same `GuideNumber` after restarts. When a channel is deleted, its previous `GuideNumber` MUST NOT be reassigned to a different channel within the same server runtime session.

**Related:** [INV-PLEX-LINEUP-001](INV-PLEX-LINEUP-001.md).

### Channel ordering invariant

Channels in `/lineup.json` MUST be returned in **ascending `GuideNumber`** order.

### Lineup determinism invariant

The set of channels and their `GuideNumber` values returned by `/lineup.json` MUST remain deterministic across requests within a single runtime session.

### Stream availability invariant

Channel streams MUST begin producing MPEG-TS packets within a bounded startup interval suitable for HDHomeRun clients. The adapter MUST begin emitting TS packets promptly after connection and MUST NOT delay initial packet emission waiting for schedule transitions.

**Related:** [INV-PLEX-STREAM-START-001](INV-PLEX-STREAM-START-001.md).

### Guide continuity invariant

For every channel exposed in `/lineup.json`, the served XMLTV MUST contain **exactly one** programme interval covering the current time as defined by RetroVue’s system clock authority (MasterClock), expressed in the adapter’s local timezone. No gaps may exist at “now”; overlapping programme entries at the current instant are not permitted (see guide overlap invariant).

### Guide overlap invariant

For any given channel, programme intervals in the Plex-served XMLTV MUST NOT overlap. Adjacent programmes MAY be contiguous, but two distinct programme entries MUST NOT both cover the same instant.

### Guide horizon invariant

Guide data MUST extend to the full RetroVue EPG horizon as defined by the scheduling subsystem. The adapter MUST expose at least 48 hours of future programme data; typical deployments SHOULD expose approximately 72 hours.

### Lineup–guide bijection invariant

Every channel exposed in `/lineup.json` MUST appear in the Plex-served XMLTV, and every XMLTV channel intended for Plex MUST have a corresponding lineup entry. This prevents the “channel in lineup but no guide data” class of bugs (e.g. Plex showing “Unknown Airing”).

### Base URL consistency invariant

The absolute URLs exposed through discovery, lineup, guide, and artwork endpoints MUST resolve to the same adapter instance and remain self-consistent for the lifetime of a Plex setup session.

### Artwork availability invariant

Artwork URLs referenced in XMLTV MUST remain **accessible** for the lifetime of the programme entry (or channel, for channel logos).

---

## IX. Failure Tolerance

- **Temporary stream failures** (e.g. a channel cannot produce video momentarily) MUST NOT invalidate the channel lineup or guide.
- Plex MUST still see the tuner and guide data even if a channel temporarily cannot produce video.
- The adapter MAY return an error or non-200 for the affected channel stream while keeping `/discover.json`, `/lineup.json`, `/lineup_status.json`, and `/iptv/guide.xml` valid and unchanged.

---

## X. Architectural Placement

This compatibility layer belongs in the **integration adapter layer**, not the RetroVue domain. Implementation MUST live in that layer; see architecture documentation for suggested module paths.

The **domain model** remains authoritative for:

- Channel identity  
- Scheduling  
- Playlog  
- As-run logging  

The adapter **translates** domain state into HDHomeRun + XMLTV + artwork endpoints. It MUST NOT own channel identity, schedule compilation, or playout logic.

---

## XI. Contract Summary

### What Plex sees

Plex sees a single stable HDHomeRun device with numeric channels (e.g. 101 Cheers 24/7, 102 Twilight Zone, 201 HBO) and guide entries (e.g. 101 6:00 PM – 6:30 PM). Internally RetroVue continues to use canonical channel identities (`cheers-24-7`, `twilight-zone`, `hbo`) for schedules, playlog, as-run logs, automation, and analytics. This contract guarantees that separation.

### External behavior

Externally, RetroVue behaves as:

1. **HDHomeRun cable tuner** — one device, stable device ID, stable channel numbers, lineup and lineup status.
2. **XMLTV guide provider** — local-time EPG aligned to the scheduling subsystem’s EPG horizon (min 48 h; typical ~72 h), continuous coverage at “now”, refresh without Plex restart.
3. **Stable artwork server** — RetroVue supplies programme and channel artwork metadata and URLs that remain valid for the lifetime of the referenced entity (display behavior in Plex is not guaranteed by this contract).

Internally, RetroVue maintains its own scheduling and playout model. The Plex Compatibility Interface is a **translation layer** only. EPG content correctness (no gaps, no overlaps, continuous roll-forward, timezone correctness, schedule → EPG → XMLTV chain) is governed by the scheduling subsystem and the [XMLTV Export Contract](../xmltv/XMLTV_EXPORT_CONTRACT.md), not this adapter contract.

---

## XII. Related Invariants and Tests

| Invariant | Description | Required tests |
|-----------|-------------|----------------|
| [INV-PLEX-DISCOVERY-001](INV-PLEX-DISCOVERY-001.md) | HDHomeRun discovery payload | `pkg/core/tests/contracts/plex/test_plex_discovery.py` |
| [INV-PLEX-LINEUP-001](INV-PLEX-LINEUP-001.md) | Lineup one-to-one with channels, stable GuideNumber | `pkg/core/tests/contracts/plex/test_plex_lineup.py` |
| [INV-PLEX-TUNER-STATUS-001](INV-PLEX-TUNER-STATUS-001.md) | Lineup status (scan, source) | `pkg/core/tests/contracts/plex/test_plex_discovery.py` |
| [INV-PLEX-XMLTV-001](INV-PLEX-XMLTV-001.md) | XMLTV from EPG, channel IDs match lineup | `pkg/core/tests/contracts/plex/test_plex_epg.py` |
| [INV-PLEX-STREAM-START-001](INV-PLEX-STREAM-START-001.md) | Stream via ProgramDirector, no adapter playout | `pkg/core/tests/contracts/plex/test_plex_streaming.py` |
| [INV-PLEX-STREAM-DISCONNECT-001](INV-PLEX-STREAM-DISCONNECT-001.md) | Disconnect → tune_out, last viewer stops playout | `pkg/core/tests/contracts/plex/test_plex_streaming.py` |
| [INV-PLEX-FANOUT-001](INV-PLEX-FANOUT-001.md) | Plex and direct viewers share same producer | `pkg/core/tests/contracts/plex/test_plex_streaming.py` |

Test matrix: [TEST-MATRIX-PLEX.md](../TEST-MATRIX-PLEX.md).
