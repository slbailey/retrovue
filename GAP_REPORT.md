# Gap Report: Canonical Rule Ledger vs Current Canonical Docs

Comparison of `CANONICAL_RULE_LEDGER.md` against:
- **Air:** `pkg/air/docs/contracts/**`
- **Core:** `pkg/core/docs/contracts/**` + `docs/core/`, `pkg/core/docs/runtime/`, `pkg/core/docs/scheduling/`
- **Main:** `docs/contracts/PHASE_MODEL.md`, `docs/ComponentMap.md`, `docs/standards/*`

---

## 1. Missing Rules (not present anywhere canonical)

Rules from the ledger that have **no normative presence** in current canonical docs.

| canonical_id | current_location | proposed_location | rewrite | tests_required | logs_required |
|--------------|------------------|-------------------|---------|----------------|---------------|
| **LAW-005** | NONE | `pkg/core/docs/scheduling/GridAndFillerInvariants.md` (new) | Episodes MUST NOT be chained back-to-back. Filler MUST NOT overrun the grid; MUST hard stop at next grid boundary. Filler MUST play exactly for padding duration. | `test_playlog_filler_between_episodes`, `test_filler_hard_stop_at_boundary`, `test_filler_duration_equals_pad_len` | (none) |
| **AIR-011** | NONE | `docs/standards/test-methodology.md` §Contract testing harness | Phase 6 tests MUST NOT inspect MPEG-TS bytes. Use gRPC response fields and control-plane outcomes only. | Assert no TS parsing in Phase 6 contract test code; lint or static check | (none) |
| **AIR-012** | `docs/legacy/air/contracts/MpegTSPlayoutSinkDomainContract.md` only | `pkg/air/docs/contracts/semantics/OutputBusAndOutputSinkContract.md` §Sink Lifecycle & Format | Sink MUST support clean start, stop, teardown; Start idempotent if already running; Stop idempotent. Packets MUST be 188 bytes with 0x47 sync; PTS/DTS monotonically increasing; PCR 20–100ms; DTS ≤ PTS. Output MUST be valid H.264; SPS/PPS for IDR. Stream MUST be delivered over TCP; non-blocking writes; graceful disconnect. | test_sink_lifecycle, test_sink_encoding, test_sink_streaming | (none) |
| **AIR-015** | `docs/legacy/air/contracts/MpegTSPlayoutSinkDomainContract.md` only | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md` §Sink Error Handling | Frames beyond threshold MUST be dropped; late_frames and frames_dropped MUST increment. Backpressure MUST be handled gracefully; queue bounded; no deadlock or crash. Client disconnect MUST be detected; resources cleaned up; reconnection MUST work. Fault state MUST persist until explicit reset. Recoverable errors MUST be logged; counters updated; operation MUST continue. | test_sink_buffer_handling, test_sink_network_handling, test_sink_error_handling | late_frames, frames_dropped, sink_late_frames_total, sink_frames_dropped_total, sink_encoding_errors_total, sink_network_errors_total, sink_status |
| **AIR-016** | `docs/legacy/air/contracts/OrchestrationLoopDomainContract.md` only | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md` §Orchestration Loop (new section) | Tick skew MUST remain within ±1ms for 99% of ticks; producer→renderer latency p95 MUST be ≤ 33ms; missed MasterClock callback MUST trigger immediate catch-up tick. Underrun MUST restore within ≤3 ticks; overrun MUST drain within ≤3 ticks; recovery time MUST be ≤ 100ms. Starvation MUST be detected within ≤100ms; teardown MUST complete within ≤500ms. | TEST-P10-ORCH-TICK-SKEW, TEST-P10-ORCH-RECOVERY, TEST-P10-ORCH-TEARDOWN (harness missing) | orchestration_tick_skew_ms, orchestration_latency_ms, orchestration_tick_violation_total, orchestration_backpressure_events_total, orchestration_backpressure_recovery_ms, orchestration_starvation_alert_total, orchestration_teardown_duration_ms |
| **CORE-002** | `pkg/core/docs/archive/phases/Phase5-ChannelManagerContract.md` only | `pkg/core/docs/contracts/resources/ChannelManagerContract.md` §Playout Instruction Semantics | Every PlayoutSegment invocation MUST create a new instance; MUST NOT mutate shared state. PlayoutSegment MUST be immutable once issued to Air; changes MUST require new segment and new LoadPreview. | test_channel_manager_segment_immutability | (none) |
| **CORE-003** | `pkg/core/docs/archive/phases/Phase5-ChannelManagerContract.md` only | `pkg/core/docs/contracts/resources/ChannelManagerContract.md` §Prefeed and Switch Timing | ChannelManager MUST issue LoadPreview for next segment no later than hard_stop_time_ms − prefeed_window_ms. ChannelManager MUST issue SwitchToLive at the boundary (after LoadPreview for that segment). ChannelManager MUST NOT wait for Air to ask for next segment; CM MUST drive the timeline. ChannelManager MUST NOT issue duplicate LoadPreview for the same next segment when re-evaluating multiple times before boundary. | test_channel_manager_prefeed_deadline, test_channel_manager_switch_at_boundary, test_channel_manager_no_duplicate_loadpreview | (none) |
| **CORE-004** | `pkg/core/docs/archive/phases/Phase2-SchedulePlanContract.md` only | `pkg/core/docs/contracts/resources/SchedulePlanInvariantsContract.md` §Mock Plan Structure | Mock SchedulePlan MUST have exactly two items per grid in order: A (samplecontent), B (filler). SchedulePlan MUST be duration-free; no duration or timing fields in plan. | test_schedule_plan_two_items_per_grid, test_schedule_plan_duration_free | (none) |
| **CORE-005** | `pkg/core/docs/archive/phases/Phase2.5-AssetMetadataContract.md` only | `pkg/core/docs/contracts/resources/AssetContract.md` §Duration and Metadata Authority | duration_ms MUST be authoritative; measured once; rounded down to integer milliseconds. duration_ms MUST NOT be recomputed in runtime logic; MUST NOT be inferred from offsets or schedules. Asset objects MUST be immutable. | test_asset_duration_authoritative, test_asset_no_runtime_recompute, test_asset_immutable | (none) |
| **CORE-006** | `pkg/core/docs/archive/phases/Phase3-ActiveItemResolverContract.md` only | `pkg/core/docs/contracts/runtime/ScheduleManagerContract.md` §Active Item Resolution | Resolver MUST assert grid_duration_ms == Phase 1 grid_duration; mismatch MUST be configuration error (fail fast). elapsed_in_grid_ms < filler_start_ms → samplecontent; elapsed_in_grid_ms >= filler_start_ms → filler. | test_resolver_grid_duration_mismatch_fail_fast, test_resolver_boundary_samplecontent, test_resolver_boundary_filler | (none) |
| **CORE-007** | `pkg/core/docs/archive/phases/Phase7-E2EAcceptanceContract.md` only | `docs/contracts/PHASE_MODEL.md` §Phase 7 Scope; `docs/ComponentMap.md` | Phase 7 MUST be the only phase requiring HTTP tune-in, real ffmpeg, and long-running behaviour. Phases 0–6 use direct ProgramDirector API. | test_phase_scope_direct_api_vs_http | (none) |
| **MET-002** | `docs/legacy/air/contracts/MpegTSPlayoutSinkDomainContract.md` §Telemetry only | `pkg/air/docs/contracts/semantics/MetricsExportContract.md` §Sink Metrics | Sink MUST export: sink_frames_sent_total, sink_frames_dropped_total, sink_late_frames_total, sink_encoding_errors_total, sink_network_errors_total, sink_buffer_empty_total, sink_running, sink_status. | Assert metrics exported at /metrics | sink_frames_sent_total, sink_frames_dropped_total, sink_late_frames_total, sink_encoding_errors_total, sink_network_errors_total, sink_buffer_empty_total, sink_running, sink_status |
| **OBS-002** | NONE | `pkg/air/docs/contracts/semantics/MetricsAndTimingContract.md` §Orchestration Metrics | Orchestration loop MUST export: orchestration_tick_skew_ms, orchestration_latency_ms, orchestration_tick_violation_total, orchestration_backpressure_events_total, orchestration_backpressure_recovery_ms, orchestration_starvation_alert_total, orchestration_teardown_duration_ms. | (harness missing) | orchestration_tick_skew_ms, orchestration_latency_ms, orchestration_tick_violation_total, orchestration_backpressure_events_total, orchestration_backpressure_recovery_ms, orchestration_starvation_alert_total, orchestration_teardown_duration_ms |

---

## 2. Conflicts (two canonical docs disagree)

| canonical_id | doc_a | doc_b | conflict_description | resolution_proposal |
|--------------|-------|-------|----------------------|---------------------|
| **LAW-005** | Ledger (from Phase0-PlayoutRules) | `pkg/core/docs/contracts/runtime/ScheduleManagerContract.md` INV-SCHED-GRID-FILLER-PADDING | Ledger: "MUST NOT restart filler from 00:00 each time; use filler_offset = (master_clock - filler_epoch) % filler_duration". ScheduleManager: "Filler always starts at frame 0; No carry-over state from previous filler usage". | **Resolve for ScheduleManager:** Frame-based execution is canonical. Phase0 continuous-offset rule is superseded by INV-SCHED-GRID-FILLER-PADDING. Remove or qualify LAW-005: filler segment always starts at frame 0 per segment; modulo formula applies only if filler is used as a continuous virtual channel (legacy Phase0 mode). Document as "Phase0 playout rules superseded by frame-based ScheduleManager." |
| **AIR-013** | Ledger / legacy MpegTSTiming T-001 | `pkg/air/docs/contracts/semantics/OutputTimingContract.md` §5.2 Real Time | Ledger: "Sink MUST use MasterClock as sole time source". OutputTimingContract: "OutputTiming uses a **process-local monotonic clock** (e.g. std::chrono::steady_clock); Absolute wall-clock time is never used". | **Resolve:** OutputTimingContract is authoritative. MasterClock (from PlayoutInvariants) refers to the playout engine's time authority for CT/scheduling; OutputTiming uses elapsed time for pacing. Add to OutputTimingContract: "OutputTiming's pacing clock is process-local monotonic; it does not consult wall-clock or Core MasterClock. MasterClock authority (PlayoutInvariants §1) governs CT/schedule; OutputTiming governs delivery pacing." Clarify that AIR-013's "MasterClock" in legacy context meant "time authority for pacing," not Python MasterClock. |

---

## 3. Weak Rules (present but not testable/observable)

Rules that exist in canonical docs but lack required tests, observability, or both.

| canonical_id | current_location | weakness | tests_required | logs_required |
|--------------|------------------|----------|----------------|---------------|
| **LAW-001** | PlayoutInvariants §1; MasterClockContract MC-007 | Core MC-007 present; Air side "no datetime.now()" not statically enforced. | Add static analysis or grep check for datetime.now()/time.time() in scheduling/playout paths | (none) |
| **LAW-002** | PlayoutEngineContract LoadPreview; FileProducerContract PROD-010 | No explicit test that asserts "no output after hard_stop_time_ms". | test_file_producer_hard_stop_respected, test_playout_no_output_after_hard_stop | Log when producer clamped at boundary |
| **LAW-004** | ScheduleManagerContract INV-SM-001, INV-SM-004 | Invariants exist; test names (SM-001, SM-002, etc.) may not be implemented. | Verify SM-001 through SM-010 exist and pass | (none) |
| **LAW-006** | PlayoutInvariants §5; OutputContinuityContract | PTS monotonicity stated; SwitchToLiveResponse.pts_contiguous optional in Phase 6A. | test_output_pts_monotonic, test_switch_pts_contiguous (when implemented) | (none) |
| **LAW-007** | Phase7-E2E (archived) | E2E drift test not in canonical test suite. | test_e2e_no_drift_after_boundaries (N × 30 min with stepped clock) | (none) |
| **AIR-005** | PlayoutEngineContract; ProducerBusContract | shadow_decode_started, pts_contiguous optional in 6A; not asserted. | Assert LoadPreviewResponse.shadow_decode_started when applicable; SwitchToLiveResponse.pts_contiguous when implemented | LoadPreviewResponse.shadow_decode_started, SwitchToLiveResponse.pts_contiguous |
| **AIR-007** | PlayoutEngineContract StopChannel; FileProducerContract | "No orphan ffmpeg" not asserted by any test. | test_stop_channel_no_orphan_processes | Log process list before/after StopChannel |
| **AIR-009** | ProducerBusContract | ProgrammaticProducer not explicitly in ProducerBusContract; heterogeneous producer tests may be missing. | test_alternation_file_backed_programmatic, test_programmatic_no_ffmpeg | (none) |
| **AIR-010** | ScheduleManager INV-PLAYOUT-SWITCH-BEFORE-EXHAUSTION | Core has INV-PLAYOUT-*; no test that asserts LoadPreview timestamp < boundary. | test_core_prefeed_before_boundary | Log LoadPreview/SwitchToLive call timestamps |
| **AIR-013** | OutputTimingContract; legacy T-* | OutputTimingContract defines behavior; legacy T-002, T-003, T-005, T-007 tests (test_sink_timing_*) not in pkg/air. | test_sink_timing_pts_mapping, test_sink_timing_early_frames, test_sink_timing_late_drops, test_sink_timing_stop | late_frame_drops |
| **AIR-014** | INV-P10 §6.1 Underrun | INV-P10 has underrun semantics; buffer_underruns / buffer_empty_count not in Metrics §8. | Add retrovue_buffer_underrun_total to INV-P10 metrics; implement test | INV-P10-UNDERRUN log; retrovue_underrun_events_total |
| **OBS-001** | PlayoutEngineContract §LoadPreview, §SwitchToLive | shadow_decode_started, pts_contiguous are optional; no MUST. | Upgrade to SHOULD with test when implemented | LoadPreviewResponse.shadow_decode_started, SwitchToLiveResponse.pts_contiguous |
| **MET-001** | PlayoutEngineContract Part 2 | Metrics defined; enforcement deferred Phase 7+; no test asserts presence. | test_metrics_exported (Phase 7+) | retrovue_playout_* metrics |

---

## 4. Summary Tables

### Missing by category

| Category | Count | IDs |
|----------|-------|-----|
| Laws | 1 | LAW-005 |
| Air | 4 | AIR-011, AIR-012, AIR-015, AIR-016 |
| Core | 6 | CORE-002, CORE-003, CORE-004, CORE-005, CORE-006, CORE-007 |
| Observability | 2 | MET-002, OBS-002 |

### Conflicts

| Count | IDs |
|-------|-----|
| 2 | LAW-005 (vs ScheduleManager), AIR-013 (vs OutputTimingContract) |

### Weak (present but not testable/observable)

| Count | IDs |
|-------|-----|
| 13 | LAW-001, LAW-002, LAW-004, LAW-006, LAW-007, AIR-005, AIR-007, AIR-009, AIR-010, AIR-013, AIR-014, OBS-001, MET-001 |
