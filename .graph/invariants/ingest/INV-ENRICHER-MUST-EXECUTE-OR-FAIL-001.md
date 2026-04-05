# INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001

**Domain:** ingest

## Plain-language rule

If an enricher is **supposed to run** for a job (registry resolves a processor), it must **run successfully** or leave a **visible failure record**—never a silent skip.

## Why it exists

Missing metadata (e.g. interstitial type) poisons **scheduling and traffic** decisions while looking like success. Surfaces failures as **planning faults** with evidence.

## What it constrains

- **Service:** `importer` / processor pipeline orchestration.
- **Entity:** `asset` readiness and derived scheduling eligibility.

## Failure mode if violated

Assets reach “ready” with **wrong or missing** editorial fields; downstream scheduling breaks in ways that are **hard to debug** and non-reproducible.
