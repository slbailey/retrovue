# INV-AIR-SEGMENT-IDENTITY-AUTHORITY: UUID-Based Segment Identity

**Classification:** INVARIANT (Identity — Execution-Grade)
**Owner:** PipelineManager / EvidenceEmitter / AsRunReconciler
**Enforcement Phase:** Every AIR event emission and reporting resolution path
**Depends on:** INV-BLOCK-WALLCLOCK-FENCE-001 (block boundary timing)
**Does NOT modify:** INV-BLOCK-WALLCLOCK-FENCE-001, INV-BLOCK-FRAME-BUDGET-AUTHORITY, INV-BLOCK-LOOKAHEAD-PRIMING
**Created:** 2025-07-14
**Status:** Active

---

## Definition

Segment identity within a block execution MUST be carried by a UUID
assigned at block feed time.  Positional index (`segment_index`) is
display-order metadata only and MUST NOT be used as an identity key
in any runtime reporting, evidence, or reconciliation path.

---

## Scope

These invariants apply to:

- **AIR event emission** (SEG_START, AIRED) — must carry `segment_uuid` and `asset_uuid`.
- **AsRun and Evidence reporting layers** — must resolve metadata via `segment_uuid`.
- **JIP renumbering** — must preserve UUID identity across index changes.

These invariants do NOT apply to:

- **Block boundary timing** — governed by INV-BLOCK-WALLCLOCK-FENCE-001.
- **Frame budget counting** — governed by INV-BLOCK-FRAME-BUDGET-AUTHORITY.
- **Lookahead priming** — governed by INV-BLOCK-LOOKAHEAD-PRIMING.
- **Historical database queries** — may continue to use original index for archival retrieval.

---

## Definitions

| Term | Definition |
|------|------------|
| **segment_uuid** | A UUID4 assigned to each segment at block feed time — specifically, after JIP mutation but before AIR execution begins.  Immutable for the lifetime of the block execution.  Uniqueness scope is `(block_execution_instance)`: two executions of the same scheduled block MUST generate distinct `segment_uuid` values.  `segment_uuid` is not persisted across schedule rebuilds or replay sessions. |
| **asset_uuid** | The UUID of the asset scheduled for this segment.  Present for CONTENT and FILLER segment types.  Explicitly `null` for PAD segments. |
| **segment_index** | The zero-based positional index of a segment within its block.  Display-order only.  MAY change under JIP renumbering. |
| **segment_type** | One of: `CONTENT`, `FILLER`, `PAD`. |
| **block_feed_time** | The moment a scheduled block is compiled into an executable block for AIR.  This occurs after JIP mutation (segment list is final) but before any AIR tick executes.  `segment_uuid` generation MUST happen at this boundary — not earlier (planning) and not later (SEG_START emission). |
| **JIP (Join-In-Progress)** | Runtime renumbering of segments when a block is entered mid-execution.  Changes `segment_index` but MUST NOT change `segment_uuid` or `asset_uuid`. |

---

## Invariants

### INV-AIR-SEGMENT-ID-001: Segment UUID Is Execution Identity

> Every AIR segment MUST carry a `segment_uuid` field.
>
> `segment_uuid` is generated at block feed time — after JIP mutation
> has finalized the segment list, but before any AIR tick executes.
> It is immutable for the lifetime of the block execution.
>
> Uniqueness scope is `(block_execution_instance)`.  Two executions
> of the same scheduled block (e.g., a replay, a schedule rebuild
> triggering re-feed) MUST generate distinct `segment_uuid` values.
> `segment_uuid` MUST NOT be persisted from planning and reused
> across executions.
>
> `segment_index` is display-order only — it describes the segment's
> position in the rendered schedule grid.  It is NOT an identity key.
>
> Reporting MUST NOT use `segment_index` as an identity key for
> resolving segment metadata, correlating evidence events, or
> matching planned-to-actual segments.

**Why:** Positional identity breaks under JIP, filler insertion, segment
reordering, and block reshaping.  A segment at index 2 in the plan may
be at index 1 at runtime after JIP skips the first segment.  UUID-based
identity is stable across all these transformations by construction.

---

### INV-AIR-SEGMENT-ID-002: Asset UUID Explicitness

> CONTENT and FILLER segments MUST carry an `asset_uuid` field
> identifying the scheduled asset.
>
> PAD segments MUST emit:
>
> ```
> asset_uuid = null
> segment_type = PAD
> ```
>
> Reporting MUST NOT infer asset identity by adjacency (e.g., "the
> segment after segment 2 must be asset X") or by database index
> lookup (e.g., "SELECT asset FROM segments WHERE index = 2").

**Why:** Adjacency-based inference assumes stable ordering.  DB index
lookup assumes positional identity.  Both fail under the same conditions
that break `segment_index` identity: JIP, filler insertion, reordering.
Explicit `asset_uuid` eliminates inference entirely.

---

### INV-AIR-SEGMENT-ID-003: Reporting Is UUID-Driven

> AsRun and Evidence layers MUST resolve segment metadata using
> `segment_uuid` as the lookup key.
>
> If metadata is missing for a given `segment_uuid`:
>
> 1. Log a violation: `SEGMENT_UUID_METADATA_MISSING: {segment_uuid}`
> 2. Do NOT fall back to database index lookup
> 3. Do NOT fall back to positional resolution
> 4. Mark the segment as unresolved in the report
>
> Cache keys for segment metadata MUST be keyed by `segment_uuid`,
> not by `segment_index` or any positional derivative.

**Why:** Fallback to positional lookup defeats the purpose of UUID
identity.  If index-based lookup silently succeeds, the system appears
correct while masking a broken identity chain.  Explicit failure surfaces
the bug immediately.

---

### INV-AIR-SEGMENT-ID-004: JIP Does Not Change Identity

> JIP renumbering MAY change `segment_index` (display order) to
> reflect the runtime entry point into a block.
>
> JIP MUST NOT change:
>
> - `segment_uuid` — the segment's execution identity
> - `asset_uuid` — the segment's asset reference
>
> After JIP renumbering, a segment with `segment_uuid = X` MUST
> still resolve to the same asset, the same metadata, and the same
> evidence trail as before renumbering.

**Why:** JIP is a display-layer operation: "we're starting from segment
3 instead of segment 0."  It changes where you look in the grid, not
what the segments are.  If JIP mutated UUIDs, evidence correlation would
break for any block entered mid-execution.

---

### INV-AIR-SEGMENT-ID-005: Event Completeness

> Every SEG_START and AIRED event MUST carry ALL of the following
> identity fields:
>
> - `block_id`
> - `segment_uuid`
> - `segment_type`
> - `asset_uuid` (nullable only when `segment_type = PAD`)
>
> An event lacking ANY required identity field MUST be rejected at
> the emission boundary and logged as a violation BEFORE emission.
> Partial-identity events MUST NOT reach the evidence spool, the
> AsRun layer, or any downstream consumer.
>
> Identity is atomic: either the full identity envelope is present,
> or the event does not exist.

**Why:** Without completeness enforcement, it is possible to emit
SEG_START with a UUID and AIRED without one — producing a partial
identity trail that silently degrades correlation.  Rejecting
incomplete events at the emission boundary converts silent data
loss into an immediate, actionable violation.

---

## Forbidden Patterns

| Pattern | Why Forbidden |
|---------|---------------|
| `segments[segment_index]` as identity resolution in reporting | Positional lookup; breaks under JIP and reordering. |
| `SELECT ... WHERE segment_index = N` in runtime reporting path | DB index lookup; positional identity. |
| `_lookup_segment_from_db(block_id, segment_index)` in runtime path | Direct positional DB resolution; must use `segment_uuid`. |
| Inferring `asset_uuid` from adjacent segment position | Adjacency inference; unstable under insertion/deletion. |
| Omitting `segment_uuid` from SEG_START or AIRED events | Identity must be explicit in every event. |
| Omitting `asset_uuid` from CONTENT/FILLER segments | Asset identity must be explicit, not inferred. |
| Emitting PAD with non-null `asset_uuid` | PAD segments carry no asset; `asset_uuid = null` is the contract. |
| Emitting a partial-identity event (e.g., SEG_START with UUID, AIRED without) | Identity is atomic; partial events corrupt the evidence trail. |

---

## Failure Modes

| Failure | Required Behavior | Governing Invariant |
|---------|-------------------|---------------------|
| SEG_START emitted without `segment_uuid` | Violation; must not proceed without identity | ID-001 |
| AIRED emitted without `segment_uuid` | Violation; must not proceed without identity | ID-001 |
| CONTENT segment missing `asset_uuid` | Violation; segment marked incomplete | ID-002 |
| PAD segment with non-null `asset_uuid` | Violation; PAD must not carry asset identity | ID-002 |
| Metadata lookup by `segment_uuid` returns empty | Log violation; do NOT fallback to index | ID-003 |
| JIP changes `segment_uuid` | Violation; UUID is immutable | ID-004 |
| JIP changes `asset_uuid` | Violation; asset identity is immutable | ID-004 |
| SEG_START or AIRED missing any required identity field | Reject before emission; log violation | ID-005 |
| Partial-identity event reaches evidence spool | Violation; emission boundary failed to enforce completeness | ID-005 |
| Replay reuses `segment_uuid` from prior execution | Violation; UUID scope is per-execution | ID-001 |

---

## Relationship to Existing Contracts

### INV-BLOCK-WALLCLOCK-FENCE-001 (Timing Authority — Unmodified)

This contract does NOT affect block boundary timing.  Fence computation,
block transitions, and the TAKE remain governed by WALLFENCE.  Segment
identity is orthogonal to when blocks start and end.

### INV-BLOCK-FRAME-BUDGET-AUTHORITY (Counting Authority — Unmodified)

Frame budgets are unchanged.  This contract affects how segments are
*identified*, not how many frames they produce.

### INV-BLOCK-LOOKAHEAD-PRIMING (Coordination — Unmodified)

Priming logic is unchanged.  Segment UUIDs are assigned at feed time,
before priming begins.

### AirExecutionEvidenceEmitterContract (Evidence — Modified)

Evidence events MUST include `segment_uuid` and `asset_uuid` per
INV-AIR-SEGMENT-ID-001 and ID-002.  The emitter's JSON payload gains
two required fields.

### AsRunReconciliationContract (Reporting — Modified)

Reconciliation MUST correlate planned-to-actual segments using
`segment_uuid`, not `segment_index`.  The reconciler's matching
logic shifts from positional to UUID-based.

| Contract | Relationship |
|----------|-------------|
| INV-BLOCK-WALLCLOCK-FENCE-001 | Unmodified; timing authority unchanged |
| INV-BLOCK-FRAME-BUDGET-AUTHORITY | Unmodified; counting authority unchanged |
| INV-BLOCK-LOOKAHEAD-PRIMING | Unmodified; priming unchanged |
| AirExecutionEvidenceEmitterContract | Modified; events gain segment_uuid, asset_uuid |
| AsRunReconciliationContract | Modified; reconciliation keyed by UUID |

---

## Required Tests

**File:** `pkg/air/tests/contracts/test_air_segment_identity.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_segment_uuid_present_in_air_events` | ID-001 | Fail if SEG_START or AIRED event lacks `segment_uuid`. |
| `test_asset_uuid_present_for_content` | ID-002 | CONTENT/FILLER must include `asset_uuid`. PAD must include `asset_uuid = null`. |
| `test_reporting_uses_uuid_not_index` | ID-003 | Simulate DB segments [0,1,2,3] with AIR renumbered [0,1,2]. Intentionally mismatch indices. Assert reporting resolves correct asset via UUID. |
| `test_no_db_lookup_by_index` | ID-003 | Monkeypatch `_lookup_segment_from_db`. Fail if called during runtime reporting. |
| `test_jip_does_not_change_segment_uuid` | ID-004 | Simulate JIP renumbering. Assert `segment_uuid` and `asset_uuid` unchanged. |
| `test_event_completeness_rejects_partial` | ID-005 | Emit events missing required identity fields. Assert rejection before emission. |
| `test_replay_generates_new_uuids` | ID-001 | Feed the same scheduled block twice. Assert all `segment_uuid` values differ between executions. |
| `test_uuid_generated_at_feed_time_not_planning` | ID-001 | Assert `segment_uuid` is absent from planning output and present only after block feed. |
