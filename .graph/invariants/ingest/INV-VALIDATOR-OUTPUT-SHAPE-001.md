# INV-VALIDATOR-OUTPUT-SHAPE-001

**Domain:** ingest

## Plain-language rule

Every validator run MUST produce a structured result with canonical shape: top-level `status` (validated/failed), `errors` list, `warnings` list, and per-validator status map. Each error/warning includes a machine-readable `code`, originating `validator` name, and human-readable `message`.

## Why it exists

Without a canonical output shape, downstream consumers (persistence, diagnostics, operator CLI) must each parse ad-hoc formats. Changing a validator's output silently breaks diagnostics and the operator experience.

## What it constrains

- **Service:** all validators in the validation pipeline must return `ValidationResult` with the canonical shape.
- **Entity:** `asset` — validator results drive state transitions (validated/failed).

## Failure mode if violated

Operator CLI shows garbled or missing error details. Auto-approve may silently pass assets that should fail.
