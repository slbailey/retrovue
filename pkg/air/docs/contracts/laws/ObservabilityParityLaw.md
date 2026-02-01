# Observability Parity Law

**Status:** Canonical  
**Scope:** Cross-component (Core → Air); enforcement primary in Air  
**Audience:** Implementers, SRE, contract authors

This law ensures that every control-plane intent and its outcome can be traced across Core and Air logs. Root-cause analysis of switching, hard-stop, or prefeed failures MUST NOT require guessing; logs MUST provide a complete, correlated transcript.

**Single source of truth:** This document. Link from Core's ChannelManagerContract, main docs, and INVARIANTS-INDEX.

_Related: [PlayoutInvariants-BroadcastGradeGuarantees](PlayoutInvariants-BroadcastGradeGuarantees.md) · [PlayoutEngineContract](../semantics/PlayoutEngineContract.md) · [ProducerBusContract](../coordination/ProducerBusContract.md)_

---

## 1. Law Statements

### LAW-OBS-001: Intent Parity

Every control-plane intent that Core issues and that affects playout MUST be observable in Air logs.

- Core issues intents via gRPC: `StartChannel`, `LoadPreview`, `SwitchToLive`, `UpdatePlan`, `StopChannel`, `AttachStream`, `DetachStream`.
- Air MUST log receipt of each intent with sufficient context to reproduce the call.
- Omission of any intent from Air logs is a violation.

---

### LAW-OBS-002: Correlation

Every intent MUST carry a correlation ID that appears in both Core and Air logs.

- Core MUST attach a `correlation_id` to each gRPC call (e.g. gRPC metadata key `x-retrovue-correlation-id` or a proto field when extended).
- The same `correlation_id` MUST appear in Core's "issued" log and Air's "received" and "response" logs for that call.
- Correlation IDs MUST be unique per call (not per channel or per session).
- Format: implementation-defined; MUST be loggable as a single opaque string (e.g. UUID, `{channel_id}-{seq}-{timestamp_ms}`).

---

### LAW-OBS-003: Result Parity

Every Air response (success/failure + result_code) MUST be logged in Air with the correlation ID.

- Air MUST log each gRPC response before returning it to Core.
- Log MUST include: `correlation_id`, `success`, `result_code` (or equivalent), and `message` when present.
- Transient states (e.g. NOT_READY) MUST be logged; they are not errors but must be observable for debugging.

---

### LAW-OBS-004: Timing Evidence

Air MUST log receipt time, effective time (if scheduled), and completion time for LoadPreview and SwitchToLive.

| RPC | Receipt time | Effective time | Completion time |
|-----|--------------|----------------|-----------------|
| LoadPreview | When gRPC handler is invoked | When segment is installed into preview (or N/A if immediate) | When handler returns |
| SwitchToLive | When gRPC handler is invoked | When switch is committed (preview promoted to live) | When handler returns |

- All times MUST be in a consistent format (e.g. epoch ms or ISO 8601).
- Receipt and completion times are mandatory. Effective time is mandatory when the operation is scheduled or deferred (e.g. switch committed after buffer readiness).

---

### LAW-OBS-005: Boundary Evidence

Hard-stop clamp behavior MUST produce explicit logs.

- When a producer reaches its hard-stop boundary and Air clamps output (stops emitting frames from that producer), Air MUST log:
  1. **Clamp started:** The moment output is clamped for that segment.
  2. **Clamp active:** Optional periodic heartbeat if clamp lasts > threshold (e.g. 1s).
  3. **Clamp ended:** When Core issues the next intent (e.g. SwitchToLive) and clamp is released.

- Logs MUST include: `channel_id`, `asset_path` (or segment id), `boundary_ms`, `correlation_id` (of the LoadPreview that established the segment).

---

## 2. Required Log Event Catalog

| Event | Required fields | When emitted |
|-------|-----------------|--------------|
| `AIR-INTENT-RECEIVED` | `correlation_id`, `rpc`, `channel_id`, `receipt_time_ms`, `asset_path` (LoadPreview), `start_frame`, `frame_count` (LoadPreview) | On entry to each gRPC handler |
| `AIR-INTENT-RESPONSE` | `correlation_id`, `rpc`, `channel_id`, `success`, `result_code`, `message`, `completion_time_ms` | Before returning each gRPC response |
| `AIR-LOADPREVIEW-EFFECTIVE` | `correlation_id`, `channel_id`, `asset_path`, `effective_time_ms` | When preview segment is installed (shadow decode ready or equivalent) |
| `AIR-SWITCHTOLIVE-EFFECTIVE` | `correlation_id`, `channel_id`, `effective_time_ms` | When switch is committed (preview promoted to live) |
| `AIR-CLAMP-STARTED` | `correlation_id`, `channel_id`, `asset_path`, `boundary_ms`, `segment_correlation_id` | When producer reaches hard stop and output is clamped |
| `AIR-CLAMP-ACTIVE` | `channel_id`, `asset_path`, `boundary_ms`, `clamp_duration_ms` | Optional; when clamp exceeds threshold (e.g. 1s) |
| `AIR-CLAMP-ENDED` | `channel_id`, `asset_path`, `boundary_ms`, `next_correlation_id` | When SwitchToLive (or next LoadPreview) ends clamp |

---

## 3. Core Obligations (prerequisite)

Core MUST:

- Attach `correlation_id` to every gRPC call (metadata or proto).
- Log each intent before issuing: event `CORE-INTENT-ISSUED` with `correlation_id`, `rpc`, `channel_id`, `issued_time_ms`, and relevant args.
- Use unique correlation IDs per call.

---

## 4. Example: Correlated Transcript for a Switch

```
# Core (ChannelManager)
[CORE] CORE-INTENT-ISSUED correlation_id=ch1-sw42-1738340123456 rpc=LoadPreview channel_id=1 asset_path=/media/ep2.mp4 start_frame=0 frame_count=1800 issued_time_ms=1738340123456

[CORE] CORE-INTENT-ISSUED correlation_id=ch1-sw43-1738340153456 rpc=SwitchToLive channel_id=1 issued_time_ms=1738340153456

# Air (PlayoutEngine)
[AIR] AIR-INTENT-RECEIVED correlation_id=ch1-sw42-1738340123456 rpc=LoadPreview channel_id=1 asset_path=/media/ep2.mp4 start_frame=0 frame_count=1800 receipt_time_ms=1738340123458

[AIR] AIR-LOADPREVIEW-EFFECTIVE correlation_id=ch1-sw42-1738340123456 channel_id=1 asset_path=/media/ep2.mp4 effective_time_ms=1738340123480

[AIR] AIR-INTENT-RESPONSE correlation_id=ch1-sw42-1738340123456 rpc=LoadPreview channel_id=1 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340123482

[AIR] AIR-INTENT-RECEIVED correlation_id=ch1-sw43-1738340153456 rpc=SwitchToLive channel_id=1 receipt_time_ms=1738340153458

[AIR] AIR-SWITCHTOLIVE-EFFECTIVE correlation_id=ch1-sw43-1738340153456 channel_id=1 effective_time_ms=1738340153462

[AIR] AIR-INTENT-RESPONSE correlation_id=ch1-sw43-1738340153456 rpc=SwitchToLive channel_id=1 success=true result_code=RESULT_CODE_OK pts_contiguous=true completion_time_ms=1738340153465
```

### Example with hard-stop clamp

```
# Core
[CORE] CORE-INTENT-ISSUED correlation_id=ch1-sw44-1738340183456 rpc=LoadPreview channel_id=1 asset_path=/media/ep3.mp4 start_frame=0 frame_count=1800 issued_time_ms=1738340183456

# Air (preview loaded; live segment hits hard stop before SwitchToLive)
[AIR] AIR-INTENT-RECEIVED correlation_id=ch1-sw44-1738340183456 rpc=LoadPreview channel_id=1 asset_path=/media/ep3.mp4 receipt_time_ms=1738340183458

[AIR] AIR-LOADPREVIEW-EFFECTIVE correlation_id=ch1-sw44-1738340183456 channel_id=1 asset_path=/media/ep3.mp4 effective_time_ms=1738340183480

[AIR] AIR-INTENT-RESPONSE correlation_id=ch1-sw44-1738340183456 rpc=LoadPreview channel_id=1 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340183482

[AIR] AIR-CLAMP-STARTED correlation_id=ch1-sw43-1738340153456 channel_id=1 asset_path=/media/ep2.mp4 boundary_ms=1738340183000 segment_correlation_id=ch1-sw43-1738340153456

# ... Core issues SwitchToLive a few seconds later ...

[CORE] CORE-INTENT-ISSUED correlation_id=ch1-sw45-1738340186500 rpc=SwitchToLive channel_id=1 issued_time_ms=1738340186500

[AIR] AIR-INTENT-RECEIVED correlation_id=ch1-sw45-1738340186500 rpc=SwitchToLive channel_id=1 receipt_time_ms=1738340186502

[AIR] AIR-CLAMP-ENDED channel_id=1 asset_path=/media/ep2.mp4 boundary_ms=1738340183000 next_correlation_id=ch1-sw45-1738340186500

[AIR] AIR-SWITCHTOLIVE-EFFECTIVE correlation_id=ch1-sw45-1738340186500 channel_id=1 effective_time_ms=1738340186508

[AIR] AIR-INTENT-RESPONSE correlation_id=ch1-sw45-1738340186500 rpc=SwitchToLive channel_id=1 success=true result_code=RESULT_CODE_OK completion_time_ms=1738340186512
```

---

## 5. Relationship to Other Laws

- **PlayoutInvariants §5 Switching:** No gaps, no PTS regression. Observability Parity does not change switching semantics; it ensures switching behavior is traceable.
- **LAW-002 (hard stop):** Hard-stop clamp is required by that law; LAW-OBS-005 ensures clamp events are visible.
- **PlayoutEngineContract:** Defines gRPC semantics; this law adds observability requirements.

---

## 6. Implementation Notes

- **Proto extension:** Add optional `string correlation_id = N` to request messages, or use gRPC metadata `x-retrovue-correlation-id`. Metadata is sufficient for compliance.
- **Log format:** Structured logging (JSON) is recommended; keys MUST match the catalog. Human-readable prefixes (`[AIR]`, `[CORE]`) aid grep.
- **Performance:** Logging MUST NOT block the gRPC handler. Async or fire-and-forget submission is acceptable.

---

## 7. Summary Table

| ID | Law |
|----|-----|
| LAW-OBS-001 | Intent parity: every control-plane intent MUST be observable in Air logs |
| LAW-OBS-002 | Correlation: every intent MUST carry correlation_id in Core and Air logs |
| LAW-OBS-003 | Result parity: every Air response MUST be logged with correlation_id |
| LAW-OBS-004 | Timing evidence: receipt, effective, completion for LoadPreview and SwitchToLive |
| LAW-OBS-005 | Boundary evidence: clamp started, active, ended when hard stop is enforced |
