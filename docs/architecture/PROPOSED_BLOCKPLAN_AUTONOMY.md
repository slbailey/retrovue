# Proposed Direction: Block-Level Playout Autonomy

> **Document Type:** Proposed Architectural Direction
> **Status:** Draft — Not Yet Authoritative
> **Author Context:** Derived from incident analysis and broadcast-engineering principles
> **Relationship:** Would simplify Phase 8 (Timeline), Phase 11 (Authority), Phase 12 (Lifecycle)

---

**This document captures a proposed architectural direction. It is not yet authoritative and does not modify existing contracts.**

**This document intentionally favors operational simplicity and determinism over dynamic recovery.**

---

## 1. Motivation

### 1.1 Why Broadcast-Grade Systems Prefer Block-Level Autonomy

Professional broadcast automation (e.g., Harris ADC, Grass Valley iTX, Imagine Communications) operates on a foundational principle: **playout engines are autonomous once armed**. The automation system thinks ahead, builds declarative rundowns, and hands them to the playout engine. The playout engine then executes without further instruction until the block is complete.

This is not accidental. It emerges from two constraints:

1. **Real-time systems cannot tolerate coordination latency.** A playout engine emitting 29.97 frames per second cannot wait for RPC round-trips to decide what to do next. Any coordination latency introduces jitter, black frames, or audio gaps.

2. **Complexity at boundaries compounds.** The more micro-coordination required at segment boundaries, the more failure modes exist. Professional systems minimize boundary-crossing coordination by batching decisions into larger units (blocks, hours, dayparts).

RetroVue has drifted toward micro-coordination: per-segment legacy preload RPC, per-transition legacy switch RPC, boundary feasibility gating at session start. This maximizes control-plane chatter and creates fragile coupling between Core's scheduling logic and AIR's execution timing.

### 1.2 What Classes of Failures This Eliminates

Recent incidents revealed systematic fragility:

| Failure Mode | Root Cause | Current Mitigation |
|--------------|------------|-------------------|
| **Black screen on viewer join near boundary** | Session creation gated on first boundary feasibility | Phase 12 startup convergence (skip infeasible) |
| **Stuck sessions on transition failure** | Single transition failure blocks all subsequent | Terminal state absorbs session |
| **Race conditions at segment boundaries** | Core and AIR disagreeing on "now" | Deadline-authoritative switching |
| **Complexity explosion in scheduler** | Per-segment legacy preload RPC/legacy switch RPC choreography | Boundary state machine |

These mitigations work, but they address symptoms. The root cause is architectural: **the system asks too many questions during execution**.

Block-level autonomy eliminates these failures by design:

- **No startup gating:** Session creation is always immediate; AIR begins playback from the current position within the active block.
- **No per-segment coordination:** AIR executes all transitions within a block autonomously.
- **No boundary races:** Block boundaries are absolute wall-clock fences; AIR enforces them locally.
- **No choreography failures:** Transitions within a block are pre-planned; nothing to fail at runtime.

---

## 2. Authority Model

### 2.1 What Core Owns

Core retains authority over:

| Concern | Authority Type | Notes |
|---------|---------------|-------|
| **Schedule** | Absolute | What content plays when, across all channels |
| **Block composition** | Absolute | Primary content, ad breaks, commercials, filler |
| **Block timing** | Absolute | start_utc and end_utc for each block |
| **Session lifecycle** | Absolute | When to start AIR, when to tear down |
| **Lookahead delivery** | Absolute | Ensuring AIR always has current + next block |
| **Epoch establishment** | Once per session | Wall-clock anchor for the session |

Core's role is **think ahead**: compute future blocks, ensure AIR has what it needs, manage viewer sessions.

### 2.2 What AIR Owns

AIR retains authority over:

| Concern | Authority Type | Notes |
|---------|---------------|-------|
| **Content Time (CT)** | Exclusive | Monotonic timeline; single writer |
| **Monotonic clock** | Exclusive | Real-time pacing; frame-accurate execution |
| **Transition execution** | Exclusive | Within-block cuts happen on AIR's clock |
| **Block fence enforcement** | Exclusive | block_end_utc is a hard deadline |
| **Buffer management** | Exclusive | Preview/live slots, backpressure |
| **Output** | Exclusive | TS emission, encoding, muxing |

AIR's role is **act deterministically**: execute the received plan without asking questions.

### 2.3 What Is Explicitly NOT Shared

| Concern | Forbidden Sharing |
|---------|------------------|
| **Current time** | AIR does not poll Core for wall clock after epoch |
| **Transition timing** | Core does not issue per-transition commands within a block |
| **Boundary decisions** | AIR does not ask Core if it should transition |
| **Recovery decisions** | AIR does not attempt mid-block recovery; it executes or fails |
| **Content availability** | AIR does not report per-segment status; block succeeds or fails |

The goal is **minimal coupling**: Core sends declarative intent; AIR executes it. No round-trips during execution.

---

## 3. BlockPlan Definition

### 3.1 Structure

A BlockPlan is a self-contained execution unit representing a contiguous span of scheduled content:

```
BlockPlan {
    block_id: UUID
    channel_id: UUID

    // Timing (absolute wall clock)
    start_utc: Timestamp      // When this block begins (inclusive)
    end_utc: Timestamp        // When this block ends (exclusive); hard fence

    // Epoch reference (for first block of session)
    epoch_utc: Timestamp?     // Set only on first block; establishes session epoch

    // Content sequence
    segments: [Segment]       // Ordered list of content within the block

    // Metadata
    block_type: BlockType     // PROGRAM, COMMERCIAL_BREAK, INTERSTITIAL, etc.
}

Segment {
    segment_id: UUID
    asset_uri: String         // File path or asset reference
    start_offset_ms: u64      // Where to begin playback within the asset
    duration_ms: u64          // How long this segment runs
    segment_type: SegmentType // PRIMARY, COMMERCIAL, FILLER, etc.
}
```

### 3.2 Timing Semantics

| Property | Semantics |
|----------|-----------|
| **start_utc** | Absolute wall-clock instant when block playback begins. For the first block of a session, this may be in the past (mid-block join). |
| **end_utc** | Absolute wall-clock instant when block playback must end. This is a **hard fence**: AIR transitions to the next block at this instant regardless of content state. |
| **duration** | `end_utc - start_utc`. Always positive. Typical values: 30 minutes (half-hour block), 60 minutes (hour block). |
| **segment durations** | Sum of segment durations must equal block duration. Core is responsible for this invariant. |

### 3.3 How Ad Breaks Fit Naturally

Ad breaks are not special-cased; they are segments within a block:

```
BlockPlan {
    block_type: PROGRAM
    start_utc: "2025-03-15T21:00:00Z"
    end_utc: "2025-03-15T21:30:00Z"

    segments: [
        { asset: "show_s01e01_part1.ts", duration: 720000 }   // 12 min
        { asset: "commercial_1.ts", duration: 30000 }         // 30 sec
        { asset: "commercial_2.ts", duration: 30000 }         // 30 sec
        { asset: "commercial_3.ts", duration: 30000 }         // 30 sec
        { asset: "promo_1.ts", duration: 15000 }              // 15 sec
        { asset: "show_s01e01_part2.ts", duration: 720000 }   // 12 min
        { asset: "commercial_4.ts", duration: 30000 }         // 30 sec
        { asset: "commercial_5.ts", duration: 30000 }         // 30 sec
        { asset: "show_s01e01_part3.ts", duration: 255000 }   // 4:15
    ]
}
```

AIR executes segment transitions at the appropriate CT without Core involvement. The block is a single unit of work.

---

## 4. Startup & Join Semantics

### 4.1 Example: Viewer Joins at 20:59:52 for a 21:00 Boundary

Current time: 20:59:52 UTC
Block A: 20:30:00 - 21:00:00 (currently active)
Block B: 21:00:00 - 21:30:00 (next block)

**Current model complexity:**
1. Core checks if first boundary is feasible (8 seconds until 21:00)
2. MIN_PREFEED_LEAD_TIME may not be satisfied
3. Session creation may be gated or boundary skipped
4. Startup convergence state machine engages

**BlockPlan model:**
1. Core sends Block A (with start_offset computed for 20:59:52)
2. Core sends Block B (lookahead)
3. AIR begins playback immediately at the correct offset within Block A
4. AIR knows Block A ends at 21:00:00; it will transition to Block B at that instant
5. No gating, no convergence, no boundary feasibility check

### 4.2 Why Playback Starts Immediately

The viewer is entitled to content the moment they tune in. The schedule says content is airing at 20:59:52; therefore, content must be delivered. Whether the next block boundary is 8 seconds away or 8 minutes away is irrelevant to the viewer's immediate experience.

Block-level autonomy makes this natural: AIR has the current block, knows when it ends, and has the next block ready. There is nothing to evaluate, nothing to gate, nothing to fail.

### 4.3 Why the Next Block Must Already Be Present

AIR cannot ask Core for the next block at 21:00:00. Real-time execution cannot tolerate RPC latency at the transition instant. The next block must already be in AIR's possession before the fence is reached.

This is the **lookahead requirement**: AIR must always have at least current + next block. Core's responsibility is to ensure this invariant; AIR's responsibility is to execute.

---

## 5. Lookahead Strategy

### 5.1 Why Two Blocks (Current + Next) Is the Minimum Safe Model

| Scenario | With Lookahead | Without Lookahead |
|----------|---------------|-------------------|
| Normal transition | AIR cuts to next block at fence | AIR must wait for RPC; potential black |
| Network hiccup | AIR has next block; unaffected | Transition fails; black screen |
| Core restart | AIR continues with cached blocks | Session dies |
| Viewer joins near boundary | Next block already present | Startup complexity |

Two blocks is the minimum because:
- One block is insufficient: no next block at transition time
- Two blocks covers all normal operations
- Three or more blocks adds safety margin but increases memory and staleness risk

### 5.2 Professional Broadcast Parallel

Professional automation systems typically maintain a "playlist window" of upcoming events. Harris ADC, for example, loads the next 2-4 events into the playout engine's cache. This is not optimization; it is a correctness requirement.

The principle: **the playout engine must be able to execute through a control-plane outage**. If the automation system goes down, the playout engine continues executing its cached playlist until it runs out.

RetroVue should adopt the same principle: AIR continues executing through Core hiccups because it has sufficient lookahead.

### 5.3 Lookahead Delivery Contract

Core's responsibility:

1. On session start, send current block and next block
2. After each block transition, send the next-next block (maintaining two-block lookahead)
3. If Core cannot deliver a block before the previous block's end_utc minus MIN_LOOKAHEAD_MARGIN, log a warning
4. If AIR reaches a fence without a next block, the session fails (terminal)

AIR's responsibility:

1. Accept and queue incoming BlockPlans
2. Transition to the next block at the current block's end_utc
3. Report when a block is consumed (optional: enables Core metrics)

---

## 6. Epoch / Clock Semantics

### 6.1 The Bathroom-Scale Metaphor

A bathroom scale is calibrated once: you step on, it zeros, then it measures. You don't re-zero mid-measurement. If you re-zeroed every second, the measurement would be meaningless.

Session epoch works the same way:

1. **Calibration (epoch establishment):** At session start, Core tells AIR "wall clock is now X; this is your epoch"
2. **Measurement (execution):** AIR advances CT using its local monotonic clock, never asking "what time is it?"
3. **No re-calibration:** Epoch is immutable for the session's lifetime

### 6.2 Why Epoch Is Never Refreshed

Refreshing epoch mid-session would cause:

- **Discontinuity:** CT would jump (forward or backward)
- **Desync:** Viewers would see duplicate or missing content
- **Indeterminism:** Same inputs would produce different outputs depending on when epoch was refreshed

Professional playout engines use GPS-locked time references precisely to avoid mid-execution clock adjustments. RetroVue approximates this by establishing epoch once and never touching it.

### 6.3 Why Drift Results in Restart, Not Correction

If AIR's monotonic clock drifts from wall clock beyond tolerance:

| Approach | Consequence |
|----------|-------------|
| **Correct drift** | CT discontinuity; viewers see glitch; violates monotonic invariant |
| **Ignore drift** | Block fences occur at wrong wall-clock times; schedule misalignment |
| **Restart session** | Clean slate; new epoch; correct alignment; brief viewer interruption |

Broadcast-grade correctness requires the third option. A brief viewer interruption (reconnect) is preferable to degraded, drifting playback.

**Drift tolerance:** Exact threshold TBD, but likely 100-500ms. Beyond this, the session is terminated and must be restarted.

---

## 7. Comparison to Current Model

### 7.1 What Complexity Disappears

| Current Model | BlockPlan Model | Complexity Removed |
|--------------|-----------------|-------------------|
| Per-segment legacy preload RPC RPC | Block contains all segments | legacy preload RPC choreography |
| Per-transition legacy switch RPC RPC | AIR executes autonomously | legacy switch RPC choreography |
| Boundary state machine (PLANNED → PRELOAD_ISSUED → SWITCH_SCHEDULED → SWITCH_ISSUED → LIVE) | Block fence (binary: before/after) | 6-state machine |
| Startup convergence (skip infeasible boundaries) | No boundaries to evaluate at startup | Convergence logic |
| Teardown deferral (transient state protection) | Simpler: executing block or not | Transient state tracking |
| Shadow/preview coordination | Single-producer per segment within block | Dual-buffer coordination |
| Write barrier timing | Block-level buffering | Per-segment barriers |

### 7.2 What Responsibilities Move

| From | To | Responsibility |
|------|-----|----------------|
| Core | AIR | Within-block transition timing |
| Core | AIR | Segment-level error handling |
| AIR | Core | Block composition (ad break placement) |
| Shared | Core | Block boundary calculation |
| Shared | AIR | Block fence enforcement |

The boundary between Core and AIR becomes cleaner: Core thinks in blocks; AIR executes blocks.

---

## 8. Explicit Non-Goals

### 8.1 No Mid-Session Recovery

If a block fails (asset missing, decode error, etc.), the session fails. AIR does not:
- Skip to the next segment
- Substitute filler
- Retry the failed segment
- Ask Core for a replacement

Rationale: Recovery logic is complex, error-prone, and rarely correct. A failed session should be restarted cleanly.

### 8.2 No Dynamic Drift Correction

AIR does not:
- Poll NTP
- Adjust CT based on wall-clock checks
- Speed up or slow down playback to compensate for drift

Rationale: These techniques introduce non-determinism and potential A/V sync issues. Drift beyond tolerance is a restart condition.

### 8.3 No Per-Segment RPC Choreography

Core does not:
- Send legacy preload RPC for each segment
- Send legacy switch RPC for each segment
- Track segment-level state within a block
- Receive segment-level acknowledgments

Rationale: This is the entire point of block-level autonomy.

### 8.4 No Mid-Block Schedule Changes

Once a BlockPlan is delivered to AIR, it is immutable. Core cannot:
- Modify segment order within a delivered block
- Change segment durations
- Insert or remove commercials
- Extend or shorten the block

Rationale: Mutating a live block would require complex reconciliation logic. Schedule changes take effect at the next block boundary.

---

## 9. Relationship to Existing Phases

### 9.1 How This Simplifies Phase 8 Timeline Mechanics

Phase 8 defines CT, epoch, segment lifecycle, write barriers, and switch semantics. Block-level autonomy preserves these concepts but simplifies their application:

| Phase 8 Concept | Current Implementation | BlockPlan Implementation |
|----------------|----------------------|-------------------------|
| CT single writer | TimelineController | TimelineController (unchanged) |
| Epoch immutability | INV-P8-005 | INV-P8-005 (unchanged) |
| Segment boundaries | Core-computed, per-segment | Block-internal, AIR-computed |
| Write barriers | Per-segment coordination | Per-segment within block (AIR-internal) |
| legacy preload RPC/legacy switch RPC | Core → AIR per segment | Block-internal (no RPC) |

Phase 8 invariants remain valid; their enforcement scope narrows to within-block execution.

### 9.2 How This Reduces Phase 12 Lifecycle Fragility

Phase 12 defines session lifecycle, teardown semantics, and startup convergence. Block-level autonomy simplifies these:

| Phase 12 Concept | Current Complexity | BlockPlan Simplification |
|-----------------|-------------------|-------------------------|
| Startup convergence | Skip infeasible boundaries | No boundaries to evaluate |
| Teardown deferral | Transient state protection | Simpler state: in-block or between-blocks |
| Boundary state machine | 6 states | 2 states: executing, waiting |
| FAILED_TERMINAL | Absorbing state | Block failure = session failure |

### 9.3 Why This Is Evolution, Not Rejection

This direction does not reject Phase 8 or Phase 12. It:
- Preserves their invariants
- Simplifies their implementation
- Reduces their failure modes
- Extends their principles to block-level granularity

The phases established essential semantics (CT authority, epoch immutability, teardown safety). Block-level autonomy is the natural next step: applying those semantics at a coarser granularity where they become simpler to enforce.

---

## 10. Open Questions

### 10.1 Lookahead Window Sizing

- Is two blocks sufficient for all network conditions?
- Should lookahead be time-based (e.g., 60 minutes ahead) rather than count-based?
- How does block size (15 min vs 30 min vs 60 min) affect lookahead requirements?

### 10.2 Block Granularity

- What is the right block size? Program-aligned (variable) or fixed (30 min)?
- How do short interstitials (station IDs, bumpers) fit into blocks?
- Should commercial breaks be separate blocks or segments within program blocks?

### 10.3 Rollout Strategy

- Can this coexist with the current legacy preload RPC/legacy switch RPC model during migration?
- Should this be opt-in per channel or system-wide?
- What is the testing strategy for block-level execution?

### 10.4 Backward Compatibility

- How do existing Core scheduling interfaces map to BlockPlans?
- Can the gRPC protocol evolve incrementally or does it require a new API version?
- What happens to in-flight sessions during upgrade?

### 10.5 Error Reporting

- How does AIR report block-level success/failure?
- What telemetry is needed for block execution monitoring?
- How does observability change when segment-level events are AIR-internal?

### 10.6 Content Preparation

- How does block-level delivery affect asset prefetch?
- Should AIR decode-verify all segments before accepting a block?
- What is the memory impact of holding two full blocks?

---

## 11. Summary

This document proposes an architectural direction: **block-level playout autonomy**.

The core insight is that micro-coordination between Core and AIR during execution creates fragility. Professional broadcast systems avoid this by:
- Thinking ahead (block composition, lookahead)
- Declaring intent (BlockPlans with absolute timing)
- Executing autonomously (playout engine runs without asking questions)

If adopted, this direction would:
- Eliminate startup gating and convergence complexity
- Remove per-segment RPC choreography
- Simplify the boundary state machine
- Align RetroVue more closely with broadcast industry practices

This is a **proposed direction**, not a mandate. It requires further analysis, prototyping, and consensus before implementation.

---

## Document History

| Date | Change |
|------|--------|
| 2026-02-02 | Initial draft capturing architectural direction |
