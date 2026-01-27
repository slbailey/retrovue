# Metrics and Timing Contract

_Related: [Playout Engine Contract](PlayoutEngineContract.md) · [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 6A Overview](Phase6A-Overview.md) · [Renderer Contract](RendererContract.md)_

**Applies starting in:** Phase 6A for clock authority; metrics and latency Deferred (Applies Phase 7+)  
**Status:** Enforced for clock/time alignment (6A); Deferred (Applies Phase 7+) for metrics and performance

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

## Purpose

Define the observable guarantees for **metrics and timing** in the Playout Engine. This contract specifies **what** timing and metrics guarantees the system provides, not how they are achieved internally. **Clock authority** lives in the Python runtime (MasterClock); Air enforces deadlines (e.g. hard_stop_time_ms) but does not compute schedule time. Microsecond-level timing and metrics pipeline are **not required for Phase 6A**; definitions and targets are preserved for Phase 7+.

---

## Timing Invariants

### MT-001: MasterClock Authority

**Guarantee:** MasterClock is the single authoritative time source for scheduling and playout timing. Air does not compute schedule time; it enforces deadlines derived from MasterClock (e.g. hard_stop_time_ms).

**Phase applicability:** 6A+

**Observable behavior:**
- All timing decisions that affect segment boundaries and deadlines use MasterClock (or wall-clock time supplied by Core, e.g. hard_stop_time_ms).
- No direct system clock calls in production code for schedule/segment decisions when a clock abstraction is used.
- MockMasterClock / test time injection produce deterministic results in tests.

**Note:** MasterClock lives in Python; Air may receive deadline timestamps (e.g. hard_stop_time_ms) and enforce them without owning the clock.

---

### MT-002: Component Time Alignment

**Guarantee:** When components (decoder, buffer, renderer) exist, they align to MasterClock (or supplied deadlines). During Phase 6A, only producer/engine segment boundaries need to align to authoritative stop time.

**Phase applicability:** 6A: segment stop at or before hard_stop_time_ms. Full “decoder, buffer, renderer all use MasterClock” applies when those components are in scope (Phase 7+).

**Observable behavior (6A):** Engine never plays past hard_stop_time_ms.  
**Future:** Decoder, buffer, and renderer all use MasterClock; frame timestamps correlate with MasterClock time.

---

### MT-003: Frame Cadence

**Guarantee:** Frames rendered at source frame rate with ±2ms tolerance (when Renderer/pipeline exists).

**Phase applicability:** Deferred (Applies Phase 7+).

**Intent (preserved):**
- Mean frame interval matches source (e.g., 33.37ms for 29.97fps)
- 95% of frames within ±2ms tolerance
- No frame interval exceeds tolerance bounds
- Source frame rate overrides default when specified

**Why deferred:** Phase 6A does not enforce Renderer or frame output timing.

---

### MT-004: End-to-End Latency

**Guarantee:** Decode-to-render latency bounded (when pipeline exists).

**Phase applicability:** Deferred (Applies Phase 7+).

**Intent (preserved):**

| Metric | Target |
|--------|--------|
| Average latency | < 33ms |
| Sustained max (5s window) | < 50ms |

**Observable behavior (future):** Latency stays within bounds under normal load; latency warning logged when exceeded; `clock_drift_warning_total` increments on violation.

**Why deferred:** Phase 6A explicitly defers performance and latency guarantees.

---

## Metrics Requirements

### MT-005: Required Metrics (Definitions Preserved)

**Guarantee:** When metrics are in scope, all required metrics exported at `/metrics`. Deferred (Applies Phase 7+).

| Metric | Type | Description |
|--------|------|-------------|
| `frame_decode_time_ms{channel}` | Gauge | Last decode duration |
| `frame_render_time_ms{channel}` | Gauge | Last render duration |
| `frames_dropped_total{channel}` | Counter | Frames dropped |
| `frames_skipped_total{channel}` | Counter | Frames skipped |
| `clock_offset_ms{channel}` | Gauge | Current clock offset |
| `uptime_seconds{channel}` | Gauge | Channel uptime |

---

### MT-006: Metrics Sampling

**Guarantee:** Metrics updated every 1 second (when metrics are enforced).

**Phase applicability:** Deferred (Applies Phase 7+).

**Observable behavior (future):** Counters show cumulative values; gauges show current/instantaneous values; updates visible within 1 second of occurrence.

---

### MT-007: Anomaly Reporting

**Guarantee:** All timing anomalies logged and exposed via metrics (when metrics are enforced).

**Phase applicability:** Deferred (Applies Phase 7+).

| Anomaly | Metric | Log Level |
|---------|--------|-----------|
| Late frame | `frames_late_total` | WARNING |
| Dropped frame | `frames_dropped_total` | WARNING |
| Clock drift | `clock_drift_warning_total` | WARNING |
| Buffer underrun | `buffer_underrun_total` | WARNING |

---

### MT-008: Forward Compatibility (Clock Interface)

**Guarantee:** MasterClock interface matches Phase 4 specification where used. When Air receives time (e.g. hard_stop_time_ms), it uses a consistent interpretation (e.g. epoch ms).

**Phase applicability:** 6A+ for any deadline/time field semantics; full interface when Air integrates with MasterClock directly.

**Required methods (when used):**
- `now_utc_us()` — current UTC time in microseconds
- `now_local_us()` — current local time in microseconds
- `to_local(utc_us)` — convert UTC to local
- `offset_from_schedule(scheduled_pts_us)` — compute offset
- `frequency()` — clock frequency

---

## Performance Targets (Future Enforcement — Phase 7+)

**Deferred (Applies Phase 7+).** Avoid enforcing microsecond-level targets in early phases.

### Latency

| Metric | Target |
|--------|--------|
| Decode-to-render (average) | < 33ms |
| Decode-to-render (sustained max) | < 50ms |
| Metrics endpoint response | < 100ms |

### Accuracy

| Metric | Target |
|--------|--------|
| Frame timing tolerance | ±2ms |
| Clock offset accuracy | ±0.1ms |

---

## Behavioral Rules Summary

| Rule | Guarantee | Phase |
|------|-----------|--------|
| MT-001 | MasterClock is sole time source; Air enforces deadlines | 6A+ |
| MT-002 | Segment/time alignment (hard_stop respected); full component alignment when pipeline exists | 6A / 7+ |
| MT-003 | Frame cadence with ±2ms tolerance | 7+ |
| MT-004 | Bounded end-to-end latency | 7+ |
| MT-005 | Required metrics exported | 7+ |
| MT-006 | 1-second metrics sampling | 7+ |
| MT-007 | Anomalies logged and exposed | 7+ |
| MT-008 | Phase 4 compatible clock interface | 6A+ |

---

## Test Coverage

| Rule | Test | Phase |
|------|------|--------|
| MT-001 | `test_no_system_clock_calls`, `test_masterclock_injection` | 6A+ |
| MT-002 | `test_component_clock_alignment`, segment hard_stop | 6A+ / 7+ |
| MT-003 | `test_frame_cadence`, `test_source_framerate_override` | 7+ |
| MT-004 | `test_latency_bounds`, `test_latency_under_load` | 7+ |
| MT-005 | `test_metrics_presence`, `test_metric_types` | 7+ |
| MT-006 | `test_metrics_sampling_frequency` | 7+ |
| MT-007 | `test_anomaly_detection`, `test_anomaly_logging` | 7+ |
| MT-008 | `test_masterclock_interface_compatibility` | 6A+ |

---

## See Also

- [Playout Engine Contract](PlayoutEngineContract.md) — control plane
- [Phase Model](../../contracts/PHASE_MODEL.md) — phase taxonomy
- [Phase 6A Overview](Phase6A-Overview.md) — deferrals
- [Renderer Contract](RendererContract.md) — frame consumption (post-6A)
- [Contract Hygiene Checklist](../../standards/contract-hygiene.md) — authoring guidelines
