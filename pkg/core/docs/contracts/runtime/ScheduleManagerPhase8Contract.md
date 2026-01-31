# ScheduleManager Phase 8 Contract: Unified Timeline Authority

**Status:** Draft
**Version:** 0.1.0
**Phase:** 8
**Depends On:** Phase 7 (Seamless Segment Transitions), MasterClockContract

---

## 1. Overview

Phase 8 establishes a single, authoritative timeline for each channel session. Prior phases achieved producer-level correctness (Phase 6) and seamless transitions (Phase 7), but time authority remained distributed—producers computed epoch-relative PTS values, and downstream components interpreted those values with implicit assumptions. This distribution of time semantics created opportunities for divergence, especially during segment transitions where two producers briefly coexist.

Phase 8 eliminates distributed time authority by introducing the **Timeline Controller** as the sole owner of channel time. Producers become time-agnostic frame sources that emit media-relative content. The Timeline Controller owns all mappings between media time, channel time, and wall-clock time. After Phase 8, segment transitions require no special-case timing logic because producers provide frames, the Timeline Controller assigns their channel position, and the renderer schedules output.

---

## 2. Scope

### In Scope
- Channel time (CT) as the single authoritative timeline
- Media time (MT) as producer-local, non-authoritative metadata
- Timeline Controller as the exclusive CT authority
- PTS assignment at the timeline boundary (not in producers)
- Segment mapping computation at transition points
- Frame admission windows and rejection criteria
- Backpressure isolation from timeline advancement

### Out of Scope (Non-Goals)
- Producer decode internals (Phase 6)
- Hot-switch mechanics (Phase 7 / OutputSwitchingContract)
- Transport and muxing (Phase 8 AIR sub-contracts)
- Multi-channel coordination
- DVR, rewind, or trickplay

---

## 3. Terminology

| Term | Definition |
|------|------------|
| **Wall-Clock Time (W)** | Real-world UTC time in microseconds, provided by MasterClock. Read-only reference. |
| **Channel Time (CT)** | Monotonic timeline scoped to a channel session, measured in microseconds from session start (CT=0). |
| **Media Time (MT)** | Position within a media asset as reported by the decoder. Producer-local, non-authoritative. |
| **Epoch** | The wall-clock instant corresponding to CT=0 for this session. Immutable after establishment. |
| **Timeline Controller** | The component with exclusive authority over CT assignment. |
| **CT Cursor** | The current position in channel time, advanced by admitted frames. |
| **Segment Mapping** | The function `CT = CT_segment_start + (MT - MT_segment_start)` for a given segment. |
| **Admission Window** | The CT range within which frames are accepted, centered on expected CT. |
| **Frame Period** | Duration of one frame at the session's frame rate (e.g., 33,333µs at 30fps). |
| **Frame-Driven CT** | CT advancement model where CT_cursor advances only when frames are admitted (chosen model). |
| **Clock-Driven CT** | Alternative model where CT_cursor advances at wall-clock rate regardless of frames (not used). |
| **Underrun** | Condition where no frame is available when the renderer needs one; CT pauses under frame-driven model. |
| **Steady-State** | Normal operation with frames flowing; CT tracks wall-clock. |

---

## 4. Time Domain Separation

### 4.1 Media Time (Producer Domain)

Producers operate exclusively in the MT domain.

**Producers SHALL:**
- Decode frames and extract MT from the container/codec
- Report MT accurately in frame metadata
- Emit frames in decode order

**Producers SHALL NOT:**
- Compute, store, or reason about CT
- Read the epoch
- Apply PTS offsets for channel alignment
- Make emission decisions based on channel position
- Implement pacing or scheduling

### 4.2 Channel Time (Timeline Controller Domain)

The Timeline Controller operates exclusively in the CT domain.

**The Timeline Controller SHALL:**
- Maintain the current channel cursor (CT_cursor)
- Compute and store the epoch at session start
- Accept frames with MT metadata from producers
- Assign CT to each admitted frame using the segment mapping
- Reject frames whose computed CT falls outside the admission window
- Advance CT_cursor by one frame period per admitted frame

**The Timeline Controller SHALL NOT:**
- Delegate CT computation to producers or other components
- Allow multiple writers to CT_cursor
- Infer timing from frame content

### 4.3 Mapping Formula

The segment mapping SHALL be:

```
CT_frame = CT_segment_start + (MT_frame - MT_segment_start)
```

Where:
- `CT_segment_start` is the CT when this segment began output
- `MT_segment_start` is the MT of the first admitted frame from this segment

This mapping SHALL be computed once per segment, at segment activation.

---

## 5. Timeline Controller Specification

### 5.1 Designation

The Timeline Controller SHALL be a single logical component within the playout engine. There SHALL be exactly one Timeline Controller per active channel session.

### 5.2 State

The Timeline Controller maintains:
- `epoch`: Wall-clock time corresponding to CT=0 (immutable after set)
- `CT_cursor`: Current position in channel time
- `segment_mapping`: Active (CT_segment_start, MT_segment_start) tuple

### 5.3 Operations

| Operation | Precondition | Effect |
|-----------|--------------|--------|
| `EstablishEpoch(W_now)` | Session starting, epoch not set | epoch := W_now, CT_cursor := 0 |
| `SetSegmentMapping(CT_start, MT_start)` | Segment transition | segment_mapping := (CT_start, MT_start) |
| `AdmitFrame(MT_frame)` | Frame presented | Compute CT_frame, apply admission rules, advance CT_cursor if admitted |
| `GetScheduledTime(CT)` | Any | Return epoch + CT |

### 5.4 Admission Rules

For each frame presented to the Timeline Controller:

1. Compute `CT_frame` using the segment mapping
2. Compute `CT_expected = CT_cursor + frame_period`
3. Evaluate admission:

| Condition | Action |
|-----------|--------|
| `\|CT_frame - CT_expected\| <= tolerance` | ADMIT, set frame.CT := CT_expected, advance CT_cursor |
| `CT_frame < CT_expected - late_threshold` | REJECT (late) |
| `CT_frame > CT_expected + early_threshold` | REJECT (early) |

### 5.5 CT Advancement Model

**Design Decision: Frame-Driven CT**

This contract specifies **frame-driven CT advancement**: CT_cursor advances only when a frame is admitted. The alternative—clock-driven CT where the cursor advances at wall-clock rate regardless of frame availability—was considered and rejected.

**Rationale for Frame-Driven:**

1. **Simplicity**: No background timer required; advancement is purely reactive
2. **Determinism**: CT sequence depends only on frame sequence, not wall-clock timing
3. **Buffer Semantics**: Ring buffer depth directly corresponds to CT lookahead
4. **Test Reproducibility**: Tests can control CT by controlling frame admission

**Consequence: Underrun Semantics**

If no frame is available when the renderer needs one (buffer underrun):
- CT_cursor does NOT advance autonomously
- The renderer emits black/silence at the *current* CT position
- When frames resume, CT picks up from where it paused
- Wall-clock will have advanced; CT will be "behind" wall-clock temporarily
- This is acceptable: the channel catches up as frames flow, or the session restarts

**Alternative Considered: Clock-Driven CT**

In clock-driven systems, CT advances at wall-clock rate regardless of frame availability. This ensures CT always matches wall-clock, but:
- Requires handling "missed" CT positions explicitly
- Late frames must be dropped (no catch-up possible)
- More complex state machine

Clock-driven may be revisited if underrun-without-stall becomes a requirement.

---

### 5.6 Catch-Up Semantics After Underrun

When frames resume after an underrun, CT will be behind wall-clock. Multiple frames may have scheduled deadlines in the past. The renderer must handle this explicitly.

**Design Decision: Emit-Until-Caught-Up**

After underrun recovery, past-deadline frames SHALL be emitted immediately (no pacing) until CT catches up to wall-clock. This is chosen over drop-and-skip.

**Behavior:**

| Condition | Action |
|-----------|--------|
| `deadline < W_now` | Emit immediately (no wait) |
| `deadline >= W_now` | Resume normal pacing (wait until deadline) |

**Rationale for Emit-Until-Caught-Up:**

1. **Content Preservation**: Viewers see all content, just compressed in time temporarily
2. **Simpler Recovery**: No need to compute "where should CT be now"
3. **Self-Limiting**: Catch-up rate bounded by decode/encode speed
4. **Audible but Recoverable**: Brief fast-forward is less jarring than content skip

**Alternative: Drop-and-Skip**

In drop-and-skip, past-deadline frames are discarded and CT jumps to match wall-clock:
- Pro: CT always matches wall-clock after recovery
- Con: Content lost; visible discontinuity
- Con: Requires computing "current" CT from wall-clock

Drop-and-skip may be preferred for live/real-time sources where freshness matters more than completeness.

**Implementation Requirements:**

1. Renderer MUST detect catch-up state: `deadline < W_now`
2. Renderer MUST emit without sleep when in catch-up state
3. Renderer MUST log catch-up events: `[CATCH-UP] emitting N frames, lag=Xms`
4. Renderer MUST resume normal pacing when `deadline >= W_now`
5. Catch-up rate SHOULD be monitored; sustained catch-up indicates systemic underrun

**Catch-Up Limit:**

If `W_now - (epoch + CT_cursor) > catch_up_limit` (default: 5 seconds), the session SHOULD be restarted rather than attempting extended catch-up. This prevents unbounded fast-forward after long outages.

---

### 5.7 Admission Threshold Derivation

The admission window thresholds are derived from system parameters, not arbitrary constants.

**Parameters:**

| Parameter | Symbol | Typical Value |
|-----------|--------|---------------|
| Frame rate | `fps` | 30 fps |
| Frame period | `P` | 33,333 µs |
| Target buffer depth | `D_target` | 5 frames |
| Maximum buffer depth | `D_max` | 30 frames |
| Acceptable latency | `L_max` | 500,000 µs |

**Derivation:**

```
tolerance       = P                           (snap to nearest frame)
late_threshold  = min(L_max, D_target * P)    (how late is recoverable)
early_threshold = D_max * P                   (how much lookahead buffer allows)
```

**Justification:**

- **tolerance = P**: Frames within one frame period of expected are snapped to the grid. This handles minor timing jitter without rejection.

- **late_threshold**: A frame is "too late" when it cannot be used for its intended position AND the buffer has moved on. With `D_target = 5` frames buffered ahead, a frame more than 5 frame periods late (166ms at 30fps) has definitely missed its slot. The 500ms default provides margin for decode variance.

- **early_threshold**: A frame is "too early" when it would overflow the buffer or represent unreasonable lookahead. With `D_max = 30` frames, early_threshold = 1,000,000 µs (1 second) is reasonable. The 500ms default is conservative.

**Configuration:**

Implementations SHOULD expose these as configurable parameters:

```
timeline.tolerance_frames      = 1      # frames
timeline.late_threshold_ms     = 500    # milliseconds
timeline.early_threshold_ms    = 500    # milliseconds
```

Or derive from buffer configuration:

```
timeline.late_threshold_ms     = buffer.target_depth * (1000 / fps)
timeline.early_threshold_ms    = buffer.max_depth * (1000 / fps)
```

---

## 6. Session Lifecycle

### 6.1 Session Start

On session start:

1. Timeline Controller establishes epoch: `epoch := W_now`
2. CT_cursor := 0
3. First producer's first admitted frame establishes MT_segment_start
4. CT_segment_start := 0
5. Segment mapping becomes active

### 6.2 Session Continuation

During normal operation:

1. CT_cursor advances by one frame period per admitted frame (frame-driven)
2. The relationship `W = epoch + CT` holds under steady-state (no underrun)
3. Frames are admitted in strict CT order
4. Consumer backpressure does not affect CT advancement

**Underrun Behavior (Frame-Driven Consequence):**

If the producer fails to supply frames:
- CT_cursor pauses (does not advance without frames)
- Renderer emits black/silence for the stalled CT position
- When frames resume, CT continues from the paused position
- CT may temporarily lag behind wall-clock; this is recovered as frames catch up
- Persistent underrun (>N seconds) MAY trigger session restart

### 6.3 Session Termination

On session termination:

1. All timeline state is discarded
2. Epoch is cleared
3. CT_cursor is reset

A new session starts fresh with no inherited timeline state.

---

## 7. Segment Transitions

### 7.1 Transition Trigger

A segment transition occurs when:
- The schedule indicates segment N ends and segment N+1 begins
- The outgoing producer's write barrier is activated
- The incoming producer has frames available

### 7.2 Transition Procedure

1. **Barrier**: Outgoing producer write barrier set (per INV-P7-007)
2. **Mapping Computation**:
   - `CT_segment_start := CT_cursor + frame_period`
   - `MT_segment_start := MT` of incoming producer's next frame
3. **Mapping Activation**: Timeline Controller adopts new segment mapping
4. **Handoff**: Incoming buffer becomes active input
5. **Resume**: Normal frame admission continues

### 7.3 Transition Atomicity

From the timeline's perspective, the transition is instantaneous. There is no CT value that is ambiguously owned by either segment.

### 7.4 No Cross-Producer State Dependency

The incoming producer's CT assignment SHALL NOT depend on any internal state of the outgoing producer. It SHALL depend only on:
- `CT_cursor` as maintained by the Timeline Controller
- `MT_segment_start` from the incoming producer's first frame

---

## 8. Invariants

### Timeline Invariants

#### INV-P8-001: Single Timeline Writer

**Statement:** The Timeline Controller MUST be the only component that assigns CT values to frames. No other component MAY write, compute, or influence CT values.

**Rationale:** Distributed time authority leads to divergent timelines and timing bugs.

**Observable:** Producers emit frames with MT only; CT appears only after Timeline Controller admission.

---

#### INV-P8-002: Monotonic Advancement

**Statement:** For any two frames F1 and F2 admitted to the active buffer, if F1 was admitted before F2, then CT(F1) < CT(F2). No exceptions.

**Rationale:** Timeline reversal causes playback glitches and violates viewer expectations.

**Observable:** CT values in the output stream are strictly increasing.

---

#### INV-P8-003: Contiguous Coverage

**Statement:** The difference between consecutive admitted frames' CT values MUST equal exactly one frame period (within quantization tolerance). Gaps MUST NOT exist in CT.

**Rationale:** CT gaps manifest as visible stutters or freezes.

**Observable:** `CT(F_{n+1}) - CT(F_n) = frame_period` for all consecutive frames.

---

#### INV-P8-004: Wall-Clock Correspondence

**Statement:** Under steady-state operation (no underrun), the relationship `W = epoch + CT` MUST hold. CT advances at wall-clock rate when frames are flowing.

**Rationale:** Drift between CT and wall-clock causes sync issues with external systems.

**Clarification (Frame-Driven Model):** During underrun, CT pauses while wall-clock advances. This is intentional—CT represents "content time," not "elapsed time." When frames resume, CT catches up. Persistent divergence (>N seconds) indicates a system fault.

**Observable:** Under steady-state, `|W_now - (epoch + CT_cursor)| < late_threshold`.

---

#### INV-P8-005: Epoch Immutability

**Statement:** Once epoch is set for a session, it MUST NOT change until session termination. No component MAY request, suggest, or force epoch modification.

**Rationale:** Epoch change invalidates all existing CT values and causes discontinuity.

**Observable:** Epoch value at session start equals epoch value at any point during session.

---

### Producer Invariants

#### INV-P8-006: Producer Time Blindness

**Statement:** Producers MUST NOT read, store, or compute any value in the CT domain. Producer logic MUST be expressible using only MT and frame sequence.

**Rationale:** Producers that know about CT can make incorrect timing assumptions.

**Observable:** Producer code contains no references to epoch, CT, or channel-relative time.

---

#### INV-P8-007: Write Barrier Finality

**Statement:** Once a write barrier is set for a producer, that producer instance MUST NOT successfully write any frame to any buffer. The barrier is permanent for that producer instance.

**Rationale:** Post-barrier writes corrupt the timeline with stale frames.

**Observable:** Frame count from producer after barrier = 0.

---

#### INV-P8-008: Frame Provenance

**Statement:** Every frame in the active buffer MUST have a single, traceable provenance: one producer, one MT, one assigned CT.

**Rationale:** Ambiguous provenance makes debugging impossible.

**Observable:** Each frame carries producer_id, MT, and CT metadata.

---

### Transition Invariants

#### INV-P8-009: Atomic Buffer Authority

**Statement:** At any instant, exactly one buffer MUST be designated as the active input to ProgramOutput. The transition between buffers MUST be instantaneous.

**Rationale:** Overlapping authority causes duplicate or missing frames.

**Observable:** Buffer switch is a single atomic operation with no intermediate state.

---

#### INV-P8-010: No Cross-Producer Dependency

**Statement:** The new producer's CT assignment MUST depend only on Timeline Controller state (CT_cursor), not on any internal state of the previous producer.

**Rationale:** Cross-producer dependencies create timing coupling and race conditions.

**Observable:** New segment mapping uses only CT_cursor and new producer's MT.

---

### System Invariants

#### INV-P8-011: Backpressure Isolation

**Statement:** Consumer slowness (encoder, network, disk) MUST NOT affect CT advancement. Frames MAY be dropped to maintain timeline, but time MUST NOT slow.

**Rationale:** Coupling consumer speed to timeline creates unpredictable timing.

**Observable:** CT_cursor advances at wall-clock rate regardless of output queue depth.

---

#### INV-P8-012: Deterministic Replay

**Statement:** Given identical session start time and segment sequence, the CT assigned to each frame MUST be identical across runs.

**Rationale:** Non-deterministic CT prevents reproducible testing and debugging.

**Observable:** Two runs with same inputs produce same CT sequence.

---

### Output Invariants

#### INV-P8-OUTPUT-001: Deterministic Output Liveness

**Statement:** When a channel is in LIVE state and an output sink is attached, the system MUST guarantee that encoded media packets are made externally observable within a bounded time window.

Specifically:

- Successful submission of packets to a muxer (e.g., `av_interleaved_write_frame`) MUST NOT be treated as evidence of output delivery.
- The playout engine MUST explicitly flush or otherwise force emission of muxed data to the configured output transport (e.g., via `avio_flush` or equivalent).
- Output correctness MUST NOT depend on:
  - Muxer internal buffering thresholds
  - Packet interleaving heuristics
  - Implicit format flush behavior
  - Accidental overproduction of frames
- A channel in LIVE state with an attached sink MUST demonstrate observable output progress (bytes written, transport send, or equivalent), or the system MUST surface an output-stall fault.

**Rationale:** Output must be intentional, not incidental. The muxer's internal buffering semantics are implementation details that can change across FFmpeg versions or configurations. Relying on implicit flush behavior couples system correctness to opaque third-party internals.

**Observable:** Within N milliseconds of the first admitted frame in LIVE state, the output sink MUST receive at least one observable write. The output layer reports `output_bytes_written > 0` or equivalent metric.

**Verification:**
- Unit test with mock AVIO callback that asserts write invocation timing
- Integration test that verifies socket receives bytes within bounded time
- Metrics: `output_bytes_written`, `output_write_count`, `output_stall_events`

---

## 9. Failure Modes

### 9.1 Contained Failures

The following failures MUST NOT affect the timeline:

| Failure | Containment |
|---------|-------------|
| Producer decode error | Producer emits error event, Timeline Controller continues from last admitted frame |
| Producer crash | Write barrier auto-set, transition triggered, CT_cursor preserved |
| Buffer overflow | Frames dropped at admission, CT advances |
| Encoder backpressure | Frames dropped after render, timeline unaffected |
| Network stall | Muxer buffers or drops, timeline unaffected |

### 9.2 Logged Failures

The following failures SHALL be logged but not halt the session:

- Buffer underrun (frames not available at render time)
- Excessive frame drops (>N consecutive)
- Admission window violations (frame too early/late)
- Segment mapping edge cases

### 9.3 Fatal Failures

The following failures SHALL terminate the session:

- Timeline Controller internal corruption
- Epoch mutation attempt after lock
- Invariant violation detected
- CT_cursor regression

---

## 10. Component Responsibility Matrix

| Component | Time Responsibilities | Forbidden Actions |
|-----------|----------------------|-------------------|
| **MasterClock** | Provide W (wall-clock). Store epoch. Convert CT ↔ W. | Infer timeline from frame content. Accept epoch from producers. |
| **Timeline Controller** | Own CT_cursor. Assign frame CT. Define segment mappings. Enforce admission window. | Delegate CT computation. Allow multiple writers. |
| **Producer** | Report MT accurately. Decode frames. Respect write barriers. | Compute CT. Set epoch. Infer channel position. Mutate timeline state. |
| **Ring Buffer** | Store frames with assigned CT. Provide depth metrics. | Reorder frames. Modify CT. Make timing decisions. |
| **ProgramOutput / Renderer** | Schedule output using CT and epoch. Pace to wall-clock. | Modify CT. Infer timing. Backpressure timeline. |
| **Encoder / Muxer** | Encode at presented rate. Use provided PTS. | Introduce timing. Recompute PTS. |

---

## 11. Lower Phase Relief

### 11.1 Phase 6 Relief

Phase 6 producers are NO LONGER responsible for:
- Computing PTS offsets for channel alignment
- Setting or reading epoch
- Coordinating timing with other producers
- Implementing AlignPTS or equivalent

### 11.2 Phase 7 Relief

Phase 7 transition logic is NO LONGER responsible for:
- AlignPTS calculations between producers
- Cross-producer PTS coordination
- Retry loops for timing convergence
- Shadow mode PTS bookkeeping
- "Almost correct" offset calculations

### 11.3 Eliminated Complexity

The following mechanisms become unnecessary under Phase 8:
- Producer-side `pts_offset_us_` calculation
- Producer-side epoch awareness
- Preview producer PTS alignment before switch
- Cross-segment PTS adjustment
- Timing-based retry logic at transition

---

## 12. Test Specifications

### P8-T001: Producer Emits MT Only

**Precondition:** Producer decoding a media file.

**Action:** Observe frame metadata before Timeline Controller admission.

**Verification:**
- Frame contains MT (media position)
- Frame does not contain CT
- Producer code has no epoch access

---

### P8-T002: Timeline Controller Assigns CT

**Precondition:** Frame admitted to Timeline Controller.

**Action:** Observe frame metadata after admission.

**Verification:**
- Frame now contains CT
- CT = CT_cursor at admission time
- CT_cursor advanced by frame_period

---

### P8-T003: CT Monotonicity Across Transition

**Precondition:** Segment A playing, segment B ready.

**Action:** Execute segment transition.

**Verification:**
- Last frame of A has CT = T
- First frame of B has CT = T + frame_period
- No CT gap or regression

---

### P8-T004: Epoch Unchanged by Transition

**Precondition:** Session started, epoch recorded.

**Action:** Execute multiple segment transitions.

**Verification:**
- Epoch value unchanged throughout
- All CT values relative to original epoch

---

### P8-T005: Segment Mapping Independence

**Precondition:** Producer A at MT=1000s, Producer B at MT=500s.

**Action:** Transition from A to B.

**Verification:**
- B's first frame CT = CT_cursor + frame_period
- B's CT does not depend on A's MT
- Mapping uses only CT_cursor and B's MT

---

### P8-T006: Late Frame Rejection

**Precondition:** Timeline Controller with CT_cursor = 1,000,000µs.

**Action:** Present frame with MT mapping to CT = 0.

**Verification:**
- Frame rejected (late)
- CT_cursor unchanged
- Rejection logged

---

### P8-T007: Early Frame Rejection

**Precondition:** Timeline Controller with CT_cursor = 1,000,000µs.

**Action:** Present frame with MT mapping to CT = 10,000,000µs.

**Verification:**
- Frame rejected (early)
- CT_cursor unchanged
- Rejection logged

---

### P8-T008: Backpressure Does Not Slow Timeline

**Precondition:** Consumer artificially blocked.

**Action:** Continue admitting frames for 1 second.

**Verification:**
- CT_cursor advanced by ~1,000,000µs
- Frames may be dropped
- Timeline not stalled

---

### P8-T009: Deterministic CT Assignment

**Precondition:** Known segment sequence with known MTs.

**Action:** Run session twice with same inputs.

**Verification:**
- CT sequence identical in both runs
- No timing-dependent variation

---

### P8-T010: Write Barrier Prevents Post-Switch Writes

**Precondition:** Producer A with write barrier set.

**Action:** Producer A attempts to write frame.

**Verification:**
- Write fails or frame discarded
- No frame from A appears in buffer after barrier
- Timeline Controller unaffected

---

### P8-T011: Underrun Pauses CT (Frame-Driven)

**Precondition:** Session running, CT_cursor = 1,000,000µs.

**Action:** Producer stops emitting frames for 500ms (wall-clock).

**Verification:**
- CT_cursor remains at 1,000,000µs (does not advance)
- Renderer emits black/silence at CT = 1,000,000µs position
- When producer resumes, CT advances from 1,000,000µs
- No frames are lost or duplicated

---

### P8-T012: Threshold Derivation from Buffer Config

**Precondition:** System configured with fps=30, buffer_target=5, buffer_max=30.

**Action:** Compute thresholds.

**Verification:**
- late_threshold = min(500ms, 5 * 33.3ms) = 166ms (or configured 500ms)
- early_threshold = 30 * 33.3ms = 1000ms (or configured 500ms)
- Thresholds are applied correctly in admission decisions

---

## 13. Relationship to Other Phases

| Phase | Relationship |
|-------|--------------|
| **Phase 6** | Producers decode and report MT; Phase 8 removes their CT responsibility |
| **Phase 7** | Transitions remain seamless; Phase 8 simplifies transition timing logic |
| **MasterClockContract** | Provides W and epoch storage; Phase 8 defines usage constraints |
| **OutputSwitchingContract (AIR)** | Hot-switch mechanism unchanged; Phase 8 ensures CT continuity across switch |

---

## 14. Contract Compliance

An implementation complies with Phase 8 if:

1. All INV-P8-XXX invariants hold under normal operation
2. All P8-TXXX tests pass
3. Producers emit MT only, never CT
4. Timeline Controller exclusively assigns CT
5. Segment transitions complete without timing special-cases
6. Epoch remains immutable throughout session
7. Backpressure does not affect CT advancement

---

## Appendix A: Invariant Summary

| ID | Name | Core Guarantee |
|----|------|----------------|
| INV-P8-001 | Single Timeline Writer | Only Timeline Controller assigns CT |
| INV-P8-002 | Monotonic Advancement | CT never decreases |
| INV-P8-003 | Contiguous Coverage | No gaps in CT sequence |
| INV-P8-004 | Wall-Clock Correspondence | CT tracks wall-clock under steady-state |
| INV-P8-005 | Epoch Immutability | Epoch never changes during session |
| INV-P8-006 | Producer Time Blindness | Producers cannot access CT |
| INV-P8-007 | Write Barrier Finality | Barrier permanently stops writes |
| INV-P8-008 | Frame Provenance | Each frame has single source |
| INV-P8-009 | Atomic Buffer Authority | One active buffer at a time |
| INV-P8-010 | No Cross-Producer Dependency | New CT independent of old producer |
| INV-P8-011 | Backpressure Isolation | Consumer speed doesn't affect time |
| INV-P8-012 | Deterministic Replay | Same inputs produce same CT |
| INV-P8-OUTPUT-001 | Deterministic Output Liveness | Output must be explicitly flushed, not implicitly buffered |

---

## Appendix B: Time Domain Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TIME DOMAINS                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  WALL-CLOCK (W)          CHANNEL TIME (CT)         MEDIA TIME (MT)      │
│  ══════════════          ═════════════════         ═══════════════      │
│                                                                          │
│  Owner: MasterClock      Owner: Timeline           Owner: Producer      │
│                          Controller                (read-only)          │
│                                                                          │
│  UTC microseconds        Session-relative          Asset-relative       │
│                          microseconds              microseconds         │
│                                                                          │
│  Read by: All            Written by: Timeline      Written by: Decoder  │
│  Written by: System      Controller ONLY           Read by: Timeline    │
│                                                    Controller           │
│                                                                          │
│  ┌─────────────┐         ┌─────────────┐          ┌─────────────┐       │
│  │ 1706659200  │ ──────► │     0       │          │  1087850666 │       │
│  │ (session    │  epoch  │ (session    │  mapping │  (seek pos  │       │
│  │  start)     │         │  start)     │ ◄─────── │  in file)   │       │
│  └─────────────┘         └─────────────┘          └─────────────┘       │
│         │                       │                        │              │
│         │                       │                        │              │
│         ▼                       ▼                        ▼              │
│  ┌─────────────┐         ┌─────────────┐          ┌─────────────┐       │
│  │ 1706659201  │ ──────► │  1000000    │          │  1087851666 │       │
│  │ (+1 second) │   W-e   │ (+1 second) │  mapping │  (+1 second │       │
│  │             │         │             │ ◄─────── │   in file)  │       │
│  └─────────────┘         └─────────────┘          └─────────────┘       │
│                                                                          │
│  Conversion: W = epoch + CT                                              │
│  Mapping: CT = CT_seg_start + (MT - MT_seg_start)                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Appendix C: Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PHASE 8 DATA FLOW                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐                                                        │
│  │   Producer   │  Emits frames with MT only                            │
│  │   (decode)   │  ───────────────────────────────────────►             │
│  └──────────────┘                                          │            │
│                                                             │            │
│                                                             ▼            │
│                                              ┌──────────────────────┐   │
│                                              │  Timeline Controller │   │
│                                              │  ────────────────────│   │
│                                              │  • Compute CT_frame  │   │
│                                              │  • Check admission   │   │
│                                              │  • Assign CT         │   │
│                                              │  • Advance cursor    │   │
│                                              └──────────────────────┘   │
│                                                             │            │
│                                                             │ Frame with │
│                                                             │ CT assigned│
│                                                             ▼            │
│                                              ┌──────────────────────┐   │
│                                              │    Ring Buffer       │   │
│                                              │  (frames have CT)    │   │
│                                              └──────────────────────┘   │
│                                                             │            │
│                                                             ▼            │
│                                              ┌──────────────────────┐   │
│                                              │   ProgramOutput      │   │
│                                              │  ────────────────────│   │
│  ┌──────────────┐                            │  • Schedule by CT    │   │
│  │ MasterClock  │ ─── epoch, W_now ────────► │  • Pace to W         │   │
│  └──────────────┘                            │  • Emit at deadline  │   │
│                                              └──────────────────────┘   │
│                                                             │            │
│                                                             ▼            │
│                                              ┌──────────────────────┐   │
│                                              │   Output Stream      │   │
│                                              │  (CT-continuous)     │   │
│                                              └──────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 15. Invariant Supersession and Decommissioning

This section explicitly supersedes and invalidates certain invariants defined in prior phases.
**Any implementation that enforces a superseded invariant while Phase 8 is active is non-compliant.**

### 15.1 Conflict Resolution Rule

**If a revoked invariant conflicts with a Phase 8 invariant, the Phase 8 invariant MUST win, and the older invariant MUST be removed or scoped.**

This is not optional. This is not a suggestion. Implementations MUST NOT attempt to reconcile or preserve old invariants unless explicitly scoped in this document.

### 15.2 Scoping Rule

| Condition | Action |
|-----------|--------|
| Invariant remains valid in legacy mode (no TimelineController) | SCOPE to legacy path only |
| Invariant remains valid in shadow mode only | SCOPE to shadow mode only |
| Invariant assigns time authority to producers | REVOKE |
| Invariant conflicts with TimelineController ownership | REVOKE |
| Otherwise | REVOKE (default) |

### 15.3 Superseded Invariants: Phase 6

| Prior Invariant | Status | Reason | Replacement |
|-----------------|--------|--------|-------------|
| **INV-P6-SEEK-001** (implicit): Producer frame suppression until MT ≥ target_pts | **SCOPED** | Valid ONLY when TimelineController is NOT active OR producer is in shadow mode. When TimelineController is active and live, producer is TIME-BLIND and MUST NOT suppress frames. | INV-P8-006 (Producer Time Blindness) + §15.3a |
| **INV-P6-008**: Clock-Gated Emission (producer paces to wall-clock) | **REVOKED** | Producer no longer performs pacing. TimelineController assigns CT; Renderer paces to W. | INV-P8-004 (Wall-Clock Correspondence via Renderer) |
| **INV-P6-010**: Audio-Video Emission Parity (audio waits for video epoch) | **SCOPED** | Valid ONLY when TimelineController is NOT active OR producer is in shadow mode. Phase 8 audio/video sync via unified CT. | INV-P8-001 + §15.3a |
| **INV-P6-011**: Warm-Up Window (producer decodes ahead) | **REVOKED** | Producer decode-ahead is no longer timeline-relevant. TimelineController admission window handles frame timing. | INV-P8-003 (Contiguous Coverage) + §5.7 |
| **INV-P6-012**: Clock Epoch Must Account for Seek Offset | **REVOKED** | Producer no longer sets epoch. TimelineController establishes epoch at session start; segment mapping handles seek offset. | INV-P8-005 (Epoch Immutability) + §6.1 |
| **INV-P6-004**: Frame Admission Gate (discard before seek target) | **SCOPED** | Valid in **legacy/shadow mode only** for pre-seek filtering. Live mode uses TimelineController admission. | Producer legacy/shadow path + INV-P8-001 |
| **INV-P6-013**: Audio Frame Processing Rate Limit | **SCOPED** | Valid in **legacy mode only** (no TimelineController). Phase 8 admission window inherently limits rate. | §5.4 Admission Rules |

#### 15.3a INV-P8-006 Extended: Producer Time Blindness (Behavioral)

INV-P8-006 states producers MUST NOT read/compute CT values. This section clarifies the **behavioral** implication:

**INV-P8-TIME-BLINDNESS:** When TimelineController is active AND shadow mode is disabled, producers MUST NOT:
- Compare MT against `target_pts_us` for frame suppression
- Drop frames "before start" based on seek target
- Delay emission waiting for alignment
- Gate audio on video PTS
- Compute or log "accuracy" vs target

All timeline-based frame admission decisions move to TimelineController's admission window.

**Observable:** When `timeline_controller_ != nullptr && !shadow_decode_mode_`:
- `DROP_VIDEO_BEFORE_START` counter = 0
- `AUDIO_SKIP` counter = 0
- No log entries for "waiting for video epoch"
- All decoded frames flow to admission window

### 15.4 Superseded Invariants: Phase 7

| Prior Invariant | Status | Reason | Replacement |
|-----------------|--------|--------|-------------|
| **INV-P7-004 (partial)**: Epoch set by first live producer | **REVOKED** | Epoch is set by TimelineController at session start, not by producers. Producer epoch awareness eliminated. | INV-P8-005 + §6.1 |
| **AlignPTS mechanism** (implicit in §7.2-7.4) | **REVOKED** | PTS alignment between producers is eliminated. Segment mapping (BeginSegment) replaces AlignPTS. | §7.2 Transition Procedure |
| **pts_offset_us_ calculation** (producer-side) | **REVOKED** | Producers do not compute PTS offsets. All CT assignment via TimelineController. | INV-P8-006 (Producer Time Blindness) |
| **Shadow mode PTS alignment before switch** | **REVOKED** | Shadow mode frames carry raw MT. CT assigned only after transition via BeginSegment. | §7.2 + Frame `has_ct` flag |

### 15.5 Invariants That Remain Valid

The following Phase 6/7 invariants remain valid and are **strengthened** by Phase 8:

| Invariant | Status | Note |
|-----------|--------|------|
| **INV-P7-001**: PTS Monotonicity | RETAINED | Now enforced by INV-P8-002 (Monotonic Advancement) |
| **INV-P7-002**: Zero-Gap Transitions | RETAINED | Now enforced by INV-P8-003 (Contiguous Coverage) |
| **INV-P7-003**: Audio Continuity | RETAINED | Both streams use same TimelineController |
| **INV-P7-005**: Prebuffer Guarantee | RETAINED | Preview producer fills buffer; TimelineController admits at transition |
| **INV-P7-006**: Deterministic Fallback | RETAINED | Failure modes unchanged |
| **INV-P7-007**: As-Run Accuracy | RETAINED | Actual times still logged |
| **INV-P6-001**: Seek Offset Calculation (Core) | RETAINED | Core still calculates offset; AIR uses it differently |
| **INV-P6-002**: Container Seek to Keyframe | RETAINED | Producer still seeks; result is MT metadata |
| **INV-P6-003**: Single Seek Per Join | RETAINED | Still valid |
| **INV-P6-005**: First Emitted Frame Accuracy | RETAINED | Quality metric unchanged |
| **INV-P6-006**: Audio-Video Sync After Seek | RETAINED | Now enforced by segment mapping |
| **INV-P6-007**: Seek Latency Bound | RETAINED | Performance target unchanged |
| **INV-P6-009**: Backpressure on Buffer Full | RETAINED | Now combined with INV-P8-011 |

### 15.6 Implementation Requirements

1. **Code Audit**: All producer code MUST be audited to remove:
   - Epoch reading or setting
   - PTS offset calculation (`pts_offset_us_`)
   - AlignPTS calls (when TimelineController active)
   - Clock-gated emission logic (when TimelineController active)
   - Audio epoch gating (when TimelineController active)

2. **Conditional Paths**: If legacy mode (no TimelineController) must be supported:
   - Scoped invariants MAY remain in legacy path
   - Legacy path MUST be clearly guarded: `if (!timeline_controller_)`
   - Legacy path MUST NOT execute when TimelineController is present

3. **Frame Validity Marker**: Frames MUST carry `has_ct` flag:
   - `has_ct = false`: Shadow mode, raw MT, NOT timeline-valid
   - `has_ct = true`: Admitted by TimelineController, CT assigned
   - Renderer MUST reject frames with `has_ct = false`

4. **Segment Mapping**: Transition logic MUST use:
   - `BeginSegment(ct_start)`: Set CT_start, MT pending
   - First admitted frame locks MT_start
   - NEVER use pre-computed or "peeked" MT for mapping

### 15.7 Verification Checklist

Before claiming Phase 8 compliance, verify:

- [ ] No producer code reads `epoch` or calls `get_epoch_utc_us()`
- [ ] No producer code computes `pts_offset_us_` (except legacy path)
- [ ] No producer code calls `AlignPTS()` when TimelineController active
- [ ] No producer code gates audio on `first_frame_pts_us_` (except legacy/shadow path)
- [ ] No producer code drops frames based on `effective_seek_target_us_` (except legacy/shadow path)
- [ ] No producer code skips audio "waiting for video epoch" (except legacy/shadow path)
- [ ] Phase 6 gating guarded by: `bool phase6_gating_active = !timeline_controller_ || in_shadow_mode;`
- [ ] TimelineController is the only component calling `set_epoch_utc_us()`
- [ ] TimelineController is the only component writing to `frame.metadata.pts` for CT
- [ ] All frames in active buffer have `has_ct = true`
- [ ] Shadow frames have `has_ct = false`
- [ ] `BeginSegment()` is used for transitions, not `SetSegmentMapping()` with guessed MT
- [ ] Renderer rejects frames with `has_ct = false`

### 15.8 Supersession Summary Table

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     INVARIANT SUPERSESSION SUMMARY                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  REVOKED (must not exist in Phase 8 code paths):                            │
│  ────────────────────────────────────────────────                            │
│  • Producer sets/reads epoch                                                 │
│  • Producer computes pts_offset_us_                                         │
│  • Producer performs clock-gated emission                                    │
│  • AlignPTS between producers                                               │
│  • Shadow mode PTS alignment                                                │
│                                                                              │
│  SCOPED (legacy/shadow mode only - guarded by phase6_gating_active):        │
│  ────────────────────────────────────────────────────────────────────        │
│  • Frame admission gate (discard MT < effective_seek_target_us_)            │
│  • Audio epoch gating (wait for first_frame_pts_us_)                        │
│  • Audio rate limiting (one frame per call)                                 │
│  • pts_offset_us_ application                                               │
│                                                                              │
│  BEHAVIORAL INVARIANT (Phase 8 active + not shadow mode):                   │
│  ──────────────────────────────────────────────────────────                  │
│  INV-P8-TIME-BLINDNESS:                                                     │
│  • Producer MUST NOT drop frames based on MT vs target comparison           │
│  • Producer MUST NOT skip audio waiting for video epoch                     │
│  • Producer MUST emit all decoded frames to admission window                │
│  • TimelineController admission window handles all time decisions           │
│                                                                              │
│  RETAINED (strengthened by Phase 8):                                        │
│  ──────────────────────────────────                                          │
│  • PTS/CT monotonicity                                                       │
│  • Zero-gap transitions                                                      │
│  • Audio continuity                                                          │
│  • Prebuffer guarantee                                                       │
│  • Deterministic fallback                                                    │
│  • As-run accuracy                                                          │
│  • Seek mechanics (container seek, keyframe, accuracy)                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---
