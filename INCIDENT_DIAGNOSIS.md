# Incident Diagnosis: legacy switch RPC result_code=4 (PROTOCOL_VIOLATION)

**Result code 4** = `RESULT_CODE_PROTOCOL_VIOLATION` — "Caller violated the protocol (e.g., legacy switch RPC without legacy preload RPC)"

**Proto:** `protos/playout.proto` enum `ResultCode`  
**Source:** Air returns this when `PlayoutEngine::legacy switch RPC()` detects a protocol violation.

---

## 1. Top Plausible Causes

| # | Cause | Likelihood | Description |
|---|-------|------------|-------------|
| 1 | **legacy switch RPC without legacy preload RPC** | High | Core issued legacy switch RPC before legacy preload RPC, or never issued legacy preload RPC for this channel. PE-CTL-002: legacy switch RPC with no preview loaded → error. |
| 2 | **legacy preload RPC failed; Core proceeded anyway** | High | Core called legacy preload RPC (invalid path, channel not started, etc.); legacy preload RPC returned success=false; Core did not check and issued legacy switch RPC. |
| 3 | **legacy preload RPC not yet received** | Medium | Core sent legacy preload RPC but Air never received it (gRPC dropped, wrong endpoint, channel_id mismatch). Core then issued legacy switch RPC. |
| 4 | **Channel_id mismatch** | Medium | Core issued legacy preload RPC for channel A and legacy switch RPC for channel B (or wrong channel_id in one call). |
| 5 | **Preview cleared between legacy preload RPC and legacy switch RPC** | Low | legacy preload RPC succeeded; before legacy switch RPC, something cleared preview_producer (e.g. INV-P8-SWITCH-ARMED FATAL path, or internal bug). |
| 6 | **INV-P8-SWITCH-ARMED FATAL** | Low | legacy preload RPC reached buffer/producer reset code while switch was armed. Returns PROTOCOL_VIOLATION. (This is legacy preload RPC, not legacy switch RPC — different RPC.) |

**Primary code path for legacy switch RPC result_code=4:** `PlayoutEngine.cpp` line 831–835:

```cpp
if (!state->preview_producer) {
  EngineResult result(false, "No preview producer loaded for channel " + std::to_string(channel_id));
  result.result_code = ResultCode::kProtocolViolation;
  return result;
}
```

---

## 2. What Air Must Log to Confirm/Deny Each Cause

| Cause | Air logs that CONFIRM | Air logs that DENY |
|-------|------------------------|--------------------|
| **1. legacy switch RPC without legacy preload RPC** | No `AIR-LOADPREVIEW-RECEIVED` (or `AIR-LOADPREVIEW-RESPONSE success=true`) for this channel before `AIR-SWITCHTOLIVE-RECEIVED` | `AIR-LOADPREVIEW-RESPONSE` with success=true and same channel_id, timestamp before legacy switch RPC |
| **2. legacy preload RPC failed; Core proceeded** | `AIR-LOADPREVIEW-RESPONSE` with success=false, result_code≠OK for this channel; `AIR-SWITCHTOLIVE-RECEIVED` later | `AIR-LOADPREVIEW-RESPONSE` with success=true |
| **3. legacy preload RPC not yet received** | No `AIR-LOADPREVIEW-RECEIVED` for this channel_id in log window | `AIR-LOADPREVIEW-RECEIVED` with matching channel_id before legacy switch RPC |
| **4. Channel_id mismatch** | `AIR-LOADPREVIEW-RECEIVED` for channel_id=X; `AIR-SWITCHTOLIVE-RECEIVED` for channel_id=Y (X≠Y) | Same channel_id in both legacy preload RPC and legacy switch RPC |
| **5. Preview cleared between calls** | `AIR-LOADPREVIEW-RESPONSE success=true`; later `AIR-SWITCHTOLIVE-RECEIVED`; no intermediate legacy preload RPC or FATAL | No evidence of preview clear; or INV-P8-SWITCH-ARMED FATAL between them |
| **6. INV-P8-SWITCH-ARMED FATAL** | `[legacy preload RPC] FATAL: INV-P8-SWITCH-ARMED violated` (legacy preload RPC returns PROTOCOL_VIOLATION) | N/A — this is legacy preload RPC, not legacy switch RPC |

---

## 3. Minimal New Air Log Events/Fields Needed

See **LOGGING_DELTA_SPEC.md** for full specification. Summary:

| Event | Purpose |
|-------|---------|
| `AIR-SWITCHTOLIVE-RECEIVED` | Intent parity; proves legacy switch RPC was received |
| `AIR-SWITCHTOLIVE-RESPONSE` | Result parity; includes result_code, correlation_id |
| `AIR-LOADPREVIEW-RECEIVED` | Proves legacy preload RPC was received (or not) before legacy switch RPC |
| `AIR-LOADPREVIEW-RESPONSE` | Proves legacy preload RPC succeeded or failed |
| **`AIR-PROTOCOL-VIOLATION-DIAG**` | **New:** Emitted when legacy switch RPC returns PROTOCOL_VIOLATION; includes `violation_reason`, `preview_loaded`, `preview_producer_null`, `last_loadpreview_correlation_id` |

---

## 4. Mapping to Observability Parity Law

| Law ID | Requirement | Current gap for result_code=4 diagnosis |
|--------|-------------|----------------------------------------|
| LAW-OBS-001 | Intent parity: every intent observable | No structured `AIR-SWITCHTOLIVE-RECEIVED`; only ad-hoc `[legacy switch RPC] Request received` |
| LAW-OBS-002 | Correlation: correlation_id in Core and Air | No correlation_id on requests; cannot correlate legacy preload RPC ↔ legacy switch RPC |
| LAW-OBS-003 | Result parity: every response logged with correlation_id | `[legacy switch RPC] Channel X switch not complete (result_code=4)` exists but lacks correlation_id, structured fields |
| LAW-OBS-004 | Timing evidence | No receipt_time_ms, completion_time_ms in structured form |
| LAW-OBS-005 | Boundary evidence | N/A for PROTOCOL_VIOLATION (clamp-specific) |

---

## 5. Mapping to PlayoutEngineContract Sections

| Section | Requirement | Gap |
|---------|-------------|-----|
| Part 2.5 Required Log Events | AIR-SWITCHTOLIVE-RECEIVED, AIR-SWITCHTOLIVE-RESPONSE with channel_id, correlation_id, result_code, receipt_time_ms, completion_time_ms | Events not implemented; no correlation_id |
| Part 2.5 Required Fields | correlation_id, result_code, channel_id on all intent/response events | Not logged in structured form |
| §legacy switch RPC PE-CTL-002 | legacy switch RPC with no preview loaded → error | Contract satisfied; logs insufficient to diagnose *why* preview missing |

---

## 6. Tests That Should Fail Until Logs Exist

| Test | File | What it should assert | Current status |
|------|------|------------------------|----------------|
| **OBS-STL-001** | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` (new) | When legacy switch RPC returns result_code=4, captured logs contain `AIR-SWITCHTOLIVE-RESPONSE` with result_code=PROTOCOL_VIOLATION and `AIR-PROTOCOL-VIOLATION-DIAG` with violation_reason, preview_loaded=false | **Missing** (no log capture) |
| **OBS-STL-002** | same | When legacy switch RPC returns result_code=4 after legacy preload RPC never sent, captured logs show no `AIR-LOADPREVIEW-RECEIVED` for that channel before `AIR-SWITCHTOLIVE-RECEIVED` | **Missing** |
| **OBS-STL-003** | same | When legacy preload RPC fails and Core sends legacy switch RPC, captured logs show `AIR-LOADPREVIEW-RESPONSE success=false` and `AIR-SWITCHTOLIVE-RESPONSE result_code=4` with correlation_ids linking both calls | **Missing** |
| **Phase6A0_legacy switch RPCWithNoPreview_Error** | PlayoutEngineContractTests.cpp | **Extend:** Assert captured log contains AIR-SWITCHTOLIVE-RESPONSE with result_code=4 and AIR-PROTOCOL-VIOLATION-DIAG | **Partial** (asserts gRPC response only) |

---

## 7. Recommended Investigation Steps (with current logs)

1. **Search Air logs** for `[legacy switch RPC]` and `[legacy preload RPC]` around the incident timestamp.
2. **Check sequence:** Was `[legacy preload RPC] Request received` for the same channel_id before `[legacy switch RPC] Request received`?
3. **Check legacy preload RPC outcome:** Did `[legacy preload RPC] Channel X preview loaded successfully` appear, or `preview load failed`?
4. **Check channel_id:** Are legacy preload RPC and legacy switch RPC using the same channel_id?
5. **Check for FATAL:** Any `[legacy preload RPC] FATAL: INV-P8-SWITCH-ARMED violated`?

**Blocker:** Without correlation_id, timestamps, and structured event names, correlating Core and Air logs across a multi-channel or high-throughput run is unreliable. Implementing LOGGING_DELTA_SPEC.md is prerequisite for reliable root-cause analysis.
