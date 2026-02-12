# Phase 8 – Timeline, Segment & Switch Semantics

**Document Type:** Architectural Contract  
**Status:** Authoritative (invariants enforced; see CANONICAL_RULE_LEDGER)  
**Laws:** LAW-TIMELINE, LAW-CLOCK, LAW-SWITCHING  
**Prerequisites:** Phase 1 (Prevent Black/Silence) for liveness and content-before-pad  
**Referenced by:** Phase 11 (Broadcast-Grade Timing & Authority Hierarchy), Phase 12 (Live Session Authority & Teardown)

---

## 1. Purpose

### 1.1 Why Phase 8 Exists

Phase 8 defines **timeline semantics** and **clock-driven segment switching** for RetroVue playout. It establishes:

- **Content Time (CT)** as the single, monotonic timeline owned by the TimelineController (AIR).
- **Wall-clock correspondence:** when and how segment boundaries align to real time.
- **Segment lifecycle:** legacy preload RPC (preview buffer fill) and legacy switch RPC (cut at boundary), with write barriers and shadow/preview coordination.
- **Core–AIR boundary:** Core computes *when* boundaries occur and issues legacy preload RPC/legacy switch RPC; AIR executes *at* the declared boundary time.

Phase 8 is the foundation for “schedule advances because time advanced, not EOF.” Later phases (11, 12) refine *who* holds authority over timing and lifecycle; Phase 8 defines *what* timeline and switch semantics are.

### 1.2 What Class of Failures This Prevents

Without Phase 8 discipline, you get:

- **Timeline corruption:** Multiple writers to CT; gaps or regressions; producers gating on wall clock.
- **Switch chaos:** Preview and live buffers undefined; legacy preload RPC while switch armed; no write barrier.
- **Authority ambiguity:** Core and AIR disagree on when a boundary occurs; poll/retry instead of declarative boundary.

Phase 8 eliminates these by: single CT authority, producer time-blindness, mapping-pending-before-preview-fills, write barrier on live before new segment, and switch execution at declared boundary.

---

## 2. Terminology

**Content Time (CT):**  
Monotonic timeline maintained by TimelineController (AIR). Single source of truth for “where we are” in the playout. Never reset mid-session. Producers do not read or compute CT for gating.

**Wall Clock (W) / Epoch:**  
Real time. LAW-CLOCK: MasterClock is the only source of “now”; epoch is set at session start and unchanged until session end. Steady-state correspondence: W ≈ epoch + CT.

**Segment:**  
A contiguous span of content (one asset or filler) with a start and end. Boundaries are the instants between segments.

**Boundary:**  
Scheduled instant (wall time) at which playout switches from current (live) segment to the next. Core computes boundaries from schedule; AIR executes the switch at the declared time.

**legacy preload RPC:**  
Core→AIR command to load the successor segment into the preview buffer. Must complete with sufficient lead time (MIN_PREFEED_LEAD_TIME) before the boundary so the switch can execute on time.

**legacy switch RPC:**  
Core→AIR command to cut from current live segment to the preview segment at the boundary. Issued at or just before the boundary; AIR executes at the declared boundary time (deadline-authoritative).

**Shadow / Preview:**  
The buffer and decode state for the *next* segment while the current segment is still live. INV-P8-SHADOW-PACE: shadow caches first frame, waits in place (no run-ahead decode). INV-P8-SWITCH-001: mapping pending *before* preview fills; write barrier on live before new segment.

**Write Barrier:**  
Mechanism that prevents writes to the output after the live segment is committed to end at the boundary. INV-P8-007: post-barrier writes = 0. INV-P8-WRITE-BARRIER-DEFERRED: write barrier on live waits until preview shadow ready.

**Segment Commit:**  
The moment the first frame of the successor is admitted; that segment “commits” and owns CT; the old segment receives RequestStop. INV-P8-SEGMENT-COMMIT, INV-P8-SEGMENT-COMMIT-EDGE.

**Switch Armed:**  
State when legacy switch RPC has been issued and the cut is pending. INV-P8-SWITCH-ARMED: no legacy preload RPC while switch armed; FATAL if reset reached while armed.

---

## 3. Authority Model

| Concern              | Owner        | Rationale |
|----------------------|--------------|------------|
| CT assignment        | TimelineController (AIR) | Single writer; monotonic; no gaps (INV-P8-001, INV-P8-002, INV-P8-003). |
| Epoch                | AIR          | Set at session start; immutable until session end (LAW-CLOCK §2, INV-P8-005). |
| Segment boundaries   | Core         | Core computes from schedule; passes boundary time to AIR (target_boundary_time_ms). |
| legacy preload RPC / legacy switch RPC | Core | Core issues; AIR executes at declared time (LAW-SWITCHING, INV-BOUNDARY-DECLARED-001). |
| Switch execution     | AIR          | AIR executes cut at boundary; clock authority (LAW-AUTHORITY-HIERARCHY refines this in Phase 11). |
| Producer progress    | AIR (FileProducer, etc.) | Producers are time-blind (INV-P8-006); they do not read CT to gate; frame-indexed execution. |

Producers do not read or compute CT for drop/delay/gate decisions; they are “time-blind after lock.” TimelineController is the only assigner of CT (LAW-TIMELINE, INV-P8-001, INV-P8-006).

---

## 4. Core–AIR Boundary (Phase 8)

- **Core** holds the schedule and clock. It computes the current segment end time (boundary), requests the next segment from the schedule service, and at the right times:
  - Sends **legacy preload RPC** (asset, start_frame, frame_count, etc.) so AIR can fill the preview buffer.
  - Sends **legacy switch RPC** with **target_boundary_time_utc** (or target_boundary_time_ms) so AIR executes the cut at that instant.
- **AIR** maintains CT, preview/live buffers, and write barriers. It executes the switch at the declared boundary time (deadline-authoritative). It does not decide *when* the boundary is; it executes *at* the time Core declares.

**The scheduled segment end time is authoritative for timeline advancement, regardless of content availability.** Schedule, CT, boundary evaluation, and (when it occurs) decoder EOF are all aligned to that authority; content deficit before scheduled end is handled by fill (see §5.4).

Phase 11 and 12 add: explicit boundary state machine in Core (Phase 11F), teardown deferral until stable state (Phase 12), and viewer-count advisory during transient states (Phase 12). Phase 8 does not define those; it defines the timeline and switch semantics that those phases build on.

---

## 5. Invariants Summary (Phase 8)

Canonical definitions and enforcement status are in **CANONICAL_RULE_LEDGER**. This section is a concise summary for readers of PHASE8.

### 5.1 Timeline Semantics (LAW-TIMELINE, LAW-CLOCK)

| Rule ID | One-Line Definition |
|---------|----------------------|
| INV-P8-001 | Single Timeline Writer — only TimelineController assigns CT |
| INV-P8-002 | Monotonic Advancement — CT strictly increasing |
| INV-P8-003 | Contiguous Coverage — no CT gaps |
| INV-P8-004 | Wall-Clock Correspondence — W = epoch + CT steady-state |
| INV-P8-005 | Epoch Immutability — epoch unchanged until session end |
| INV-P8-006 | Producer Time Blindness — producers do not read/compute CT; must not drop/delay/gate based on MT vs target |
| INV-P8-008 | Frame Provenance — one producer, one MT, one CT per frame |
| INV-P8-009 | Atomic Buffer Authority — one active buffer, instant switch |
| INV-P8-010 | No Cross-Producer Dependency — new CT from TC state only |
| INV-P8-011 | Backpressure Isolation — consumer slowness does not slow CT |
| INV-P8-012 | Deterministic Replay — same inputs → same CT sequence |
| INV-P8-OUTPUT-001 | Deterministic Output Liveness — explicit flush, bounded delivery. **Output liveness is defined as continuous TS emission at real-time cadence, independent of content availability.** Pad emission must preserve TS cadence so mux/HTTP never stall. |
| INV-P8-SWITCH-002 | CT and MT describe same instant at segment start; first frame locks both |
| INV-P8-AUDIO-CT-001 | Audio PTS derived from CT, init from first video frame |

### 5.2 Coordination (Write Barriers, Switch Orchestration)

| Rule ID | One-Line Definition |
|---------|----------------------|
| INV-P8-007 | Write Barrier Finality — post-barrier writes = 0 |
| INV-P8-SWITCH-001 | Mapping pending BEFORE preview fills; write barrier on live before new segment |
| INV-P8-SHADOW-PACE | Shadow caches first frame, waits in place; no run-ahead decode |
| INV-P8-AUDIO-GATE | Audio gated only while shadow (and while mapping pending) |
| INV-P8-SEGMENT-COMMIT | First frame admitted → segment commits, owns CT; old segment RequestStop |
| INV-P8-SEGMENT-COMMIT-EDGE | Generation counter per commit for multi-switch edge detection |
| INV-P8-SWITCH-ARMED | No legacy preload RPC while switch armed; FATAL if reset reached while armed |
| INV-P8-WRITE-BARRIER-DEFERRED | Write barrier on live waits until preview shadow ready |
| INV-P8-EOF-SWITCH | Live EOF → switch completes immediately (no buffer depth wait) |
| INV-P8-PREVIEW-EOF | Preview EOF with frames → complete with lower thresholds |
| INV-P8-SHADOW-FLUSH | On leaving shadow: flush cached first frame to buffer immediately |
| INV-P8-ZERO-FRAME-READY | When frame_count=0, signal shadow_decode_ready immediately |
| INV-P8-ZERO-FRAME-BOOTSTRAP | When no_content_segment=true, bypass CONTENT-BEFORE-PAD gate |
| INV-P8-AV-SYNC | Audio gated until video locks mapping (no audio ahead of video at switch) |
| INV-P8-AUDIO-PRIME-001 | No header until first audio; no video encode before header written |

### 5.3 Switch Timing (Core)

| Rule ID | One-Line Definition |
|---------|----------------------|
| INV-P8-SWITCH-TIMING | Core: switch at boundary; **MUST complete within one frame of boundary**; violation log if >1 frame late |

### 5.4 Content Deficit Semantics (EOF vs Boundary)

Phase 8 does **not** assume that decoder EOF coincides with segment end or that frame_count always matches actual content length. When live decoder EOF occurs before the scheduled segment end, the following invariants apply.

**Timeline Continuity Rule:** CT must advance at real-time cadence for the full scheduled duration of a segment, regardless of content availability. The schedule defines segment duration; content availability does not shorten it.

| Rule ID | One-Line Definition |
|---------|----------------------|
| **INV-P8-SEGMENT-EOF-DISTINCT-001** | Segment EOF (decoder exhaustion) is distinct from segment end (scheduled boundary). EOF is an event within the segment; boundary is the scheduled instant at which the switch occurs. Timeline advancement and boundary evaluation are driven by scheduled segment end time, not by EOF. |
| **INV-P8-CONTENT-DEFICIT-FILL-001** | If live decoder reaches EOF before the scheduled segment end time, the gap (content deficit) MUST be filled using a deterministic fill strategy at real-time cadence until the boundary; pad (black/silence) is the guaranteed fallback. Output liveness and TS cadence are preserved; the mux never stalls. |
| **INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001** | frame_count (and segment duration) in the playout plan are planning authority from Core. AIR receives this authority and enforces runtime adaptation against it. If actual content is shorter than planned, INV-P8-CONTENT-DEFICIT-FILL-001 applies; if longer, segment end time still governs when the switch occurs (schedule is authoritative). |

These invariants close the semantic loop between schedule, CT, EOF, and boundary evaluation: schedule defines *when* the boundary is; EOF does not. Content deficit between EOF and boundary is filled; boundary remains the single authority for the switch. Phase 8 does not attempt to infer or repair incorrect schedule metadata; it preserves timeline integrity in the presence of imperfect content.

Broadcast-grade timing invariants (INV-BOUNDARY-TOLERANCE-001, INV-BOUNDARY-DECLARED-001, INV-SWITCH-DEADLINE-AUTHORITATIVE-001, etc.) were added in the Phase 11 audit; they operationalize LAW-SWITCHING and boundary declaration. See CANONICAL_RULE_LEDGER and PHASE11.

---

## 6. Relationship to Later Phases

- **Phase 11 (Broadcast-Grade Timing & Authority Hierarchy):**  
  Establishes LAW-AUTHORITY-HIERARCHY (“clock authority supersedes frame completion”). Refines *when* Core issues legacy preload RPC/legacy switch RPC (deadline-scheduled, not cadence-detected), adds boundary lifecycle state machine in Core (Phase 11F), and adds declarative target_boundary_time in protocol. Phase 8 remains the semantics of CT, write barriers, and switch coordination; Phase 11 adds authority and lifecycle rules.

- **Phase 12 (Live Session Authority & Teardown):**  
  Defines *who* may tear down a channel and when (teardown deferred until boundary state stable). Viewer count is advisory during transient states. Phase 8’s “playout starts with viewers, stops when zero viewers” is preserved; Phase 12 adds the rule that teardown must not occur mid-switch (transient state).

Phase 8 does not define boundary state enums, teardown deferral, or startup convergence; those are Phase 11F and Phase 12. Code and docs that say “Phase 8” in the context of timeline, segment, switch, legacy preload RPC, legacy switch RPC, or CT/epoch refer to this contract.

---

## 7. Document References

| Document | Relationship |
|----------|--------------|
| **CANONICAL_RULE_LEDGER.md** | Authoritative list of all INV-P8-* and LAW-* rules; enforcement and test status |
| **PHASE11.md** | Authority hierarchy, boundary lifecycle, prefeed contract, deadline enforcement |
| **PHASE12.md** | Live session authority, teardown semantics, viewer-count advisory |
| **pkg/air/docs/contracts/semantics/** | AIR-side Phase 8 detail (TimelineController, PlayoutEngine, FileProducer, etc.) |
