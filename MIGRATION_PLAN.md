# Migration Plan: Gap Report → Canonical Docs

PR-sized backlog derived from `GAP_REPORT.md`. Prioritizes: **switching correctness**, **hard-stop clamp behavior**, **preview/live slot semantics**, and **log parity**.

---

## Dependency Graph

```
PR-1, PR-2 (conflicts, doc-only)
    │
    ├──► PR-3 (hard-stop)
    ├──► PR-4 (gRPC observability)
    ├──► PR-5 (ChannelManager prefeed/immutability)
    │
    ├──► PR-6 (prefeed/switch logs)
    ├──► PR-7 (underrun log + metric)
    │
    └──► PR-8, PR-9, PR-10 (supporting)
            │
            └──► PR-11 … PR-19 (remaining)
```

---

## Tier 1: Conflicts & Critical Path (switching, hard-stop, preview/live, logs)

### PR-1: Resolve OutputTiming vs MasterClock conflict (AIR-013)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/semantics/OutputTimingContract.md` |
| **Rules migrated** | AIR-013 (conflict resolution) |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §5.5 Clarification: "OutputTiming's pacing clock is process-local monotonic (e.g. std::chrono::steady_clock). It does not consult wall-clock or Core MasterClock. MasterClock authority (PlayoutInvariants §1) governs CT/schedule; OutputTiming governs delivery pacing. Legacy T-001 'MasterClock as sole time source' referred to pacing authority, not Python MasterClock."
- **Tests added/updated:** None (doc clarification only)
- **Log requirements added:** None

| **Depends on** | None |

---

### PR-2: Resolve filler LAW-005 vs ScheduleManager conflict

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/core/docs/contracts/runtime/ScheduleManagerContract.md`, `CANONICAL_RULE_LEDGER.md` |
| **Rules migrated** | LAW-005 (conflict resolution) |
| **Acceptance criteria** | |

- **Contract/law text added:** Add note under INV-SCHED-GRID-FILLER-PADDING: "Phase0 playout rules (continuous filler_offset modulo formula) are superseded by frame-based execution. Filler segment always starts at frame 0 per segment; no carry-over. LAW-005 'never restart from 00:00' applied to continuous virtual channel mode (archived); current canonical is frame-based."
- **Tests added/updated:** None (doc clarification)
- **Log requirements added:** None

| **Depends on** | None |

---

### PR-3: Hard-stop clamp behavior + observability (LAW-002)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/semantics/FileProducerContract.md`, `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md`, Air tests, Air runtime (log) |
| **Rules migrated** | LAW-002 (weak → strong) |
| **Acceptance criteria** | |

- **Contract/law text added:** In FileProducerContract PROD-010, add: "When producer reaches hard_stop_time_ms boundary, runtime MUST log: `[FileProducer] LAW-002: Producer clamped at hard_stop boundary (asset=..., segment_end_ms=...)`."
- **Tests added/updated:** `test_file_producer_hard_stop_respected`, `test_playout_no_output_after_hard_stop` — assert no frames emitted after hard_stop_time_ms; use short asset + stepped clock.
- **Log requirements added:** `[FileProducer] LAW-002: Producer clamped at hard_stop boundary` |

| **Depends on** | PR-1, PR-2 (optional; can proceed in parallel) |

---

### PR-4: gRPC response observability for preview/live (OBS-001, AIR-005)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md`, `pkg/core/` or Air gRPC tests |
| **Rules migrated** | OBS-001, AIR-005 (weak → strong) |
| **Acceptance criteria** | |

- **Contract/law text added:** In PlayoutEngineContract §LoadPreview, §SwitchToLive: "LoadPreviewResponse SHOULD include `shadow_decode_started` when shadow decode is used. SwitchToLiveResponse SHOULD include `pts_contiguous` when implemented. Phase 6A tests MUST assert these fields when present."
- **Tests added/updated:** Assert LoadPreviewResponse.shadow_decode_started when applicable; assert SwitchToLiveResponse.pts_contiguous when implemented. Update Phase 6A control-plane tests.
- **Log requirements added:** LoadPreviewResponse.shadow_decode_started, SwitchToLiveResponse.pts_contiguous (as response fields) |

| **Depends on** | None |

---

### PR-5: ChannelManager prefeed and segment immutability (CORE-002, CORE-003)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/core/docs/contracts/resources/ChannelManagerContract.md`, `pkg/core/tests/` |
| **Rules migrated** | CORE-002, CORE-003 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Playout Instruction Semantics: "Every PlayoutSegment invocation MUST create a new instance; MUST NOT mutate shared state. PlayoutSegment MUST be immutable once issued to Air; changes MUST require new segment and new LoadPreview." Add §Prefeed and Switch Timing: "ChannelManager MUST issue LoadPreview for next segment no later than hard_stop_time_ms − prefeed_window_ms. MUST issue SwitchToLive at the boundary (after LoadPreview). MUST NOT wait for Air to ask; CM drives timeline. MUST NOT issue duplicate LoadPreview for the same next segment."
- **Tests added/updated:** `test_channel_manager_segment_immutability`, `test_channel_manager_prefeed_deadline`, `test_channel_manager_switch_at_boundary`, `test_channel_manager_no_duplicate_loadpreview`
- **Log requirements added:** None

| **Depends on** | None |

---

### PR-6: Prefeed and switch log parity (AIR-010)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/core/src/retrovue/runtime/` (channel_manager or tick loop), `pkg/core/docs/contracts/resources/ChannelManagerContract.md` |
| **Rules migrated** | AIR-010 (weak → strong) |
| **Acceptance criteria** | |

- **Contract/law text added:** In ChannelManagerContract §Prefeed and Switch Timing: "Log LoadPreview and SwitchToLive calls with timestamps for diagnostics: `[ChannelManager] LoadPreview channel={id} asset={path} boundary_ms={ms}`, `[ChannelManager] SwitchToLive channel={id} boundary_ms={ms}`."
- **Tests added/updated:** `test_core_prefeed_before_boundary` — use gRPC mock, stepped clock; assert LoadPreview timestamp ≤ boundary − prefeed_window, SwitchToLive at boundary.
- **Log requirements added:** `[ChannelManager] LoadPreview channel=...`, `[ChannelManager] SwitchToLive channel=...`

| **Depends on** | PR-5 |

---

### PR-7: INV-P10 underrun log and metric (AIR-014)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md`, Air runtime (ProgramOutput / buffer) |
| **Rules migrated** | AIR-014 |
| **Acceptance criteria** | |

- **Contract/law text added:** In INV-P10 §8 Metrics: add `retrovue_buffer_underrun_total`. In §7 Logging: ensure `INV-P10-UNDERRUN: warning (buffer_depth=0, duration_ms=X)` is emitted when buffer drains.
- **Tests added/updated:** `test_sink_buffer_handling` or equivalent; start with empty buffer, verify counter increments and worker remains alive.
- **Log requirements added:** `INV-P10-UNDERRUN`, `retrovue_buffer_underrun_total` |

| **Depends on** | None |

---

## Tier 2: Supporting (producer lifecycle, test methodology)

### PR-8: No orphan ffmpeg after StopChannel (AIR-007)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/tests/` or integration tests, `pkg/air/docs/contracts/semantics/FileProducerContract.md` |
| **Rules migrated** | AIR-007 (weak → strong) |
| **Acceptance criteria** | |

- **Contract/law text added:** In FileProducerContract: "On StopChannel or segment stop, MUST NOT leave orphan ffmpeg processes. Verify via process enumeration before/after."
- **Tests added/updated:** `test_stop_channel_no_orphan_processes` — start channel, load segment, stop; assert no ffmpeg children remain.
- **Log requirements added:** Optional: log process count before/after StopChannel for diagnostics |

| **Depends on** | None |

---

### PR-9: ProgrammaticProducer in ProducerBusContract (AIR-009)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/coordination/ProducerBusContract.md`, `pkg/air/tests/` |
| **Rules migrated** | AIR-009 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Heterogeneous Producers: "Engine MUST support both file-backed and programmatic producers with same ExecutionProducer lifecycle. ProgrammaticProducer MUST NOT read files or call ffmpeg. MUST fit preview/live slot model and Stop semantics."
- **Tests added/updated:** `test_alternation_file_backed_programmatic`, `test_programmatic_no_ffmpeg`
- **Log requirements added:** None

| **Depends on** | None |

---

### PR-10: Phase 6 test scaffolding (AIR-011)

| Field | Value |
|-------|-------|
| **Files changed** | `docs/standards/test-methodology.md` |
| **Rules migrated** | AIR-011 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Phase 6 contract tests: "Phase 6 tests MUST NOT inspect MPEG-TS bytes. Use gRPC response fields and control-plane outcomes only. Lint or static check to prevent TS parsing in Phase 6 contract test code."
- **Tests added/updated:** Add lint/grep rule or pytest marker to enforce no TS parsing in Phase 6 tests.
- **Log requirements added:** None

| **Depends on** | None |

---

## Tier 3: Core scheduling and metadata

### PR-11: SchedulePlan mock structure (CORE-004)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/core/docs/contracts/resources/SchedulePlanInvariantsContract.md`, `pkg/core/tests/` |
| **Rules migrated** | CORE-004 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Mock Plan Structure: "Mock SchedulePlan MUST have exactly two items per grid in order: A (samplecontent), B (filler). SchedulePlan MUST be duration-free; no duration or timing fields in plan."
- **Tests added/updated:** `test_schedule_plan_two_items_per_grid`, `test_schedule_plan_duration_free`
- **Log requirements added:** None

| **Depends on** | None |

---

### PR-12: Asset duration and metadata authority (CORE-005)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/core/docs/contracts/resources/AssetContract.md`, `pkg/core/tests/` |
| **Rules migrated** | CORE-005 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Duration and Metadata Authority: "duration_ms MUST be authoritative; measured once; rounded down to integer ms. MUST NOT be recomputed in runtime logic; MUST NOT be inferred from offsets or schedules. Asset objects MUST be immutable."
- **Tests added/updated:** `test_asset_duration_authoritative`, `test_asset_no_runtime_recompute`, `test_asset_immutable`
- **Log requirements added:** None

| **Depends on** | None |

---

### PR-13: Active item resolver semantics (CORE-006)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/core/docs/contracts/runtime/ScheduleManagerContract.md`, `pkg/core/tests/` |
| **Rules migrated** | CORE-006 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Active Item Resolution: "Resolver MUST assert grid_duration_ms == Phase 1 grid_duration; mismatch MUST be configuration error (fail fast). elapsed_in_grid_ms < filler_start_ms → samplecontent; elapsed_in_grid_ms >= filler_start_ms → filler."
- **Tests added/updated:** `test_resolver_grid_duration_mismatch_fail_fast`, `test_resolver_boundary_samplecontent`, `test_resolver_boundary_filler`
- **Log requirements added:** None

| **Depends on** | PR-11 |

---

### PR-14: Phase 7 scope documentation (CORE-007)

| Field | Value |
|-------|-------|
| **Files changed** | `docs/contracts/PHASE_MODEL.md`, `docs/ComponentMap.md` |
| **Rules migrated** | CORE-007 |
| **Acceptance criteria** | |

- **Contract/law text added:** In PHASE_MODEL: "Phase 7 MUST be the only phase requiring HTTP tune-in, real ffmpeg, and long-running behaviour. Phases 0–6 use direct ProgramDirector API." Add cross-ref in ComponentMap.
- **Tests added/updated:** `test_phase_scope_direct_api_vs_http` (optional; may be doc-only)
- **Log requirements added:** None

| **Depends on** | None |

---

## Tier 4: Phase 7+ Air (deferred)

### PR-15: Sink lifecycle and format (AIR-012)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/architecture/OutputBusAndOutputSinkContract.md` or new `SinkLifecycleContract.md` |
| **Rules migrated** | AIR-012 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Sink Lifecycle & Format: "Sink MUST support clean start, stop, teardown; Start idempotent if already running; Stop idempotent. Packets MUST be 188 bytes with 0x47 sync; PTS/DTS monotonically increasing; PCR 20–100ms; DTS ≤ PTS. Output MUST be valid H.264; SPS/PPS for IDR. Stream MUST be delivered over TCP; non-blocking writes; graceful disconnect."
- **Tests added/updated:** test_sink_lifecycle, test_sink_encoding, test_sink_streaming (harness Phase 7+)
- **Log requirements added:** None

| **Depends on** | PR-1 (conflict clarity) |
| **Phase** | 7+ |

---

### PR-16: Sink error handling and metrics (AIR-015, MET-002)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md`, `pkg/air/docs/contracts/semantics/MetricsExportContract.md` |
| **Rules migrated** | AIR-015, MET-002 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Sink Error Handling to INV-P10 or OutputBus contract. Add §Sink Metrics to MetricsExportContract: sink_frames_sent_total, sink_frames_dropped_total, sink_late_frames_total, sink_encoding_errors_total, sink_network_errors_total, sink_buffer_empty_total, sink_running, sink_status.
- **Tests added/updated:** test_sink_buffer_handling, test_sink_network_handling, test_sink_error_handling
- **Log requirements added:** late_frames, frames_dropped, sink_* metrics |

| **Depends on** | PR-7, PR-15 |
| **Phase** | 7+ |

---

### PR-17: Orchestration loop invariants and telemetry (AIR-016, OBS-002)

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md`, `pkg/air/docs/contracts/semantics/MetricsAndTimingContract.md` |
| **Rules migrated** | AIR-016, OBS-002 |
| **Acceptance criteria** | |

- **Contract/law text added:** Add §Orchestration Loop. Add §Orchestration Metrics: orchestration_tick_skew_ms, orchestration_latency_ms, orchestration_tick_violation_total, orchestration_backpressure_events_total, orchestration_backpressure_recovery_ms, orchestration_starvation_alert_total, orchestration_teardown_duration_ms.
- **Tests added/updated:** TEST-P10-ORCH-TICK-SKEW, TEST-P10-ORCH-RECOVERY, TEST-P10-ORCH-TEARDOWN (harness missing)
- **Log requirements added:** orchestration_* metrics |

| **Depends on** | PR-7 |
| **Phase** | 7+ |

---

## Tier 5: Remaining weak rules (lower priority)

### PR-18: LAW-001 static check for datetime.now()

| Field | Value |
|-------|-------|
| **Files changed** | `scripts/` or CI, `docs/standards/` |
| **Rules migrated** | LAW-001 |
| **Acceptance criteria** | Add grep/lint rule: no datetime.now() or time.time() in scheduling/playout paths |
| **Depends on** | None |

---

### PR-19: LAW-004, LAW-006, LAW-007, MET-001 test coverage

| Field | Value |
|-------|-------|
| **Files changed** | `pkg/core/tests/`, `pkg/air/tests/` |
| **Rules migrated** | LAW-004, LAW-006, LAW-007, MET-001 |
| **Acceptance criteria** | Verify SM-001–SM-010 exist; add test_output_pts_monotonic, test_e2e_no_drift_after_boundaries, test_metrics_exported |
| **Depends on** | PR-11, PR-13 |

---

## Summary: PR Count by Tier

| Tier | PRs | Focus |
|------|-----|-------|
| 1 | PR-1 … PR-7 | Conflicts, switching, hard-stop, preview/live, logs |
| 2 | PR-8 … PR-10 | Producer lifecycle, test methodology |
| 3 | PR-11 … PR-14 | Core scheduling, metadata |
| 4 | PR-15 … PR-17 | Phase 7+ Air (deferred) |
| 5 | PR-18 … PR-19 | Remaining weak rules |

**Recommended sequence for Tier 1:** PR-1, PR-2 (parallel) → PR-3, PR-4, PR-5, PR-7 (parallel) → PR-6.
