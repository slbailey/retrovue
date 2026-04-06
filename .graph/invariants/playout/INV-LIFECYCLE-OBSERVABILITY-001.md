# INV-LIFECYCLE-OBSERVABILITY-001

**Domain:** playout

## Plain-language rule

Runtime lifecycle transitions must emit **structured** log events at **DEBUG** level. Every viewer session must carry a correlation ID (`session_id`) traceable end-to-end through PD activation → ChannelManager → HLS phantom tracking → segments.

## Why it exists

Without structured, correlation-ID-tagged events, tracing a viewer session through logs is guesswork. Silent lifecycle transitions and free-form strings make production debugging impossible.

## What it constrains

- **Services:** `program-director`, `channel-manager`, `hls-consumption-adapter` — any component handling lifecycle state transitions or viewer session tracking.
- **Required events:** channel activation, first segment produced, viewer join, viewer leave, linger start, linger expire, teardown.

## Failure mode if violated

Untraceable viewer sessions, invisible lifecycle state changes, incident response reduced to log grepping free-form strings.

## Note

Full authoritative prose lives in RetroVue root `CLAUDE.md` (observability rule) and `docs/contracts/invariants/core/runtime/INV-LIFECYCLE-OBSERVABILITY-001.md`. This file is the graph's actionable summary.
