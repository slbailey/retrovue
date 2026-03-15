# Pipeline Migration Task Plan

This document is a detailed implementation task plan for migrating the current pipeline to the contract-driven architecture. Tasks are ordered so they can be executed sequentially (e.g. by Cursor). Each phase includes goals, concrete tasks, risk mitigation, and validation steps.

**Reference:** `PIPELINE_MIGRATION_ARCHITECTURE.md`, `docs/contracts/core/*.md`, `CURRENT_PIPELINE_INVENTORY.md`, **`CONTRACT_TEST_HARNESS.md`** (defines how contract tests enforce the contracts), **`PIPELINE_MIGRATION_FEATURE_FLAGS.md`** (defines flags and migration states to avoid double processing), **`ASSET_IDENTITY_MIGRATION.md`** (asset identity backfill and unique constraint so Phase 2 does not stall).

---

## Phase 0 — Contract Test Harness

### Goals

- Define and create the **contract test harness** so that the catalog and processor contracts are enforced by tests, not documentation only.
- Add one test module per contract with the required test cases (names and intent specified in `CONTRACT_TEST_HARNESS.md`). Tests may be skipped until the implementing phase is done; the harness ensures traceability and a single place to implement each guarantee.

### Tasks

1. **Create the harness specification document.**  
   Ensure `docs/contracts/architecture/CONTRACT_TEST_HARNESS.md` exists and specifies: purpose (traceability, enforcement); location (`pkg/core/tests/contracts/`); naming (`test_*_contract.py`); convention (module docstring references contract path; deterministic; no DB destruction); required test suites and test cases per contract with exact test method names and what each verifies; phase–test mapping; how to run contract tests. This document is the single source of truth for “what contract tests exist and what they verify.”

2. **Create skeleton test_container_discovery_contract.py.**  
   In `pkg/core/tests/contracts/test_container_discovery_contract.py`, add module docstring referencing `docs/contracts/core/ContainerDiscoveryContract_v0.1.md`. Add class `TestContainerDiscoveryContract` with methods: `test_discovery_occurs_through_containers`, `test_source_may_have_multiple_containers`, `test_discovery_returns_locators_without_catalog_writes`, `test_locator_deterministic_for_same_item`. Each method body: `pytest.skip("Phase 1 not yet implemented")` and a one-line docstring stating the contract guarantee (see CONTRACT_TEST_HARNESS.md). Optional: `test_discovery_scope_passed_to_importer`.

3. **Create skeleton test_catalog_reconciliation_contract.py.**  
   In `pkg/core/tests/contracts/test_catalog_reconciliation_contract.py`, add module docstring referencing `docs/contracts/core/CatalogReconciliationContract_v0.1.md`. Add class `TestCatalogReconciliationContract` with methods: `test_reconciliation_idempotency`, `test_reconciliation_outcome_create_when_absent`, `test_reconciliation_outcome_no_action_when_unchanged`, `test_reconciliation_outcome_update_when_fingerprint_differs`, `test_reconciliation_outcome_mark_unavailable_when_absent_from_source`, `test_reconciliation_workflow_steps_in_order`, `test_locator_uniqueness`. Each: `pytest.skip("Phase 2 not yet implemented")` and docstring per harness.

4. **Create skeleton test_asset_media_identity_contract.py.**  
   In `pkg/core/tests/contracts/test_asset_media_identity_contract.py`, add module docstring referencing `docs/contracts/core/AssetMediaIdentityContract_v0.1.md`. Add class `TestAssetMediaIdentityContract` with methods: `test_scheduler_references_assets_not_media`, `test_media_identity_tuple_unique`, `test_same_locator_fingerprint_change_updates_no_new_entry`, `test_locator_disappears_mark_unavailable_not_delete`. Each: `pytest.skip` (Phase 1 or 2 as appropriate) and docstring. If a test is already covered by `test_asset_invariants.py` (e.g. INV-ASSET-MEDIA-IDENTITY), the skeleton may call that test or defer to it and mark “see test_asset_invariants”.

5. **Create skeleton test_processor_job_queue_contract.py.**  
   In `pkg/core/tests/contracts/test_processor_job_queue_contract.py`, add module docstring referencing `docs/contracts/core/ProcessorJobQueueContract_v0.1.md`. Add class `TestProcessorJobQueueContract` with methods: `test_job_identity_unique`, `test_job_queue_deduplication`, `test_job_lifecycle_pending_to_running_to_completed`, `test_job_lifecycle_pending_to_running_to_failed`, `test_job_retry_resets_to_pending_preserves_identity`, `test_job_priority_ordering`, `test_worker_claims_one_job_at_a_time`, `test_observable_state_queued_running_completed_failed`. Each: `pytest.skip("Phase 3 not yet implemented")` and docstring.

6. **Create skeleton test_processor_execution_contract.py.**  
   In `pkg/core/tests/contracts/test_processor_execution_contract.py`, add module docstring referencing `docs/contracts/core/ProcessorExecutionContract_v0.1.md`. Add class `TestProcessorExecutionContract` with methods: `test_processor_receives_execution_context`, `test_processor_failure_does_not_modify_metadata`, `test_processor_result_validated_before_apply`, `test_execution_isolated_from_scheduler`, `test_observable_events_started_completed_failed_duration`. Each: `pytest.skip("Phase 4 not yet implemented")` and docstring.

7. **Create skeleton test_processor_metadata_contract.py.**  
   In `pkg/core/tests/contracts/test_processor_metadata_contract.py`, add module docstring referencing `docs/contracts/core/ProcessorMetadataContract_v0.1.md`. Add class `TestProcessorMetadataContract` with methods: `test_processor_does_not_overwrite_operator_owned_field`, `test_structured_metadata_in_structured_tables`, `test_flexible_output_in_processor_outputs`, `test_processor_may_update_own_fields_when_media_changes`. Each: `pytest.skip("Phase 5 not yet implemented")` and docstring.

8. **Update tests/contracts README.**  
   In `pkg/core/tests/contracts/README.md`, add a subsection “Catalog and processor contracts” that points to `docs/contracts/architecture/CONTRACT_TEST_HARNESS.md` and lists the six test modules (test_container_discovery_contract, test_catalog_reconciliation_contract, test_asset_media_identity_contract, test_processor_job_queue_contract, test_processor_execution_contract, test_processor_metadata_contract) and states that these tests enforce the behavior in `docs/contracts/core/`.

9. **Run contract tests.**  
   Run `pytest pkg/core/tests/contracts/test_container_discovery_contract.py pkg/core/tests/contracts/test_catalog_reconciliation_contract.py pkg/core/tests/contracts/test_asset_media_identity_contract.py pkg/core/tests/contracts/test_processor_job_queue_contract.py pkg/core/tests/contracts/test_processor_execution_contract.py pkg/core/tests/contracts/test_processor_metadata_contract.py -v`. All tests should be skipped (exit 0). No test should fail or error.

10. **Add migration feature flags to settings.**  
    In `pkg/core/src/retrovue/infra/settings.py`, add three optional boolean fields with defaults `false`: `enable_fingerprint_updates` (alias `ENABLE_FINGERPRINT_UPDATES`), `enable_processor_queue` (alias `ENABLE_PROCESSOR_QUEUE`), `enable_runtime_execution` (alias `ENABLE_RUNTIME_EXECUTION`). Document in docstring or comment that these gate Phase 2/3/4 behavior; see `docs/contracts/architecture/PIPELINE_MIGRATION_FEATURE_FLAGS.md`. Do not change any ingest or reconciliation behavior in this task; only add the settings so later phases can read them.

### Risk Mitigation

- Skeleton tests do not change existing behavior; they only add skipped tests. Existing contract and ingest tests continue to run as before.
- The harness document is the authority for test names and intent; implementation of each test is done in the phase that implements the corresponding behavior.

### Validation

- All six test files exist under `pkg/core/tests/contracts/`.
- Each file has the required test methods and module docstring referencing the contract.
- `pytest` on the six files completes with all tests skipped (no failures).
- `CONTRACT_TEST_HARNESS.md` exists and is linked from the task plan and from `pkg/core/tests/contracts/README.md`.
- Migration feature flags exist in settings (`ENABLE_FINGERPRINT_UPDATES`, `ENABLE_PROCESSOR_QUEUE`, `ENABLE_RUNTIME_EXECUTION`); defaults `false`. See `PIPELINE_MIGRATION_FEATURE_FLAGS.md`.

---

## Phase 1 — Discovery Refactor

### Goals

- Introduce a **discovery-only** step that returns locator-like records (source_id, container_id, locator, optional fingerprint) without writing to the catalog.
- Align with ContainerDiscoveryContract: “discover locators” as a distinct step before compare and reconcile.
- Leave existing ingest behavior unchanged: `CollectionIngestService.ingest_collection()` still creates/skips/reconciles using the same logic; it will call the new discovery step and map its output into the existing flow.

### Tasks

1. **Create the DiscoveredLocator type.**  
   In `pkg/core/src/retrovue/` add a module (e.g. `catalog/discovery.py` or `usecases/container_discovery.py`). Define a dataclass or typed structure `DiscoveredLocator` with fields: `source_id` (UUID or str), `container_id` (UUID or str), `locator` (str), and optional `fingerprint` (e.g. `size: int | None`, `mtime: float | None`, or a small `Fingerprint` dataclass). Add `__all__` and docstring referencing ContainerDiscoveryContract.

2. **Implement `discover_locators()`.**  
   In the same module, implement a function `discover_locators(collection, importer, *, title=None, season=None, episode=None) -> list[DiscoveredLocator]`. It must: (a) call `importer.discover()` or `importer.discover_scoped(title, season, episode)` if scope is provided and the importer supports it; (b) for each returned item, derive `source_id` from `collection.source_id`, `container_id` from `collection.uuid`; (c) derive `locator` from the item (e.g. use existing `canonical_key_for(item, collection, provider)` or a stable string from `path_uri`/`provider_key`); (d) set optional fingerprint from item’s `size`, `last_modified` (or equivalent). Return the list. Do not perform path resolution or enrichment; do not touch the database.

3. **Integrate discovery into CollectionIngestService.**  
   In `pkg/core/src/retrovue/cli/commands/_ops/collection_ingest_service.py`, at the start of the ingest work (after validation and pipeline build), call `discover_locators(collection, importer, title=title, season=season, episode=episode)`. Build a mapping from `DiscoveredLocator.locator` to the original importer item (e.g. by running importer.discover() again and matching on canonical_key, or by having `discover_locators` return both the locator record and the raw item). Use the existing loop over `discovered_items` but ensure the set of items (or canonical_key_hashes) is driven by the discovery step so that behavior is identical: same items, same create/skip/reconcile outcomes. Prefer: run discovery once, then in the loop iterate over a list that combines locator + raw item so that downstream code (path resolution, enricher pipeline, handle_ingest, canonical_key_for) still receives the same inputs. Document that discovery is now the single source of “what was discovered.”

4. **Add unit tests for discovery.**  
   In `pkg/core/tests/` add or extend a test module (e.g. `usecases/test_container_discovery.py` or `catalog/test_discovery.py`). Tests: (a) mock importer returning a list of dicts or DiscoveredItems with path_uri, provider_key, size; assert `discover_locators(collection, importer)` returns one DiscoveredLocator per item; assert `locator` is deterministic for the same item (run twice, same locator string). (b) Assert source_id and container_id match the collection’s source_id and uuid. (c) If importer has discover_scoped, test that scope parameters are passed through.

5. **Run existing ingest contract tests.**  
   Run `pytest pkg/core/tests/contracts/test_collection_ingest_contract.py pkg/core/tests/contracts/test_source_ingest_contract.py pkg/core/tests/contracts/test_collection_ingest_data_contract.py` (and any other ingest-related contract tests). Fix any regressions so all pass. Optionally add one test that explicitly asserts “after ingest, discovery step was used” (e.g. by asserting call count or that results match a prior baseline).

### Risk Mitigation

- Do not change the signature or behavior of `importer.discover()` / `discover_scoped()`; only consume their output.
- Do not remove the existing “discovered_items” loop; keep path resolution, enricher pipeline, handle_ingest, and create/skip/reconcile logic unchanged. Discovery becomes the source of the list; the rest of the code path stays the same.
- If integrating discovery requires a second call to the importer (e.g. to get raw items), ensure the importer is stateless and that two calls with the same scope return the same items in the same order, so that create/skip/reconcile counts and final catalog state are unchanged.

### Validation

- **Contract harness:** All tests in `test_container_discovery_contract.py` pass (skips removed; see CONTRACT_TEST_HARNESS.md).
- All existing ingest and source-ingest contract tests pass.
- New unit tests for `discover_locators` pass (deterministic locator, one record per item, source_id/container_id correct).
- Manual or automated run of `retrovue collection ingest <collection>` (or source ingest) produces the same created/skipped/reconciled counts and final asset state as before Phase 1 (compare against a known baseline or a run without the discovery refactor).

---

## Phase 2 — Reconciliation Layer

### Goals

- Refactor ingest into the six-step reconciliation workflow: discover → detect sidecars → compare → determine outcome → apply → enqueue jobs.
- Add fingerprint to the Asset model and implement “update if fingerprint differs” (outcome = update; refresh fingerprint and source-derived metadata; call enqueue stub).
- Introduce outcome type: create | update | no_action | mark_unavailable. Enqueue step is a stub (no-op or log-only) until Phase 3.
- Add **processor capability registry** (processor_id, target_type, produced_metadata, required_metadata) in Phase 2 so the job queue and runtime know which processors to enqueue and how to validate results; otherwise Phase 3 enqueue cannot resolve target_type or filter by capability.

### Tasks

1. **Add source_id and fingerprint fields to Asset.**  
   In `pkg/core/src/retrovue/domain/entities.py` and an Alembic migration, add: (a) **source_id** (UUID, nullable initially; same type as `collections.source_id`, FK to sources if applicable) so that contract identity (source_id, container_id, locator) can be stored. (b) Optional fingerprint columns (e.g. `file_size`, `file_mtime`, or `fingerprint_hash`). Update the Asset model class. Do not backfill fingerprint in this task; existing rows can have NULL fingerprint. See ASSET_IDENTITY_MIGRATION.md.

2. **Backfill source_id from Collection.**  
   In an Alembic migration or a one-off data migration: `UPDATE assets SET source_id = (SELECT source_id FROM collections WHERE collections.uuid = assets.collection_uuid)`. Ensure every asset has a collection that exists and has source_id set. Run the migration; then alter source_id to NOT NULL. See ASSET_IDENTITY_MIGRATION.md.

3. **Verify no (source_id, container_id, locator) collisions.**  
   Before adding the unique constraint, run a query: duplicate (source_id, collection_uuid, uri) where is_deleted = false (or all rows, per contract). If any duplicates exist, resolve them (operator merge, deduplicate by canonical_key_hash, or document policy in ASSET_IDENTITY_MIGRATION.md). Do not add the unique constraint until there are no collisions.

4. **Add unique constraint on contract identity.**  
   Add a unique constraint on Asset: (source_id, collection_uuid, uri). Name it e.g. `uq_assets_source_container_locator`. This enforces the contract rule “(source_id, container_id, locator) MUST be unique.” If soft-delete allows the same locator to reappear after delete, document whether the constraint is partial (WHERE is_deleted = false) or total. See ASSET_IDENTITY_MIGRATION.md.

5. **Define reconciliation outcome type.**  
   In a module used by reconciliation (e.g. `pkg/core/src/retrovue/catalog/reconciliation.py` or next to the ingest service), define an enum or literal type `ReconciliationOutcome`: `create`, `update`, `no_action`, `mark_unavailable`. Optionally define a small dataclass per item: `(locator, outcome, existing_asset_or_none)`.

6. **Add processor capability registry (ProcessorCapabilityContract).**  
   Add a capability declaration layer so the job queue and runtime know which processors exist and what they produce. In code (e.g. `pkg/core/src/retrovue/catalog/processor_capability.py` or alongside `adapters/registry.py`), define a **processor capability registry** with per-processor entries: `processor_id` (str, same key as ENRICHERS, e.g. "ffprobe", "loudness"), `target_type` ("MEDIA" or "ASSET"), `execution_order` (int or comparable, for ascending run order; see ProcessorCapabilityContract), `produced_metadata` (list[str], e.g. ["duration_ms", "video_codec", "audio_codec"] for ffprobe), `required_metadata` (list[str], e.g. [] or ["path_uri"]). Populate from existing ENRICHERS: for each entry in ENRICHERS, add a capability record (e.g. ffprobe → MEDIA, produced: duration_ms, video_codec, audio_codec, etc.; loudness → MEDIA, produced: loudness_lufs; interstitial-type → MEDIA/ASSET as appropriate). Expose a function or registry lookup: `get_processors_for_target(target_type: str) -> list[str]` and `get_capability(processor_id: str) -> {target_type, execution_order, produced_metadata, required_metadata}`. Phase 3 enqueue will use this to resolve processor_ids (from collection config) and to set job target_type; Phase 4 validation will use produced_metadata. Do not change how enrichers are invoked yet; this is additive. See ProcessorCapabilityContract_v0.1.md.

7. **Create a function to load current catalog state for a collection.**  
   In the same reconciliation module (or in a repository), add a function `load_catalog_state_for_collection(db, collection_uuid) -> dict[str, Asset]` (or similar) that returns a mapping from canonical_key_hash (or locator, if stored) to the existing Asset row for that collection. Include only non-deleted assets (is_deleted=False). This is used in the “compare” step.

8. **Implement “determine outcome” logic (gated by ENABLE_FINGERPRINT_UPDATES).**  
   Add a function `determine_reconciliation_outcomes(discovered_locators: list[DiscoveredLocator], catalog_state: dict, *, collection, enable_fingerprint_updates: bool = False) -> list[tuple[DiscoveredLocator, ReconciliationOutcome, Asset | None]]`. For each discovered locator: compute canonical_key_hash from locator (or use locator as key if already stored). If not in catalog_state → outcome = create. If in catalog_state: **if `enable_fingerprint_updates` is false,** treat as no_action (do not compare fingerprint). **If true,** compare fingerprint (if present); if different or fingerprint missing on asset → update, else → no_action. Build a set of “seen” locators/hashes. After processing discovered list, for each asset in catalog_state not in seen, add an entry with outcome = mark_unavailable. Return the full list. Caller passes `settings.enable_fingerprint_updates` (or equivalent) so State 1 keeps current behavior (no fingerprint-based update).

9. **Implement stub enqueue API.**  
   Add a module or function e.g. `pkg/core/src/retrovue/catalog/processor_jobs.py` with `enqueue_processor_jobs(asset_ids: list[UUID], processor_ids: list[str], *, db=None) -> None`. Implementation: no-op (pass) or log “would enqueue N jobs for assets …”. This will be replaced in Phase 3.

10. **Refactor CollectionIngestService into six steps.**  
   In `collection_ingest_service.py`, refactor the body of `ingest_collection()` into:  
   (1) **Discover:** call `discover_locators(...)` and obtain raw items (locator + item) as in Phase 1.  
   (2) **Detect sidecars:** for each item, detect if sidecar metadata is present or changed (e.g. compare sidecar path or content hash if available); produce a list of “sidecar_changed” flags or leave for apply step.  
   (3) **Compare:** call `load_catalog_state_for_collection(db, collection.uuid)`.  
   (4) **Determine outcome:** call `determine_reconciliation_outcomes(discovered_locators, catalog_state, collection=collection)`.  
   (5) **Apply:** for each (locator, outcome, existing_asset): if create → run existing “create asset” path (path resolution, enricher pipeline, handle_ingest, persist); if update **and** `settings.enable_fingerprint_updates` → update existing_asset’s fingerprint and source-derived fields, then call `enqueue_processor_jobs([existing_asset.uuid], ...)`; if update and flag false, treat as no_action; if no_action → skip; if mark_unavailable → set asset.is_deleted=True, asset.deleted_at=now.  
   (6) **Enqueue:** for each create, after persisting the new asset, call `enqueue_processor_jobs([new_asset.uuid], ...)`.  
   Ensure the “create” path still runs the enricher pipeline and handle_ingest so that new assets are identical to pre–Phase 2 behavior. Preserve stats (assets_ingested, assets_updated, assets_removed, etc.) and reconciliation of missing items (mark_unavailable).

11. **Emit or log reconciliation events.**  
   After apply, log (structlog or similar) events: `asset_created`, `asset_updated`, `asset_marked_unavailable`, `jobs_enqueued` (count). Use consistent keys so they can be asserted in tests.

12. **Add reconciliation contract tests.**  
   In `pkg/core/tests/contracts/` add tests (e.g. `test_catalog_reconciliation_contract.py` or extend an existing file). Tests: (a) Run reconciliation twice with same source state (same discover output); assert second run does not create duplicate assets and does not change counts (idempotency). (b) For an asset that exists and has a different fingerprint in the next discovery run, assert outcome is update and asset’s fingerprint (and optionally source-derived fields) are updated and enqueue_processor_jobs was called. (c) When a previously seen locator is missing from discovery, assert outcome mark_unavailable and asset is_deleted=True (or unavailable).

13. **Run full ingest and asset invariant tests.**  
   Run `pytest pkg/core/tests/contracts/test_collection_ingest_*.py pkg/core/tests/contracts/test_source_ingest_*.py pkg/core/tests/contracts/test_asset_invariants.py`. Fix regressions until all pass.

14. **Wire scheduler daemon: container_refresh before horizon_expansion.**  
   In the scheduler daemon (e.g. `PlaylistBuilderDaemon` or the process that runs horizon extension), ensure each evaluation cycle runs **container_refresh** (discovery + reconciliation for configured collections/sources) **before** horizon expansion. Order: container_refresh → reconciliation → horizon_expansion. This satisfies ContainerDiscoveryContract and CatalogReconciliationContract (container refresh MUST run before playout horizon expansion). Call the discovery + reconciliation pipeline at the start of the daemon loop or before horizon extension; then run the existing Tier 2 / horizon expansion. CLI ingest remains a valid trigger. See PIPELINE_MIGRATION_ARCHITECTURE.md “Daemon integration.”

### Risk Mitigation

- Keep the “create” path for new assets identical to the current implementation (path resolution, enricher pipeline, handle_ingest, persist). Only the control flow (iteration over outcomes instead of raw items) changes; the code that creates one asset remains the same.
- For “update,” only update fingerprint and source-derived fields; do not run the full enricher pipeline inline in Phase 2 (enqueue stub is called so that Phase 3 can run processors via workers). If no fingerprint columns exist on Asset yet, outcome “update” can be implemented as “no_action” until Task 1 is done.
- Ensure reconciliation still runs only for full collection scope (no title/season/episode) when marking missing items as unavailable, and only when discovery returned at least one item, to avoid wiping assets on importer failure.
- Complete asset identity backfill (tasks 2–4) before relying on locator-based compare; otherwise Phase 2 stalls. Resolve any (source_id, collection_uuid, uri) collisions before adding the unique constraint.

### Validation

- **Asset identity migration:** Backfill completed (all assets have source_id); unique constraint (source_id, collection_uuid, uri) exists; no collisions. New assets set source_id from collection. See ASSET_IDENTITY_MIGRATION.md.
- **Processor capability registry:** Registry exists with processor_id, target_type, produced_metadata, required_metadata, execution_order for each processor (e.g. ffprobe, loudness, interstitial-type); get_capability(processor_id) and get_processors_for_target(target_type) available for Phase 3 enqueue and Phase 4 validation.
- **Contract harness:** All tests in `test_catalog_reconciliation_contract.py` and `test_asset_media_identity_contract.py` pass (skips removed; see CONTRACT_TEST_HARNESS.md).
- All existing `test_collection_ingest_*`, `test_source_ingest_*`, and `test_asset_invariants` tests pass.
- New reconciliation tests pass: idempotency, update when fingerprint differs, mark_unavailable when locator missing.
- Manual run: same collection ingested twice with no source change → second run creates 0, updates 0, removes 0 (idempotent). Change a file’s mtime/size and re-run discovery/reconciliation → one asset updated and enqueue stub called.

---

## Phase 3 — Processor Job Queue

### Goals

- Implement the processor job queue: **processor_jobs** table (queued or in-progress work only), enqueue API with deduplication, job lifecycle (pending/running/completed/failed), priority, workers that pull jobs and call a minimal processor runtime. Execution history (**processor_runs**) is a separate table added in Phase 4; do not store run history in processor_jobs.
- Replace the stub `enqueue_processor_jobs` with real enqueue. Reconciliation “apply” and “enqueue” steps call the real API.
- Optionally keep an inline enrichment fallback (feature flag or config) until workers are stable.

### Tasks

1. **Create processor_jobs schema.**  
   Add an Alembic migration that creates table `processor_jobs` with columns: `id` (UUID PK), `target_type` (str, e.g. 'MEDIA' or 'ASSET'), `target_id` (UUID), `status` (str: pending, running, completed, failed), `priority` (int or str; e.g. 0=LOW, 1=NORMAL, 2=HIGH, 3=CRITICAL), `created_at`, `started_at`, `completed_at`, `error_message` (text, nullable). Job identity is (target_type, target_id). Add a unique partial index or constraint so that (target_type, target_id) has at most one row with status in (pending, running). Add index on (status, priority) for worker dequeue. No processor_id column—the runtime selects which processors run for the target when the job is executed.

2. **Add ProcessorJob entity.**  
   In `pkg/core/src/retrovue/domain/entities.py`, add a SQLAlchemy model `ProcessorJob` mapping to `processor_jobs` with the above columns and any relationships (e.g. to Asset by target_id if target_type is ASSET).

3. **Implement job repository or service.**  
   In `pkg/core/src/retrovue/catalog/processor_jobs.py` (or a dedicated `processor_queue.py`), implement:  
   - `enqueue(db, target_type, target_id, priority=...) -> ProcessorJob | None`: insert a new job only if no row exists with (target_type, target_id) and status in (pending, running). If such a row exists, optionally update its priority (escalate) and return that row; do not create a duplicate. One job per target.  
   - `claim_next_job(db) -> ProcessorJob | None`: select one row with status=pending ordered by priority DESC (or by priority level), then by created_at; update its status to running and set started_at; return it. Use `SELECT ... FOR UPDATE SKIP LOCKED` (or equivalent) to enforce one worker per job.  
   - `complete_job(db, job_id, success: bool, error_message=None)`: set status to completed or failed, set completed_at, and optionally error_message.  
   - `retry_job(db, job_id)`: set status back to pending, clear started_at and error_message.

4. **Gate enqueue on ENABLE_PROCESSOR_QUEUE; replace stub when flag is true.**  
   In the reconciliation apply and enqueue steps, read `settings.enable_processor_queue`. **If false:** keep calling the stub (no-op or log only) — State 1/2. **If true:** replace the stub `enqueue_processor_jobs(asset_ids, processor_ids)` with calls to the real `enqueue(db, processor_id, target_type, target_id, priority)` for each (asset_id, processor_id). Determine processor_ids from the collection’s configured enrichers (same list as today’s pipeline). Resolve target_type from the processor capability registry (Phase 2 task 6): get_capability(processor_id).target_type. Use target_id=asset.uuid, default priority NORMAL. Ensure the same transaction or a following one commits the jobs so workers can see them.

5. **Implement minimal processor runtime (placeholder for Phase 4).**  
   In `pkg/core/src/retrovue/catalog/` or `runtime/`, add a minimal module e.g. `processor_runtime.py` with `execute_job(db, job: ProcessorJob) -> None`. Implementation: load Asset by job.target_id; build a minimal “item” (path_uri from asset.uri/canonical_uri, etc.); get list of processor_ids for this target from the capability registry; run each in ascending order of execution_order (ProcessorCapabilityContract): get enricher from registry by processor_id; call enricher.enrich(item); map result back to asset (duration_ms, video_codec, etc.) and call persist_asset_metadata. On exception, do not persist; re-raise so the worker can mark the job failed. Phase 4 will add context, structured result, and validation.

6. **Implement worker loop.**  
   Add a worker (e.g. `pkg/core/src/retrovue/runtime/processor_worker.py` or CLI command `retrovue worker run --once`): in a loop, call `claim_next_job(db)`; if a job is returned, call `execute_job(db, job)`; on success call `complete_job(db, job.id, True)`; on exception call `complete_job(db, job.id, False, str(e))`; commit. Optionally run N iterations or run until queue empty. Add a way to run the worker (CLI subcommand or script) so tests and manual runs can drain the queue.

7. **Add job queue contract tests.**  
   In `pkg/core/tests/contracts/` add `test_processor_job_queue_contract.py`. Tests: (a) Enqueue two jobs for the same (target_type, target_id) → only one row exists (deduplication). (b) Enqueue then claim → status is running; complete_job → status is completed. (c) Claim with two workers → each claim returns a different job (or second returns None if only one job). (d) Priority: enqueue LOW and HIGH; claim_next returns HIGH first. (e) Retry: failed job, retry_job, then claim → job can be claimed again. Job identity is (target_type, target_id).

8. **Add integration test: reconciliation → enqueue → worker.**  
   Test: run reconciliation for a collection that would create one new asset (or use a fixture with one new asset); assert at least one row in processor_jobs with status pending. Run the worker once or until queue empty; assert job status completed and asset has duration_ms (or other enricher-produced field) set. Optionally compare with “inline” run to ensure same final asset state.

9. **Enforce single enrichment path (no double processing).**  
   When `settings.enable_processor_queue` is true and `settings.enable_runtime_execution` is true, the ingest “create” path MUST NOT run the inline enricher pipeline for new assets; only enqueue jobs. Workers are the sole enrichment path (State 3). When either flag is false, the create path MAY run inline enrichment (State 1 or 2). Add a branch in the apply step: if both flags true, skip the enricher pipeline for new assets and only enqueue; otherwise run inline as today. Tests that validate “enqueue + worker” must set both flags true and assert no inline enrichment for new assets. See PIPELINE_MIGRATION_FEATURE_FLAGS.md.

10. **Run full contract and ingest tests.**  
    Run all ingest, reconciliation, and asset invariant tests; run new job queue tests. Fix any regressions.

### Risk Mitigation

- Do not remove the inline enricher path from the “create” flow until the worker and minimal runtime are tested. Either keep both paths (create still runs pipeline inline and also enqueues) or use a feature flag to switch to “enqueue only” after validation.
- Use a single transaction or short transactions for claim so that “only one worker per job” is guaranteed. Avoid long-running transactions that hold the job row locked while running the processor.
- Ensure worker and reconciliation use the same DB session factory and that jobs are committed so the worker sees them (same DB).

### Validation

- ProcessorJobQueueContract tests pass (identity, deduplication, lifecycle, priority, retry).
- Integration test: reconciliation creates assets and enqueues jobs; worker processes jobs and updates catalog; final asset state matches expectation (e.g. duration_ms set by ffprobe).
- Existing ingest contract tests still pass (with inline path if kept). If cut over to enqueue-only, run ingest tests with “run worker after ingest” and assert same effective catalog state.

---

## Phase 4 — Processor Execution Isolation

### Goals

- Introduce a formal **processor runtime** that uses a **shared ProcessingContext per target**: load the target entity and related metadata **once**; build a ProcessingContext (target entity, existing metadata, processor outputs, mutable changes); run processors **sequentially** with read-only access to the context; **collect** all results in the context (no database reads or writes per processor); **validate** metadata ownership rules; **persist all changes in a single database transaction** after execution completes (including **processor_runs** rows for execution history). Processors MUST read from the context and return structured metadata updates only; they MUST NOT perform direct database reads or writes.
- **processor_runs** table is distinct from **processor_jobs** (queue) and **processor_outputs** (metadata): jobs = queued/in-progress work; runs = immutable execution history; outputs = metadata produced. Runs support staleness detection, reruns on processor version change, retry history, auditability, and future licensing/reporting.
- Enrichers continue to accept “item” and return “item”; runtime adapts to a structured result and merges into the context. Observability: processor_started, processor_completed, processor_failed, duration.

### Tasks

1. **Define ProcessingContext (shared) and execution context (per-invocation).**  
   In `pkg/core/src/retrovue/catalog/processor_runtime.py`, define: (a) **ProcessingContext**: holds target entity (Asset or Media), existing metadata (from one load), processor outputs (accumulated), and mutable changes (updates to persist). Built once per job; processors receive a read-only view. (b) **ExecutionContext** (or equivalent): per-processor-invocation read-only fields `processor_id`, `target_type`, `target_id`, `job_id`, `execution_timestamp`. Document that processors MUST NOT perform direct DB reads/writes; they read from the context and return structured updates.

2. **Define structured result type.**  
   Define a type (e.g. dict or dataclass) `ProcessorResult` with at least `metadata: dict` (e.g. duration_ms, video_codec, audio_codec). Optionally `flexible: dict` for Phase 5. Document that this must conform to ProcessorMetadataContract (produced fields allowed for the processor).

3. **Implement adapter: item → ProcessorResult.**  
   In the processor runtime module, add `item_to_processor_result(item, processor_id: str) -> ProcessorResult`. Extract from the item the fields that the processor produces. This allows existing enrichers to remain “item in, item out” while the runtime gets a structured result to merge into the ProcessingContext.

4. **Implement result validation.**  
   Add `validate_processor_result(result: ProcessorResult, processor_id: str) -> None`. Use the processor capability (Phase 2) to get allowed produced_metadata. Assert result.metadata only contains keys in that set. Raise ValueError if invalid. Validation runs before merging into the context; no DB write.

5. **Create processor_runs schema and ProcessorRun entity.**  
   Add an Alembic migration: table `processor_runs` with columns `run_id` (UUID PK), `job_id` (UUID, FK to processor_jobs), `processor_id` (str), `target_type` (str), `target_id` (UUID), `processor_version` (str, e.g. semver or build id), `input_fingerprint` (str or text, fingerprint of target/input at run start), `status` (str: completed, failed), `started_at` (timestamp), `completed_at` (timestamp, nullable), `error_message` (text, nullable). Index on (job_id), (processor_id, target_type, target_id) for staleness and reporting. In `domain/entities.py`, add model `ProcessorRun`. This table is **execution history** (immutable); distinct from processor_jobs (queue) and processor_outputs (metadata). See ProcessorExecutionContract and PIPELINE_MIGRATION_ARCHITECTURE (Processor data model: jobs, runs, outputs).

6. **Implement execute_job with shared context, run recording, and single-transaction persist.**  
   Refactor `execute_job(db, job)` to: (a) **Load once:** load target entity (Asset or Media by job.target_id) and related metadata (e.g. AssetProbed, processor_outputs for that target). Compute **input_fingerprint** for the target (e.g. media file hash/size/mtime or composite) once for use in run records. No further DB reads for this target during the job. (b) **Build ProcessingContext:** target entity, existing metadata, processor outputs (from load or empty), mutable changes (empty). (c) **Get processor list** from capability registry for job.target_type; run in **ascending order of execution_order** (ProcessorCapabilityContract). (d) **For each processor:** record **started_at** (in memory); build ExecutionContext (processor_id, target_type, target_id, job_id, timestamp); obtain **processor_version** (from capability registry or processor implementation); build "item" from current context; call enricher.enrich(item) [or pass read-only context if enricher accepts it]; adapt to ProcessorResult; validate; **merge result into ProcessingContext** (mutable changes); record **completed_at** (in memory). Do **not** write to the database yet. On exception: record completed_at and error_message for that run in memory; do not merge; do not persist; re-raise so worker marks job failed. (e) **After all processors succeed (or on failure):** validate metadata ownership rules if job succeeded; **persist all changes in a single database transaction**: structured metadata to Asset/child tables (if job succeeded); Phase 5 adds processor_outputs; **insert processor_runs rows** (one per processor that was invoked, with run_id, job_id, processor_id, target_type, target_id, processor_version, input_fingerprint, status, started_at, completed_at, error_message). For a failed job, still insert run rows for every processor that ran (completed or failed). Commit; then mark job completed or failed. Log processor_started, processor_completed/processor_failed, duration.

7. **Update enrichers to accept context (optional).**  
   Extend the enricher protocol to accept an optional second argument: a read-only view of ProcessingContext (and/or ExecutionContext). Enrichers read from it instead of the database; they return structured updates. Existing enrichers that do not accept it continue to work; the runtime builds an "item" from the context so they still receive necessary data without DB access.

8. **Add processor runtime contract tests.**  
   In `pkg/core/tests/contracts/` add `test_processor_execution_contract.py`. Tests: (a) execute_job with a job that points to a valid asset and processor → job completes, asset updated. (b) When the processor raises an exception, execute_job re-raises; worker (or test) marks job failed; asset is unchanged (re-fetch and assert). (c) When validate_processor_result fails (e.g. result contains a disallowed field or invalid value), execute_job raises; job marked failed; asset unchanged. (d) Assert logs or events: processor_started, processor_completed or processor_failed, and duration present. (e) After a successful job, assert processor_runs has one row per processor that ran (job_id, processor_id, target_type, target_id, status, started_at, completed_at); after a failed job, assert run rows exist for each processor that was invoked before the failure.

9. **Optional: execution time limit.**  
   In execute_job, optionally run the enricher in a thread or subprocess with a timeout; on timeout, raise and let the worker mark the job failed. Document in ProcessorExecutionContract.

10. **Gate formal runtime on ENABLE_RUNTIME_EXECUTION.** Worker must read `settings.enable_runtime_execution`. When true: use only the formal processor runtime (execute_job with context, validate, apply). When false: worker may use the Phase 3 minimal runtime. Ensures State 2 vs State 3; when true, ingest create path must not run inline (Phase 3 task 9).
11. **Ensure workers use only the runtime when flag is true.**  
   Audit the worker code: it must call only `execute_job(db, job)` (or the single entry point). No direct calls to enricher.enrich() from the worker. Remove or refactor the “minimal runtime” from Phase 3 so that the formal runtime is the only path.

12. **Run all relevant tests.**  
    Run processor job queue tests, new processor execution tests, ingest/reconciliation tests, and asset invariants. Fix regressions.

### Risk Mitigation

- Do not change enricher implementations beyond adding an optional context parameter. The runtime adapts their output to ProcessorResult and merges into the shared ProcessingContext; no per-processor DB writes.
- If validation is strict (only allowlist), ensure the allowlist includes all fields that current enrichers produce (duration_ms, video_codec, etc.) so that existing jobs still pass validation.
- On failure, always re-raise so the worker can mark the job failed and record error_message; never merge into context and never persist (single-transaction persist only after all processors succeed).

### Validation

- **Contract harness:** All tests in `test_processor_execution_contract.py` pass (skips removed; see CONTRACT_TEST_HARNESS.md).
- Processor execution contract tests pass (success path, failure path, validation failure path, observability).
- Workers use only the runtime; no direct enricher calls from worker code.
- Existing re-enrich (reprobe, apply enrichers) still works: either it remains inline and preserves INV-ASSET-APPROVAL-OPERATOR-ONLY-001 and related invariants, or it is refactored to enqueue + worker and the same invariants are verified by tests.

---

## Phase 5 — Metadata Ownership Enforcement

### Goals

- Add `processor_outputs` table and write flexible/processor-specific payloads there from the runtime.
- Define ownership (Source / Processor / Operator) for core fields and enforce “processors MUST NOT overwrite operator-owned fields” in the runtime apply step.
- Contract tests: processor does not overwrite approved_for_broadcast; processor_outputs row created when processor returns flexible payload.

### Tasks

1. **Create processor_outputs schema.**  
   Add an Alembic migration: table `processor_outputs` with columns `id` (UUID PK), `processor_id` (str), `target_type` (str), `target_id` (UUID), `payload_json` (JSONB), `created_at` (timestamp). Index on (processor_id, target_type, target_id) for upsert or lookup. Add unique constraint on (processor_id, target_type, target_id) if one row per processor per target is desired, or allow multiple rows with created_at for history.

2. **Add ProcessorOutput entity.**  
   In `domain/entities.py`, add model `ProcessorOutput` for table `processor_outputs` with the above columns.

3. **Define ownership mapping.**  
   In a config module or the processor runtime module, define a mapping (e.g. dict or module-level constant) `FIELD_OWNERSHIP`: field name → 'source' | 'processor' | 'operator'. Include at least: `approved_for_broadcast` → operator, `operator_verified` → operator; `duration_ms`, `video_codec`, `audio_codec`, `container` → processor (or source for importer-set). Document in a short comment or doc that this implements ProcessorMetadataContract ownership.

4. **Enforce ownership in runtime apply.**  
   In the processor runtime’s apply step (where result.metadata is written to the asset), before applying: load current asset (or use in-memory state); for each key in result.metadata, if FIELD_OWNERSHIP.get(key) == 'operator', skip that key (do not overwrite). Apply all other keys. When writing to AssetEditorial, AssetProbed, etc., apply the same rule if those tables have operator-owned fields.

5. **Write flexible payload to processor_outputs.**  
   In the runtime, after applying structured metadata, if the processor result has a `flexible` dict (or if the adapter extracts “extra” payload from the enricher output), upsert a row in processor_outputs: processor_id, target_type, target_id, payload_json = flexible, created_at = now. Use merge or insert-or-update so one row per (processor_id, target_type, target_id) if that is the contract.

6. **Add ownership contract test.**  
   In `pkg/core/tests/contracts/test_processor_metadata_contract.py` (or add to processor execution tests): (a) Set asset.approved_for_broadcast = True and persist. Run a processor job for that asset via the runtime (or full worker path). Assert asset.approved_for_broadcast is still True after job completes. (b) Optionally: set an operator-owned editorial field; run processor; assert that field unchanged.

7. **Add processor_outputs contract test.**  
   In the same or a separate test file: (a) Use an enricher that returns (or is adapted to return) a flexible payload (e.g. a small dict). Run execute_job for that processor and asset. Assert a row exists in processor_outputs with the same processor_id, target_id, and payload_json content. (b) Assert created_at is set.

8. **Document ProcessorMetadataContract compliance.**  
   In `docs/contracts/core/ProcessorMetadataContract_v0.1.md` or in `PIPELINE_MIGRATION_ARCHITECTURE.md` / this task plan, add a short “Implementation notes” or “Compliance” subsection: structured metadata in Asset/child tables; flexible output in processor_outputs; ownership enforced in runtime apply; processors do not overwrite operator-owned fields.

9. **Run full test suite.**  
   Run all contract tests (ingest, reconciliation, job queue, processor execution, metadata ownership and processor_outputs). Run asset invariants and any integration tests. Fix regressions.

### Risk Mitigation

- When enforcing ownership, only skip keys that are explicitly operator-owned. Do not skip processor-owned fields; otherwise re-enrich would never update duration/codecs after a file change.
- If an enricher does not yet return a “flexible” payload, the runtime can still write an empty dict or skip the processor_outputs write for that processor until enrichers are extended. Ensure the table and write path exist and are tested with at least one processor that does write flexible payload.

### Validation

- **Contract harness:** All tests in `test_processor_metadata_contract.py` pass (skips removed; see CONTRACT_TEST_HARNESS.md).
- Contract test: operator-owned field (e.g. approved_for_broadcast) is not overwritten by processor.
- Contract test: processor_outputs row created with correct processor_id, target_id, payload_json when processor returns flexible payload.
- All prior phase tests (Phase 1–4) still pass. No regression in ingest, reconciliation, job queue, or processor execution tests.

---

## Phase 6 — Legacy Pipeline Removal

**Task list only — do not implement until after Phase 5.** The contract-driven architecture must be fully implemented and operational (discover → reconcile → enqueue → worker runtime) before executing Phase 6. Then remove all legacy inline enrichment as follows.

### Goals

- Remove all inline processor execution from ingest and reconciliation.
- Remove migration feature flags; the system always operates in worker-runtime mode.
- Ensure ingest and reconciliation perform only: discover → compare → apply → enqueue job.
- Processors are referenced only by the processor runtime and the processor capability registry.
- Documentation reflects only the final architecture; temporary migration documents are removed.

### Tasks

1. **Remove all inline processor execution paths from ingest and reconciliation.**

2. **Delete legacy helper functions** including:
   - run_enricher_pipeline
   - apply_enrichers
   - inline_enrich_asset
   - reprobe_inline

3. **Remove fallback behavior** that executes processors when the job queue is disabled.

4. **Remove migration feature flags:**
   - ENABLE_FINGERPRINT_UPDATES
   - ENABLE_PROCESSOR_QUEUE
   - ENABLE_RUNTIME_EXECUTION

5. **Ensure ingest and reconciliation perform only:**  
   discover → compare → apply → enqueue job.

6. **Verify that processors are only referenced by:**
   - processor runtime
   - processor capability registry

7. **Update tests** to reflect the final architecture.

8. **Update documentation:**
   - remove references to inline enrichment
   - remove migration flags
   - remove migration planning documents
   - update architecture documentation to reflect the final pipeline

9. **Delete temporary migration documents** including:
   - PIPELINE_MIGRATION_TASK_PLAN.md
   - PIPELINE_MIGRATION_GAPS.md
   - PIPELINE_CONTRACT_ALIGNMENT.md


### Risk Mitigation

- Execute Phase 6 only when Phases 1–5 are complete and workers are running the full processor runtime in production or staging.
- Run the full contract test suite and integration tests before and after Phase 6. All contract tests must pass.

### Acceptance criteria (Phase 6 complete when)

- No inline enrichment code remains.
- Processor execution occurs only via workers.
- Feature flags are removed.
- Documentation reflects only the final architecture.
- All contract tests pass.

---

## Task Execution Order (Summary)

Execute in this order within each phase; phases in sequence 1 → 2 → 3 → 4 → 5 → **6**.

| Phase | Task order |
|-------|------------|
| 1 | 1 → 2 → 3 → 4 → 5 |
| 2 | 1 → 2 → 3 → 4 → 5 → 6 (capability registry) → 7 … → 14 (daemon: container_refresh before horizon_expansion) |
| 3 | 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → (9 optional) → 10 |
| 4 | 1 → 2 → 3 → 4 → 5 (processor_runs schema) → 6 → 7 → 8 → (9 optional) → 10 → 11 → 12 |
| 5 | 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 |
| **6** | **1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9** (legacy removal; execute only after 1–5 complete) |

After each phase, run the validation steps before starting the next phase.
