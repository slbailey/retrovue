# RetroVue Catalog Processing Architecture

## System Overview

RetroVue maintains a catalog of Assets and Media discovered from external Sources. External systems (Plex, Jellyfin, filesystem) are scanned through Containers. The system reconciles discovered media with the catalog and runs processors to enrich metadata.

The pipeline has five stages:

1. **Container discovery** — Enumerate locators from the source.
2. **Catalog reconciliation** — Compare with catalog; create/update/mark unavailable; enqueue jobs.
3. **Job queue** — One job per target; workers drain the queue.
4. **Processor runtime** — Workers run processors sequentially per job; single transaction persist.
5. **Metadata persistence** — Structured tables and processor_outputs; ownership enforced.

---

## Processing Pipeline Diagram

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

(Contracts: ContainerDiscoveryContract → CatalogReconciliationContract → ProcessorJobQueueContract → ProcessorExecutionContract → ProcessorMetadataContract. AssetMediaIdentityContract and ProcessorCapabilityContract define identity and capability rules used across the flow.)

Each stage transforms or enriches information while preserving system invariants. The ProcessorCapabilityContract determines which processors apply to discovered or updated media; processors are selected dynamically, not hard-coded, before jobs are enqueued.

---

## Stage Responsibilities

### Container Discovery

Responsible for enumerating media locators within a container.

Defined by: **ContainerDiscoveryContract**

Outputs a list of locators discovered within the source container.

### Catalog Reconciliation

Responsible for synchronizing discovered locators with catalog records.

Defined by: **CatalogReconciliationContract**

Determines whether media should be created, updated, left unchanged, or marked unavailable.

### Media Identity

Defines how physical media files are uniquely identified.

Defined by: **AssetMediaIdentityContract**

Uses the tuple: `(source_id, container_id, locator)`.

### Processor Job Scheduling

Responsible for scheduling metadata processors when new or updated media is detected.

Defined by: **ProcessorJobQueueContract**

One **job per target** (target_type, target_id) is queued; jobs are executed asynchronously so reconciliation is not blocked. The queue does not store processor_id—the processor runtime selects which processors run for each target when the job is executed.

### Processor Execution

Responsible for running processors that analyze media or assets.

Defined by: **ProcessorExecutionContract**

Workers retrieve a job (target), hand it to the processor runtime. The runtime **loads the target and related metadata once**, builds a **shared ProcessingContext** (target entity, existing metadata, processor outputs, mutable changes), and runs processors **sequentially**; each processor reads from the context and returns structured updates; the runtime **merges** results into the context (no database read or write per processor). After all processors succeed, the runtime **validates ownership rules** and **persists all changes in a single database transaction**. The worker does not need to know processor internals.

### Metadata Storage

Responsible for storing derived metadata produced by processors.

Defined by: **ProcessorMetadataContract**

Metadata ownership rules determine which processors control specific metadata fields.

### Processor Capability System

Processors declare their capabilities through: **ProcessorCapabilityContract**

Capabilities describe:

- which targets processors operate on
- which metadata fields they produce
- which inputs they require

This allows the system to schedule processors automatically.

---

## End-to-End Flow Example

A new video file is added to a filesystem container.

1. ContainerDiscovery discovers the locator.
2. CatalogReconciliation determines the media is new.
3. A new Asset and Media record are created.
4. One processor job per target is enqueued (job identity: target_type, target_id).
5. The system determines which processors apply to each target via ProcessorCapabilityContract when the job runs.
6. Workers pull jobs and hand them to the processor runtime; the runtime runs applicable processors (e.g. ffprobe, loudness) for that target in ascending order of execution_order (ProcessorCapabilityContract).
7. Derived metadata is written to the catalog.

---

## Design Principles

This architecture follows several principles:

- **Deterministic reconciliation** — Repeated reconciliation with unchanged sources produces no catalog changes.
- **Asynchronous metadata enrichment** — Processors run via a job queue; discovery and scheduling are not blocked by processor execution.
- **Processor isolation** — Scheduler and reconciliation do not execute processors directly; workers do.
- **Contract-driven architecture** — Behavior is defined by the core contracts; implementations conform to them.
- **Extensibility through processors** — New enrichment and analysis are added by registering processors and their capabilities.
