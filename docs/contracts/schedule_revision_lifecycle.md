# Schedule Revision REST Lifecycle Contract

Authority Domain: Scheduling
Owner: ScheduleService (scheduling layer)
Derived From: `INV-SCHEDULEREVISION-IMMUTABLE-001`, `LAW-IMMUTABILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Defines the REST contract for operator-facing ScheduleRevision lifecycle management.
Operators create draft revisions, review them, and explicitly publish (draft → active).
Publication atomically supersedes any existing active revision for the same (channel_id, broadcast_day).

Active revisions are immutable — no PUT/PATCH. Schedule changes require a new draft + publish cycle.

---

## Endpoints

### GET /api/scheduling/channels/{channel_id}/revisions

List revisions for a channel. Supports filtering.

**Query Parameters:**
- `broadcast_day` (date, optional) — filter by broadcast day (YYYY-MM-DD)
- `status` (string, optional) — filter by status: `draft`, `active`, `superseded`

**Response:** `200 OK`
```json
[
  {
    "id": "<uuid>",
    "channel_id": "<uuid>",
    "broadcast_day": "2026-03-04",
    "status": "active",
    "created_at": "<iso8601>",
    "activated_at": "<iso8601> | null",
    "superseded_at": "<iso8601> | null",
    "created_by": "<string> | null",
    "item_count": 5
  }
]
```

**Error Responses:**
- `404 Not Found` — channel does not exist

---

### POST /api/scheduling/channels/{channel_id}/revisions

Create a draft revision with items.

**Request Body:**
```json
{
  "broadcast_day": "2026-03-04",
  "created_by": "operator",
  "items": [
    {
      "start_time": "2026-03-04T06:00:00+00:00",
      "duration_sec": 1800,
      "asset_id": "<uuid> | null",
      "content_type": "episode",
      "metadata": {}
    }
  ]
}
```

**Response:** `201 Created`
```json
{
  "id": "<uuid>",
  "channel_id": "<uuid>",
  "broadcast_day": "2026-03-04",
  "status": "draft",
  "created_at": "<iso8601>",
  "activated_at": null,
  "superseded_at": null,
  "created_by": "operator",
  "items": [
    {
      "id": "<uuid>",
      "start_time": "2026-03-04T06:00:00+00:00",
      "duration_sec": 1800,
      "asset_id": "<uuid> | null",
      "content_type": "episode",
      "slot_index": 0
    }
  ]
}
```

**Error Responses:**
- `404 Not Found` — channel does not exist
- `422 Unprocessable Entity` — empty items list (INV-PERSISTENCE-GUARD-NONEMPTY-001)

---

### GET /api/scheduling/revisions/{revision_id}

Get a single revision with its items.

**Response:** `200 OK`
```json
{
  "id": "<uuid>",
  "channel_id": "<uuid>",
  "broadcast_day": "2026-03-04",
  "status": "active",
  "created_at": "<iso8601>",
  "activated_at": "<iso8601> | null",
  "superseded_at": "<iso8601> | null",
  "created_by": "<string> | null",
  "items": [
    {
      "id": "<uuid>",
      "start_time": "2026-03-04T06:00:00+00:00",
      "duration_sec": 1800,
      "asset_id": "<uuid> | null",
      "content_type": "episode",
      "slot_index": 0
    }
  ]
}
```

**Error Responses:**
- `404 Not Found` — revision does not exist

---

### POST /api/scheduling/revisions/{revision_id}/publish

Publish a draft revision: transitions to `active`, atomically supersedes any existing active revision for the same (channel_id, broadcast_day).

**Request Body:** None required.

**Response:** `200 OK`
```json
{
  "id": "<uuid>",
  "channel_id": "<uuid>",
  "broadcast_day": "2026-03-04",
  "status": "active",
  "activated_at": "<iso8601>",
  "superseded_revision_id": "<uuid> | null"
}
```

**Error Responses:**
- `404 Not Found` — revision does not exist
- `409 Conflict` — revision is not in `draft` status (cannot publish non-draft)
- `422 Unprocessable Entity` — revision has zero items (INV-PERSISTENCE-GUARD-NONEMPTY-001)

---

## Lifecycle Rules

1. **Draft creation:** New revisions are always created as `draft`. Items are attached at creation time with deterministic `slot_index` assignment (0-based, insertion order).

2. **Publish (draft → active):** Publication atomically:
   - Validates the revision has at least one item
   - Validates the revision is in `draft` status
   - Supersedes any existing `active` revision for the same (channel_id, broadcast_day): sets status to `superseded`, sets `superseded_at`
   - Transitions the draft to `active`, sets `activated_at`
   - Upserts the `ChannelActiveRevision` pointer

3. **Immutability (active lock):** Once `active`, a revision's items MUST NOT be mutated. There is no PUT/PATCH endpoint for active revisions. This delegates to `INV-SCHEDULEREVISION-IMMUTABLE-001`.

4. **Supersession:** When a new revision is published, any existing active revision for the same (channel_id, broadcast_day) transitions to `superseded`. At most one active revision exists per (channel_id, broadcast_day) at any time (enforced by DB partial unique index).

5. **Empty revision guard:** Revisions with zero items MUST NOT be published. The publish endpoint rejects them with `422`.

---

## Non-Goals

- No timeline boundary enforcement on publish via REST. The internal `write_active_revision_from_compiled_schedule()` pipeline enforces `INV-TIMELINE-BOUNDARY-IMMUTABLE-001` for automated writes. Operator-initiated publish via REST creates a new active revision without boundary checks — the operator has explicit intent.
- No DELETE endpoint for revisions. Revisions are historical records.
- No PATCH/PUT on revision items. Use new draft + publish.

---

## Required Tests

- `server/tests/contracts/scheduling/test_schedule_revision_rest_lifecycle.py`
