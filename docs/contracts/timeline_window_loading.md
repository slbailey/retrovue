# Timeline Window Loading Contract

**Status:** Architectural Contract
**Authority Level:** Constitutional — Runtime Layer

---

## I. Purpose

Timeline loading populates the runtime block list from persisted schedule data. The selection criterion is time-range intersection against a continuous window. Broadcast day boundaries have no role in determining which blocks are loaded.

---

## II. Core Invariant — Continuous Time Model

Time is continuous. The runtime timeline is a flat sequence of non-overlapping blocks ordered by `start_utc_ms`. Timeline construction MUST NOT depend on broadcast day partitioning, day-start offsets, or day-relative indexing.

`broadcast_day` is a storage-level grouping key. It MUST NOT influence inclusion, exclusion, or ordering of blocks in the runtime timeline.

---

## III. Window Intersection Rule

A block MUST be included in the runtime timeline if and only if:

    block.start_utc_ms < window_end_utc_ms
    AND
    block.end_utc_ms   > window_start_utc_ms

This is the canonical inclusion predicate. All timeline loading paths MUST apply this rule without modification.

Blocks satisfying this predicate MUST be included regardless of which `broadcast_day` they were compiled under.

Blocks not satisfying this predicate MUST NOT be included.

---

## IV. Prohibited Concepts

The following concepts MUST NOT appear in timeline loading logic:

| Prohibited | Replacement |
|---|---|
| "carry-in block" | Window intersection (Section III) |
| "previous day loading" | Window intersection across all days |
| "last block from prior day" | No ordinal selection; intersection only |
| "last item by slot_index" | No ordinal selection; intersection only |
| Single-block carry-in limit | No cardinality limit; all intersecting blocks |

No selection heuristic based on ordering, recency, or cardinality MUST be used as a substitute for the window intersection predicate.

---

## V. Timeline Continuity

The runtime timeline MUST NOT contain temporal gaps within the active window. For every instant `t` where `window_start_utc_ms <= t < window_end_utc_ms`, exactly one of the following MUST hold:

1. A block `b` exists such that `b.start_utc_ms <= t < b.end_utc_ms`.
2. No persisted block covers `t` (schedule gap — reported as 503, not masked).

All blocks satisfying the window intersection predicate MUST be present. Omitting a qualifying block is a loading fault, not a schedule gap.

---

## VI. Deterministic Reconstruction

Given identical inputs `(window_start_utc_ms, window_end_utc_ms)` and identical persisted state, the loaded timeline MUST be identical.

Process restarts, service crashes, and cold starts MUST NOT change which blocks are loaded for a given window. The timeline is a deterministic function of the window bounds and the persisted schedule data.

---

## VII. Ordering and Uniqueness

Blocks in the runtime timeline MUST be sorted by `start_utc_ms` ascending.

A block MUST appear at most once. Duplicate `block_id` entries MUST NOT exist in the loaded timeline.

---

## VIII. Boundary Behavior

Blocks MUST be loaded from any `broadcast_day` whose blocks intersect the window. The loader MUST scan all `broadcast_day` values that could contain intersecting blocks.

The minimum scan range: any `broadcast_day` whose compiled blocks could have `end_utc_ms > window_start_utc_ms`. In practice this requires loading at least the current broadcast day and the immediately prior broadcast day.

`broadcast_day` boundaries MUST NOT cause block exclusion, truncation, or deduplication.

---

## IX. Required Test Categories

| Category | Condition |
|---|---|
| Overlap inclusion | Block spanning window boundary is loaded |
| Non-overlap exclusion | Block entirely outside window is not loaded |
| Multi-block overlap | Multiple blocks from same day intersecting window are all loaded |
| Cross-day inclusion | Block compiled under prior `broadcast_day` intersecting window is loaded |
| No gaps | No temporal gap exists between loaded blocks within the window |
| Deterministic results | Same window bounds produce identical block list across restarts |
| Boundary-exact exclusion | Block ending exactly at `window_start_utc_ms` is not loaded |
| Boundary-exact inclusion | Block starting exactly at `window_start_utc_ms` is loaded |

---

## X. Violation

Any of the following constitutes a violation:

- A block satisfying the window intersection predicate is absent from the loaded timeline.
- A block not satisfying the predicate is present.
- Blocks are loaded based on ordinal position, `broadcast_day` membership, or cardinality limits rather than time intersection.
- The loaded timeline differs across restarts given identical persisted state and window bounds.
- A temporal gap exists in the timeline that is caused by loading logic rather than a true schedule gap.
