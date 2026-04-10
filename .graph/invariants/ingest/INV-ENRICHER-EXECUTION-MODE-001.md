# INV-ENRICHER-EXECUTION-MODE-001

**Domain:** ingest

## Plain-language rule

Every enricher MUST declare exactly one execution mode: IMMEDIATE (inline during state transition), LAZY_ON_ACCESS (triggered on first field access), or BACKGROUND (queued for worker execution). The mode is validated at enricher class construction.

## Why it exists

Without declared execution modes, enricher dispatch is ad-hoc — some enrichers block import, others silently skip. Explicit modes enable predictable behavior: operators know which enrichers run inline and which run asynchronously.

## What it constrains

- **Service:** all enrichers via `DomainEnricher.__init_subclass__()` — rejects undeclared or invalid modes.
- **Service:** `container-ingest-workflow` — dispatches enrichers by mode.

## Failure mode if violated

Import hangs because a slow enricher was not marked BACKGROUND. Or a critical enricher was incorrectly marked BACKGROUND and assets reach `ready` without required metadata.
