# Contract — Transmission Log Persistence

**Classification:** DATA CONTRACT (Runtime)
**Owner:** `BlockPlanProducer._try_feed_block` (write), `EvidenceServicer` (read)
**Introduced:** 2026-02-18
**Depends on:** INV-TRAFFIC-LATE-BIND-001

---

## Purpose

The `transmission_log` table is the authoritative, durable record of exactly what
segments were fed to AIR for each block — including the concrete commercial URIs
resolved at feed time.

It bridges the gap between the compile-time schedule (which has empty filler
placeholders) and the evidence stream (which reports segment indices from AIR):

```
Compile time  →  empty filler placeholders  →  compiled_program_log
Feed time     →  filled block (real URIs)   →  transmission_log   ←─── evidence_server
```

---

## Table Schema

```sql
CREATE TABLE transmission_log (
    block_id        VARCHAR(255) PRIMARY KEY,
    channel_slug    VARCHAR(255) NOT NULL,
    broadcast_day   DATE NOT NULL,
    start_utc_ms    BIGINT NOT NULL,
    end_utc_ms      BIGINT NOT NULL,
    segments        JSONB NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ix_transmission_log_channel_day
    ON transmission_log (channel_slug, broadcast_day);
```

`block_id` is the primary key. The same `block_id` that `BlockPlanProducer` assigns
(from `ScheduledBlock.block_id`) is what AIR reports back in evidence events.

---

## Segments JSONB Structure

Each row stores the full, expanded segment list for the block as a JSON array.
Each element is a segment object with the following fields:

```json
[
  {
    "segment_index": 0,
    "segment_type": "content",
    "asset_uri": "/media/shows/episode-s01e01.mp4",
    "asset_start_offset_ms": 0,
    "segment_duration_ms": 1320000,
    "title": "episode-s01e01"
  },
  {
    "segment_index": 1,
    "segment_type": "commercial",
    "asset_uri": "/media/interstitials/brand-ad-30s.mp4",
    "asset_start_offset_ms": 0,
    "segment_duration_ms": 30000,
    "title": "brand-ad-30s"
  },
  {
    "segment_index": 2,
    "segment_type": "pad",
    "asset_uri": "",
    "asset_start_offset_ms": 0,
    "segment_duration_ms": 2000,
    "title": "BLACK"
  }
]
```

Segment types in use: `content`, `commercial`, `promo`, `ident`, `psa`, `filler`, `pad`.

**The segments array reflects the FILLED block** — it contains real commercial URIs
resolved by `fill_ad_blocks()` at feed time. Compile-time empty placeholders
(`asset_uri=""`, `segment_type="filler"`) never appear in `transmission_log`.

---

## Write Path

Written by `BlockPlanProducer._try_feed_block()` immediately after `fill_ad_blocks()`
and before `session.feed(block)`:

```
_try_feed_block(block):
    1. fill_ad_blocks(block, ...)          → filled_block
    2. persist_transmission_log(db, filled_block)
    3. write traffic_play_log entries
    4. session.feed(filled_block)          → gRPC to AIR
```

A fresh DB session is opened and closed within `_try_feed_block`. The session is
**not held across feeds** — each block write is an independent transaction.

On error during fill: fall back to static filler, still persist, still feed.

---

## Read Path

Read by `EvidenceServicer` in `evidence_server.py` on `SEG_START` events from AIR.

The evidence server:
1. Receives `SEG_START(block_id, segment_index)` from AIR.
2. Queries `transmission_log WHERE block_id = ?`.
3. Parses the `segments` JSONB array.
4. Finds the segment at `segment_index`.
5. Uses `segment_type` and `title` to enrich the `.asrun` log line.
6. Adds `segment_type`, `asset_uri`, `segment_title`, `segment_duration_ms` to `.asrun.jsonl`.

Results are cached in-memory per `block_id` (cleared on block completion) to avoid
repeated DB queries within a single block.

---

## Indexes and Performance

| Index | Purpose |
|-------|---------|
| `block_id` (PRIMARY KEY) | Per-block lookup from evidence server (O(1)) |
| `ix_transmission_log_channel_day` on `(channel_slug, broadcast_day)` | Daily traffic reports, reconciliation queries |

---

## Retention Policy

Rows are retained for **N days** (configurable, default 7) after `created_at`.
After that, they may be archived to cold storage or deleted.

A periodic maintenance job (or Alembic migration) handles pruning:

```sql
DELETE FROM transmission_log
WHERE created_at < now() - INTERVAL 7 days;
```

As-run logs (`.asrun` files) are the long-term record. The `transmission_log`
table is operational data needed only while blocks may still be on-air or
within the replay-reconciliation window.

---

## Invariants

**INV-TXLOG-WRITE-BEFORE-FEED-001:** `transmission_log` MUST be written before
`session.feed(block)` is called. If the DB write fails, the feed MUST still proceed
(degrade gracefully; log the error; do not halt playout).

**INV-TXLOG-FILLED-ONLY-001:** Only filled blocks (with real asset URIs) are persisted.
Empty filler placeholders (`asset_uri=""`) MUST NOT appear in `transmission_log.segments`.

**INV-TXLOG-BLOCK-ID-001:** `block_id` in `transmission_log` MUST exactly match the
`block_id` sent to AIR in the `BlockPlan`. AIR reports this same ID in evidence events.

---

## See Also

- `runtime/INV-TRAFFIC-LATE-BIND-001.md` — invariant governing when traffic fill occurs
- `runtime/AsRunEnrichmentContract.md` — how evidence server uses this table
- `domain/entities.py` `TransmissionLog` — SQLAlchemy model
- `runtime/channel_manager.py` `BlockPlanProducer._try_feed_block` — write site
- `runtime/evidence_server.py` `EvidenceServicer` — read site
