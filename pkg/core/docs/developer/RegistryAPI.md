_Related: [Developer: Plugin authoring](PluginAuthoring.md) • [Operator CLI](../cli/README.md) • [Domain: Enricher](../domain/Enricher.md)_

# Registry API

## Purpose

Describe how plugin types are registered so that operators can see and configure them via the CLI without touching core code.

## Core model / scope

RetroVue has three main registries:

- Source Registry (importer plugins)
- Enricher Registry (ingest + playout enrichers)
- Producer Registry (Producer plugins)

Each registry:

- Knows what plugin types exist.
- Knows how to create a configured instance of that plugin type.
- Exposes help/parameter specs to the CLI.

## Contract / interface

Each registry supports:

- `list-types`
- `add`
- `update`
- `remove`
- `list`
- type-specific `--help` output used by the CLI

Each plugin type must provide:

- A unique type identifier.
- A parameter spec with required/optional fields.
- A callable entry point (`apply`, `build_playout_plan`, etc.), depending on the plugin class.

## Execution model

When an operator runs:

- `retrovue enricher add --type <type> --help`  
  The CLI asks the Enricher Registry for that type's parameter spec and prints it. The CLI does not hardcode per-type flags.
- `retrovue source list-types`  
  The CLI asks the Source Registry for all registered importer types.

## Failure / fallback behavior

- If a registry cannot instantiate a plugin because required config is missing, the CLI should fail validation before saving anything.
- Removing a plugin instance should warn about which Channels or Collections reference it.

## Naming rules

- "Registry" always means the in-process map of known plugin types and configured instances.
- "Plugin" means code provided outside core that registers itself into a registry.

See also:

- [Plugin authoring](PluginAuthoring.md)
- [CLI contract](../contracts/resources/README.md)
