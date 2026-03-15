# Pipeline Architecture

This document describes the contract-driven ingestion and metadata pipeline. The system operates in a single mode: discover → reconcile → apply → enqueue jobs; processor execution is performed only by workers via the processor runtime. See `docs/contracts/core/` and `catalog_processing_architecture.md`.

---

## Architecture Overview

The system conforms to the following contract-driven flow.

### Pipeline Shape

```
External Source
     │
     ▼
Container Discovery (discover locators; optional sidecar detection)
     │
     ▼
Catalog Reconciliation (compare → determine outcome → apply mutations → enqueue jobs)
     │
     ▼
Asset/Media Identity (locator + fingerprint; create/update/unavailable)
     │
     ▼
Processor Capability (select processors by target type and metadata)
     │
     ▼
Processor Job Queue (enqueue jobs; workers drain queue by priority)
     │
     ▼
Processor Execution (runtime: invoke → validate result → apply; isolate from scheduler/reconciliation)
     │
     ▼
Metadata Storage (structured tables + processor_outputs; ownership enforced)
```

### Component Responsibilities

| Layer | Responsibility | Contract |
|-------|----------------|----------|
| **Discovery** | Enumerate locators per container; output locator-like records (source_id, container_id, locator, optional fingerprint). No catalog writes. | ContainerDiscoveryContract |
| **Reconciliation** | Compare discovered locators with catalog; determine create/update/no_action/mark_unavailable; apply mutations; enqueue processor jobs. Idempotent; observable. | CatalogReconciliationContract |
| **Identity** | (source_id, container_id, locator) unique; fingerprint for “update if differs.” Asset = schedulable unit; Media = playable file (or Asset as proxy until Media table exists). | AssetMediaIdentityContract |
| **Processor capability** | Declare target type (MEDIA/ASSET), required/produced metadata. Used to select which processors run and to validate results. | ProcessorCapabilityContract |
| **Job queue** | Jobs (target_type, target_id)—one job per target; lifecycle; priority; deduplication; workers; retry; observability. Prevents job explosion, dependency ordering issues, and metadata write conflicts. | ProcessorJobQueueContract |
| **Processor execution** | Workers hand job to processor runtime. Runtime loads target and related metadata **once**, builds a **shared ProcessingContext** (target entity, existing metadata, processor outputs, mutable changes); runs processors sequentially; processors read from context and return structured updates; runtime **merges** results into context (no DB write per processor); **single database transaction** at job completion; validate ownership before persist; do not overwrite operator-owned; failure and time limits. | ProcessorExecutionContract |
| **Metadata storage** | Structured fields in Asset/child tables; flexible output in processor_outputs; ownership (Source/Processor/Operator) enforced on apply. | ProcessorMetadataContract |

### Invariants Preserved

- **INV-ASSET-MEDIA-IDENTITY:** Scheduler schedules Assets; playout resolves to a playable file (Asset or Media). Media selection occurs after scheduling and before playout execution.
- **Approval and state:** New assets created with state=new, approved_for_broadcast=false; only operator can approve. Re-enrich resets approval where specified by contract.
- **No scheduler execution of processors:** Scheduler and horizon expansion do not run processor workloads; only workers do.

### Job queue design: per-target jobs

The job queue uses **per-target job identity** (target_type, target_id), not per-processor-per-target. One job represents “process this target”; the processor runtime determines which processors run for that target and executes them **sequentially in a deterministic order**. This design:

- **Prevents job explosion:** Reconciliation enqueues one job per target that needs processing, not N jobs per target (one per processor). Queue size scales with the number of targets (M), not N×M.
- **Avoids processor dependency problems:** Processors that must run in order (e.g. ffprobe before loudness) are run in a fixed sequence within the same job. There are no separate jobs that could run in the wrong order or require dependency edges.
- **Prevents metadata race conditions:** Only one job owns a target at a time; all processors for that target run in one worker, sequentially. No concurrent writes to the same asset or media from different jobs.

See ProcessorJobQueueContract and ProcessorExecutionContract.

### Processor data model: jobs, runs, outputs

Three tables support the processor pipeline; each has a distinct role:

| Table | Role | Mutable? |
|-------|------|----------|
| **processor_jobs** | Queued or in-progress work. One row per target (target_type, target_id). Tracks state (pending, running, completed, failed), priority, timestamps. | Yes; state and timestamps change as work is claimed and completed. |
| **processor_runs** | Immutable execution history. One row per processor execution (per processor that ran within a job). Records run_id, job_id, processor_id, target_type, target_id, processor_version, input_fingerprint, status, started_at, completed_at, error_message. | Append-only (or status/timestamps updated on completion). |
| **processor_outputs** | Metadata produced by processors (flexible/processor-specific payloads). Keyed by processor_id, target_type, target_id. | Yes; overwritten or versioned per processor contract. |

This separation keeps the queue small (jobs), provides audit and staleness support (runs), and stores derived metadata (outputs). Runs enable: staleness detection (input_fingerprint vs current), reruns when processor_version changes, retry history, auditability, and future paid processor licensing or reporting. See ProcessorJobQueueContract (data model section) and ProcessorExecutionContract (Execution History).

### Daemon integration

The contracts require that **container refresh run before playout horizon expansion** (ContainerDiscoveryContract, CatalogReconciliationContract). Daemon integration intentionally minimal until discovery and reconciliation are in place; once they are, the **scheduler daemon** (e.g. `PlaylistBuilderDaemon` or the process that drives horizon extension) must run catalog refresh before expanding the horizon so that newly discovered media is available for scheduling.

**Target daemon flow:**

```
scheduler_daemon (each evaluation cycle)
       │
       ▼
  container_refresh   (discovery + reconciliation for configured collections)
       │
       ▼
  reconciliation      (compare → determine outcome → apply → enqueue jobs; may be same step as refresh)
       │
       ▼
  horizon_expansion   (extend Tier 2 / playout horizon using updated catalog)
```

Implementation must wire this order: **container_refresh → reconciliation → horizon_expansion**. CLI ingest (`source ingest`, `collection ingest`) remains a valid trigger; the daemon adds a second trigger so that refresh runs on a schedule or before each horizon extension. See architecture for the concrete “wire daemon” task.

---

## Migration Phases

Phases are ordered so that each builds on the previous without breaking the pipeline. Each phase section includes: objective, scope, deliverables, acceptance criteria / testability, and dependency notes.

---

### Phase 1 — Discovery Refactor

**Objective:** Separate “discover locators” from the rest of ingest so that discovery is a distinct, contract-aligned step. No change to observable ingest behavior.

**Scope**

- Add a **discovery service** (or function) that, for a given Collection (and optional scope: title/season/episode), calls the existing importer and returns a list of **discovered locator records**.
- A locator record is a value type (e.g. dataclass) with: `source_id`, `container_id` (collection uuid), `locator` (string: current canonical_key or a stable URI form), and optional `fingerprint` (e.g. size, mtime; hash optional). Map from existing importer output (path_uri, provider_key, etc.) to this shape.
- The existing `CollectionIngestService.ingest_collection()` continues to run; it **calls** the new discovery step first, then uses the returned list to drive the existing “create or skip” and reconciliation logic (still keyed by canonical_key_hash). Ingest now only enqueues; workers run processors.

**Deliverables**

- New module or package: e.g. `retrovue.usecases.container_discovery` or `retrovue.catalog.discovery` with a function `discover_locators(collection, importer, scope=...) -> list[DiscoveredLocator]`.
- `DiscoveredLocator` (or equivalent) type with source_id, container_id, locator, optional fingerprint.
- Integration: `CollectionIngestService` uses `discover_locators()` and maps results to the existing item list or canonical_key_hash set so that create/skip/reconcile behavior is unchanged.
- Unit tests for discovery in isolation (mock importer; assert shape and that locator is stable for same item).
- Contract test or existing ingest test: run `collection ingest` (or equivalent) and assert that created/skipped/reconciled counts and final catalog state match the pre–Phase 1 behavior.

**Acceptance Criteria / Testability**

- All existing ingest and source-ingest contract tests pass.
- New test: “discover_locators returns one record per importer item; locator is deterministic for same path/provider_key.”
- No new CLI surface required; no daemon changes.

**Dependencies**

- None. Phase 1 is the first step and does not depend on job queue or Media.

---

### Phase 2 — Reconciliation Layer

**Objective:** Refactor ingest into the contract’s reconciliation workflow (discover → detect sidecars → compare → determine outcome → apply → enqueue jobs). Add fingerprint and “update if differs” on the current Asset model. Enqueue step is a no-op or stub until Phase 3. Behavior remains backward-compatible.

**Asset identity migration (prerequisite).** Before reconciliation can compare by locator and enforce contract identity, existing assets must be migrated from current identity (collection_uuid, canonical_key_hash) to contract identity (source_id, container_id, locator). Mapping: locator = asset.uri, container_id = asset.collection_uuid, source_id = collection.source_id. Steps: add source_id to Asset, backfill from Collection, verify no (source_id, container_id, locator) collisions, add unique constraint. New assets must set source_id from collection when created. See **ASSET_IDENTITY_MIGRATION.md**.

**Scope**

- **Workflow split:** Refactor `CollectionIngestService.ingest_collection()` (or a dedicated reconciliation service) into explicit steps:
  1. Discover locators (Phase 1).
  2. Detect sidecar metadata additions or changes (explicit step: compare sidecar presence/contents per locator; output flags or deltas).
  3. Load current catalog state for the collection (e.g. assets by canonical_key_hash or by locator if stored).
  4. For each discovered locator, **determine outcome**: create | update | no_action | mark_unavailable (when locator missing from discovery).
  5. **Apply mutations:** create new Asset (and optional Media later), or update existing Asset (fingerprint + source-derived metadata), or mark unavailable (soft-delete or unavailable flag).
  6. **Enqueue processor jobs:** call a stub or no-op “job enqueue” API for each item that would have been enriched (create or update). No real queue yet.
- **Fingerprint:** Add optional fingerprint fields to Asset (e.g. `file_size`, `file_mtime`, or a composite `fingerprint_hash`). In “compare,” when a locator already exists, compare fingerprint; if different, outcome = update. In “apply” for update, refresh fingerprint and any source-derived fields; then call “enqueue jobs” for that asset.
- **Observability:** Emit or log reconciliation events: asset_created, asset_updated, asset_marked_unavailable, jobs_enqueued (count or stub).

**Deliverables**

- Reconciliation service or refactored ingest service implementing the six-step workflow.
- Fingerprint columns (or equivalent) on Asset; backfill optional for existing rows.
- Outcome type: create | update | no_action | mark_unavailable.
- Stub job-enqueue API (e.g. `enqueue_processor_jobs(asset_ids, processor_ids)` no-op or log-only).
- Contract tests: reconciliation idempotency (run twice, no source change → no catalog change); outcome “update” when fingerprint differs (test with two discovery runs, same locator, different fingerprint).
- All existing ingest and asset invariant tests still pass.

**Acceptance Criteria / Testability**

- Existing `test_collection_ingest_*` and `test_source_ingest_*` pass.
- New test: “reconciliation workflow produces correct outcomes (create/update/no_action/mark_unavailable) from discovered locators and current catalog.”
- New test: “re-run reconciliation with same source state → idempotent (no duplicate creates, no redundant updates).”
- New test: “when fingerprint changes for same locator, outcome is update and asset is updated (and stub enqueue called).”

**Dependencies**

- Phase 1 (discovery returns locator-like records). Phase 2 does not require Phase 3 (real queue).

---

### Phase 3 — Processor Job Queue

**Objective:** Implement the processor job queue: store, enqueue API, job identity and deduplication, lifecycle, priority, workers that drain the queue and call processors. Reconciliation switches to “enqueue only” for new/updated assets; optional fallback to inline execution during rollout.

**Scope**

- **Job store:** Table (or equivalent) `processor_jobs`: job_id, target_type (MEDIA/ASSET), target_id, status (pending | running | completed | failed), priority, created_at, started_at, completed_at, error_message, etc. Unique constraint or deduplication on (target_type, target_id) so at most one pending/running job per target. Job identity is per-target.
- **Enqueue API:** Reconciliation enqueues one job per target that needs processing. The processor runtime (Phase 4) uses the capability registry at execution time to select which processors run for that target; the queue does not store processor_id per job. Deduplication: if job for same identity exists and pending/running, do not insert; optionally escalate priority.
- **Workers:** One or more worker processes that: select next job by priority, claim it (status → running), hand the job to the **processor runtime**; the runtime selects processors for that target and runs them sequentially in ascending order of execution_order (ProcessorCapabilityContract); worker sets status completed/failed when the runtime returns. Enforce “only one worker per job” (e.g. row-level lock or conditional update).
- **Retry:** Operator or CLI can retry failed jobs (set status to pending, preserve identity).
- **Observability:** Log job lifecycle and processor execution events; optional timestamps and metrics (queued/running/completed/failed counts).

**Deliverables**

- Schema and repository (or service) for processor_jobs.
- Enqueue API used by reconciliation; stub from Phase 2 replaced by real enqueue.
- Worker implementation that pulls jobs and calls the **processor runtime** (Phase 4 provides the runtime; Phase 3 can call a minimal runtime that runs existing enrichers and applies to Asset).
- Contract tests: job identity and deduplication; lifecycle transitions; priority ordering; one worker per job.
- Integration test: run reconciliation → enqueue jobs → run worker → assert jobs completed and catalog updated. Optionally keep an “inline” path for comparison until Phase 4 is stable.

**Acceptance Criteria / Testability**

- Reconciliation can run with “enqueue only” (no inline enrichment); workers process jobs and update catalog.
- Contract tests for ProcessorJobQueueContract (identity, deduplication, lifecycle, priority, retry) pass.
- Existing ingest contract tests can be run in “enqueue + worker” mode and produce same effective catalog state as before (modulo timing).

**Dependencies**

- Phase 2 (reconciliation has enqueue step). Phase 3 depends on a minimal **processor runtime** that can run one enricher on one target and apply result; Phase 4 formalizes and hardens that runtime.

---

### Phase 4 — Processor Execution Isolation

**Objective:** Introduce a formal **processor runtime** that uses a **shared ProcessingContext per target**: load the target entity and related metadata **once**; build a ProcessingContext (target entity, existing metadata, processor outputs, mutable changes); run processors **sequentially** with read-only access to the context; **collect** all results in the context (no database reads or writes per processor); **validate** metadata ownership rules; **persist all changes in a single database transaction** after execution completes. Processors read from the context and return structured metadata updates only; they MUST NOT perform direct database reads or writes. Processors remain the same enrichers; runtime adapts their I/O and merges into the context. Failures and time limits are handled; observability is standardized.

**Scope**

- **Processor runtime module:** Single entry used by workers: `execute_job(job) -> result`. **Load once:** target entity and related metadata (e.g. AssetProbed, processor_outputs). **Build ProcessingContext:** target entity, existing metadata, processor outputs, mutable changes. **For each processor:** pass read-only view of ProcessingContext and ExecutionContext (processor_id, job_id, etc.); enricher returns structured result; runtime validates and **merges into context** (no DB write). **After all processors succeed:** validate ownership rules; **persist all changes in a single database transaction**. Enrichers may still accept “item” and return “item”; runtime adapts to a structured result and merges into the context. If any processor or validation fails, do not persist; worker marks job failed.
- **ProcessingContext and ExecutionContext:** Processors receive a read-only view of the shared ProcessingContext (target, existing metadata, accumulated results) and per-invocation ExecutionContext (processor_id, target_type, target_id, job_id, timestamp). Enrichers treat both as read-only; they never perform direct DB reads or writes.
- **Execution history (processor_runs):** Runtime records each processor execution in **processor_runs** (run_id, job_id, processor_id, target_type, target_id, processor_version, input_fingerprint, status, started_at, completed_at, error_message). Runs are immutable history; written in the same transaction as catalog updates at job completion. Supports staleness detection, reruns on processor version change, retry history, auditability, and future licensing/reporting.
- **Failure and limits:** On exception, runtime does not apply; worker sets job to failed and records error. Optional: global or per-job execution time limit; on timeout, terminate and mark failed.
- **Isolation:** Only workers call the runtime. Scheduler and reconciliation do not invoke processors directly; they only enqueue jobs. This preserves “processor execution isolated from scheduler and reconciliation.”
- **Observability:** Runtime (or worker) logs: processor_started, processor_completed, processor_failed; record duration.

**Deliverables**

- Processor runtime: `execute_job(job)` → **load once** target and related metadata; **build ProcessingContext**; select processors for target (from capability registry), run each in ascending execution_order: pass read-only context, call enricher, adapt result, validate, **merge into context** (no DB write); **after all succeed**, validate ownership and **persist in a single transaction** (catalog updates + **processor_runs** rows for each processor that ran). Ownership checks at persist (Phase 5); until then, apply all processor-produced fields that are not explicitly operator-owned.
- Adapter: existing enricher “item in, item out” mapped to structured result for validation/apply.
- **processor_runs table:** Schema per ProcessorExecutionContract (run_id, job_id, processor_id, target_type, target_id, processor_version, input_fingerprint, status, started_at, completed_at, error_message). Runtime writes one row per processor execution in the same transaction as job completion (or failure); capture started_at/completed_at in memory during execution.
- Contract tests: processor receives context; result is validated before apply; on failure no catalog update; job marked failed; run rows written for each processor execution.
- Optional: execution time limit and timeout handling.

**Acceptance Criteria / Testability**

- Workers use only the runtime to execute jobs; no direct enricher calls from workers.
- Test: “when processor raises, job is failed and asset is unchanged.”
- Test: “processor result that fails validation does not update catalog; job failed.”
- Existing re-enrich (reprobe, apply enrichers) can remain inline or be refactored to enqueue + worker; both paths must preserve invariants (e.g. INV-ASSET-APPROVAL-OPERATOR-ONLY-001, INV-ASSET-REPROBE-RESETS-APPROVAL-001).

**Dependencies**

- Phase 3 (workers and job queue). Phase 4 does not require Phase 5 (ownership enforcement), but Phase 5 will plug into the runtime’s apply step.

---

### Phase 5 — Metadata Ownership Enforcement

**Objective:** Enforce ProcessorMetadataContract: structured metadata in structured tables; flexible output in `processor_outputs`; ownership (Source / Processor / Operator) defined and enforced so that processors do not overwrite operator-owned fields.

**Scope**

- **processor_outputs table:** Schema (processor_id, target_type, target_id, payload_json, created_at). Runtime writes processor-specific or flexible output here instead of (or in addition to) overloading AssetProbed or similar. Existing enrichers can continue to write core fields to Asset/AssetProbed; extra output goes to processor_outputs.
- **Ownership model:** Define which fields are Operator-owned (e.g. approved_for_broadcast, operator_verified, certain editorial fields). Document or config: field → owner (Source | Processor | Operator). In the processor runtime’s apply step, **skip** any processor result key that is tagged Operator-owned (or merge only if not set by operator). Processors may update their own (Processor-owned) fields when media changes.
- **Tests:** Re-enrich must not overwrite operator-approved or operator-edited fields; contract test that sets operator field then runs processor and asserts field unchanged.

**Deliverables**

- `processor_outputs` table and write path from runtime for flexible payloads.
- Ownership mapping (code or config) and enforcement in runtime apply logic.
- Contract tests: “processor apply does not overwrite operator-owned field”; “processor_outputs row created for processor that returns flexible payload.”
- Documentation update: ProcessorMetadataContract compliance (structured + processor_outputs + ownership).

**Acceptance Criteria / Testability**

- Contract test: set approved_for_broadcast=true (operator); run processor; assert still true after job completes.
- Contract test: processor that returns extra payload → row in processor_outputs with correct processor_id, target_id, payload_json.
- All prior phase tests still pass.

**Dependencies**

- Phase 4 (runtime apply step). Phase 5 completes metadata storage and processor execution contract alignment.

---

## Current Operating Mode

The pipeline runs only in worker-runtime mode: ingest and re-enrich (reprobe, apply enrichers) perform discover → compare → apply → enqueue; processor execution is done solely by workers via the processor runtime. There is no inline enrichment path.

---

## Implementation notes (keep in mind)

The following are not blockers but should be kept in mind during discovery, reconciliation, and fingerprint design.

**Locator stability**  
Locator must be stable across rescans. Prefer stable, filesystem-style identifiers (e.g. `file:///media/movies/blade_runner.mkv`) over unstable ones (e.g. `plex://123`). If locator changes unnecessarily, reconciliation becomes chaotic.

**Fingerprint design**  
Start simple. Use **size** and **mtime** only. Do not hash file content yet — hashing large libraries will hurt performance. A **content_hash** (or equivalent) can be added later if needed.

**Media table timing**  
Media table creation is correctly postponed. Asset-as-media is sufficient for now; a separate Media table can be introduced later when the contract identity and reconciliation flow are stable.


