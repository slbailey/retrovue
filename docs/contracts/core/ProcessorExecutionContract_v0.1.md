# ProcessorExecutionContract v0.1

## Purpose

This contract governs the execution of metadata processors by workers. Jobs are **per-target** (one job per target_type, target_id); the processor runtime determines which processors must run for that target and executes them **sequentially in a deterministic order**. This contract defines the runtime interface between workers, processor implementations, and metadata storage.

---

## Definitions

**Processor**  
A metadata enrichment component defined by the ProcessorCapabilityContract. Processors analyze media or assets and produce derived metadata.

**Processor Job**  
A request to process a specific target. The job is identified by (target_type, target_id). Processor jobs are defined in the ProcessorJobQueueContract. The runtime runs one or more processors for that target within a single job.

**Worker**  
A runtime component responsible for retrieving jobs from the processor job queue and invoking the processor runtime. The worker does not choose which processors run; the runtime does.

**Processor Runtime**  
The component that, given a job (target_type, target_id), loads the target and related data once, builds a **shared ProcessingContext** for that target, runs processors sequentially using that context, collects all results in the context, validates ownership rules, and persists all changes in a **single database transaction** after execution completes. The worker calls the runtime once per job.

**ProcessingContext**  
A shared in-memory structure for the duration of one job, loaded once and cached for the life of the job. It contains explicitly: **target entity** (Asset or Media); **existing structured metadata** (from Asset/AssetProbed and related tables); **processor_outputs** (existing rows for this target, from the processor_outputs table); **sidecar metadata** (e.g. .nfo, companion files associated with the target); and **mutable_changes** (accumulated updates from processor results to be persisted). Processors read from the context and return structured metadata updates; the runtime merges updates into the context. No database reads or writes occur per processor—only one load at start and one persist at end.

**Processor Result**  
The output produced by a processor after execution. Results are structured metadata updates (and optionally flexible payload). Processors return results to the runtime; the runtime merges them into the ProcessingContext and does not write to the database until all processors have run.

---

## Job Execution Model

Given a job (target_type, target_id):

1. The processor runtime **loads the target entity and related metadata once** (e.g. Asset, AssetProbed, processor_outputs for that target). No further database reads for this target during the job.
2. The runtime **constructs a ProcessingContext** containing: target entity; existing structured metadata; processor_outputs (for this target); sidecar metadata; and mutable_changes (initially empty).
3. The runtime determines which processors must run for that target (from the ProcessorCapabilityContract) and runs them **sequentially in ascending order of execution_order** (see ProcessorCapabilityContract). Order is thus deterministic and stable.
4. **For each processor:** the runtime provides a read-only view of the ProcessingContext (and execution context: processor_id, target_type, target_id, job_id, timestamp). The processor **reads from the context** and **returns structured metadata updates**; the processor MUST NOT perform direct database writes. The runtime validates the result (e.g. against produced_metadata and ownership), then **merges the result into the ProcessingContext** (mutable changes). No database write yet.
5. If a processor fails, the runtime MUST mark the job failed, MUST NOT merge that result, and MUST NOT run subsequent processors. No persist; the job is failed.
6. **When all selected processors have run successfully,** the runtime **validates metadata ownership rules** (e.g. do not overwrite operator-owned fields), then **persists all changes in a single database transaction** (structured metadata to Asset/child tables, flexible payloads to processor_outputs). After the transaction commits, the job is completed.

This model ensures one job per target, one load and one persist per job, and a fixed order so that processor dependencies are satisfied. Processors share derived metadata through the context; later processors see earlier results in the same context without additional database reads.

---

## Shared Processing Context: Design Rationale

**Minimizes database load.** The target entity and related metadata are read once at job start. Processors do not trigger their own queries. All updates are written in a single transaction at the end. This reduces round-trips and lock hold time compared to reading and writing per processor.

**Allows processors to share derived metadata.** The ProcessingContext holds existing metadata and the accumulated results of processors that have already run. A processor (e.g. loudness) can read duration or codec produced by an earlier processor (e.g. ffprobe) from the context without a database read. The runtime merges each processor's result into the context so the next processor sees an up-to-date view.

**Prevents metadata race conditions.** Only one job owns a target at a time (ProcessorJobQueueContract). Within the job, only the runtime writes to the database, and only once at the end. There are no concurrent writes to the same target from multiple processors or multiple jobs. The single transaction makes the outcome atomic.

**Enforces metadata ownership rules.** Before persisting, the runtime validates that processor-produced updates do not overwrite operator-owned fields (ProcessorMetadataContract). Validation and application of ownership rules happen in one place at persist time, so ownership is enforced consistently regardless of how many processors ran.

---

## Processor Invocation

For each processor run within a job, the runtime provides:

- processor_id
- target_type
- target_id
- job_id (the job that owns this target)

Processors receive a read-only view of the ProcessingContext (which holds the target entity and metadata) and execution context (processor_id, job_id, etc.). They do not access the database; they read from the context and return structured updates. target_type is ASSET or MEDIA.

---

## Execution Context

Processors MAY receive execution context including:

- processor_id
- target_type
- target_id
- job_id
- execution timestamp

Processors MUST treat the execution context as read-only.

---

## Processor Inputs and Requirements

Processors **read from the ProcessingContext** (a read-only view provided by the runtime). The context exposes:

- target entity (Asset or Media)
- existing structured metadata (loaded once at job start)
- processor_outputs (for this target)
- sidecar metadata (e.g. .nfo, companion files)
- mutable_changes (accumulated so far in the job, so later processors see earlier results)

Processors MUST **return structured metadata updates** to the runtime. The runtime merges these into the context; processors do not write to the context or database themselves.

Processors MUST NOT perform **direct database reads or writes**. All input comes from the ProcessingContext; all output is returned to the runtime for validation and eventual persist in a single transaction. This keeps database load minimal and ensures ownership and ordering are enforced by the runtime.

---

## Processor Outputs

Processors MUST return structured metadata results. Example result structure:

```
{
  "metadata": {
    "duration_ms": 5423000,
    "video_codec": "h264",
    "audio_codec": "aac"
  }
}
```

Metadata fields produced by processors MUST conform to the ProcessorMetadataContract.

---

## Result Validation

Processor results MUST be validated against the ProcessorMetadataContract (and the processor’s declared produced_metadata in the ProcessorCapabilityContract) before being applied to the catalog. If validation fails:

- the processor job MUST be marked as failed
- no metadata changes MUST be applied for that processor
- no further processors for that job run

This prevents corrupt metadata from breaking the catalog.

---

## Metadata Application

During execution, the runtime **merges** each processor's result into the ProcessingContext (mutable changes); no database write occurs yet. After all processors have run successfully, the runtime **validates metadata ownership rules** (ProcessorMetadataContract) and **persists all changes in a single database transaction** to the catalog (Asset/child tables, processor_outputs). Processors MUST NOT overwrite operator-managed metadata; the runtime enforces this at validation and persist time.

---

## Metadata Write Semantics

Processor outputs MUST represent the complete set of metadata fields produced by the processor. The processor runtime merges results into the ProcessingContext during execution and updates only the metadata fields owned by each processor. **No database writes occur per processor**—all changes are persisted in a single transaction at job completion. Because only the runtime writes and only once per job, there is no concurrent write to the same target; ordering within the job is deterministic.

---

## Processor Idempotency

Processors SHOULD be idempotent. Running the same processor multiple times against the same target MUST produce consistent metadata results.

---

## Processor Failure

If a processor execution fails:

- the processor job MUST be marked as failed
- failure details SHOULD be recorded (e.g. processor_id, error message)
- the processor MUST NOT modify metadata
- the runtime MUST NOT run subsequent processors for that job

Workers MAY retry processor jobs according to queue policies. On retry, the same target is processed again and the same processor sequence runs.

---

## Execution Time Limits

Processor execution MAY be subject to runtime limits defined by the processor runtime. If execution exceeds the allowed runtime:

- the processor execution MUST be terminated
- the processor job MUST be marked as failed

This protects the worker pool from hanging processors.

---

## Execution Isolation

Processor execution MUST be isolated from the scheduler and catalog reconciliation systems. Processor failures MUST NOT interrupt scheduler operation. Only workers invoke the processor runtime.

---

## Observability

Processor execution MUST produce observable events including:

- job started (target_type, target_id)
- processor started (processor_id, target_type, target_id, job_id)
- processor completed
- processor failed
- job completed or job failed

Execution duration SHOULD be recorded (per processor and optionally per job).

---

## Execution History (processor_runs)

Execution history is stored in a **processor_runs** table, distinct from the job queue and from processor outputs. The runtime records one row per processor execution (each time a processor runs within a job). Runs are **immutable execution history**: they are written when execution completes (or fails) and are not updated for content; they support staleness detection, reruns, retry history, auditability, and future licensing or reporting.

**Separation of concerns**

- **processor_jobs** — Queued or in-progress work. Mutable; lifecycle (pending → running → completed/failed). See ProcessorJobQueueContract.
- **processor_runs** — Immutable execution history. One row per processor run; append-only (or status/timestamps updated only to reflect completion). This contract.
- **processor_outputs** — Metadata produced by processors (payloads). See ProcessorMetadataContract.

**processor_runs schema (minimum)**

Each row MUST include at least:

| Column | Description |
|--------|--------------|
| run_id | Unique identifier for this run (e.g. UUID). |
| job_id | The processor job that contained this execution. |
| processor_id | Which processor ran. |
| target_type | ASSET or MEDIA. |
| target_id | Identifier of the target entity. |
| processor_version | Version or revision of the processor at execution time (e.g. semver or build id). Enables "rerun when processor version changes." |
| input_fingerprint | Fingerprint of the target (or input state) at run start (e.g. media file hash, size, mtime, or composite). Used for staleness detection. |
| status | completed, failed, or equivalent. |
| started_at | When this processor execution started. |
| completed_at | When this processor execution completed or failed (nullable until complete). |
| error_message | If status is failed, the error message or summary (nullable). |

The runtime MUST create a run record for each processor execution. When the runtime uses a single transaction at job completion (see Metadata Application), it MUST persist run rows in that same transaction (one row per processor that was invoked, with started_at and completed_at captured in memory during execution). For a failed job, the runtime still writes run rows for every processor that ran before the failure, with appropriate status and error_message for the run that failed.

**How this supports**

- **Staleness detection when media fingerprints change:** Compare `input_fingerprint` on the latest run for (processor_id, target_type, target_id) to the current fingerprint of the target. If they differ (e.g. file was replaced or metadata changed), the system can enqueue a new job or mark that target as needing re-processing.
- **Reruns when processor versions change:** If a processor is updated, `processor_version` changes. The system can query runs where processor_version is older than the current version and re-enqueue jobs for those targets so they are re-processed with the new processor.
- **Retry history:** Each job attempt (or each processor run within a job) is a distinct run row. Operators and support can see how many times a processor ran for a target, when, and whether it succeeded or failed.
- **Auditability:** An immutable record of what ran, for which job, on which target, with which version and input fingerprint, and the outcome. Supports compliance and debugging.
- **Future paid processor licensing and reporting:** Run rows can be aggregated by processor_id, processor_version, time window, or target to support usage-based licensing, billing, or reporting (e.g. runs per processor per month).
