_Related: [Contracts](../contracts/resources/README.md) • [Architecture](../architecture/ArchitectureOverview.md)_

# CLI Command Reference

This directory contains the authoritative reference documentation for all RetroVue CLI commands. This documentation defines **command syntax, arguments, and usage examples**.

For **behavioral contracts** (rules, guarantees, exit codes, data effects), see [`docs/contracts/resources/`](../contracts/resources/README.md).

## Documentation Structure

Each command group has its own documentation file:

- [`source.md`](source.md) - Source and collection management
- [`channel.md`](channel.md) - Broadcast channel operations
- [`collection.md`](collection.md) - Collection management
- [`asset.md`](asset.md) - Asset inspection and review
- [`enricher.md`](enricher.md) - Enricher management
- [`producer.md`](producer.md) - Producer management
- [`runtime.md`](runtime.md) - Runtime diagnostics and validation

## CLI Router Architecture

RetroVue uses a **router-based CLI dispatcher**. All commands are registered through a centralized router that maps top-level nouns to command groups.

### Registration Pattern

Command groups are registered in `src/retrovue/cli/main.py`:

```python
router.register(
    "channel",
    channel.app,
    help_text="Broadcast channel operations",
    doc_path="channel.md",
)
```

### Command Grammar

All commands follow the flat structure:

```
retrovue <noun> <verb> [options]
```

**Examples:**
- `retrovue channel list`
- `retrovue channel add --name "RetroToons"`
- `retrovue source discover <source-id>`
- `retrovue collection ingest <collection-id>`

### Global Flags

All commands support these global flags:

| Flag        | Description                                    |
| ----------- | ---------------------------------------------- |
| `--dry-run` | Preview what would be done without executing   |
| `--force`   | Bypass confirmation prompts (use with caution)   |
| `--json`    | Output result in structured JSON format        |
| `--test-db` | Execute against an isolated test database      |

### Exit Codes

| Code | Meaning                                     |
| ---- | ------------------------------------------- |
| `0`  | Success                                     |
| `1`  | Validation or runtime failure               |
| `2`  | Partial success (some recoverable failures) |
| `3`  | External dependency unreachable             |

## Documentation vs Contracts

### This Directory (`docs/cli/`)

**Purpose**: Command syntax and usage reference

**Contains**:
- Command syntax and grammar
- Available flags and arguments
- Usage examples
- Command discovery and navigation

**Use when**: You need to know "how to type the command" or "what flags are available"

### Contracts Directory (`docs/contracts/resources/`)

**Purpose**: Behavioral specifications and guarantees

**Contains**:
- Behavior Rules (B-#) - CLI behavior requirements
- Data Rules (D-#) - Persistence and integrity guarantees
- Exit code specifications
- Safety and confirmation requirements
- Output format schemas

**Use when**: You need to know "what the command guarantees" or "what rules it must follow"

## Command Group Index

### Source Management

- `retrovue source list` - List configured sources
- `retrovue source add` - Register a new source
- `retrovue source discover` - Discover collections from a source
- `retrovue source update` - Update source configuration
- `retrovue source delete` - Remove a source

See [`source.md`](source.md) for full documentation.

### Channel Management

- `retrovue channel list` - List all channels
- `retrovue channel add` - Create a new channel
- `retrovue channel show` - Show channel details
- `retrovue channel update` - Update channel configuration
- `retrovue channel validate` - Validate channel configuration

See [`channel.md`](channel.md) for full documentation.

### Collection Management

- `retrovue collection list` - List collections
- `retrovue collection show` - Show collection details
- `retrovue collection update` - Update collection configuration
- `retrovue collection ingest` - Ingest content from a collection

See [`collection.md`](collection.md) for full documentation.

### Asset Operations

- `retrovue asset list` - List assets
- `retrovue asset show` - Show asset details
- `retrovue asset update` - Update asset metadata

See [`asset.md`](asset.md) for full documentation.

### Enricher Management

- `retrovue enricher list` - List enrichers
- `retrovue enricher add` - Create an enricher
- `retrovue enricher remove` - Remove an enricher

See [`enricher.md`](enricher.md) for full documentation.

### Producer Management

- `retrovue producer list` - List producers
- `retrovue producer add` - Create a producer
- `retrovue producer remove` - Remove a producer

See [`producer.md`](producer.md) for full documentation.

### Runtime Operations

- `retrovue runtime masterclock` - Master clock diagnostics
- `retrovue runtime status` - Runtime system status

See [`runtime.md`](runtime.md) for full documentation.

## Adding New Command Groups

When adding a new command group:

1. **Create the command module** in `src/retrovue/cli/commands/`
2. **Register with router** in `src/retrovue/cli/main.py`:
   ```python
   router.register(
       "new-noun",
       new_noun.app,
       help_text="Description of operations",
       doc_path="new-noun.md",
   )
   ```
3. **Create CLI documentation** in `docs/cli/new-noun.md`
4. **Create contract documentation** in `docs/contracts/resources/NewNounVerbContract.md`
5. **Update this README** with the new command group

## Router Implementation

The router is implemented in `src/retrovue/cli/router.py`. It provides:

- Explicit command group registration
- Documentation path mapping
- Registration metadata tracking
- Discovery of registered groups

The router is a thin abstraction over Typer's `add_typer()` mechanism, providing:
- Clear domain ownership
- Explicit registration
- Documentation traceability
- Future extensibility for nested routing

## See also

- [Contracts](../contracts/resources/README.md) - Behavioral specifications
- [CLI Change Policy](../contracts/resources/CLI_CHANGE_POLICY.md) - Governance rules
- [Architecture Overview](../architecture/ArchitectureOverview.md)

