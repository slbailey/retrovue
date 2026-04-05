# RetroStudio knowledge graph — primary entry

**Use this file first.** It routes questions to the smallest useful slice of `.graph/`—not the RetroVue source tree.

Semantic model: **RetroVue**, contracts-first. **Node kinds** in YAML: `entity`, `service`, `invariant`, `ambiguity`. Personas are **not** nodes.

**Canonical domains:** `scheduling` · `playout` · `ingest` · `systems`

---

## 1. Domain entry points

Pick **one** domain to open first. Read `domains/<domain>.md` for depth; stay shallow here.

### Scheduling

| | |
|--|--|
| **Start here when the question is about** | What *should* air (editorial intent), daily/grid structure, derivation chains, execution **plan** horizon, EPG as a **display** derivative, traffic/playlist-shaped **outputs** from planning—not runtime bytes. |
| **Responsible for** | `schedule-plan` → `schedule-day` → `transmission-log` → `execution-entry`; **persisted playlog plan** materialization (scheduling-side; see `entities/playout/playlog.md`); zones, programs, channels; `playlist-schedule-manager` (playlist-shaped output, not playlog authority). |
| **Does NOT handle** | Frame timing, encode/mux, AIR, channel activation, viewers, HTTP TS/HLS, “what is on the wire right now,” catalog discovery, asset probing. |

### Playout

| | |
|--|--|
| **Start here when the question is about** | Turning **prefetched** execution artifacts into live playout: `channel-manager`, AIR session, BlockPlan feed, adapters (TS/HLS), segment ring, lifecycle/activation, **runtime** consumption of `playlog` (not rebuilding the schedule). |
| **Responsible for** | Truth chain tail: **playlog** → `channel-manager` → `air-playout-engine`; `program-director`, consumption adapters, `block-plan-producer`, `hls-segmenter`, in-memory HLS (`segment-ring`). |
| **Does NOT handle** | Authoring SchedulePlan/ScheduleDay, EPG-driven **control** of what plays, ingest discovery, cross-cutting **laws** (those live under `systems` pointers). |

### Ingest

| | |
|--|--|
| **Start here when the question is about** | Where **assets** and catalog rows come from, importers, containers/sources, enrichment/probes, eligibility **inputs** to scheduling—not the broadcast grid or playout control. |
| **Responsible for** | `source`, `container`, `discovered-item`, `asset`; `importer`; pipeline/enrichment obligations. |
| **Does NOT handle** | SchedulePlan, zones, EPG, playlog, playlists as execution authority, AIR, HTTP delivery, channel lifecycle. |

### Systems

| | |
|--|--|
| **Start here when the question is about** | **Who may decide what** (single owner per authority), production vs test boundaries, “no ghost methods,” contract discipline, naming collisions, **when the same word means two things**. |
| **Responsible for** | `invariants/systems/*`, `services/systems/master-clock.md` (orchestration timebase authority pointer), `ambiguities/*` as first-class disambiguation. |
| **Does NOT handle** | Concrete schedule rows, concrete playout sessions, concrete asset files—only the **rules** that constrain how those domains are implemented. |

---

## 2. Question routing

For each pattern: **start domain** → then **entities** / **services** / **invariants** (load only what the question needs). Cross-domain only if the answer chain requires it (see §4).

| Question pattern | Start domain | Entities (typical) | Services (typical) | Invariants (typical) |
|------------------|--------------|--------------------|--------------------|----------------------|
| **What should air on channel C at time T (planned / editorial)?** | scheduling | `schedule-plan`, `schedule-day`, `channel`, `program`, `execution-entry`, `transmission-log` | `playlist-schedule-manager` | `INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001` |
| **What does runtime execution consume (not re-plan)?** | playout | `playlog`, `execution-entry`* | `channel-manager`, `block-plan-producer` | `INV-CHANNELMANAGER-NO-PLANNING-001`, `INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001` |
| **How is content executed on the wire / in the engine?** | playout | `block-plan`, `playout-instance` | `air-playout-engine`, `channel-manager`, `playout-session` | (see playout domain list in `domains/playout.md`) |
| **How do viewers get HLS or TS?** | playout | `segment-ring` | `hls-segmenter`, `hls-consumption-adapter`, `ts-consumption-adapter`, `program-director` | `INV-HLS-NO-DISK-IO-001`, `INV-SINGLE-ACTIVATION-PATH-001` |
| **Where do assets come from / what is eligible to schedule?** | ingest | `asset`, `container`, `source`, `discovered-item` | `importer` | `INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001` |
| **Who is allowed to call AIR or extend the plan at runtime?** | systems → then playout/scheduling | — | (infer targets from YAML `forbids` / `constrained_by`) | `INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001`, `INV-CHANNELMANAGER-NO-PLANNING-001`, `INV-AUTHORITY-SINGLE-OWNER-001` |
| **Is this code in the right layer / module class?** | systems | — | — | `INV-PRODUCTION-BOUNDARY-001`, `INV-NO-GHOST-METHODS-001` |

\*`execution-entry` is a **scheduling** entity; load it from scheduling when you need **plan** semantics, or follow `relationships/cross-domain.yaml` (`playlog` → `execution-entry`) when tracing the spine from playout.

---

## 3. Persona routing (agent types)

Use this to **minimize** context. “Unless bridging” = only when a question explicitly spans domains or YAML points across the seam.

| Agent type | SHOULD load | MUST NOT load (unless bridging) |
|------------|-------------|----------------------------------|
| **Scheduling-focused** | `domains/scheduling.md`, `entities/scheduling/`, `services/scheduling/`, `invariants/scheduling/`, `relationships/by-domain/scheduling.yaml`, `relationships/cross-domain.yaml` (execution-spine + forbids edges only) | Playout internals: `segment-ring`, `hls-segmenter`, `hls-consumption-adapter`, `ts-consumption-adapter`, `air-playout-engine`, BlockPlan/AIR gRPC detail; full `entities/playout/` except `playlog` / `playlist` stubs when tracing the plan→playlog handoff |
| **Playout-focused** | `domains/playout.md`, `entities/playout/`, `services/playout/`, `invariants/playout/`, `relationships/by-domain/playout.yaml`, `relationships/cross-domain.yaml` | Ingest: `importer`, probe/enrichment pipelines; scheduling: break/traffic DSL depth, full derivation math—pull only `execution-entry` / schedule stubs if the question is the execution spine |
| **Ingest-focused** | `domains/ingest.md`, `entities/ingest/`, `services/ingest/`, `invariants/ingest/`, `relationships/by-domain/ingest.yaml` | BlockPlan, AIR, HLS segment ring, `channel-manager`, `program-director` session details |
| **Systems-focused** | `domains/systems.md`, `invariants/systems/`, `services/systems/`, `relationships/by-domain/systems.yaml`, relevant `ambiguities/*` | Entire subgraphs of scheduling/playout/ingest **unless** the question is about their interaction; then use YAML + one domain file’s boundary table only |

---

## 4. Graph navigation rules

1. **Always start in one domain** (§1). Open that domain’s `domains/<domain>.md` before wandering into entities.
2. **Do not cross domains** until the question or a **relationship edge** requires it (e.g. `playlog` → `execution-entry` in `cross-domain.yaml`).
3. **Follow relationships, not the file tree.** Use `relationships/by-domain/*.yaml` for intra-domain edges; **merge** `relationships/cross-domain.yaml` for seams (planning↔playout, eligibility, ambiguities).
4. **Invariants override assumptions.** If prose in an entity stub conflicts with an `INV-*` file or a YAML `constrained_by` / `forbids`, the invariant wins; refresh the stub in a later maintenance pass if needed.
5. **Prefer reverse lookup:** from a slug, scan YAML for edges **to**/**from** that id rather than loading all markdown.
6. **Truth chain for execution** (broadcast-accurate): scheduling plan → `playlog` → `channel-manager` → AIR—do not treat `playlist` as the root (see `domains/playout.md`).

---

## 5. Known ambiguities

Check these **when** the symptom matches the trigger—avoid loading all ambiguity files by default.

| Ambiguity file | When to check | What confusion it resolves |
|----------------|---------------|----------------------------|
| `ambiguities/dual-meaning-producer.md` | “Producer” appears in Core vs AIR vs adapter context | Core feeder vs AIR decode “producer” vs naming overlap |
| `ambiguities/schedule-manager-vs-playlist-schedule-manager.md` | “Schedule manager,” “traffic,” or playlist **as authority** | Architectural traffic role vs concrete `playlist-schedule-manager`; playlist-shaped output vs `playlog` spine |
| `ambiguities/collection-vs-container.md` | “Collection” vs “container” in ingest vs scheduling | Ingest **container** vs scheduling **zone** vs legacy “collection” wording |
| `ambiguities/program-director-import-alias.md` | Import named `program_director` vs runtime supervisor | Protocol re-export vs product `ProgramDirector` service |

---

## 6. Relationship usage rules

**Files:** `relationships/by-domain/<domain>.yaml` hold **within-domain** and tightly coupled playout edges. **`relationships/cross-domain.yaml`** is mandatory glue: execution spine (`playlog` ↔ planning), planning→AIR **forbids**, ingest↔scheduling hints, ambiguity anchors.

**Types** (only these exist in YAML):

| Type | Meaning | Direction |
|------|---------|-----------|
| `owns` | Exclusive writer / authority over that artifact slice (use sparingly; see YAML `note:`) | owner → owned |
| `produces` | Creates or emits an artifact | producer → artifact |
| `consumes` | Reads artifact as primary input | consumer → artifact |
| `drives` | Causes or commands another service | driver → driven |
| `depends_on` | Requires the other to exist or be true first | dependent → dependency |
| `constrained_by` | Must obey the invariant | subject → `INV-*` |
| `forbids` | Hard prohibition between nodes | from → to (see note on edge) |

**Combining files:** Merge **all** relevant `by-domain` files for domains in scope, **plus** `cross-domain.yaml`. When two files mention the same pair, **one semantic edge**—prefer the more specific `note:` if present.

**IDs:** Entity/service slugs (`channel-manager`, `playlog`) or full `INV-*` for invariants.

---

## Quick paths (file open order)

| Goal | Open |
|------|------|
| Domain overview | `domains/<domain>.md` |
| Slug → path + domain + YAML hints | `LOOKUP.md` |
| Edges for one slug | Grep or scan `relationships/**/*.yaml` for `id: <slug>` |
| Invariant text | `invariants/<domain>/INV-*.md` |
| Disambiguation | `ambiguities/*.md` per §5 |
| Maintainer pass | `AUDIT.md` |

---

## What not to load (global)

- **RetroVue source** (`pkg/core/...`, `pkg/air/...`) for everyday architecture questions—use this graph + RetroVue `docs/contracts/`.
- **Proto / generated stubs** unless changing the Core↔AIR API.
- **Full `INVARIANTS.md`** table unless verifying an ID string—prefer the single `invariants/*/INV-*.md` stub here.

---

## Maintenance

When RetroVue contracts change, update affected stubs and YAML edges, then run the checklist in `AUDIT.md`. This graph is **not** auto-generated.
