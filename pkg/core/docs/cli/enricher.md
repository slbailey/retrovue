# Enricher Commands

_Related: [Enricher Contracts](../contracts/resources/EnricherContract.md) • [Enricher Domain](../domain/Enricher.md)_

## Overview

Enricher commands manage enricher instances for ingest and playout.

## Commands

### `retrovue enricher list`

List all enrichers.

**Syntax:**
```bash
retrovue enricher list [--json]
```

### `retrovue enricher add`

Create an enricher instance.

**Syntax:**
```bash
retrovue enricher add --type <type> --name <name> [options] [--json]
```

**Required Options:**
- `--type <type>` - Enricher type (ingest or playout)
- `--name <name>` - Human-readable label

### `retrovue enricher remove`

Remove an enricher.

**Syntax:**
```bash
retrovue enricher remove <enricher-id> [--force] [--confirm] [--json]
```

## See also

- [Enricher Contract](../contracts/resources/EnricherAddContract.md) - Behavioral specifications
- [Enricher Domain](../domain/Enricher.md) - Domain model

