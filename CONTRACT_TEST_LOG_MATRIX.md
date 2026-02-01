# Contract Test Log Matrix

**Scope:** Phase 6A + Phase 8 switching semantics  
**Purpose:** Map canonical rules to test coverage, assertions, and log evidence.  
**Traceability:** CANONICAL_RULE_LEDGER.md · ObservabilityParityLaw.md · PlayoutEngineContract.md Part 2.5

---

## Legend

| Status | Meaning |
|--------|---------|
| **exists** | Test exists and asserts the rule (log evidence may or may not be asserted) |
| **missing** | No test exists for the rule |
| **partial** | Test exists but asserts only part of the rule (e.g., gRPC outcome, not log events) |

---

## 1. Laws / Invariants (Phase 6A + Phase 8 scope)

| canonical_id | contract/law location | test file path | test asserts | log evidence asserted | status |
|--------------|----------------------|----------------|--------------|------------------------|--------|
| LAW-001 | `pkg/air/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md` §1 Clock; `pkg/core/docs/contracts/resources/MasterClockContract.md` | `pkg/air/tests/contracts/MasterClock/MasterClockContractTests.cpp` · `pkg/core/tests/contracts/test_masterclock_contract.py` | MasterClock is sole time source; components consume via interface; no direct time.time()/datetime.now() for scheduling | (none) | exists |
| LAW-002 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; FileProducerContract | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` (Phase6A2_HardStopEnforced — SKIP per Phase 8.6) | Producer stops at or before hard_stop_time_ms; no output past boundary | (none) | partial (skipped) |
| LAW-003 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §THINK vs ACT; Phase6A-Overview | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` | StartChannel alone → no decode; LoadPreview precedes SwitchToLive; execution begins only after LoadPreview + SwitchToLive | (none) | exists |
| LAW-006 | `pkg/air/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md` §5 Switching; OutputContinuityContract | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` BC_006_FramePtsRemainMonotonic; BC_007_DualProducerSwitchingSeamlessness | PTS strictly increasing; no gaps/regression during switch; pts_contiguous in SwitchToLiveResponse | (none) | exists |
| LAW-OBS-001 | `pkg/air/docs/contracts/laws/ObservabilityParityLaw.md` §1 | NONE | Every intent (StartChannel, LoadPreview, SwitchToLive, etc.) MUST be observable in Air logs | AIR-*-RECEIVED events for each RPC | **missing** |
| LAW-OBS-002 | `pkg/air/docs/contracts/laws/ObservabilityParityLaw.md` §2 | NONE | correlation_id MUST appear in both Core and Air logs for each call | correlation_id in CORE-INTENT-ISSUED, AIR-*-RECEIVED, AIR-*-RESPONSE | **missing** |
| LAW-OBS-003 | `pkg/air/docs/contracts/laws/ObservabilityParityLaw.md` §3 | NONE | Every Air response MUST be logged with correlation_id, success, result_code | AIR-*-RESPONSE with correlation_id, success, result_code, completion_time_ms | **missing** |
| LAW-OBS-004 | `pkg/air/docs/contracts/laws/ObservabilityParityLaw.md` §4 | NONE | Receipt, effective, completion time for LoadPreview and SwitchToLive | receipt_time_ms, effective_time_ms, completion_time_ms in appropriate events | **missing** |
| LAW-OBS-005 | `pkg/air/docs/contracts/laws/ObservabilityParityLaw.md` §5 | NONE | Hard-stop clamp MUST produce explicit logs (started, active, ended) | AIR-CLAMP-STARTED, AIR-CLAMP-ACTIVE, AIR-CLAMP-ENDED with channel_id, asset_path, boundary_ms | **missing** |

---

## 2. Air Contracts — Control Surface (Phase 6A.0)

| canonical_id | contract/law location | test file path | test asserts | log evidence asserted | status |
|--------------|----------------------|----------------|--------------|------------------------|--------|
| AIR-001 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §Service Definition; proto | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A0_ServerAcceptsFourRPCs | Build links proto; StartChannel, LoadPreview, SwitchToLive, StopChannel accept requests; plan_handle not interpreted | (none) | exists |
| AIR-002 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §Idempotency; PE-START-002, PE-STOP-002 | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A0_StartChannelIdempotentSuccess, Phase6A0_StopChannelIdempotentSuccess; BC_003_ControlOperationsAreIdempotent | StartChannel twice → both success; StopChannel on unknown/stopped → success | (none) | exists |
| AIR-003 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; PE-CTL-001 | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A0_LoadPreviewBeforeStartChannel_Error | LoadPreview without StartChannel → success=false | (none) | exists |
| AIR-004 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §SwitchToLive; PE-CTL-002 | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A0_SwitchToLiveWithNoPreview_Error | SwitchToLive without LoadPreview → success=false | (none) | exists |
| AIR-005 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; §SwitchToLive; ProducerBusContract | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A1_LoadPreviewInstallsIntoPreviewSlot_LiveUnchanged, Phase6A1_SwitchToLivePromotesPreview_StopsOldLive_ClearsPreview; BC_007 | LoadPreview → preview slot; live unchanged until SwitchToLive; SwitchToLive promotes preview, stops old live, clears preview | (none) | exists |
| AIR-006 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §THINK vs ACT; ProducerBusContract | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A1_*; `pkg/air/tests/contracts/PlayoutControl/PlayoutControlContractTests.cpp` | Engine owns slots; producers passive; no self-switch | (none) | exists |
| AIR-007 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §StopChannel; PE-STOP-001 | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` BC_005_ChannelStopReleasesResources; Phase6A1_StopReleasesProducer_ObservableStoppedState | No frames after StopChannel; resources released; producer stopped | (none) | exists |
| AIR-008 | `pkg/air/docs/contracts/semantics/FileProducerContract.md` | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A2_SegmentParamsPassedToFileBackedProducer, Phase6A2_InvalidPath_LoadPreviewFails; `pkg/air/tests/contracts/file_producer/FileProducerContractTests.cpp` | Producer receives start_offset_ms, hard_stop_time_ms; invalid path → success=false | (none) | exists |
| AIR-009 | `pkg/air/docs/contracts/coordination/ProducerBusContract.md` | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` Phase6A3_*, Phase6A3_SwitchBetweenFileBackedAndProgrammatic | Alternation FileBacked ↔ Programmatic; ProgrammaticProducer no ffmpeg | (none) | exists |

---

## 3. Air Contracts — Phase 8 Switching Invariants

| canonical_id | contract/law location | test file path | test asserts | log evidence asserted | status |
|--------------|----------------------|----------------|--------------|------------------------|--------|
| INV-P8-SWITCH-ARMED | `pkg/air/docs/contracts/semantics/Phase8-Invariants-Compiled.md` §4; PlayoutEngine.cpp | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` INV_P8_SWITCH_ARMED_LoadPreviewRejectedWhileSwitchArmed | LoadPreview while switch armed → RESULT_CODE_REJECTED_BUSY; switch eventually completes | (none) | exists |
| INV-P8-EOF-SWITCH | `pkg/air/docs/contracts/semantics/Phase8-Invariants-Compiled.md` §4 | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` INV_P8_EOF_SWITCH_SwitchCompletesWhenLiveReachesEOF | Live producer EOF → switch completes (no indefinite stall) | (none) | exists |
| INV-P8-AUDIO-GATE | `pkg/air/docs/contracts/semantics/Phase8-Invariants-Compiled.md` §3, §4 | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` INV_P8_AUDIO_GATE_ReadinessTripsAfterShadowDisabled | Readiness trips within bounded time after switch armed; audio gating does not block indefinitely | (none) | exists |
| INV_001 (fallback) | BlackFrameProducerContract; DeterministicHarness | `pkg/air/tests/contracts/DeterministicHarness/DeterministicHarnessContractTests.cpp` INV_001_*, INV_001b_* | Fallback ONLY on producer exhaustion; planned transitions NEVER trigger fallback | (none) | exists |
| INV_002 | BlackFrameProducerContract | `pkg/air/tests/contracts/DeterministicHarness/DeterministicHarnessContractTests.cpp` INV_002_* | Fallback persists until explicit LoadPreview + SwitchToLive | (none) | exists |

---

## 4. Output Switching (Phase 8)

| canonical_id | contract/law location | test file path | test asserts | log evidence asserted | status |
|--------------|----------------------|----------------|--------------|------------------------|--------|
| OS-001 | `pkg/air/docs/contracts/` OutputSwitchingContract | `pkg/air/tests/contracts/OutputSwitching/OutputSwitchingContractTests.cpp` OS_001_OutputReadsFromExactlyOneBuffer | Output consumes from exactly one buffer at a time | (none) | exists |
| OS-002 | OutputSwitchingContract | `pkg/air/tests/contracts/OutputSwitching/OutputSwitchingContractTests.cpp` OS_002_HotSwitchIsImmediate | Switch is immediate; first preview frame within 50ms | (none) | exists |
| OS-003 | OutputSwitchingContract | `pkg/air/tests/contracts/OutputSwitching/OutputSwitchingContractTests.cpp` OS_003_PreviewMustHaveFramesBeforeSwitch | Preview must have frames before switch | (none) | exists |
| OS-004 | OutputSwitchingContract | `pkg/air/tests/contracts/OutputSwitching/OutputSwitchingContractTests.cpp` OS_004_SwitchDoesNotDrainOldBuffer | Switch completes in &lt; 10ms (no drain wait) | (none) | exists |
| OS-005 | OutputSwitchingContract | `pkg/air/tests/contracts/OutputSwitching/OutputSwitchingContractTests.cpp` OS_005_SwitchOccursOnDecodedFrames | Switch at decoded frame level; encoder sees continuous stream | (none) | exists |
| OS-006 | OutputSwitchingContract | `pkg/air/tests/contracts/OutputSwitching/OutputSwitchingContractTests.cpp` OS_006_* | Live and Preview have separate buffers; isolation | (none) | exists |

---

## 5. Observability Requirements (PlayoutEngineContract Part 2.5)

| rule / event set | contract/law location | test file path | test asserts | log evidence asserted | status |
|------------------|----------------------|----------------|--------------|------------------------|--------|
| StartChannel log events | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` Part 2.5 | NONE | AIR-STARTCHANNEL-RECEIVED, AIR-STARTCHANNEL-RESPONSE with required fields | channel_id, correlation_id, receipt_time_ms, result_code, completion_time_ms | **missing** |
| LoadPreview log events | PlayoutEngineContract Part 2.5 | NONE | AIR-LOADPREVIEW-RECEIVED, AIR-LOADPREVIEW-EFFECTIVE, AIR-LOADPREVIEW-RESPONSE | channel_id, correlation_id, asset_path, start_offset_ms, hard_stop_time_ms, receipt_time_ms, effective_time_ms, completion_time_ms, result_code | **missing** |
| SwitchToLive log events | PlayoutEngineContract Part 2.5 | NONE | AIR-SWITCHTOLIVE-RECEIVED, AIR-SWITCHTOLIVE-EFFECTIVE, AIR-SWITCHTOLIVE-RESPONSE | channel_id, correlation_id, receipt_time_ms, effective_time_ms, completion_time_ms, result_code | **missing** |
| Producer clamp log events | PlayoutEngineContract Part 2.5; LAW-OBS-005 | NONE | AIR-CLAMP-STARTED, AIR-CLAMP-ACTIVE, AIR-CLAMP-ENDED | channel_id, asset_path, boundary_time, correlation_id, segment_correlation_id, next_correlation_id | **missing** |
| Black/silence fallback | PlayoutEngineContract Part 2.5 | NONE | AIR-FALLBACK-ENTERED, AIR-FALLBACK-EXITED | channel_id, reason, asset_path | **missing** |
| Mux/sink attach/detach | PlayoutEngineContract Part 2.5 | NONE | AIR-ATTACHSTREAM-*, AIR-DETACHSTREAM-* | channel_id, correlation_id, endpoint, receipt_time_ms, result_code, completion_time_ms | **missing** |
| Required fields catalog | PlayoutEngineContract Part 2.5 | NONE | All events include channel_id; receive/response include correlation_id, result_code; segment events include segment_id, asset_path, boundary_time; state_transitions on channel state change | channel_id, segment_id, asset_path, start_offset_ms, hard_stop_time_ms, boundary_time, correlation_id, result_code, state_transitions, receipt_time_ms, completion_time_ms, effective_time_ms | **missing** |

---

## 6. Observability Rule (OBS-001)

| canonical_id | contract/law location | test file path | test asserts | log evidence asserted | status |
|--------------|----------------------|----------------|--------------|------------------------|--------|
| OBS-001 | `pkg/air/docs/contracts/semantics/PlayoutEngineContract.md` §LoadPreview; §SwitchToLive | `pkg/air/tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp` LT_005_*, LT_006_*, Phase6A0_*, Phase83_* | LoadPreviewResponse.shadow_decode_started; SwitchToLiveResponse.pts_contiguous (when implemented) | (gRPC response fields, not logs) | partial |

---

## 7. Missing Harness Capabilities

The following harness capabilities are **required** to test observability rules but are **not present** in the current test infrastructure:

| Capability | Description | Blocks |
|------------|-------------|--------|
| **Log capture** | Tests cannot capture or intercept Air (or Core) process stdout/stderr or structured log output. Log assertions require either: (a) redirecting process logs to a sink the test can read, or (b) injecting a log observer/callback that the engine calls on each log event. | LAW-OBS-001 through LAW-OBS-005; PlayoutEngineContract Part 2.5 log events |
| **Correlation ID injection** | Tests issue gRPC calls without attaching `correlation_id` (metadata or proto). No mechanism to pass correlation_id and assert it appears in Air logs. | LAW-OBS-002; log event correlation |
| **Log transcript parsing** | No parser or matcher for structured log lines (e.g., `AIR-LOADPREVIEW-RECEIVED correlation_id=...`). Tests would need a way to parse captured log output and assert on event names and fields. | All log evidence assertions |
| **Process subprocess log capture** | Core tests spawn ChannelManager/Air as subprocesses. If Air logs to stdout/stderr, tests could capture subprocess output; current tests do not assert on captured log content. | LAW-OBS-* when running full Core→Air flow |
| **Deterministic log timing** | Timing evidence (receipt_time_ms, effective_time_ms, completion_time_ms) requires deterministic or mockable clock so tests can assert time fields are present and coherent. TestMasterClock exists; log emission must use it. | LAW-OBS-004 |

---

## 8. Summary

| Category | Rules in scope | Exists | Partial | Missing |
|----------|----------------|--------|---------|---------|
| Laws (LAW-*) | 9 | 4 | 1 | 4 |
| Air control (AIR-*) | 9 | 9 | 0 | 0 |
| Phase 8 switching | 5+ | 5+ | 0 | 0 |
| Output switching (OS-*) | 6 | 6 | 0 | 0 |
| Observability (LAW-OBS-*, Part 2.5) | 10 | 0 | 0 | 10 |
| **Total** | ~39 | ~24 | ~1 | ~14 |

**Critical gap:** No tests assert on log events. All LAW-OBS-* rules and PlayoutEngineContract Part 2.5 observability requirements are untested. Implementing log capture + parsing in the contract test harness is prerequisite for closing this gap.
