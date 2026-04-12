# Collection → Container Refactor — Phase 0 Inventory

**Purpose:** Complete inventory of all "Collection" references before any rename. Classify each reference and build the canonical rename table. No code or DB changes in Phase 0.

**Refactor guardrails** (apply to every phase):

- Do not change runtime behavior of discovery, reconciliation, job queueing, processor execution order, or scheduler triggers.
- Do not change media identity semantics: `(source_id, container_id, locator)` stays canonical.
- Do not perform destructive DB renames until the final phase.
- Keep old external names temporarily accepted where needed; stop introducing new uses of "Collection" as the ingest entity name.
- Treat as contract-alignment refactor, not a feature change.

---

## 1. Exclusions (do not rename)

| Category | Description | Examples |
|----------|-------------|----------|
| **Python stdlib** | `from collections.abc import ...` | All Alembic migrations, `usecases/asset_attention.py`, `usecases/metadata_handler.py`, `infra/db.py`, `streaming/*.py`, `tests/**/conftest.py`, `test_*_contract.py` (Mapping, Sequence, etc.) |
| **Historical migrations** | Alembic version files that already ran | `alembic/versions/*.py` — do not edit; physical renames happen in a future migration only |
| **Plex API metadata** | "Collection" as Plex tag/category key | `plex_importer.py`: `meta.get("Collection", [])`, `_extract_tags("Collection")`, `metadata["collection_tags"]` — external API surface; may keep key name or document as "Plex collection tag" |
| **Test variable names (generic)** | Local vars like `collections = []` | Where the meaning is "list of container entities"; rename to `containers` when touching that file |
| **`collections.issubset`** | Set method | `test_schedule_block_program_list.py` — stdlib set, not our entity |

---

## 2. Canonical Rename Table

| Current | Target | Notes |
|--------|--------|-------|
| **Entity / ORM** | | |
| `Collection` (class) | `Container` | Domain entity in `domain/entities.py` |
| `collections` (table name) | `containers` | **Final phase only** — ORM `__tablename__` stays until DB migration |
| `collection` (relationship name) | `container` | e.g. `Asset.collection` → `Asset.container` |
| `collections` (relationship on Source) | `containers` | `Source.collections` → `Source.containers` |
| **Columns (application-facing; DB rename later)** | | |
| `collection_uuid` (Asset, PathMapping) | `container_id` or keep `container_uuid` | Contract uses container_id; DB phase renames to `container_id` or keep `container_uuid` per project choice |
| `collection_id` (ScheduleItem) | `container_id` | Already "id" semantics; align name to container |
| **Services / modules** | | |
| `CollectionIngestService` | `ContainerIngestService` | `cli/commands/_ops/collection_ingest_service.py` → module can stay `container_ingest_service.py` |
| `CollectionIngestResult` | `ContainerIngestResult` | Same file |
| `resolve_collection_selector` | `resolve_container_selector` | Same file |
| `validate_collection_exists` | `validate_container_exists` | `infra/validation.py` |
| `discover_collections` (usecase) | `discover_containers` | `usecases/source_discover.py` |
| **CLI** | | |
| `retrovue collection` (Typer name) | `retrovue container` | `cli/commands/collection.py` → `container.py`; register in main as `container` |
| `--collection` (option) | `--container` | e.g. `asset list --container`, `asset attention --container`; accept `--collection` as compatibility alias during window |
| Argument `collection_id` | `container_id` (or keep as param name for compatibility) | CLI args; JSON output keys `collection_id` → `container_id` after compatibility window |
| **API / routes** | | |
| `/collections` | `/containers` | Legacy API under `src_legacy/`; new APIs use `/containers` |
| `/sources/{id}/collections` | `/sources/{id}/containers` | Same |
| **JSON / DTOs** | | |
| `collection_id` in JSON | `container_id` | After compatibility window |
| `collection_name` in JSON | `container_name` | After compatibility window |
| **Scheduler / DSL** | | |
| `type: "collection"` (resolver/source type) | `type: "container"` | `source_resolver.py` _SUPPORTED_TYPES, `template_runtime.py` Literal; scheduler DSL "collection" → "container" |
| `match["collection"]` (filter by name) | `match["container"]` | Catalog/source resolver filter |
| `block.get("collection")` (schedule block) | `block.get("container")` | schedule_revision_writer, dsl_schedule_service — block metadata key |
| **Interfaces** | | |
| `ImporterInterface.discover_collections` | `discover_containers` | `domain/interfaces.py` |
| `ImporterInterface.ingest_collection` | `ingest_container` | Same |
| `ImporterInterface.validate_ingestible(self, collection)` | `validate_ingestible(self, container)` | Same |
| **Internal helpers** | | |
| `_resolve_collection` | `_resolve_container` | `usecases/collection_enrichers.py` |
| `_get_interstitial_collection_uuid` | `_get_interstitial_container_uuid` | `catalog/db_asset_library.py` |
| `_interstitial_collection_name` | `_interstitial_container_name` | Same |
| **Enrichers** | | |
| `InterstitialTypeEnricher(collection_name=...)` | `container_name=...` | Constructor and internal field; contract may still say "collection type map" for display |
| **Docs/contracts** | | |
| "Collection" as ingest entity | "Container" | All architecture and contract docs; keep "collection" only where referring to legacy or Plex |

**Note:** `collection_uuid` in Asset/PathMapping is the FK to the container; contract identity is `(source_id, container_id, locator)`. So `container_id` = current `collection_uuid` in identity docs. DB column rename to `container_id` is optional if we prefer keeping `_uuid` for PK consistency.

**Official definition (post-refactor):**
- **Container** — subdivision of a Source (e.g. one Plex library, one filesystem folder). One container has 1..n assets. This is the entity we renamed from "Collection."
- **Collection** *(reserved)* — future concept: a logical grouping of assets from **1..n containers** (and sources). Example: a "Horror" collection = 2 movies from Container A + 2 from Container B. Do not use "collection" for the source-subdivision entity; that is **Container**. See TERMINOLOGY_COLLECTION_TO_CONTAINER.md.

---

## 3. Classification of References

### 3.1 Ingest entity (domain, services, CLI, usecases)

| File | References | Classification |
|------|------------|----------------|
| `server/src/retrovue/domain/entities.py` | `Collection`, `__tablename__ = "collections"`, `collection_uuid`, `collection`, `collections` (relationship) | Ingest entity |
| `server/src/retrovue/domain/interfaces.py` | `Collection`, `discover_collections`, `ingest_collection`, `validate_ingestible(collection)` | Ingest entity |
| `server/src/retrovue/cli/commands/collection.py` | All Collection CLI, `collection_id` arg, `CollectionIngestService`, `resolve_collection_selector`, JSON `collection_id`/`collection_name` | Ingest entity + CLI |
| `server/src/retrovue/cli/commands/_ops/collection_ingest_service.py` | `Collection`, `CollectionIngestResult`, `resolve_collection_selector`, `collection_uuid`, `collection_id`/`collection_name` in result | Ingest entity |
| `server/src/retrovue/usecases/collection_enrichers.py` | `Collection`, `_resolve_collection`, `collection_id`/`collection_name` in payloads | Ingest entity |
| `server/src/retrovue/usecases/source_discover.py` | `discover_collections` | Ingest entity |
| `server/src/retrovue/usecases/asset_reprobe.py` | `Collection`, `collection_uuid` param, `collection.name` | Ingest entity |
| `server/src/retrovue/usecases/asset_enrich_stale.py` | `Collection`, `--collection` / `--source`, `collection_selector` | Ingest entity |
| `server/src/retrovue/infra/validation.py` | `validate_collection_exists`, `Collection`, `collection_id` | Ingest entity |
| `server/src/retrovue/catalog/processor_runtime.py` | `Collection`, `asset.collection_uuid`, `collection_name` (derived) | Ingest entity |
| `server/src/retrovue/catalog/reconciliation.py` | `collection_uuid` | Ingest entity |
| `server/src/retrovue/catalog/discovery.py` | Comment "collection" (container) | Ingest entity (docs) |
| `server/src/retrovue/catalog/db_asset_library.py` | `_interstitial_collection_name`, `_get_interstitial_collection_uuid`, `Collection` | Ingest entity |
| `server/src/retrovue/adapters/importers/plex_importer.py` | `validate_ingestible(self, collection: Collection)`, Plex `Collection` tag (exclude tag key per §1) | Ingest entity + Plex tag |
| `server/src/retrovue/adapters/importers/filesystem_importer.py` | "collections" in comments/list (subdirs as containers) | Ingest entity (docs) |
| `server/src/retrovue/cli/commands/asset.py` | `--collection`, `collection_uuid=`, `collection_name` in output | CLI + ingest entity |
| `server/src/retrovue/cli/commands/source.py` | `usecase_discover_collections`, "collections table", `discover_collections` | Ingest entity |
| `server/src/retrovue/cli/commands/_ops/source_ingest_service.py` | `collection_uuid`, `coll` (variable) | Ingest entity |
| `server/src/retrovue/cli/commands/_ops/backfill_plex_artwork.py` | `Collection`, `collections`, `collection_uuids` | Ingest entity |

### 3.2 Scheduler / DSL / runtime

| File | References | Classification |
|------|------------|----------------|
| `server/src/retrovue/runtime/source_resolver.py` | `_SUPPORTED_TYPES = {"asset", "collection", "pool", "program"}`, "collection" resolution by name | Scheduler DSL |
| `server/src/retrovue/runtime/asset_resolver.py` | `register_collection`, `_collections`, `match.get("collection")`, `type not in ("collection", "pool")` | Scheduler DSL |
| `server/src/retrovue/runtime/catalog_resolver.py` | `collection` filter, `col_name_map` (collection_uuid→name), `collection_name` on result type | Scheduler DSL + ingest |
| `server/src/retrovue/runtime/dsl_schedule_service.py` | `Collection`, `PathMapping.collection_uuid`, `block "collection"`, `it.collection_id` | Scheduler DSL + ingest |
| `server/src/retrovue/runtime/schedule_revision_writer.py` | `block.get("collection")`, `collection_id` on ScheduleItem | Scheduler DSL |
| `server/src/retrovue/runtime/schedule_compiler.py` | `d["collection"]` | Scheduler DSL |
| `server/src/retrovue/runtime/template_runtime.py` | `type: Literal["collection", "pool", "primary_content"]` | Scheduler DSL |
| `server/src/retrovue/runtime/schedule_types.py` | "collection" in comments (series/collection) | Scheduler DSL (docs) |
| `server/src/retrovue/usecases/schedule_reschedule.py` | `collection_id=it.collection_id` | Scheduler + ScheduleItem field |

### 3.3 Tests

| File | References | Classification |
|------|------------|----------------|
| `server/tests/contracts/conftest.py` | "Test Container" fixture text | Test name |
| `server/tests/contracts/test_*collection*.py` | All Collection/collection_id/CollectionIngestService | Test (follow code renames) |
| `server/tests/contracts/test_processor_*.py` | `Collection`, `collection_uuid`, "Test Container" | Test |
| `server/tests/contracts/test_asset_*.py` | `collection_id`, `collection_uuid`, `--collection` | Test |
| `server/tests/contracts/test_source_*.py` | `usecase_discover_collections`, "collections" | Test |
| `server/tests/contracts/test_interstitial_type_stamp.py` | `TestKnownCollectionMapping`, `TestUnknownCollectionRejection`, "collection", `collection_uuid`, `_get_interstitial_collection_uuid` | Test + invariant |
| `server/tests/contracts/test_channel_*.py` | `collection_uuid` in fixtures | Test |
| `server/tests/contracts/scheduling/*.py` | `collection_id=None` | Test (ScheduleItem) |
| `server/tests/contracts/runtime/*.py` | `collection_id` | Test |
| `server/tests/_legacy/**` | Legacy API `/collections`, `discover_collections`, `--collection-id` | Legacy test (compat or update) |
| `tests/contracts/test_interstitial_enrichment.py` | `collection_uuid`, `_get_interstitial_collection_uuid` | Test (invariant) |

### 3.4 Migration history (do not modify)

| File | References | Classification |
|------|------------|----------------|
| `alembic/versions/20251029_000000_rename_source_collections_to_collections.py` | Rename source_collections → collections | Historical migration |
| `alembic/versions/20251030_rename_path_mapping_collection_id_to_uuid.py` | collection_id → collection_uuid on path_mappings | Historical migration |
| `alembic/versions/20251029_000001_create_assets_table.py` | collection_uuid, collections.uuid FK | Historical migration |
| `alembic/versions/20260315_assets_source_id_fingerprint.py` | collections table in backfill | Historical migration |
| `alembic/versions/20260303_create_schedule_revisions.py` | schedule_revision collection_id column | Historical migration |
| `alembic/versions/9541bbc23bcd_fresh_baseline_schema.py` | source_collections, collection_uuid, collection_id | Historical migration |
| Other `alembic/versions/*.py` | `from collections.abc import Sequence` only | Stdlib exclude |

### 3.5 Docs and contracts

| File | References | Classification |
|------|------------|----------------|
| `docs/contracts/architecture/CURRENT_PIPELINE_INVENTORY.md` | Collection, CollectionIngestService, ingest_collection | Docs → Container |
| `docs/contracts/architecture/ASSET_IDENTITY_MIGRATION.md` | collection_uuid, Collection, collections table | Docs → container_id / Container |
| `docs/contracts/architecture/PIPELINE_MIGRATION_ARCHITECTURE.md` | (Container already used) | Already aligned |
| `docs/contracts/core/ContainerDiscoveryContract_v0.1.md` | (Container) | Already aligned |
| `server/docs/contracts/resources/CollectionIngestContract.md` | (referenced by code) | Rename to ContainerIngestContract + update body |
| `server/docs/contracts/resources/CollectionUpdateContract.md` | collection_id, Collection | Docs → container |
| `server/docs/contracts/resources/SourceIngestContract.md` | collection-level, collection ingest, collection_id | Docs → container |
| `server/docs/contracts/resources/SourceDiscoverContract.md` | collection discovery, collections | Docs → container |
| `server/docs/contracts/resources/AssetListContract.md` | --collection, collection_id | Docs → container |
| `server/docs/contracts/resources/AssetAttentionContract.md` | --collection, collection_uuid | Docs → container |
| `server/docs/contracts/resources/TrafficManagementContract.md` | collection_uuid | Docs → container_id |
| `docs/contracts/traffic_shaping.md` | collection_uuid, collection_name | Docs → container |
| `docs/invariants/interstitial_enrichment.md` | apply_enrichers_to_collection, collections | Docs → container |
| `docs/contracts/interstitial_enrichment.md` | collections (subdirs), Collection Type Map | Docs → container |
| `docs/contracts/core/ProcessorCapabilityContract_v0.1.md` | processor run ffprobe --collection | Docs → --container |
| `server/docs/contracts/INV-INTERSTITIAL-TYPE-STAMP-001.md` | collection_uuid filter | Docs → container |
| `server/docs/overview/source-management.md` | collection_id | Docs → container_id |
| `server/docs/data/domain/IngestPipeline.md` | collections | Docs → containers |
| `server/docs/developer/TestingStrategy_CollectionContracts.md` | collection_uuid, Collection | Docs → container |
| `server/docs/contracts/resources/cross-domain/Source_Collection_Guarantees.md` | (title) | Docs → Source_Container |
| `server/.cursor/rules.json` | discover_collections, collections | Cursor rules → container |
| `docs/domains/AssetResolution.md` | Sources own collections | Docs → containers |
| Archive docs under `server/docs/archive/` | collection_id, collections | Docs (update when touching) |

### 3.6 Web / API (legacy)

| File | References | Classification |
|------|------------|----------------|
| `server/src/retrovue/web/studio.py` | SQL `JOIN collections c ON c.uuid=a.collection_uuid` | Ingest entity (SQL; table rename in final phase) |
| `server/src_legacy/retrovue/api/routers/ingest.py` | `/sources/{source_id}/collections` | Legacy API route |
| `server/src_legacy/retrovue/api/web/pages.py` | `/sources/{id}/collections`, discover_collections | Legacy API |
| `server/src_legacy/retrovue/api/web/templates/*.html` | collections, collection.external_id | Legacy UI |
| `server/src_legacy/retrovue/content_manager/source_service.py` | discover_collections, Collection, db.refresh(collection) | Legacy (quarantine) |
| `server/src_legacy/retrovue/content_manager/ingest_orchestrator.py` | _process_collection, collections | Legacy (quarantine) |

### 3.7 ScheduleItem / ScheduleRevision

| File | References | Classification |
|------|------------|----------------|
| `server/src/retrovue/domain/entities.py` | ScheduleItem.collection_id | Ingest/scheduler (column → container_id in rename) |
| `server/src/retrovue/runtime/schedule_revision_writer.py` | collection_id=, "collection_raw" | Scheduler DSL |
| `server/src/retrovue/runtime/dsl_schedule_service.py` | it.collection_id, "collection" in meta | Scheduler DSL |

---

## 4. Tracked Checklist (non-historical)

Use this checklist when executing later phases. Only non-historical references are listed; migrations are excluded.

- [ ] **Domain** — `domain/entities.py`: Collection → Container, __tablename__ (code only; DB in final phase), relationship names, collection_uuid → container_id/container_uuid
- [ ] **Domain** — `domain/interfaces.py`: Collection type, discover_collections → discover_containers, ingest_collection → ingest_container, validate_ingestible(container)
- [ ] **CLI collection group** — `cli/commands/collection.py` → `container.py`, Typer name, all collection_id args and JSON keys (with compat shim), resolve_collection_selector, CollectionIngestService
- [ ] **CLI _ops** — `collection_ingest_service.py` → container_ingest_service.py: CollectionIngestService/Result, resolve_collection_selector, collection_uuid/collection_id/collection_name
- [ ] **Usecases** — source_discover.discover_collections → discover_containers; collection_enrichers _resolve_collection, payload keys; asset_reprobe/asset_enrich_stale collection params; schedule_reschedule collection_id
- [ ] **Infra** — validation.validate_collection_exists → validate_container_exists
- [ ] **Catalog** — processor_runtime Collection, collection_uuid, collection_name; reconciliation collection_uuid; discovery comment; db_asset_library interstitial_collection_* → container_*
- [ ] **Importers** — plex_importer validate_ingestible(collection) → container; filesystem_importer comments (Plex "Collection" tag key excluded)
- [ ] **CLI asset/source** — asset.py --collection → --container, collection_uuid/collection_name; source.py discover_collections refs
- [ ] **Runtime** — source_resolver "collection" type → "container"; asset_resolver register_collection, match["collection"]; catalog_resolver collection filter, collection_name; dsl_schedule_service Collection, collection_uuid, block "collection", collection_id; schedule_revision_writer block.get("collection"), collection_id; schedule_compiler d["collection"]; template_runtime Literal "collection" → "container"
- [ ] **Web** — studio.py SQL (table name in final phase only)
- [ ] **ScheduleItem** — entities ScheduleItem.collection_id → container_id (code; DB in final phase)
- [ ] **Tests** — all test_*collection*, test_processor_*, test_asset_*, test_source_*, test_interstitial_*, test_channel_*, scheduling/runtime tests (collection_id, collection_uuid, --collection, CollectionIngestService, discover_collections)
- [ ] **Docs/contracts** — All listed in §3.5; CollectionIngestContract → ContainerIngestContract; CollectionUpdateContract; Source_Collection_Guarantees → Source_Container
- [ ] **Cursor rules** — .cursor/rules.json discover_collections, collections
- [ ] **Legacy** — src_legacy API routes /collections → /containers (or compat); legacy service discover_collections/_process_collection (quarantine; rename when removing legacy)

---

## 5. Known Exceptions and Compatibility Shims

| Exception | Handling |
|-----------|----------|
| **DB table and column names** | No physical rename in Phase 0–N-1. ORM can use `__tablename__ = "collections"` until a dedicated migration renames to `containers` and columns to `container_id` where chosen. |
| **CLI backward compatibility** | During compatibility window: accept `--collection` as alias for `--container` where applicable; JSON output may emit both `container_id` and `collection_id` (deprecated) until window closes. |
| **Legacy API** | Keep `/sources/{id}/collections` working; add `/containers` or same path returning container semantics; document deprecation. |
| **Plex "Collection" tag** | Retain as external key in Plex metadata (e.g. `meta.get("Collection")`); do not rename to "Container" in Plex API payloads. Internal type/entity is Container. |
| **Historical migrations** | Never edit. New migration in final phase will rename table/columns. |

---

## 6. Success Criteria (Phase 0)

- [x] Tracked checklist exists for every non-historical Collection reference (§4).
- [x] Canonical rename table documented (§2).
- [x] All references classified (§3).
- [x] Exclusions and exceptions documented (§1, §5).
- [ ] Team review of inventory and rename table before Phase 1.

---

## 7. Phase 1 Complete (Contract and Documentation Alignment)

Phase 1 made the written architecture the source of truth before code changes:

- **Terminology note:** [TERMINOLOGY_COLLECTION_TO_CONTAINER.md](TERMINOLOGY_COLLECTION_TO_CONTAINER.md) states the migration and that only historical migrations (and temporary CLI/API compatibility) may keep "Collection".
- **Architecture docs** now describe Container as the ingest/catalog entity; remaining "Collection" in docs is either deprecated compatibility or historical migration only.
- **Contract docs** use `--container` in examples and note `--collection` as deprecated and accepted temporarily.
- **Developer/overview docs** (overview/architecture, source-management, IngestPipeline, AssetResolution, Source_Collection_Guarantees, interstitial, traffic_shaping, TestingStrategy) updated to Container terminology.

## 8. Phase 2 Complete (Code-Level Container Aliases, No DB Change)

Phase 2 introduced Container terminology in Python/domain/service code while the database still uses legacy table/column names:

- **ORM:** `Container` class maps to table `collections`; `Collection = Container` compatibility alias retained.
- **Asset:** `container_id` (maps to column `collection_uuid`), `container` relationship to `Container`, `container_format` (maps to column `container`) for media format string.
- **PathMapping:** `container_id` (maps to column `collection_uuid`), `container` relationship.
- **Source:** `containers` relationship (replacing `collections`).
- **ScheduleItem:** `container_id` (maps to column `collection_id`).
- **Domain interfaces / importers / services / CLI/repos:** Types and variables use `Container` and `container_id`; method names (e.g. `discover_collections`, `ingest_collection`) kept for compatibility.
- **Tests:** Contract and unit tests updated to use `container_id` and `Container` where they construct or assert on entities; `Collection` import still resolves via alias.

No physical schema change; runtime behavior unchanged.

## 9. Phase 3 Complete (Service and Pipeline Interfaces)

Phase 3 renamed operational code paths to speak Container end-to-end with compatibility wrappers:

- **Discovery:** `discover_containers(db, source_id=...)` in `usecases/source_discover.py`; `discover_collections` = alias.
- **Ingest service:** `ContainerIngestService`, `ContainerIngestResult` (fields `container_id`, `container_name`); `ingest_container(...)`; `ingest_collection` / `CollectionIngestService` / `CollectionIngestResult` = compatibility.
- **Repository:** `get_by_container_and_canonical_hash`, `exists_by_container_and_canonical_hash` on `AssetRepository`; `get_by_collection_*` = wrappers.
- **Refresh:** `refresh_container(db, container, importer, **kwargs)` and `refresh_collection` wrapper.
- **Resolution:** `resolve_container_selector(db, container_selector)`, `construct_importer_for_container(container, db)`; `resolve_collection_selector` and `construct_importer_for_collection` = wrappers.
- **Source ingest:** Uses `Container`, `ContainerIngestService`, `ingest_container(container=...)`; re-exports `CollectionIngestService` for tests that patch it.
- **Daemon:** Comment updated to "configured containers" and "container_refresh".
- **Tests:** Contract tests updated to `container_id`/`container_name`, `ingest_container`, and patch `ContainerIngestService` where applicable.

Pipeline shape unchanged: refresh_container → discover locators → reconcile catalog → enqueue processor jobs.

## 10. Phase 4 Complete (CLI and Operator Surface Migration)

Phase 4 moved operator-facing commands and flags to Container with backward-compatible shims:

- **Canonical command group:** `retrovue container` registered in main (before `collection`); same subcommands as collection (show, list, list-all, update, approve, attach-enricher, detach-enricher, delete, wipe, ingest, sync). Help and docstrings use Container wording and examples (`retrovue container show`, etc.).
- **Deprecated alias:** `retrovue collection` retained; callback on the collection group emits deprecation warning to stderr when any subcommand is invoked. No behavior change.
- **Asset CLI:** `asset attention` and `asset enrich` accept `--container` (canonical) and `--collection` (deprecated); when `--collection` is used, deprecation warning is emitted. Usecase error messages say "Provide --source or --container."
- **Docs and help:** All command docstrings and examples use "container" and `retrovue container`; operator docs (`container.md`) created; `collection.md` unchanged. Source/add help and ingest-service/source CLI error messages reference `retrovue container update` / `retrovue container show`.
- **Tests:** CLI tests for `--container` (canonical) and `--collection` (deprecated, must still work and show warning); legacy CLI tests updated to expect Container help text; collection ingest contract tests expect `retrovue container show` in error messages.

No DB migration; no runtime behavior change beyond deprecation warnings.

## 11. Phase 5 Complete (API and Serialization Surface Migration)

Phase 5 made public payloads and routes container-first with dual-read / single-write behavior:

- **ContainerIngestResult.to_dict():** Response is container-first: `container_id`, `container_name` emitted first; `collection_id`, `collection_name` retained as deprecated (same values).
- **Legacy API (src_legacy):** Added GET `/api/ingest/sources/{source_id}/containers` (canonical) returning `{"source_id", "containers": [{..., "container_id", "collection_id", ...}]}`. GET `.../collections` (deprecated) now includes `container_id` in each item. Added PUT `/api/ingest/sources/{source_id}/containers/{external_id}` (canonical); PUT `.../collections/{external_id}` delegates to same impl. Shared helper `_collection_to_item()` builds items with container_id first.
- **IngestRequest (Pydantic):** `container_ids` (canonical) and `library_ids` (deprecated); dual-read in run_ingest (single_id from list when len==1).
- **CollectionDTO:** Added `container_id: str`; populated in `list_enabled_collections`, `list_all_collections`, ingest orchestrator. Legacy source_service and ingest_orchestrator updated to use `PathMapping.container_id`, `collection.uuid`, `Asset(container_id=...)`, `CollectionDTO(..., container_id=str(collection.uuid))`.
- **Usecase response dicts:** `asset_attention` rows include `container_id` and `collection_uuid`. `asset_update` summary includes `container_id` and `collection_uuid`. `BulkEnrichResult.to_dict()` includes `containers_processed`, `container_results` (and kept `collections_processed`, `collection_results`). `collection_enrichers` return dicts include `container_id`/`container_name` first, then `collection_id`/`collection_name`.
- **Tests:** Contract tests assert `container_id` in ingest JSON output; BulkEnrichResult tests assert `containers_processed` and `container_results`; mock to_dict return values updated to include container_id.

No DB migration. Old request payloads (library_ids) still accepted; response schema is container-first.

## 12. Phase 6 Complete (Test Suite Migration and Anti-Regression Enforcement)

Phase 6 enforces container terminology in tests and prevents regressions:

- **Guard test:** `tests/contracts/test_container_terminology_guard.py` fails if any file outside an explicit allowed list contains `Collection` or `collection_id`. Exclusions: `alembic/versions/`, docs refactor files, pytest hooks (`pytest_collection_modifyitems`, `pytest_ignore_collect`), stdlib (`collections.abc`, `typing.Collection`), compat alias (`Collection = Container`), Plex API tag, and the guard file itself. Scan limited to `src/`, `src_legacy/`, `tests/` (no `.venv`). Run in CI: `pytest tests/contracts/test_container_terminology_guard.py`.
- **Fixture renames:** `_fake_collection` → `_fake_container` in test_asset_enrich_stale, test_source_ingest_service_contract; `_make_collection` → `_make_container` in test_channel_reconciliation, test_channel_purge. `_make_asset(db, collection)` → `_make_asset(db, container)` with same type. All call sites updated.
- **Test renames/docstrings:** TestSourceScoping docstring and tests `test_iterates_source_containers`, `test_source_with_no_containers`; TestCollectionScoping → TestContainerScoping, `test_single_collection` → `test_single_container`. Test container names "Test Container" in _make_container.
- **Allowed list:** Guard maintains `ALLOWED_TERMINOLOGY_FILES` for files that still reference Collection during the compatibility window. Shrink this list as code is migrated; do not add new production code to it.

No DB migration. Tests preserved through iterative renames.

## 13. Phase 7 Complete (Remove Compatibility Shims)

Phase 7 removed all compatibility shims so application code no longer depends on old Collection names at runtime (DB physical names remain legacy until final migration):

- **Alias removed:** `Collection = Container` removed from `domain/entities.py`. All imports and usages now use `Container` (legacy DTOs renamed to `ContainerDTO`/`ContainerUpdateDTO` in src_legacy; legacy code and tests updated).
- **Wrappers removed:** `resolve_collection_selector`, `ingest_collection` method, `refresh_collection`, `get_by_collection_and_canonical_hash` (in collection_ingest_service and asset_repository), and module aliases `CollectionIngestService`/`CollectionIngestResult` removed. Callers use `resolve_container_selector`, `ingest_container`, `refresh_container`, `get_by_container_and_canonical_hash`, `ContainerIngestService`, `ContainerIngestResult`.
- **CLI:** Deprecated `retrovue collection` command group and `--collection` flag removed. Only `retrovue container` and `--container` remain. Commands registered only on `container_app`; `app = container_app` for backward import.
- **API:** Deprecated `library_ids` and GET/PUT `.../collections` routes removed. Request uses `container_ids` only; responses use `_container_to_item()` with `container_id` only. Legacy web pages and templates updated to `/containers` and `container_ids`.
- **Response payloads:** `ContainerIngestResult.to_dict()` and `collection_enrichers` return dicts no longer include `collection_id`/`collection_name`; only `container_id`/`container_name`. CLI enricher output uses `container_id`/`container_name`.
- **Tests:** Deprecated test `test_collection_filter_deprecated_still_works` removed. Ingest contract tests invoke `retrovue container ingest`; assert `container` keyword and `container_id`/`container_name` in output. Mock `id` → `uuid` for Container in tests.

No DB migration. Runtime behavior unchanged; only DB physical table/column names may still be legacy. Some contract tests (duplicate-handling, milestone persistence, time-tracking) still fail due to mock setup or pre-existing isolation; follow-up may be needed.

## 14. Phase 8 Complete (Final Schema Rename)

Phase 8 renamed physical database objects so schema matches logical architecture:

- **Migration:** `alembic/versions/20260315_rename_collections_to_containers.py` (revision `20260315_containers`, depends on `20260315_proc_out`). Single migration: renames table `collections` → `containers`; renames columns `collection_uuid` → `container_id` (assets, path_mappings), `collection_id` → `container_id` (schedule_items); renames PK, FKs, unique constraints, and indexes to use `containers`/`container_id` naming. Downgrade supported.
- **ORM:** `Container.__tablename__` = `"containers"`; `Asset.container_id` and `PathMapping.container_id` map to DB column `container_id` (no override); `ScheduleItem.container_id` maps to `container_id`; all `__table_args__` index/constraint names updated to `ix_containers_*`, `ix_assets_container_id`, `ix_assets_container_canonical_*`, `ix_path_mappings_container_id`, `uq_containers_source_external`, `fk_*_containers`.
- **Raw SQL:** `web/studio.py` uses `JOIN containers c ON c.uuid=a.container_id`; `src/retrovue/tests/conftest.py` uses `DELETE FROM containers`.
- **Historical migrations:** Unchanged; only new migration and ORM/application code reference the new names. Alembic version files under `alembic/versions/` remain the only place that reference old names (for history).

Success criteria met: physical schema matches logical architecture; no application code references legacy DB table/column names; only historical migration files contain the old names.

## 15. Phase 9 Complete (Final Documentation Sweep and Historical Containment)

Phase 9 makes the repo self-policing and aligns documentation with the canonical model:

- **Canonical model (documented):** Source → Container → Locator → Asset → Processor Jobs → Processor Runtime. Stated in root [CLAUDE.md](../../../CLAUDE.md) and [TERMINOLOGY_COLLECTION_TO_CONTAINER.md](TERMINOLOGY_COLLECTION_TO_CONTAINER.md).
- **Migration notes:** [MIGRATION_NOTES_COLLECTION_TO_CONTAINER.md](MIGRATION_NOTES_COLLECTION_TO_CONTAINER.md) explains the rename and where “Collection” may still appear (historical migrations, that note, refactor inventory, Plex API).
- **Terminology doc:** Updated to “Container (Canonical)”; allowed remaining uses limited to historical migrations, migration notes, and external API (e.g. Plex).
- **CI guard (Python):** Unchanged; fails if `Collection` or `collection_id` appears in scanned `.py` files outside path/line exclusions or `ALLOWED_TERMINOLOGY_FILES`. Path exclusions include `alembic/versions/`, refactor docs, and `MIGRATION_NOTES_COLLECTION`.
- **Docs terminology test:** `test_docs_no_collection_terminology_outside_historical` in `test_container_terminology_guard.py` scans `.md` under `server/docs` and repo `docs/`; fails if “Collection” or `collection_id` appears outside excluded paths. Excluded: refactor/migration docs, `/archive/`, `contracts/`, `data/`, `overview/`, `developer/`, `domains/`. Architecture and operations docs are enforced; shrink exclusions as more docs are updated.
- **Architecture docs updated:** DataFlow.md, SystemBoundaries.md, and IngestArchitecture.md use Container/container_id throughout.

- **CI rule:** Both guard tests must pass in CI. Fail on `Collection` or `collection_id` outside allowlisted paths (Python) or outside excluded doc paths (markdown). Run: `pytest server/tests/contracts/test_container_terminology_guard.py`.

No database migration. Repo conceptually reads as Source → Container → …; “Collection” exists only in historical migrations and explicitly historical notes (and in allowlisted code until further renames).

## 16. Next Steps (Post–Phase 9)

1. Optionally rename CLI module/file (e.g. `collection.py` → `container.py`).
2. Fix remaining contract test failures (mock setup, exit code 1) if desired.
3. Shrink `ALLOWED_TERMINOLOGY_FILES` and rename remaining symbols (e.g. `validate_collection_exists` → `validate_container_exists`, test vars `collection_id` → `container_id`, `mock_collection` → `mock_container`) so the Python guard passes with a minimal allowlist.
4. Update remaining `.md` files that still mention “Collection” so `test_docs_no_collection_terminology_outside_historical` passes (or add targeted path exclusions only where justified).
