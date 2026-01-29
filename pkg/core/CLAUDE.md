You are working on RetroVue Core.

RetroVue Core is the Python control plane and orchestration system for the Retro IPTV Simulation Project.
Core owns editorial intent, persistence, scheduling horizons, playout plan generation, and runtime orchestration.
AIR is a separate C++ playout engine; Core supervises and spawns AIR per channel.

────────────────────────
HOW TO RUN PYTHON (MANDATORY)
────────────────────────
Use the Core virtualenv only. Do not use system python, system pytest, or any other interpreter for Core code.

Activate the venv (do this first, in every shell where you run Core Python):
  From repo root:    source pkg/core/.venv/bin/activate
  From pkg/core/:    source .venv/bin/activate

Then, with the venv active:
  Install deps:      pip install -r pkg/core/requirements.txt   (from repo root)
  Run all tests:    pytest pkg/core/tests/
  Run one file:     pytest pkg/core/tests/path/to/test_file.py -vv
  Lint:             ruff check pkg/core/src/   ;  mypy pkg/core/src/
  CLI:              retrovue <noun> <verb>     (e.g. retrovue channel list)

Database (tests and runtime often need Postgres):
  Migrations:       cd pkg/core && alembic upgrade head

Do NOT:
- Run `python`, `pytest`, or `pip` for Core without activating pkg/core/.venv first.
- Use system python or a different venv for Core code.

────────────────────────
BOUNDARIES
────────────────────────
Core IS responsible for:
- Persistent Channel definitions
- Ingest (Importer → Asset catalog)
- Scheduling (EPG horizon = days, Playlog horizon = hours)
- Playout plan generation at “now”
- Playout enrichers (presentation-only)
- Runtime orchestration and supervision
- As-run logging
- Operator CLI + contracts

Core is NOT responsible for:
- Continuous 24/7 transcoding
- Direct video decoding/encoding
- Editorial playback correctness (AIR enforces runtime correctness)
- Embedding Plex/Jellyfin logic (Importer-only)

────────────────────────
CORE PIPELINES
────────────────────────
1) Ingest
   Importer → DiscoveredItem → Asset (persisted)
   Enrichers add metadata but do not persist.

2) Scheduling
   SchedulePlan → ScheduleDay → EPG
   Timeline advances with wall clock.

3) Playout plan generation (now)
   Producer builds ordered segments + offsets.
   Playout enrichers decorate HOW content appears, not WHAT airs.

4) Runtime orchestration
   First viewer starts playout.
   Last viewer stops playout.
   Channel schedule continues regardless of viewers.

────────────────────────
FIRST-CLASS DOMAIN OBJECTS
────────────────────────
Catalog:
- Source, Collection, DiscoveredItem, Asset, ProviderRef

Scheduling:
- Channel (grid_block_minutes, block_start_offsets_minutes, programming_day_start)
- SchedulePlan
- Zone (time window holding schedulable assets)
- Program, VirtualAsset, SyntheticAsset
- ScheduleDay (immutable daily truth)
- EPG derived from ScheduleDay

Execution:
- PlaylogEvent / BroadcastPlaylogEvent (lowest runtime truth)

Playout generation:
- Producer (builds plans; never launches ffmpeg)
- Enricher (ingest or playout)

Runtime:
- ProgramDirector (top-level supervisor)
- ChannelManager (per-channel runtime owner)

────────────────────────
ZONES / GRID INVARIANTS
────────────────────────
- All starts align to grid boundaries.
- Zones fill their window; underfill becomes avails.
- Zones do not cut in-flight programs.
- Zones do not auto-extend.
- Longform is never cut.
- Carry-in across day boundary is allowed.
- EPG reflects resolved ScheduleDay times.

────────────────────────
RUNTIME MODEL
────────────────────────
- ChannelManager serves MPEG-TS over HTTP.
- Multiple viewers share one playout instance.
- Missing asset → 500 (do not start playout).
- Schedule gap → 503.
- Channel errors are isolated.

Viewer endpoints:
- GET /channellist.m3u
- GET /channel/{id}.ts

────────────────────────
OPERATOR MODEL
────────────────────────
- CLI: `retrovue <noun> <verb>`
- Contracts define behavior; tests enforce contracts.
- Behavior changes require contract updates first.

────────────────────────
CHANGE DISCIPLINE
────────────────────────
When asked “add X to Core”:
1) Identify layer (ingest, scheduling, plan gen, runtime, CLI/contracts).
2) Use existing first-class nouns only.
3) Enforce grid, carry-in, longform, and on-demand playout invariants.
4) Never add external system logic outside Importers.

ACKNOWLEDGEMENT:
Confirm understanding of Core as the multi-channel orchestration system that schedules, plans, and supervises playout while AIR handles runtime execution correctness.
Do not proceed until this model is accepted.
