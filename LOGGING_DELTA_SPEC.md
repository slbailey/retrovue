# Logging Delta Spec

**Purpose:** Minimal new Air log events and fields required to diagnose SwitchToLive result_code=4 (PROTOCOL_VIOLATION) and satisfy Observability Parity Law.  
**Traceability:** INCIDENT_DIAGNOSIS.md · ObservabilityParityLaw.md · PlayoutEngineContract.md Part 2.5

---

## 1. Event Catalog (New / Delta)

Events marked **NEW** are not yet in ObservabilityParityLaw or PlayoutEngineContract. Events marked **DELTA** extend existing specs with additional fields.

### 1.1 SwitchToLive (Primary for result_code=4)

| Event | Status | When emitted | Required fields |
|-------|--------|--------------|-----------------|
| `AIR-SWITCHTOLIVE-RECEIVED` | DELTA (add structured) | On entry to SwitchToLive gRPC handler | channel_id, correlation_id, receipt_time_ms |
| `AIR-SWITCHTOLIVE-RESPONSE` | DELTA (add structured) | Before returning SwitchToLive response | channel_id, correlation_id, success, result_code, message, completion_time_ms |
| `AIR-PROTOCOL-VIOLATION-DIAG` | **NEW** | When SwitchToLive returns result_code=PROTOCOL_VIOLATION | channel_id, correlation_id, violation_reason, preview_loaded, preview_producer_null, last_loadpreview_correlation_id (if any) |

### 1.2 LoadPreview (Needed for Cause Correlation)

| Event | Status | When emitted | Required fields |
|-------|--------|--------------|-----------------|
| `AIR-LOADPREVIEW-RECEIVED` | DELTA (add structured) | On entry to LoadPreview gRPC handler | channel_id, correlation_id, asset_path, receipt_time_ms |
| `AIR-LOADPREVIEW-RESPONSE` | DELTA (add structured) | Before returning LoadPreview response | channel_id, correlation_id, success, result_code, message, completion_time_ms |

### 1.3 StartChannel (Context)

| Event | Status | When emitted | Required fields |
|-------|--------|--------------|-----------------|
| `AIR-STARTCHANNEL-RECEIVED` | DELTA (add structured) | On entry to StartChannel gRPC handler | channel_id, correlation_id, receipt_time_ms |
| `AIR-STARTCHANNEL-RESPONSE` | DELTA (add structured) | Before returning StartChannel response | channel_id, correlation_id, success, result_code, completion_time_ms |

---

## 2. Field Specifications

### 2.1 Common Fields

| Field | Type | Required for | Description |
|-------|------|--------------|-------------|
| `channel_id` | int32 | All | Target channel |
| `correlation_id` | string | All receive/response | From gRPC metadata `x-retrovue-correlation-id` or proto; opaque string |
| `receipt_time_ms` | int64 | All *-RECEIVED | Epoch ms when handler invoked |
| `completion_time_ms` | int64 | All *-RESPONSE | Epoch ms when handler returns |
| `result_code` | string | All *-RESPONSE | RESULT_CODE_OK, RESULT_CODE_PROTOCOL_VIOLATION, etc. |
| `success` | bool | All *-RESPONSE | Response success flag |
| `message` | string | *-RESPONSE when present | Error or status message |

### 2.2 AIR-PROTOCOL-VIOLATION-DIAG (New)

| Field | Type | Description |
|-------|------|-------------|
| `channel_id` | int32 | Channel that received SwitchToLive |
| `correlation_id` | string | Correlation ID of the SwitchToLive call |
| `violation_reason` | string | Human-readable: "NO_PREVIEW_PRODUCER", "INV_P8_SWITCH_ARMED_FATAL", etc. |
| `preview_loaded` | bool | state->preview_loaded at time of check |
| `preview_producer_null` | bool | state->preview_producer == nullptr |
| `last_loadpreview_correlation_id` | string | If LoadPreview was received for this channel, its correlation_id; else empty |
| `switch_in_progress` | bool | state->switch_in_progress (for INV-P8-SWITCH-ARMED context) |

---

## 3. Sample Log Lines

### 3.1 Happy Path (SwitchToLive succeeds)

```
[AIR] AIR-STARTCHANNEL-RECEIVED channel_id=3 correlation_id=ch3-sc1-1738340100000 receipt_time_ms=1738340100002
[AIR] AIR-STARTCHANNEL-RESPONSE channel_id=3 correlation_id=ch3-sc1-1738340100000 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340100005
[AIR] AIR-LOADPREVIEW-RECEIVED channel_id=3 correlation_id=ch3-lp1-1738340123000 asset_path=/opt/retrovue/assets/SampleB.mp4 receipt_time_ms=1738340123002
[AIR] AIR-LOADPREVIEW-RESPONSE channel_id=3 correlation_id=ch3-lp1-1738340123000 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340123025
[AIR] AIR-SWITCHTOLIVE-RECEIVED channel_id=3 correlation_id=ch3-stl1-1738340223000 receipt_time_ms=1738340223002
[AIR] AIR-SWITCHTOLIVE-RESPONSE channel_id=3 correlation_id=ch3-stl1-1738340223000 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340223015
```

### 3.2 SwitchToLive result_code=4 — No LoadPreview

```
[AIR] AIR-STARTCHANNEL-RECEIVED channel_id=3 correlation_id=ch3-sc1-1738340100000 receipt_time_ms=1738340100002
[AIR] AIR-STARTCHANNEL-RESPONSE channel_id=3 correlation_id=ch3-sc1-1738340100000 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340100005
[AIR] AIR-SWITCHTOLIVE-RECEIVED channel_id=3 correlation_id=ch3-stl1-1738340150000 receipt_time_ms=1738340150002
[AIR] AIR-PROTOCOL-VIOLATION-DIAG channel_id=3 correlation_id=ch3-stl1-1738340150000 violation_reason=NO_PREVIEW_PRODUCER preview_loaded=false preview_producer_null=true last_loadpreview_correlation_id= switch_in_progress=false
[AIR] AIR-SWITCHTOLIVE-RESPONSE channel_id=3 correlation_id=ch3-stl1-1738340150000 success=false result_code=RESULT_CODE_PROTOCOL_VIOLATION message="No preview producer loaded for channel 3" completion_time_ms=1738340150003
```

### 3.3 SwitchToLive result_code=4 — LoadPreview Failed Earlier

```
[AIR] AIR-STARTCHANNEL-RECEIVED channel_id=3 correlation_id=ch3-sc1-1738340100000 receipt_time_ms=1738340100002
[AIR] AIR-STARTCHANNEL-RESPONSE channel_id=3 correlation_id=ch3-sc1-1738340100000 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340100005
[AIR] AIR-LOADPREVIEW-RECEIVED channel_id=3 correlation_id=ch3-lp1-1738340123000 asset_path=/nonexistent/video.mp4 receipt_time_ms=1738340123002
[AIR] AIR-LOADPREVIEW-RESPONSE channel_id=3 correlation_id=ch3-lp1-1738340123000 success=false result_code=RESULT_CODE_FAILED message="Invalid path" completion_time_ms=1738340123010
[AIR] AIR-SWITCHTOLIVE-RECEIVED channel_id=3 correlation_id=ch3-stl1-1738340123500 receipt_time_ms=1738340123502
[AIR] AIR-PROTOCOL-VIOLATION-DIAG channel_id=3 correlation_id=ch3-stl1-1738340123500 violation_reason=NO_PREVIEW_PRODUCER preview_loaded=false preview_producer_null=true last_loadpreview_correlation_id=ch3-lp1-1738340123000 switch_in_progress=false
[AIR] AIR-SWITCHTOLIVE-RESPONSE channel_id=3 correlation_id=ch3-stl1-1738340123500 success=false result_code=RESULT_CODE_PROTOCOL_VIOLATION message="No preview producer loaded for channel 3" completion_time_ms=1738340123505
```

### 3.4 LoadPreview INV-P8-SWITCH-ARMED FATAL (LoadPreview returns PROTOCOL_VIOLATION)

```
[AIR] AIR-LOADPREVIEW-RECEIVED channel_id=3 correlation_id=ch3-lp2-1738340200000 asset_path=/opt/retrovue/assets/SampleC.mp4 receipt_time_ms=1738340200002
[AIR] AIR-PROTOCOL-VIOLATION-DIAG channel_id=3 correlation_id=ch3-lp2-1738340200000 violation_reason=INV_P8_SWITCH_ARMED_FATAL preview_loaded=true preview_producer_null=false last_loadpreview_correlation_id=ch3-lp1-1738340123000 switch_in_progress=true
[AIR] AIR-LOADPREVIEW-RESPONSE channel_id=3 correlation_id=ch3-lp2-1738340200000 success=false result_code=RESULT_CODE_PROTOCOL_VIOLATION message="FATAL: INV-P8-SWITCH-ARMED violated" completion_time_ms=1738340200005
```

---

## 4. Log Format Convention

- **Prefix:** `[AIR]` for machine parsing and grep.
- **Event name:** Uppercase with hyphens, e.g. `AIR-SWITCHTOLIVE-RECEIVED`.
- **Key=value pairs:** Space-separated; values with spaces must be quoted.
- **Timestamp:** All times in epoch milliseconds (UTC).
- **Structured alternative:** JSON lines (`{"event":"AIR-SWITCHTOLIVE-RECEIVED","channel_id":3,...}`) if log aggregation supports it.

---

## 5. Implementation Notes

1. **Correlation ID:** Core MUST send `x-retrovue-correlation-id` in gRPC metadata. If missing, Air generates one (e.g. `air-gen-{channel_id}-{timestamp_ms}`) and logs it; diagnostic value is reduced for cross-component correlation.
2. **AIR-PROTOCOL-VIOLATION-DIAG:** Emit immediately before returning the PROTOCOL_VIOLATION response. Do not emit for other result codes.
3. **last_loadpreview_correlation_id:** Requires Air to track the most recent LoadPreview correlation_id per channel. Set when LoadPreview is received; clear when preview is cleared or channel stopped.
4. **Performance:** Logging MUST NOT block the gRPC handler. Use async or fire-and-forget if necessary.

---

## 6. Mapping to Observability Parity Law

| Law ID | Spec section | Implementation |
|--------|--------------|----------------|
| LAW-OBS-001 | §1.1, §1.2, §1.3 RECEIVED events | Emit *-RECEIVED on handler entry |
| LAW-OBS-002 | All events: correlation_id | Extract from metadata; generate if missing |
| LAW-OBS-003 | §1.1, §1.2, §1.3 RESPONSE events | Emit *-RESPONSE before return with result_code |
| LAW-OBS-004 | receipt_time_ms, completion_time_ms | Capture on entry and before return |
| LAW-OBS-005 | N/A for PROTOCOL_VIOLATION | Clamp events unchanged |

---

## 7. Mapping to PlayoutEngineContract Part 2.5

| Contract event | Spec event | Notes |
|----------------|------------|-------|
| AIR-STARTCHANNEL-RECEIVED | §1.3 | Same |
| AIR-STARTCHANNEL-RESPONSE | §1.3 | Same |
| AIR-LOADPREVIEW-RECEIVED | §1.2 | Same |
| AIR-LOADPREVIEW-RESPONSE | §1.2 | Same |
| AIR-LOADPREVIEW-EFFECTIVE | (unchanged) | When preview installed |
| AIR-SWITCHTOLIVE-RECEIVED | §1.1 | Same |
| AIR-SWITCHTOLIVE-RESPONSE | §1.1 | Same |
| AIR-SWITCHTOLIVE-EFFECTIVE | (unchanged) | When switch committed |
| AIR-PROTOCOL-VIOLATION-DIAG | **NEW** | Add to Part 2.5 as diagnostic extension |

---

## 8. Tests That Should Fail Until Logs Exist

| Test ID | Assertion | Blocks |
|---------|-----------|--------|
| OBS-STL-001 | SwitchToLive result_code=4 → AIR-SWITCHTOLIVE-RESPONSE and AIR-PROTOCOL-VIOLATION-DIAG in logs | LOGGING_DELTA_SPEC implementation |
| OBS-STL-002 | No LoadPreview before SwitchToLive → last_loadpreview_correlation_id empty in AIR-PROTOCOL-VIOLATION-DIAG | LOGGING_DELTA_SPEC implementation |
| OBS-STL-003 | LoadPreview failed before SwitchToLive → last_loadpreview_correlation_id matches failed LoadPreview | LOGGING_DELTA_SPEC implementation |
| Phase6A0_SwitchToLiveWithNoPreview_Error | Extend: captured log contains AIR-PROTOCOL-VIOLATION-DIAG | Log capture harness |
