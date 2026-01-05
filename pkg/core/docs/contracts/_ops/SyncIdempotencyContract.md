# Sync Idempotency

## Purpose

Ensure all synchronization commands (e.g., ingest, schedule sync, metadata refresh) produce the same final system state when run repeatedly, without duplicating or corrupting data.

## Scope

Applies to all CLI-driven sync operations and automated background daemons that interact with external or internal data stores.

## Design Principles

- **Idempotent by default:** Re-running a sync command should never introduce duplicates or inconsistencies.
- **Predictable syntax:** Human operators must find commands easy to remember and reason about.
- **Verifiable through mocks:** Sync behavior should be validated against a mock environment before affecting real systems.

## CLI Syntax

```
retrovue sync <target> [--force] [--dry-run] [--test-db]
```

### Parameters

- `target`: Component or data type to synchronize (e.g., `schedule`, `media`, `epg`).
- `--force`: Bypasses idempotency cache to rebuild state completely.
- `--dry-run`: Displays changes that would occur without applying them.
- `--test-db`: Runs against mock database for validation.

### Examples

```
# Validate schedule sync without committing
retrovue sync schedule --dry-run --test-db

# Force full media resync in mock DB
retrovue sync media --force --test-db

# Run live idempotent sync (after testing)
retrovue sync schedule
```

## Testing Procedure

1. Run command in `--test-db` mode and observe resulting database state.
2. Re-run command with same parameters to verify no new changes occur (idempotency).
3. Remove `--test-db` and confirm identical behavior in staging or live environments.

## Documentation Integration

CLI syntax and usage examples must appear in `CONTRIBUTING.md` under the "Sync Operations" section.






