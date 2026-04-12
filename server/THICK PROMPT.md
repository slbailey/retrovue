You are working on RetroVue Core (the orchestration component that sits beside AIR).

RetroVue Core presents as a continuous multi-channel retro TV network:
- Channels are persistent logical entities.
- Viewers can tune in at any time and see what is “on right now”.
- Core does NOT burn CPU 24/7: it only spins up playout resources while viewers exist.

Core owns: persistence, ingest, scheduling horizons (EPG + playlog), playout plan generation, runtime orchestration, and operator tooling.
AIR is a spawned playout engine; Core supervises it per-channel at runtime.

────────────────────────
SYSTEM BOUNDARIES (HARD)
────────────────────────
Core IS responsible for:
- Maintaining a persistent definition of each Channel.
- Building and advancing scheduling horizons (EPG horizon ~days, Playlog horizon ~hours).
- Generating a playout plan at “now”.
- Decorating playout plans via playout enrichers.
- Launching and supervising ffmpeg/AIR to serve real bytes to viewers.
- Writing an as-run log.

Core is NOT responsible for:
- Permanent 24/7 transcoding (no always-on ffmpeg).
- Scraping/mounting arbitrary storage automatically; operator provides valid local_path mappings per Collection.
- Automatic ingest without operator intent.
- Hardcoded metadata rules; metadata is handled by pluggable ingest enrichers.
- Directly embedding external systems (Plex/Jellyfin/etc.) in core code; external integration is Importer-only.

Security / safety boundaries:
- Plugins register with registries but cannot bypass core orchestration.
- Enrichers transform objects and return updated objects; they do not persist.
- Producer plugins generate plans but may NOT launch ffmpeg themselves.

────────────────────────
MAJOR LAYERS / PIPELINES
────────────────────────
1) Ingest pipeline (catalog build)
   Source (Importer plugin) → Collection → DiscoveredItem → Asset
   - Operator registers Sources and discovers Collections.
   - Ingest runs only via explicit operator action.
   - Importer returns DiscoveredItem objects.
   - Core converts DiscoveredItem → Asset records and persists them.
   - Ingest-scope enrichers add metadata (e.g., filename parsing, TVDB enrichment, LLM synopsis).

2) Scheduling system (future truth)
   - Builds a rolling future plan per Channel:
     - EPG horizon: coarse “what’s on”
     - Playlog horizon: fine-grained segments with timestamps (ads/bumper/segments)
   - Timeline advances with wall clock.

3) Playout plan generation (now)
   Viewer tunes a Channel → Core asks “what should be airing right now?”
   Producer builds a base playout plan for the current moment:
   - ordered segments
   - offsets (join mid-show)
   - transitions
   - any needed filtergraph directives
   Playout enrichers decorate presentation (branding bug, lower-third, emergency crawl, VHS aesthetic).
   Enrichers do NOT change WHAT content airs; they change HOW it is presented.

4) Runtime orchestration (serving bytes)
   ChannelManager owns runtime playout for a Channel:
   - First viewer in: build plan and start playout
   - Last viewer out: stop playout
   - Channel’s logical schedule continues even when not watched

5) Operator surface (CLI + contracts)
   Operators manage Sources, Collections, Enrichers, Producers, Channels via the `retrovue` CLI.
   Contracts define the binding operator-visible behavior; code must conform to contracts.

────────────────────────
FIRST-CLASS CITIZENS (DOMAIN)
────────────────────────
Core’s primary operator-managed and runtime-managed “nouns” include:

Catalog / ingest:
- Source: configured external system endpoint (filesystem, Plex via importer plugin, etc.)
- Collection: ingest scope within a Source (operator enables/disables ingest per collection)
- DiscoveredItem: importer output that becomes catalog entities
- Asset: persisted playable media entity in the RetroVue catalog
- ProviderRef: importer-managed linkage to external identifiers (core stores normalized refs only)

Scheduling:
- Channel: persistent logical network channel with grid configuration:
  - grid_block_minutes
  - block_start_offsets_minutes
  - programming_day_start
- SchedulePlan: template for future scheduling
- Zone: named time windows within the programming day that hold SchedulableAssets directly
- SchedulableAssets: Programs, Assets, VirtualAssets, SyntheticAssets placed in Zones
- Program: catalog schedulable entity (series/movie/block/composite), expands via asset_chain and play_mode
- ScheduleDay: resolved immutable daily schedule generated from SchedulePlan + policies
- EPGGeneration: guide data derived from ScheduleDay (EPG truth is ScheduleDay)

Execution-level playout truth:
- PlaylogEvent / BroadcastPlaylogEvent: lowest runtime layer describing exactly what plays and when

Playout decoration:
- Enricher (ingest or playout type)
  - ingest enrichers: enrich catalog data
  - playout enrichers: decorate playout plans/presentation

Playout plan generation:
- Producer: generates a base playout plan from schedule/playlog “now”
  - Producers do NOT launch ffmpeg; ChannelManager owns playout process lifecycle.

────────────────────────
ZONES + GRID CONTRACTS (SCHEDULING INVARIANTS)
────────────────────────
The Zones model is contract-driven. Key invariants:
- All scheduled starts align to Channel grid boundaries (grid_block_minutes + block_start_offsets_minutes).
- Zones expand SchedulableAssets across their window until full; underfill becomes avails.
- Zones soft-start after in-flight content ends, snapping to the next grid boundary (no mid-program interruption).
- Zones end at their declared end time (no auto-extend); underfill becomes avails.
- Longform is never cut; it consumes additional grid blocks if needed.
- Carry-in across programming-day boundary is supported; Day+1 starts with carry-in then snaps to grid.
- EPG reflects resolved ScheduleDay start times (not zone declarations).

────────────────────────
RUNTIME ORCHESTRATION MODEL
────────────────────────
Process hierarchy and responsibilities:
- ProgramDirector: top-level supervisor; spawns a ChannelManager when one doesn’t exist for a requested channel.
- ChannelManager: long-running runtime serving MPEG-TS streams for all channels via HTTP.
  - Spawns AIR (playout engine) to play video.
  - Owns AIR lifecycle per channel.
  - Must NOT spawn ProgramDirector or the main retrovue process.

Core runtime contracts include:
- On-demand playout: first viewer starts playout; last viewer stops playout (no wasted resources idle).
- Shared playout: multiple viewers on the same channel share one playout instance (no restart per viewer).
- Schedule-based selection: content determined by schedule + current time (if no active item, 503).
- Asset validation before playout: missing asset file returns 500 and does not start playout.
- Channel isolation: per-channel errors do not crash the runtime.

────────────────────────
HTTP SERVING SURFACE (VIEWERS)
────────────────────────
ProgramDirector exposes the HTTP interface (single server, post–PD/CM collapse):

- GET /channels
  - Returns JSON channel list: `{"channels": [{"id": "...", "name": "..."}, ...]}`.

- GET /channel/{id}.ts
  - Returns a continuous MPEG-TS stream for that channel.
  - Errors:
    - 404: channel not found (no schedule file)
    - 500: schedule error / invalid asset
    - 503: schedule gap (no active schedule item)

This viewer surface is HTTP MPEG-TS (not gRPC).

────────────────────────
OPERATOR SURFACE (CLI + CONTRACTS)
────────────────────────
All CLI commands follow:
  retrovue <noun> <verb> [options]

Contracts are the binding authority:
- Contracts define WHAT must be true (B-# behavior rules, D-# data rules).
- Implementation must conform; breaking behavior requires contract update.
- Commands support global flags such as:
  --dry-run, --force, --json, --test-db (where applicable)
- Destructive operations require confirmation unless --force and must honor ProductionSafety rules.

Contract-first development rules:
- Every command has exactly two test files:
  - one CLI contract test
  - one data contract test
- Traceability is mandatory: each rule maps to tests.

────────────────────────
TOOLSET / STACK EXPECTATIONS
────────────────────────
Core is the Python control plane and orchestration layer that:
- Persists domain entities to Postgres (SQLAlchemy + Alembic migrations).
- Runs CLI commands (retrovue CLI) aligned to contracts.
- Runs runtime services (ProgramDirector, ChannelManager).
- Supervises playout processes (AIR + ffmpeg execution plans).
- Uses a plugin system:
  - Importers (Source types) are the ONLY gateway to external systems.
  - Enrichers (ingest/playout) are pluggable transformers.
  - Producers are pluggable plan generators.

────────────────────────
HOW TO THINK ABOUT CHANGES (NO GUESSING)
────────────────────────
When asked “add X to Core”:
1) Decide which layer it belongs to:
   ingest, scheduling, playout plan generation, runtime orchestration, operator CLI/contracts, plugins
2) Use only first-class citizens defined above; do not invent parallel nouns.
3) Enforce scheduling and runtime invariants (grid alignment, carry-in, no longform cuts, on-demand playout, shared playout).
4) If behavior or CLI changes: update contracts first, then tests, then implementation.
5) Never add direct Plex/Jellyfin logic into core; external systems are Importer-only.

ACKNOWLEDGEMENT REQUIRED:
Confirm you understand Core as the multi-channel orchestration system with persistent channels, ingest + scheduling horizons, plan generation at “now”, playout enrichers, and runtime ChannelManager that serves MPEG-TS over HTTP and spawns AIR for playout.
Do not proceed until this model is accepted.
