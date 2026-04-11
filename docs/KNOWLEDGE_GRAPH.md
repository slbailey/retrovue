# Knowledge graph — agent instructions

The RetroVue **knowledge graph** is under **`.graph/`** at the repository root (contracts-aligned; not a code index). It maps domain boundaries, entities, services, invariants, ambiguities, and relationships.

## Usage

- **Start architectural and system reasoning from `.graph/`** before inferring structure from the source tree or memory.
- Open **`.graph/INDEX.md` first** for domain entry points, question routing, and persona rules; use **`.graph/LOOKUP.md`** for slug → file → relationship YAML hints.
- Follow **domain boundaries and routing** in `INDEX.md` and `domains/*.md`.
- **Do not** substitute assumptions when `.graph/` or **`docs/contracts/`** already defines an entity, service, invariant, or edge.
- **Graph invariants override agent assumptions** for authority and behavior; if implementation or narrative disagrees, treat that as a **defect to surface**.

The graph does **not** replace **`docs/contracts/`**; it **routes** to them.

## Maintenance

Update `.graph/` in lockstep with truth when any of the following occur:

- A **new or materially changed** invariant
- A **new service or entity** that belongs in the model (stub + `LOOKUP.md` + edges)
- A **domain boundary** change
- An **ambiguity** discovered or resolved (`ambiguities/*.md`, `cross-domain.yaml`, or traceable note in `AUDIT.md`)
- **Contract meaning** changes for a component already modeled

**Audits:** Run the checklist in **`.graph/AUDIT.md`** after substantive graph edits, after contract changes that touch modeled components, and before treating an architecture change as release-ready.

**RetroStudio roles** (see **retro-studio** `agents/` and `COMPANY.md` for org context): **documentation-architect** stewards graph integrity; **technical-director** (or delegate) validates graph vs contracts; **producer** (or delegate) ensures Board decisions that affect domains or ownership appear in `.graph/`; **all agents** consult the graph before architecture reasoning.

## Graph-first rule

Before **writing code**, **changing architecture**, or **redefining boundaries** when the change touches components or invariants represented in `.graph/`:

1. **Update or validate `.graph/`** (stubs, YAML, `INDEX.md` / `LOOKUP.md` if routes or slugs change).
2. **Confirm invariants** (graph stubs and **`docs/contracts/`** as source of truth for IDs).
3. **Confirm ownership and relationships** (`owns`, `depends_on`, `consumes`, `forbids`, etc.) match the intended authority model.

**Then** follow the mandatory **Contracts → Invariants → Tests → Code** order defined in **`CLAUDE.md`** (and `server/CLAUDE.md` where applicable). Narrow edits with **no** graph impact may be exempt when that is obvious; when in doubt, run graph-first.
