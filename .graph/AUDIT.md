# Graph maintenance audit (lightweight)

Run after RetroVue contract changes, graph edits, or before a release. Goal: catch **authority drift** and **broken routing**, not to re-derive the whole system.

## Checklist

1. **Ownership (`owns` edges)**  
   - [ ] Each `owns` edge still matches RetroVue authority (who may **write** that artifact or slice).  
   - [ ] No new code path has become a second writer without a graph update or an intentional contract change.

2. **Entity / service stubs**  
   - [ ] Definitions still align with `docs/contracts/` and domain glossaries (especially playlog plan vs runtime playlog).  
   - [ ] “Must NOT” lists are not contradicted by new YAML edges.

3. **Invariants**  
   - [ ] Each `INV-*` stub still points to the right canonical source (`docs/contracts/INVARIANTS.md` + domain contracts).  
   - [ ] YAML `constrained_by` / `forbids` edges for that ID still match the invariant’s intent.

4. **Routing**  
   - [ ] `INDEX.md` still lists the four domains and correct question→domain guidance.  
   - [ ] `LOOKUP.md` includes every entity, service, invariant, and ambiguity file under `.graph/` (add rows when adding nodes).

5. **Ambiguities**  
   - [ ] If product or docs adopted a **single canonical term**, update stub + ambiguity file (or retire the ambiguity with a one-line note in `AUDIT.md` changelog below—not duplicate prose elsewhere).

6. **Relationships**  
   - [ ] `cross-domain.yaml` still reflects execution spine (`playlog` ↔ planning) and planning→AIR `forbids`.  
   - [ ] No forbidden relationship **type** appears in YAML (only: `owns` | `produces` | `consumes` | `drives` | `depends_on` | `constrained_by` | `forbids`).

## Changelog (optional, one line per pass)

| Date | Notes |
|------|-------|
| 2026-04-06 | First full audit pass. 47 YAML edges verified, zero orphans/duplicates. Two invariants (INV-AUTHORITY-SINGLE-OWNER-001, INV-SINGLE-ACTIVATION-PATH-001) flagged as missing from INVARIANTS.md — escalated to Systems Lead. Stale "Collection" terminology fixed in onboarding docs. |
| 2026-04-06 | Post-RETA-11/12 review. Added INV-LIFECYCLE-OBSERVABILITY-001 graph stub + 3 constrained_by edges in playout.yaml. Updated master-clock downstream to include evidence-server (RETA-11 clock injection). LOOKUP.md updated. |
| 2026-04-06 | RETA-52 doc review. Fixed INVARIANTS.md Shared section (missing Derived From column). Added 4 gRPC invariant graph stubs (INV-GRPC-DEADLINE-POLICY-001, INV-GRPC-FEED-BACKPRESSURE-001, INV-GRPC-GRACEFUL-DRAIN-001, INV-GRPC-HEALTH-CHECK-001) + 6 YAML edges in playout.yaml + evidence-server service node + cross-domain edge to master-clock. LOOKUP.md updated with all new entries. New contracts verified: GrpcEvidenceInterfaceContract_v0.1, PlayoutControlHardeningContract_v0.1. ROADMAP_1.0.md reviewed — consistent with completed work. |
| 2026-04-09 | RETA-111 Phase 4.2. Added scheduling-policy entity to LOOKUP.md. Created 5 graph invariant stubs (INV-POLICY-PURE-001, INV-POLICY-LAYERED-001, INV-POLICY-IDEMPOTENT-001, INV-POLICY-DSL-DECLARED-001, INV-POLICY-VIOLATION-STRUCTURED-001) in .graph/invariants/scheduling/. Added 6 YAML edges in scheduling.yaml: depends_on LAW-ELIGIBILITY, consumes asset, constrained_by for all 5 INV-POLICY-* invariants (2 already existed, 3 new + 2 non-constraint edges). LOOKUP.md updated with entity + 5 invariant rows. |
| 2026-04-09 | RETA-129 Phase 6 review. Created 4 invariant stubs in .graph/invariants/ingest/ (INV-TAG-CANONICAL-FORM-001, INV-TAG-MIGRATION-IDEMPOTENT-001, INV-WATCH-DELEGATES-001, INV-WATCH-DEBOUNCE-001). Created source-watch-service service stub in .graph/services/ingest/. Added 8 YAML edges in ingest.yaml (3 constrained_by for tags, 2 depends_on + 3 constrained_by for watch). Updated domains/ingest.md with new service + 4 invariant IDs. LOOKUP.md updated with 1 service + 4 invariant rows. Systems review: 62 contract tests pass, no authority domain overlap, backward compatibility preserved. |
| 2026-04-09 | RETA-134 asset management doc sync. Created 13 invariant stubs in .graph/invariants/ingest/ to close gap between docs/contracts/ and graph: INV-ENRICHER-OBSERVABILITY-001, INV-ENRICHER-RESULT-VERSIONED-001 (were broken links), INV-VALIDATOR-OUTPUT-SHAPE-001, INV-VALIDATOR-RESULT-PERSISTENCE-001, INV-CATALOG-READY-SCHEDULABLE-001, INV-ENRICHER-IDEMPOTENT-001, INV-ENRICHER-EXECUTION-MODE-001, INV-PATH-MAPPING-SOURCE-SCOPED-001, INV-PATH-VALIDATION-ON-IMPORT-001, INV-SOURCE-TYPE-REGISTRY-001, INV-ASSET-LIFECYCLE-COMPLETION-001, INV-ASSET-TAGS-PERSISTED-CORRECTLY-001, INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001. Updated domains/ingest.md key invariants (9 → 20, grouped by concern). Updated domains/scheduling.md key entities to include `pool`. Updated INDEX.md question routing with validator, path-mapping, and watch rows. LOOKUP.md updated with 13 new invariant rows. Operator guide expanded with Scenario 5 (source watch + path mapping) and Scenario 6 (pool management). |
