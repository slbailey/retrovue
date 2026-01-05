# CLI Router Architecture Contract

## Purpose

Define the behavioral contract for the CLI router-based command dispatch system. This contract ensures consistent command registration, clear domain ownership, and explicit documentation mapping.

## Command Registration

### R-1: Explicit Registration Required

All command groups MUST be registered through the centralized `CliRouter` in `src/retrovue/cli/main.py`. Direct calls to `app.add_typer()` outside the router are forbidden.

### R-2: Registration Metadata

Each command group registration MUST include:
- Command group name (noun)
- Typer app instance
- Help text description
- Documentation path (relative to `docs/cli/`)

### R-3: No Duplicate Registrations

The router MUST reject duplicate command group names and raise `ValueError` if a name is registered twice.

### R-4: Registration Order Preservation

Command groups MUST be registered in a consistent order. The router tracks registration order for discovery and documentation generation.

## Command Grammar

### R-5: Flat Command Structure

All commands follow the flat structure:

```
retrovue <noun> <verb> [options]
```

**Examples:**
- `retrovue channel list`
- `retrovue channel add --name "RetroToons"`
- `retrovue source discover <source-id>`

### R-6: No Nested Routing (v0.1)

Nested routes like `retro channel <id> schedule-template list` are NOT supported in v0.1. Use flat structure with explicit IDs:

```
retrovue schedule-template list --channel-id <id>
```

**Future Enhancement**: Nested routing support may be added in future versions (e.g., `retrovue channel <id> schedule-template list`) to provide more intuitive command hierarchies for resource-specific operations.

## Documentation Requirements

### R-7: CLI Documentation Location

All CLI command syntax and usage documentation MUST be in `docs/cli/`. Each command group MUST have a corresponding markdown file:

- `docs/cli/source.md` - Source commands
- `docs/cli/channel.md` - Channel commands
- `docs/cli/collection.md` - Collection commands
- etc.

### R-8: Contract Documentation Location

Behavioral contracts (rules, guarantees, exit codes) MUST remain in `docs/contracts/resources/`. These define behavior, not syntax.

### R-9: Documentation Split

- **`docs/cli/`**: Command syntax, arguments, flags, usage examples
- **`docs/contracts/resources/`**: Behavior rules (B-#), data rules (D-#), exit codes, safety requirements

### R-10: Documentation Mapping

The router MUST track `doc_path` for each registered command group. This enables automated documentation validation and discovery.

### R-10a: Documentation Link Validation (Dev-Time)

The router MUST provide a `validate_documentation_links()` method that verifies all registered command groups have corresponding markdown files in `docs/cli/`. This is an optional dev-time check that can be run during development or CI to ensure documentation mapping is correct.

**Example usage:**
```python
router = get_router(app)
# ... register all commands ...
validation = router.validate_documentation_links()
if not all(validation.values()):
    missing = [name for name, valid in validation.items() if not valid]
    raise ValueError(f"Missing CLI docs: {missing}")
```

**Future Enhancement**: CLI documentation generation via static parser walk - a future tool could automatically generate or update `docs/cli/*.md` files by parsing the Typer command definitions, ensuring documentation stays in sync with implementation.

## Router Implementation

### R-11: Router Abstraction

The router is implemented in `src/retrovue/cli/router.py` as a thin abstraction over Typer's `add_typer()` mechanism.

### R-12: Router Interface

The router MUST provide:
- `register(name, command_group, *, help_text, doc_path)` - Register a command group
- `get_registered_groups()` - Get all registered groups with metadata
- `list_registered_groups()` - List registered group names

### R-13: Global Router Instance

The router MUST use a singleton pattern via `get_router(root_app)` to ensure single registration point.

## Testing Requirements

### R-14: Registration Test Coverage

Tests MUST verify:
- All command groups are registered
- No duplicate registrations occur
- Documentation paths are correctly mapped
- Help text is present for all groups

### R-15: Command Discovery

Tests MUST verify that registered commands are discoverable via `retrovue --help` and individual command group help.

## Validation & Invariants

- **R-V1**: All command groups in `src/retrovue/cli/commands/` are registered in `main.py`
- **R-V2**: Every registered command group has a corresponding `docs/cli/<name>.md` file
- **R-V3**: Documentation paths in router match actual file locations
- **R-V4**: No command group registration occurs outside `main.py`

## See also

- [CLI Reference](../../cli/README.md) - Command syntax documentation
- [Contracts README](README.md) - Behavioral contract standards
- [CLI Change Policy](CLI_CHANGE_POLICY.md) - Governance rules

