## Collection Ingest Implementation Plan

- **Contract Boundary:**  
  `CollectionIngestService` is the **official contract boundary** for collection ingest operations.

- **Legacy Components:**  
  The modules in `content_manager/` (including `IngestOrchestrator`) are **considered legacy** and **must NOT** be invoked directly by CLI entrypoints.

- **CLI Behavior:**  
  The CLI command

  ```bash
  retrovue collection ingest
  ```

  **MUST** instantiate and invoke **only** `CollectionIngestService`—**never** `IngestOrchestrator` directly.

- **Internal Delegation:**  
  While `CollectionIngestService` **may internally delegate** to `IngestOrchestrator` (for asset traversal, etc.), this is strictly an implementation detail and **outside the CLI contract**.
