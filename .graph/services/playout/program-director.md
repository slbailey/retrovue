# ProgramDirector

**Domain:** playout  
**Slug:** `program-director`

## Responsibility

Top-level **runtime supervisor**: HTTP surface for channels, routes viewer-driven activation through the **single** channel lifecycle entry point, coordinates diagnostics for HLS as contracted.

## Owns vs reads

- **Owns:** channel lifecycle **registry** decisions (activation/teardown policy), HTTP routing to adapters, correlation-friendly structured lifecycle logging expectations.
- **Reads:** configuration, clock, channel manager factory/provider patterns per runtime design.

## Upstream inputs

HTTP clients, configuration, internal references to per-channel `channel-manager` (conceptually).

## Downstream outputs

TS/HLS responses, logs, activation of `channel-manager` via `start_channel` (sole path—`INV-SINGLE-ACTIVATION-PATH-001`).

## Must NOT do

- Bypass `start_channel()` with a parallel activation path inside adapters.
- Implement frame timing or encoding (AIR).

## Ambiguity

See `ambiguities/program-director-import-alias.md` (import names vs this conceptual service).
