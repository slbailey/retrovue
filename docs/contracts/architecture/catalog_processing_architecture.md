# RetroVue Catalog Processing Architecture

## System Overview

RetroVue maintains a catalog of Assets and Media discovered from external Sources. External systems (Plex, Jellyfin, filesystem) are scanned through Containers. The system reconciles discovered media with the catalog and runs processors to enrich metadata.

The architecture separates:

- discovery
- reconciliation
- job orchestration
- processor execution
- metadata storage

---

## Processing Pipeline Diagram

```
External Source
     │
     ▼
ContainerDiscoveryContract
     │
     ▼
CatalogReconciliationContract
     │
     ▼
AssetMediaIdentityContract
     │
     ▼
ProcessorCapabilityContract
     │
     ▼
ProcessorJobQueueContract
     │
     ▼
ProcessorExecutionContract
     │
     ▼
ProcessorMetadataContract
```

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

Processor jobs are queued asynchronously to avoid blocking catalog reconciliation.

### Processor Execution

Responsible for running processors that analyze media or assets.

Defined by: **ProcessorExecutionContract**

Workers retrieve processor jobs and execute processors through the processor runtime. The runtime loads the processor, passes execution context, validates results, and writes metadata; the worker does not need to know processor internals.

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
4. The system determines which processors apply (via ProcessorCapabilityContract).
5. Processor jobs (such as ffprobe) are enqueued.
6. Workers execute processors through the processor runtime.
7. Derived metadata is written to the catalog.

---

## Design Principles

This architecture follows several principles:

- **Deterministic reconciliation** — Repeated reconciliation with unchanged sources produces no catalog changes.
- **Asynchronous metadata enrichment** — Processors run via a job queue; discovery and scheduling are not blocked by processor execution.
- **Processor isolation** — Scheduler and reconciliation do not execute processors directly; workers do.
- **Contract-driven architecture** — Behavior is defined by the core contracts; implementations conform to them.
- **Extensibility through processors** — New enrichment and analysis are added by registering processors and their capabilities.
