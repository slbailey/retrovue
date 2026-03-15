# ProcessorCapabilityContract v0.1

## Purpose

Defines how metadata processors operate within RetroVue.

Processors enrich catalog metadata asynchronously.

---

## Processor Declaration

Processors MUST declare:

- id
- target type
- required metadata
- produced metadata
- execution order

Example:

```
processor: ffprobe
target: MEDIA
execution_order: 10
produces:
  duration_ms
  video_codec
  resolution
```

---

## Execution Order

Processors MUST declare an **execution_order**. Processors are executed in **ascending order** of execution_order. The runtime uses this to run processors in a deterministic sequence (e.g. ffprobe → scene detection → loudness → thumbnail generator → AI tagging). Without a declared order, processor sequence would be undefined and could cause subtle bugs.

---

## Target Types

Processors operate on one of:

- **MEDIA**
- **ASSET**

MEDIA processors operate on a single playable file.

ASSET processors operate on logical program metadata.

---

## Processor Invocation

Processors may be triggered by:

1. catalog changes
2. operator commands
3. metadata demand

---

## Batch Operations

Processors MUST support batch execution.

Examples (canonical: use `--container`):

```
processor run ffprobe --container commercials
processor run blackframe --container movies
```

*Compatibility:* `--collection` is deprecated and accepted temporarily during rollout. Batch operations enqueue individual processor jobs.

---

## Job Priority

Processor jobs MAY be assigned a priority level. When metadata required by scheduling or operator requests is not yet available, the system MAY raise the priority of the corresponding processor job. Workers MUST execute higher priority jobs before lower priority jobs.

---

## Asynchronous Execution

Processors MUST run asynchronously via the processor job queue.

Scheduler components MUST NOT execute processor workloads directly.
