# Container Commands

_Related: [Container Contracts](../contracts/resources/ContainerContract.md) • [Container Domain](../../data/domain/Container.md)_

## Overview

Container commands manage containers within sources and their ingest configuration. Use `retrovue container` for all operations; `retrovue collection` is deprecated and will be removed in a future release.

## Commands

### `retrovue container list`

List containers for a source.

**Syntax:**
```bash
retrovue container list [--source <source-id>] [--json] [--test-db]
```

**Options:**
- `--source <source-id>` - Filter by source ID
- `--json` - Output in JSON format
- `--test-db` - Use test database

### `retrovue container show`

Show detailed container information.

**Syntax:**
```bash
retrovue container show <container-id> [--json] [--test-db]
```

### `retrovue container update`

Update container configuration.

**Syntax:**
```bash
retrovue container update <container-id> [options] [--json] [--test-db]
```

**Options:**
- `--sync-enabled/--sync-disabled` - Enable/disable sync
- `--ingestible/--not-ingestible` - Mark as ingestible or not

### `retrovue container ingest`

Ingest content from a container.

**Syntax:**
```bash
retrovue container ingest <container-id> [options] [--json] [--test-db]
```

### `retrovue container sync`

Sync a container: discover new files and/or run enrichers on pending assets.

**Syntax:**
```bash
retrovue container sync <container-id> [--enrich-only] [--new-files-only] [--limit N]
```

## Deprecation

The `retrovue collection` command group is deprecated. Use `retrovue container` for all operations. The `collection` alias will emit a warning and may be removed in a future release.

## See also

- [Container Contract](../contracts/resources/ContainerIngestContract.md) - Behavioral specifications
- [Container Domain](../../data/domain/Container.md) - Domain model
