# Incident Diagnosis: SwitchToLive result_code=4 (PROTOCOL_VIOLATION)

**Result code 4** = `RESULT_CODE_PROTOCOL_VIOLATION` — "Caller violated the protocol (e.g., SwitchToLive without LoadPreview)"

**Proto:** `protos/playout.proto` enum `ResultCode`  
**Source:** Air returns this when `PlayoutEngine::SwitchToLive()` detects a protocol violation.

---

## 1. Top Plausible Causes

| # | Cause | Likelihood | Description |
|---|-------|------------|-------------|
| 1 | **SwitchToLive without LoadPreview** | High | Core issued SwitchToLive before LoadPreview, or never issued LoadPreview for this channel. PE-CTL-002: SwitchToLive with no preview loaded → error. |
| 2 | **LoadPreview failed; Core proceeded anyway** | High | Core called LoadPreview (invalid path, channel not started, etc.); LoadPreview returned success=false; Core did not check and issued SwitchToLive. |
| 3 | **LoadPreview not yet received** | Medium | Core sent LoadPreview but Air never received it (gRPC dropped, wrong endpoint, channel_id mismatch). Core then issued SwitchToLive. |
| 4 | **Channel_id mismatch** | Medium | Core issued LoadPreview for channel A and SwitchToLive for channel B (or wrong channel_id in one call). |
| 5 | **Preview cleared between LoadPreview and SwitchToLive** | Low | LoadPreview succeeded; before SwitchToLive, something cleared preview_producer (e.g. INV-P8-SWITCH-ARMED FATAL path, or internal bug). |
| 6 | **INV-P8-SWITCH-ARMED FATAL** | Low | LoadPreview reached buffer/producer reset code while switch was armed. Returns PROTOCOL_VIOLATION. (This is LoadPreview, not SwitchToLive — different RPC.) |

**Primary code path for SwitchToLive result_code=4:** `PlayoutEngine.cpp` line 831–835:

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
| **1. SwitchToLive without LoadPreview** | No `AIR-LOADPREVIEW-RECEIVED` (or `AIR-LOADPREVIEW-RESPONSE success=true`) for this channel before `AIR-SWITCHTOLIVE-RECEIVED` | `AIR-LOADPREVIEW-RESPONSE` with success=true and same channel_id, timestamp before SwitchToLive |
| **2. LoadPreview failed; Core proceeded** | `AIR-LOADPREVIEW-RESPONSE` with success=false, result_code≠OK for this channel; `AIR-SWITCHTOLIVE-RECEIVED` later | `AIR-LOADPREVIEW-RESPONSE` with success=true |
| **3. LoadPreview not yet received** | No `AIR-LOADPREVIEW-RECEIVED` for this channel_id in log window | `AIR-LOADPREVIEW-RECEIVED` with matching channel_id before SwitchToLive |
| **4. Channel_id mismatch** | `AIR-LOADPREVIEW-RECEIVED` for channel_id=X; `AIR-SWITCHTOLIVE-RECEIVED` for channel_id=Y (X≠Y) | Same channel_id in both LoadPreview and SwitchToLive |
| **5. Preview cleared between calls** | `AIR-LOADPREVIEW-RESPONSE success=true`; later `AIR-SWITCHTOLIVE-RECEIVED`; no intermediate LoadPreview or FATAL | No evidence of preview clear; or INV-P8-SWITCH-ARMED FATAL between them |
| **6. INV-P8-SWITCH-ARMED FATAL** | `[LoadPreview] FATAL: INV-P8-SWITCH-ARMED violated` (LoadPreview returns PROTOCOL_VIOLATION) | N/A — this is LoadPreview, not SwitchToLive |

---

## 3. Minimal New Air Log Events/Fields Needed

See **LOGGING_DELTA_SPEC.md** for full specification. Summary:

| Event | Purpose |
|-------|---------|
| `AIR-SWITCHTOLIVE-RECEIVED` | Intent parity; proves SwitchToLive was received |
| `AIR-SWITCHTOLIVE-RESPONSE` | Result parity; includes result_code, correlation_id |
| `AIR-LOADPREVIEW-RECEIVED` | Proves LoadPreview was received (or not) before SwitchToLive |
| `AIR-LOADPREVIEW-RESPONSE` | Proves LoadPreview succeeded or failed |
| **`AIR-PROTOCOL-VIOLATION-DIAG**` | **New:** Emitted when SwitchToLive returns PROTOCOL_VIOLATION; includes `violation_reason`, `preview_loaded`, `preview_producer_null`, `last_loadpreview_correlation_id` |

---

## 4. Mapping to Observability Parity Law

| Law ID | Requirement | Current gap for result_code=4 diagnosis |
|--------|-------------|----------------------------------------|
| LAW-OBS-001 | Intent parity: every intent observable | No structured `AIR-SWITCHTOLIVE-RECEIVED`; only ad-hoc `[SwitchToLive] Request received` |
| LAW-OBS-002 | Correlation: correlation_id in Core and Air | No correlation_id on requests; cannot correlate LoadPreview ↔ SwitchToLive |
| LAW-OBS-003 | Result parity: every response logged with correlation_id | `[SwitchToLive] Channel X switch not complete (result_code=4)` exists but lacks correlation_id, structured fields |
| LAW-OBS-004 | Timing evidence | No receipt_time_ms, completion_time_ms in structured form |
| LAW-OBS-005 | Boundary evidence | N/A for PROTOCOL_VIOLATION (clamp-specific) |

---

## 5. Mapping to PlayoutEngineContract Sections

| Section | Requirement | Gap |
|---------|-------------|-----|
| Part 2.5 Required Log Events | AIR-SWITCHTOLIVE-RECEIVED, AIR-SWITCHTOLIVE-RESPONSE with channel_id, correlation_id, result_code, receipt_time_ms, completion_time_ms | Events not implemented; no correlation_id |
| Part 2.5 Required Fields | correlation_id, result_code, channel_id on all intent/response events | Not logged in structured form |
| §SwitchToLive PE-CTL-002 | SwitchToLive with no preview loaded → error | Contract satisfied; logs insufficient to diagnose *why* preview missing |

---

## 6. Tests That Should Fail Until Logs Exist

| Test | File | What it should assert | Current status |
|------|------|------------------------|----------------|
| **OBS-STL-001** | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` (new) | When SwitchToLive returns result_code=4, captured logs contain `AIR-SWITCHTOLIVE-RESPONSE` with result_code=PROTOCOL_VIOLATION and `AIR-PROTOCOL-VIOLATION-DIAG` with violation_reason, preview_loaded=false | **Missing** (no log capture) |
| **OBS-STL-002** | same | When SwitchToLive returns result_code=4 after LoadPreview never sent, captured logs show no `AIR-LOADPREVIEW-RECEIVED` for that channel before `AIR-SWITCHTOLIVE-RECEIVED` | **Missing** |
| **OBS-STL-003** | same | When LoadPreview fails and Core sends SwitchToLive, captured logs show `AIR-LOADPREVIEW-RESPONSE success=false` and `AIR-SWITCHTOLIVE-RESPONSE result_code=4` with correlation_ids linking both calls | **Missing** |
| **Phase6A0_SwitchToLiveWithNoPreview_Error** | PlayoutEngineContractTests.cpp | **Extend:** Assert captured log contains AIR-SWITCHTOLIVE-RESPONSE with result_code=4 and AIR-PROTOCOL-VIOLATION-DIAG | **Partial** (asserts gRPC response only) |

---

## 7. Recommended Investigation Steps (with current logs)

1. **Search Air logs** for `[SwitchToLive]` and `[LoadPreview]` around the incident timestamp.
2. **Check sequence:** Was `[LoadPreview] Request received` for the same channel_id before `[SwitchToLive] Request received`?
3. **Check LoadPreview outcome:** Did `[LoadPreview] Channel X preview loaded successfully` appear, or `preview load failed`?
4. **Check channel_id:** Are LoadPreview and SwitchToLive using the same channel_id?
5. **Check for FATAL:** Any `[LoadPreview] FATAL: INV-P8-SWITCH-ARMED violated`?

**Blocker:** Without correlation_id, timestamps, and structured event names, correlating Core and Air logs across a multi-channel or high-throughput run is unreliable. Implementing LOGGING_DELTA_SPEC.md is prerequisite for reliable root-cause analysis.
