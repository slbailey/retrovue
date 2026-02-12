# Coverage Gap Remediation Plan

**Status:** Actionable
**Source:** Canonical Rule Ledger + GAP_REPORT analysis
**Last Updated:** 2026-02-01

Based on Canonical Rule Ledger (Test/Log columns) and GAP_REPORT analysis.

---

## Layer 0 — Constitutional Laws

| Rule ID | Missing Coverage | Recommended Action | Owner | Why This Matters Operationally |
|---------|------------------|-------------------|-------|-------------------------------|
| **LAW-AUDIO-FORMAT** | Test=No, Log=No | **ADD TEST** | AIR | Without test, house format violations could cause encoder failures or audio glitches mid-playout. Init-time check prevents runtime surprises. |
| **LAW-FRAME-EXECUTION** | Test=No, Log=No | **DEFER** | AIR | Reclassified to CONTRACT. P10 enforcement. Frame-indexed execution is architectural; test coverage belongs with INV-FRAME-* contracts. |
| **LAW-OBS-001 through LAW-OBS-005** | Test=No | **DEFER** | AIR | Observability laws are meta-rules. Enforcement is via code review and audit, not runtime tests. Log presence IS the test. |
| **LAW-001** (GAP) | No static enforcement of "no datetime.now()" | **ADD TEST** | AIR | Accidental system clock usage causes time drift; viewer sees jumps or freezes. Static analysis catches violations before they ship. |
| **LAW-002** (GAP) | No test for "no output after hard_stop_time_ms" | **ADD BOTH** | AIR (FileProducer) | Overrun past hard stop causes content collision with next segment; viewer sees jarring cut or overlap. Log marks the clamp event. |
| **LAW-004** (GAP) | SM-001–SM-010 tests may not exist | **ADD TEST** | Core | Schedule invariant violations cause gaps or overlaps in EPG; viewer sees wrong content at wrong time. |
| **LAW-005** (GAP/Conflict) | Conflict with ScheduleManager filler semantics | **DEFER** | Core | Conflict must be resolved first. Frame-based execution is canonical; legacy continuous-offset rule is superseded. |
| **LAW-006** (GAP) | PTS monotonicity test missing | **ADD TEST** | AIR | PTS regression causes decoder to drop frames or freeze; viewer sees stutter or black screen. |
| **LAW-007** (GAP) | E2E drift test not in suite | **DEFER** | Core+AIR | Phase 7 scope. E2E tests require full HTTP stack. Add when Phase 7 harness exists. |

---

## Layer 1 — Semantic Invariants

| Rule ID | Missing Coverage | Recommended Action | Owner | Why This Matters Operationally |
|---------|------------------|-------------------|-------|-------------------------------|
| **INV-SEGMENT-CONTENT-001** | Test=No | **DEFER** | Core | SCHEDULE-TIME enforcement. Core plan generation tests belong in Core contract suite, not AIR. |
| **INV-P8-012** | Test=No, Log=No | **ADD TEST** | TimelineController | Deterministic replay is testable with mock inputs. Critical for debugging: same inputs must produce same CT sequence. |
| **INV-P10-REALTIME-THROUGHPUT** | Test=No | **ADD TEST** | ProgramOutput | Throughput deviation means viewer sees stuttering or frame drops. Test validates output rate matches fps. |
| **INV-P10-CONTENT-BLIND** | Test=No, Log=No | **DEFER** | ProgramOutput | Architectural constraint. "No pixel heuristics" is code-review enforced, not runtime testable. |
| **INV-FRAME-001** | Test=No, Log=No | **DEFER** | Core | SCHEDULE-TIME. Frame-indexed boundaries are Core plan structure, not AIR runtime. |
| **INV-FRAME-002** | Test=No, Log=No | **DEFER** | Core | SCHEDULE-TIME. Padding in frames is Core plan structure. |
| **INV-FRAME-003** | Test=No, Log=No | **ADD TEST** | TimelineController | CT derivation formula is testable: `ct = epoch + (frame_index × frame_duration)`. Violation causes drift. |
| **INV-P10-FRAME-INDEXED-EXECUTION** | Test=No, Log=No | **ADD TEST** | FileProducer | Producer tracking by frame index (not elapsed time) prevents drift. Testable with mock clock. |
| **INV-AUDIO-HOUSE-FORMAT-001** | Test=No | **ADD TEST** | EncoderPipeline | Derives from LAW-AUDIO-FORMAT. Test that non-house input is rejected at encoder boundary. |

---

## Layer 2 — Coordination Invariants

| Rule ID | Missing Coverage | Recommended Action | Owner | Why This Matters Operationally |
|---------|------------------|-------------------|-------|-------------------------------|
| **INV-P8-IO-UDS-001** | Test=No, Log=No | **ADD TEST** | MpegTSOutputSink | UDS blocking on prebuffer causes startup deadlock. Test validates prebuffer disabled for UDS path. |
| **INV-P10-BACKPRESSURE-SYMMETRIC** | Test=No | **ADD TEST** | FileProducer, FrameRingBuffer | Asymmetric backpressure causes A/V desync. Test validates both streams throttled together. |
| **INV-P10-PRODUCER-THROTTLE** | Test=No | **ADD TEST** | FileProducer | Unthrottled producer overflows buffer. Test validates decode rate governed by consumer capacity. |
| **INV-P10-BUFFER-EQUILIBRIUM** | Test=No | **ADD TEST** | FrameRingBuffer | Buffer runaway causes memory exhaustion or starvation. Test validates depth oscillates around target. |
| **INV-P10-NO-SILENCE-INJECTION** | Test=No, Log=No | **ADD TEST** | MpegTSOutputSink | Silence injection when PCR-paced causes audio glitches. Test validates audio liveness disabled when PCR active. |
| **INV-P10-SINK-GATE** | Test=No, Log=No | **ADD TEST** | ProgramOutput | Consuming frames before sink attached causes lost frames. Test validates gate prevents early consumption. |
| **INV-OUTPUT-READY-BEFORE-LIVE** | Test=No | **ADD TEST** | PlayoutEngine | Entering LIVE before output observable means viewer sees nothing. Test validates output pipeline ready. |
| **INV-SWITCH-READINESS** | Test=No | **ADD TEST** | PlayoutEngine | Premature switch causes glitches. Test validates video≥2, sink attached, format locked. |
| **RULE-P10-DECODE-GATE** | Test=No | **ADD TEST** | FileProducer | Without decode gate, buffer overflow crashes playout. Test validates slot-based blocking. |

---

## Layer 3 — Diagnostic Invariants

| Rule ID | Missing Coverage | Recommended Action | Owner | Why This Matters Operationally |
|---------|------------------|-------------------|-------|-------------------------------|
| **INV-P8-WRITE-BARRIER-DIAG** | Test=No | **DEFER** | FileProducer | Diagnostic rules are log-only by design. Log=Yes is sufficient. Test would be redundant with log assertion. |
| **INV-P8-AUDIO-PRIME-STALL** | Test=No | **DEFER** | MpegTSOutputSink | Diagnostic log-only. Stall detection is observability, not testable behavior. |
| **INV-P10-FRAME-DROP-POLICY** | Test=No | **DEFER** | ProgramOutput | Diagnostic log-only. Drop logging is observability. Policy is "no drops" which is tested elsewhere. |
| **INV-P10-PAD-REASON** | Test=No | **DEFER** | ProgramOutput | Diagnostic log-only. Pad classification is for debugging, not behavioral test. |
| **INV-NO-PAD-WHILE-DEPTH-HIGH** | Test=No | **ADD TEST** | ProgramOutput | This IS a violation detector. Test should trigger pad at high depth and verify violation logged. |

---

## Proposed Invariants (Pending Promotion)

| Rule ID | Missing Coverage | Recommended Action | Owner | Why This Matters Operationally |
|---------|------------------|-------------------|-------|-------------------------------|
| **INV-SINK-TIMING-OWNERSHIP-001** | Test=No, Log=No | **ADD TEST** | MpegTSOutputSink | Timing loop ownership is testable with mock clock. Direct system clock access causes drift. |
| **INV-SINK-PIXEL-FORMAT-FAULT-001** | Test=No | **ADD TEST** | EncoderPipeline | Unsupported format without fault causes undefined behavior. Test validates fault state entry. |
| **INV-ENCODER-NO-B-FRAMES-001** | Test=No | **ADD TEST** | EncoderPipeline | B-frames in live output cause decode failures. Test validates `max_b_frames=0` and no B-frame output. |
| **INV-ENCODER-GOP-FIXED-001** | Test=No | **ADD TEST** | EncoderPipeline | Adaptive GOP breaks segment boundaries. Test validates keyframe interval is exactly `gop_size`. |
| **INV-ENCODER-BITRATE-BOUNDED-001** | Test=No | **ADD TEST** | EncoderPipeline | Bitrate spikes cause buffer overflow at muxer. Test validates rate within ±10% of target. |
| **INV-SINK-FAULT-LATCH-001** | Test=No | **ADD TEST** | MpegTSOutputSink | Silent fault recovery masks errors. Test validates fault persists until reset. |
| **INV-SINK-PRODUCER-THREAD-ISOLATION-001** | Test=No | **ADD TEST** | MpegTSOutputSink | Cross-thread blocking causes deadlock. Test validates bounded timeouts on cross-boundary ops. |
| **INV-LIFECYCLE-IDEMPOTENT-001** | Test=No | **ADD TEST** | Multiple | Double Start/Stop causes resource leaks or crashes. Test validates idempotent behavior. |
| **INV-TEARDOWN-BOUNDED-001** | Test=No | **ADD TEST** | MpegTSOutputSink | Unbounded teardown leaks resources. Test validates completion within timeout. |
| **INV-CONFIG-IMMUTABLE-001** | Test=No | **ADD TEST** | Multiple | Mid-session config change causes undefined behavior. Test validates rejection after construction. |
| **INV-SINK-ROLE-BOUNDARY-001** | Test=No, Log=No | **DEFER** | MpegTSOutputSink | ARCHITECTURE enforcement. Code review, not runtime test. |
| **INV-STARVATION-FAILSAFE-001** | Test=No | **ADD TEST** | ProgramOutput | Starvation without failsafe causes black screen. Test validates pad emission within bounded time. |
| **INV-TIMING-DESYNC-LOG-001** | Test=No | **ADD LOG** | MpegTSOutputSink | Diagnostic-only. Log presence IS the deliverable. Test that log appears when behind by threshold. |
| **INV-NETWORK-BACKPRESSURE-DROP-001** | Test=No | **ADD BOTH** | MpegTSOutputSink | Network blocking propagates back to timing. Test validates drop (not block) and log on backpressure. |

---

## Cross-Domain Rules

| Rule ID | Missing Coverage | Recommended Action | Owner | Why This Matters Operationally |
|---------|------------------|-------------------|-------|-------------------------------|
| **RULE-CORE-RUNTIME-READONLY** | Test=No, Log=No | **ADD TEST** | Core | Runtime mutation of config corrupts station state. Test validates write rejection. |
| **RULE-CORE-PLAYLOG-AUTHORITY** | Test=No, Log=No | **ADD TEST** | Core | ChannelManager writing playlog creates duplicate/conflicting as-run records. Test validates read-only. |
| **INV-P8-SWITCH-TIMING** | Test=No | **ADD LOG** | Core | Switch after boundary causes content collision. Log presence enables debugging. |

---

## GAP_REPORT: Missing Rules

| Rule ID | Missing Coverage | Recommended Action | Owner | Why This Matters Operationally |
|---------|------------------|-------------------|-------|-------------------------------|
| **AIR-005** (GAP) | shadow_decode_started not asserted | **ADD LOG** | PlayoutEngine | Optional response field. Add log when shadow decode starts for observability. |
| **AIR-007** (GAP) | "No orphan ffmpeg" not tested | **ADD BOTH** | PlayoutEngine | Orphan processes consume resources and may hold file locks. Test + log process list. |
| **AIR-009** (GAP) | ProgrammaticProducer tests missing | **DEFER** | ProducerBus | ProgrammaticProducer is test harness, not production path. Lower priority. |
| **AIR-010** (GAP) | legacy preload RPC timestamp < boundary not tested | **ADD BOTH** | Core | Late legacy preload RPC causes gap at switch. Test validates timing + log call timestamps. |
| **AIR-011** (GAP) | Phase 6 tests inspect TS bytes | **DEFER** | Test harness | Test methodology rule. Enforce via code review, not runtime. |
| **AIR-012** (GAP) | Sink lifecycle not in canonical doc | **ADD TEST** | MpegTSOutputSink | Already covered by INV-LIFECYCLE-IDEMPOTENT-001. Consolidate. |
| **AIR-013** (GAP/Conflict) | Timing clock conflict | **DEFER** | OutputTiming | Conflict must be resolved first. OutputTimingContract is authoritative. |
| **AIR-014** (GAP) | buffer_underruns metric missing | **ADD BOTH** | FrameRingBuffer | Underrun without metric is invisible. Add metric + log. |
| **AIR-015** (GAP) | Sink error handling not canonical | **ADD BOTH** | MpegTSOutputSink | Covered by proposed invariants. Need tests + logs. |
| **AIR-016** (GAP) | Orchestration loop metrics missing | **DEFER** | ProgramOutput | Orchestration loop model superseded by Phase 10 flow control. Metrics may be obsolete. |
| **CORE-002** (GAP) | Segment immutability not tested | **ADD TEST** | ChannelManager | Mutable segment causes race conditions. Test validates immutability after issue. |
| **CORE-003** (GAP) | Prefeed timing not tested | **ADD TEST** | ChannelManager | Late prefeed causes gap. Test validates legacy preload RPC before deadline. |
| **CORE-004** (GAP) | Mock plan structure not tested | **DEFER** | Core | Test infrastructure, not production rule. Lower priority. |
| **CORE-005** (GAP) | duration_ms authority not tested | **ADD TEST** | Core (Asset) | Duration recomputation causes scheduling errors. Test validates immutability. |
| **CORE-006** (GAP) | Resolver boundary logic not tested | **ADD TEST** | ScheduleManager | Wrong active item at boundary causes wrong content. Test validates filler_start_ms logic. |
| **CORE-007** (GAP) | Phase scope not documented | **DEFER** | Docs | Documentation, not code. Phase 7 scope is architectural guidance. |
| **MET-001** (GAP) | Metrics presence not tested | **DEFER** | PlayoutEngine | Phase 7+ scope. Defer until harness exists. |
| **MET-002** (GAP) | Sink metrics not in canonical doc | **ADD BOTH** | MpegTSOutputSink | Missing metrics are invisible failures. Add to MetricsExportContract + test. |
| **OBS-001** (GAP) | Optional response fields | **ADD LOG** | PlayoutEngine | Upgrade from optional to SHOULD. Log presence enables debugging. |
| **OBS-002** (GAP) | Orchestration metrics missing | **DEFER** | ProgramOutput | Orchestration loop model superseded. Evaluate if metrics still needed. |

---

## Summary by Action

| Action | Count | Rule IDs |
|--------|-------|----------|
| **ADD TEST** | 32 | LAW-AUDIO-FORMAT, LAW-001, LAW-004, LAW-006, INV-P8-012, INV-P10-REALTIME-THROUGHPUT, INV-FRAME-003, INV-P10-FRAME-INDEXED-EXECUTION, INV-AUDIO-HOUSE-FORMAT-001, INV-P8-IO-UDS-001, INV-P10-BACKPRESSURE-SYMMETRIC, INV-P10-PRODUCER-THROTTLE, INV-P10-BUFFER-EQUILIBRIUM, INV-P10-NO-SILENCE-INJECTION, INV-P10-SINK-GATE, INV-OUTPUT-READY-BEFORE-LIVE, INV-SWITCH-READINESS, RULE-P10-DECODE-GATE, INV-NO-PAD-WHILE-DEPTH-HIGH, INV-SINK-TIMING-OWNERSHIP-001, INV-SINK-PIXEL-FORMAT-FAULT-001, INV-ENCODER-NO-B-FRAMES-001, INV-ENCODER-GOP-FIXED-001, INV-ENCODER-BITRATE-BOUNDED-001, INV-SINK-FAULT-LATCH-001, INV-SINK-PRODUCER-THREAD-ISOLATION-001, INV-LIFECYCLE-IDEMPOTENT-001, INV-TEARDOWN-BOUNDED-001, INV-CONFIG-IMMUTABLE-001, INV-STARVATION-FAILSAFE-001, RULE-CORE-RUNTIME-READONLY, RULE-CORE-PLAYLOG-AUTHORITY, CORE-002, CORE-003, CORE-005, CORE-006 |
| **ADD LOG** | 4 | INV-TIMING-DESYNC-LOG-001, INV-P8-SWITCH-TIMING, AIR-005, OBS-001 |
| **ADD BOTH** | 6 | LAW-002, INV-NETWORK-BACKPRESSURE-DROP-001, AIR-007, AIR-010, AIR-014, MET-002 |
| **DEFER** | 18 | LAW-FRAME-EXECUTION, LAW-OBS-*, LAW-005, LAW-007, INV-SEGMENT-CONTENT-001, INV-P10-CONTENT-BLIND, INV-FRAME-001, INV-FRAME-002, INV-P8-WRITE-BARRIER-DIAG, INV-P8-AUDIO-PRIME-STALL, INV-P10-FRAME-DROP-POLICY, INV-P10-PAD-REASON, INV-SINK-ROLE-BOUNDARY-001, AIR-009, AIR-011, AIR-013, AIR-016, CORE-004, CORE-007, MET-001, OBS-002 |

---

## Priority Tiers

### Tier 1 — Broadcast-Critical (viewer-visible failures)

| Rule ID | Action | Rationale |
|---------|--------|-----------|
| LAW-002 | ADD BOTH | Overrun past hard stop causes content collision |
| LAW-006 | ADD TEST | PTS regression causes decoder freeze |
| INV-STARVATION-FAILSAFE-001 | ADD TEST | Starvation causes black screen |
| INV-NETWORK-BACKPRESSURE-DROP-001 | ADD BOTH | Network blocking propagates to timing |
| INV-ENCODER-NO-B-FRAMES-001 | ADD TEST | B-frames cause decode failures |
| INV-ENCODER-GOP-FIXED-001 | ADD TEST | Adaptive GOP breaks segment boundaries |

### Tier 2 — Operational Integrity (resource leaks, drift, corruption)

| Rule ID | Action | Rationale |
|---------|--------|-----------|
| INV-LIFECYCLE-IDEMPOTENT-001 | ADD TEST | Double Start/Stop causes leaks or crashes |
| INV-TEARDOWN-BOUNDED-001 | ADD TEST | Unbounded teardown leaks resources |
| AIR-007 | ADD BOTH | Orphan ffmpeg processes consume resources |
| RULE-CORE-RUNTIME-READONLY | ADD TEST | Runtime mutation corrupts station state |
| CORE-002 | ADD TEST | Mutable segment causes race conditions |
| CORE-003 | ADD TEST | Late prefeed causes gap at switch |

### Tier 3 — Flow Control (buffer management, backpressure)

| Rule ID | Action | Rationale |
|---------|--------|-----------|
| INV-P10-BACKPRESSURE-SYMMETRIC | ADD TEST | Asymmetric backpressure causes A/V desync |
| INV-P10-PRODUCER-THROTTLE | ADD TEST | Unthrottled producer overflows buffer |
| INV-P10-BUFFER-EQUILIBRIUM | ADD TEST | Buffer runaway causes memory exhaustion |
| RULE-P10-DECODE-GATE | ADD TEST | Without decode gate, buffer overflow crashes playout |
| AIR-014 | ADD BOTH | Underrun without metric is invisible |

### Tier 4 — Observability and Debugging

| Rule ID | Action | Rationale |
|---------|--------|-----------|
| INV-TIMING-DESYNC-LOG-001 | ADD LOG | Desync detection for debugging |
| INV-P8-SWITCH-TIMING | ADD LOG | Switch timing visibility |
| AIR-005 | ADD LOG | Shadow decode observability |
| OBS-001 | ADD LOG | Response field observability |
| MET-002 | ADD BOTH | Sink metrics for monitoring |

---

## Document References

| Document | Relationship |
|----------|--------------|
| `docs/contracts/CANONICAL_RULE_LEDGER.md` | Source of truth for rule coverage status |
| `GAP_REPORT.md` | Source of missing/weak/conflicting rules |
| `pkg/air/docs/contracts/PROPOSED-INVARIANTS-FROM-HARVEST.md` | Pending promotion invariants |

---

## Maintenance

When a gap is remediated:

1. Update the rule's Test/Log column in `CANONICAL_RULE_LEDGER.md`
2. Mark the row in this document as DONE
3. Update coverage summary percentages in the ledger
4. If promoting a proposed invariant, move it to the appropriate layer in the ledger
