# Current Pipeline Inventory — Final Architecture

This document is a technical inventory of the RetroVue media ingestion and metadata pipeline.

**Terminology:** The ingest/catalog entity is **Container**. See [TERMINOLOGY_COLLECTION_TO_CONTAINER.md](TERMINOLOGY_COLLECTION_TO_CONTAINER.md). For the refactor inventory and rename table, see [COLLECTION_TO_CONTAINER_REFACTOR_PHASE0_INVENTORY.md](COLLECTION_TO_CONTAINER_REFACTOR_PHASE0_INVENTORY.md). Architecture docs use Container only; the only allowed remaining "Collection" references are historical migrations and temporary CLI/API compatibility.

---

## Pipeline Stages (Execution Order)

1. **Container discovery** — Enumerate locators from the source (e.g. Plex, filesystem). No catalog writes. Output: list of `DiscoveredLocator` (source_id, container_id, locator, optional fingerprint).
2. **Catalog reconciliation** — Load catalog state for the container; compare discovered locators to determine outcome per item (create | update | no_action | mark_unavailable). Apply mutations: create new assets, update fingerprint, soft-delete missing, or restore soft-deleted when re-added. Enqueue processor jobs for created/updated/restored assets.
3. **Job queue** — One row in `processor_jobs` per target (target_type, target_id). States: pending, running, completed, failed. Workers claim pending jobs (status → running), hand to processor runtime, then set completed/failed.
4. **Processor runtime** — For each job: load target and related metadata once; build ProcessingContext; run applicable processors (from capability registry) sequentially; merge results into context (no DB write per processor); validate ownership; persist in a single transaction (asset/editorial/probed, processor_runs, processor_outputs).
5. **Metadata persistence** — Structured fields on Asset and child tables (AssetEditorial, AssetProbed, etc.); flexible payloads in `processor_outputs`. Operator-owned fields (e.g. approved_for_broadcast) are not overwritten by processors.

Ingest is triggered by CLI (`retrovue container ingest <name>`, `retrovue source ingest <source>`) or (when wired) by the scheduler daemon before horizon expansion. (During compatibility rollout, `retrovue collection ingest` may be accepted as a deprecated alias.) Workers run separately (`retrovue worker run`) and drain the job queue.

---

## Code Locations

### Container discovery

| Responsibility | Module / file | Key classes / functions |
|----------------|---------------|--------------------------|
| Discover locators | `pkg/core/src/retrovue/catalog/discovery.py` | `discover_locators(container, importer, ...)` (contract term: container), `DiscoveredLocator`, `Fingerprint` |
| Invoked from ingest | `pkg/core/src/retrovue/cli/commands/_ops/collection_ingest_service.py` | Ingest service → `discover_locators()` (code names still Collection until Phase 2+; contract entity is Container) |
| Importers | `pkg/core/src/retrovue/adapters/importers/` | `FilesystemImporter`, `PlexImporter` — `discover()`, `discover_scoped()` |

### Catalog reconciliation

| Responsibility | Module / file | Key classes / functions |
|----------------|---------------|--------------------------|
| Load catalog state | `pkg/core/src/retrovue/catalog/reconciliation.py` | Load catalog state for container; `determine_reconciliation_outcomes()` |
| Outcomes | Same | `ReconciliationOutcome`: create, update, no_action, mark_unavailable |
| Apply + enqueue | Ingest service module | Apply loop: create/update/restore/soft-delete; `enqueue_processor_jobs()` |

### Job queue

| Responsibility | Module / file | Key classes / functions |
|----------------|---------------|--------------------------|
| Job table and API | `pkg/core/src/retrovue/catalog/processor_jobs.py` | `enqueue()`, `claim_next_job()`, `complete_job()`, `purge_old_processor_jobs()` |
| Entity | `pkg/core/src/retrovue/domain/entities.py` | `ProcessorJob` |
| Worker | `pkg/core/src/retrovue/runtime/processor_worker.py` | `run_once()`, `run_loop()` |

### Processor runtime

| Responsibility | Module / file | Key classes / functions |
|----------------|---------------|--------------------------|
| Execute job | `pkg/core/src/retrovue/catalog/processor_runtime.py` | `execute_job(db, job)` |
| Context and apply | Same | `ProcessingContext`, ownership filter (`FIELD_OWNERSHIP`), persist asset + processor_runs + processor_outputs |
| Capability registry | `pkg/core/src/retrovue/catalog/processor_capability.py` | `get_processors_for_target()`, `get_capability()`, `CAPABILITY_REGISTRY` |
| Enrichers | `pkg/core/src/retrovue/adapters/registry.py` | `ENRICHERS` (e.g. ffprobe, interstitial-type, loudness) |

### Metadata persistence

| Responsibility | Module / file | Key classes / functions |
|----------------|---------------|--------------------------|
| Structured persistence | `pkg/core/src/retrovue/infra/metadata/persistence.py` | `persist_asset_metadata()` |
| Run history | `processor_runtime.py` | Writes `ProcessorRun` rows in same transaction as job completion |
| Flexible output | Same | Upserts `ProcessorOutput` by (processor_id, target_type, target_id) |
| Entities | `domain/entities.py` | `Asset`, `AssetEditorial`, `AssetProbed`, `ProcessorRun`, `ProcessorOutput` |

### Identity and canonical key

| Responsibility | Module / file | Key classes / functions |
|----------------|---------------|--------------------------|
| Canonical key and hash | `pkg/core/src/retrovue/infra/canonical.py` | `canonical_key_for()`, `canonical_hash()` |
| Duplicate / restore check | Ingest service module | Get by container and canonical hash (contract: container) |

---

## Data Flow Summary

1. **CLI** — `retrovue container ingest <name>` (or source ingest) opens a session and calls the container ingest service. (Compatibility: `collection ingest` may be accepted during rollout.)
2. **Discovery** — Discover locators for the container (contract entity); returns list of (DiscoveredLocator, item). No DB write.
3. **Reconciliation** — Load catalog state for the container; `determine_reconciliation_outcomes(discovered, catalog_state)` → list of (loc, outcome, existing_asset). For each outcome: create (persist asset, enqueue jobs), update (refresh fingerprint, enqueue), no_action (skip), mark_unavailable (soft-delete). Restore: if create path finds existing soft-deleted asset by canonical_key_hash, undelete and enqueue.
4. **Enqueue** — `enqueue_processor_jobs(asset_ids, processor_ids)` adds rows to `processor_jobs` (one per target_type per asset; deduplicated).
5. **Worker** — `retrovue worker run` (or run_loop): `claim_next_job()` → `execute_job(db, job)` → `complete_job()`. Runtime loads asset, builds context, runs processors in order, merges results, persists in one transaction.
6. **Persistence** — Asset (and editorial/probed), processor_runs (one per processor that ran), processor_outputs (flexible payloads). Operator-owned fields are skipped on apply.

---

## Data Models

- **Source** — id, external_id, name, type, config. One-to-many **Containers** (contract term; DB table name may still be `collections` until final migration).
- **Container** — uuid, source_id, external_id, name, sync_enabled, ingestible, config. One-to-many Assets; PathMappings.
- **Asset** — uuid, container_id (contract; DB column may still be `collection_uuid` until final migration), canonical_key_hash, uri, state, approved_for_broadcast, duration_ms, is_deleted, etc. Child: AssetEditorial, AssetProbed, etc.
- **ProcessorJob** — id, target_type, target_id, status (pending|running|completed|failed), priority, created_at, started_at, completed_at, error_message.
- **ProcessorRun** — run_id, job_id, processor_id, target_type, target_id, status, started_at, completed_at, error_message. History; cascade-deleted with job.
- **ProcessorOutput** — id, processor_id, target_type, target_id, payload_json. Flexible metadata per processor per target.

---

## Assumptions

1. **One job per target** — (target_type, target_id) has at most one pending/running job. Deduplication at enqueue.
2. **Processors run only in workers** — Ingest and reconciliation do not invoke processors; they only enqueue jobs.
3. **Single transaction per job** — Runtime loads once, runs all processors, then persists in one commit.
4. **Operator-owned fields** — approved_for_broadcast, operator_verified; processors must not overwrite (enforced in runtime apply).
5. **Reconciliation only on full collection scope** — Scoped ingest (title/season/episode) does not mark missing assets as unavailable.
6. **Catalog state excludes soft-deleted** — Load catalog state for the container returns only assets with is_deleted=false; re-added files with same canonical_key_hash restore the soft-deleted row and enqueue.
