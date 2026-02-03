# Layer 1 - Phase 8 Semantic Invariants

**Status:** Canonical
**Scope:** Truths about correctness and time - Phase 8 timeline, segment mapping, and output semantics
**Authority:** Refines Layer 0 Laws; does not override them

---

## Primitive Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-PACING-001** | CONTRACT | ProgramOutput | RUNTIME | Yes | Yes |
| **INV-PACING-ENFORCEMENT-002** | CONTRACT | ProgramOutput | RUNTIME | Yes | Yes |
| **INV-DECODE-RATE-001** | CONTRACT | FileProducer | RUNTIME | Yes | Yes |
| **INV-SEGMENT-CONTENT-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-PACING-001 | Frame emission rate = target_fps; render loop paced by wall clock, not CPU |
| INV-PACING-ENFORCEMENT-002 | No-drop, freeze-then-pad: max 1 frame/period; freeze <=250ms then pad; no catch-up |
| INV-DECODE-RATE-001 | Producer sustains decode rate >= target_fps; buffer never drains below low-watermark |
| INV-SEGMENT-CONTENT-001 | **(Core only)** Aggregate frame_count >= slot_duration x fps; Core provides content + filler plan. AIR consumes frame_count as planning authority; AIR does not validate schedule feasibility. See also: INV-P8-CONTENT-DEFICIT-FILL-001 for AIR's runtime adaptation when actual frames < frame_count. |

---

## Phase 8 Timeline Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Notes |
|---------|---------------|-------|-------------|------|-----|-------|
| **INV-P8-001** | CONTRACT | TimelineController | P8 | Yes | No | *Alias of LAW-TIMELINE §1* |
| **INV-P8-002** | CONTRACT | TimelineController | P8 | Yes | No | |
| **INV-P8-003** | CONTRACT | TimelineController | P8 | Yes | No | |
| **INV-P8-004** | CONTRACT | TimelineController | P8 | Yes | No | |
| **INV-P8-005** | CONTRACT | TimelineController | INIT | Yes | No | *Alias of LAW-CLOCK §2* |
| **INV-P8-006** | CONTRACT | FileProducer | P8 | Yes | No | *Alias of LAW-TIMELINE §2* |
| **INV-P8-008** | CONTRACT | TimelineController | P8 | Yes | No | |
| **INV-P8-009** | CONTRACT | PlayoutEngine | P8 | Yes | No | |
| **INV-P8-010** | CONTRACT | TimelineController | P8 | Yes | No | |
| **INV-P8-011** | CONTRACT | ProgramOutput | P8 | Yes | No | |
| **INV-P8-012** | CONTRACT | TimelineController | P8 | No | No | |
| **INV-P8-OUTPUT-001** | CONTRACT | ProgramOutput | RUNTIME | Yes | Yes | *Refines LAW-OUTPUT-LIVENESS* |
| **INV-P8-SWITCH-002** | CONTRACT | TimelineController | P8 | Yes | No | |
| **INV-P8-AUDIO-CT-001** | CONTRACT | TimelineController | P8 | Yes | No | |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-001 | Single Timeline Writer - only TimelineController assigns CT |
| INV-P8-002 | Monotonic Advancement - CT strictly increasing |
| INV-P8-003 | Contiguous Coverage - no CT gaps |
| INV-P8-004 | Wall-Clock Correspondence - W = epoch + CT steady-state |
| INV-P8-005 | Epoch Immutability - epoch unchanged until session end |
| INV-P8-006 | Producer Time Blindness - producers do not read/compute CT; must not drop/delay/gate based on MT vs target |
| INV-P8-008 | Frame Provenance - one producer, one MT, one CT per frame |
| INV-P8-009 | Atomic Buffer Authority - one active buffer, instant switch |
| INV-P8-010 | No Cross-Producer Dependency - new CT from TC state only |
| INV-P8-011 | Backpressure Isolation - consumer slowness does not slow CT |
| INV-P8-012 | Deterministic Replay - same inputs -> same CT sequence |
| INV-P8-OUTPUT-001 | Deterministic Output Liveness - explicit flush, bounded delivery |
| INV-P8-SWITCH-002 | CT and MT describe same instant at segment start; first frame locks both |
| INV-P8-AUDIO-CT-001 | Audio PTS derived from CT, init from first video frame |

---

## Phase 8 Content Deficit Invariants

Amendment 2026-02-02: These invariants address the distinction between decoder EOF and segment boundary.

| Rule ID | Classification | Owner | Enforcement | Test | Log | Notes |
|---------|---------------|-------|-------------|------|-----|-------|
| **INV-P8-SEGMENT-EOF-DISTINCT-001** | CONTRACT | PlayoutEngine | P8 | Pending | Yes | EOF ≠ boundary |
| **INV-P8-CONTENT-DEFICIT-FILL-001** | CONTRACT | ProgramOutput | P8 | Pending | Yes | Pad fills EOF-to-boundary gap |
| **INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001** | CONTRACT | FileProducer | P8 | Pending | Yes | frame_count is planning authority |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-SEGMENT-EOF-DISTINCT-001 | Segment EOF (decoder exhaustion) is distinct from segment end (scheduled boundary). EOF is an event within the segment; boundary is the scheduled instant at which the switch occurs. Timeline advancement driven by scheduled segment end time, not by EOF. |
| INV-P8-CONTENT-DEFICIT-FILL-001 | If live decoder reaches EOF before the scheduled segment end time, the gap (content deficit) MUST be filled using a deterministic fill strategy at real-time cadence until the boundary; pad (black/silence) is the guaranteed fallback. Output liveness and TS cadence preserved; mux never stalls. |
| INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | frame_count in the playout plan is planning authority from Core. AIR receives this authority and enforces runtime adaptation against it. If actual content is shorter than planned, INV-P8-CONTENT-DEFICIT-FILL-001 applies; if longer, segment end time still governs (schedule authoritative). |

---

## Phase 9/10 Semantic Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-P9-A-OUTPUT-SAFETY** | CONTRACT | ProgramOutput | P9 | Yes | No |
| **INV-P9-EMISSION-OBLIGATION** | CONTRACT | ProgramOutput | P9 | Yes | No |
| **INV-P10-REALTIME-THROUGHPUT** | CONTRACT | ProgramOutput | P10 | No | Yes |
| **INV-P10-PRODUCER-CT-AUTHORITATIVE** | CONTRACT | MpegTSOutputSink | P10 | Yes | No |
| **INV-P10-PCR-PACED-MUX** | CONTRACT | MpegTSOutputSink | P10 | Yes | No |
| **INV-P10-CONTENT-BLIND** | CONTRACT | ProgramOutput | P10 | No | No |

### Definitions

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P9-A-OUTPUT-SAFETY | No frame emitted to sink before its CT |
| INV-P9-EMISSION-OBLIGATION | Frame whose CT has arrived must eventually be emitted *(renamed from INV-P9-B-OUTPUT-LIVENESS)* |
| INV-P10-REALTIME-THROUGHPUT | Output rate matches configured frame rate within tolerance |
| INV-P10-PRODUCER-CT-AUTHORITATIVE | Muxer must use producer-provided CT (no local CT counter) |
| INV-P10-PCR-PACED-MUX | Mux loop must be time-driven, not availability-driven |
| INV-P10-CONTENT-BLIND | Frame-based rendering presents authored sequence; no pixel heuristics |

---

## Sink Delivery Mechanics

**Ownership Clarification:** These are mechanical delivery guarantees within AIR, not broadcast correctness guarantees. The timing of AttachSink/DetachSink commands is owned by Protocol/Core. AIR guarantees delivery mechanics once attachment occurs; AIR does not decide when attachment occurs.

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-P9-SINK-LIVENESS-001** | CONTRACT | OutputBus | P9 | Yes | No |
| **INV-P9-SINK-LIVENESS-002** | CONTRACT | OutputBus | P9 | Yes | No |
| **INV-P9-SINK-LIVENESS-003** | CONTRACT | OutputBus | P9 | Yes | No |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P9-SINK-LIVENESS-001 | **(Mechanical)** Pre-attach discard: frames without sink silently discarded (legal). AIR emits unconditionally; absence of sink means discard, not suppression. |
| INV-P9-SINK-LIVENESS-002 | **(Mechanical)** Post-attach delivery: after AttachSink command, all frames reach sink until DetachSink. This is a delivery guarantee, not a correctness condition. |
| INV-P9-SINK-LIVENESS-003 | **(Mechanical)** Sink stability: sink pointer stable between attach and explicit detach. AIR does not autonomously attach or detach sinks. |

---

## Video Decodability Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-AIR-IDR-BEFORE-OUTPUT** | CONTRACT | EncoderPipeline | P9 | Yes | Yes |
| **INV-AIR-CONTENT-BEFORE-PAD** | CONTRACT | ProgramOutput | P9 | Yes | Yes |
| **INV-AUDIO-HOUSE-FORMAT-001** | CONTRACT | EncoderPipeline | INIT | No | Yes |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-AIR-IDR-BEFORE-OUTPUT | AIR must not emit video packets until IDR produced; gate resets on switch |
| INV-AIR-CONTENT-BEFORE-PAD | Pad frames only after first real decoded content frame routed to output |
| INV-AUDIO-HOUSE-FORMAT-001 | All audio reaching EncoderPipeline must be house format; reject non-house input |

---

## Frame Execution Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **INV-FRAME-001** | CONTRACT | Core | SCHEDULE-TIME | No | No |
| **INV-FRAME-002** | CONTRACT | Core | SCHEDULE-TIME | No | No |
| **INV-FRAME-003** | CONTRACT | TimelineController | P10 | No | No |
| **INV-P10-FRAME-INDEXED-EXECUTION** | CONTRACT | FileProducer | P10 | No | No |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-FRAME-001 | Segment boundaries are frame-indexed for execution precision. **Does not delay clock-scheduled transitions.** *(Execution-level per LAW-AUTHORITY-HIERARCHY)* |
| INV-FRAME-002 | Padding is expressed in frames, never duration |
| INV-FRAME-003 | CT derives from frame index within a segment: ct = epoch + (frame_index x frame_duration). **Frame completion does not gate switch execution.** *(Execution-level per LAW-AUTHORITY-HIERARCHY)* |
| INV-P10-FRAME-INDEXED-EXECUTION | Producers track progress by frame index, not elapsed time |

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) - Layer 0 Laws
- [PHASE8_COORDINATION.md](../coordination/PHASE8_COORDINATION.md) - Phase 8 Coordination
- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth
