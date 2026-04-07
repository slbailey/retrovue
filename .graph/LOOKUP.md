# Slug / id → file lookup

Fast navigation: **id** → **kind** → **file** → **domain** → **relationship YAML** (likely).  
Always merge `relationships/cross-domain.yaml` when tracing cross-domain seams.

**Convention:** paths are relative to `.graph/`.

---

## Domains (conceptual; not YAML nodes)

| id | kind | canonical file | domain | relationship file(s) |
|----|------|----------------|--------|----------------------|
| scheduling | domain | `domains/scheduling.md` | scheduling | `relationships/by-domain/scheduling.yaml`, `relationships/cross-domain.yaml` |
| playout | domain | `domains/playout.md` | playout | `relationships/by-domain/playout.yaml`, `relationships/by-domain/systems.yaml`, `relationships/cross-domain.yaml` |
| ingest | domain | `domains/ingest.md` | ingest | `relationships/by-domain/ingest.yaml`, `relationships/cross-domain.yaml` |
| systems | domain | `domains/systems.md` | systems | `relationships/by-domain/systems.yaml`, `relationships/cross-domain.yaml` |

---

## Entities

| id | kind | canonical file | domain | relationship file(s) |
|----|------|----------------|--------|----------------------|
| schedule-plan | entity | `entities/scheduling/schedule-plan.md` | scheduling | `by-domain/scheduling.yaml` |
| schedule-day | entity | `entities/scheduling/schedule-day.md` | scheduling | `by-domain/scheduling.yaml` |
| zone | entity | `entities/scheduling/zone.md` | scheduling | `by-domain/scheduling.yaml`, `cross-domain.yaml` (ambiguity) |
| channel | entity | `entities/scheduling/channel.md` | scheduling | `by-domain/scheduling.yaml` |
| program | entity | `entities/scheduling/program.md` | scheduling | `by-domain/scheduling.yaml`, `cross-domain.yaml` |
| execution-entry | entity | `entities/scheduling/execution-entry.md` | scheduling | `by-domain/scheduling.yaml`, `cross-domain.yaml` |
| transmission-log | entity | `entities/scheduling/transmission-log.md` | scheduling | `by-domain/scheduling.yaml` |
| epg | entity | `entities/scheduling/epg.md` | scheduling | `by-domain/scheduling.yaml` |
| playlog | entity | `entities/playout/playlog.md` | playout | `by-domain/playout.yaml`, `cross-domain.yaml` |
| playlist | entity | `entities/playout/playlist.md` | playout | `by-domain/scheduling.yaml` |
| segment-ring | entity | `entities/playout/segment-ring.md` | playout | `by-domain/playout.yaml`, `by-domain/systems.yaml` |
| block-plan | entity | `entities/playout/block-plan.md` | playout | `by-domain/playout.yaml` |
| playout-instance | entity | `entities/playout/playout-instance.md` | playout | *(edges via prose / AIR; sparse YAML)* |
| source | entity | `entities/ingest/source.md` | ingest | `by-domain/ingest.yaml` |
| container | entity | `entities/ingest/container.md` | ingest | `by-domain/ingest.yaml`, `cross-domain.yaml` (ambiguity) |
| discovered-item | entity | `entities/ingest/discovered-item.md` | ingest | `by-domain/ingest.yaml` |
| asset | entity | `entities/ingest/asset.md` | ingest | `by-domain/ingest.yaml`, `cross-domain.yaml` |
| production-server | entity | `entities/systems/production-server.md` | systems | — |

---

## Services

| id | kind | canonical file | domain | relationship file(s) |
|----|------|----------------|--------|----------------------|
| playlist-schedule-manager | service | `services/scheduling/playlist-schedule-manager.md` | scheduling | `by-domain/scheduling.yaml`, `cross-domain.yaml` |
| program-director | service | `services/playout/program-director.md` | playout | `by-domain/playout.yaml`, `by-domain/systems.yaml` |
| channel-manager | service | `services/playout/channel-manager.md` | playout | `by-domain/playout.yaml`, `by-domain/systems.yaml` |
| hls-consumption-adapter | service | `services/playout/hls-consumption-adapter.md` | playout | `by-domain/playout.yaml` |
| ts-consumption-adapter | service | `services/playout/ts-consumption-adapter.md` | playout | `by-domain/playout.yaml` |
| hls-segmenter | service | `services/playout/hls-segmenter.md` | playout | `by-domain/playout.yaml`, `by-domain/systems.yaml` |
| block-plan-producer | service | `services/playout/block-plan-producer.md` | playout | `by-domain/playout.yaml`, `cross-domain.yaml` (ambiguity) |
| playout-session | service | `services/playout/playout-session.md` | playout | `by-domain/playout.yaml` |
| air-playout-engine | service | `services/playout/air-playout-engine.md` | playout | `by-domain/playout.yaml`, `cross-domain.yaml`, `by-domain/systems.yaml` |
| importer | service | `services/ingest/importer.md` | ingest | `by-domain/ingest.yaml`, `by-domain/systems.yaml` |
| source-ingest-workflow | service | `services/ingest/source-ingest-workflow.md` | ingest | `by-domain/ingest.yaml` |
| container-ingest-workflow | service | `services/ingest/container-ingest-workflow.md` | ingest | `by-domain/ingest.yaml` |
| evidence-server | service | `services/playout/evidence-server.md` | playout | `by-domain/playout.yaml`, `cross-domain.yaml` |
| master-clock | service | `services/systems/master-clock.md` | systems | `by-domain/systems.yaml` |

---

## Invariants

| id | kind | canonical file | domain | relationship file(s) |
|----|------|----------------|--------|----------------------|
| INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001 | invariant | `invariants/scheduling/INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001.md` | scheduling | `by-domain/scheduling.yaml`, `cross-domain.yaml` |
| INV-SINGLE-ACTIVATION-PATH-001 | invariant | `invariants/playout/INV-SINGLE-ACTIVATION-PATH-001.md` | playout | `by-domain/playout.yaml` |
| INV-CHANNELMANAGER-NO-PLANNING-001 | invariant | `invariants/playout/INV-CHANNELMANAGER-NO-PLANNING-001.md` | playout | `by-domain/playout.yaml` |
| INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001 | invariant | `invariants/playout/INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001.md` | playout | `by-domain/playout.yaml` |
| INV-HLS-NO-DISK-IO-001 | invariant | `invariants/playout/INV-HLS-NO-DISK-IO-001.md` | playout | `by-domain/playout.yaml` |
| INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001 | invariant | `invariants/ingest/INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001.md` | ingest | `by-domain/ingest.yaml` |
| INV-CLI-NO-BUSINESS-LOGIC-001 | invariant | `invariants/systems/INV-CLI-NO-BUSINESS-LOGIC-001.md` | systems | `by-domain/ingest.yaml` |
| INV-API-NO-BUSINESS-LOGIC-001 | invariant | `invariants/systems/INV-API-NO-BUSINESS-LOGIC-001.md` | systems | `by-domain/ingest.yaml` |
| INV-WORKFLOW-FLAT-NESTING-001 | invariant | `invariants/systems/INV-WORKFLOW-FLAT-NESTING-001.md` | systems | `by-domain/ingest.yaml` |
| INV-AUTHORITY-SINGLE-OWNER-001 | invariant | `invariants/systems/INV-AUTHORITY-SINGLE-OWNER-001.md` | systems | `by-domain/systems.yaml` |
| INV-NO-GHOST-METHODS-001 | invariant | `invariants/systems/INV-NO-GHOST-METHODS-001.md` | systems | `by-domain/systems.yaml` |
| INV-LIFECYCLE-OBSERVABILITY-001 | invariant | `invariants/playout/INV-LIFECYCLE-OBSERVABILITY-001.md` | playout | `by-domain/playout.yaml` |
| INV-PRODUCTION-BOUNDARY-001 | invariant | `invariants/systems/INV-PRODUCTION-BOUNDARY-001.md` | systems | `by-domain/systems.yaml` |
| INV-GRPC-DEADLINE-POLICY-001 | invariant | `invariants/playout/INV-GRPC-DEADLINE-POLICY-001.md` | playout | `by-domain/playout.yaml` |
| INV-GRPC-FEED-BACKPRESSURE-001 | invariant | `invariants/playout/INV-GRPC-FEED-BACKPRESSURE-001.md` | playout | `by-domain/playout.yaml` |
| INV-GRPC-GRACEFUL-DRAIN-001 | invariant | `invariants/playout/INV-GRPC-GRACEFUL-DRAIN-001.md` | playout | `by-domain/playout.yaml` |
| INV-GRPC-HEALTH-CHECK-001 | invariant | `invariants/playout/INV-GRPC-HEALTH-CHECK-001.md` | playout | `by-domain/playout.yaml` |

---

## Ambiguities

| id | kind | canonical file | domain | relationship file(s) |
|----|------|----------------|--------|----------------------|
| dual-meaning-producer | ambiguity | `ambiguities/dual-meaning-producer.md` | systems | `cross-domain.yaml` |
| schedule-manager-vs-playlist-schedule-manager | ambiguity | `ambiguities/schedule-manager-vs-playlist-schedule-manager.md` | systems | `cross-domain.yaml` |
| collection-vs-container | ambiguity | `ambiguities/collection-vs-container.md` | systems | `cross-domain.yaml` |
| program-director-import-alias | ambiguity | `ambiguities/program-director-import-alias.md` | systems | `cross-domain.yaml` |
