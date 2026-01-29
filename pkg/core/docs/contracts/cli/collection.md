# Collection Commands

_Related: [Collection Contracts](../contracts/resources/CollectionContract.md) • [Collection Domain](../domain/Collection.md)_

## Overview

Collection commands manage collections within sources and their ingest configuration.

## Commands

### `retrovue collection list`

List all collections.

**Syntax:**
```bash
retrovue collection list [--source <source-id>] [--json] [--test-db]
```

**Options:**
- `--source <source-id>` - Filter by source ID
- `--json` - Output in JSON format
- `--test-db` - Use test database

### `retrovue collection show`

Show detailed collection information.

**Syntax:**
```bash
retrovue collection show <collection-id> [--json] [--test-db]
```

### `retrovue collection update`

Update collection configuration.

**Syntax:**
```bash
retrovue collection update <collection-id> [options] [--json] [--test-db]
```

**Options:**
- `--sync-enabled/--sync-disabled` - Enable/disable sync
- `--ingestible/--not-ingestible` - Mark as ingestible or not

### `retrovue collection ingest`

Ingest content from a collection.

**Syntax:**
```bash
retrovue collection ingest <collection-id> [options] [--json] [--test-db]
```

## See also

- [Collection Contract](../contracts/resources/CollectionIngestContract.md) - Behavioral specifications
- [Collection Domain](../domain/Collection.md) - Domain model

