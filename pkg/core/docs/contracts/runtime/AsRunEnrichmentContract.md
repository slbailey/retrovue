# Contract — As-Run Enrichment via Transmission Log

**Classification:** RUNTIME CONTRACT
**Owner:** `EvidenceServicer` in `runtime/evidence_server.py`
**Introduced:** 2026-02-18
**Depends on:** `runtime/TransmissionLogPersistenceContract.md`, `INV-TRAFFIC-LATE-BIND-001.md`

---

## Purpose

This contract defines how the evidence server enriches as-run log entries with
segment metadata (commercial titles, types, durations) drawn from the
`transmission_log` table.

Before this contract, the evidence server used an in-process `SegmentLookup`
singleton (`runtime/segment_lookup.py`) populated by `BlockPlanProducer` before
feeding each block. This created a tight coupling between the producer and the
evidence server, and was unreliable when the evidence server process was separate
from the producer.

The DB-backed approach queries `transmission_log` by `block_id` on each `SEG_START`
event, making the evidence server self-contained and fault-tolerant.

---

## Data Flow

```
AIR  →  SEG_START(block_id, segment_index)  →  EvidenceServicer
                                                     │
                                          query transmission_log
                                          WHERE block_id = ?
                                                     │
                                          parse segments JSONB
                                          find segment at index
                                                     │
                                     segment_type, asset_uri, title
                                                     │
                                    ┌────────────────┴─────────────────┐
                               .asrun line                      .asrun.jsonl
                           COMMERCL [Brand Ad]              segment_type, asset_uri...
```

---

## SEG_START Enrichment

On each `SEG_START` event from AIR:

1. Extract `block_id` and `segment_index` from the event.
2. Check in-memory cache: if `block_id` is cached, use cached segments.
3. If not cached: query `transmission_log WHERE block_id = ?`.
4. Parse `segments` JSONB array.
5. Store parsed segments in cache keyed by `block_id`.
6. Look up segment at `segment_index`.
7. Enrich the as-run entry with segment metadata.

---

## Human-Readable .asrun Format

The `.asrun` type column (8 chars, left-justified) maps `segment_type` to a
broadcast-standard abbreviation:

| `segment_type` | `.asrun` type column |
|----------------|---------------------|
| `content`      | `PROGRAM` |
| `commercial`   | `COMMERCL` |
| `promo`        | `PROMO` |
| `ident`        | `IDENT` |
| `psa`          | `PSA` |
| `filler`       | `FILLER` |
| `pad`          | `PAD` |
| (unknown)      | `PROGRAM` |

The title appears in the notes column in brackets: `[Brand Ad 30s]`.

Example enriched `.asrun` line:

```
10:30:00 00:00:30 OK         COMMERCL block-20260218-1030:2       [brand-ad-30s]
```

Without enrichment (fallback):

```
10:30:00 00:00:30 OK         PROGRAM  block-20260218-1030:2
```

---

## Machine-Readable .asrun.jsonl Format

For `SEG_START` events, the JSONL record gains additional fields when enrichment
succeeds:

```json
{
  "event_type": "SEG_START",
  "block_id": "block-20260218-1030",
  "segment_index": 2,
  "start_utc_ms": 1739872200000,
  "segment_type": "commercial",
  "asset_uri": "/media/interstitials/brand-ad-30s.mp4",
  "segment_title": "brand-ad-30s",
  "segment_duration_ms": 30000
}
```

Without enrichment (graceful degradation):

```json
{
  "event_type": "SEG_START",
  "block_id": "block-20260218-1030",
  "segment_index": 2,
  "start_utc_ms": 1739872200000
}
```

---

## In-Memory Cache

The evidence server maintains a per-`block_id` cache of parsed segment lists:

```python
_block_segment_cache: dict[str, list[dict]] = {}
```

- Populated on the first `SEG_START` for a given `block_id`.
- Cleared when the block completes (`BLOCK_COMPLETE` event from AIR).
- Maximum cache size: 10 blocks (evict oldest on overflow; in practice only
  2-3 blocks are ever in-flight simultaneously per INV-FEED-QUEUE-DISCIPLINE).

This avoids repeated DB queries within a single block (which may contain dozens
of segments). The cache is keyed by `block_id`, not `channel_id`, because
`block_id` is globally unique.

---

## Graceful Degradation

The evidence server MUST NOT crash or halt due to enrichment failures.
If any of the following occur, fall back to unenriched output:

- `transmission_log` row not found for `block_id`.
- `segments` JSONB cannot be parsed.
- `segment_index` is out of range.
- DB connection unavailable.

Fallback behavior:
- `.asrun` type column: `PROGRAM`
- `.asrun` notes: no title in brackets
- `.asrun.jsonl`: no extra segment fields
- Log a `WARNING` with `block_id` and `segment_index`.

This ensures that a DB outage does not interrupt as-run logging.

---

## Deleted Module: segment_lookup.py

The in-process `SegmentLookup` singleton (`runtime/segment_lookup.py`) and its
associated `get_global_lookup()` function are deleted as part of this change.

`BlockPlanProducer._register_segment_lookup()` and the corresponding
`_register_segment_lookup()` call in `_try_feed_block()` are also removed.

The `transmission_log` DB table is the sole segment metadata store.

---

## Invariants

**INV-ASRUN-ENRICH-DEGRADE-001:** The evidence server MUST never crash due to
enrichment failure. Degrade to unenriched output; never raise.

**INV-ASRUN-ENRICH-CACHE-001:** Segment cache MUST be cleared on block completion
to prevent stale data from leaking into the next block.

**INV-ASRUN-ENRICH-SOURCE-001:** The sole source of segment enrichment data is
`transmission_log`. The in-process `SegmentLookup` singleton MUST NOT be used.

---

## See Also

- `runtime/TransmissionLogPersistenceContract.md` — table schema and write path
- `runtime/INV-TRAFFIC-LATE-BIND-001.md` — why fill happens at feed time
- `runtime/evidence_server.py` — `EvidenceServicer`, `AsRunWriter`
- `domain/entities.py` — `TransmissionLog` SQLAlchemy model
