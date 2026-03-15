## Container Ingest Implementation Plan

- **Contract Boundary:**  
  `ContainerIngestService` is the **official contract boundary** for container ingest operations.

- **Legacy Components:**  
  The modules in `content_manager/` (including `IngestOrchestrator`) are **considered legacy** and **must NOT** be invoked directly by CLI entrypoints.

- **CLI Behavior:**  
  The CLI command

  ```bash
  retrovue container ingest
  ```

  **MUST** instantiate and invoke **only** `ContainerIngestService`—**never** `IngestOrchestrator` directly.

- **Internal Delegation:**  
  While `ContainerIngestService` **may internally delegate** to `IngestOrchestrator` (for asset traversal, etc.), this is strictly an implementation detail and **outside the CLI contract**.
