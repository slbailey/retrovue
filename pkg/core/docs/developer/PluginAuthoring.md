_Related: [Architecture overview](../architecture/ArchitectureOverview.md) • [Runtime: Channel manager](../runtime/ChannelManager.md) • [Operator CLI](../cli/README.md)_

# Developer guide — Plugin authoring

## Purpose

Define what a developer must implement to add a new Source importer, a new Enricher, or a new Producer. The goal is to allow extension without modifying RetroVue core code paths.

## Importer plugins (Source types)

An importer plugin represents a Source type (e.g. plex, filesystem, jellyfin).

The plugin must register itself with the Source Registry using a unique type key.

The plugin must expose:

- A parameter spec used for:
  - validating `retrovue source add`
  - generating `retrovue source add --type <type> --help`
- `list_collections(source_config)`
  - Return the collections (libraries / folders) available in that source. Each collection must include:
    - stable identifier / name
    - display label
    - source_path or equivalent remote path info
- `discover()` method that returns DiscoveredItem objects
  - Returns list of DiscoveredItem objects with path_uri, provider_key, size, last_modified
  - The ingest orchestrator handles duplicate detection automatically based on canonical key

The importer must NOT decide which collections sync. RetroVue handles that via `sync_enabled`.

The importer must NOT assume filesystem paths are directly readable. RetroVue will provide the resolved `local_path` mapping per collection.

### Discovered items MUST be handler-ready

Importers MUST return discovered items that can be turned into a handler payload without additional guessing in the ingest service.

A discovered item SHOULD provide:

- `path_uri` (source-native: e.g. `plex://39593` or real path)
- `editorial` (light, source-derived: title, year, series, season/episode, library/bucket)
- `sidecar` (optional) — when the source already exposes structured metadata
- `probed` is OPTIONAL for importers; enrichers MAY attach it later

Importers that subclass the base importer SHOULD implement or use a helper like:
`DiscoveredItem.to_ingest_payload(importer_name, asset_type)` which returns the dict expected by
`retrovue.usecases.metadata_handler.handle_ingest(...)`.

Note on domains: importers and enrichers must add to the correct metadata domain (editorial, probed, station_ops) rather than overwriting existing values. When a domain already exists, perform a deep merge (object/object recursive, last-writer-wins on scalars). Do not replace the `sidecar` unless explicitly extending it.

## Enricher plugins

An enricher is always called "enricher". We do not use alternate terms.

The plugin must register itself with the Enricher Registry using a unique type key.

The plugin must declare:

- `scope = ingest` or `playout`
- parameter spec for CLI (`retrovue enricher add --type <type> --help`)
- `apply(input_obj) -> output_obj`
  - `scope=ingest`: input is DiscoveredItem, output is DiscoveredItem
  - `scope=playout`: input is playout plan, output is playout plan

Enrichers must be orderable. RetroVue will call multiple enrichers in ascending priority.

Enrichers must fail soft. Throwing an error should not crash ingest or playout; RetroVue will continue with the most recent valid object and log the failure.

## Producer plugins

A producer generates a base playout plan for a Channel.

The plugin must register itself with the Producer Registry using a unique type key.

The plugin must expose:

- a parameter spec for CLI (`retrovue producer add --type <type> --help`)
- a `build_playout_plan(now, channel_config, schedule_context)` function that returns a playout plan:
  - ordered segments
  - timing / offsets
  - transitions

The producer does not apply channel branding, fades, lower-thirds, etc. Those are handled by playout-scope enrichers.

## Registry pattern

RetroVue uses registry classes for all modular surfaces:

- Source Registry (importers)
- Enricher Registry (ingest+playout enrichers)
- Producer Registry (channel output generators)

Each registry supports:

- `list-types` to see available plugin types
- `add` / `update` / `remove` to configure instances
- `list` to view configured instances

Each registry also exposes type-specific help.

Example: `retrovue source add --type plex --help` prints the parameter contract defined by the plex importer plugin.

## CLI contract for plugin authors

Every plugin type MUST provide a machine-readable parameter spec so the CLI can:

- validate required fields on add
- render type-specific help on `--help`

If a plugin needs new config fields later (for example, `verify-ssl=false`), the plugin updates its own parameter spec. The CLI help output updates automatically without core changes.

## Safety and operator expectations

Importer plugins must not automatically ingest content on registration. Ingest only happens when an operator runs `retrovue source <source_id> ingest` or `retrovue collection <collection_id> ingest`.

Importer plugins must expose all collections they can see, including collections the operator may choose not to sync.

Importer plugins must not implement their own duplicate detection logic. The ingest orchestrator handles duplicate detection automatically based on asset URI, preventing both database duplication and unnecessary review queue entries.

Importer plugins must not implement their own collection deletion logic. The system provides `retrovue collection delete` for soft deletion and `retrovue collection wipe` for complete cleanup.

Enricher plugins must not assume they run first or run alone.

Producer plugins must never launch ffmpeg directly. The ChannelManager is responsible for ffmpeg lifecycle.

## Future expansion notes

Backfill / rescan of existing assets after adding a new ingest enricher is an operator-triggered workflow. It is not automatic.

Channel-level playout enrichers are the default model. Future producers may negotiate optional opt-outs.

## See also

- [Architecture overview](../architecture/ArchitectureOverview.md) - System architecture and design
- [Runtime: Channel manager](../runtime/ChannelManager.md) - Channel runtime operations
- [Operator CLI](../cli/README.md) - Operational procedures
- [Developer: Registry API](RegistryAPI.md) - Plugin registration system
- [Developer: Testing plugins](TestingPlugins.md) - Plugin testing guide
