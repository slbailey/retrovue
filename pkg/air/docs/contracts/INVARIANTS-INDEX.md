# Invariants Index

**This index is navigational only. Canonical contract documents remain authoritative.**

**Purpose:** Single entry point to find every codified invariant by ID. Use this when coding or reviewing: look up the ID, read the one-line summary and type, then follow the link to the authoritative contract for full text and tests.

**Rule:** If code disagrees with an invariant, the code is wrong — fix the code or change the contract explicitly.

---

## How to use this index

| Goal | Go to |
|------|--------|
| **Constitutional laws** (Layer 0) | [PlayoutInvariants-BroadcastGradeGuarantees.md](laws/PlayoutInvariants-BroadcastGradeGuarantees.md) · [ObservabilityParityLaw.md](laws/ObservabilityParityLaw.md) |
| **Find an invariant by ID** | Tables below by layer; follow **Source** in each section |
| **RETIRED (Phase 8 / playlist path)** | [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md) — playlist/segment RPC orchestration removed; only BlockPlan is valid runtime |
| **Phase 9 bootstrap / audio liveness** | [Phase9-OutputBootstrap.md](../archive/phases/Phase9-OutputBootstrap.md) |
| **Phase 10 pipeline flow control** | [INV-P10-PIPELINE-FLOW-CONTROL.md](../../docs/contracts/INVARIANTS.md#inv-p10-pipeline-flow-control-phase-10-flow-control-invariants) |
| **Primitive invariants** (pacing, decode rate, content depth) | [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) |
| **Component-level contracts** | [README.md](semantics/README.md) |

**Invariant types:** **Law** (constitutional); **Semantic** (correctness and time); **Coordination** (barriers, switch, readiness, backpressure); **Diagnostic** (logging, stall/drop policies, violation logs). When an invariant could fit multiple categories, this index assigns the highest applicable layer (Law > Semantic > Coordination > Diagnostic).

---

## Ownership Domains

Four domains govern decoder transition behavior. Each domain owns a distinct
concern. No domain substitutes for another.

| Domain | Concern | Contracts |
|--------|---------|-----------|
| **Channel Clock** | Tick cadence, guaranteed output, monotonic enforcement | Clock Law, INV-TICK-GUARANTEED-OUTPUT, INV-TICK-DEADLINE-DISCIPLINE-001, INV-TICK-MONOTONIC-UTC-ANCHOR-001, INV-EXECUTION-CONTINUOUS-OUTPUT-001, INV-TIME-MODE-EQUIVALENCE-001, MasterClockContract |
| **Seam Continuity Engine** | Decoder overlap, clock isolation, readiness, swap, fallback observability | SeamContinuityEngine (INV-SEAM-*), SegmentContinuityContract (OUT-SEG-*) |
| **Program Block Authority** | Fence-driven block lifecycle, editorial boundaries, frame budget | ProgramBlockAuthorityContract (OUT-BLOCK-*), INV-BLOCK-WALLFENCE-*, INV-FRAME-BUDGET-* |
| **Content Engine** | Decoder lifecycle, buffer fill, priming, decode decoupling | INV-BLOCK-LOOKAHEAD-PRIMING, INV-LOOKAHEAD-BUFFER-AUTHORITY, FileProducerContract |

**Dependency direction:** Channel Clock → Seam Continuity Engine → Content Engine.
Program Block Authority feeds seam tick timing to Seam Continuity Engine.
Content Engine fills buffers that Seam Continuity Engine swaps. No domain
references the implementation details of a domain below it.

---

## Layer 0 – Constitutional Laws

Top-level broadcast guarantees. **Authoritative definition lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](laws/PlayoutInvariants-BroadcastGradeGuarantees.md).** Phase invariants refine these; they do not replace them.

| Law | One-line | Type |
|-----|----------|------|
| **Clock** | MasterClock is the only source of "now"; CT never resets once established. | Law |
| **Timeline** | TimelineController owns CT mapping; producers are time-blind after lock. | Law |
| **Output Liveness** | ProgramOutput never blocks; if no content → deterministic pad (black + silence). | Law |
| **INV-TICK-GUARANTEED-OUTPUT** | Every output tick emits exactly one frame; fallback chain: real → freeze → black. No conditional can prevent emission. Contract: [../../docs/contracts/INVARIANTS.md#inv-tick-guaranteed-output-every-tick-emits-exactly-one-frame](../../docs/contracts/INVARIANTS.md#inv-tick-guaranteed-output-every-tick-emits-exactly-one-frame) | Law |
| **Audio Format** | Channel defines house format; all audio normalized before OutputBus; EncoderPipeline never negotiates. Contract test: **INV-AUDIO-HOUSE-FORMAT-001**. | Law |
| **Switching** | No gaps, no PTS regression, no silence during switches. | Law |
| **Observability Parity** | Intent, correlation, result, timing, and boundary evidence (LAW-OBS-001 through LAW-OBS-005). | Law |
| **LAW-RUNTIME-AUDIO-AUTHORITY** | When producer_audio_authoritative=true, producer MUST emit audio ≥90% of nominal rate, or mode auto-downgrades to silence-injection. | Law |

**Source:** [ObservabilityParityLaw.md](laws/ObservabilityParityLaw.md)

---

## Layer 1 – Semantic Invariants

Truths about correctness and time: CT monotonicity, provenance, determinism, time-blindness, wall-clock correspondence, output safety/liveness semantics, format correctness.

**Source:** [Phase9-OutputBootstrap.md](../archive/phases/Phase9-OutputBootstrap.md) · [INV-P10-PIPELINE-FLOW-CONTROL.md](../../docs/contracts/INVARIANTS.md#inv-p10-pipeline-flow-control-phase-10-flow-control-invariants) · [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) · [RealTimeHoldPolicy.md](semantics/RealTimeHoldPolicy.md) · [SegmentContinuityContract.md](semantics/SegmentContinuityContract.md) · [SeamContinuityEngine.md](semantics/SeamContinuityEngine.md). *(Phase8 / playlist-path refs retired: [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md).)*

### Primitive Invariants

These are foundational assumptions from which other invariants derive. Violation of a primitive causes cascade failures across multiple derived invariants. See [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) for full behavioral contracts including violation discrimination matrix.

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-PACING-001** | Frame emission rate = target_fps; render loop paced by wall clock, not CPU | `ProgramOutput` | Semantic (Primitive) |
| **INV-PACING-ENFORCEMENT-002** | No-drop, freeze-then-pad: max 1 frame/period; freeze last frame ≤250ms; then pad; no catch-up, no drops | `ProgramOutput` | Semantic (Enforcement) |
| **INV-DECODE-RATE-001** | Producer sustains decode rate ≥ target_fps (burst allowed); buffer never drains below low-watermark | `FileProducer` | Semantic (Primitive) |
| **INV-SEGMENT-CONTENT-001** | Aggregate frame_count of all segments in slot ≥ slot_duration × fps; Core provides content + filler plan | `Core` (external) | Semantic (Primitive) |

### Sink Liveness Invariants

Output sink attachment policy. See [SinkLivenessPolicy.md](semantics/SinkLivenessPolicy.md) for full behavioral contract.

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-P9-SINK-LIVENESS-001** | Pre-attach discard: frames routed to bus without sink are silently discarded (legal) | `OutputBus` | Semantic |
| **INV-P9-SINK-LIVENESS-002** | Post-attach delivery: after AttachSink succeeds, all frames MUST reach sink until DetachSink | `OutputBus` | Semantic |
| **INV-P9-SINK-LIVENESS-003** | Sink stability: sink pointer SHALL NOT become null between attach and explicit detach | `OutputBus` | Semantic |
| **INV-SINK-NO-IMPLICIT-EOF** | After AttachStream, sink MUST emit TS until explicit stop/detach/fatal error. Producer EOF, empty queues, segment boundaries MUST NOT terminate emission. Contract: [../../docs/contracts/INVARIANTS.md#inv-sink-no-implicit-eof-continuous-output-until-explicit-stop](../../docs/contracts/INVARIANTS.md#inv-sink-no-implicit-eof-continuous-output-until-explicit-stop) | `MpegTSOutputSink` | Semantic |

### Derived Semantic Invariants

| ID | One-line | Type |
|----|----------|------|
| INV-P8-001 | Single Timeline Writer — only TimelineController assigns CT | Semantic |
| INV-P8-002 | Monotonic Advancement — CT strictly increasing | Semantic |
| INV-P8-003 | Contiguous Coverage — no CT gaps. *Defines timeline continuity.* | Semantic |
| INV-P8-004 | Wall-Clock Correspondence — W = epoch + CT steady-state | Semantic |
| INV-P8-005 | Epoch Immutability — epoch unchanged until session end | Semantic |
| INV-P8-006 | Producer Time Blindness — producers do not read/compute CT | Semantic |
| INV-P8-008 | Frame Provenance — one producer, one MT, one CT per frame | Semantic |
| INV-P8-009 | Atomic Buffer Authority — one active buffer, instant switch | Semantic |
| INV-P8-010 | No Cross-Producer Dependency — new CT from TC state only | Semantic |
| INV-P8-011 | Backpressure Isolation — consumer slowness does not slow CT | Semantic |
| INV-P8-012 | Deterministic Replay — same inputs → same CT sequence | Semantic |
| INV-P8-OUTPUT-001 | Deterministic Output Liveness — explicit flush, bounded delivery. *Defines emission continuity.* | Semantic |
| INV-P8-TIME-BLINDNESS | Producer must not drop on MT vs target, delay for alignment, gate audio on video PTS; all admission via TimelineController | Semantic |
| INV-P8-SWITCH-002 | CT and MT describe same instant at segment start; first frame locks both | Semantic |
| INV-P8-AUDIO-CT-001 | Audio PTS derived from CT, init from first video frame | Semantic |
| INV-P9-A-OUTPUT-SAFETY | No frame emitted to sink before its CT | Semantic |
| INV-P9-B-OUTPUT-LIVENESS | Frame whose CT has arrived must eventually be emitted (or dropped); audio processed even if video empty | Semantic |
| INV-P10-REALTIME-THROUGHPUT | Output rate must match configured frame rate within tolerance during steady-state | Semantic |
| INV-P10-PRODUCER-CT-AUTHORITATIVE | Muxer must use producer-provided CT (no local CT counter) | Semantic |
| INV-P10-PCR-PACED-MUX | Mux loop must be time-driven, not availability-driven | Semantic |
| INV-AUDIO-HOUSE-FORMAT-001 | All audio reaching EncoderPipeline (including pad) must be house format; pipeline rejects or fails loudly on non-house input; pad uses same path, CT, cadence, format as program. Test: INV_AUDIO_HOUSE_FORMAT_001_HouseFormatOnly (stub) | Semantic |
| INV-AIR-IDR-BEFORE-OUTPUT | AIR must not emit any video packets for a segment until an IDR frame has been produced by the encoder for that segment. Gate resets on segment switch (ResetOutputTiming). | Semantic |
| **INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT** | After AttachStream, emit decodable TS within 500ms using fallback if needed. Output-first, content-second. Contract: [../../docs/contracts/INVARIANTS.md#inv-boot-immediate-decodable-output-decodable-output-within-500ms](../../docs/contracts/INVARIANTS.md#inv-boot-immediate-decodable-output-decodable-output-within-500ms) | Semantic |
| ~~INV-AIR-CONTENT-BEFORE-PAD~~ | **RETIRED** — Replaced by INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT. Old philosophy (gate output on content) was backwards. | — |

### Segment Continuity Invariants

Decoder transition correctness at segment seams (episode→filler, block→block, content→pad). See [SegmentContinuityContract.md](semantics/SegmentContinuityContract.md).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **OUT-SEG-001** | Seam safety gate — incoming segment must be ready or fallback emitted | `PipelineManager` | Semantic |
| **OUT-SEG-002** | No stream death on segment seam — decoder latency must not stop channel | `PipelineManager` | Semantic |
| **OUT-SEG-003** | Continuous audio output across segment seam — every tick produces audio | `PipelineManager` | Semantic |
| **OUT-SEG-004** | Audio underflow is survivable and observable — inject fallback, increment metric, log | `PipelineManager` | Semantic |
| **OUT-SEG-005** | Segment seam is mechanically equivalent to a prepared source swap — tick loop must not block | `PipelineManager` / `ProducerPreloader` | Semantic |
| **OUT-SEG-005b** | Bounded fallback at seams — well-formed assets SHOULD NOT require >N consecutive fallback ticks (default 5). `max_consecutive_audio_fallback_ticks` tracked as observable metric. | `PipelineManager` | Semantic |
| **OUT-SEG-006** | Segment transition invariants apply uniformly to all decoder transitions | `PipelineManager` | Semantic |

### Seam Continuity Engine Invariants

Decoder-overlapped transition model: clock isolation, readiness gates, audio continuity, mechanical equivalence, and bounded fallback observability. These invariants formalize the decoder-overlap model that the OUT-SEG-* outcomes require. See [SeamContinuityEngine.md](semantics/SeamContinuityEngine.md).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-SEAM-001** | Clock isolation — channel clock MUST NOT observe, wait for, or be influenced by any decoder lifecycle event. Decoder open/probe/seek/prime execute on background threads within the overlap window. Fatal if systematic. | Seam Continuity Engine | Semantic (Broadcast-Grade) |
| **INV-SEAM-002** | Decoder readiness before seam tick — incoming decoder MUST achieve readiness (video frame + audio prime) before the seam tick arrives. Readiness gate MUST NOT hang; failure signals "not ready" and tick thread selects fallback. Recoverable per-instance; fatal if systematic. | `ProducerPreloader` / `TickProducer` | Semantic (Broadcast-Grade) |
| **INV-SEAM-003** | Audio continuity across seam — at the seam tick, real decoded audio MUST be emitted from the incoming source (not silence, not pad). Stronger than INV-TICK-GUARANTEED-OUTPUT which only requires *something*. Assets with no audio track are exempt (pad is correct output). Recoverable. | `AudioLookaheadBuffer` / `PipelineManager` | Semantic (Broadcast-Grade) |
| **INV-SEAM-004** | Segment/block mechanical equivalence — all decoder transitions MUST use the same prepared-swap primitive regardless of editorial context. Swap mechanism is context-blind; only seam tick determination differs (fence tick vs. media-time exhaustion). Fatal. | Seam Continuity Engine | Semantic (Broadcast-Grade) |
| **INV-SEAM-005** | Bounded fallback observability — `max_consecutive_audio_fallback_ticks` MUST be tracked as session-lifetime high-water mark, exposed via Prometheus, and bounded (default threshold: 5 ticks for well-formed assets). Metric MUST NOT influence execution. Recoverable (metric absence is fatal). | `PipelineManager` | Semantic (Broadcast-Grade) |
| **INV-SEAM-006** | Eager decoder preparation — decoder preparation for segment N+1 MUST begin no later than the tick where segment N becomes active. Segment duration, type, and block boundaries MUST NOT delay preparation. Overlap is eager, not reactive. Fatal. | Seam Continuity Engine | Semantic (Broadcast-Grade) |

### Segment Seam Overlap Invariants

Structural constraints enforcing eager decoder overlap for intra-block segment transitions. These invariants specify which thread may perform which operation, eliminating the reactive `AdvanceToNextSegment` path. See [SegmentSeamOverlapContract.md](semantics/SegmentSeamOverlapContract.md).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-SEAM-SEG-001** | Clock isolation at segment seams — tick thread does no FFmpeg work at any seam (segment or block). Fatal if systematic. | `PipelineManager` | Semantic (Broadcast-Grade) |
| **INV-SEAM-SEG-002** | No reactive transitions — `TryGetFrame` MUST NOT perform decoder lifecycle or segment advancement. `AdvanceToNextSegment` must not exist. Fatal. | `TickProducer` | Semantic (Broadcast-Grade) |
| **INV-SEAM-SEG-003** | Eager arming — when segment N becomes active, prep for N+1 MUST be armed on the same tick (subject only to "N+1 exists"). No condition may delay arming. Fatal. | `PipelineManager` / `SeamPreparer` | Semantic (Broadcast-Grade) |
| **INV-SEAM-SEG-004** | Deterministic seam tick — `segment_seam_frame = block_activation_frame + ceil(boundary.end_ct_ms × fps_num / (fps_den × 1000))`. Same rational arithmetic as block fence. Fatal. | `PipelineManager` | Semantic (Broadcast-Grade) |
| **INV-SEAM-SEG-005** | Unified swap mechanism — segment seams use the same pointer-swap (buffer rotation + fill thread lifecycle) as block seams. Context-blind swap primitive. Fatal. | `PipelineManager` | Semantic (Broadcast-Grade) |
| **INV-SEAM-SEG-006** | No decoder lifecycle on fill thread — `FillLoop` cannot call Open/Close/Seek or any function that does. Fill thread decodes from an already-open decoder only. Fatal. | `VideoLookaheadBuffer` / `TickProducer` | Semantic (Broadcast-Grade) |

### Media Time Authority Invariants

Decoded media time governs **intra-block** segment transitions and CT tracking. See [INV-AIR-MEDIA-TIME.md](../../docs/contracts/INVARIANTS.md#inv-air-media-time-media-time-authority-contract) for full behavioral contract. **Note:** INV-AIR-MEDIA-TIME-001 is **partially superseded** — CT is no longer timing authority for block transitions (see Wall-Clock Fence below). CT tracking (002–005) remains fully in force for segment-internal behavior.

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-AIR-MEDIA-TIME-001** | ~~Block execution governed by decoded media time~~ — **Superseded for block transitions** by INV-BLOCK-WALLFENCE-001. CT remains authoritative for segment transitions within a block. | `TickProducer` | Semantic (Partially Superseded) |
| **INV-AIR-MEDIA-TIME-002** | No cumulative drift — PTS-anchored tracking bounds error to one frame period | `TickProducer` | Semantic |
| **INV-AIR-MEDIA-TIME-003** | Fence alignment — decoded media time converges to block end within one frame | `TickProducer` | Semantic |
| **INV-AIR-MEDIA-TIME-004** | Cadence independence — output FPS does not affect media time tracking | `TickProducer` | Semantic |
| **INV-AIR-MEDIA-TIME-005** | Pad is never primary — padding only when decoded media time exceeds block end | `TickProducer` | Semantic |
| **INV-FPS-RESAMPLE** | Output tick grid and block CT from rational (fps_num, fps_den); no round(1e6/fps) accumulation, no int(1000/fps) advancement. Contract: [INV-FPS-RESAMPLE.md](../../docs/contracts/INVARIANTS.md#inv-fps-resample-fps-resample-authority-contract). Tests: FR-001–FR-005, MediaTimeContractTests. | FileProducer, TickProducer | Semantic |
| **INV-NO-FLOAT-FPS-TIMEBASE-001** | Runtime code MUST NOT compute frame/tick duration via 1e6/fps, round(1e6/fps), or similar float-derived formulas; use RationalFps only. Exceptions: tests/helpers explicitly labeled. Contract: [INV-NO-FLOAT-FPS-TIMEBASE-001.md](INV-NO-FLOAT-FPS-TIMEBASE-001.md). Test: test_inv_no_float_fps_timebase_001. | All runtime (src, include) | Semantic |
| **INV-FPS-MAPPING** | Source→output frame authority: input≠output MUST use OFF (exact rational equality), DROP (integer step), or CADENCE (rational accumulator). 60→30/120→30 DROP; 23.976→30 CADENCE; 30→30 OFF. No float/epsilon, no default OFF. Contract: [INV-FPS-MAPPING.md](../../docs/contracts/INVARIANTS.md#inv-fps-mapping-sourceoutput-frame-authority). | TickProducer, VideoLookaheadBuffer | Semantic |
| **INV-TICK-AUTHORITY-001** | Returned video PTS delta and video.metadata.duration MUST equal exactly one output tick (OFF/DROP/CADENCE). Input frame duration must never leak into output. Contract: [INV-FPS-MAPPING.md](../../docs/contracts/INVARIANTS.md#inv-fps-mapping-sourceoutput-frame-authority). | TickProducer | Semantic |

### Block Boundary Authorities (Canonical Model)

Block transitions are governed by **three complementary authorities**, each owning a distinct concern. No authority substitutes for another. Together they define the complete block transition model.

| Authority | Contract | Concern | Owner |
|-----------|----------|---------|-------|
| **Timing** | [../../docs/contracts/INVARIANTS.md#inv-block-wallclock-fence-001-deterministic-block-fence-from-rational-timebase](../../docs/contracts/INVARIANTS.md#inv-block-wallclock-fence-001-deterministic-block-fence-from-rational-timebase) | **When** does the A/B swap fire? Precomputed rational fence tick. | `PipelineManager` |
| **Counting** | [../../docs/contracts/INVARIANTS.md#inv-block-frame-budget-authority-frame-budget-as-counting-authority](../../docs/contracts/INVARIANTS.md#inv-block-frame-budget-authority-frame-budget-as-counting-authority) | **How many** frames does the block emit? Budget derived from fence range. | `PipelineManager` / `TickProducer` |
| **Latency** | [../../docs/contracts/INVARIANTS.md#inv-block-lookahead-priming-look-ahead-priming-at-block-boundaries](../../docs/contracts/INVARIANTS.md#inv-block-lookahead-priming-look-ahead-priming-at-block-boundaries) | **How fast** is the first frame of the next block? Zero-decode-latency priming. | `ProducerPreloader` / `TickProducer` |

The fence tick is the single timing authority for block transitions. The frame budget is derived from the fence (`fence_tick - block_start_tick`) and converges to 0 on the fence tick by construction. Priming ensures zero decode latency on the fence tick. All three use rational `fps_num/fps_den` as the authoritative frame rate representation.

#### Wall-Clock Fence Invariants (Timing Authority)

Precomputed deterministic fence tick from rational timebase. **Supersedes INV-AIR-MEDIA-TIME-001 for block transition authority.** See [../../docs/contracts/INVARIANTS.md#inv-block-wallclock-fence-001-deterministic-block-fence-from-rational-timebase](../../docs/contracts/INVARIANTS.md#inv-block-wallclock-fence-001-deterministic-block-fence-from-rational-timebase).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-BLOCK-WALLFENCE-001** | Rational fence tick is sole authority for block boundaries; computed from `ceil(delta_ms * fps_num / (fps_den * 1000))`; immutable after computation | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-BLOCK-WALLFENCE-002** | CT underrun at fence tick results in truncation, not delayed swap | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-BLOCK-WALLFENCE-003** | Early CT exhaustion results in freeze/pad until fence tick, not early advancement | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-BLOCK-WALLFENCE-004** | TAKE selects next block's buffers at pop→encode on the fence tick; fence tick is first tick of next block | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-BLOCK-WALLFENCE-005** | BlockCompleted is a consequence of the swap, not a gate for it | `PipelineManager` | Coordination (Broadcast-Grade) |

#### Frame Budget Invariants (Counting Authority)

Per-block frame counter derived from fence range. Budget reaching 0 at fence tick is verification, not trigger. See [../../docs/contracts/INVARIANTS.md#inv-block-frame-budget-authority-frame-budget-as-counting-authority](../../docs/contracts/INVARIANTS.md#inv-block-frame-budget-authority-frame-budget-as-counting-authority).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-FRAME-BUDGET-001** | Frame budget derived from fence range: `fence_tick - block_start_tick`; not from `duration * fps` or `FramesPerBlock()` | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-FRAME-BUDGET-002** | Explicit remaining frame tracking — initialized once, decremented by 1 per emitted frame, never modified otherwise | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-FRAME-BUDGET-003** | One frame, one decrement — real, freeze, and black frames all decrement budget equally | `PipelineManager` / `TickProducer` | Coordination (Broadcast-Grade) |
| **INV-FRAME-BUDGET-004** | Budget reaching 0 is diagnostic verification that fence fired, not the swap trigger | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-FRAME-BUDGET-005** | Segments must consult remaining budget before emitting; budget is hard ceiling | `TickProducer` | Coordination (Broadcast-Grade) |
| **INV-FRAME-BUDGET-006** | Segment exhaustion does not cause block completion; only fence tick ends a block | `PipelineManager` / `TickProducer` | Coordination (Broadcast-Grade) |
| **INV-FRAME-BUDGET-007** | No negative frame budget — violation is proof of bug | `PipelineManager` | Coordination (Broadcast-Grade) |

#### Preroll Ownership Authority (INV-PREROLL-OWNERSHIP-AUTHORITY)

Single source of truth for "next block at fence"; preroll arming aligned with fence swap. See [../../docs/contracts/INVARIANTS.md#inv-preroll-ownership-authority-preroll-arming-and-fence-swap-coherence](../../docs/contracts/INVARIANTS.md#inv-preroll-ownership-authority-preroll-arming-and-fence-swap-coherence).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **OUT-PREROLL-001** | Committed successor block id is set when TakeBlockResult assigns preview_, not when queue is popped | `PipelineManager` | Coordination (Broadcast-Grade) |
| **OUT-PREROLL-002** | Expected next block (ownership stamp) set only at TakeBlockResult; cleared after B→A rotation | `PipelineManager` | Coordination (Broadcast-Grade) |
| **OUT-PREROLL-003** | Mismatch at fence: fail closed, single structured log (expected_next_block_id, candidate_block_id); playout continues with session block | `PipelineManager` | Diagnostic |
| **OUT-PREROLL-004** | Plan queue MUST NOT be used to derive expected block at fence | `PipelineManager` | Coordination (Broadcast-Grade) |

#### Lookahead Priming Invariants (Latency Authority)

Zero-decode-latency priming at block boundaries. See [../../docs/contracts/INVARIANTS.md#inv-block-lookahead-priming-look-ahead-priming-at-block-boundaries](../../docs/contracts/INVARIANTS.md#inv-block-lookahead-priming-look-ahead-priming-at-block-boundaries).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-BLOCK-PRIME-001** | Decoder readiness before fence tick — first frame decoded into memory before kReady | `ProducerPreloader` / `TickProducer` | Coordination |
| **INV-BLOCK-PRIME-002** | Zero deadline work at fence tick — fence tick's TryGetFrame returns primed frame, no I/O | `TickProducer` | Coordination |
| **INV-BLOCK-PRIME-003** | No duplicate decoding — primed frame consumed exactly once | `TickProducer` | Coordination |
| **INV-BLOCK-PRIME-004** | No impact on steady-state cadence — priming does not alter decode/repeat pattern | `PipelineManager` / `TickProducer` | Coordination |
| **INV-BLOCK-PRIME-005** | Priming failure degrades safely — kReady still reached, swap still fires at fence tick | `TickProducer` | Coordination |
| **INV-BLOCK-PRIME-006** | Priming is event-driven — executes after AssignBlock, no polling or timers | `ProducerPreloader` | Coordination |
| **INV-BLOCK-PRIME-007** | Primed frame metadata integrity — PTS, audio, asset_uri match normal decode | `TickProducer` | Coordination |
| **INV-AUDIO-PRIME-002** | Primed frame must carry ≥1 audio packet when asset has audio; ready for seam not declared until audio depth threshold satisfied. Contract: [INV-AUDIO-PRIME-002.md](../../docs/contracts/INVARIANTS.md#inv-audio-prime-002-prime-frame-must-carry-audio). | `TickProducer` / `VideoLookaheadBuffer` | Coordination |

### Deterministic Underflow and Tick Observability (INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY)

Underflow as controlled transition; tick lateness observable. See [../../docs/contracts/INVARIANTS.md#inv-deterministic-underflow-and-tick-observability-underflow-policy-and-tick-lateness](../../docs/contracts/INVARIANTS.md#inv-deterministic-underflow-and-tick-observability-underflow-policy-and-tick-lateness).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **OUT-UNDERFLOW-001** | When depth ≤ low_water, deterministic freeze/pad policy; no stall spiral | `PipelineManager` | Coordination (Broadcast-Grade) |
| **OUT-UNDERFLOW-002** | UNDERFLOW log includes low_water, target, depth_at_event, optionally lateness_ms/p95 | `PipelineManager` / `VideoLookaheadBuffer` | Diagnostic |
| **OUT-TICK-OBS-001** | Tick lateness observable (per-tick lateness_ms, TICK_GAP with gap_ms/lateness_ms/phase) | `PipelineManager` | Diagnostic |
| **OUT-TICK-OBS-002** | No nondeterministic sleeps; MasterClock-driven timing | `PipelineManager` | Coordination (Broadcast-Grade) |

### Lookahead Buffer Authority Invariants (Decode Decoupling)

Tick-thread decode decoupling and hard-fault underflow semantics. Background fill threads own all decode; the tick loop only consumes pre-decoded frames. See [../../docs/contracts/INVARIANTS.md#inv-lookahead-buffer-authority-lookahead-buffer-decode-authority](../../docs/contracts/INVARIANTS.md#inv-lookahead-buffer-authority-lookahead-buffer-decode-authority).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-VIDEO-LOOKAHEAD-001** | Tick thread MUST NOT call video decode APIs; fill thread decodes into bounded buffer; underflow = hard fault (no pad/hold injection) | `VideoLookaheadBuffer` / `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-AUDIO-LOOKAHEAD-001** | Audio pushed by video fill thread; tick thread pops only; underflow = hard fault (no silence injection); buffer not flushed at fence | `AudioLookaheadBuffer` / `PipelineManager` | Coordination (Broadcast-Grade) |

### Tick Deadline Enforcement (Derived)

These invariants ensure that tick progression remains wall-clock anchored so that block boundary authorities defined above are enforced even when execution falls behind. Tick deadlines are derived from the session epoch and rational FPS; they do not define schedule semantics.

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-TICK-DEADLINE-DISCIPLINE-001** | Hard deadline discipline: each tick anchored to session epoch; late ticks emit fallback, no catch-up bursts, no drift. Contract: [../../docs/contracts/INVARIANTS.md#inv-tick-deadline-discipline-001-hard-deadline-discipline-for-output-ticks](../../docs/contracts/INVARIANTS.md#inv-tick-deadline-discipline-001-hard-deadline-discipline-for-output-ticks) | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-TICK-MONOTONIC-UTC-ANCHOR-001** | Monotonic clock enforcement for tick deadlines; UTC remains schedule authority but enforcement uses monotonic time to resist NTP/system-time steps. Contract: [../../docs/contracts/INVARIANTS.md#inv-tick-monotonic-utc-anchor-001-monotonic-deadline-enforcement](../../docs/contracts/INVARIANTS.md#inv-tick-monotonic-utc-anchor-001-monotonic-deadline-enforcement) | `PipelineManager` | Coordination (Broadcast-Grade) |
| **INV-EXECUTION-CONTINUOUS-OUTPUT-001** | Session runs in continuous_output; tick deadlines anchored to session epoch + rational output FPS; no segment/block/decoder lifecycle event may shift tick schedule; underflow may repeat/black but tick schedule fixed; frame-selection cadence may refresh, tick cadence fixed by session RationalFps. Contract: [../../docs/contracts/INVARIANTS.md#inv-execution-continuous-output-001-continuous-output-execution-model](../../docs/contracts/INVARIANTS.md#inv-execution-continuous-output-001-continuous-output-execution-model) | `PipelineManager` | Semantic (Broadcast-Grade) |
| **INV-TIME-MODE-EQUIVALENCE-001** | Clock mode MUST NOT alter timing contract semantics — deadline math, frame index progression, seam decisions, and switch boundary enforcement produce identical outcomes under real-time and deterministic clock implementations. All timing consumers depend on `IOutputClock`; no component branches on clock type. Derives from LAW-CLOCK. Contract: [../../docs/contracts/invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md](../../docs/contracts/invariants/air/INV-TIME-MODE-EQUIVALENCE-001.md) | `PipelineManager` / `IOutputClock` implementors | Semantic (Broadcast-Grade) |

**Overlap note:** INV-P8-003 defines **timeline continuity** (no gaps in CT). INV-P8-OUTPUT-001 defines **emission continuity** (output explicitly flushed and delivered in bounded time). Both are required; they address different continuities.

---

## Layer 2 – Coordination / Concurrency Invariants

Write barriers, shadow decode, switch arming, backpressure symmetry, readiness, no-deadlock rules, ordering and sequencing that coordinate components.

**Source:** [Phase9-OutputBootstrap.md](../archive/phases/Phase9-OutputBootstrap.md) · [INV-P10-PIPELINE-FLOW-CONTROL.md](../../docs/contracts/INVARIANTS.md#inv-p10-pipeline-flow-control-phase-10-flow-control-invariants) · [SwitchWatcherStopTargetContract.md](coordination/SwitchWatcherStopTargetContract.md) · [ProgramBlockAuthorityContract.md](coordination/ProgramBlockAuthorityContract.md). *(Phase8 refs retired: [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md).)*

| ID | One-line | Type |
|----|----------|------|
| INV-P8-007 | Write Barrier Finality — post-barrier writes = 0 | Coordination |
| INV-P8-SWITCH-001 | Mapping must be pending BEFORE preview fills; write barrier on live before new segment | Coordination |
| INV-P8-SHADOW-PACE | Shadow caches first frame, waits in place; no run-ahead decode | Coordination |
| ~~INV-P8-AUDIO-GATE~~ | **RETIRED** — playlist-path only. See [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md). | — |
| INV-P8-SEGMENT-COMMIT | First frame admitted → segment commits, owns CT; old segment RequestStop | Coordination |
| INV-P8-SEGMENT-COMMIT-EDGE | Generation counter per commit for multi-switch edge detection | Coordination |
| ~~INV-P8-SWITCH-ARMED~~ | **RETIRED** — playlist-path only. See [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md). | — |
| INV-P8-WRITE-BARRIER-DEFERRED | Write barrier on live MUST wait until preview shadow decode ready | Coordination |
| ~~INV-P8-EOF-SWITCH~~ | **RETIRED** — playlist-path only. See [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md). | — |
| INV-P8-PREVIEW-EOF | Preview EOF with frames → complete with lower thresholds (e.g. ≥1 video, ≥1 audio) | Coordination |
| **INV-P8-SWITCHWATCHER-STOP-TARGET-001** | Switch machinery must not stop/disable/write-barrier successor as result of switch-completion or commit bookkeeping | Coordination |
| **INV-P8-SWITCHWATCHER-COMMITGEN-EDGE-SAFETY-002** | Post-swap commit-gen transitions must not trigger retirement actions against successor | Coordination |
| **INV-P8-COMMITGEN-RETIREMENT-SEMANTICS-003** | Retirement decisions must ignore commit-gen transitions representing successor activation or same-segment bookkeeping | Coordination |
| INV-P8-SHADOW-FLUSH | On leaving shadow: flush cached first frame to buffer immediately | Coordination |
| INV-P8-ZERO-FRAME-READY | When frame_count=0, signal shadow_decode_ready=true immediately; vacuous flush returns true | Coordination |
| INV-P8-ZERO-FRAME-BOOTSTRAP | When no_content_segment=true, bypass CONTENT-BEFORE-PAD gate; first pad frame bootstraps encoder | Coordination |
| INV-P8-AUDIO-GATE Fix #2 | mapping_locked_this_iteration_ so audio same iteration ungate after video locks | Coordination |
| INV-P8-AV-SYNC | Audio gated until video locks mapping (no audio ahead of video at switch) | Coordination |
| INV-P8-AUDIO-PRIME-001 | No header until first audio; no video encode before header written | Coordination |
| INV-P8-IO-UDS-001 | UDS/output must not block on prebuffer; prebuffering disabled for UDS path | Coordination |
| INV-P9-FLUSH | Cached shadow frame pushed to buffer synchronously when shadow disabled. Test: INV_P9_FLUSH_Synchronous | Coordination |
| INV-P9-BOOTSTRAP-READY | Readiness = commit detected AND ≥1 video frame, not deep buffering. Test: G9_002, AudioZeroFrameAcceptable | Coordination |
| INV-P9-NO-DEADLOCK | Output routing must not wait on conditions that require output routing. Test: G9_003_NoDeadlockOnSwitch | Coordination |
| INV-P9-WRITE-BARRIER-SYMMETRIC | When write barrier set, audio and video suppressed symmetrically; audio push checks writes_disabled_. Test: Audio liveness tests | Coordination |
| INV-P9-BOOT-LIVENESS | Newly attached sink must emit decodable TS within bounded time, even if audio not yet available. Test: G9_001, G9_004 | Coordination |
| INV-P9-AUDIO-LIVENESS | From header written, output must contain continuous, monotonic audio PTS with correct pacing (silence if no decoded audio yet). Test: AUDIO_LIVENESS_001/002/003 | Coordination |
| INV-P9-PCR-AUDIO-MASTER | Audio owns PCR at startup. Test: PCR_AUDIO_MASTER_001/002, VLC_STARTUP_SMOKE | Coordination |
| **INV-P9-TS-EMISSION-LIVENESS** | First decodable TS packet MUST be emitted within 500ms of PCR-PACE timing initialization. Refines INV-P9-BOOT-LIVENESS. | Coordination |
| INV-P10-BACKPRESSURE-SYMMETRIC | When buffer full, both audio and video throttled symmetrically | Coordination |
| INV-P10-PRODUCER-THROTTLE | Producer decode rate governed by consumer capacity, not decoder speed | Coordination |
| INV-P10-BUFFER-EQUILIBRIUM | Buffer depth must oscillate around target, not grow unbounded or drain to zero | Coordination |
| INV-P10-NO-SILENCE-INJECTION | Audio liveness must be disabled when PCR-paced mux is active | Coordination |
| **INV-P10-AUDIO-VIDEO-GATE** | When segment video epoch is established, first audio frame MUST be queued within 100ms. Complements INV-P8-AV-SYNC. | Coordination |

### Program Block Authority Outcomes

Block lifecycle ownership and fence-driven transfer. See [ProgramBlockAuthorityContract.md](coordination/ProgramBlockAuthorityContract.md).

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **OUT-BLOCK-001** | Fence is sole authority for block ownership transfer — no early advancement | `PipelineManager` | Coordination |
| **OUT-BLOCK-002** | Block identity is externally observable — lifecycle events with block_id, fence, verdict | `PipelineManager` | Coordination |
| **OUT-BLOCK-003** | Block completion must be recorded at fence — frame count, pad count, asset ranges | `PipelineManager` | Coordination |
| **OUT-BLOCK-004** | Block-to-block transition must invoke segment continuity outcomes | `PipelineManager` | Coordination |
| **OUT-BLOCK-005** | Missing/late next block results in PADDED_GAP, not stream death | `PipelineManager` | Coordination |

---

## Layer 3 – Diagnostic / Enforcement Invariants

Logging requirements, stall diagnostics, drop policies, safety rails, test-only guards. These make violations visible and enforce explicit handling.

**Source:** [INV-P10-PIPELINE-FLOW-CONTROL.md](../../docs/contracts/INVARIANTS.md#inv-p10-pipeline-flow-control-phase-10-flow-control-invariants). *(Phase8 refs retired: [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md).)*

| ID | One-line | Type |
|----|----------|------|
| INV-P8-WRITE-BARRIER-DIAG | On writes_disabled_: drop frame, log INV-P8-WRITE-BARRIER | Diagnostic |
| INV-P8-AUDIO-PRIME-STALL | Diagnostic: log if video dropped too long waiting for audio prime | Diagnostic |
| INV-P8-SWITCH-TIMING | Core: switch at boundary; log if pending after boundary; violation log if complete after boundary | Diagnostic |
| INV-P10-FRAME-DROP-POLICY | Frame drops forbidden except under explicit conditions; must log INV-P10-FRAME-DROP | Diagnostic |

---

## Where to find what (for coding)

| You need… | Document / location |
|-----------|----------------------|
| **Laws** (Layer 0) | [PlayoutInvariants-BroadcastGradeGuarantees.md](laws/PlayoutInvariants-BroadcastGradeGuarantees.md) |
| **Invariants by layer** (this index) | Layer 1–3 tables above |
| **RETIRED (Phase 8 / playlist path)** | [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md) |
| **Phase 9** (bootstrap, audio liveness) | [Phase9-OutputBootstrap.md](../archive/phases/Phase9-OutputBootstrap.md) |
| **Phase 10** (flow control, backpressure, mux) | [INV-P10-PIPELINE-FLOW-CONTROL.md](../../docs/contracts/INVARIANTS.md#inv-p10-pipeline-flow-control-phase-10-flow-control-invariants) |
| **Primitive invariants** (pacing, decode rate, content) | [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) |
| **RealTimeHold** (freeze-then-pad, no-drop policy) | [RealTimeHoldPolicy.md](semantics/RealTimeHoldPolicy.md) |
| **Component contracts** | [README.md](semantics/README.md) |
| **Broadcast-grade output** (unconditional emission) | [../../docs/contracts/INVARIANTS.md#inv-tick-guaranteed-output-every-tick-emits-exactly-one-frame](../../docs/contracts/INVARIANTS.md#inv-tick-guaranteed-output-every-tick-emits-exactly-one-frame) · [../../docs/contracts/INVARIANTS.md#inv-sink-no-implicit-eof-continuous-output-until-explicit-stop](../../docs/contracts/INVARIANTS.md#inv-sink-no-implicit-eof-continuous-output-until-explicit-stop) · [../../docs/contracts/INVARIANTS.md#inv-boot-immediate-decodable-output-decodable-output-within-500ms](../../docs/contracts/INVARIANTS.md#inv-boot-immediate-decodable-output-decodable-output-within-500ms) |
| **Block boundary model** (fence, budget, priming) | [../../docs/contracts/INVARIANTS.md#inv-block-wallclock-fence-001-deterministic-block-fence-from-rational-timebase](../../docs/contracts/INVARIANTS.md#inv-block-wallclock-fence-001-deterministic-block-fence-from-rational-timebase) · [../../docs/contracts/INVARIANTS.md#inv-block-frame-budget-authority-frame-budget-as-counting-authority](../../docs/contracts/INVARIANTS.md#inv-block-frame-budget-authority-frame-budget-as-counting-authority) · [../../docs/contracts/INVARIANTS.md#inv-block-lookahead-priming-look-ahead-priming-at-block-boundaries](../../docs/contracts/INVARIANTS.md#inv-block-lookahead-priming-look-ahead-priming-at-block-boundaries) |
| **Tick deadline enforcement** (deadline discipline, monotonic anchor, continuous output) | [../../docs/contracts/INVARIANTS.md#inv-tick-deadline-discipline-001-hard-deadline-discipline-for-output-ticks](../../docs/contracts/INVARIANTS.md#inv-tick-deadline-discipline-001-hard-deadline-discipline-for-output-ticks) · [../../docs/contracts/INVARIANTS.md#inv-tick-monotonic-utc-anchor-001-monotonic-deadline-enforcement](../../docs/contracts/INVARIANTS.md#inv-tick-monotonic-utc-anchor-001-monotonic-deadline-enforcement) · [../../docs/contracts/INVARIANTS.md#inv-execution-continuous-output-001-continuous-output-execution-model](../../docs/contracts/INVARIANTS.md#inv-execution-continuous-output-001-continuous-output-execution-model) |
| **Lookahead buffer authority** (decode decoupling, underflow semantics) | [../../docs/contracts/INVARIANTS.md#inv-lookahead-buffer-authority-lookahead-buffer-decode-authority](../../docs/contracts/INVARIANTS.md#inv-lookahead-buffer-authority-lookahead-buffer-decode-authority) |
| **Segment continuity** (decoder transition correctness, fallback KPI) | [SegmentContinuityContract.md](semantics/SegmentContinuityContract.md) |
| **Seam continuity engine** (clock isolation, decoder overlap, mechanical equivalence) | [SeamContinuityEngine.md](semantics/SeamContinuityEngine.md) |
| **Program block authority** (fence ownership, block lifecycle) | [ProgramBlockAuthorityContract.md](coordination/ProgramBlockAuthorityContract.md) |
| **Build / codec rules** | [build.md](coordination/build.md) |
| **Architecture reference** | [AirArchitectureReference.md](semantics/AirArchitectureReference.md) |
| **Timing authority** (tick grid, FPS resample, frame mapping, audio prime) | [TIMING-AUTHORITY-OVERVIEW.md](semantics/TIMING-AUTHORITY-OVERVIEW.md) · [INV-FPS-RESAMPLE.md](../../docs/contracts/INVARIANTS.md#inv-fps-resample-fps-resample-authority-contract) · [INV-NO-FLOAT-FPS-TIMEBASE-001.md](INV-NO-FLOAT-FPS-TIMEBASE-001.md) · [INV-FPS-MAPPING.md](../../docs/contracts/INVARIANTS.md#inv-fps-mapping-sourceoutput-frame-authority) · [INV-AUDIO-PRIME-002.md](../../docs/contracts/INVARIANTS.md#inv-audio-prime-002-prime-frame-must-carry-audio) |

Canonical contract documents take precedence over this index. When in doubt, the contract wins.
