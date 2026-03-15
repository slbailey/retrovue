# Pipeline–Contract Alignment

This document analyzes how the **current** implementation (see `CURRENT_PIPELINE_INVENTORY.md`) aligns with the core contracts in `docs/contracts/core/`. For each contract it summarizes current implementation, compliance, differences, and change difficulty. No migration steps are proposed.

---

## 1. ContainerDiscoveryContract

### Current Implementation

- **Source and Container:** Implemented as `Source` (sources table) and `Collection` (collections table). Source has `type` (plex, filesystem); Collection is the subdivision (Plex library or filesystem subdirectory). One-to-many Source → Collections.
- **Discovery through Containers:** Media is discovered per collection: `importer.discover()` or `importer.discover_scoped()` is called per collection. Importers are built from Source config and Collection (e.g. `construct_importer_for_collection(collection, db)`). Filesystem: `FilesystemImporter.list_collections()` / `discover()`; Plex: `PlexImporter` with library key.
- **Locator:** No first-class “locator” type. The closest concept is `path_uri` (and `provider_key` for Plex) on discovered items; canonical identity is derived via `canonical_key_for(item, collection, provider)` and `canonical_key_hash`, not a (source_id, container_id, locator) tuple.
- **Discovery process:** Current flow is: discover items → compare (by canonical_key_hash) → apply mutations (create asset or skip; reconcile stale). There is no separate “container refresh” step that only discovers locators; discovery and catalog mutation are fused in `CollectionIngestService.ingest_collection()`.
- **Reconciliation outcomes:** Create (new asset) and “absent → mark unavailable” (implemented as soft-delete: `is_deleted`, `deleted_at`). “Present + present, update if fingerprint changed” is **not** implemented in the main ingest loop (existing asset → skip). No enqueue of processor jobs; enrichers run inline.
- **Discovery timing:** No scheduler/daemon runs container refresh. Ingest is CLI-only; there is no guarantee that “container refresh runs before playout horizon expansion.”

### Contract Compliance

**Partially complies.**

- Discovery is done through Containers (Collections). Source may have multiple Containers. Locators are not named or modeled as (source_id, container_id, locator); identity is canonical_key/canonical_key_hash. Discovery process in the contract (discover → compare → reconcile → enqueue jobs) is only partly reflected: no separate “discover locators” phase, no job enqueue, and “update if fingerprint differs” is missing.

### Differences

- Contract identity is `(source_id, container_id, locator)`; implementation uses `(collection_uuid, canonical_key_hash)` with canonical_key derived from provider, collection, and path/provider_key.
- Contract: “update media if fingerprint changed”; implementation: on existing (collection, canonical_key_hash) the code skips (no update, no re-enqueue).
- Contract: “enqueue processor jobs as required”; implementation: no job queue; enrichers run inline during ingest.
- Contract: “Container refresh MUST run before playout horizon expansion”; implementation: no daemon-driven container refresh; ingest is CLI-triggered only.
- Contract uses “mark media unavailable”; implementation uses soft-delete (is_deleted, deleted_at) and does not distinguish “unavailable” from “deleted” for display or scheduling.

### Risk Level

**Medium.** Aligning requires: (1) introducing an explicit locator model and optional Media entity or clear mapping from Asset to contract’s “media”; (2) separating “discover locators” from “apply reconciliation” and adding “enqueue processor jobs”; (3) implementing “update existing media if fingerprint differs” instead of skip; (4) optionally adding daemon/scheduler trigger and “mark unavailable” semantics. No full subsystem rewrite, but non-trivial structural change.

---

## 2. CatalogReconciliationContract

### Current Implementation

- **Reconciliation trigger:** Only via CLI (`source ingest`, `collection ingest`). No scheduler daemon trigger.
- **Workflow:** Single ingest path: discover items → path resolution → enricher pipeline (inline) → canonical key/hash → lookup by (collection_uuid, canonical_key_hash) → create new Asset or skip → after loop, mark assets not in seen_hashes as soft-deleted. No explicit “detect sidecar metadata additions or changes” step; sidecars are merged in `handle_ingest` during the same pass.
- **Locator identity:** Identity is canonical_key_hash (and effectively collection_uuid). No (source_id, container_id, locator) tuple. Uniqueness is per (collection_uuid, canonical_key_hash).
- **Media fingerprint:** Not modeled. No explicit fingerprint (hash, size, mtime) comparison; “existing” is “same canonical_key_hash.” No “update if fingerprint differs” path.
- **Outcomes:** “Present / absent → create” and “absent / present → mark unavailable” are implemented (creation + soft-delete). “Present / present → update if fingerprint differs” and “present / present unchanged → no action” are only partially reflected: when present in catalog the code does “no action” (skip) but never “update if fingerprint differs.”
- **Media creation:** New Asset is created; no separate Media entity. “Enqueue processor jobs” is not done; enrichment is inline.
- **Media update:** Not implemented in main ingest; existing asset causes skip.
- **Media retirement:** Implemented as soft-delete (is_deleted, deleted_at). Contract says “mark unavailable” and “do not delete”; implementation does not delete the row but does not use a separate “unavailable” flag.
- **Processor job creation:** Reconciliation does not enqueue jobs; processors run inline.
- **Idempotency:** Running ingest again with no source changes: new items are skipped (existing hash); seen items are re-processed but skipped at create; reconciliation would re-mark already-deleted assets. Idempotency is largely satisfied for “no new changes” runs, but the contract’s full workflow (including job enqueue) is not.
- **Observability:** Logging exists (e.g. ingest_reconcile_removed); no formal “catalog mutation records” or event list matching the contract’s observable events (e.g. “processor jobs enqueued”).

### Contract Compliance

**Partially complies.**

- Reconciliation is deterministic and largely idempotent for the current behavior. Create and “mark missing” behaviors exist. Missing: (source_id, container_id, locator) identity; Media as first-class entity; fingerprint-based update; sidecar-detection step; enqueue of processor jobs; “mark unavailable” vs soft-delete; daemon trigger; full observability list.

### Differences

- Contract workflow has six ordered steps including “detect sidecar metadata additions or changes” and “enqueue processor jobs”; implementation combines discovery, enrichment, and mutation and does not enqueue jobs.
- Contract identity is (source_id, container_id, locator); implementation uses (collection_uuid, canonical_key_hash).
- Contract: “update media if fingerprint differs” and “enqueue processors”; implementation: skip existing, no job queue.
- Contract: “mark media unavailable” and “do not delete”; implementation: soft-delete (row kept, is_deleted set).
- Contract: “create Asset if none exists” and “create Media record”; implementation: single Asset row only, no Media table.
- No scheduler/daemon trigger; no guarantee “before playout horizon expansion.”

### Risk Level

**Medium.** Requires: (1) optional Media entity and/or clear Asset/Media mapping; (2) locator and fingerprint model; (3) “update if fingerprint differs” and “enqueue processor jobs”; (4) sidecar-detection step; (5) “unavailable” vs “deleted” if desired; (6) observability and possibly daemon integration. Structural change but not a full rewrite of the ingest path.

---

## 3. AssetMediaIdentityContract

### Current Implementation

- **Asset vs Media:** There is no Media entity. `Asset` is the only catalog entity for playable content; it holds both “logical program” and “playable file” data (uri, canonical_uri, duration_ms, codecs, etc.). Scheduler and runtime reference Asset (e.g. asset_id) only.
- **Identity:** Implemented as `canonical_key` and `canonical_key_hash` (from `canonical_key_for` and `canonical_hash`), scoped by collection. Not (source_id, container_id, locator).
- **Rules:** “Scheduler schedules Assets” is true (schedule/playlist reference assets). “Playout selects Media variant” is not modeled—there is no Media or variant selection; playout uses the asset’s uri/canonical_uri. “Every Media belongs to exactly one Asset” and “Asset may contain multiple Media” cannot be satisfied because there is no Media.
- **Media replacement:** When the same “logical” item is seen again (same canonical_key_hash), the code skips; it does not update the existing record when fingerprint changes. So “update Media record, do not create new” is partially reflected only in the sense that we do not create a second Asset for the same hash.
- **Media variants:** No support; one Asset per (collection, canonical_key_hash), no multiple Media per Asset.
- **Media availability:** “Mark unavailable” is implemented as soft-delete (is_deleted, deleted_at); contract says do not delete the record—implementation keeps the row.
- **Duplicate detection:** No “flag for operator review”; duplicate is defined as same canonical_key_hash in same collection and results in skip.

### Contract Compliance

**Does not comply.**

- The contract requires Asset = logical program and Media = playable file, with Media identity (source_id, container_id, locator) and optional multiple Media per Asset. The implementation has only Asset and no Media, and uses a different identity scheme. Scheduler/playout behavior is “asset-only”; there is no media variant selection.

### Differences

- No Media entity; Asset conflates program and file.
- Identity is (collection, canonical_key_hash), not (source_id, container_id, locator).
- No “update existing Media when fingerprint changes”; existing → skip.
- No multiple Media per Asset; no runtime “select Media variant.”
- “Mark unavailable” is soft-delete, not a dedicated unavailable flag.
- Duplicate handling is “skip,” not “flag for operator review.”

### Risk Level

**High.** Full alignment would require: (1) introducing a Media entity and a clear Asset–Media relationship; (2) migrating identity from canonical_key_hash to (source_id, container_id, locator); (3) updating ingest to create/update Media and attach to Asset; (4) implementing “update Media when fingerprint differs” and “mark unavailable”; (5) scheduler/playout to resolve Asset → Media (variant selection) where needed. This is a substantial model and pipeline change.

---

## 4. ProcessorCapabilityContract

### Current Implementation

- **Processors:** Implemented as “enrichers” (e.g. `FFprobeEnricher`, `InterstitialTypeEnricher`, `LoudnessEnricher`) in `adapters/enrichers/`. Registry: `ENRICHERS` in `adapters/registry.py` (type name → class).
- **Declaration:** Enrichers have `name`, `scope` (ingest/playout), and `get_config_schema()` (EnricherConfig: required_params, optional_params, scope, description). They do **not** declare “target type” (MEDIA vs ASSET), “required metadata,” or “produced metadata” in a form the system uses for scheduling. Produced fields are implicit (e.g. ffprobe adds raw_labels and probed).
- **Target types:** All current enrichers operate on the discovered item (effectively “file”/media); there is no ASSET-level processor or declaration of target type.
- **Invocation:** Enrichers are triggered only from ingest or re-enrich (reprobe, apply enrichers); no “metadata demand” or queue-based invocation.
- **Batch:** “Batch” is “run pipeline over many items in one process”; there is no “enqueue individual jobs” or job queue. CLI has no `processor run ffprobe --collection X` that enqueues jobs.
- **Asynchronous execution:** Contract requires async via job queue; implementation runs enrichers synchronously inside ingest and re-enrich. Scheduler does not run processors; reconciliation (ingest) does run them inline, which the contract forbids for “scheduler” but the contract also says “catalog reconciliation” should enqueue jobs, not run processors directly.

### Contract Compliance

**Partially complies.**

- Processors (enrichers) exist and are registered; they have a form of declaration (name, scope, config schema). They do not declare target type or required/produced metadata. They are not async and are not invoked via a job queue; batch is “inline loop,” not “enqueue jobs.”

### Differences

- No formal declaration of target type (MEDIA/ASSET), required metadata, or produced metadata.
- Processors run synchronously in the ingest path; no job queue.
- Batch execution is inline, not “enqueue individual processor jobs.”
- Contract: “Processors MUST run asynchronously via the processor job queue” and “Scheduler components MUST NOT execute processor workloads directly”; implementation: reconciliation (ingest) executes enrichers directly; there is no scheduler executing them.

### Risk Level

**Medium.** To align: (1) add capability declaration (target type, required/produced metadata) per processor; (2) introduce a job queue and move execution off the ingest path; (3) make “batch” mean “enqueue one job per target”; (4) keep scheduler from running processors (already true). Structural change, not a rewrite of every enricher.

---

## 5. ProcessorJobQueueContract

### Current Implementation

- **Processor job queue:** None. There is no job table, no queue, no workers, no job lifecycle.
- **Processor jobs:** “Run enricher on item” is implicit in the ingest loop (and in `enrich_asset`); there is no first-class “processor job” entity.
- **Workers:** None. Enrichers are invoked directly by `CollectionIngestService` and `enrich_asset()`.
- **Job identity, deduplication, lifecycle, priority, retry, coordination, observability:** None of these exist.

### Contract Compliance

**Does not comply.**

- The contract requires a processor job queue, job identity (processor_id, target_type, target_id), deduplication, lifecycle (pending/running/completed/failed), priority, workers that pull and execute jobs, coordination (one worker per job), retry, and observability. None of this is implemented.

### Differences

- No queue, no jobs, no workers. Enrichment is synchronous and inline.
- All contract sections (Job Identity, Deduplication, Lifecycle, Priority, Creation, Execution, Worker Coordination, Idempotency, Failure Handling, Observability) are gaps.

### Risk Level

**High.** Implementing the contract means building a new subsystem: job store, queue semantics, worker pool, job lifecycle, priority ordering, deduplication, retry, and observability. Ingest and re-enrich flows must be refactored to “enqueue jobs” instead of “run enrichers.” This is a subsystem rewrite.

---

## 6. ProcessorExecutionContract

### Current Implementation

- **Invocation:** Enrichers are called with a single argument: the discovered item (dict or DiscoveredItem). No explicit (processor_id, target_type, target_id) or job_id or execution timestamp context.
- **Inputs:** Enrichers receive the item (path_uri, raw_labels, probed, editorial, etc.); they do not receive a formal “target identifier” or “execution context.” They can read what’s on the item; they do not “modify catalog entities directly” (they return an enriched item; the caller persists).
- **Outputs:** Enrichers mutate the item (e.g. add raw_labels, probed); they do not return a separate “structured metadata result” object conforming to ProcessorMetadataContract. Mapping from item to asset/child tables is done in the ingest service and in `enrich_asset`, not by a “processor runtime.”
- **Result validation:** No validation against ProcessorMetadataContract before apply; no “processor runtime” that validates then writes.
- **Metadata application:** Application is done in `collection_ingest_service` and `asset_enrich` (and `persist_asset_metadata`); there is no single “processor runtime” that applies results per ownership rules. Operator-owned fields are not explicitly modeled; enrichers do not overwrite operator fields by design but there is no formal ownership tagging.
- **Idempotency:** Enrichers are effectively idempotent (e.g. ffprobe on same file → same result). Not formally guaranteed.
- **Failure:** On enricher exception, the item is often skipped or the error is appended to stats; there is no “job” to mark failed, no retry policy, no “do not modify metadata” guarantee (the item may have been partially enriched).
- **Time limits:** FFprobeEnricher has a timeout; there is no global “processor runtime” limit or job-level limit.
- **Execution isolation:** Enrichers run inside the same process and transaction as ingest; they are not isolated from “catalog reconciliation.” Scheduler does not run them.
- **Observability:** Logging is ad hoc; no standard events like “processor started / completed / failed” or duration recording.

### Contract Compliance

**Partially complies.**

- Processors (enrichers) do not modify the catalog directly; the caller applies results. They are not triggered by jobs; they do not receive execution context or return a contract-shaped result; there is no result validation or processor runtime; failure and observability do not match the contract.

### Differences

- No job-based invocation; no (processor_id, target_type, target_id) or job_id/timestamp context.
- No structured “processor result” or validation against ProcessorMetadataContract before apply.
- No dedicated “processor runtime” that applies results and enforces ownership.
- No job failure state or retry; no formal “do not modify metadata on failure.”
- No execution time limits at runtime level; no standard observability events/duration.

### Risk Level

**Medium.** Alignment requires: (1) job-driven invocation with context; (2) processors returning structured results and a runtime that validates and applies them; (3) failure handling and observability; (4) optional time limits. Depends on a job queue (ProcessorJobQueueContract) but does not require rewriting every enricher from scratch.

---

## 7. ProcessorMetadataContract

### Current Implementation

- **Structured metadata:** Core fields (duration_ms, video_codec, audio_codec, container, etc.) are stored on `Asset` and in child tables (`AssetEditorial`, `AssetProbed`, `AssetStationOps`, `AssetRelationships`, `AssetSidecar`). These are indexed/queryable. Enricher output is mapped onto Asset and these tables (e.g. from raw_labels and probed in `collection_ingest_service` and `asset_enrich`).
- **Flexible metadata:** No `processor_outputs` table. Extra enricher output lives in the item’s `probed` (or similar) and is persisted in `AssetProbed.payload` (JSONB) or similar child payloads. There is no per-processor, per-target table with (processor_id, target_type, asset_id or media_id, payload_json, created_at).
- **Metadata ownership:** No explicit ownership (Source / Processor / Operator) on fields. Operator edits are not tagged; there is no rule that “processors MUST NOT overwrite operator-owned fields” enforced by schema or runtime. In practice, re-enrich overwrites probe-derived fields; operator-only fields are not clearly separated.

### Contract Compliance

**Partially complies.**

- Structured metadata is stored in structured tables. Flexible/processor-specific output is stored in JSONB (e.g. AssetProbed.payload) but not in a dedicated processor_outputs table. Ownership is not modeled; processor vs operator overwrite is not enforced.

### Differences

- No `processor_outputs` table with (processor_id, target_type, asset_id or media_id, payload_json, created_at).
- No ownership tagging (Source / Processor / Operator) on fields; no enforcement that “Processors MUST NOT overwrite operator-owned fields.”
- “Processors MAY update fields they own when media changes” is not explicitly modeled.

### Risk Level

**Low to medium.** Adding a processor_outputs table and optional ownership is a manageable schema and wiring change. Enforcing “do not overwrite operator-owned” requires defining which fields are operator-owned and where to check (e.g. in the apply layer or runtime). No full subsystem rewrite.

---

## Summary Table

| Contract                       | Compliance       | Risk Level |
|-------------------------------|------------------|------------|
| ContainerDiscoveryContract    | Partial          | Medium     |
| CatalogReconciliationContract  | Partial          | Medium     |
| AssetMediaIdentityContract    | Does not comply  | High       |
| ProcessorCapabilityContract   | Partial          | Medium     |
| ProcessorJobQueueContract     | Does not comply  | High       |
| ProcessorExecutionContract   | Partial          | Medium     |
| ProcessorMetadataContract     | Partial          | Low–Medium |
