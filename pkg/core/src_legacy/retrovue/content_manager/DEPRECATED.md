# Deprecated Orchestration Layer

> **Note:**  
> This directory contains **legacy ingest orchestration logic** (e.g. `IngestOrchestrator`).

---

## Guidance for New Development

- **Do NOT call this layer directly from new ingest commands.**
- **All new ingest flows must invoke**  
  [`CollectionIngestService`](../../cli/commands/_ops/collection_ingest_service.py).

---

## Internal Usage

While `IngestOrchestrator` may still be used _internally_ by `CollectionIngestService`,  
**it is no longer the contract boundary**  
and should **not be imported by CLI entrypoints** moving forward.
