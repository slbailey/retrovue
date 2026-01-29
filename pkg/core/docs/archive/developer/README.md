> **⚠️ Historical document.** Superseded by: [Core documentation](../../README.md), [developer/](../../developer/).

# RetroVue Developer Documentation

This directory is for **contributors and plugin authors** working on RetroVue's internals:

- ingest and enrichment,
- channel/planning/playout,
- scheduling and broadcast behavior,
- runtime extension via plugins.

If you're operating RetroVue (running commands, managing sources, scheduling channels), see the operator-oriented CLI contract in `../contracts/resources/README.md`.  
If you're extending or modifying RetroVue, start here.

---

## How to read this directory

### 1. System Architecture / Philosophy

#### `architecture.md`

End-to-end view of how RetroVue is structured.  
Explains the layering (Presentation → Application → Domain → Infrastructure), how services like `IngestService` and `SourceService` coordinate work, how Importers and Enrichers live in `adapters/`, and how data flows from an external source into RetroVue and then to playout. It also documents the Unit of Work transactional model used in both API and CLI code paths.

Read this first if you're new.

#### `abstract-design-principles.md`

This is the architectural gatekeeper.  
It defines the patterns you are allowed to create and extend: **Adapter**, **Importer**, **Enricher**, **Unit of Work**, **Orchestrator**, **Service / Capability Provider**, and **Authority**.  
For each pattern it spells out what it may and may not do, and gives "violation smells" to catch architectural debt early.

Read this before adding or refactoring any component. If your proposed code doesn’t fit one of these patterns, either update this doc first or don’t merge.

#### `development-roadmap.md`

What we're building next and why.  
Captures completed phases (ingest, MPEG-TS streaming) and in-progress work (multi-channel, scheduling, commercial insertion, overlays/branding). This is where priorities live.

Read this to understand what's actively in flight or about to land.

---

### 2. Core Runtime Data Model

#### `database-schema.md`

Authoritative description of RetroVue’s persistent state.  
Covers the media-first schema (physical media → logical content → scheduling → playout → play log) and documents key tables like `plex_servers`, `libraries`, `media_files`, `content_items`, `channels`, `schedule_blocks`, and `schedule_instances`. It also defines the schema-first workflow: one canonical SQL file, deterministic rebuild, no ad hoc migrations.

Importers ultimately write into this world. Enrichers annotate data that becomes part of it. Schedulers and ChannelManager depend on it. If you're touching ingest, scheduling, or playout, you will need this.

---

### 3. Plugin Surfaces and Runtime Registry

RetroVue is intentionally modular. You can add new behavior without editing core by providing plugins and registering them.

#### `Importer.md`

Detailed guide for implementing custom importers.  
Covers the `ImporterInterface` protocol, configuration schema definition, discovery and ingestion patterns, error handling, and testing requirements. This is the authoritative reference for importer implementation details and method signatures.

Read this when implementing a new importer or modifying existing importer behavior.

#### `extending-retrovue.md`

High-level guide to extending RetroVue through **Importers** and **Enrichers**.  
Explains:

- what an Importer is (discovers content from Plex, Jellyfin, filesystem, etc.),
- what a DiscoveredItem looks like,
- how to build a custom importer (`discover()` that returns DiscoveredItem objects),
- how to build a custom enricher (`enrich()` that augments those items),
- how to register your plugin with the runtime registry (e.g. `SOURCES["jellyfin"] = JellyfinImporter`).

Start here if you’re adding a new integration.

#### `PluginAuthoring.md`

This is the contract for plugin authors.  
For each plugin class, it defines:

- what you MUST expose (parameter spec, required call signatures),
- how Importer plugins surface `list_collections(...)` and `fetch_assets_for_collection(...)`,
- how Enricher plugins declare their `scope` (`ingest` vs `playout`) and implement `apply(...)`,
- how Producer plugins generate playout plans but are not allowed to apply overlays/branding (that’s the playout enricher’s job).

Read this before you submit a plugin. If your plugin doesn’t satisfy this doc, it’s out of spec.

#### `RegistryAPI.md`

Defines the runtime registry model used by RetroVue.  
There are three registries in play:

- Source Registry (importer plugins),
- Enricher Registry (ingest + playout enrichers),
- Producer Registry (producer plugins).

Each registry:

- tracks what plugin types are available at runtime,
- exposes parameter specs for `--help` / validation,
- can create configured instances,
- and supports CLI surfaces like `list-types`, `add`, `list`, `update`, `remove`.  
  For example, `retrovue enricher add --type <type> --help` asks the Enricher Registry for that type’s param spec, and `retrovue source list-types` asks the Source Registry what importer types exist.

This doc is about how plugins become visible and operable to the CLI. Update this if you change how registration or discovery works.

#### `TestingPlugins.md`

How to validate a plugin before it lands.  
Covers:

- Importer testing (`list_collections`, `fetch_assets_for_collection`, CLI help rendering),
- Enricher testing (idempotent transform, fail-soft behavior, no persistence),
- Producer testing (generate a playout plan with timing, do not launch ffmpeg, do not apply branding),
- Full integration smoke test across Source → Collection → Enricher → Producer → Channel, including ChannelManager orchestration.

This is required reading before merging a new importer/enricher/producer into main.

---

### 4. Developer-Facing Interfaces

#### `api-reference.md`

Reference for programmatic APIs used in importer/enricher work:

- Base `Importer` protocol and the `DiscoveredItem` dataclass (path, provider_key, labels, last_modified, size, hash).
- Base `Enricher` protocol (takes a `DiscoveredItem`, returns an enriched `DiscoveredItem`).
- Registry functions like `list_importers`, `get_importer`, `list_enrichers`, `get_enricher`, and how registration is done (e.g. `SOURCES["custom"] = CustomImporter`).  
  It also includes examples of built-ins like `FilesystemImporter`, `PlexImporter`, and an API-backed metadata enricher.

Use this when you're writing code and want to know actual method signatures / expected structures.

#### `cli-reference.md`

Developer-facing CLI walkthrough.  
Documents how Retrovue is actually operated in practice: content ingestion, asset promotion into the broadcast catalog, channel definition, schedule assignment, and test/debug commands like `retrovue test masterclock`. It shows how pieces like assets → catalog → channel → schedule all line up into “real TV.”

Read this to understand how your code will be invoked by real operators and orchestrators.

---

## How to add new docs to this directory

When you add documentation under `developer/`, follow these rules so we don’t create drift:

1. **Pick the right category above**

   - Architecture / Principles
   - Data Model
   - Plugin Surfaces & Registry
   - Developer-Facing Interfaces  
     If your new doc doesn’t fit one of those, stop and decide whether you’re inventing a new surface without writing down its contract.

2. **State the audience at the top of the file**  
   Every doc here implicitly answers one of:

   - “I am extending RetroVue with a new plugin.”
   - “I am modifying core orchestration / scheduling / playout.”
   - “I am working on persistence / schema / transactional guarantees.”
     If your doc doesn’t say who it’s for, new contributors will guess wrong and misuse it.

3. **Declare responsibilities and prohibitions**  
   Match the style in `abstract-design-principles.md`, `PluginAuthoring.md`, and `TestingPlugins.md`. Each doc should say:

   - what the component is allowed to do,
   - what it is NOT allowed to do,
   - how we test that.

   If you don't write the “not allowed” side, other people _will_ fill the gap with convenience hacks.

4. **Do not silently introduce a new top-level runtime concept**  
   If you invent a new plugin class (for example, “Transcoder”) or a new registry, you must:

   - document its lifecycle (how it's discovered, configured, attached),
   - define its test requirements,
   - update both the Registry API doc and Plugin Authoring doc.

   Otherwise, it’s not a supported surface.

5. **If you change runtime behavior, update both the interface doc and the test doc**  
   Example: if you change how `Producer` is supposed to build playout plans, you must update:

   - `PluginAuthoring.md` (what authors must do),
   - `TestingPlugins.md` (how we prove it's correct).

   Those two must never drift.

---

## TL;DR

- This directory is not “misc dev notes.”  
  It is the spec for how to extend, test, and safely evolve Retrovue.

- `abstract-design-principles.md` is the guardrail for architecture.
- `architecture.md` and `database-schema.md` describe what already exists.
- `Importer.md`, `PluginAuthoring.md`, `extending-retrovue.md`, `RegistryAPI.md`, and `TestingPlugins.md` describe how to add new importers, enrichers, and producers and get them accepted.
- `api-reference.md` and `cli-reference.md` describe the concrete surfaces you code against and the way operators will actually call your work.

If you add a new kind of module or registry, you must update these docs in lockstep — otherwise you're creating behavior that the rest of the system is not allowed to trust.
