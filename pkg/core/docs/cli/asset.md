# Asset Commands

_Related: [Asset Contracts](../contracts/resources/AssetContract.md) • [Asset Domain](../domain/Asset.md)_

## Overview

Asset commands inspect and manage assets in the catalog.

## Commands

### `retrovue asset list`

List assets.

**Syntax:**
```bash
retrovue asset list [options] [--json] [--test-db]
```

**Options:**
- `--tag <tag>` - Filter by tag
- `--canonical-only` - Show only approved assets
- `--json` - Output in JSON format

### `retrovue asset show`

Show detailed asset information.

**Syntax:**
```bash
retrovue asset show <asset-id> [--json] [--test-db]
```

### `retrovue asset update`

Update asset metadata.

**Syntax:**
```bash
retrovue asset update <asset-id> [options] [--json] [--test-db]
```

## See also

- [Asset Contract](../contracts/resources/AssetContract.md) - Behavioral specifications
- [Asset Domain](../domain/Asset.md) - Domain model

