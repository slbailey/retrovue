# Entity: PlaylistEvent

**Classification:** Entity Specification
**Layer:** Core (Execution Intent)
**Upstream:** ScheduleItem
**Downstream:** ExecutionSegment

---

## Purpose

A **PlaylistEvent** defines the execution plan for a single scheduled program block. It represents the fully expanded playout structure for a **ScheduleItem**, including content acts, filler segments, transitions, and padding. PlaylistEvents are created lazily -- they are only instantiated when playout requires a block. A PlaylistEvent is **immutable** once created.

For the conceptual execution model, semantic boundary rules, and layer authority definitions, see [PlayoutExecutionModel](PlayoutExecutionModel.md).

---

## Persistence: `playlist_events` Table

| Column | Type | Notes |
|---|---|---|
| block_id | text, primary key | Deterministic SHA-256 of identity |
| schedule_item_id | uuid, fk -> schedule_items.id | |
| channel_id | uuid, fk -> channels.id | |
| broadcast_day | date | Programming day |
| start_utc_ms | bigint | UTC start (ms) |
| end_utc_ms | bigint | UTC end (ms) |
| segments | jsonb | Segment list (see below) |
| created_at | timestamp with time zone | |

---

## Relationships

- **ScheduleItem**
  - **PlaylistEvent** (1-to-1)

Each **ScheduleItem** produces exactly **one** PlaylistEvent. PlaylistEvents may not exist until playout actually requires the block.

---

## Deterministic Identity

Each PlaylistEvent has a deterministic `block_id`:

```
block_id = sha256(asset_id + start_time)
```

This guarantees:
- Idempotent expansion
- Cacheable blocks
- Stable references even if recomputed

---

## Domain Model Fields

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable unique identifier (= `block_id`) |
| `start_utc_ms` | int | Wall-clock start time (epoch milliseconds) |
| `duration_ms` | int | Duration of this event in milliseconds |
| `kind` | Literal["content", "ad", "promo", "pad", "override"] | The type of execution intent |
| `schedule_item_id` | string or null | ScheduleItem this event derives from. Required for `content`. Null for non-content kinds. |
| `asset_id` | string or null | Asset to play. Required for `content`, `ad`, `promo`. Null for `pad`. |
| `offset_ms` | int or null | Offset into the asset at which playback begins. Required for `content`. Null or 0 for non-content kinds. |
| `metadata` | dict | Optional. Extensible metadata (ratings, flags, signaling hints). |

**Field requirements by kind:**

| Field | content | ad | promo | pad | override |
|---|---|---|---|---|---|
| `schedule_item_id` | Required | Null | Null | Null | Optional |
| `asset_id` | Required | Required | Required | Null | Required |
| `offset_ms` | Required | 0 | 0 | Null | 0 |

Notes:

- `start_utc_ms` is absolute wall-clock time aligned to the playout timeline.
- `duration_ms` is the wall-clock duration this event occupies. For content events, this is the playback duration within this event, not the full program duration.
- `offset_ms` for content events indicates the byte-stream position within the asset. For a 90-minute movie on a 30-minute grid with no semantic breaks, `offset_ms` would be 0 and `duration_ms` would be 5,400,000. If an ad break splits the movie at minute 45, the first content event has `offset_ms=0, duration_ms=2,700,000` and the second has `offset_ms=2,700,000, duration_ms=2,700,000`.
- `id` is generated during PlaylistEvent creation and is stable for the lifetime of the playout horizon window containing it.

---

## Segment Structure

The `segments` column stores a heterogeneous list in JSON form, encoding all required playout segments.

**Example:**

```json
[
  {
    "segment_type": "content",
    "asset_uri": "/media/tng/s03e15.mkv",
    "asset_start_offset_ms": 0,
    "segment_duration_ms": 440000
  },
  {
    "segment_type": "filler",
    "asset_uri": "/media/interstitials/promo_002.mp4",
    "segment_duration_ms": 160000
  }
]
```

**Possible segment types:**
- `content`
- `filler`
- `pad`
- `transition`

---

## Runtime Generation

When the playout engine (via `ChannelManager`) needs instructions:

```
ChannelManager
    |
    v
Find ScheduleItem for timestamp
    |
    v
Lookup PlaylistEvent by schedule_item_id
    |
    v
If missing, generate PlaylistEvent from ScheduleItem
```

**Example queries:**

```sql
SELECT * FROM schedule_items
WHERE start_at <= now() AND end_at > now();
```

```sql
SELECT * FROM playlist_events
WHERE schedule_item_id = ?;
```

If no PlaylistEvent exists, it is (deterministically) generated on demand.

---

## Operator Interaction

PlaylistEvents are **not** operator-editable. They are derived, execution-only artifacts.

Operators interact exclusively with **ScheduleItem**, not PlaylistEvent.

---

**Related:** [PlayoutExecutionModel](PlayoutExecutionModel.md) | [ScheduleItem](../ScheduleItem.md) | [ExecutionSegment](ExecutionSegment.md)
