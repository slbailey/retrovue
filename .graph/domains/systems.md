# Domain: systems

## Purpose

**Cross-cutting rules** that are not “what airs” or “how bytes emit,” but **how the architecture must behave**: single ownership of concerns, contract discipline, code placement, and timebase authority for orchestration.

## Responsibilities

- Encode **authority domains** so exactly one component **writes** each class of decision (orchestration clock, HLS window, channel lifecycle, diagnostics as contracted).
- Encode **engineering laws** (no ghost methods, no test mocks in production modules) that keep the codebase auditable.
- Provide the conceptual home for **disambiguation** when the same word means two things (see `ambiguities/`).

## What this domain owns

- Invariant and law **interpretation** in this graph (pointers to RetroVue `docs/contracts/`).
- Named **systems services** that exist solely as cross-cutting authorities (e.g. orchestration clock).

## What this domain does NOT own (critical)

- Editorial content or grid math (**scheduling**).
- Playback sessions or AIR (**playout**).
- Files and catalog records (**ingest**).

## Boundaries vs other domains

| Adjacent domain | Boundary |
|-----------------|----------|
| **All** | Systems invariants **constrain** how scheduling, ingest, and playout are implemented; they do not replace domain truth in those areas. |

## Key entities (slugs)

*(none in skeleton; optional future stubs for “law” nodes if the graph is extended)*

## Key services (slugs)

`master-clock`

## Key invariants (IDs)

`INV-AUTHORITY-SINGLE-OWNER-001`, `INV-NO-GHOST-METHODS-001`, `INV-PRODUCTION-BOUNDARY-001`
