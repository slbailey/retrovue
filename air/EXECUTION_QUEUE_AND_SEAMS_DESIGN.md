# AIR vNext — Execution Queue and Seams Design

**Status:** design note for upcoming implementation slice.
**Authored:** 2026-04-20.
**Scope:** multi-block execution queue in AIR, seam transitions between queued blocks, pull/push contract with Core.

**Out of scope:** device retune, hot re-tuning across channels, emergency interrupts, cross-channel coordination. These are future-scope; this note must not encode decisions about them.

## Purpose

Extend AIR from "one asset per session" to "ordered queue of blocks with fence-anchored transitions." Today AIR takes a single `input_path` at StartChannel and plays until EOF. For real broadcast operation, AIR must accept multiple blocks over time, execute seams between them at scheduled fences, and honor editorial revisions to queued-but-not-yet-active blocks.

Vocabulary per `project_retrovue_air_vocabulary_discipline` memory and `BlockSupplyDemand.md §Vocabulary Doctrine (AIR vNext)`:
- Core owns the editorial schedule.
- AIR owns the execution queue.
- Pull primary; push override.
- Active block immutable; queued blocks mutable.

## v1 Simplifications (Locked)

Four decisions, locked for the first implementation. Loosen only if/when production use reveals specific limitations.

1. **Queue depth default = 3.** Configurable at session start. Minimum functional = 2 (active + one queued). Starting default = 3 (active + two queued — one priming, one raw lookahead).
2. **Single priming worker.** Only one queued block may be in the `priming` state at a time. Once it reaches `primed`, the next raw block may begin priming. No concurrent priming in v1.
3. **Armed blocks are frozen except for retirement.** Once SeamController arms block B for fence F, revisions targeting B are REJECTED until the seam fires or B is retired. Retirement is the only allowed mutation on an armed block; it disarms and triggers pad-bridge. This simplifies the mutation matrix and eliminates the re-prime-during-armed race.
4. **Pull loop runs outside the encode thread.** A dedicated lightweight thread issues queue-depth polls / demand signals. The encode thread remains focused on real-time emission. Thread communication via the same atomic/mutex primitives already used for state transitions.

These supersede any looser wording in the sections below. Where a section previously described broader behavior (e.g., re-prime on armed-block revision), read it in light of these v1 constraints.

---

## 1. Queue ownership model

AIR holds a single ordered **execution queue** per session:

```
[ active_block ]  [ queued[0], queued[1], ..., queued[N-1] ]
```

- **active_block** — the block currently being encoded. At most one.
- **queued** — ordered list of upcoming blocks in playout order. Zero or more.

Queue depth is **private** to AIR, per existing `INV-QUEUE-DEPTH-AIR-PRIVATE-001`. Configurable. Reasonable defaults:
- Minimum functional depth: **2** (active + one queued for seam).
- Starting default: **3** (active + two queued — one priming for next seam, one raw lookahead).
- Max: bounded, not fixed here. Adjustable via session config.

**Core does not observe the queue.** Core sees only:
- Pulls AIR initiates.
- Pushes Core initiates.
- Session status (which block is active, possibly queue length as an integer — not contents).

**Queue operations (all AIR-internal):**
- `promote_to_active(queued[0])` — at seam commit, front of queue becomes active.
- `append(block)` — after a pull satisfies.
- `replace(block_id, new_block_data)` — on Core revision.
- `remove(block_id)` — on Core retirement.
- `drop_active()` — at Close, or on active-block fatal fault.

**Block identity:** every block carries a stable `block_id`. Revisions and retirements key on it. The same `block_id` from Core always refers to the same block.

**Prime state** is per-queued-block, tracked internally:
- `raw` — block record received, no decode/priming work started.
- `priming` — decoder opened, buffers filling.
- `primed` — buffers at operational floor, ready for promotion.
- `armed` — SeamController has committed the promotion for a specific fence tick.

Prime state transitions are internal operational planning; not exposed to Core.

---

## 2. Mutability matrix by block state

Mutations originate from Core: **revise** (same block_id, updated fields) or **retire** (drop block by id).

| Block state | Revision | Retirement | Notes |
|---|---|---|---|
| **active** | ❌ rejected | ❌ rejected | Active block is sacred. Core gets an error response. |
| **armed** | ❌ rejected (v1 simplification 3) | ✓ accepted (disarm + pad-bridge + re-pull) | v1: armed blocks are frozen. Rejection reason `BLOCK_ARMED`. Core may retry after the seam fires or retire+re-supply the block. |
| **primed** | ✓ accepted (re-prime from scratch) | ✓ accepted (drop; next-in-queue takes primed slot) | Re-prime cost is a decoder restart; bounded. |
| **raw** | ✓ accepted (replace record in-place) | ✓ accepted (remove from queue) | Cheapest case — no priming work to undo. |
| **not in queue** | Silently dropped / logged | Silently dropped / logged | Core is sending a mutation for a block AIR never pulled. Possible after AIR retired it, before Core heard. Log and move on. |

**Rejections** return a structured error to the originating RPC; they do NOT disturb the session. Core can resolve by waiting for the active block to transition, then re-sending.

**Acceptances** are acknowledged in the RPC response + emit an observability event.

**Mutation on `armed` is the subtle case.** The rule is permissive (re-prime if time allows, pad-bridge if not). The fence itself is sacred — we never delay the fence to give a late re-prime more runway.

---

## 3. Seam timing doctrine (fence sacred)

A **seam** is the transition at block A's fence tick from A → B, where B is the successor block. Seam semantics:

**Arm early, commit exact** (from execution-discipline memory):
- SeamController moves through conceptual phases: `observing → armed → committed_for_tick(F) → executed`.
- Arming happens when two conditions hold: (a) block A's fence tick F is known (it always is; Core supplies it), (b) block B is primed and ready.
- On arming, SeamController issues an arm directive: "successor = B, target_tick = F." PlaybackDirector stores it.
- At tick F (precisely), PlaybackDirector executes the pre-armed commit. No re-evaluation at F; the decision was made earlier with slack.

**Fence is sacred.**
- Block A MUST stop emitting at fence tick F, regardless of what is ready.
- If block B is ready at F, seam fires: B emits from F.
- If block B is NOT ready at F (not yet primed, revision in flight, EOF-before-fence in B's source, etc.), **pad substitutes** at F. Block A does not overrun.

Why sacred: editorial schedule trust. Operators, EPG, other system components all assume block A ends at F. An overrun breaks every downstream assumption.

**Underrun behavior** (active block's source hits EOF before its fence):
- Active block remains the active block until fence F.
- Between EOF and F, pad substitutes (standard under-flow handling — see `AIR_Lifecycle §INV-UNDERFLOW-NORMAL-FALLBACK-001`).
- At F, seam fires normally.

**Late successor** (successor not ready at F):
- Pad emits at F.
- AIR continues attempting to prime B.
- When B becomes ready, emit resumes with B.
- Block B's own fence is still honored (it is not extended to compensate for late start; the pad gap is the cost).

**Seam disarm conditions** (once armed, may disarm before commit):
- B is revised → disarm, re-prime, re-arm if still possible before F.
- B is retired → disarm; treat as late successor (pad at F).
- B falls out of ready state (prime failure) → disarm; treat as late successor.

---

## 4. Pull/push contract interactions

### Pull (primary flow)

AIR issues `GetSuccessorOf(block_id)` when its queue depth falls below target. The predecessor in the request is AIR's last-known queued block (or active if queue is empty).

```
AIR:  GetSuccessorOf(A123)     — asking "what follows A123?"
Core: { block: B234, ... }     — supplies the next block
AIR:  GetSuccessorOf(B234)     — continues lookahead
Core: { block: C345, ... }
```

Core's responses:
- **Block supplied** — AIR appends to queue.
- **None available yet** — Core has no successor yet (schedule not built that far ahead). AIR retries after a back-off. No error.
- **Error** — Core declines for any reason (channel invalid, schedule retired). AIR logs; no retry.

### Push (override flow)

Core pushes at any time, outside the pull loop:

- `PutBlockRevision(block_id, new_fields)` — revise an existing queued block. AIR looks up by id; applies per mutability matrix.
- `RetireBlock(block_id)` — cancel a queued block. AIR removes and re-pulls if necessary.
- Future: explicit immediate overrides (device retune, emergency interrupt) — **explicitly out of scope here**.

### Interactions with prime state

- Revision on `raw` → replace record. No prime work affected.
- Revision on `priming` → cancel prime-in-flight, restart with new record.
- Revision on `primed` → discard primed buffers, re-prime.
- Revision on `armed` → **v1: REJECT** with reason `BLOCK_ARMED`. Caller may retry after seam fires, or retire the block and supply a replacement.
- Retirement of `raw` → remove. If retired block was the predecessor for a downstream pull, re-pull successor-of(new-predecessor).
- Retirement of `priming` or `primed` → cancel prime work, remove.
- Retirement of `armed` → disarm, remove, pad-bridge at fence.

**Insertion of a new block between existing ones** (not covered by revise/retire):
- Handled by Core updating its internal schedule + retiring the now-stale queued block. AIR then re-pulls and receives the new successor.
- Example: AIR has [A, B, C]. Core wants [A, X, B, C]. Core updates its schedule, sends `RetireBlock(B)` to AIR. AIR removes B, re-pulls `GetSuccessorOf(A)` and gets X. Later pulls `GetSuccessorOf(X)` and gets B again.
- No dedicated insertion RPC needed for v1.

---

## 5. Failure handling cases

Enumerated cases AIR must handle deterministically. "Handle" means a defined behavior with observable trace.

| Case | AIR behavior |
|---|---|
| Pull timeout (Core unresponsive) | Retry with backoff. If queue empty when fence approaches, pad-bridge at fence. Log as operational event. |
| Pull returns "no successor yet" | Retry with backoff. Same fallback as timeout. |
| Prime fails on a queued block (decoder error, missing asset) | Mark block as failed. If armed, disarm. If next in line, skip; pull successor. If prime of block A fails before it becomes active, it transitions to a local "failed" state; AIR logs and treats as retirement. |
| Revision arrives on active block | Reject RPC. Response carries reason `ACTIVE_BLOCK_IMMUTABLE`. |
| Revision arrives on armed block | **v1: REJECT** with reason `BLOCK_ARMED`. Seam proceeds with the already-armed block. Caller may retry after seam or retire+re-supply. |
| Retirement arrives on active block | Reject RPC. Response carries reason `ACTIVE_BLOCK_IMMUTABLE`. |
| Retirement of the last queued block near fence | Drop block; pad-bridge at fence; keep pulling for successor. |
| Active block source fault mid-stream (decoder error) | Per AIR_Lifecycle (existing): normal-underflow fallback (freeze + pad). Session continues. Active block does not switch to failed; it stays active through its fence, with pad under. At fence, normal seam or pad-bridge. |
| Active block source EOF before fence | Pad under-fill until fence. Seam fires normally at fence. |
| Queue empty at fence (no successor pulled, no Core response) | Pad-bridge. Continue pulling. Emit when next block arrives. |
| Revision creates canonical mismatch (e.g., different codec) | Reject revision. Response carries reason `CANONICAL_MISMATCH`. Block stays as it was. |

**What is NOT handled in v1** (explicitly deferred):
- Recovery from a fatal session fault post-sign-on (existing `INV-UNDERFLOW-POSTPRIMED-FATAL-001` terminates session; out of this slice).
- Hot canonical change (device retune) — out of scope per top-of-doc.
- Multi-queue / parallel streams — out of scope (single channel, single queue).

---

## 6. Minimal observability events

All events emitted via the existing LifecycleObserver surface or an equivalent for queue/seam events. Structured `key=value` on stderr by default.

| Event | Fields | When |
|---|---|---|
| `queue.pull_issued` | predecessor_id, mono_us | AIR issues GetSuccessorOf |
| `queue.pull_supplied` | block_id, predecessor_id, mono_us | Core supplied a block |
| `queue.pull_empty` | predecessor_id, mono_us | Core returned "none yet" |
| `queue.revision_applied` | block_id, prior_state, mono_us | Revision accepted |
| `queue.revision_rejected` | block_id, reason, mono_us | Revision rejected (e.g. ACTIVE_BLOCK_IMMUTABLE, CANONICAL_MISMATCH) |
| `queue.retirement_applied` | block_id, prior_state, mono_us | Retirement accepted |
| `queue.retirement_rejected` | block_id, reason, mono_us | Retirement rejected |
| `queue.prime_complete` | block_id, mono_us | Block transitioned to `primed` |
| `queue.prime_failed` | block_id, reason, mono_us | Block failed priming |
| `seam.armed` | block_id, target_tick, mono_us | Seam armed for upcoming fence |
| `seam.disarmed` | block_id, reason, mono_us | Seam disarmed (revision, retirement, un-ready) |
| `seam.committed` | block_id, target_tick, mono_us | Seam at commit point, will fire at target_tick |
| `seam.executed` | from_block_id, to_block_id, tick, mono_us | Seam fired, new active block |
| `seam.pad_bridge_started` | predecessor_id, mono_us | Pad substitution began at or after fence |
| `seam.pad_bridge_ended` | new_active_id, mono_us | Pad ended, content resumed |

Minimal set: 15 events. All structured, all parseable.

Aggregated counters surfaced via `GetSessionStatus` response (extensions to the existing message):
- `queue_depth` — current count of queued blocks (scalar; does not leak identity).
- `pad_bridge_ms_total` — cumulative time in pad-bridge during this session.
- `seams_executed_total` — count of successful seams.
- `revisions_accepted_total`, `revisions_rejected_total`.

---

## Open questions (to resolve during implementation, not here)

1. **Pull retry backoff.** Fixed vs exponential; initial value. Needs a sensible default (e.g., 500 ms initial, 2× up to 5 s).
2. **Block_id format.** String? Integer? UUID? Whatever Core uses; AIR treats as opaque stable identifier. Needs explicit type in the proto.
3. **Canonical-mismatch policy.** Rejecting revisions that change codec/dimensions is safe but restrictive. For v1, reject; revisit if needed.
4. **Pull-empty backoff vs fence proximity.** Should AIR increase pull frequency as fence approaches? Probably yes; specific policy is an implementation tuning knob.

*(Previously-open questions about queue depth default, concurrent priming, and pull-loop thread location are resolved by v1 Simplifications above.)*

---

## What this is NOT

- **Not device retune.** Sink remains attached to the same fd across all seams in this slice. Canonical doesn't change.
- **Not multi-channel.** Single session, single active channel, single queue. (One-process-one-channel per product decisions.)
- **Not admission pacing.** Fill-thread + PacingController is a separate slice. In this slice, priming is on the encode thread or a small dedicated helper — details for implementation.
- **Not Core-side schedule revision policy.** How Core decides to revise or retire is Core's business. This note only describes how AIR responds.
- **Not failure-transition within OnAir beyond existing AIR_Lifecycle rules.** If active block faults fatally (per `INV-UNDERFLOW-POSTPRIMED-FATAL-001`), existing session-terminate behavior applies. Recovery patterns for that are out of scope.

---

## Wiring plan (for implementer — high-level only)

1. **Proto additions.** New RPCs: `GetSuccessorOf`, `PutBlockRevision`, `RetireBlock`. New message: `Block` (id, canonical, asset URI, JIP, fence, etc.). `StartChannel` accepts a seed `Block` instead of `input_path`. `GetSessionStatus` extended with queue metrics.
2. **`AirSession` extension.** Replace single-source model with an execution queue (active + list). Methods: `SeedActiveBlock`, `PullSuccessor`, `HandleRevision`, `HandleRetirement`, `NotifyFenceApproaching`, `CommitSeam`. Preserve existing three-phase AttachOutput / AssignContent (renamed `SeedActiveBlock`?) / OpenAir structure.
3. **SeamController.** New narrow class (similar to BootstrapContentGate). Owns observing → armed → committed state machine. Receives fence-proximity signals from the encode loop; emits arm/disarm/commit directives.
4. **Per-block priming.** The normalizer + decoder chain is constructed per-queued-block, attached to that block's record. When a block becomes active, its chain is already primed; we swap references, not re-initialize.
5. **Pull loop.** Lightweight polling inside the encode thread or a dedicated tiny thread; issues `GetSuccessorOf` when queue depth < target.
6. **Integration test.** Two-block session: seed with block A, observe pull for B, allow encode through fence, verify seam, verify ffprobe sees continuous MPEG-TS. Longer variants: three blocks with revision mid-flight; retirement before fence.

---

## Relationship to existing memory and vault

- `project_retrovue_air_vocabulary_discipline` — this design uses the vocabulary it defines.
- `project_retrovue_air_lifecycle_model` — this slice adds to the OnAir phase; does not introduce new top-level lifecycle phases. Seams happen within OnAir.
- `project_retrovue_air_execution_discipline` — arm-early/commit-exact, fence sacred, tick-boundary commits all directly apply.
- `BlockSupplyDemand.md §Vocabulary Doctrine (AIR vNext)` — the vault-side counterpart. Any new invariants for this slice live there or in a new component doc (`AIR_ExecutionQueue.md` if warranted).
- `AIR_Lifecycle.md §INV-LIFECYCLE-FIRST-BYTE-CONTENT-001` — unchanged; still applies. First byte on wire of a session is content, regardless of queue state.
- `BootstrapContentGate.md` — governs sign-on for the session's first block. Unchanged; fires once per session. Subsequent blocks do NOT re-fire bootstrap; they fire seams.
