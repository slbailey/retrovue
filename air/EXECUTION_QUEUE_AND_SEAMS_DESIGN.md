# AIR vNext — Execution Queue and Seams Design (segment-aware)

**Status:** design note for the upcoming implementation slice.
**Authored:** 2026-04-20 (re-drafted after Phase B.5 rollback for segment awareness).
**Supersedes:** the pre-rollback draft that collapsed Block and Segment into a single asset pointer.

**Scope:** multi-block execution queue in AIR, **segment-level** seam transitions, pull/push contract with Core. Block-to-block transitions are treated as ordinary segment-to-segment seams (the final segment of block A followed by the first segment of block B).

**Out of scope:** device retune, cross-canonical transitions, emergency interrupts, cross-channel coordination. These are future-scope; this note must not encode decisions about them.

## Authority

This design is governed by:

- [[Truth - Block Is Handoff Unit and Segment Is Playback Unit]] — primary authority. Block is Core's handoff unit; Segment is AIR's execution unit. Every Block contains 1..N Segments; neither grain may be collapsed.
- [[Truth - Segment Is AIR's Runtime Unit]] — segment boundaries are AIR's primary runtime decision points.
- `AIR_Boundary §INV-AIR-CORE-CONTRACT-001` — Core MUST supply the full ordered segment list with `asset_uri`, `asset_start_offset_ms`, `segment_duration_ms`, `segment_index`.
- `SeamController.md` — SeamController is the sole authority for segment transition moments.
- `BlockSupplyDemand §Vocabulary Doctrine (AIR vNext)` — vocabulary and ownership split.

Vocabulary per `project_retrovue_air_vocabulary_discipline` memory:
- Core owns the editorial schedule (Blocks).
- AIR owns the execution queue (Blocks + Segments within).
- Pull primary; push override.
- Active immutable; queued mutable; armed frozen except for retirement.

## Purpose

Extend AIR from "one asset per session" to "ordered queue of Blocks, each containing 1..N Segments, with frame-accurate transitions at every Segment boundary." Today AIR takes a single `input_path` at StartChannel and plays until EOF. For real broadcast operation AIR must:
1. Accept multiple Blocks over time (each with its own segment list).
2. Walk through Segments within a Block, executing a seam at each Segment boundary.
3. Transition from the last Segment of Block A to the first Segment of Block B as an ordinary segment seam.
4. Honor editorial revisions of queued-but-not-yet-active Blocks.

## v1 Simplifications (Locked)

Four decisions, locked for the first implementation. Loosen only if production use reveals specific limitations.

1. **Queue depth default = 3 Blocks.** Configurable at session start. Minimum functional = 2 Blocks.
2. **Single priming worker.** Only one Block (and within it, one Segment) may be in the `priming` state at a time.
3. **Armed segments are frozen except for retirement of their parent Block.** Once SeamController arms Segment S for fence tick F, revisions targeting S's parent Block are REJECTED until the seam fires or the Block is retired. Retirement disarms the seam and triggers pad-bridge.
4. **Pull loop runs outside the encode thread.** A dedicated lightweight thread issues queue-depth polls / demand signals. Encode thread stays focused on real-time emission.

---

## 1. Queue ownership model

AIR holds a single ordered **execution queue** of Blocks per session. The active Block additionally has an **active segment cursor** pointing at the currently-playing Segment:

```
active_block:  { block_id=A, segments=[A.s0, A.s1*, A.s2, A.s3], active_segment_index=1 }
queued_blocks: [
  { block_id=B, segments=[B.s0, B.s1] },
  { block_id=C, segments=[C.s0, C.s1, C.s2] },
]
```

(`*` marks the currently-playing segment.)

**AIR-private state:**
- `active_block_` — the Block currently being executed. `std::optional<Block>`.
- `active_segment_index_` — cursor within `active_block_.segments`. `int32_t`, 0-based.
- `queued_blocks_` — ordered deque of upcoming Blocks (each carrying its own segment list).

**Queue depth** is reported in **Blocks** (editorial grain) per `INV-QUEUE-DEPTH-AIR-PRIVATE-001`. Internal diagnostics may also count segments; external interfaces speak in Blocks.

**Segment state** (per segment, not exposed externally):
- `raw` — segment present in a queued Block; no prime work started.
- `priming` — decoder opened, buffers filling (at most one at a time — v1 constraint).
- `primed` — buffers at operational floor; ready for seam.
- `armed` — SeamController has committed the transition onto this Segment at a specific fence tick.
- `active` — currently playing.

**Queue operations** (AIR-internal, serialized by gRPC handler mutex):
- `seed(block)` — install the first Block with segment 0 active.
- `append(block)` — add to end of queued_blocks_.
- `replace(block_id, new_block)` — on Core revision.
- `remove(block_id)` — on Core retirement.
- `promote()` — at Block seam, front of queued_blocks_ becomes active_block_, active_segment_index_ = 0.
- `advance_segment()` — at intra-Block segment seam, active_segment_index_++.
- `drop_active()` — at Close or on active-Block fatal fault.

## 2. Mutability matrix by Block state

Mutation verbs: **revise** (same block_id, updated fields — may include updated segments list) and **retire** (drop by block_id).

| Block state | Revision | Retirement |
|---|---|---|
| **active** | ❌ rejected (`ACTIVE_BLOCK_IMMUTABLE`) | ❌ rejected (`ACTIVE_BLOCK_IMMUTABLE`) |
| any segment of block is **armed** | ❌ rejected (`BLOCK_ARMED`) — v1 | ✓ accepted (disarm + pad-bridge + re-pull) |
| any segment **priming** | ✓ accepted (cancel prime, re-prime from new record) | ✓ accepted (drop) |
| all segments **raw** (no priming/armed work) | ✓ accepted (replace record in-place) | ✓ accepted (remove) |
| block **not in queue** | Silently dropped / logged | Silently dropped / logged |

Note: "armed" is a segment-level state. But per v1 simplification 3, any segment of a block being armed freezes the entire block from revision. Retirement of a block whose segment is armed is accepted (disarm fires).

Rejections return a reason code in the RPC response; they do NOT disturb the session. Acceptances emit an observability event.

## 3. Seam timing doctrine (fence sacred)

**A seam is a Segment-to-Segment transition** — per `SeamController.md` and `Truth - Segment Is AIR's Runtime Unit` statement 3. Two flavors, mechanically identical:
- **Intra-Block seam**: active_segment_index_ advances within active_block_.
- **Inter-Block seam**: the final Segment of active_block_ yields to the first Segment of queued_blocks_.front(); promotion happens as a side effect.

In both cases SeamController runs one seam lifecycle: `observing → armed → committed_for_tick(F) → executed`.

**Arm early, commit exact.**
- SeamController knows the next Segment's fence tick (computed from Segment durations + Block fence, anchored on `start_utc_ms`).
- Arming happens when: (a) the next Segment's fence is known, (b) the next Segment is primed and ready.
- On arming, SeamController issues an arm directive: "successor = Segment X of Block Y, target_tick = F."
- At tick F (precisely), PlaybackDirector executes the pre-armed commit. No re-evaluation.

**Fence is sacred.**
- Active Segment stops emitting at tick F regardless.
- If next Segment is ready at F → seam fires: next Segment emits from F.
- If next Segment is NOT ready at F → pad substitutes at F; active does not overrun.
- Block end_utc_ms is the outer fence of the last Segment in that Block; honored identically.

**Disarm conditions:**
- Next Segment's parent Block is retired → disarm; treat as late successor.
- Next Segment falls out of ready state (prime failure) → disarm; treat as late successor.
- (Revision on an armed-parent Block is rejected per v1 simplification 3, so revision is not a disarm trigger.)

**Late-successor recovery:**
- Pad emits at F.
- AIR keeps priming the next Segment.
- When it becomes ready, emission resumes with the next Segment.
- The late Segment's own fence is still honored — no extension.

## 4. Pull/push contract interactions

### Pull (primary)

AIR issues `GetSuccessorOf(block_id)` when its Block queue depth falls below target:

```
AIR:  GetSuccessorOf(A123)          — "what follows A123?"
Core: { block: B234, segments: [...] }
AIR:  GetSuccessorOf(B234)
Core: { block: C345, segments: [...] }
```

Core responses:
- **Block supplied** — AIR appends (with its segment list) to queue.
- **None available yet** — AIR retries after back-off.
- **Error** — AIR logs; no retry.

### Push (override)

Core pushes at any time:
- `PutBlockRevision(block_id, new_block_data)` — revises a queued Block. AIR applies per the mutability matrix; reason codes on rejection.
- `RetireBlock(block_id)` — drops a queued Block (possibly armed-parent).
- Future: explicit immediate overrides — out of scope here.

### Interactions with segment prime state

- Revision on a Block where all segments are `raw` → replace record.
- Revision on a Block where any segment is `priming` → cancel prime, re-prime with the new record's first raw/needing segment.
- Revision on a Block where any segment is `armed` → **v1: REJECT** with reason `BLOCK_ARMED`.
- Retirement of a Block where no segments are armed/active → drop.
- Retirement of a Block where a segment is armed → disarm seam, drop Block, pad-bridge at the seam's fence tick.
- Retirement of the active Block → rejected (`ACTIVE_BLOCK_IMMUTABLE`).

**Insertion of a new Block** (not covered by revise/retire): Core updates its schedule + sends `RetireBlock(B)` for the now-stale predecessor. AIR re-pulls `GetSuccessorOf(A)` and receives the new B. No dedicated insertion RPC.

## 5. Failure handling cases

| Case | AIR behavior |
|---|---|
| Pull timeout / Core unresponsive | Retry with backoff; pad-bridge at fence if queue empty. |
| Pull returns "no successor yet" | Retry with backoff; same fallback. |
| Prime fails on a queued Segment (decoder error, missing asset) | Mark Segment failed; if its parent Block is armed, disarm. Pad-bridge at fence if this was the next Segment. Continue with the remainder of the Block if possible. |
| Revision arrives targeting active Block | Reject with `ACTIVE_BLOCK_IMMUTABLE`. |
| Revision arrives targeting armed-parent Block | Reject with `BLOCK_ARMED` (v1). |
| Revision on queued Block with only raw segments | Accept; replace record. |
| Retirement of active Block | Reject with `ACTIVE_BLOCK_IMMUTABLE`. |
| Retirement of last queued Block near fence | Drop; pad-bridge at fence; keep pulling. |
| Active Segment source fault mid-stream | Per `AIR_Lifecycle` existing rules — freeze + pad fallback; session continues; active Segment stays active through its own fence. |
| Active Segment source EOF before its fence | Pad under-fill until Segment fence; seam fires normally. |
| Queue empty at a fence | Pad-bridge; continue pulling; emit when next Block arrives. |
| Revision creates canonical mismatch | Reject with `CANONICAL_MISMATCH` (v1: all Blocks in a session share canonical). |

**Not handled in v1:**
- Recovery from fatal session fault post-sign-on (existing `INV-UNDERFLOW-POSTPRIMED-FATAL-001` terminates session).
- Hot canonical change mid-session.
- Multi-queue / parallel streams.

## 6. Minimal observability events

Emitted via the existing lifecycle observer surface. Structured `key=value` on stderr by default.

| Event | Fields |
|---|---|
| `queue.pull_issued` | predecessor_id, mono_us |
| `queue.pull_supplied` | block_id, predecessor_id, segment_count, mono_us |
| `queue.pull_empty` | predecessor_id, mono_us |
| `queue.revision_applied` | block_id, prior_state, mono_us |
| `queue.revision_rejected` | block_id, reason, mono_us |
| `queue.retirement_applied` | block_id, prior_state, mono_us |
| `queue.retirement_rejected` | block_id, reason, mono_us |
| `segment.prime_complete` | block_id, segment_index, mono_us |
| `segment.prime_failed` | block_id, segment_index, reason, mono_us |
| `seam.armed` | block_id, segment_index, target_tick, mono_us |
| `seam.disarmed` | block_id, segment_index, reason, mono_us |
| `seam.committed` | block_id, segment_index, target_tick, mono_us |
| `seam.executed` | from_block_id, from_segment_index, to_block_id, to_segment_index, tick, mono_us |
| `seam.pad_bridge_started` | predecessor_block_id, predecessor_segment_index, mono_us |
| `seam.pad_bridge_ended` | new_active_block_id, new_active_segment_index, mono_us |

Aggregated counters (exposed via `GetSessionStatus`):
- `queue_depth` — count of Blocks (editorial grain).
- `segment_depth` (optional internal diagnostic) — total Segments across active + queued.
- `pad_bridge_ms_total` — cumulative pad-bridge time.
- `seams_executed_total` — successful seams (segment-to-segment transitions of all flavors).
- `block_transitions_total` — count of last→first segment seams (subset of the above).
- `revisions_accepted_total`, `revisions_rejected_total`.

## What this is NOT

- **Not device retune.** Single device, single sink, no canonical change.
- **Not multi-channel.** Single session, single active channel.
- **Not admission pacing.** Fill-thread + PacingController is a separate slice.
- **Not Core-side schedule revision policy.** This note only describes how AIR responds.
- **Not failure-transition within OnAir beyond existing AIR_Lifecycle rules.**

## Open questions (to resolve during implementation)

1. Pull retry backoff policy.
2. `block_id` and `segment_id` formats (opaque strings to AIR).
3. Whether canonical-mismatch on revision is always a hard reject (v1 says yes).
4. Pull-empty fence-proximity behavior (tighten polling as fence approaches).

## Wiring plan (phases; implementation begins after this design note is approved)

- **Phase A (re-do):** proto with `Segment` message, `Block` containing `repeated Segment segments`, RPCs SupplyBlock/PutBlockRevision/RetireBlock stubbed UNIMPLEMENTED, seed_block field on StartChannel. Handlers still stub.
- **Phase B (re-do):** C++ Segment + Block structs, AirSession execution queue (active_block_, active_segment_index_, queued_blocks_), SeedActiveBlock/AddQueuedBlock/QueueDepth on AirSession. Legacy AssignContent synthesizes single-segment Block. queue_foundation_test rebuilt.
- **Phase C (new):** SeamController. Operates on Segment boundaries (intra-Block + inter-Block, uniform). Integration test: two-Block session with multi-Segment blocks validates real seams via ffprobe.

## Relationship to existing memory and vault

- `Truth - Block Is Handoff Unit and Segment Is Playback Unit` — primary authority.
- `Truth - Segment Is AIR's Runtime Unit` — complementary.
- `project_retrovue_air_vocabulary_discipline` — amended 2026-04-20 to add Block/Segment grain awareness.
- `BlockSupplyDemand §Vocabulary Doctrine (AIR vNext)` — amended same.
- `AIR_Lifecycle` — unchanged; seams happen within the OnAir phase.
- `BootstrapContentGate` — unchanged; fires once per session on the first Segment of the first Block.
