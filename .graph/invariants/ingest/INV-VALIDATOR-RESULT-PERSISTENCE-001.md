# INV-VALIDATOR-RESULT-PERSISTENCE-001

**Domain:** ingest

## Plain-language rule

Validator results MUST be persistable and round-trip safely: serialize to plain dict, deserialize back to the same canonical shape with no data loss.

## Why it exists

Persistence enables audit trails, re-validation comparisons, and operator access to historical validation results. Without round-trip safety, stored results silently lose fields on deserialization.

## What it constrains

- **Service:** `ValidationResultStore` — serialization/deserialization must preserve exact shape.
- **Entity:** `asset` — validation history is queryable.

## Failure mode if violated

Historical validation results are corrupted or incomplete. Operators cannot trace why an asset was accepted or rejected.
