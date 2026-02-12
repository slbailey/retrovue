# Proposed Invariants from Rule Harvest

**Status:** Draft - Pending Review
**Source:** RULE_HARVEST.json analysis
**Purpose:** Formalize historical rules as canonical invariants

This document contains formal invariant definitions drafted from historical rules that were found to be missing or partially codified in canonical contracts.

---

## Process

Each proposed invariant follows the canonical format:
1. **Invariant ID**: `INV-<PHASE>-<COMPONENT>-<NUMBER>`
2. **One-line summary**: What the invariant requires
3. **Owner**: Component responsible for enforcement
4. **Type**: Law, Semantic, Coordination, or Diagnostic
5. **Enforcement**: How violations are detected
6. **Violation log**: Standardized log format
7. **Related rules**: Source rules from RULE_HARVEST.json

---

## Layer 1 - Semantic Invariants (Missing/Partial)

### INV-SINK-TIMING-OWNERSHIP-001

**Summary:** Sink owns the timing loop; timing decisions derive from MasterClock, not system clock.

**Owner:** `IOutputSink` implementations (e.g., `MpegTSOutputSink`)

**Type:** Semantic

**Full Definition:**
- Every sink implementation MUST own its timing loop
- Timing loop MUST query MasterClock for "now", never `std::chrono::steady_clock::now()` or equivalent
- Frame emission decisions MUST be driven by MasterClock-derived deadlines
- Sinks MUST implement buffer underflow/overflow policies without blocking producers

**Enforcement:**
- Code review: No direct system clock calls in sink timing code
- Test: Mock MasterClock and verify sink respects mock time

**Violation log:**
```
[Sink] INV-SINK-TIMING-OWNERSHIP-001 VIOLATION: Direct system clock access in timing loop
```

**Related rules:** RULE_HARVEST #2

---

### INV-SINK-PIXEL-FORMAT-FAULT-001

**Summary:** Unsupported pixel format causes explicit error and fault state, never silent drop.

**Owner:** `MpegTSOutputSink`, `EncoderPipeline`

**Type:** Semantic

**Full Definition:**
- If encoder receives a frame with unsupported pixel format:
  - MUST return `ERROR_UNSUPPORTED_PIXEL_FORMAT`
  - MUST transition sink to fault state
  - MUST NOT silently drop the frame
  - MUST NOT crash
- Fault state is latched until explicit reset or teardown (see INV-SINK-FAULT-LATCH-001)

**Enforcement:**
- Contract test: Feed encoder an unsupported format (e.g., YUV444P when configured for YUV420P)
- Verify: Fault state entered, error logged, no crash

**Violation log:**
```
[Encoder] INV-SINK-PIXEL-FORMAT-FAULT-001: Unsupported pixel format <format>, entering fault state
```

**Related rules:** RULE_HARVEST #6

---

### INV-ENCODER-NO-B-FRAMES-001

**Summary:** Encoder MUST NOT produce B-frames; output contains only I and P frames.

**Owner:** `EncoderPipeline`

**Type:** Semantic

**Full Definition:**
- Encoder configuration MUST set `max_b_frames = 0`
- All encoded packets MUST be I-frame (IDR) or P-frame
- B-frames are forbidden because they require future frames for decoding, which conflicts with live playout
- This complements INV-AIR-IDR-BEFORE-OUTPUT (keyframe gate)

**Enforcement:**
- Encoder init: Assert `max_b_frames = 0` in codec context
- Runtime: Validate `AV_PICTURE_TYPE_B` never appears in output

**Violation log:**
```
[Encoder] INV-ENCODER-NO-B-FRAMES-001 VIOLATION: B-frame detected in output (pict_type=%d)
```

**Related rules:** RULE_HARVEST #7

---

### INV-ENCODER-GOP-FIXED-001

**Summary:** GOP structure MUST be fixed and deterministic; no adaptive GOP sizing.

**Owner:** `EncoderPipeline`

**Type:** Semantic

**Full Definition:**
- GOP size is configured at encoder initialization and MUST NOT change during session
- No scene-change detection that alters GOP boundaries
- Keyframe interval is exactly `gop_size` frames apart (not "at least" or "at most")
- This ensures:
  - Random access at predictable intervals
  - Deterministic segment boundaries for switching
  - Reproducible output for same input

**Enforcement:**
- Config: `scenecut = 0` (disable adaptive keyframe insertion)
- Test: Encode sequence and verify keyframe interval is exactly `gop_size`

**Violation log:**
```
[Encoder] INV-ENCODER-GOP-FIXED-001: GOP size changed from %d to %d
```

**Related rules:** RULE_HARVEST #9

---

### INV-ENCODER-BITRATE-BOUNDED-001

**Summary:** Encoder MUST use strict CBR or capped VBR; bitrate within ±10% of target.

**Owner:** `EncoderPipeline`

**Type:** Semantic

**Full Definition:**
- Encoder bitrate mode MUST be one of:
  - CBR (constant bitrate)
  - Capped VBR (variable with hard ceiling)
- Instantaneous bitrate MUST NOT exceed `target_bitrate * 1.1`
- Average bitrate over any 1-second window MUST be within `target_bitrate ± 10%`
- This ensures:
  - Predictable transport stream rate
  - No buffer overflow at muxer/network
  - Consistent viewer experience

**Enforcement:**
- Config: Set `rc_mode = CBR` or equivalent
- Test: Measure output bitrate over 60 seconds, verify bounds

**Violation log:**
```
[Encoder] INV-ENCODER-BITRATE-BOUNDED-001: Bitrate %d exceeds ceiling %d
```

**Related rules:** RULE_HARVEST #11

---

### INV-SINK-FAULT-LATCH-001

**Summary:** Once sink enters Faulted state, it remains latched until explicit reset or full teardown.

**Owner:** `MpegTSOutputSink`

**Type:** Semantic

**Full Definition:**
- Fault state is a terminal operational state
- Once `status == Faulted`:
  - MUST remain Faulted until `Reset()` or destructor
  - MUST NOT silently recover to Running
  - MUST reject new operations with error
- Allows clean error propagation and explicit recovery decisions

**Enforcement:**
- State machine: No transition from Faulted except via Reset/teardown
- Test: Trigger fault, verify operations rejected until reset

**Violation log:**
```
[Sink] INV-SINK-FAULT-LATCH-001: Rejecting operation in Faulted state (call Reset() first)
```

**Related rules:** RULE_HARVEST #29

---

## Layer 2 - Coordination Invariants (Missing/Partial)

### INV-SINK-PRODUCER-THREAD-ISOLATION-001

**Summary:** Sink MUST never block the producer thread; producer MUST never block the sink thread.

**Owner:** `MpegTSOutputSink`, `FileProducer`

**Type:** Coordination

**Full Definition:**
- Producer → Buffer: `Push()` is non-blocking (returns immediately or with bounded timeout)
- Buffer → Sink: `Pop()` is non-blocking (returns immediately or with bounded timeout)
- If buffer is full, producer yields or applies backpressure (RULE-P10-DECODE-GATE)
- If buffer is empty, sink waits with bounded timeout, then pads
- Cross-thread blocking for unbounded time is forbidden

**Binding Rules:**
- Producer never calls blocking sink operations
- Sink never calls blocking producer operations
- All cross-boundary operations have timeouts ≤ 1 frame duration

**Enforcement:**
- Code review: No unbounded waits in cross-thread code paths
- Test: Artificially stall one side, verify other side does not deadlock

**Violation log:**
```
[Sink] INV-SINK-PRODUCER-THREAD-ISOLATION-001 VIOLATION: Blocked waiting for producer > %dms
```

**Related rules:** RULE_HARVEST #12, #13, #31, #32

---

### INV-LIFECYCLE-IDEMPOTENT-001

**Summary:** Start() and Stop() are idempotent; multiple calls are safe.

**Owner:** All lifecycle-managed components

**Type:** Coordination

**Full Definition:**
- `Start()`:
  - Returns `true` on first call (starts component)
  - Returns `false` if already running (no-op)
  - MUST NOT create duplicate threads or resources
- `Stop()`:
  - Is idempotent (safe to call multiple times)
  - First call initiates shutdown
  - Subsequent calls are no-ops
  - MUST NOT double-free resources

**Enforcement:**
- Test: Call Start() twice, verify single thread created
- Test: Call Stop() twice, verify no crash or double-free

**Violation log:**
```
[Component] INV-LIFECYCLE-IDEMPOTENT-001: Start() called while already running
[Component] INV-LIFECYCLE-IDEMPOTENT-001: Stop() called while already stopped
```

**Related rules:** RULE_HARVEST #18, #19, #34

---

### INV-TEARDOWN-BOUNDED-001

**Summary:** Teardown MUST complete within maximum drain timeout (default 3s).

**Owner:** `MpegTSOutputSink`, `PlayoutEngine`

**Type:** Coordination

**Full Definition:**
- When Stop() or teardown is initiated:
  - Encoder MUST be flushed to encode buffered frames
  - Muxer MUST write trailer and close gracefully
  - Thread MUST join within timeout (default 5s thread, 3s drain)
  - After timeout, force stop
- Prevents orphaned threads or resource leaks

**Enforcement:**
- Timeout: All teardown paths have bounded waits
- Test: Trigger teardown, verify completion within 5s

**Violation log:**
```
[Sink] INV-TEARDOWN-BOUNDED-001: Drain timeout exceeded, forcing stop
[Sink] INV-TEARDOWN-BOUNDED-001: Thread join timeout exceeded
```

**Related rules:** RULE_HARVEST #20, #21, #22, #23

---

### INV-CONFIG-IMMUTABLE-001

**Summary:** Configuration MUST NOT be modified after construction.

**Owner:** All configurable components

**Type:** Coordination

**Full Definition:**
- All configuration (fps, resolution, bitrate, format) is set at construction
- After construction, configuration is read-only
- Runtime changes require teardown + new instance
- Prevents undefined behavior from mid-session config changes

**Why:**
- Encoder cannot change resolution mid-stream
- FPS changes would break PTS continuity
- Format changes would confuse decoder

**Enforcement:**
- API design: No `SetConfig()` methods after construction
- Test: Attempt config change, verify rejection

**Violation log:**
```
[Component] INV-CONFIG-IMMUTABLE-001: Configuration change rejected after construction
```

**Related rules:** RULE_HARVEST #35

---

### INV-SINK-ROLE-BOUNDARY-001

**Summary:** Sink does not schedule content, decode frames, or manage channel state.

**Owner:** `MpegTSOutputSink`

**Type:** Coordination

**Full Definition:**
- Sink is pure encode/stream output
- Sink MUST NOT:
  - Schedule or select content (Core's responsibility)
  - Decode frames (Producer's responsibility)
  - Manage channel state (PlayoutEngine's responsibility)
  - Access schedule, EPG, or editorial data
- Sink receives decoded frames and emits encoded transport stream

**Enforcement:**
- Code review: No schedule/EPG references in sink code
- Architecture: Sink has no dependencies on Core types

**Related rules:** RULE_HARVEST #36

---

### INV-STARVATION-FAILSAFE-001

**Summary:** Loop starvation detection triggers fail-safe within bounded time.

**Owner:** `ProgramOutput`, `PlayoutEngine`

**Type:** Coordination

**Full Definition:**
- If render loop detects starvation (no frames to emit):
  - Detection: buffer empty for > 1 frame duration
  - Response: emit pad frames (INV-P8-OUTPUT-001)
  - Escalation: if starvation persists > 250ms, freeze last real frame then pad (INV-PACING-ENFORCEMENT-002)
- Fail-safe ensures output continuity even under producer failure

**Enforcement:**
- Test: Starve producer, verify pad frames emitted within tolerance
- Counter: `retrovue_underrun_events_total`

**Violation log:**
```
[ProgramOutput] INV-STARVATION-FAILSAFE-001: Starvation detected, emitting pad
```

**Related rules:** RULE_HARVEST #40

---

## Layer 3 - Diagnostic Invariants (Missing/Partial)

### INV-TIMING-DESYNC-LOG-001

**Summary:** Log desync event when timing falls behind schedule by more than threshold.

**Owner:** `MpegTSOutputSink`

**Type:** Diagnostic

**Full Definition:**
- If frame emission is > 50ms behind scheduled time:
  - Log WARNING with desync details
  - Increment `retrovue_desync_events_total` counter
- Does not trigger action (action is freeze-then-pad per INV-PACING-ENFORCEMENT-002)
- Diagnostic for debugging timing issues

**Log format:**
```
[Sink] INV-TIMING-DESYNC-LOG-001: Desync detected, behind_ms=%d, frame_pts=%ld
```

**Related rules:** RULE_HARVEST #15

---

### INV-NETWORK-BACKPRESSURE-DROP-001

**Summary:** Network backpressure causes frame drop (not block), with logging.

**Owner:** `MpegTSOutputSink`

**Type:** Diagnostic (enforcement deferred to network layer)

**Full Definition:**
- When TCP/network buffer is full:
  - DO NOT block on write
  - Drop the packet/frame
  - Log the drop
  - Increment drop counter
- Network backpressure is a downstream problem that MUST NOT propagate back to timing

**Note:** This rule conflicts with INV-PACING-ENFORCEMENT-002 (no drops during normal operation). Resolution:
- INV-PACING-ENFORCEMENT-002 applies to producer → buffer → sink
- INV-NETWORK-BACKPRESSURE-DROP-001 applies to sink → network (downstream of timing)

**Violation log:**
```
[Sink] INV-NETWORK-BACKPRESSURE-DROP-001: Dropped packet due to network backpressure
```

**Related rules:** RULE_HARVEST #3, #4, #5

---

## Cross-Domain Invariants (Core/AIR Boundary)

### INV-CANONICAL-CONTENT-ONLY-001

**Summary:** AIR MUST NOT play non-canonical content.

**Owner:** `PlayoutEngine` (enforcement), `Core` (definition)

**Type:** Semantic (cross-domain)

**Full Definition:**
- Only assets with `canonical=true` may be played
- AIR receives playout plans from Core
- AIR MUST reject plans referencing non-canonical assets
- This is a contract between Core and AIR:
  - Core: MUST NOT generate plans with non-canonical assets
  - AIR: MUST validate and reject if violated

**Enforcement:**
- Validation: Check asset canonical flag in legacy preload RPC
- Rejection: Return error if non-canonical

**Violation log:**
```
[PlayoutEngine] INV-CANONICAL-CONTENT-ONLY-001: Rejected non-canonical asset in playout plan
```

**Related rules:** RULE_HARVEST #52, #53, #58, #59, #60

---

## Summary Table

| ID | Summary | Type | Status |
|----|---------|------|--------|
| INV-SINK-TIMING-OWNERSHIP-001 | Sink owns timing loop via MasterClock | Semantic | Draft |
| INV-SINK-PIXEL-FORMAT-FAULT-001 | Unsupported format → fault, not silent drop | Semantic | Draft |
| INV-ENCODER-NO-B-FRAMES-001 | No B-frames in encoder output | Semantic | Draft |
| INV-ENCODER-GOP-FIXED-001 | Fixed, deterministic GOP | Semantic | Draft |
| INV-ENCODER-BITRATE-BOUNDED-001 | Bitrate within ±10% of target | Semantic | Draft |
| INV-SINK-FAULT-LATCH-001 | Fault state latched until reset | Semantic | Draft |
| INV-SINK-PRODUCER-THREAD-ISOLATION-001 | No cross-thread blocking | Coordination | Draft |
| INV-LIFECYCLE-IDEMPOTENT-001 | Start/Stop idempotent | Coordination | Draft |
| INV-TEARDOWN-BOUNDED-001 | Teardown within timeout | Coordination | Draft |
| INV-CONFIG-IMMUTABLE-001 | No config changes after construction | Coordination | Draft |
| INV-SINK-ROLE-BOUNDARY-001 | Sink doesn't schedule/decode | Coordination | Draft |
| INV-STARVATION-FAILSAFE-001 | Fail-safe on starvation | Coordination | Draft |
| INV-TIMING-DESYNC-LOG-001 | Log desync events | Diagnostic | Draft |
| INV-NETWORK-BACKPRESSURE-DROP-001 | Network drop, not block | Diagnostic | Draft |
| INV-CANONICAL-CONTENT-ONLY-001 | Only canonical content | Semantic | Draft |

---

## Contradictions Identified

### Drop Policy Conflict

**Historical:** RULE_HARVEST #3, #14 require dropping frames when behind schedule.

**Current:** INV-PACING-ENFORCEMENT-002 requires freeze-then-pad, no drops.

**Resolution:** The historical drop policy applied to the old sink-driven timing model. The current freeze-then-pad policy is canonical and applies to producer → buffer → sink. Network-layer drops (sink → viewer) remain allowed as they're downstream of timing authority.

### Timing Thresholds

**Historical:** RULE_HARVEST #14 says drop if > 2 frames behind; #15 says log if > 50ms behind; #16 says sleep if > 5ms ahead.

**Current:** INV-PACING-ENFORCEMENT-002 and Phase 10 define pacing rules without specific thresholds.

**Resolution:** Specific thresholds are implementation details, not invariants. The canonical contracts define the policies (freeze-then-pad, no drops) without prescribing exact thresholds.

---

## Next Steps

1. Review with stakeholders
2. Identify which invariants should be promoted to canonical contracts
3. For each promoted invariant:
   - Add to INVARIANTS-INDEX.md
   - Create contract tests
   - Update component implementations
4. Archive remaining rules as historical context
