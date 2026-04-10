# INV-ASSET-LIFECYCLE-COMPLETION-001

**Domain:** ingest

## Plain-language rule

Assets follow a strict state machine: `new` -> `enriching` -> `ready` -> `retired`. Only legal transitions are permitted. `retired` is terminal. The system MUST reject invalid transitions with a clear error.

## Why it exists

Without a state machine, assets can reach `ready` without passing through validation/enrichment, or be silently un-retired. The state machine is the backbone of the ingest trust model.

## What it constrains

- **Entity:** `asset` — `state` field with checked transitions.
- **Service:** auto-approve, `container-ingest-workflow` — must follow legal transition paths.

## Failure mode if violated

Assets bypass validation and reach schedulable state without required checks. Or retired assets silently reappear in pool resolution.
