# ScheduleManager Phase 7 Contract: Seamless Segment Transitions

**Status:** Draft
**Version:** 0.1.0
**Phase:** 7
**Depends On:** Phase 6 (Mid-Segment Join), OutputSwitchingContract (AIR)

---

## 1. Overview

Phase 7 guarantees that segment transitions appear seamless to viewers. When one segment ends and the next begins, the transition must be imperceptible—no pauses, no glitches, no discontinuities. The channel behaves as a single continuous stream regardless of how many segment boundaries occur internally.

This contract defines the observable behavior and invariants that ensure seamless transitions. It does not prescribe implementation mechanisms beyond what is necessary for testability.

---

## 2. Illusion Guarantee

**From the viewer's perspective, the channel appears to have been playing continuously forever.**

A viewer tuning in at any moment—including during a segment boundary—must not be able to perceive:
- Where one segment ends and another begins
- That multiple source files are involved
- Any interruption, stutter, or discontinuity in playback

The only visible indication of segment change is the content itself (e.g., credits ending, new program beginning).

---

## 3. Scope

### In Scope
- Segment-to-segment transitions during live playout
- PTS continuity across segment boundaries
- Audio/video synchronization preservation
- Prebuffering requirements for the next segment
- Failure modes and fallback behavior at boundaries
- As-run logging of actual transition times

### Out of Scope (Non-Goals)
- DVR functionality
- Viewer-initiated rewind or fast-forward
- Seeking within or across segments
- Trickplay modes
- Pause/resume functionality
- Multi-channel coordination

---

## 4. Terminology

| Term | Definition |
|------|------------|
| **Segment** | A contiguous unit of scheduled content with defined start time, duration, and source asset. |
| **Segment Boundary** | The instant at which the last frame of segment N is immediately followed by the first frame of segment N+1 in the output stream. |
| **Scheduled Boundary Time** | The wall-clock time at which a segment is scheduled to end and the next to begin. |
| **Actual Boundary Time** | The wall-clock time at which the transition observably occurs in the output stream. |
| **Channel Epoch** | The reference point (established at channel start) from which all channel PTS values are derived. |
| **Hot-Switch** | The mechanism by which output redirects from one frame source to another without interruption (see OutputSwitchingContract). |
| **Prebuffer Window** | The interval before a scheduled boundary during which the next segment must achieve readiness. |
| **Readiness** | The state where a segment's frame source is capable of emitting frames immediately upon handoff. |
| **Boundary Drift** | The difference between scheduled boundary time and actual boundary time. |

---

## 5. Invariants

### INV-P7-001: PTS Monotonicity Across Boundaries

**Statement:** Channel PTS must be strictly monotonically increasing across all segment boundaries. No PTS reset, wrap, or backward jump may occur during channel lifetime.

**Rationale:** Viewers and downstream systems rely on continuous PTS for synchronization. Any discontinuity causes visible glitches or player errors.

**Observable:** For any two consecutive frames F_n and F_{n+1} in the output stream (regardless of source segment): `PTS(F_{n+1}) > PTS(F_n)`.

---

### INV-P7-002: Zero-Gap Transitions

**Statement:** The time delta between the last frame of segment N and the first frame of segment N+1 must equal the nominal frame period (1/fps), within one frame period of tolerance. No additional gap may be introduced at segment boundaries.

**Rationale:** Any gap larger than one frame period is perceptible as a stutter or pause.

**Observable:** If segment N's last frame has PTS = T and the frame period is P, then segment N+1's first frame must have PTS = T + P (within timing tolerance).

---

### INV-P7-003: Audio Continuity

**Statement:** Audio sample flow must be continuous across segment boundaries. The audio timeline must not have gaps, overlaps, or sample discontinuities at transition points.

**Rationale:** Audio discontinuities are immediately perceptible as clicks, pops, or silence.

**Observable:** Audio PTS maintains the same monotonicity and gap constraints as video PTS.

---

### INV-P7-004: Epoch Stability

**Statement:** Channel epoch must not be modified, reset, or recalculated at segment boundaries. Epoch changes are permitted only at channel start or channel stop.

**Rationale:** Epoch reset would cause PTS discontinuity, violating INV-P7-001.

**Observable:** The epoch value recorded at channel start remains constant through all segment transitions until channel stop.

---

### INV-P7-005: Prebuffer Guarantee

**Statement:** The next segment must achieve readiness before the current segment's scheduled end time. Readiness must be achieved with sufficient margin to permit seamless hot-switch.

**Rationale:** If the next segment is not ready at boundary time, the output must either stall (violating INV-P7-002) or emit frames from an unprepared source (causing glitches).

**Observable:** At the moment of hot-switch, the next segment's frame source has at least one decoded frame available for immediate emission.

---

### INV-P7-006: Deterministic Fallback

**Statement:** When a segment transition cannot occur as scheduled (missing asset, decode failure, early EOF), the system must exhibit deterministic, documented behavior rather than undefined or random behavior.

**Rationale:** Unpredictable failure modes make debugging impossible and may cause cascading failures.

**Observable:** Each failure mode maps to exactly one defined fallback behavior.

---

### INV-P7-007: As-Run Accuracy

**Statement:** The as-run log must record the actual boundary times at which transitions occurred, not the scheduled times.

**Rationale:** As-run logs are authoritative for compliance, billing, and debugging. They must reflect reality.

**Observable:** `as_run.actual_start_time` matches the wall-clock time of the first frame emitted from that segment.

---

## 6. Segment Boundary Semantics

### 6.1 What Constitutes a Segment Boundary

A segment boundary exists when:
1. The schedule defines segment N ending at time T and segment N+1 starting at time T
2. The output stream transitions from emitting segment N frames to emitting segment N+1 frames
3. This transition occurs at approximately time T (within boundary drift tolerance)

### 6.2 Boundary Eligibility

Segment N+1 becomes eligible to emit frames when:
1. Wall-clock time >= scheduled start time of segment N+1
2. Segment N+1 has achieved readiness (decoded frames available)
3. Hot-switch has been executed (output redirected to N+1's frame source)

### 6.3 Handoff Semantics

"Handoff" is the observable transition from segment N to segment N+1:
- **Before handoff:** Output stream contains frames from segment N
- **At handoff:** Output redirects to segment N+1's frame source
- **After handoff:** Output stream contains frames from segment N+1

The handoff is atomic in the sense that no frame can originate from both segments, and no frame can be lost at the boundary.

### 6.4 Boundary Drift Tolerance

Actual boundary time may differ from scheduled boundary time due to:
- Frame quantization (boundaries align to frame periods)
- Decode timing variations
- Clock precision limits

**Maximum Drift:** Actual boundary time must be within one frame period of scheduled boundary time.

---

## 7. Epoch Rules

### 7.1 Epoch Establishment

Channel epoch is established exactly once per channel lifecycle:
- **When:** At channel start, before the first frame is emitted
- **Value:** Derived from wall-clock time at start
- **Scope:** Applies to all frames emitted during this channel session

### 7.2 Epoch Persistence

During channel operation:
- Epoch value is immutable
- Segment transitions do not affect epoch
- All segment PTS values are computed relative to the same epoch
- Epoch persists across any number of segment boundaries

### 7.3 Epoch Reset Conditions

Epoch reset occurs only when:
- Channel stops (explicit stop command or last viewer departure with teardown)
- Channel restarts after stop

Epoch reset does NOT occur when:
- A new segment begins
- A segment fails and fallback activates
- Schedule is updated mid-stream

### 7.4 Architectural Consequence: Channel Clock Authority

**Important:** The combination of INV-P7-001 (PTS monotonicity), INV-P7-002 (zero-gap), INV-P7-004 (epoch stability), and INV-P7-005 (prebuffer guarantee) implicitly establishes that the **channel timeline is authoritative over producer timelines**.

This means:
- Producers do not control when their frames are emitted
- Frame emission timing is governed by channel PTS, not source PTS
- If a segment ends early or late relative to its source timing, the next segment's initial emission must align to channel time
- Implementations MUST NOT reset or recalculate timing at segment boundaries

Violating this principle—for example, by "helpfully" resetting clocks when a new producer starts—will cause PTS discontinuities and violate INV-P7-001.

---

## 8. Prebuffering Requirements

### 8.1 Prebuffer Timing

The system must initiate prebuffering of segment N+1 before segment N ends:
- **Prebuffer Start:** Sufficiently early to achieve readiness before boundary time
- **Readiness Deadline:** Before scheduled boundary time

### 8.2 Readiness Definition

A segment is "ready" when:
1. Its frame source has been initialized with the correct seek offset
2. At least one decoded video frame is available for consumption
3. Corresponding audio frames are available for consumption
4. PTS values have been remapped to channel epoch

### 8.3 Readiness Observable

Readiness can be verified by:
- Querying frame source buffer depth (must be > 0)
- Confirming producer is running and has emitted frames

---

## 9. Failure and Fallback Behavior

### 9.1 Missing Segment

**Condition:** Segment N+1's asset cannot be located or opened.

**Behavior:**
1. Log error with segment details
2. Emit filler/black frames for the scheduled duration of segment N+1
3. Attempt normal transition to segment N+2 at its scheduled time
4. Record in as-run log: segment N+1 marked as "MISSING", filler substituted

**Observable:** Output stream continues without interruption; filler content appears instead of scheduled content.

---

### 9.2 Early EOF

**Condition:** Segment N ends before its scheduled end time (asset shorter than scheduled duration).

**Behavior:**
1. Log warning with actual vs. scheduled duration
2. Immediately transition to segment N+1 if ready
3. If N+1 not ready, emit filler until N+1 achieves readiness or its scheduled start
4. Record in as-run log: segment N actual end time, any filler duration

**Observable:** Output stream continues without interruption; early content may appear or filler bridges the gap.

---

### 9.3 Decode Stall

**Condition:** Segment N+1 fails to achieve readiness by boundary time due to decode issues.

**Behavior:**
1. Continue emitting from segment N if frames remain
2. If segment N exhausted, emit filler/black frames
3. Retry N+1 readiness with backoff
4. If N+1 achieves readiness, transition immediately
5. If N+1 fails permanently, skip to N+2

**Observable:** Output stream continues; possible extended segment N or filler, followed by either late N+1 or skip to N+2.

---

### 9.4 Fallback Priority

When multiple fallback options exist, the system MUST select the first available option in the following priority order:
1. **Extend current segment** (if frames available and within tolerance)
2. **Emit designated filler** (channel-specific filler asset)
3. **Emit black frames with silent audio** (last resort)

Dead air (no output) is never acceptable.

---

## 10. As-Run Guarantees

### 10.1 Required Fields

Each as-run entry must include:
- `segment_id`: Identifier of the scheduled segment
- `scheduled_start_time`: When the segment was scheduled to start
- `scheduled_end_time`: When the segment was scheduled to end
- `actual_start_time`: When the first frame was actually emitted
- `actual_end_time`: When the last frame was actually emitted
- `status`: PLAYED | PARTIAL | MISSING | SKIPPED
- `notes`: Reason for any deviation from schedule

### 10.2 Timing Precision

As-run times must be recorded with millisecond precision or better.

### 10.3 Authoritative Status

The as-run log is authoritative over scheduled intent:
- If as-run says segment played from T1 to T2, that is the ground truth
- Schedule discrepancies are reconciled in favor of as-run

---

## 11. High-Level Data Flow (Conceptual)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CHANNEL TIMELINE                            │
│  ═══════════════════════════════════════════════════════════════►   │
│       │                    │                    │                   │
│   Segment N            Boundary            Segment N+1              │
│   (playing)              Time              (prebuffered)            │
│       │                    │                    │                   │
│       ▼                    ▼                    ▼                   │
│  ┌─────────┐          ┌─────────┐          ┌─────────┐             │
│  │ Frame   │          │ Hot     │          │ Frame   │             │
│  │ Source  │─────────►│ Switch  │─────────►│ Source  │             │
│  │   N     │          │         │          │  N+1    │             │
│  └─────────┘          └─────────┘          └─────────┘             │
│       │                    │                    │                   │
│       └────────────────────┼────────────────────┘                   │
│                            ▼                                        │
│                    ┌──────────────┐                                 │
│                    │ Output Bus   │                                 │
│                    │ (continuous) │                                 │
│                    └──────────────┘                                 │
│                            │                                        │
│                            ▼                                        │
│                    PTS-continuous stream                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 12. Test Specifications

### P7-T001: PTS Continuity Across Single Boundary

**Precondition:** Channel playing segment A, segment B scheduled to follow.

**Action:** Allow natural transition from A to B.

**Verification:**
- Last frame of A has PTS = T
- First frame of B has PTS = T + frame_period
- No PTS gap or reset observed

---

### P7-T002: PTS Continuity Across Multiple Boundaries

**Precondition:** Channel with segments A, B, C scheduled consecutively.

**Action:** Allow transitions A→B→C to occur.

**Verification:**
- PTS is strictly monotonically increasing across all frames
- Each boundary exhibits zero-gap behavior per P7-T001

---

### P7-T003: Audio Continuity at Boundary

**Precondition:** Channel playing segment with audio, next segment also has audio.

**Action:** Allow natural transition.

**Verification:**
- Audio sample count is continuous (no missing samples at boundary)
- No audible click, pop, or silence at transition point
- Audio PTS maintains same monotonicity as video PTS

---

### P7-T004: Epoch Unchanged After Transition

**Precondition:** Channel started, epoch recorded.

**Action:** Allow multiple segment transitions.

**Verification:**
- Epoch value after N transitions equals epoch value at start
- No epoch recalculation or reset observed

---

### P7-T005: Prebuffer Readiness Before Boundary

**Precondition:** Segment A playing, segment B scheduled at time T.

**Action:** Observe system state at time T - epsilon.

**Verification:**
- Segment B's frame source reports ready (buffer depth > 0)
- Segment B's producer is running

---

### P7-T006: Missing Segment Fallback

**Precondition:** Segment B's asset file does not exist.

**Action:** Allow transition from A to (missing) B.

**Verification:**
- No dead air or stall occurs
- Filler content emitted for duration of B
- As-run log shows B as MISSING with filler substituted
- Transition to C occurs at scheduled time

---

### P7-T007: Early EOF Handling

**Precondition:** Segment A's actual duration < scheduled duration.

**Action:** Allow A to play to natural EOF.

**Verification:**
- Transition to B occurs early (at EOF, not scheduled time)
- OR filler bridges gap until B's scheduled start
- No dead air
- As-run log records actual end time of A

---

### P7-T008: Decode Stall Recovery

**Precondition:** Segment B's decode is artificially delayed.

**Action:** Allow transition time to pass with B not ready.

**Verification:**
- Segment A extended OR filler emitted (no dead air)
- B eventually plays when ready
- As-run log reflects actual timing

---

### P7-T009: Boundary Drift Within Tolerance

**Precondition:** Scheduled boundary at time T, frame period P.

**Action:** Measure actual boundary time T'.

**Verification:**
- |T' - T| <= P (within one frame period)

---

### P7-T010: As-Run Accuracy

**Precondition:** Scheduled segment with known start/end times.

**Action:** Play segment through, record as-run.

**Verification:**
- `actual_start_time` matches first frame emission time
- `actual_end_time` matches last frame emission time
- Times recorded with millisecond precision

---

## 13. Edge Cases

### 13.1 Zero-Duration Segment

A segment with zero scheduled duration is skipped entirely:
- No frames emitted
- As-run entry with status SKIPPED
- Immediate transition to next segment

### 13.2 Back-to-Back Identical Assets

Two consecutive segments using the same asset:
- Treated as separate segments with independent readiness
- Boundary exists between them (not coalesced)
- PTS continues monotonically (no seek/reset even if same file)

### 13.3 Very Short Segment

Segment shorter than prebuffer window:
- Prebuffer for segment N+2 may need to start before N+1 begins
- Overlapping prebuffer is permitted
- Each segment's readiness is independent

### 13.4 Schedule Update During Playback

If schedule changes while segment N is playing:
- Current segment N continues to natural end
- New schedule applies to segment N+1 and beyond
- Hot-switch redirects to new N+1 at boundary

### 13.5 Channel Start at Segment Boundary

If viewer tunes in exactly at a segment boundary:
- Viewer sees first frame of new segment (not last frame of old)
- Epoch established relative to new segment start
- Equivalent to clean mid-segment join at position 0

---

## 14. Relationship to Other Phases

| Phase | Relationship |
|-------|--------------|
| **Phase 3** | Provides SchedulePlan with segment ordering and timing |
| **Phase 4** | Validates schedule constraints; Phase 7 assumes valid schedule |
| **Phase 5** | Runtime integration; Phase 7 extends runtime behavior at boundaries |
| **Phase 6** | Mid-segment join establishes epoch and PTS gating; Phase 7 preserves these across boundaries |
| **OutputSwitchingContract (AIR)** | Phase 7 relies on hot-switch mechanism for atomic source redirection |

---

## 15. Contract Compliance

An implementation complies with Phase 7 if:

1. All INV-P7-XXX invariants hold under normal operation
2. All P7-TXXX tests pass
3. Failure modes exhibit documented fallback behavior
4. As-run logs accurately reflect actual playback
5. No viewer-perceptible discontinuity occurs at segment boundaries

---

## Appendix A: Invariant Summary

| ID | Name | Core Guarantee |
|----|------|----------------|
| INV-P7-001 | PTS Monotonicity | PTS never decreases or resets at boundaries |
| INV-P7-002 | Zero-Gap Transitions | Frame timing maintains nominal period at boundaries |
| INV-P7-003 | Audio Continuity | Audio stream uninterrupted at boundaries |
| INV-P7-004 | Epoch Stability | Epoch unchanged by segment transitions |
| INV-P7-005 | Prebuffer Guarantee | Next segment ready before current ends |
| INV-P7-006 | Deterministic Fallback | Failure modes have defined behavior |
| INV-P7-007 | As-Run Accuracy | Actual times recorded, not scheduled |

---

## Appendix B: Failure Mode Summary

| Condition | Fallback | As-Run Status |
|-----------|----------|---------------|
| Missing asset | Filler for scheduled duration | MISSING |
| Early EOF | Early transition or filler bridge | PARTIAL |
| Decode stall | Extend current or filler | Actual times recorded |
| Prebuffer timeout | Filler until ready | Actual times recorded |
