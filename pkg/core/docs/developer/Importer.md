# Importer Development Guide

_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Plugin Authoring](PluginAuthoring.md) • [Registry API](RegistryAPI.md) • [Testing Plugins](TestingPlugins.md)_

## Audience

**I am extending RetroVue with a new importer plugin.**

This guide explains how to implement and register a new **Importer** in RetroVue. An Importer is responsible for discovering and retrieving media/metadata from an external system (e.g. Plex, Jellyfin, filesystem) and making that content available to RetroVue's ingest pipeline.

Importers are loaded dynamically at runtime, and operators configure them through the `retrovue source` CLI commands.

---

## Concepts

### Two-URI Model

During ingest, RetroVue persists two URIs on each Asset:
- **source_uri**: Source-native reference (e.g., `plex://12345` or `file:///...`) provided by the importer.
- **canonical_uri**: Local `file://` URI used by enrichers and playout, derived by the importer via `resolve_local_uri(...)` and collection `PathMapping`.

Your importer must:
- Return a stable `source_uri` as part of discovery (via `DiscoveredItem.path_uri` or item dict `path_uri`).
- Implement `resolve_local_uri(item, *, collection, path_mappings)` to translate to a local file URI suitable for enrichment.

### Importer Type (code)

An _importer type_ is a Python implementation that knows how to talk to a specific upstream system.

**Examples:**

- `plex`
- `filesystem`
- `jellyfin`

An importer type lives in code under `adapters/importers/` and is discovered at runtime. Importer types are **not** stored in the database.

Each importer type:

- declares what configuration it needs (e.g. `base_url`, `api_key`, `token`, `verify_ssl`, etc.),
- exposes discovery / ingest methods,
- and registers itself with the Source Registry at startup.

### Source (persistent instance)

A _Source_ is an operator-configured instance of an importer type.

**Example:**  
`"Living Room Plex"` might be a Source of type `plex` with:

- a base URL,
- an auth token,
- SSL policy,
- and sync policy.

This configuration is stored in the database and is assigned a stable `source_id`. Operators refer to Sources by that ID in all CLI commands:

```bash
retrovue source add --type plex --name "Living Room Plex" \
  --base-url http://10.0.0.5:32400 \
  --token abc123

retrovue source discover plex-5063d926
retrovue source ingest plex-5063d926
```

**So:**

- **Importer Type** = code you ship.
- **Source** = persisted instance of that code with real credentials.

---

## Responsibilities of an Importer

An Importer is responsible for:

### Connection & Auth

- Know how to authenticate to the upstream system (token, API key, etc.).
- Validate that connectivity works using the provided config for a Source.

### Discovery

- Enumerate "collections" / libraries / buckets of content the operator might want to ingest.
- **Example:** Plex libraries, filesystem folders, Jellyfin libraries.

This powers commands like:

```bash
retrovue source discover <source_id>
retrovue collection list --source <source_id>
```

### Asset Enumeration

- Given a collection, list the individual media assets (movies, episodes, specials).
- Normalize them into RetroVue's ingest model (unified structure instead of upstream-specific shapes).

### Stable Identification

- Provide stable IDs / references for collections and assets so ingest can be incremental.
- **Example:** external library ID, path mapping, media GUID, checksum.

### Safety & Isolation

- MUST support test/preview modes (`--dry-run`, `test-db` modes).
- MUST NOT mutate production content on discovery.
- MUST surface errors in a structured way (raise importer-specific exceptions instead of crashing the process).

---

## What Importers Are NOT Allowed To Do

Importers are **not allowed** to:

- **Enrich or decorate content** with editorial/branding metadata (that's the Enricher's job).
- **Decide playout or scheduling policy**.
- **Write outside the ingest transaction boundary**.

---

## Importer Interface

Each importer type must implement a well-defined interface so orchestration code (and the CLI) can drive it.

Below is a representative shape. Names may differ in code, but the contract is the same.

```python
class BaseImporter:
    # A short, unique string ID for this importer type.
    # This is what operators pass to --type in `retrovue source add`.
    type_id = "plex"

    # Human-friendly label for help output / diagnostics.
    display_name = "Plex Media Server"

    # Machine-readable parameter spec used by the CLI.
    # This is how `retrovue source add --type plex --help`
    # knows what flags are required or optional.
    @classmethod
    def param_spec(cls) -> dict:
        return {
            "required": {
                "--base-url": "Base URL of the Plex server",
                "--token": "X-Plex-Token for API access"
            },
            "optional": {
                "--verify-ssl": "Require valid TLS certs (default: true)"
            }
        }

    # Called with a Source's persisted config (from the DB).
    # Should raise a clear, typed error if auth / connectivity fails.
    def validate_connection(self, source_config) -> None:
        ...

    # Return a list of "collections" (libraries, folders, etc.)
    # that this Source can ingest.
    def list_collections(self, source_config) -> list["CollectionInfo"]:
        ...

    # Return assets (episodes, movies, etc.) for a given collection.
    # Each asset MUST be normalized into RetroVue's ingest model.
    def fetch_assets_for_collection(
        self,
        source_config,
        collection_ref,
        *,
        filter_title=None,
        filter_season=None,
        filter_episode=None,
    ) -> list["DiscoveredAsset"]:
        ...
```

**Notes:**

- `param_spec()` is critical. The CLI uses it to dynamically render help and to validate flags at source add time.
- `list_collections()` feeds collection discovery and UI/CLI listing.
- `fetch_assets_for_collection()` feeds ingest. It must be able to support surgical ingest (just one show, just a season, just an episode) because the CLI supports targeted ingest on collection ingest.
- If your importer can't express this level of filtering, that limitation needs to be explicit in its help so the operator isn't lied to.

---

## Registration

Importer types must be registered so RetroVue can find them at runtime.

At startup, RetroVue scans `adapters/importers/` for modules that identify themselves as importers and registers them with the Source Registry.

That registry:

- maps `type_id` → importer class
- exposes all importer types to the CLI via `retrovue source list-types`
- validates parameters for `retrovue source add --type <type>`

A typical registration pattern looks like:

```python
from retrovue.registry import SOURCE_REGISTRY

class PlexImporter(BaseImporter):
    type_id = "plex"
    display_name = "Plex Media Server"
    ...

SOURCE_REGISTRY.register(PlexImporter)
```

**Key rules:**

- `type_id` must be unique across all importer types.
- If two importer types claim the same `type_id`, registration MUST fail fast and loudly.
- If an importer type is removed from the codebase, any Source rows in the DB that reference that `type_id` are still kept, but will be marked unavailable at runtime. Those sources cannot ingest until the importer code comes back.
- That "unavailable" behavior is enforced in the CLI contract for source commands — the CLI must refuse to run discover/ingest against a Source whose importer type is not currently loaded, and must explain why.

---

## Source Lifecycle (Operator View)

Once your importer type is registered, operators interact with it entirely through `retrovue source ....`

### Create a Source

```bash
retrovue source add \
  --type plex \
  --name "Living Room Plex" \
  --base-url http://10.0.0.5:32400 \
  --token abc123
```

- CLI calls your importer's `param_spec()` to know what flags are required.
- CLI validates that all required params are present.
- RetroVue persists a new Source row in the DB with:
  - `source_id` (e.g. `plex-5063d926`)
  - `type_id = "plex"`
  - `config` (URL, token, etc.)
- Your importer can be asked to `validate_connection(...)` at add-time.

### Discover collections

```bash
retrovue source discover plex-5063d926
```

- System loads your importer by `type_id`.
- Passes the persisted config.
- Calls `list_collections()`.
- RetroVue records or updates Collection objects in its own DB.

### Ingest content

```bash
retrovue source ingest plex-5063d926
```

- System loops over all sync-enabled collections for that Source.
- For each collection, it calls `fetch_assets_for_collection()`.
- Those assets become ingest candidates and flow through Enrichers.

### Targeted ingest (collection-level)

```bash
retrovue collection ingest "TV Shows" \
  --title "The Big Bang Theory" \
  --season 1 \
  --episode 6
```

- Orchestrator uses the Source/Importer behind that Collection.
- Calls `fetch_assets_for_collection()` with the narrowed filters.
- Only the requested subset is ingested.

**Your importer must handle being called in both bulk mode and surgical mode.**

---

## Error Handling & Safety

Your importer must behave like infrastructure, not like a script.

**Rules you must follow:**

### You MUST raise typed, importer-specific errors for:

- bad credentials,
- unreachable upstream,
- malformed responses,
- "collection not found," etc.

**Do not** `sys.exit`, **do not** print and continue. **Raise.** The orchestration layer / CLI is responsible for converting that into:

- exit code 1,
- clean human output,
- stable JSON if `--json` was passed.

### You MUST support dry-run modes.

When the operator supplies `--dry-run` to an ingest or wipe-like command, RetroVue will still invoke your importer to resolve what it would ingest. You MUST NOT mutate state in the upstream system or in RetroVue's DB during dry-run.

### You MUST be deterministic for the same config and same upstream state.

Ingest and discovery need to be repeatable so we can diff runs, isolate partial failures, and reconcile.

### You MUST NOT persist outside the controlled ingest transaction.

Importers feed ingest. They don't write directly to RetroVue's final authoritative tables. Persistence happens inside the Ingest Service / Unit of Work layer, not inside your importer class.

---

## Versioning / Availability

Importers can come and go at runtime.

If your importer file is removed from the codebase, RetroVue will no longer register that `type_id`.

Any existing Sources in the DB that referenced your importer will:

- still exist,
- still be listed in `retrovue source list`,
- but will appear as unavailable.

Commands like `retrovue source ingest <source_id>` MUST refuse to run for an unavailable source and MUST produce an explanatory error telling the operator the implementation is missing.

You are not responsible for that UX inside the importer. That's enforced in the Source command contract. But: you are responsible for giving the registry enough metadata (`type_id`, friendly name) that the CLI can report something meaningful.

---

## Checklist for Contributing a New Importer

Before you send a PR for a new importer:

### Implements required interface

- [ ] `type_id`
- [ ] `param_spec()`
- [ ] `list_collections()`
- [ ] `fetch_assets_for_collection()`
- [ ] sane auth / validation

### Registers with the Source Registry

- [ ] unique `type_id`
- [ ] no collisions

### Supports filtered ingest

- [ ] Able to narrow to one title, one season, one episode if the upstream supports it.
- [ ] If unsupported, your importer must make that explicit in its param spec / help so the operator is not lied to.

### Raises typed errors, does not exit()

- [ ] We centralize exit codes in the CLI layer, not in your importer.

### Has tests

- [ ] Discovery (collections returned from `list_collections()`)
- [ ] Asset fetch behavior
- [ ] Invalid auth / bad config path
- [ ] Dry-run safety (no mutation)
- [ ] Deterministic output for same input

See [TestingPlugins.md](TestingPlugins.md) for expectations on importer tests, and integration smoke tests across Source → Collection → Enricher → Producer.

---

## Summary

- **Importer Type** = runtime plugin that knows how to talk to a content source.
- **Source** = persisted instance of that importer type with real credentials and operator intent.
- **Runtime registry** wires importer types into the CLI (`source list-types`, `source add`, etc.).
- **Your importer** feeds discovery and ingest, but does not own persistence, policy, playout, or enrichment.

If your importer follows this contract, RetroVue can safely treat your external world like first-class internal inventory.
