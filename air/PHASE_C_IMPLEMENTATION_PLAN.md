# Phase C Implementation Plan — Segment Seams and Block Transitions

**Status:** planning document (no code).
**Authored:** 2026-04-20.
**Precedes:** implementation of SeamController + multi-segment / multi-block execution in AIR.
**Sits on:** Phase B (re-do) baseline at commit `e3f78679` — AirSession has active_block_ with active_segment_index_, queued_blocks_ deque, segment-aware proto and C++ types, Block carries 1..N Segments.

## Authority

- `[[SeamController]]` — sole runtime authority for segment transition moments, including the six-phase lifecycle (begin → armed → firing → committed → recovered → complete) and the three dispositions (cutover / pad bridge / JIP). C1 and C2 implement this spec.
- `[[Truth - Block Is Handoff Unit and Segment Is Playback Unit]]` — Block is Core's handoff unit; Segment is AIR's execution unit. Every seam fires at a segment boundary.
- `[[Truth - Segment Is AIR's Runtime Unit]]` — segment boundaries are AIR's primary runtime decision points.
- `[[AIR_Lifecycle]]` — seams happen within the OnAir phase; they do not change session lifecycle state.
- `[[AIR_Pipeline]] §INV-AIR-EGRESS-REALTIME-001`, `§INV-AIR-BLOCK-OWNERSHIP-001` — timing discipline within which seams operate.
- `project_retrovue_air_execution_discipline` memory — arm-early / commit-exact; fence is sacred.

## Scope split

**C1 — intra-block segment progression.** A Block with N≥2 segments plays through all of them with frame-accurate seams between adjacent segments. No block boundary involved; active_block_ does not change. Segment source (FileSourceProducer), Normalizer, and decoder swap at each segment seam; encoder stays open (single canonical within a block).

**C2 — inter-block block-to-block seams.** At the fence of the last segment of Block A, AIR transitions to the first segment of Block B (head of queued_blocks_). Mechanically identical to intra-block seam per the truth; the additional action is promoting queued_blocks_.front() to active_block_ (with active_segment_index_ reset to 0). Introduces pull-driven queue refill and the revision/retirement handlers.

**Out of scope for Phase C:** device retune, canonical-changing seams, concurrent priming, admission pacing (fill-thread architecture), editorial mid-asset entry (Segment.asset_start_offset_ms > 0 on happy path). Note: late-successor JIP recovery (lateness_ms > 0) is IN scope — implemented in C1.4c per `INV-SEAM-LATE-SUCCESSOR-JIP-001`, with frame-accurate entry required (backward keyframe seek + forward decode-and-discard).

## New invariants

All additive. None mutate existing invariants.

### C1 invariants

| ID | Statement | Failure authority |
|---|---|---|
| `INV-SEGMENT-FENCE-SACRED-001` | The active Segment MUST stop emitting content at its computed fence tick regardless of source state. If the next Segment is not ready, pad bridges at fence; active Segment does not overrun. | terminate session on violation (indicates broken timing) |
| `INV-SEGMENT-CURSOR-MONOTONIC-001` | `active_segment_index_` MUST only advance or reset (on Block promotion). It MUST NOT regress within the same active Block. | abort process (state corruption) |
| `INV-SEGMENT-SEAM-ARM-COMMIT-001` | Every segment seam MUST pass through `armed → committed_for_tick(F) → executed`. Firing at tick F is deterministic; there is no re-evaluation at F. | diagnostic only |
| `INV-SEGMENT-PRIMING-SINGLE-001` | At most one queued Segment may be in the `priming` state at a time (v1 simplification). Priming begins on the next raw Segment only after the previous priming completes or fails. | diagnostic only |
| `INV-SEGMENT-FENCE-ARITHMETIC-001` | Each Segment's fence tick MUST be computed as: `anchor_monotonic_us + (block.start_utc_ms - session_anchor_utc_ms) * 1000 + sum(segments[0..N].duration_ms) * 1000`. No other formula; no drift compensation. | terminate session |

### C2 invariants

| ID | Statement | Failure authority |
|---|---|---|
| `INV-BLOCK-TRANSITION-IS-SEGMENT-SEAM-001` | Block-to-block transitions MUST be executed by the same seam mechanism as intra-block transitions. The last-segment-of-A → first-segment-of-B transition is a segment seam; block promotion is a side effect. | diagnostic only |
| `INV-BLOCK-PROMOTION-ATOMIC-001` | Block promotion (queued_blocks_.pop_front() becomes active_block_) MUST happen at a single tick boundary, coincident with the corresponding segment seam's `firing` phase. | abort process |
| `INV-BLOCK-FENCE-SACRED-001` | A Block MUST NOT overrun its `end_utc_ms`. end_utc_ms equals the fence tick of its final Segment; this invariant is a consequence of `INV-SEGMENT-FENCE-SACRED-001` applied to the last Segment. | terminate session |
| `INV-QUEUE-EMPTY-PAD-BRIDGE-001` | If active Block's last Segment fence arrives with queued_blocks_ empty, AIR MUST emit pad indefinitely until a Block is supplied or session is stopped. No other fallback content. | continue with fallback |
| `INV-ACTIVE-BLOCK-IMMUTABLE-001` | PutBlockRevision and RetireBlock targeting the active Block MUST be rejected with `ACTIVE_BLOCK_IMMUTABLE`. | diagnostic only |
| `INV-ARMED-BLOCK-FROZEN-001` | PutBlockRevision targeting a Block whose Segment is currently armed MUST be rejected with `BLOCK_ARMED` (v1 simplification). RetireBlock on an armed-parent Block is accepted; disarms the seam. | diagnostic only |
| `INV-PRIMING-BLOCK-FROZEN-001` | PutBlockRevision targeting a Block whose Segment is currently priming MUST be rejected with `BLOCK_PRIMING` (v1 simplification). RetireBlock on a priming-parent Block is accepted; cancels the prime. Only Blocks whose segments are ALL in `raw` state are mutable via revision. | diagnostic only |
| `INV-PULL-SINGLE-OUTSTANDING-001` | At most one pull request (`GetSuccessorOf`) MUST be outstanding from AIR to Core at any time. New pulls MUST NOT be issued while a prior pull is in flight. | diagnostic only |

## State machines

### Per-Segment lifecycle (within a queued or active Block)

```
                          prime_fail
                 ┌──────────────────────┐
                 ↓                      │
  raw ──(start priming)──> priming ──(success)──> primed
                                                    │
                                       (SeamController arms)
                                                    ↓
                                                  armed
                                                    │
                                      (fence tick, commit)
                                                    ↓
                                                  active
                                                    │
                                       (next seam fires)
                                                    ↓
                                                 retired
```

- `raw`: Segment present in a queued Block; no priming work started.
- `priming`: FileSourceProducer::Prepare/Activate in progress; Normalizer constructed; decoder warming. **At most one segment in this state at a time.**
- `primed`: Buffers filled to operational floor. Ready for seam arming.
- `armed`: SeamController has issued a commit directive for a specific fence tick.
- `active`: Segment is being emitted. `active_segment_index_` points at it within `active_block_`.
- `retired`: Segment has been fully played; no longer active. (Records persist for as-run metadata; struct is not dropped until Block is retired.)

### Per-Seam lifecycle (from `SeamController.md`, unchanged)

```
observing → armed → committed_for_tick(F) → firing → committed → recovered → complete
```

- Monotonic progression; no regression.
- One seam in flight at a time per session.
- `committed_for_tick(F)` is reached before tick F; firing is exact at F.

### Session lifecycle (existing, unchanged)

Seams happen within the `OnAir` phase (`AIR_Lifecycle`). They do not transition session state.

## Timing authority

- AIR's injected `AuthoritativeClock` (via `EgressPacer`'s clock reference) provides monotonic time.
- **Session anchor** established at first OnAir tick: `(anchor_monotonic_us, anchor_utc_ms)`. Derived from `BootstrapContentGate`'s kickoff or StartChannel's `seed_block.start_utc_ms`.
- **Segment fence tick** (in monotonic time) computed at arm time:
  ```
  segment_end_utc_ms = block.start_utc_ms + Σ(segments[0..N].duration_ms) for N in [0..index]
  segment_end_monotonic_us = anchor_monotonic_us + (segment_end_utc_ms - anchor_utc_ms) * 1000
  ```
- No drift compensation, no clock re-anchoring at seams (per `INV-SEGMENT-FENCE-ARITHMETIC-001`).
- SeamController reads current encode-thread frame tick to decide when to arm (e.g., arm when `fence_tick - current_tick <= arm_window_frames`).

## Failure handling (by case)

### C1

| Case | Behavior |
|---|---|
| Next Segment prime fails (decoder error, missing asset) | Mark Segment `failed`. If it was armed, disarm. Pad bridge at fence. Keep session alive. Log `segment.prime_failed`. |
| Next Segment not primed at fence | Pad bridge at fence. Priming continues. When primed, resume with that Segment. Its own fence is still honored. |
| Active Segment source EOF before its fence | Per `INV-UNDERFLOW-NORMAL-FALLBACK-001`: freeze + pad until fence. Seam fires normally at fence. |
| Active Segment source fault mid-play | Per `INV-UNDERFLOW-POSTPRIMED-FATAL-001`: session terminates (existing behavior). |
| Fence tick arithmetic overflow / invalid | Terminate session with structured error; this indicates a Core contract violation. |

### C2

| Case | Behavior |
|---|---|
| Active Block last segment ends, queue empty | Pad bridge indefinitely (`INV-QUEUE-EMPTY-PAD-BRIDGE-001`). Pull loop continues asking for successor. Resume when next Block supplied. |
| Retirement of queued Block whose first Segment is armed | Disarm seam; drop Block; pad bridge at fence; pull next successor. |
| Revision of queued Block (no segments armed) | Replace stored record. If any segment was in `priming`, cancel and re-prime from the new record. |
| Revision of Block whose segment is armed | Reject `BLOCK_ARMED`. No state change. |
| Revision/retirement of active Block | Reject `ACTIVE_BLOCK_IMMUTABLE`. No state change. |
| Pull RPC timeout / Core unresponsive | Retry with backoff. Pad bridge at fence if queue empty when it arrives. |
| Block canonical differs from active Block's canonical | v1: reject revision/supply with `CANONICAL_MISMATCH`. (Future: canonical-change is a retune, out of scope.) |

## Metrics (GetSessionStatus extensions + events)

### Cumulative counters (on `GetSessionStatusResponse`)

Already declared in Phase A proto; populated during Phase C:

- `seams_executed_total` — count of all seams (intra-block + inter-block).
- `block_transitions_total` — subset: inter-block transitions.
- `pad_bridge_ms_total` — cumulative time in pad bridge.
- `revisions_accepted_total`, `revisions_rejected_total`.

New additions to proto (C2):

- `segment_transitions_total` — intra-block seams (complement of block_transitions).
- `segments_completed_total` — segments that played to their own fence (for as-run).
- `pad_bridge_events_total` — count of distinct pad bridge intervals (not ms).

### Structured events (via existing lifecycle observer)

From `EXECUTION_QUEUE_AND_SEAMS_DESIGN.md §6`:

**Segment priming / readiness:**
- `segment.prime_started` (block_id, segment_index, mono_us)
- `segment.prime_complete` (block_id, segment_index, mono_us)
- `segment.prime_failed` (block_id, segment_index, reason, mono_us)

**Seam lifecycle:**
- `seam.armed` (block_id, segment_index, target_tick, mono_us)
- `seam.disarmed` (block_id, segment_index, reason, mono_us)
- `seam.committed` (block_id, segment_index, target_tick, mono_us)
- `seam.executed` (from_{block_id, segment_index}, to_{block_id, segment_index}, tick, mono_us, is_block_transition)
- `seam.pad_bridge_started` (predecessor_block_id, predecessor_segment_index, mono_us)
- `seam.pad_bridge_ended` (new_active_block_id, new_active_segment_index, mono_us)

**Queue events (C2):**
- `queue.pull_issued` (predecessor_id, mono_us)
- `queue.pull_supplied` (block_id, segment_count, mono_us)
- `queue.revision_applied` / `queue.revision_rejected` (block_id, reason, mono_us)
- `queue.retirement_applied` / `queue.retirement_rejected` (block_id, reason, mono_us)
- `queue.block_promoted` (from_block_id, to_block_id, mono_us)

## Recommended commit boundaries

Each commit should leave tests green. Each is a single coherent unit with its own test or test extension.

### C0 — Vault, contracts, and invariants (no code)

**Purpose:** formalize the invariants C1 and C2 will enforce BEFORE any code lands. Prevents the drift that Phase A/B hit (code committed ahead of vault authority).

**Placement decision:** new invariants are distributed across existing component docs rather than a new `ExecutionQueue.md`. `PlaybackDirector.md` already owns "current live, next queued, active producer assignment, pending successor-plan truth" — the invariants about queue state, cursor monotonicity, block promotion, and mutability belong there. `SeamController.md` owns segment seam authority. `BlockSupplyDemand.md` owns the Core↔AIR supply protocol.

Deliverables:
- **`PlaybackDirector.md`** — 5 new invariants (segment cursor monotonicity, block promotion atomicity, priming single-worker, block mutability matrix, queue-empty pad bridge).
- **`SeamController.md`** — 2 new invariants (segment fence sacred, fence arithmetic formula).
- **`BlockSupplyDemand.md`** — 1 new invariant (pull single-outstanding); also amend `§Vocabulary Doctrine (AIR vNext) §Mutability rule` to reflect the v1 tightening that priming-state blocks are also frozen to revisions.
- **Memory `project_retrovue_air_vocabulary_discipline.md`** — amend mutability rule to match (priming also frozen).

Exit criteria: every invariant C1/C2 expects to enforce has an authored vault home. No new or modified C++ code. Tests still 66/66 green (no changes).

Single commit. Diff-first discipline per prior vault work. Vault changes are not under git (separate repo); the commit captures the memory amendment only.

### C1 commits

**C1.1 — Segment fence-tick arithmetic**
- `air/include/segment_fence.hpp` + `.cpp` (or inline helpers in air_session): compute fence tick from block anchor + cumulative segment duration.
- Unit tests against `INV-SEGMENT-FENCE-ARITHMETIC-001`: verify fences for synthetic blocks with varying segment durations.
- No integration with encode loop yet.
- **Tests:** ~5 unit tests on fence arithmetic. All green.

**C1.2 — Single-worker priming pipeline**
- Dedicated priming thread (per v1 simplification 4) or async priming task. Owns the `raw → priming → primed` transitions.
- Input: queued_blocks_ → next raw Segment. Output: constructed FileSourceProducer + StandardNormalizer for that Segment, flagged `primed`.
- Emits `segment.prime_*` events.
- **Tests:** priming a single queued Segment; priming a Segment that fails to open (missing asset) emits `segment.prime_failed`; `INV-SEGMENT-PRIMING-SINGLE-001` enforced.

**C1.3 — SeamController (minimal, intra-block scope)**
- New class `air/include/seam_controller.hpp` + `.cpp`. Owns seam lifecycle state (observing / armed / committed / firing / committed / recovered / complete).
- Reads fence ticks from segment_fence helper. Decides arm timing based on a configurable `arm_window_frames` (default ~30 frames = 1s at 30fps).
- Issues `seam.armed`, `seam.committed`, `seam.executed` events.
- Does NOT yet execute the swap — exposes a `ShouldCommitAt(current_tick)` predicate the encode loop consumes.
- **Tests:** SeamController arms when primed + window open; disarms on retraction; fires at exact target_tick; never regresses.

**C1.4a — Encode-loop wiring: happy-path source swap at seam**
- `AirSession::EncodeLoop` polls SeamController each tick. On commit tick, the next Segment is already primed + armed; swap to its source/normalizer and advance `active_segment_index_`.
- **Encoder continuity success criteria** (verifiable in tests):
  - Encoder instance is NOT reopened across the swap. Same `MpegTsEncoder` handles both segments. No PAT/PMT reset, no stream restart on the wire.
  - Channel PTS does NOT regress across the swap. `pacer_.WaitFor(vf->pts_us_relative)` continues to return valid monotonically-increasing targets.
  - Pacer instance is NOT reset across the swap.
  - Downstream MPEG-TS output remains valid throughout (sync byte at every packet boundary; ffprobe parses the stream without error).
- No pad-bridge logic yet — this commit assumes the next Segment is always ready at fence. Late-successor handling is C1.4b.
- **Tests:** two-segment block with both segments primed well ahead of fence. Encode through seam; ffprobe validates; asserts encoder_open_count == 1 (via observer or accessor); asserts no pacer reset event.

**C1.4b — Pad bridge / late successor handling**
- At fence tick, if next Segment is NOT armed (prime incomplete, prime failed, or not yet started): engage pad bridge. Emit `seam.pad_bridge_started`. Continue priming in the background; when Segment becomes primed and armed, transition out of pad to content.
- Uses PadSourceProducer (existing, from earlier slices). Same encoder, no reopen.
- **Encoder continuity** still required across pad→content transition (no PAT/PMT reset, no PTS regression).
- Updates `pad_bridge_ms_total` and `pad_bridge_events_total`.
- **Tests:** two-segment block where segment[1] prime is artificially delayed (test fixture); fence fires, pad bridges, content resumes when ready. Assert: encoder_open_count == 1 throughout; pad_bridge_events_total == 1; continuous TS output through the bridge.

**C1.5 — C1 integration + observability test**
- End-to-end: seed_block with 3 segments → full play → verify `segments_completed_total == 3`, `seams_executed_total == 2`, `block_transitions_total == 0`.
- ffprobe validates the full output is valid MPEG-TS with expected duration.
- Encoder continuity asserted: single `MpegTsEncoder` instance, continuous PTS across both seams, no stream restart visible to ffprobe.
- Verify events fired in order via custom LifecycleObserver.

### C2 commits

**C2.1 — Block fence + promotion arithmetic**
- Extend segment_fence: compute "is this the last segment of active_block_?" and "next block's first segment fence = block.start_utc_ms (modulo anchor)".
- Unit tests: fence continuity at block boundary.

**C2.2 — SeamController extension: block-to-block seams**
- SeamController recognises last-segment seams and flags them as block transitions. Same state machine; `seam.executed.is_block_transition = true`.
- On commit, arranges for `AirSession::PromoteActiveBlock()` to run at firing.
- **Tests:** synthetic two-block fixture. SeamController arms the block seam at the correct target_tick.

**C2.3 — Block promotion in AirSession**
- `AirSession::PromoteActiveBlock()`: atomically pops queued_blocks_.front(), installs as active_block_, resets active_segment_index_ = 0. Emits `queue.block_promoted`. Increments `block_transitions_total`.
- Guarded by queue_mutex_.
- **Tests:** promotion atomicity; queue depth updates; segment cursor resets.

**C2.4 — Demand-driven pull loop (single outstanding request)**
- Dedicated pull thread (per v1 simplification 4). Polls `QueueDepth()`; when below target, issues `GetSuccessorOf(block_id)` via gRPC client to Core.
- **At most one outstanding pull request at a time** (v1 constraint). If a pull is in flight, no new pull is issued until it completes (success, empty, or error). Prevents parallel pulls that could race and double-populate the queue.
- Emits `queue.pull_issued`, `queue.pull_supplied`, `queue.pull_empty`.
- Note: this implements the GetSuccessorOf *call-out* from AIR (AIR as client) — requires either a test Core server or an in-process mock. Real Core integration is out of scope for Phase C; the pull surface is tested against a mock.
- **Tests:** queue below target → pull fires; Core returns block → queue_depth grows; Core returns empty → retry with backoff; parallel-pull guard: while pull is in flight, additional queue-depth dips do NOT issue second pull.

**C2.5 — Revision + retirement handlers**
- Wire `PutBlockRevision` and `RetireBlock` gRPC handlers to real AirSession logic per the mutability matrix.
- **v1 tightened rule (refinement 5):** revisions are accepted ONLY when every segment of the target Block is in `raw` state. Any segment in `priming`, `armed`, or (parent block) `active` state causes revision rejection. This simplifies the race space: no mid-prime restart, no mid-arm reshape.
- Reason codes: `ACTIVE_BLOCK_IMMUTABLE`, `BLOCK_ARMED`, `BLOCK_PRIMING` (new, v1), `BLOCK_NOT_IN_QUEUE`, `CANONICAL_MISMATCH`, `EMPTY_SEGMENTS`.
- Retirement remains permissive for non-active blocks (disarms armed, cancels priming, drops raw).
- Emits `queue.revision_*`, `queue.retirement_*`.
- **Tests:** each reason code path; accept path for all-raw-segments revision; reject path for priming-state revision (new); disarm + pad bridge on armed-parent retirement.

**C2.6 — C2 integration test**
- Seed Block A (2 segments) → at intra-block seam, move to A.s1 → at block seam, promote to Block B (2 segments) → seam within B → session ends cleanly or pulls for more.
- ffprobe validates the full output.
- Encoder continuity asserted across the block seam: single encoder instance, continuous PTS across A→B transition, no stream restart visible to ffprobe.
- Verify `block_transitions_total == 1`, `segment_transitions_total == 2`, `segments_completed_total == 4`.

### Total commit count

- C0: 1 commit (vault/invariants only, no code)
- C1: 6 commits (was 5; C1.4 split into C1.4a + C1.4b)
- C2: 6 commits
- **Phase C total: 13 commits.** Each small, each testable, each reverting cleanly if needed.

## Relationship to existing memory and vault

- Adds new invariants: `INV-SEGMENT-*`, `INV-BLOCK-*`, `INV-QUEUE-EMPTY-PAD-BRIDGE-001`, `INV-ACTIVE-BLOCK-IMMUTABLE-001`, `INV-ARMED-BLOCK-FROZEN-001`. Where do these live?
  - **Recommendation:** new vault component doc `ExecutionQueue.md` or appendix in `BlockSupplyDemand.md`. Not `AIR_Pipeline.md` (too broad) or `SeamController.md` (seam-specific; not all of these are seam invariants). Decision in Phase C.0 (vault authoring).
- Consumes existing: `SeamController.md` (six-phase lifecycle), `AIR_Lifecycle.md` (OnAir phase unchanged), `AIR_Pipeline.md` (egress pacing unchanged), `AIR_Boundary.md` (INV-AIR-CORE-CONTRACT-001 for segment fields).
- Memory: no new memories needed. Existing `project_retrovue_air_execution_discipline` (arm/commit, fence sacred) directly applies. Existing vocabulary discipline covers all naming.
- Does not modify any existing invariants.

## Open questions (decide during implementation)

1. **Arm window default.** 30 frames (1s at 30fps)? 60? Tunable per session.
2. **Pad-bridge fallback asset.** Reuse PadSourceProducer (existing). Black + silence at channel canonical.
3. **Priming start trigger.** When does priming begin for the next segment? Options: (a) immediately when active segment starts playing; (b) when active segment passes a trigger point (e.g., 10s remaining). Recommendation: (a) for v1; simpler.
4. **Vault doc for new invariants.** New component doc or extend existing. Decide at Phase C.0.
5. **Test Core mock.** A shared test fixture for "Core server responding to GetSuccessorOf" across C2 tests. Build once, reuse.

## Explicitly deferred

- Canonical-changing seams (retune).
- Concurrent priming (>1 segment at a time).
- Editorial mid-asset entry on happy path (Segment.asset_start_offset_ms > 0 with no lateness). Late-successor JIP recovery (lateness_ms > 0) is in scope and implemented in C1.4c with frame-accurate entry.
- Admission pacing (fill-thread architecture).
- Real Core integration (Core-side implementation of the pull/push protocol is not AIR's scope).
- Cross-session state (single-session is still the model).
