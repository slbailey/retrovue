# INV-PATH-VALIDATION-ON-IMPORT-001

**Domain:** ingest

## Plain-language rule

At container import time, sample asset paths MUST be validated against effective path mappings. All paths failing = hard error. Partial failure = warning + proceed. Actionable diagnostics (missing prefixes, suggested mappings) are included.

## Why it exists

Without import-time validation, broken path mappings produce assets with unresolvable URIs that fail silently at playout time — hours or days after ingest.

## What it constrains

- **Service:** `container-ingest-workflow` — must call path validation before persisting assets.
- **Entity:** `asset` — URI correctness depends on path mapping resolution.

## Failure mode if violated

Assets with broken paths reach `ready` state and fail at playout time. Operator discovers the problem only when a channel goes dark.
