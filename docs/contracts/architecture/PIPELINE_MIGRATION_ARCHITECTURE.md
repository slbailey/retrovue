# Pipeline Architecture

This document describes the contract-driven ingestion and metadata pipeline. The system has a single flow: container discovery → catalog reconciliation → job queue → processor runtime → metadata persistence. See `docs/contracts/core/` and `catalog_processing_architecture.md`.

**Terminology:** The ingest/catalog entity is **Container** (Source → Container → Locator → Media/Asset). See [TERMINOLOGY_COLLECTION_TO_CONTAINER.md](TERMINOLOGY_COLLECTION_TO_CONTAINER.md). The only allowed remaining uses of "Collection" for this entity are historical migrations and temporary CLI/API compatibility; architecture docs use Container only.

---

## Architecture Overview

### Pipeline Flow

```
Container discovery
       ↓
Catalog reconciliation
       ↓
Job queue
       ↓
Processor runtime
       ↓
Metadata persistence
```

**In more detail:**

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
Processor Job Queue (one job per target; workers drain by priority)
     │
     ▼
Processor Runtime (load target once → run processors sequentially → validate → persist)
     │
     ▼
Metadata Persistence (structured tables + processor_outputs; ownership enforced)
```

### Component Responsibilities

| Layer | Responsibility | Contract |
|-------|----------------|----------|
| **Container discovery** | Enumerate locators per container; output locator-like records (source_id, container_id, locator, optional fingerprint). No catalog writes. | ContainerDiscoveryContract |
| **Catalog reconciliation** | Compare discovered locators with catalog; determine create/update/no_action/mark_unavailable; apply mutations; enqueue processor jobs. Idempotent; observable. | CatalogReconciliationContract |
| **Job queue** | Jobs (target_type, target_id)—one job per target; lifecycle (pending/running/completed/failed); priority; deduplication; workers claim and run jobs. | ProcessorJobQueueContract |
| **Processor runtime** | Workers hand job to runtime. Runtime loads target and related metadata **once**, builds **ProcessingContext**, runs processors **sequentially**, merges results into context (no DB write per processor), then **single transaction** at job completion; validates ownership; does not overwrite operator-owned fields. | ProcessorExecutionContract |
| **Metadata persistence** | Structured fields in Asset/child tables; flexible output in processor_outputs; ownership (Source/Processor/Operator) enforced on apply. | ProcessorMetadataContract |

### Invariants Preserved

- **INV-ASSET-MEDIA-IDENTITY:** Scheduler schedules Assets; playout resolves to a playable file (Asset or Media). Media selection occurs after scheduling and before playout execution.
- **Approval and state:** New assets created with state=new, approved_for_broadcast=false; only operator can approve. Re-enrich resets approval where specified by contract.
- **No scheduler execution of processors:** Scheduler and horizon expansion do not run processor workloads; only workers do.

### Job queue: per-target jobs

The job queue uses **per-target job identity** (target_type, target_id), not per-processor-per-target. One job represents “process this target”; the processor runtime determines which processors run for that target and executes them **sequentially in a deterministic order**. This design:

- **Prevents job explosion:** Reconciliation enqueues one job per target that needs processing, not N jobs per target. Queue size scales with the number of targets.
- **Avoids processor dependency problems:** Processors that must run in order (e.g. ffprobe before loudness) are run in a fixed sequence within the same job.
- **Prevents metadata race conditions:** Only one job owns a target at a time; all processors for that target run in one worker, sequentially.

See ProcessorJobQueueContract and ProcessorExecutionContract.

### Processor data model: jobs, runs, outputs

Three tables support the pipeline:

| Table | Role | Mutable? |
|-------|------|----------|
| **processor_jobs** | Queued or in-progress work. One row per target (target_type, target_id). States: pending, running, completed, failed. | Yes; state and timestamps change as work is claimed and completed. |
| **processor_runs** | Execution history. One row per processor execution within a job. Records run_id, job_id, processor_id, target, status, timestamps, error_message. | Append-only (or status/timestamps on completion). |
| **processor_outputs** | Flexible/processor-specific metadata. Keyed by processor_id, target_type, target_id. | Yes; overwritten or versioned per processor contract. |

Runs enable staleness detection, reruns when processor_version changes, retry history, and auditability.

### Daemon integration

The contracts require that **container refresh run before playout horizon expansion**. The scheduler daemon (e.g. PlaylistBuilderDaemon) must run catalog refresh before expanding the horizon so that newly discovered media is available for scheduling.

**Target daemon flow:**

```
scheduler_daemon (each evaluation cycle)
       │
       ▼
  container_refresh   (discovery + reconciliation for configured containers)
       │
       ▼
  horizon_expansion   (extend Tier 2 / playout horizon using updated catalog)
```

CLI ingest (`source ingest`, `container ingest`) remains a valid trigger; the daemon adds a second trigger so that refresh runs on a schedule or before each horizon extension. (During compatibility rollout, `collection ingest` may still be accepted as a deprecated alias.)

---

## Implementation notes

**Locator stability**  
Locator must be stable across rescans. Prefer stable, filesystem-style identifiers (e.g. `file:///media/movies/blade_runner.mkv`) over unstable ones.

**Fingerprint design**  
Use **size** and **mtime** only. A content_hash can be added later if needed.

**Media table timing**  
Asset-as-media is sufficient for now; a separate Media table can be introduced later when needed.
