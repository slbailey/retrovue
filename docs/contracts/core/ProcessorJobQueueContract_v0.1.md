# ProcessorJobQueueContract v0.1

## Purpose

This contract governs the lifecycle and execution behavior of processor jobs. The processor job queue enables asynchronous metadata enrichment and isolates processor workloads from the scheduler and catalog reconciliation. A **job represents processing work for a target**, not a single processor execution: workers retrieve one job per target, and the processor runtime runs all applicable processors for that target in a deterministic order.

---

## Definitions

**Processor**  
A metadata enrichment component defined by the ProcessorCapabilityContract.

**Processor Job**  
A request to process a target entity. One job corresponds to one (target_type, target_id). The worker claims the job; the processor runtime determines which processors must run for that target (from the ProcessorCapabilityContract) and executes them sequentially in a deterministic order.

**Target**  
The entity to be processed. Possible targets: MEDIA, ASSET.

**Worker**  
A runtime component responsible for retrieving processor jobs from the queue and executing them. The worker hands the job to the processor runtime, which runs the applicable processors for the job’s target.

---

## Job Identity

A processor job MUST be uniquely identified by:

```
(target_type, target_id)
```

Where target_type is either ASSET or MEDIA and target_id is the identifier of the target entity. There is at most one pending or running job per target. This **per-target** identity (rather than per-processor-per-target) is the basis for the design below.

---

## Design Rationale: Per-Target Jobs

**Prevents job explosion.** If each job were (processor_id, target_type, target_id), then N processors × M targets would create N×M jobs. Reconciliation would enqueue N jobs per new asset. With per-target identity, reconciliation enqueues **one job per target** that needs processing; the runtime runs all applicable processors for that target within a single job. Queue size scales with targets (M), not with processors × targets (N×M).

**Avoids processor dependency problems.** When multiple processors must run on the same target (e.g. ffprobe before loudness), ordering is enforced by the processor runtime **within one job**: processors run in a fixed, deterministic sequence. There are no separate jobs that could run in the wrong order or require explicit dependency edges between jobs.

**Prevents metadata race conditions.** Only one job owns a target at a time. All processors for that target run sequentially in the same worker; no concurrent writes to the same asset or media from different jobs. Metadata updates are serialized per target.

---

## Job Deduplication

If a processor job is requested for a target (target_type, target_id) that already has a job in the queue (pending or running):

- the system MUST NOT create a duplicate job
- the existing job MAY have its priority escalated
- the existing job state MUST NOT be reset

This guarantees deterministic queue behavior and one job per target.

---

## Job Lifecycle

Processor jobs MUST move through the following states:

- pending
- running
- completed
- failed

State transitions:

- pending → running → completed
- pending → running → failed

Running means a worker has claimed the job and the processor runtime is executing (one or more) processors for the target. Completed means all selected processors for that target ran successfully. Failed means at least one processor failed or the runtime failed; the job is marked failed and no further processors for that job run.

Failed jobs MAY be retried.

---

## Job Retry

Operators MAY retry failed jobs. Retrying a job MUST:

- reset the job state to pending
- preserve the original job identity (target_type, target_id)

This prevents the system from creating a second job for the same target.

---

## Job Priority

Processor jobs MUST support priority levels. Recommended priority levels:

- LOW
- NORMAL
- HIGH
- CRITICAL

Workers MUST process higher-priority jobs before lower-priority jobs. If metadata required by scheduling or operator actions is missing for a target, the system MAY escalate the priority of the corresponding job for that target.

---

## Job Creation

Processor jobs MAY be created by:

- catalog reconciliation (one job per target that needs processing: e.g. per new or updated asset)
- operator CLI commands (e.g. “process this collection” enqueues one job per target in the collection)
- metadata demand during runtime

Reconciliation MUST enqueue **one job per target** (e.g. per asset or media) that requires processing, not one job per processor per target. Batch commands resolve to a set of targets and enqueue one job per target.

---

## Job Execution

Processor jobs MUST be executed by workers. The scheduler and catalog reconciliation components MUST NOT execute processors directly. Workers MUST:

- retrieve a job from the queue (by priority)
- hand the job to the processor runtime
- the processor runtime determines which processors must run for that target (from the ProcessorCapabilityContract) and runs them sequentially in a deterministic order
- update job state (completed or failed) when the runtime returns

---

## Worker Coordination

The job queue MUST guarantee that a processor job is executed by only one worker at a time. Workers retrieving jobs MUST acquire exclusive execution of that job before processing begins. This prevents duplicate processing of the same target.

**Job claim strategy:** Workers SHOULD claim jobs using an exclusive acquisition mechanism—e.g. `SELECT ... FOR UPDATE SKIP LOCKED` (or equivalent in the persistence layer)—so that a pending job is locked to one worker and other workers skip it. This avoids thundering herd and ensures exactly-one execution per job.

---

## Idempotency

Processors SHOULD be idempotent. If the same processor runs multiple times for the same target (e.g. on retry), the resulting metadata MUST remain consistent.

---

## Failure Handling

If a processor job fails (e.g. a processor in the sequence fails or the runtime fails):

- the job state MUST be set to failed
- failure details SHOULD be recorded (e.g. which processor failed, error message)

Operators MUST be able to retry failed jobs. Retry re-queues the same target; the runtime will run the same processor sequence again.

---

## Data Model: Jobs, Runs, and Outputs

The processor system separates three concerns in distinct storage:

**processor_jobs** — Queued or in-progress work. One row per target (target_type, target_id). Tracks job state (pending, running, completed, failed), priority, timestamps, and optional error_message. Jobs are mutable: state and timestamps change as work is claimed and completed. When a job is completed or failed, it remains for audit but is no longer "active"; the queue operates on pending and running jobs only.

**processor_runs** — Immutable execution history. One row per processor execution (per processor that ran within a job). Records run_id, job_id, processor_id, target_type, target_id, processor_version, input_fingerprint, status, started_at, completed_at, error_message. Runs are append-only: once written, they are not updated (or only status/timestamps are updated to reflect completion/failure). Defined in detail in the ProcessorExecutionContract.

**processor_outputs** — Metadata produced by processors. Stores the flexible or processor-specific payload (e.g. JSON) keyed by processor_id, target_type, target_id. Defined in the ProcessorMetadataContract.

This separation keeps the queue (jobs) small and focused on work to do; execution history (runs) supports staleness detection, retry history, auditability, and future licensing or reporting; outputs hold the derived metadata.

---

## Observability

The processor job queue MUST provide observable state including:

- queued jobs (by target)
- running jobs
- completed jobs
- failed jobs

Jobs MAY track timestamps such as created_at, started_at, and completed_at to improve observability and debugging. Systems MUST log processor execution events (both job-level and, where applicable, per-processor within a job).
