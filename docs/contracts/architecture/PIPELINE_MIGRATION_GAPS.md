# Pipeline Migration Gaps

This document identifies gaps between the current system and the contract-defined architecture and recommends **incremental** migration strategies. It is organized by subsystem and does not prescribe a single big-bang rewrite.

---

## 1. Discovery

### Current Behavior

- **Source** and **Collection** (containers) exist; discovery is performed per collection via importers (`importer.discover()` or `importer.discover_scoped()`). Importers are built from `Source` config and `Collection` in `construct_importer_for_collection()`.
- Discovery is **fused** with reconciliation and enrichment: one code path discovers items, resolves paths, runs the enricher pipeline inline, then creates or skips assets and reconciles stale ones. There is no separate “container refresh” that only discovers locators.
- There is no first-class **locator** type; the closest notion is `path_uri` (and `provider_key`) on discovered items. Identity is derived later as `canonical_key` / `canonical_key_hash`.
- Discovery is **CLI-triggered only** (`source ingest`, `collection ingest`). No daemon or scheduler runs container refresh; there is no guarantee that refresh runs before playout horizon expansion.

### Required Behavior (Contracts)

- **ContainerDiscoveryContract:** Media discovery MUST occur through Containers. Container refresh performs: (1) discover locators, (2) compare with catalog, (3) apply reconciliation, (4) enqueue processor jobs. Discovery timing: container refresh MUST run before playout horizon expansion (when daemon-driven).
- **CatalogReconciliationContract:** Reconciliation workflow step 1 is “Discover locators within the container” as a distinct step before compare and mutate.

### Gap Description

- Discovery is not a separate phase; it is embedded in ingest. There is no “discover locators only” API or step.
- Locator is not an explicit type or tuple `(source_id, container_id, locator)`; identity is canonical_key_hash.
- No daemon/scheduler trigger for container refresh; no ordering guarantee relative to horizon expansion.
- “Enqueue processor jobs” is absent (covered under job queue).

### Migration Strategy

1. **Extract a discovery-only phase (incremental).** Add a function or service that, for a given collection (and optional scope), calls the importer to discover items and returns a list of **locator-like** records (e.g. a dataclass with source_id, container_id, locator, optional fingerprint fields). Do not change importer return types yet; map existing `path_uri`/`provider_key` to a canonical locator string (e.g. same as today’s canonical_key or a new format). Call this from the existing ingest path so behavior is unchanged; the existing “create or skip” and reconciliation logic still run after this phase.
2. **Introduce locator identity in the data model (optional, phased).** If/when introducing Media or a formal locator table, add `(source_id, container_id, locator)` and migrate from canonical_key_hash in stages (e.g. backfill locator from existing Asset.uri and collection/source, then use locator for new writes). Until then, keep using canonical_key_hash as the effective “locator identity” and ensure the discovery phase outputs something that can later map to (source_id, container_id, locator).
3. **Daemon/scheduler trigger later.** Once a scheduler or daemon exists that drives horizon expansion, add a “container refresh” step (calling the discovery + reconciliation pipeline) that runs before horizon expansion. CLI ingest remains a valid trigger; the contract allows both.

---

## 2. Reconciliation

### Current Behavior

- Reconciliation is **embedded** in `CollectionIngestService.ingest_collection()`: after processing each discovered item (create or skip by canonical_key_hash), assets in the collection whose canonical_key_hash was not in the “seen” set are marked `is_deleted=True`, `deleted_at=now`. No separate “compare” or “determine outcome” step; no fingerprint comparison; no “update if fingerprint differs.”
- Trigger is **CLI only**; no scheduler daemon.
- **Present / absent → create** and **absent / present → soft-delete** are implemented. **Present / present → update if fingerprint differs** is not: existing asset causes skip. **Present / present unchanged → no action** is effectively what happens when we skip.
- Sidecars are merged in `handle_ingest()` during the same pass; there is no explicit “detect sidecar metadata additions or changes” step.
- Processor jobs are not enqueued; enrichers run inline.
- Idempotency: re-running with no source changes largely leaves the catalog unchanged (skips and no new deletes for already-deleted). Observability is ad hoc logging (e.g. ingest_reconcile_removed).

### Required Behavior (Contracts)

- **CatalogReconciliationContract:** Workflow in order: (1) discover locators, (2) detect sidecar changes, (3) compare with catalog, (4) determine outcome, (5) apply catalog mutations, (6) enqueue processor jobs. Outcomes: create asset+media, update media if fingerprint differs, no action if unchanged, mark media unavailable if absent. Media retirement: mark unavailable, do not delete. Idempotent; observable (asset created, media created/updated/unavailable, jobs enqueued).

### Gap Description

- Workflow is a single fused path; no distinct “compare” or “determine outcome” or “enqueue jobs” steps.
- No fingerprint; “existing” is same canonical_key_hash only. No update path when fingerprint changes.
- “Mark unavailable” is implemented as soft-delete (row kept, is_deleted set); contract says “mark unavailable” and “do not delete”—semantically close but no separate `unavailable` flag.
- No Media entity (see asset/media identity). No enqueue of processor jobs.
- Sidecar detection is implicit in the merge step, not a separate step.

### Migration Strategy

1. **Keep reconciliation in the same process, split phases.** After extracting the discovery phase (see Discovery), refactor the ingest service into explicit steps: (a) discover locators (and optional sidecar detection), (b) load current catalog state for that collection (e.g. by canonical_key_hash or future locator), (c) compute outcome per item (create / update / no_action / mark_unavailable), (d) apply mutations (create asset, or update existing, or mark unavailable), (e) enqueue processor jobs (once a queue exists). Run (e) as a no-op or best-effort until the job queue exists. This preserves current behavior while matching the contract’s workflow shape.
2. **Add fingerprint and “update if differs” without Media first.** On the Asset (or current single-entity) model, add optional fingerprint fields (e.g. file hash, size, mtime) or derive from existing fields. In “compare” phase, when a locator already exists in the catalog, compare fingerprint; if different, set outcome to “update” instead of “no action.” In “apply” phase, implement update: refresh fingerprint and source-derived metadata, and enqueue processor jobs (when queue exists). This satisfies “update media if fingerprint differs” and “do not create new Media entry” at the Asset level; later, when Media exists, the same logic can apply to Media.
3. **Unavailable vs deleted (optional).** If desired, add an `unavailable` flag (or use `is_deleted` as “unavailable” and reserve “deleted” for a future hard-delete). Document that “mark unavailable” is implemented as soft-delete; rename or extend only if product needs a distinction.
4. **Sidecar step.** Make “detect sidecar metadata additions or changes” an explicit step (e.g. after discovery, before or as part of compare) that records which items have new/changed sidecars; use that to drive “enqueue processor jobs” for those items when the queue exists.
5. **Observability.** Add a small audit or event log for reconciliation (e.g. “asset_created”, “asset_updated”, “asset_marked_unavailable”, “jobs_enqueued”) so that observability matches the contract; keep existing logs.

---

## 3. Asset/Media Identity

### Current Behavior

- **Asset** is the only catalog entity for playable content; it holds both “logical program” and “playable file” data (uri, canonical_uri, duration_ms, codecs, etc.). There is no **Media** entity.
- Identity is **canonical_key** and **canonical_key_hash** (from `canonical_key_for()` and `canonical_hash()`), scoped by collection. Uniqueness is per (collection_uuid, canonical_key_hash). Duplicate → skip; no “update when fingerprint changes”; no “flag for operator review.”
- Scheduler and playout reference **Asset** only; there is no “select Media variant” step.
- When a previously seen item disappears from discovery, the asset is **soft-deleted** (is_deleted, deleted_at); the row is not removed.

### Required Behavior (Contracts)

- **AssetMediaIdentityContract:** Asset = logical program; Media = playable file. Every Media belongs to exactly one Asset; an Asset may have multiple Media variants. Identity: (source_id, container_id, locator) uniquely identifies a Media record. Media replacement: same locator, fingerprint changed → update Media, enqueue processors; do not create a new Media. Media retirement: mark unavailable, do not delete. Duplicate detection: flag for operator review when media may belong to existing asset.
- **CatalogReconciliationContract:** Create Media record, create Asset if none exists, attach media to asset; identity (source_id, container_id, locator) unique across Media.

### Gap Description

- No Media entity; Asset conflates program and file. No multiple Media per Asset; no variant selection at playout.
- Identity is (collection_uuid, canonical_key_hash), not (source_id, container_id, locator).
- No “update Media when fingerprint changes” (today: skip). No explicit “mark unavailable” flag (soft-delete used). Duplicate handling is “skip,” not “flag for operator review.”

### Migration Strategy

1. **Defer Media entity until needed (incremental).** The contract’s “Asset = program, Media = file” can be approached in stages. **Phase A:** Keep a single Asset table and treat it as “one Asset per playable file” (current behavior). Document that Asset currently represents the contract’s “Media” and that “logical program” is implicit (one-to-one). Ensure scheduler and playout continue to reference Asset only. No schema change yet.
2. **Introduce locator and fingerprint on Asset (low risk).** Add columns or a small table that store (source_id, container_id, locator) and optional fingerprint for the **current** Asset row. Backfill from existing Source/Collection and uri/canonical_key. Use this for uniqueness and “update if fingerprint differs” in reconciliation. This gets contract identity and update semantics without a Media table.
3. **Introduce Media only when variants are required.** When product needs multiple playable files per logical program (e.g. fullscreen vs widescreen), add a Media table: (media_id, asset_id, source_id, container_id, locator, fingerprint, unavailable, …). Migrate: one Asset per current “file” → create one Asset and one Media per current row, then later support “attach new Media to existing Asset” for variants. Scheduler still references Asset; playout resolution “Asset → Media” chooses one Media (e.g. by policy or default). This is a larger change; do it only when needed.
4. **Duplicate handling.** When (source_id, container_id, locator) or canonical_key_hash already exists for another Asset, instead of silently skipping, write a “duplicate candidate” or review record and/or log for operator review; keep skip as default behavior until operator tooling exists. Low risk.

---

## 4. Processor Capability

### Current Behavior

- **Enrichers** (FFprobeEnricher, InterstitialTypeEnricher, LoudnessEnricher) are registered in `ENRICHERS` by type name. They have `name`, `scope` (ingest/playout), and `get_config_schema()` (params, description). They do **not** declare target type (MEDIA/ASSET), required metadata, or produced metadata.
- Invocation is from ingest or re-enrich (reprobe, apply enrichers) only; no job queue, no “metadata demand.” Batch = inline loop over items. Scheduler does not run processors; reconciliation **does** run enrichers inline (contract says reconciliation should enqueue jobs, not run them).

### Required Behavior (Contracts)

- **ProcessorCapabilityContract:** Processors MUST declare id, target type, required metadata, produced metadata. Target type MEDIA or ASSET. Batch operations enqueue individual jobs. Processors MUST run asynchronously via the processor job queue; scheduler MUST NOT execute processor workloads directly.

### Gap Description

- No formal declaration of target type or required/produced metadata. Processors run synchronously in the ingest path; no enqueue of jobs. Batch is inline, not “enqueue one job per target.”

### Migration Strategy

1. **Add capability declaration without changing execution (incremental).** For each enricher type, add a small capability record or config: `target_type` (MEDIA for current enrichers), `required_metadata` (e.g. [] or [path_uri]), `produced_metadata` (e.g. [duration_ms, video_codec, audio_codec] for ffprobe). Store in code or in the existing Enricher table (new columns or config). Do not change how enrichers are invoked yet; this is additive and enables future job selection and validation.
2. **Use capability when the job queue exists.** When enqueueing jobs, use target_type and produced_metadata to decide which processors to run and to validate results. Keep existing inline execution path until the queue is in place.
3. **Move execution off reconciliation only when the queue exists.** Once the job queue and workers exist, change reconciliation to “enqueue processor jobs” instead of running the pipeline inline. Scheduler already does not run processors; no change there. This completes compliance without rewriting enricher implementations.

---

## 5. Job Queue

### Current Behavior

- There is **no** processor job queue: no job table, no workers, no lifecycle (pending/running/completed/failed), no priority, no deduplication, no retry. Enrichers are invoked directly in the ingest and re-enrich code paths.

### Required Behavior (Contracts)

- **ProcessorJobQueueContract:** Jobs identified by (processor_id, target_type, target_id). Deduplication: do not create duplicate job; may escalate priority; do not reset state. Lifecycle: pending → running → completed | failed. Priority (LOW/NORMAL/HIGH/CRITICAL); workers process higher before lower. Creation from reconciliation, operator CLI, metadata demand. Workers retrieve job, execute processor, update state. One worker per job at a time. Retry: reset to pending, preserve identity. Observability: queued/running/completed/failed; timestamps; log execution events.

### Gap Description

- The entire job queue subsystem is missing: store, semantics, workers, lifecycle, priority, deduplication, retry, observability.

### Migration Strategy

1. **Add the queue as a parallel path first (incremental).** Introduce a `processor_jobs` table (or equivalent) with: job_id, processor_id, target_type, target_id, status (pending/running/completed/failed), priority, created_at, started_at, completed_at, error_message, etc. Implement “enqueue” API: when reconciliation or CLI would have run an enricher, instead insert a row (and deduplicate by (processor_id, target_type, target_id) per contract). **Do not** remove the existing inline execution yet; either call the enqueue API and then still run inline for the same items (so behavior is unchanged), or run only inline until workers exist. Goal: queue and schema exist, ingest can enqueue, no behavioral change until workers are added.
2. **Add workers that drain the queue.** Implement one or more workers (same process or separate) that: claim a job (update status to running, enforce “only one worker per job”), load target (e.g. Asset by target_id), invoke the processor via the processor runtime (see Processor Execution), apply results, update job to completed/failed, log. Use priority ordering when selecting the next job. On failure, set status to failed and record error; support retry (e.g. operator command or retry-all) that sets status back to pending. This satisfies execution, coordination, and observability without rewriting ingest in one go.
3. **Switch reconciliation to “enqueue only.”** Once workers are reliable, remove the inline enricher pipeline from the reconciliation path; reconciliation only enqueues jobs. Re-enrich (reprobe, apply enrichers) can either enqueue as well or remain inline for a transition period. Prefer enqueue for consistency.
4. **Add priority escalation and timestamps.** Use priority column and ordering in worker dequeue; add created_at/started_at/completed_at and standard log events (processor_started, processor_completed, processor_failed) so observability matches the contract.

---

## 6. Processor Execution

### Current Behavior

- Enrichers are called with the **discovered item** (dict or DiscoveredItem); no job context (processor_id, target_type, target_id, job_id, timestamp). They mutate the item (e.g. add raw_labels, probed); the **caller** (ingest service or `enrich_asset`) maps results to Asset and child tables. No structured “processor result” or validation against ProcessorMetadataContract; no single “processor runtime.” Failure: errors are recorded in stats or the item is skipped; no job failure state or “do not modify metadata” guarantee. FFprobe has a timeout; no global execution time limit. Observability is ad hoc.

### Required Behavior (Contracts)

- **ProcessorExecutionContract:** Workers invoke with processor_id, target_type, target_id (and optional context: job_id, timestamp). Processors receive target identifier, locator, source/derived/sidecar metadata; MUST NOT modify catalog directly; return structured result. Result validated against ProcessorMetadataContract before apply; processor runtime applies per ownership rules. On failure: job marked failed, no metadata change, details recorded. Optional execution time limits. Isolated from scheduler and reconciliation. Observable: processor started/completed/failed; duration recorded.

### Gap Description

- No job-based invocation or execution context. No structured result type or validation before apply. No dedicated processor runtime; application is ad hoc in ingest and asset_enrich. No job failure semantics or standard observability.

### Migration Strategy

1. **Introduce a processor runtime layer (incremental).** Add a small “processor runtime” module used by **workers only** (and optionally by the existing inline path for compatibility). Responsibility: given (processor_id, target_type, target_id), load target and build execution context (processor_id, target_type, target_id, job_id, timestamp); call the enricher with that context and the target data; accept a **result** (e.g. dict with a “metadata” section). Map the current enricher’s mutated item back into that result shape so existing enrichers do not need to change their implementation yet—the runtime adapts “item with raw_labels/probed” to “structured result.” Then the runtime validates (e.g. against ProcessorMetadataContract or a allowlist of fields) and applies to the catalog (existing persist_asset_metadata or equivalent), enforcing “do not overwrite operator-owned” when ownership is defined. This gives a single place for invocation, validation, and apply.
2. **Keep enrichers as-is first.** Enrichers continue to accept an item and return an item; the runtime wraps that in the contract’s invocation and result shape. Later, optionally, allow enrichers to return a structured result dict for new processors.
3. **Failure and observability.** In the runtime, on exception: do not apply metadata; when called from a worker, the worker sets job to failed and records the error. Add standard log events (processor_started, processor_completed, processor_failed) and duration. Optional: add a global or per-job execution time limit and terminate/flag job on timeout.
4. **Ownership.** When ProcessorMetadataContract ownership is implemented (see Metadata Storage), the runtime checks operator-owned fields and skips overwriting them when applying processor results.

---

## 7. Metadata Storage

### Current Behavior

- **Structured metadata** (duration_ms, video_codec, audio_codec, container, editorial, probed, etc.) is stored on **Asset** and in child tables (AssetEditorial, AssetProbed, AssetStationOps, AssetRelationships, AssetSidecar). Enricher output is mapped into these in the ingest service and in `enrich_asset`; no per-processor table.
- **Flexible/processor-specific** output lives in JSONB payloads (e.g. AssetProbed.payload); there is no **processor_outputs** table with (processor_id, target_type, asset_id or media_id, payload_json, created_at).
- **Ownership** (Source / Processor / Operator) is not modeled; there is no enforcement that “processors MUST NOT overwrite operator-owned fields.”

### Required Behavior (Contracts)

- **ProcessorMetadataContract:** Structured metadata in structured tables; flexible processor output in a **processor_outputs** table (processor_id, target_type, asset_id or media_id, payload_json, created_at). Ownership: Source, Processor, Operator; processors MUST NOT overwrite operator-owned fields; processors MAY update their own fields when media changes.

### Gap Description

- No processor_outputs table. No ownership tagging or enforcement. Current storage is sufficient for structured and JSON payloads but does not separate by processor or enforce ownership.

### Migration Strategy

1. **Add processor_outputs table (incremental).** Create a table: processor_id, target_type, target_id (asset_id or media_id), payload_json, created_at (and optionally updated_at). When the processor runtime applies results, for any “flexible” or processor-specific fields that are not part of the core structured schema, write (or upsert) a row per (processor_id, target_id). Existing Asset/AssetProbed/etc. can remain the primary store for core fields; processor_outputs holds extra per-processor payloads. Backfill not required for old data; new runs populate it. Low risk.
2. **Define ownership for core fields (phased).** Define which Asset (and child) fields are Source (importer), Processor (enricher), or Operator (manual). Store this in config or code (e.g. a mapping “duration_ms → processor”, “approved_for_broadcast → operator”). In the processor runtime (and in any re-enrich path), before applying processor result, skip or clear operator-owned fields from the update. Add tests so that re-enrich does not overwrite operator-approved or operator-edited fields. This satisfies “Processors MUST NOT overwrite operator-owned fields” without a full schema change.
3. **“Processors MAY update fields they own when media changes.”** Document that when reconciliation marks “update if fingerprint differs,” the apply step and job enqueue allow processors to refresh their fields; the runtime already updates only the fields it owns when applying a processor result. No code change if the runtime is scoped to processor-owned fields.

---

## Summary: Ordering and Dependencies

- **Discovery:** Extract discovery phase and optional locator shape first; no dependency on other subsystems.
- **Reconciliation:** Split workflow into contract steps; add fingerprint and “update if differs” on current Asset model; depends only on discovery phase and (later) job enqueue.
- **Asset/Media identity:** Start with locator/fingerprint on Asset and “update if differs”; introduce Media entity only when multiple variants are needed.
- **Processor capability:** Add declarations (target type, produced metadata) anytime; used by queue and runtime later.
- **Job queue:** Add table and enqueue API first (parallel to inline execution); then workers and runtime; then switch reconciliation to enqueue-only.
- **Processor execution:** Introduce processor runtime used by workers (and optionally inline); add result shape, validation, and apply; add observability and failure handling.
- **Metadata storage:** Add processor_outputs table and ownership rules; runtime and apply layer use them.

Prefer doing discovery and reconciliation phases first, then job queue + runtime + metadata storage, and defer Media entity until product needs variants.
