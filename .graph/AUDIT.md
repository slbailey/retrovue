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
| *(append rows as you audit)* | |
