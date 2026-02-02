<!-- NOTE: This is a legacy file. The authoritative Canonical Rule Ledger is at: [docs/contracts/CANONICAL_RULE_LEDGER.md](docs/contracts/CANONICAL_RULE_LEDGER.md) -->

# Canonical Rule Ledger

Deduped and clustered from `RULE_CANDIDATES.json`. Traceability: each canonical rule lists contributing source `rule_id`s.

---

## 1. Laws / Invariants (cross-component, supreme)

### LAW-001: MasterClock Authority

| Field | Value |
|-------|-------|
| **canonical_id** | LAW-001 |
| **normative_text** | MasterClock MUST be the single source of "now" for scheduling and playout. No component MUST call `datetime.now()` or `time.time()` directly for scheduling/playout decisions. All downstream logic MUST consume time only via MasterClock interface. |
| **scope** | core, air (both); Phase 0+ |
| **phase_applicability** | 0, 6A, 7+ |
| **sources** | ARCH-core-Phase0Clock-001, ARCH-core-Phase0Clock-002, ARCH-core-Phase0Clock-003, ARCH-air-Phase6AOverview-003, ARCH-main-MpegTSTiming-T001, ARCH-main-MpegTSDomain-SINK012 |
| **where_it_belongs** | `pkg/air/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md` §1 Clock Invariant; `pkg/core/docs/contracts/resources/MasterClockContract.md` |
| **required_tests** | INV-AUDIO-HOUSE-FORMAT-001 (stub); `retrovue runtime masterclock`; test_sink_timing_clock_usage |
| **required_log_events_fields** | (none for clock authority) |
| **codified_status** | **yes** — PlayoutInvariants §1; MasterClockContract MC-007 |

---

### LAW-002: Hard Stop Authoritative

| Field | Value |
|-------|-------|
| **canonical_id** | LAW-002 |
| **normative_text** | `hard_stop_time_ms` is authoritative. Air MAY stop at or before it; Air MUST NOT play past it. Producer MUST stop at or before `hard_stop_time_ms`; engine MUST NOT play past it. |
| **scope** | both (Core produces; Air enforces) |
| **phase_applicability** | 4, 5, 6A, 6A.1, 6A.2, 6A.3, 7+ |
| **sources** | ARCH-air-Phase6AOverview-004, ARCH-air-Phase6A1-004, ARCH-air-Phase6A2-001, ARCH-air-Phase6A2-003, ARCH-air-Phase6A3-003, ARCH-core-Phase4Pipeline-001, ARCH-core-Phase4Pipeline-003 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; `pkg/air/docs/contracts/semantics/FileProducerContract.md`; `pkg/core/docs/archive/phases/Phase4-PlayoutPipelineContract.md` |
| **required_tests** | Assert no output after hard_stop_time_ms; producer stopped by hard_stop; FileProducer hard-stop tests |
| **required_log_events_fields** | (none specified) |
| **codified_status** | **yes** — PlayoutEngineContract LoadPreview; Phase4/Phase5 archived |

---

### LAW-003: Segment-Based Control

| Field | Value |
|-------|-------|
| **canonical_id** | LAW-003 |
| **normative_text** | Media execution MUST be driven by LoadPreview (segment payload) then SwitchToLive (at boundary). Air MUST NOT interpret schedules or plans. StartChannel initializes channel state but MUST NOT imply media playback; execution begins only after LoadPreview + SwitchToLive. |
| **scope** | both |
| **phase_applicability** | 6, 6A, 6A.0 |
| **sources** | ARCH-air-Phase6AOverview-001, ARCH-air-Phase6AOverview-002, ARCH-air-Phase6A0-003 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §THINK vs ACT; `pkg/air/docs/archive/phases/Phase6A-Overview.md` |
| **required_tests** | StartChannel alone produces no decode/output; LoadPreview precedes SwitchToLive |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutEngineContract THINK vs ACT; Phase6A Overview |

---

### LAW-004: Grid Boundaries Sacred

| Field | Value |
|-------|-------|
| **canonical_id** | LAW-004 |
| **normative_text** | Content MUST NOT drift off the grid. Cuts MUST occur at grid boundaries (:00, :30). Grid size MUST be 30 minutes; boundaries MUST be at :00 and :30. |
| **scope** | core |
| **phase_applicability** | 0, 1, 7 |
| **sources** | ARCH-core-Phase0Playout-002, ARCH-core-Phase0Playout-003, ARCH-core-Phase1Grid-001, ARCH-core-Phase7E2E-002 |
| **where_it_belongs** | `pkg/core/docs/contracts/runtime/ScheduleManagerContract.md`; `pkg/core/docs/scheduling/` |
| **required_tests** | grid_start(10:00)=10:00, grid_end=10:30; assert cuts at :00/:30; boundaries respected across switches |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — ScheduleManager* contracts exist; grid math in core; Phase 0 playout rules archived |

---

### LAW-005: No Episodes Back-to-Back; Filler Rules

| Field | Value |
|-------|-------|
| **canonical_id** | LAW-005 |
| **normative_text** | Episodes MUST NOT be chained back-to-back. Filler MUST use continuous offset `(master_clock - filler_epoch) % filler_duration`; MUST NOT restart from 00:00 each time. Filler MUST NOT overrun the grid; MUST hard stop at next grid boundary. Filler MUST play exactly for padding duration. |
| **scope** | core |
| **phase_applicability** | 0 |
| **sources** | ARCH-core-Phase0Playout-001, ARCH-core-Phase0Playout-004, ARCH-core-Phase0Playout-005, ARCH-core-Phase0Playout-006 |
| **where_it_belongs** | `pkg/core/docs/scheduling/`; `pkg/core/docs/archive/phases/Phase0-PlayoutRules.md` |
| **required_tests** | Playlog has filler between episodes; filler seek uses modulo; filler duration equals pad_len |
| **required_log_events_fields** | (none) |
| **codified_status** | **no** — Phase0 playout rules archived; not in canonical scheduling docs |

---

### LAW-006: PTS Monotonicity / No Gaps on Switch

| Field | Value |
|-------|-------|
| **canonical_id** | LAW-006 |
| **normative_text** | Output PTS MUST be monotonically increasing. Frames MUST NOT be output out of PTS order. No gaps, no PTS regression, no silence during switches. |
| **scope** | air |
| **phase_applicability** | 6, 7+ |
| **sources** | ARCH-air-Phase6-002, ARCH-main-MpegTSDomain-SINK011, ARCH-main-MpegTSTiming-T006 |
| **where_it_belongs** | `pkg/air/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md` §5 Switching; `pkg/air/docs/contracts/semantics/OutputContinuityContract.md` |
| **required_tests** | Record output PTS; verify strictly increasing; SwitchToLiveResponse.pts_contiguous; test_sink_frame_order |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutInvariants §5 Switching; INV-P8-002 |

---

### LAW-007: No Drift Over Time

| Field | Value |
|-------|-------|
| **canonical_id** | LAW-007 |
| **normative_text** | Offsets and hard stops MUST remain correct after many boundaries; MUST NOT drift after hours. |
| **scope** | both |
| **phase_applicability** | 7 |
| **sources** | ARCH-core-Phase7E2E-003 |
| **where_it_belongs** | `pkg/core/docs/archive/phases/Phase7-E2EAcceptanceContract.md`; E2E acceptance tests |
| **required_tests** | Run N × 30 min; assert offsets and hard stops correct |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — E2E contract archived; harness/tests may be missing |

---

## 2. Air Contracts (execution / coordination)

### AIR-001: gRPC Control Surface

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-001 |
| **normative_text** | Air MUST compile and link against `protos/playout.proto` generated code. Air MUST expose PlayoutControl with StartChannel, LoadPreview, SwitchToLive, StopChannel. Air MUST NOT interpret `plan_handle` in Phase 6A; accepted only for proto compatibility. |
| **scope** | air |
| **phase_applicability** | 6A.0 |
| **sources** | ARCH-air-Phase6A0-001, ARCH-air-Phase6A0-002, ARCH-air-Phase6A0-008 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §Service Definition; `protos/playout.proto` |
| **required_tests** | Build succeeds; client can call all four RPCs; plan_handle values do not affect behavior |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutEngineContract; proto schema |

---

### AIR-002: Idempotent Start/Stop Semantics

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-002 |
| **normative_text** | StartChannel on already-started channel MUST return idempotent success. StopChannel on unknown or already-stopped channel MUST return idempotent success. |
| **scope** | air |
| **phase_applicability** | 6A.0 |
| **sources** | ARCH-air-Phase6A0-004, ARCH-air-Phase6A0-007 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §Idempotency; §StartChannel; §StopChannel |
| **required_tests** | Call StartChannel twice → both success; StopChannel on unknown → success |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutEngineContract PE-START-002, PE-STOP-002 |

---

### AIR-003: LoadPreview Before StartChannel → Error

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-003 |
| **normative_text** | LoadPreview before StartChannel for that channel MUST return error (`success=false`). |
| **scope** | air |
| **phase_applicability** | 6A.0 |
| **sources** | ARCH-air-Phase6A0-005 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; PE-CTL-001 |
| **required_tests** | Call LoadPreview without StartChannel; assert success=false |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutEngineContract PE-CTL-001 |

---

### AIR-004: SwitchToLive With No Preview → Error

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-004 |
| **normative_text** | SwitchToLive with no preview loaded for that channel MUST return error (`success=false`). |
| **scope** | air |
| **phase_applicability** | 6A.0 |
| **sources** | ARCH-air-Phase6A0-006 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §SwitchToLive; PE-CTL-002 |
| **required_tests** | Call SwitchToLive without LoadPreview; assert success=false |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutEngineContract PE-CTL-002 |

---

### AIR-005: LoadPreview → Preview Only; SwitchToLive → Promote

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-005 |
| **normative_text** | LoadPreview MUST load asset into preview slot; MUST NOT go live. LoadPreview MUST install into preview slot; live MUST remain unchanged until SwitchToLive. SwitchToLive MUST promote preview to live exactly when commanded; MUST be seamless with no gap. Old live MUST be stopped; preview slot cleared or ready for next. |
| **scope** | air |
| **phase_applicability** | 6, 6A, 6A.1 |
| **sources** | ARCH-air-Phase6-001, ARCH-air-Phase6-002, ARCH-air-Phase6A1-005, ARCH-air-Phase6A1-006 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; §SwitchToLive; `pkg/air/docs/contracts/coordination/ProducerBusContract.md` |
| **required_tests** | LoadPreviewResponse.shadow_decode_started; SwitchToLiveResponse.pts_contiguous; preview updated, live unchanged; old live stopped |
| **required_log_events_fields** | LoadPreviewResponse.shadow_decode_started, SwitchToLiveResponse.pts_contiguous |
| **codified_status** | **yes** — PlayoutEngineContract; Phase6A-1 |

---

### AIR-006: Engine Owns Slots; Producers Passive

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-006 |
| **normative_text** | Engine MUST own preview/live slot state and switch timing. Producers MUST be passive; MUST NOT self-switch or manage switch timing internally. Producers respond only to Start/Stop. |
| **scope** | air |
| **phase_applicability** | 6A.1 |
| **sources** | ARCH-air-Phase6A1-001, ARCH-air-Phase6A1-002 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §THINK vs ACT; `pkg/air/docs/contracts/coordination/ProducerBusContract.md` |
| **required_tests** | Producer does not self-switch; engine controls all transitions |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutInvariants §2 Timeline; INV-P8-TIME-BLINDNESS |

---

### AIR-007: StopChannel / Segment Stop Semantics

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-007 |
| **normative_text** | On StopChannel, all producers MUST stop; MUST NOT emit frames after stop. Resources MUST be released; MUST NOT leave orphan ffmpeg processes. Channel MUST remain active across switches; MUST NOT receive spurious StopChannel. |
| **scope** | air |
| **phase_applicability** | 6, 6A.1, 6A.2 |
| **sources** | ARCH-air-Phase6-006, ARCH-air-Phase6A1-003, ARCH-air-Phase6A2-005 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §StopChannel; `pkg/air/docs/contracts/semantics/FileProducerContract.md` |
| **required_tests** | No frames after StopChannel; no orphan ffmpeg; resources released |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — PlayoutEngineContract StopChannel; PE-STOP-001 |

---

### AIR-008: FileProducer Segment Params

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-008 |
| **normative_text** | FileBackedProducer MUST honor `start_offset_ms` and `hard_stop_time_ms`. Decode MUST seek to position at or before `start_offset_ms`; MUST NOT play earlier than intended. Invalid path or unreadable file MUST yield defined error (`success=false`). |
| **scope** | air |
| **phase_applicability** | 6A.2 |
| **sources** | ARCH-air-Phase6A2-001, ARCH-air-Phase6A2-002, ARCH-air-Phase6A2-004 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/FileProducerContract.md` |
| **required_tests** | Output respects start and stop; seek within tolerance; LoadPreviewResponse.success=false for invalid path |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — FileProducerContract; PROD-010, PROD-010b |

---

### AIR-009: Heterogeneous Producers

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-009 |
| **normative_text** | Engine MUST support both file-backed and programmatic producers with same ExecutionProducer lifecycle. ProgrammaticProducer MUST NOT read files or call ffmpeg. ProgrammaticProducer MUST fit ExecutionProducer lifecycle; MUST stop at hard_stop_time_ms or StopChannel. |
| **scope** | air |
| **phase_applicability** | 6A.3 |
| **sources** | ARCH-air-Phase6AOverview-005, ARCH-air-Phase6A3-001, ARCH-air-Phase6A3-002, ARCH-air-Phase6A3-003 |
| **where_it_belongs** | `pkg/air/docs/contracts/coordination/ProducerBusContract.md`; `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` |
| **required_tests** | Alternation FileBackedSegment → ProgrammaticSegment; no ffmpeg for programmatic path |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — ProducerBusContract; ProgrammaticProducer not explicitly codified |

---

### AIR-010: Prefeed Ordering

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-010 |
| **normative_text** | LoadPreview for next segment MUST be received before current segment ends. SwitchToLive at boundary. |
| **scope** | both (Core issues; Air receives) |
| **phase_applicability** | 6 |
| **sources** | ARCH-air-Phase6-007 |
| **where_it_belongs** | `pkg/core/docs/archive/phases/Phase5-ChannelManagerContract.md`; Core owns prefeed; Air receives |
| **required_tests** | LoadPreview call timestamp < boundary; SwitchToLive at boundary |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — Core Phase5; Air receives, does not enforce ordering |

---

### AIR-011: Phase 6 Test Scaffolding

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-011 |
| **normative_text** | Phase 6 tests MUST NOT inspect MPEG-TS bytes. Use gRPC outcomes only. |
| **scope** | air (test methodology) |
| **phase_applicability** | 6 |
| **sources** | ARCH-air-Phase6-003 |
| **where_it_belongs** | `pkg/air/docs/archive/phases/Phase6-ExecutionContract.md`; test methodology |
| **required_tests** | Assert no TS parsing in Phase 6 test code |
| **required_log_events_fields** | (none) |
| **codified_status** | **no** — Phase 6 archived; methodology in archive only |

---

### AIR-012: MPEG-TS Sink Lifecycle & Format (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-012 |
| **normative_text** | Sink MUST support clean start, stop, teardown; Start idempotent if already running; Stop idempotent. Packets MUST be 188 bytes with 0x47 sync; PTS/DTS monotonically increasing; PCR 20-100ms; DTS ≤ PTS. Output MUST be valid H.264; SPS/PPS for IDR; bitrate within 10% of configured. Stream MUST be delivered over TCP; non-blocking writes; graceful disconnect. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | ARCH-main-MpegTSDomain-SINK010, ARCH-main-MpegTSDomain-SINK013, ARCH-main-MpegTSDomain-SINK014, ARCH-main-MpegTSDomain-SINK015 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/OutputContinuityContract.md`; `docs/legacy/air/contracts/MpegTSPlayoutSinkDomainContract.md` (to migrate) |
| **required_tests** | test_sink_lifecycle, test_sink_encoding, test_sink_streaming |
| **required_log_events_fields** | (none) |
| **codified_status** | **no** — legacy contract; pkg/air contracts cover output continuity; SINK-013/014/015 not fully migrated |

---

### AIR-013: Sink Timing (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-013 |
| **normative_text** | Sink MUST use MasterClock as sole time source. First frame MUST anchor PTS zero to current MasterClock; PTS MUST be monotonically increasing. Frame with future PTS MUST cause wait until scheduled time; MUST NOT output ahead of schedule. Frames beyond late threshold MUST be dropped. Stop MUST exit timing loop within 100ms; MUST NOT output frames after stop. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | ARCH-main-MpegTSTiming-T001, ARCH-main-MpegTSTiming-T002, ARCH-main-MpegTSTiming-T003, ARCH-main-MpegTSTiming-T005, ARCH-main-MpegTSTiming-T007 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/OutputTimingContract.md`; `pkg/air/docs/contracts/semantics/MasterClockContract.md` |
| **required_tests** | test_sink_timing_clock_usage, test_sink_timing_pts_mapping, test_sink_timing_early_frames, test_sink_timing_late_drops, test_sink_timing_stop |
| **required_log_events_fields** | late_frame_drops |
| **codified_status** | **partial** — OutputTimingContract exists; legacy T-* rules not all migrated |

---

### AIR-014: Empty Buffer / Underrun (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-014 |
| **normative_text** | Empty buffer MUST increment buffer_empty_count / buffer_underruns; sink MUST back off (2-5ms); MUST NOT spin or high CPU. Sink MUST resume when frames available. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | ARCH-main-MpegTSDomain-SINK020, ARCH-main-MpegTSTiming-T004 |
| **where_it_belongs** | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md`; `pkg/air/docs/contracts/semantics/RealTimeHoldPolicy.md` |
| **required_tests** | test_sink_buffer_handling; start with empty buffer, verify counter and worker alive |
| **required_log_events_fields** | buffer_empty_count, buffer_underruns, sink_buffer_empty_total |
| **codified_status** | **partial** — INV-P10 covers backpressure; SINK-020/T-004 in legacy |

---

### AIR-015: Late Frames, Backpressure, Disconnect, Fault (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-015 |
| **normative_text** | Frames beyond threshold MUST be dropped; late_frames and frames_dropped MUST increment. Backpressure MUST be handled gracefully; queue bounded; no deadlock or crash. Client disconnect MUST be detected; resources cleaned up; reconnection MUST work. Fault state MUST persist until explicit reset; MUST NOT auto-recover. Recoverable errors MUST be logged; counters updated; operation MUST continue. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | ARCH-main-MpegTSDomain-SINK021, ARCH-main-MpegTSDomain-SINK022, ARCH-main-MpegTSDomain-SINK023, ARCH-main-MpegTSDomain-SINK030, ARCH-main-MpegTSDomain-SINK031 |
| **where_it_belongs** | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md`; `docs/legacy/air/contracts/MpegTSPlayoutSinkDomainContract.md` |
| **required_tests** | test_sink_buffer_handling, test_sink_network_handling, test_sink_error_handling |
| **required_log_events_fields** | late_frames, frames_dropped, sink_late_frames_total, sink_frames_dropped_total, sink_encoding_errors_total, sink_network_errors_total, sink_status |
| **codified_status** | **no** — legacy SINK-0xx; INV-P10 covers some; SINK-021/022/023/030/031 not fully codified |

---

### AIR-016: Orchestration Loop (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | AIR-016 |
| **normative_text** | Tick skew MUST remain within ±1ms for 99% of ticks; producer→renderer latency p95 MUST be ≤ 33ms; missed MasterClock callback MUST trigger immediate catch-up tick. Underrun MUST restore within ≤3 ticks; overrun MUST drain within ≤3 ticks; recovery time MUST be ≤ 100ms. Starvation MUST be detected within ≤100ms; teardown MUST complete within ≤500ms. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | ARCH-main-Orch-ORCH001, ARCH-main-Orch-ORCH002, ARCH-main-Orch-ORCH003 |
| **where_it_belongs** | `pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md`; `docs/legacy/air/contracts/OrchestrationLoopDomainContract.md` |
| **required_tests** | (harness missing) |
| **required_log_events_fields** | orchestration_tick_skew_ms, orchestration_latency_ms, orchestration_tick_violation_total, orchestration_backpressure_events_total, orchestration_backpressure_recovery_ms, orchestration_starvation_alert_total, orchestration_teardown_duration_ms |
| **codified_status** | **no** — legacy OrchestrationLoopDomainContract; ORCH_001/002/003 not in pkg/air |

---

## 3. Core Contracts (timeline / scheduling / channel mgmt)

### CORE-001: start_offset_ms Media-Relative Only

| Field | Value |
|-------|-------|
| **canonical_id** | CORE-001 |
| **normative_text** | `start_offset_ms` MUST be media-relative only; MUST NOT be wall-clock-relative. Air seeks by offset. |
| **scope** | both (Core produces; Air consumes) |
| **phase_applicability** | 4 |
| **sources** | ARCH-core-Phase4Pipeline-002 |
| **where_it_belongs** | `pkg/core/docs/archive/phases/Phase4-PlayoutPipelineContract.md`; `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` LoadPreview |
| **required_tests** | Assert start_offset_ms in segment is media position; not wall time |
| **required_log_events_fields** | (none) |
| **codified_status** | **yes** — Phase4; PlayoutEngineContract LoadPreview |

---

### CORE-002: PlayoutSegment Immutable; New Instance Per Invocation

| Field | Value |
|-------|-------|
| **canonical_id** | CORE-002 |
| **normative_text** | Every invocation MUST create new segment/request; MUST NOT mutate shared state. PlayoutSegment MUST be immutable once issued to Air; changes MUST require new segment and new LoadPreview. |
| **scope** | core |
| **phase_applicability** | 4, 5 |
| **sources** | ARCH-core-Phase4Pipeline-004, ARCH-core-Phase5CM-003 |
| **where_it_belongs** | `pkg/core/docs/archive/phases/Phase4-PlayoutPipelineContract.md`; `pkg/core/docs/archive/phases/Phase5-ChannelManagerContract.md`; `pkg/core/docs/contracts/resources/ChannelManagerContract.md` |
| **required_tests** | Assert each call returns new instance; CM never mutates issued segment |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — Phase4/5 archived; ChannelManagerContract exists but may not state immutability |

---

### CORE-003: Prefeed Window

| Field | Value |
|-------|-------|
| **canonical_id** | CORE-003 |
| **normative_text** | ChannelManager MUST issue LoadPreview for next segment no later than `hard_stop_time_ms - prefeed_window_ms`. ChannelManager MUST issue SwitchToLive at the boundary (after LoadPreview for that segment). ChannelManager MUST NOT wait for Air to ask for next segment; CM MUST drive the timeline. ChannelManager MUST NOT issue duplicate LoadPreview for the same next segment when re-evaluating multiple times before boundary. |
| **scope** | core |
| **phase_applicability** | 5 |
| **sources** | ARCH-core-Phase5CM-001, ARCH-core-Phase5CM-002, ARCH-core-Phase5CM-004, ARCH-core-Phase5CM-005 |
| **where_it_belongs** | `pkg/core/docs/archive/phases/Phase5-ChannelManagerContract.md`; `pkg/core/docs/contracts/resources/ChannelManagerContract.md` |
| **required_tests** | LoadPreview timestamp <= hard_stop_time_ms - prefeed_window_ms; SwitchToLive at boundary; at most one LoadPreview per next segment |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — Phase5 archived; ChannelManagerContract has HTTP/startup; prefeed semantics not fully codified |

---

### CORE-004: SchedulePlan Structure

| Field | Value |
|-------|-------|
| **canonical_id** | CORE-004 |
| **normative_text** | Mock SchedulePlan MUST have exactly two items per grid in order: A (samplecontent), B (filler). SchedulePlan MUST be duration-free; no duration or timing fields in plan. |
| **scope** | core |
| **phase_applicability** | 2 |
| **sources** | ARCH-core-Phase2Plan-001, ARCH-core-Phase2Plan-002 |
| **where_it_belongs** | `pkg/core/docs/archive/phases/Phase2-SchedulePlanContract.md`; `pkg/core/docs/contracts/resources/SchedulePlan*.md` |
| **required_tests** | Each grid has two items in correct order; plan has no duration/offset/timing fields |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — Phase2 archived; SchedulePlan contracts exist for add/list/show |

---

### CORE-005: Asset Metadata

| Field | Value |
|-------|-------|
| **canonical_id** | CORE-005 |
| **normative_text** | `duration_ms` MUST be authoritative; measured once; rounded down to integer milliseconds. `duration_ms` MUST NOT be recomputed in runtime logic; MUST NOT be inferred from offsets or schedules. Asset objects MUST be immutable. |
| **scope** | core |
| **phase_applicability** | 2.5 |
| **sources** | ARCH-core-Phase2_5Asset-001, ARCH-core-Phase2_5Asset-002, ARCH-core-Phase2_5Asset-003 |
| **where_it_belongs** | `pkg/core/docs/contracts/resources/AssetContract.md`; `pkg/core/docs/archive/phases/Phase2.5-AssetMetadataContract.md` |
| **required_tests** | duration_ms is int, > 0; Phase 3/4 use asset.duration_ms; no probing at runtime; Asset frozen |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — AssetContract exists; Phase2.5 duration rules not fully in canonical AssetContract |

---

### CORE-006: Active Item Resolver

| Field | Value |
|-------|-------|
| **canonical_id** | CORE-006 |
| **normative_text** | Resolver MUST assert `grid_duration_ms == Phase 1 grid_duration`; mismatch MUST be configuration error (fail fast). `elapsed_in_grid_ms < filler_start_ms` → samplecontent; `elapsed_in_grid_ms >= filler_start_ms` → filler. |
| **scope** | core |
| **phase_applicability** | 3 |
| **sources** | ARCH-core-Phase3Resolver-001, ARCH-core-Phase3Resolver-002 |
| **where_it_belongs** | `pkg/core/docs/contracts/runtime/ScheduleManagerContract.md`; `pkg/core/docs/archive/phases/Phase3-ActiveItemResolverContract.md` |
| **required_tests** | Mismatch causes fail fast; 1_498_000 → samplecontent; 1_499_000 → filler |
| **required_log_events_fields** | (none) |
| **codified_status** | **partial** — ScheduleManager* contracts; Phase3 resolver semantics in archive |

---

### CORE-007: Phase 7 Scope

| Field | Value |
|-------|-------|
| **canonical_id** | CORE-007 |
| **normative_text** | Phase 7 MUST be the only phase requiring HTTP tune-in, real ffmpeg, and long-running behaviour. Phases 0–6 use direct ProgramDirector API. |
| **scope** | both |
| **phase_applicability** | 7 |
| **sources** | ARCH-core-Phase7E2E-001 |
| **where_it_belongs** | `pkg/core/docs/archive/phases/Phase7-E2EAcceptanceContract.md`; `docs/ComponentMap.md` |
| **required_tests** | Phases 0-6 use direct API; Phase 7 uses GET /channel/{id}.ts |
| **required_log_events_fields** | (none) |
| **codified_status** | **no** — Phase7 archived; ComponentMap may reference |

---

## 4. Observability + Telemetry Requirements

### OBS-001: gRPC Response Fields

| Field | Value |
|-------|-------|
| **canonical_id** | OBS-001 |
| **normative_text** | LoadPreviewResponse SHOULD include `shadow_decode_started` when applicable. SwitchToLiveResponse SHOULD include `pts_contiguous` when implemented. |
| **scope** | air |
| **phase_applicability** | 6, 6A |
| **sources** | ARCH-air-Phase6-004, ARCH-air-Phase6-005 |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; §SwitchToLive |
| **required_tests** | Assert LoadPreviewResponse.shadow_decode_started; SwitchToLiveResponse.pts_contiguous |
| **required_log_events_fields** | LoadPreviewResponse.shadow_decode_started, SwitchToLiveResponse.pts_contiguous |
| **codified_status** | **yes** — PlayoutEngineContract defines response fields |

---

### MET-001: Playout Metrics (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | MET-001 |
| **normative_text** | Playout engine SHOULD export: retrovue_playout_channel_state, retrovue_playout_buffer_depth_frames, retrovue_playout_frame_gap_seconds, retrovue_playout_decode_failure_count, retrovue_playout_frames_decoded_total, retrovue_playout_frames_dropped_total, retrovue_playout_buffer_underrun_total, retrovue_playout_decode_latency_seconds, retrovue_playout_channel_uptime_seconds. All metrics include `channel` label. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | PlayoutEngineContract Part 2; ARCH-main-MpegTSDomain-Telemetry |
| **where_it_belongs** | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §Part 2 Telemetry; `pkg/air/docs/contracts/semantics/MetricsAndTimingContract.md` |
| **required_tests** | Assert metrics exported; PE-TEL-001 through PE-TEL-004 |
| **required_log_events_fields** | retrovue_playout_* metrics |
| **codified_status** | **partial** — PlayoutEngineContract defines; enforcement deferred Phase 7+ |

---

### MET-002: Sink Telemetry (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | MET-002 |
| **normative_text** | Sink SHOULD export: sink_frames_sent_total, sink_frames_dropped_total, sink_late_frames_total, sink_encoding_errors_total, sink_network_errors_total, sink_buffer_empty_total, sink_running, sink_status. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | ARCH-main-MpegTSDomain-Telemetry |
| **where_it_belongs** | `docs/legacy/air/contracts/MpegTSPlayoutSinkDomainContract.md` §Telemetry; to migrate to `pkg/air/docs/contracts/semantics/MetricsExportContract.md` |
| **required_tests** | Assert metrics exported |
| **required_log_events_fields** | sink_frames_sent_total, sink_frames_dropped_total, sink_late_frames_total, sink_encoding_errors_total, sink_network_errors_total, sink_buffer_empty_total, sink_running, sink_status |
| **codified_status** | **no** — legacy MpegTSPlayoutSinkDomainContract; not in pkg/air MetricsExportContract |

---

### OBS-002: Orchestration Telemetry (Phase 7+)

| Field | Value |
|-------|-------|
| **canonical_id** | OBS-002 |
| **normative_text** | Orchestration loop SHOULD export: orchestration_tick_skew_ms, orchestration_latency_ms, orchestration_tick_violation_total, orchestration_backpressure_events_total, orchestration_backpressure_recovery_ms, orchestration_starvation_alert_total, orchestration_teardown_duration_ms. |
| **scope** | air |
| **phase_applicability** | 7+ |
| **sources** | ARCH-main-Orch-ORCH001, ARCH-main-Orch-ORCH002, ARCH-main-Orch-ORCH003 |
| **where_it_belongs** | `docs/legacy/air/contracts/OrchestrationLoopDomainContract.md`; to migrate to pkg/air |
| **required_tests** | (harness missing) |
| **required_log_events_fields** | orchestration_tick_skew_ms, orchestration_latency_ms, orchestration_tick_violation_total, orchestration_backpressure_events_total, orchestration_backpressure_recovery_ms, orchestration_starvation_alert_total, orchestration_teardown_duration_ms |
| **codified_status** | **no** — legacy only |

---

## Summary: Codified Status

| Status | Count | IDs |
|--------|-------|-----|
| **yes** | 12 | LAW-001, LAW-002, LAW-003, LAW-006, AIR-001 through AIR-007, CORE-001, OBS-001 |
| **partial** | 12 | LAW-004, LAW-007, AIR-009, AIR-010, AIR-013, AIR-014, CORE-002, CORE-003, CORE-004, CORE-005, CORE-006, MET-001 |
| **no** | 10 | LAW-005, AIR-011, AIR-012, AIR-015, AIR-016, CORE-007, MET-002, OBS-002 |

**Partial — what's missing:**
- LAW-004: Grid math explicit in ScheduleManager* as invariant
- LAW-007: E2E harness / long-run drift test
- AIR-009: ProgrammaticProducer explicit in ProducerBusContract
- AIR-010: Air does not enforce; Core prefeed tests
- AIR-013: Legacy T-* rules migration to OutputTimingContract
- AIR-014: SINK-020/T-004 migration to INV-P10
- CORE-002: ChannelManagerContract immutability clause
- CORE-003: Prefeed semantics in ChannelManagerContract
- CORE-004: Phase2 structure in SchedulePlan contracts
- CORE-005: Phase2.5 duration rules in AssetContract
- CORE-006: Phase3 resolver in ScheduleManager
- MET-001: Phase 7+ enforcement of metrics presence
