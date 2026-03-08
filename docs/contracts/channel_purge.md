# INV-CHANNEL-PURGE-001 — Channel purge removes all derived broadcast state

Status: Invariant
Authority Level: Infrastructure
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

---

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-DERIVATION` by ensuring that when channels are removed, all downstream artifacts derived from those channels are also removed. Stale schedule, playlist, or traffic state referencing deleted channels violates the derivation chain.

## Guarantee

Deleting all channels MUST remove all channel-scoped broadcast state. After purge completes, the system MUST behave as if no channels were ever configured.

Purge MUST NOT remove media assets, catalog data, or library metadata.

## Preconditions

The caller MUST hold a database session with write access.

## Tables Removed (channel-scoped broadcast state)

The following tables MUST contain zero channel-scoped rows after purge:

| Table | FK Cascade | Cleanup Method |
|-------|-----------|----------------|
| `channels` | — | Direct delete |
| `programs` | `channels.id` CASCADE | Automatic |
| `schedule_plans` | `channels.id` CASCADE | Automatic |
| `zones` | `schedule_plans.id` CASCADE | Automatic (via plan) |
| `schedule_plan_labels` | `schedule_plans.id` CASCADE | Automatic (via plan) |
| `schedule_revisions` | `channels.id` CASCADE | Automatic |
| `schedule_items` | `schedule_revisions.id` CASCADE | Automatic (via revision) |
| `channel_active_revisions` | `channels.id` CASCADE | Automatic |
| `serial_runs` | `channels.id` CASCADE | Automatic |
| `program_log_days` | `channel_id` (string, no FK) | Explicit delete |
| `traffic_play_log` | `channel_slug` (string, no FK) | Explicit delete |
| `playlist_events` | `channel_slug` (string, no FK) | Explicit delete |

## Tables Preserved (MUST NOT be modified)

| Table | Domain |
|-------|--------|
| `assets` | Media catalog |
| `asset_editorial` | Media catalog |
| `asset_probed` | Media catalog |
| `asset_station_ops` | Media catalog |
| `asset_relationships` | Media catalog |
| `asset_sidecar` | Media catalog |
| `asset_tags` | Media catalog |
| `sources` | Ingest |
| `collections` | Ingest |
| `path_mappings` | Ingest |
| `markers` | Media catalog |
| `enrichers` | Ingest |
| `titles` | Media catalog |
| `seasons` | Media catalog |
| `episodes` | Media catalog |
| `provider_refs` | Media catalog |
| `review_queue` | Media catalog |

## Observability

After purge, `SELECT count(*) FROM channels` MUST return 0. Queries against all cascade and explicit-delete tables for any previously existing channel identifier MUST return zero rows.

## Deterministic Testability

Create channels with full derived state (plans, revisions, items, playlist events, traffic log). Execute purge. Assert all channel-scoped tables are empty. Assert all catalog tables are unchanged.

## Failure Semantics

**Infrastructure fault.** Purge MUST execute in a single transaction. If any step fails, the transaction MUST roll back and the database MUST remain unchanged.

---

# INV-CHANNEL-PURGE-002 — Purge is idempotent

Status: Invariant
Authority Level: Infrastructure
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects operational safety. Running purge on an already-empty system MUST NOT raise errors or modify catalog state.

## Guarantee

Executing purge when no channels exist MUST succeed and MUST NOT modify any table.

## Observability

Second invocation produces the same post-state as the first.

## Deterministic Testability

Run purge twice in sequence. Assert no errors. Assert catalog tables unchanged after both runs.

## Failure Semantics

**Infrastructure fault.** Any error on an empty-state purge is a bug.

---

# INV-CHANNEL-PURGE-003 — Non-cascaded tables require explicit cleanup

Status: Invariant
Authority Level: Infrastructure
Derived From: `LAW-DERIVATION`

## Purpose

Three tables use `channel_slug` (string) or `channel_id` (string) columns without foreign key constraints to `channels`. Postgres CASCADE does not reach them. Purge MUST explicitly delete rows from these tables.

## Guarantee

Purge MUST explicitly delete all rows from `program_log_days`, `traffic_play_log`, and `playlist_events` before or after the `channels` table delete. These deletions MUST be part of the same transaction.

## Observability

After purge, `SELECT count(*) FROM program_log_days` MUST return 0. Same for `traffic_play_log` and `playlist_events`.

## Deterministic Testability

Insert rows into `program_log_days`, `traffic_play_log`, and `playlist_events` for a test channel. Delete the channel via purge. Assert all three tables are empty.

## Failure Semantics

**Infrastructure fault.** Orphaned rows in non-cascaded tables are stale broadcast state and violate `LAW-DERIVATION`.

---

## Required Tests

- `pkg/core/tests/contracts/test_channel_purge.py`

---

## Enforcement Evidence

TODO
