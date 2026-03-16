# INV-HDHOMERUN-COMPAT-001: HDHomeRun Tuner Emulation Contract

## Purpose

RetroVue must present itself to Plex as an HDHomeRun-compatible tuner device.
Plex **only** supports HDHomeRun-compatible tuners for Live TV — there is no
generic IPTV/M3U support. Full compliance with the HDHomeRun HTTP API ensures
reliable channel scanning, stream delivery, and EPG integration.

## Authority

This contract is the sole authority for HDHomeRun emulation behavior in Core.
Implementation must conform to this document. Changes require contract update first.

---

## 1. Discovery Endpoints

### 1.1 `GET /discover.json`

Current response (RetroVue):
```json
{
  "FriendlyName": "RetroVue",
  "DeviceID": "52565545",
  "Manufacturer": "RetroVue",
  "DeviceAuth": "",
  "BaseURL": "http://localhost:8000",
  "LineupURL": "http://localhost:8000/lineup.json",
  "TunerCount": 2
}
```

Required response:
```json
{
  "FriendlyName": "RetroVue",
  "Manufacturer": "Silicondust",
  "ModelNumber": "HDHR5-4US",
  "FirmwareName": "hdhomerun5_atsc",
  "FirmwareVersion": "20210210",
  "DeviceID": "52565545",
  "DeviceAuth": "retrovue",
  "BaseURL": "http://<external_ip>:8000",
  "LineupURL": "http://<external_ip>:8000/lineup.json",
  "TunerCount": 2
}
```

| Field | Current | Required | Gap |
|-------|---------|----------|-----|
| `FriendlyName` | "RetroVue" | "RetroVue" | OK |
| `Manufacturer` | "RetroVue" | "Silicondust" | **CHANGE** — Plex identifies device type by manufacturer |
| `ModelNumber` | missing | "HDHR5-4US" | **ADD** — Plex uses this for capability detection |
| `FirmwareName` | missing | "hdhomerun5_atsc" | **ADD** — identifies firmware variant |
| `FirmwareVersion` | missing | "20210210" | **ADD** — date-based version string |
| `DeviceID` | "52565545" | 8 hex uppercase chars | OK (already valid hex) |
| `DeviceAuth` | "" | non-empty string | **CHANGE** — empty string may cause issues |
| `BaseURL` | "http://localhost:8000" | external IP | **CHANGE** — must be reachable by Plex |
| `LineupURL` | present | present | OK |
| `TunerCount` | 2 | 2 | OK |

### 1.2 `GET /lineup_status.json`

Current response: **Compliant.** No changes needed.

### 1.3 `GET /lineup.json`

Current response:
```json
[
  {
    "GuideNumber": "101",
    "GuideName": "Cheers 24/7",
    "URL": "http://localhost:8000/channel/cheers-24-7.ts"
  }
]
```

Required additions:
```json
{
  "GuideNumber": "101",
  "GuideName": "Cheers 24/7",
  "HD": 1,
  "URL": "http://<external_ip>:8000/channel/cheers-24-7.ts"
}
```

| Field | Current | Required | Gap |
|-------|---------|----------|-----|
| `GuideNumber` | present | present | OK |
| `GuideName` | present | present | OK |
| `HD` | missing | `1` for HD channels | **ADD** |
| `URL` | localhost | external IP | **CHANGE** — must use same IP as BaseURL |

### 1.4 `POST /lineup.post`

**Missing.** Plex may call this during DVR setup for channel scan control.
Implement as no-op returning `200 OK`.

### 1.5 `GET /device.xml`

**Missing.** UPnP device descriptor for SSDP auto-discovery.
Optional if using manual device entry, but recommended for reliability.

---

## 2. Stream Delivery

### 2.1 Stream URL

Current: `/channel/{channel_id}.ts`
HDHomeRun native: `/auto/v{channel_number}`

**No change required.** Plex reads the URL from `lineup.json` verbatim.
The URL pattern does not need to match HDHomeRun's native format.

### 2.2 HTTP Response Headers

Current:
```
HTTP/1.1 200 OK
Content-Type: video/mp2t
Transfer-Encoding: chunked
Connection: close
Cache-Control: no-cache
```

HDHomeRun sends:
```
HTTP/1.1 200 OK
Content-Type: video/mpeg
Transfer-Encoding: chunked
```

| Header | Current | HDHomeRun | Gap |
|--------|---------|-----------|-----|
| `Content-Type` | `video/mp2t` | `video/mpeg` | **CHANGE** — HDHomeRun uses `video/mpeg` |
| `Transfer-Encoding` | `chunked` | `chunked` | OK |
| `Connection` | `close` | not sent | **EVALUATE** — may remove |
| `Cache-Control` | `no-cache` | not sent | Harmless, keep |

### 2.3 Stream Error Responses

HDHomeRun returns `503 Service Unavailable` when tuner is busy.
Current behavior: **Compliant** (503 when at startup capacity).

---

## 3. MPEG-TS Stream Characteristics

### 3.1 Video

| Property | Current | HDHomeRun (CONNECT passthrough) | HDHomeRun (EXTEND transcode) | Gap |
|----------|---------|--------------------------------|------------------------------|-----|
| Codec | H.264 (Constrained Baseline) | MPEG-2 or H.264 | H.264 Main Profile | OK — H.264 is correct |
| Profile | Constrained Baseline | Main/High (passthrough) | Main | **EVALUATE** — Baseline works but Main/High is more standard |
| GOP | 90 frames (~3s) | Varies (broadcast) | ~30-90 frames | OK |
| B-frames | 0 | Varies | 0 or low | OK |
| Bitrate | 8 Mbps | 10-19 Mbps (passthrough) | 3-7 Mbps (transcode) | OK |
| Resolution | 1280x720 | 1920x1080i or 1280x720p | Up to 1080p | OK |

### 3.2 Audio

| Property | Current | HDHomeRun | Gap |
|----------|---------|-----------|-----|
| Codec | AAC LC | AC-3 (Dolby Digital) | **EVALUATE** — AC-3 is standard for ATSC; AAC works but may trigger transcode |
| Sample rate | 48000 Hz | 48000 Hz | OK |
| Channels | Stereo | 5.1 or stereo | OK |
| Bitrate | 128 kbps | 384 kbps (AC-3) | OK |

### 3.3 MPEG-TS Container

| Property | Current | Required | Gap |
|----------|---------|----------|-----|
| Packet size | 188 bytes | 188 bytes | OK |
| PAT | Present | Present | OK |
| PMT | Present | Present, correct stream_type | OK (fixed — was broken by av_new_program) |
| PCR | 20ms interval | ~40ms interval | OK (more frequent is fine) |
| Stream type (video) | 0x1B (H.264) | 0x1B or 0x02 | OK |
| Stream type (audio) | 0x0F (AAC) | 0x81 (AC-3) or 0x0F | OK |
| Mux rate | 10 Mbps CBR | VBR (passthrough) | OK — CBR with null packets is valid |
| service_name | "Channel {id}" | Not typically set | OK — harmless |
| service_provider | "RetroVue" | Not typically set | OK — harmless |

---

## 4. EPG / Guide Data

### 4.1 XMLTV

Plex supports XMLTV guide data provided as a URL during DVR setup.
RetroVue should serve XMLTV at a stable URL (e.g. `/xmltv.xml`).

Channel matching: Plex matches XMLTV `<channel>` entries to `lineup.json`
entries by comparing `<display-name>` against `GuideNumber` and `GuideName`.

**Status:** RetroVue serves EPG via `/api/epg` (JSON) but may not serve XMLTV.
**Gap:** Need to verify XMLTV endpoint exists and is properly formatted.

---

## 5. Compliance Summary

### Must Fix (stream/playback impact)

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| 1 | `Manufacturer` → "Silicondust" | Plex device capability detection | P1 |
| 2 | Add `ModelNumber`, `FirmwareName`, `FirmwareVersion` | Plex identifies device type | P1 |
| 3 | `DeviceAuth` → non-empty | May cause auth issues | P1 |
| 4 | `BaseURL` / lineup URLs → external IP | Plex can't reach localhost | P1 |
| 5 | `Content-Type` → `video/mpeg` | Match HDHomeRun exactly | P2 |
| 6 | Add `HD: 1` to lineup entries | Channel metadata | P2 |

### Should Add (completeness)

| # | Gap | Impact | Priority |
|---|-----|--------|----------|
| 7 | `POST /lineup.post` endpoint | Channel scan during DVR setup | P2 |
| 8 | `GET /device.xml` endpoint | SSDP auto-discovery | P3 |
| 9 | XMLTV endpoint at stable URL | Guide data for Plex | P2 |

### No Change Needed

| Property | Status |
|----------|--------|
| Stream URL pattern | OK (Plex reads from lineup.json) |
| Transfer-Encoding: chunked | OK (matches HDHomeRun) |
| lineup_status.json | OK |
| PAT/PMT structure | OK |
| PCR interval | OK |
| H.264 video codec | OK |
| AAC audio codec | OK (Plex stream-copies it) |
| Mux rate (10 Mbps CBR) | OK |
| GOP size (90) | OK |
| flush_packets | OK |

---

## 6. Invariant Rules

**INV-HDHOMERUN-COMPAT-001-R1:** `/discover.json` MUST return `Manufacturer: "Silicondust"` and include `ModelNumber`, `FirmwareName`, `FirmwareVersion` fields.

**INV-HDHOMERUN-COMPAT-001-R2:** `BaseURL` and all URLs in `lineup.json` MUST use the server's externally-reachable IP address, never `localhost` or `127.0.0.1`.

**INV-HDHOMERUN-COMPAT-001-R3:** Stream responses MUST use `Content-Type: video/mpeg` and `Transfer-Encoding: chunked`.

**INV-HDHOMERUN-COMPAT-001-R4:** PMT stream_type values MUST correctly identify the elementary streams (0x1B for H.264, 0x0F for AAC). MUST NOT use `av_new_program()` which overwrites stream_type to 0.

**INV-HDHOMERUN-COMPAT-001-R5:** `POST /lineup.post` MUST return `200 OK` (no-op implementation acceptable).

**INV-HDHOMERUN-COMPAT-001-R6:** Encoder settings MUST NOT be changed without validating playback in ffplay, VLC, AND Plex Live TV (phone + tablet + browser).

---

## 7. Validation

After implementation, verify:

1. `curl http://<ip>:8000/discover.json` — contains Manufacturer, ModelNumber, FirmwareName
2. `curl http://<ip>:8000/lineup.json` — URLs use external IP, HD field present
3. `curl -X POST http://<ip>:8000/lineup.post` — returns 200
4. `ffplay http://<ip>:8000/channel/hbo.ts` — plays immediately, no PPS errors after first keyframe
5. `vlc http://<ip>:8000/channel/hbo.ts` — plays immediately, timer increments
6. Plex DVR setup — detects device, scans channels, tunes successfully
7. Plex Live TV on Android — plays within 5 seconds
8. Plex Live TV on browser — plays within 5 seconds
