# INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH — YAML config is authoritative for channel set

Status: Invariant
Authority Level: Infrastructure
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring the operator-controlled YAML configuration is the sole source of truth for which channels exist. The database MUST reflect the YAML channel set after reconciliation.

## Guarantee

After `reconcile_channels(db, yaml_channel_slugs)` completes, the set of channel slugs in the database MUST equal `yaml_channel_slugs`. Channels present in YAML but absent from the database MUST be created. Channels present in the database but absent from YAML MUST be deleted along with all derived broadcast state.

## Preconditions

The caller MUST hold a database session with write access. `yaml_channel_slugs` MUST be a set of strings.

## Observability

After reconciliation, `SELECT slug FROM channels` MUST return exactly the slugs in `yaml_channel_slugs`.

## Deterministic Testability

Create channels in the database. Provide a YAML slug set that adds one channel and removes another. Execute reconciliation. Assert the database channel set matches the YAML set.

## Failure Semantics

**Infrastructure fault.** Reconciliation MUST execute in a single transaction. If any step fails, the transaction MUST roll back and the database MUST remain unchanged.

## Required Tests

- `server/tests/contracts/test_channel_reconciliation.py`

## Enforcement Evidence

TODO

---

# INV-CHANNEL-RECONCILE-DELETE — Removed channels lose all derived state

Status: Invariant
Authority Level: Infrastructure
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-DERIVATION` by ensuring that when a channel is removed from the YAML configuration, all downstream artifacts derived from that channel are also removed. This includes both FK-cascaded tables and non-FK string-keyed tables (`program_log_days`, `traffic_play_log`, `playlist_events`).

## Guarantee

Deleting a channel via reconciliation MUST remove all channel-scoped broadcast state for that channel. Tables with FK CASCADE to `channels` are cleaned automatically. Tables using string channel identifiers (`program_log_days`, `traffic_play_log`, `playlist_events`) MUST be explicitly cleaned for the removed channel slugs.

Channels that remain in the YAML set MUST NOT be modified. Catalog tables (assets, collections, sources, etc.) MUST NOT be modified.

## Preconditions

The caller MUST hold a database session with write access.

## Observability

After reconciliation, queries against all channel-scoped tables for any removed channel slug MUST return zero rows. Rows for surviving channels MUST be unchanged.

## Deterministic Testability

Create two channels with full derived state including non-FK table rows. Provide a YAML set containing only one of the two slugs. Execute reconciliation. Assert all state for the removed channel is gone. Assert all state for the surviving channel is intact.

## Failure Semantics

**Infrastructure fault.** Orphaned rows in non-cascaded tables for deleted channels violate `LAW-DERIVATION`.

## Required Tests

- `server/tests/contracts/test_channel_reconciliation.py`

## Enforcement Evidence

TODO

---

# INV-CHANNEL-RECONCILE-IDEMPOTENT — Reconciliation is idempotent

Status: Invariant
Authority Level: Infrastructure
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects operational safety. Running reconciliation twice with the same YAML set MUST produce the same database state and MUST NOT raise errors.

## Guarantee

Executing `reconcile_channels(db, yaml_channel_slugs)` twice in sequence with the same input MUST NOT raise errors and MUST NOT modify any table beyond the first invocation.

## Observability

Second invocation produces the same post-state as the first.

## Deterministic Testability

Run reconciliation twice with the same YAML set. Assert no errors. Assert channel count and catalog tables unchanged after both runs.

## Failure Semantics

**Infrastructure fault.** Any error or state change on a second invocation with identical input is a bug.

## Required Tests

- `server/tests/contracts/test_channel_reconciliation.py`

## Enforcement Evidence

TODO

---

# INV-CHANNEL-RECONCILE-EMPTY-GUARD — Empty config set must not purge existing channels

Status: Invariant
Authority Level: Infrastructure
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by preventing silent, total channel destruction during startup. If `load_all_schedules()` returns an empty set due to a configuration loading failure, `reconcile_channels()` MUST NOT delete all existing database channels.

## Guarantee

If `yaml_channel_slugs` is empty AND the database contains one or more channels, `reconcile_channels()` MUST raise a `RuntimeError` rather than proceeding with deletion. The caller MUST explicitly opt into full purge by passing `allow_full_purge=True`.

## Preconditions

The caller MUST hold a database session with read access (to check existing channel count).

## Observability

A `RuntimeError` with a clear message is raised. The database remains unchanged.

## Deterministic Testability

Create one or more channels in the database. Call `reconcile_channels(db, set())` without `allow_full_purge`. Assert `RuntimeError` is raised. Assert channel count is unchanged.

## Failure Semantics

**Infrastructure fault.** Proceeding with an empty config set against a populated database is a destructive misconfiguration, not an intentional operation.

## Required Tests

- `server/tests/contracts/test_channel_reconciliation.py`

## Enforcement Evidence

- `TestChannelReconcileEmptyGuard::test_empty_config_with_existing_channels_raises` — guard raises RuntimeError
- `TestChannelReconcileEmptyGuard::test_empty_config_with_allow_full_purge` — explicit purge permitted
- `TestChannelReconcileEmptyGuard::test_empty_config_with_no_existing_channels` — empty DB is no-op

---

# Startup Sequence — Channel Reconciliation Context

The following documents the startup sequence in `ProgramDirector._background_prewarm()` where channel reconciliation executes. This is the ONLY path where `reconcile_channels()` is called during normal startup.

## Sequence

```
load_all_schedules()
    → reconcile_channels(db, configured_ids)   ← INV-CHANNEL-RECONCILE-EMPTY-GUARD fires here
        → _prewarm_channel_schedules()
            → _init_playlog_daemons()
```

1. **`load_all_schedules()`** — Reads YAML schedule definitions from disk. Returns the set of configured channel IDs. If this returns empty due to a transient config failure, the empty-guard prevents reconciliation from proceeding.

2. **`reconcile_channels(db, configured_ids)`** — Compares configured channel IDs against the database. Creates missing channels, deletes removed channels with all derived state. Protected by INV-CHANNEL-RECONCILE-EMPTY-GUARD against accidental total purge.

3. **`_prewarm_channel_schedules()`** — Compiles schedule horizons for all configured channels. Requires reconciliation to have completed so the DB channel set is consistent with YAML.

4. **`_init_playlog_daemons()`** — Starts background playlog maintenance threads. Requires channel schedules to be pre-warmed.

## Invariant

The ordering is strict: each step depends on the prior step's completion. Reordering or skipping steps violates the startup contract.
