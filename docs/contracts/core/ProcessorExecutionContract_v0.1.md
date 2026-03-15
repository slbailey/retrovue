# ProcessorExecutionContract v0.1

## Purpose

This contract governs the execution of metadata processors by workers. Processors are executed asynchronously and are triggered by jobs in the processor job queue. It defines the runtime interface between workers, processor implementations, and metadata storage.

---

## Definitions

**Processor**  
A metadata enrichment component defined by the ProcessorCapabilityContract. Processors analyze media or assets and produce derived metadata.

**Processor Job**  
A request to execute a processor against a specific target. Processor jobs are defined in the ProcessorJobQueueContract.

**Worker**  
A runtime component responsible for executing processor jobs. Workers retrieve jobs from the processor job queue and execute processors according to this contract.

**Processor Result**  
The output produced by a processor after execution. Results may include derived metadata fields or analysis results.

---

## Processor Invocation

Workers execute processors by providing:

- processor_id
- target_type
- target_id

Where target_type is ASSET or MEDIA. Processors MUST receive sufficient information to retrieve the target entity and any required metadata.

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

## Processor Inputs

Processors MAY access the following inputs:

- target identifier (asset_id or media_id)
- locator information
- source metadata
- previously derived metadata
- sidecar metadata associated with the target

Processors MUST NOT modify catalog entities directly. Processors return results which are applied by the processor runtime.

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

Processor results MUST be validated against the ProcessorMetadataContract before being applied to the catalog. If validation fails:

- the processor job MUST be marked as failed
- no metadata changes MUST be applied

This prevents corrupt metadata from breaking the catalog.

---

## Metadata Application

Processor results MUST be applied to the catalog according to metadata ownership rules defined in the ProcessorMetadataContract. Processors MUST NOT overwrite operator-managed metadata.

---

## Metadata Write Semantics

Processor outputs MUST represent the complete set of metadata fields produced by the processor. The processor runtime MUST update only the metadata fields owned by that processor. This ensures processors cannot accidentally delete metadata owned by other processors.

---

## Processor Idempotency

Processors SHOULD be idempotent. Running the same processor multiple times against the same target MUST produce consistent metadata results.

---

## Processor Failure

If a processor execution fails:

- the processor job MUST be marked as failed
- failure details SHOULD be recorded
- the processor MUST NOT modify metadata

Workers MAY retry processor jobs according to queue policies.

---

## Execution Time Limits

Processor execution MAY be subject to runtime limits defined by the processor runtime. If execution exceeds the allowed runtime:

- the processor execution MUST be terminated
- the processor job MUST be marked as failed

This protects the worker pool from hanging processors.

---

## Execution Isolation

Processor execution MUST be isolated from the scheduler and catalog reconciliation systems. Processor failures MUST NOT interrupt scheduler operation.

---

## Observability

Processor execution MUST produce observable events including:

- processor started
- processor completed
- processor failed

Execution duration SHOULD be recorded.
