# ProcessorJobQueueContract v0.1

## Purpose

This contract governs the lifecycle and execution behavior of processor jobs. The processor job queue enables asynchronous metadata enrichment and isolates processor workloads from the scheduler and catalog reconciliation.

---

## Definitions

**Processor**  
A metadata enrichment component defined by the ProcessorCapabilityContract.

**Processor Job**  
A single request to execute a processor against a target entity.

Examples:
- ffprobe(media_id=42)
- ai_genre_tagger(asset_id=18)

**Target**  
The entity a processor operates on. Possible targets: MEDIA, ASSET.

**Worker**  
A runtime component responsible for executing processor jobs from the queue.

---

## Job Identity

A processor job MUST be uniquely identified by:

```
(processor_id, target_type, target_id)
```

Where target_type is either ASSET or MEDIA and target_id is the identifier of the target entity.

---

## Job Deduplication

If a processor job is requested for an identity that already exists in the queue:

- the system MUST NOT create a duplicate job
- the existing job MAY have its priority escalated
- the existing job state MUST NOT be reset

This guarantees deterministic queue behavior.

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

Failed jobs MAY be retried.

---

## Job Retry

Operators MAY retry failed jobs. Retrying a job MUST:

- reset the job state to pending
- preserve the original job identity

This prevents the system from creating a second job for the same target.

---

## Job Priority

Processor jobs MUST support priority levels. Recommended priority levels:

- LOW
- NORMAL
- HIGH
- CRITICAL

Workers MUST process higher-priority jobs before lower-priority jobs. If metadata required by scheduling or operator actions is missing, the system MAY escalate the priority of the corresponding processor job.

---

## Job Creation

Processor jobs MAY be created by:

- catalog reconciliation
- operator CLI commands
- metadata demand during runtime

Batch processor commands MUST enqueue individual jobs for each target. Example: `processor run ffprobe --collection commercials` resolves the collection to multiple targets and enqueues a job for each.

---

## Job Execution

Processor jobs MUST be executed by workers. The scheduler and catalog reconciliation components MUST NOT execute processors directly. Workers MUST:

- retrieve a job from the queue
- execute the processor
- update job state

---

## Worker Coordination

The job queue MUST guarantee that a processor job is executed by only one worker at a time. Workers retrieving jobs MUST acquire exclusive execution of that job before processing begins. This prevents duplicate processor execution.

---

## Idempotency

Processors SHOULD be idempotent. If the same processor runs multiple times for the same target, the resulting metadata MUST remain consistent.

---

## Failure Handling

If a processor job fails:

- the job state MUST be set to failed
- failure details SHOULD be recorded

Operators MUST be able to retry failed jobs.

---

## Observability

The processor job queue MUST provide observable state including:

- queued jobs
- running jobs
- completed jobs
- failed jobs

Jobs MAY track timestamps such as created_at, started_at, and completed_at to improve observability and debugging. Systems MUST log processor execution events.
