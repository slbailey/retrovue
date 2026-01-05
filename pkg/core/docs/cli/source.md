# Source Commands

_Related: [Source Contract](../contracts/resources/SourceContract.md) • [Source Domain](../domain/Source.md)_

## Overview

Source commands manage content sources (Plex servers, filesystem directories) and their collections.

## Commands

### `retrovue source list`

List all configured sources.

**Syntax:**
```bash
retrovue source list [--type <type>] [--json] [--test-db]
```

**Options:**
- `--type <type>` - Filter by source type (plex, filesystem)
- `--json` - Output in JSON format
- `--test-db` - Query test database

**Examples:**
```bash
retrovue source list
retrovue source list --type plex
retrovue source list --json
```

### `retrovue source add`

Register a new content source.

**Syntax:**
```bash
retrovue source add --type <type> --name <name> [type-specific options] [--enrichers <list>] [--discover] [--dry-run] [--json] [--test-db]
```

**Required Options:**
- `--type <type>` - Source type (plex, filesystem)
- `--name <name>` - Human-readable name

**Type-Specific Options:**

**Plex:**
- `--base-url <url>` - Plex server base URL (required)
- `--token <token>` - Plex authentication token (required)

**Filesystem:**
- `--base-path <path>` - Base filesystem path to scan (required)

**Common Options:**
- `--enrichers <list>` - Comma-separated list of enricher IDs
- `--discover` - Automatically discover collections after creation
- `--dry-run` - Show what would be created without executing
- `--json` - Output in JSON format
- `--test-db` - Use test database

**Examples:**
```bash
retrovue source add --type plex --name "My Plex" --base-url "http://192.168.1.100:32400" --token "token"
retrovue source add --type filesystem --name "Local Media" --base-path "/media/movies"
```

### `retrovue source discover`

Discover collections from a source.

**Syntax:**
```bash
retrovue source discover <source-id> [--json] [--test-db]
```

**Arguments:**
- `<source-id>` - Source ID, name, or external ID

**Examples:**
```bash
retrovue source discover "My Plex Server"
retrovue source discover plex-5063d926 --json
```

### `retrovue source show`

Show detailed information for a source.

**Syntax:**
```bash
retrovue source show <source-id> [--json] [--test-db]
```

### `retrovue source update`

Update source configuration.

**Syntax:**
```bash
retrovue source update <source-id> [options] [--json] [--test-db]
```

### `retrovue source delete`

Remove a source.

**Syntax:**
```bash
retrovue source delete <source-id> [--force] [--confirm] [--json] [--test-db]
```

**Safety:** Requires confirmation unless `--force` or `--confirm` is provided.

### `retrovue source list-types`

Show available source types.

**Syntax:**
```bash
retrovue source list-types [--json]
```

### `retrovue source ingest`

Ingest content from a source.

**Syntax:**
```bash
retrovue source ingest <source-id> [options] [--json] [--test-db]
```

## See also

- [Source Contract](../contracts/resources/SourceAddContract.md) - Behavioral specifications
- [Source Domain](../domain/Source.md) - Domain model

